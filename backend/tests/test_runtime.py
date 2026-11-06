"""Isolated PostgreSQL + real local HTTP/MCP contracts; never calls paid providers."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from test_local_flow import client, cloud_contract, configure, upload, publish
from app import db, telemetry as obs


def wait_run(client, rid, statuses=('succeeded','failed','waiting_approval','cancelled','paused')):
    for _ in range(150):
        result = client.get('/api/runs/' + rid)
        assert result.status_code == 200, result.text
        data = result.json()
        if data['run']['status'] in statuses: return data
        time.sleep(.05)
    raise AssertionError('run did not finish: ' + str(data))


def app(client, value, aid='test-app'):
    result=client.put('/api/applications/'+aid,json=value)
    assert result.status_code==200,result.text
    return result.json()


def flow_app(nodes=None,edges=None):
    return {'name':'真实流程测试','type':'chatflow','kbIds':[],'flow':{'nodes':nodes or [{'id':'start','type':'start','name':'开始'},{'id':'text','type':'template','name':'模板','template':'已收到：{{input.question}}'},{'id':'end','type':'end','name':'输出','template':'{{text.output}}'}], 'edges':edges or [{'source':'start','target':'text'},{'source':'text','target':'end'}]}}


def test_flow_version_trace_permissions_and_metrics(client):
    value=flow_app(); app(client,value)
    assert client.post('/api/applications/test-app/validate').json()['valid']
    version=client.post('/api/applications/test-app/publish').json()['versionId']
    value['flow']['nodes'][1]['template']='未发布的修改'
    app(client,value)
    run=client.post('/api/applications/test-app/runs',json={'input':{'question':'版本固定'}}).json()
    detail=wait_run(client,run['id'])
    assert detail['run']['status']=='succeeded',detail
    assert detail['run']['output']=='已收到：版本固定'
    assert detail['run']['versionId']==version and len(detail['spans'])==3
    assert any(s.get('attributes',{}).get('contextBefore') for s in detail['spans'])
    code=client.get('/api/runs/'+run['id']+'/implementation?kind=node')
    assert code.status_code==200 and 'async def flow' in code.json()['source']
    assert client.get('/api/runs/'+run['id']+'/implementation?kind=node',headers={'X-Role':'user','X-Browser-Id':'other'}).status_code==404
    assert client.get('/api/runs/'+run['id'],headers={'X-Role':'user','X-Browser-Id':'other'}).status_code==404
    assert client.get('/api/observability/summary').json()['succeeded']==1
    assert client.get('/api/observability/runs?export=true').headers['content-type'].startswith('text/csv')
    assert len(client.get('/api/applications/test-app/versions').json())==1


def test_flow_validation_branch_and_approval_resume(client):
    value=flow_app([{'id':'start','type':'start','name':'开始'},{'id':'gate','type':'condition','name':'判断','value':'{{input.question}}','equals':'yes'},{'id':'approve','type':'approval','name':'确认','value':'允许'},{'id':'deny','type':'template','name':'拒绝','template':'不匹配'},{'id':'end','type':'end','name':'输出','template':'{{approve.output}}'},{'id':'end_no','type':'end','name':'输出否','template':'{{deny.output}}'}],[{'source':'start','target':'gate'},{'source':'gate','target':'approve','condition':'true'},{'source':'gate','target':'deny','condition':'false'},{'source':'approve','target':'end'},{'source':'deny','target':'end_no'}])
    app(client,value)
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'yes'}}).json()
    detail=wait_run(client,run['id']);assert detail['run']['status']=='waiting_approval',detail
    key=detail['run']['pending']['key']
    assert client.post('/api/runs/'+run['id']+'/resume',json={'approvalKey':'wrong'}).status_code==422
    assert client.post('/api/runs/'+run['id']+'/resume',json={'approvalKey':key,'approve':True}).status_code==200
    detail=wait_run(client,run['id'],('succeeded','failed'))
    assert detail['run']['output']=='允许',detail
    assert any(s['status']=='skipped' for s in detail['spans'])
    value['flow']['edges'].append({'source':'end','target':'start'})
    app(client,value)
    assert client.post('/api/applications/test-app/validate').status_code==422


def test_real_mcp_stdio_discovery_authorized_call(client,tmp_path):
    script=tmp_path/'mcp_server.py'
    script.write_text('from mcp.server.fastmcp import FastMCP\nm=FastMCP("test")\n@m.tool()\ndef echo(text:str)->str:\n return "MCP:"+text\nif __name__=="__main__":m.run()\n')
    config={'name':'本地契约MCP','transport':'stdio','command':sys.executable,'args':[str(script)],'timeout':15,'enabled':True}
    assert client.put('/api/integrations/mcpConnections/mcp-test',json=config).status_code==200
    result=client.post('/api/mcp/mcp-test/discover');assert result.status_code==200,result.text
    service=result.json();assert service['status']=='connected',service
    assert service['tools'][0]['name']=='echo'
    assert not any(t['id'].startswith('mcp:') for t in client.get('/api/integrations').json()['catalog'])
    config['allowedTools']=['echo'];config['autoApproveTools']=['echo']
    client.put('/api/integrations/mcpConnections/mcp-test',json=config)
    # Saving configuration invalidates connection status; discover again before enabling calls.
    client.post('/api/mcp/mcp-test/discover')
    result=client.post('/api/tools/test',json={'toolId':'mcp:mcp-test:echo','arguments':{'text':'hello'}})
    assert result.json()['status']=='succeeded',result.text
    assert 'MCP:hello' in json.dumps(result.json()['output'])
    bad=client.post('/api/tools/test',json={'toolId':'mcp:mcp-test:echo','arguments':{'bad':'x'}})
    assert bad.json()['status']=='failed'


def test_agent_model_context_skill_and_usage_price(client,cloud_contract):
    base,calls=cloud_contract
    configure(client,base,'contract-llm','LLM');client.put('/api/settings',json={'allowExternalProcessing':True})
    assert client.put('/api/integrations/skills/skill-test',json={'name':'证据规则','content':'必须给出证据','version':'v1'}).status_code==200
    assert client.put('/api/integrations/priceRules/price-test',json={'name':'测试价','modelId':'contract-llm','inputPerMillion':2,'outputPerMillion':4,'currency':'CNY','effectiveAt':'2026-01-01T00:00:00+00:00'}).status_code==200
    app(client,{'name':'测试Agent','type':'agent','modelId':'contract-llm','skillIds':['skill-test'],'toolIds':[],'maxSteps':3})
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'测试'}}).json()
    detail=wait_run(client,run['id']);assert detail['run']['status']=='succeeded',detail
    assert detail['run']['output']=='连接成功'
    assert any(s['kind']=='skill_load' for s in detail['spans'])
    assert detail['usage'][0]['inputTokens']==8 and detail['usage'][0]['outputTokens']==2
    assert detail['usage'][0]['cost']==pytest.approx(.000024)
    assert detail['usage'][0]['costStatus']=='estimated'
    assert any('必须给出证据' in str(body.get('messages')) for _,body in calls)
    assert client.put('/api/integrations/priceRules/price-test',json={'name':'不能覆盖','modelId':'contract-llm'}).status_code==422


def test_external_events_auth_and_dedup(client):
    client.put('/api/integrations/runnerConnections/runner-test',json={'name':'外部事件契约','url':'http://127.0.0.1:1/run'})
    token=client.post('/api/runners/runner-test/webhook-token').json()['token']
    assert client.post('/api/external/runner-test/runs',json={'input':{}}).status_code==401
    headers={'Authorization':'Bearer '+token}
    run=client.post('/api/external/runner-test/runs',headers=headers,json={'input':{'question':'外部'}}).json()
    events={'events':[{'id':'one','type':'span','spanId':'s1','kind':'tool','name':'远程工具','input':{'secret':'do-not-show'},'output':'ok'},{'id':'two','type':'usage','model':{'modelId':'remote-model'},'usage':{'inputTokens':10,'outputTokens':5}},{'id':'three','type':'result','output':'完成'}]}
    for _ in range(2):assert client.post(f"/api/external/runner-test/runs/{run['id']}/events",headers=headers,json=events).status_code==200
    detail=client.get('/api/runs/'+run['id']).json()
    assert len(detail['usage'])==1 and len(detail['spans'])==1
    assert detail['run']['status']=='succeeded' and 'do-not-show' not in json.dumps(detail)
    assert detail['usage'][0]['cost'] is None


def test_missing_model_failure_is_observed_and_alerted(client):
    client.put('/api/integrations/alertRules/failure',json={'name':'失败提醒','metric':'failure'})
    app(client,{'name':'缺少模型','type':'agent','modelId':'','maxSteps':2})
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'x'}}).json()
    detail=wait_run(client,run['id'])
    assert detail['run']['status']=='failed' and detail['spans'][0]['kind']=='model'
    summary=client.get('/api/observability/summary').json()
    assert len(summary['alerts'])==1
    assert client.post('/api/alerts/'+summary['alerts'][0]['id']+'/ack').json()['status']=='acknowledged'

@pytest.fixture
def runtime_http():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value):
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            calls.append(('tool',self.path));self.send({'data':'来自真实HTTP工具'})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(('post',body))
            if self.path=='/external':self.send({'output':'外部运行完成','runId':'remote-1','usage':{'inputTokens':4,'outputTokens':3},'model':{'modelId':'external-test'}});return
            used=any(m['role']=='tool' for m in body['messages'])
            message={'role':'assistant','content':'工具完成'} if used else {'role':'assistant','content':None,'tool_calls':[{'id':'call_contract','type':'function','function':{'name':'tool_0','arguments':'{"query":"test"}'}}]}
            self.send({'id':'test','object':'chat.completion','created':1,'model':'agent-model','choices':[{'index':0,'message':message,'finish_reason':'stop' if used else 'tool_calls'}],'usage':{'prompt_tokens':11,'completion_tokens':3,'total_tokens':14}})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',calls
    server.shutdown();server.server_close();thread.join()


def test_real_agent_tool_approval_and_external_json(client,runtime_http):
    base,calls=runtime_http
    configure(client,base+'/v1','agent-model','LLM');client.put('/api/settings',json={'allowExternalProcessing':True})
    response=client.put('/api/integrations/httpTools/lookup',json={'name':'查询','url':base+'/lookup','method':'GET','requiresApproval':True,'inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}})
    assert response.status_code==200,response.text
    app(client,{'name':'工具Agent','type':'agent','modelId':'agent-model','toolIds':['http:lookup'],'maxSteps':4})
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'查询'}}).json()
    detail=wait_run(client,run['id']);assert detail['run']['status']=='waiting_approval',detail
    assert not any(kind=='tool' for kind,_ in calls)
    key=detail['run']['pending']['key']
    client.post('/api/runs/'+run['id']+'/resume',json={'approve':True,'approvalKey':key})
    detail=wait_run(client,run['id'],('succeeded','failed'))
    assert detail['run']['status']=='succeeded',detail
    assert detail['run']['output']=='工具完成'
    assert len([c for c in calls if c[0]=='tool'])==1 and len(detail['usage'])==2
    assert any(s['kind']=='tool' for s in detail['spans'])
    client.put('/api/integrations/runnerConnections/remote',json={'name':'外部JSON','url':base+'/external','enabled':True})
    response=client.post('/api/runners/remote/test',json={'input':{'question':'外部契约'}})
    detail=wait_run(client,response.json()['id'])
    assert detail['run']['output']=='外部运行完成' and detail['run']['capture']=='basic'
    assert detail['usage'][0]['inputTokens']==4


def test_knowledge_and_existing_chat_emit_linked_observations(client,cloud_contract):
    base,_=cloud_contract
    configure(client,base,'contract-llm','LLM');client.put('/api/settings',json={'allowExternalProcessing':True})
    rid=upload(client,'obs.md','# 远程办公\n员工可申请远程办公，需主管审批。'.encode());publish(client,rid)
    state=client.get('/api/workspace').json();assistant=state['assistants'][0];assistant['modelId']='contract-llm'
    client.post('/api/workspace/mutations',json={'operations':[{'kind':'assistants','id':assistant['id'],'action':'put','value':assistant}]})
    response=client.post('/api/chat/stream',json={'assistantId':assistant['id'],'question':'远程办公'})
    assert response.status_code==200,response.text
    rows=client.get('/api/observability/runs?kind=chat').json()['items'];assert len(rows)==1
    detail=client.get('/api/runs/'+rows[0]['id']).json()
    assert detail['run']['status']=='succeeded' and detail['usage'][0]['inputTokens']==37
    assert any('messages' in (s.get('input')or{}) for s in detail['spans'] if s['kind']=='model')
    assert client.get('/api/observability/runs?kind=knowledge').json()['total']==2


def test_cancel_waiting_and_failed_checkpoint_restore(client):
    value=flow_app([{'id':'start','type':'start','name':'开始'},{'id':'check','type':'approval','name':'确认','value':'ok'},{'id':'end','type':'end','name':'输出','template':'{{check.output}}'}],[{'source':'start','target':'check'},{'source':'check','target':'end'}])
    app(client,value)
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'x'}}).json()
    assert wait_run(client,run['id'])['run']['status']=='waiting_approval'
    assert client.post('/api/runs/'+run['id']+'/cancel').status_code==200
    assert wait_run(client,run['id'])['run']['status']=='cancelled'
    assert client.post('/api/runs/'+run['id']+'/resume',json={}).status_code==422


def test_retention_is_opt_in_and_preserves_ledger(client):
    from app.runtime import prune_payloads
    run=obs.start('agent','待过期记录',inputs={'private':'正文'})
    with obs.scope(run['id']):
        span=obs.Span('model','历史输入',{'message':'历史消息'});span.end('历史输出')
        obs.usage({'modelId':'example'},{'inputTokens':1,'outputTokens':1},span.value['id'])
        obs.finish(run['id'],'succeeded','历史输出')
    with db.pool.connection() as conn:conn.execute("UPDATE obs_runs SET created_at=now()-interval '90 days' WHERE id=%s",(run['id'],))
    prune_payloads();assert obs.get_run(run['id'])['input']
    client.put('/api/integrations/captureSettings/retention',json={'name':'观测正文留存','retentionEnabled':True,'retentionDays':30})
    prune_payloads()
    detail=client.get('/api/runs/'+run['id']).json()
    assert detail['run']['capture']=='expired' and 'input' not in detail['run']
    assert len(detail['usage'])==1 and 'input' not in detail['spans'][0]


def test_external_sse_trace_contract(client):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            events=[{'type':'meta','remoteRunId':'remote-sse'},{'type':'output.delta','delta':'外部'},{'type':'span','spanId':'tool-a','kind':'tool','name':'远程工具','output':'ok','status':'succeeded'},{'type':'usage','requestId':'request-1','model':{'modelId':'sse-model'},'usage':{'inputTokens':5,'outputTokens':2}},{'type':'result','output':'外部完成'}]
            raw=''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        client.put('/api/integrations/runnerConnections/sse',json={'name':'SSE','url':f'http://127.0.0.1:{server.server_port}','capability':'events'})
        run=client.post('/api/runners/sse/test',json={'input':{'question':'x'}}).json()
        detail=wait_run(client,run['id'])
        assert detail['run']['output']=='外部完成' and detail['run']['remoteRunId']=='remote-sse'
        assert detail['run']['capture']=='reported_events'
        assert detail['usage'][0]['inputTokens']==5
        assert any(s['name']=='远程工具' for s in detail['spans'])
    finally:
        server.shutdown();server.server_close();thread.join()


def test_known_budget_stops_followup_tool_request(client,runtime_http):
    base,calls=runtime_http
    configure(client,base+'/v1','agent-model','LLM');client.put('/api/settings',json={'allowExternalProcessing':True})
    client.put('/api/integrations/httpTools/lookup',json={'name':'预算工具','url':base+'/lookup','method':'GET','requiresApproval':False,'inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}})
    client.put('/api/integrations/priceRules/priced',json={'name':'预算测试价','modelId':'agent-model','inputPerMillion':1000000,'outputPerMillion':0,'currency':'CNY','effectiveAt':'2026-01-01T00:00:00+00:00'})
    app(client,{'name':'预算验证','type':'agent','modelId':'agent-model','toolIds':['http:lookup'],'maxSteps':4,'maxCost':1,'budgetCurrency':'CNY'})
    run=client.post('/api/applications/test-app/runs',json={'debug':True,'input':{'question':'预算'}}).json()
    detail=wait_run(client,run['id'])
    assert detail['run']['status']=='failed' and 'BUDGET_REACHED' in detail['run']['error']
    assert len(detail['usage'])==1 and not any(c[0]=='tool' for c in calls)
