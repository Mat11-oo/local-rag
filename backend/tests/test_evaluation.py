"""Manual case collection against isolated real PostgreSQL, including immutable evidence."""
import json
from concurrent.futures import ThreadPoolExecutor
from test_local_flow import client
from app import db, telemetry as obs


def finished_run():
    run = obs.start('chatflow', '回流测试应用', 'a-real-user', 'app-eval', {'question': '=线上问题', 'apiKey': 'must-not-leak'}, sessionId='session-eval', versionId='immutable-v1')
    with obs.scope(run['id']):
        step = obs.Span('tool', '真实执行步骤', {'query': '证据'}, {'context': '知识原文'})
        step.end('原始工具结果')
    obs.finish(run['id'], 'succeeded', '真实回答')
    with db.pool.connection() as conn:
        db.put(conn, 'sessions', {'id':'session-eval','ownerId':'a-real-user','messages':[{'role':'user','content':'=线上问题'},{'role':'assistant','content':'真实回答','traceId':run['id']},{'role':'user','content':'不能混入后来的对话'}]})
        db.put(conn, 'logs', {'id':run['id'],'kind':'chat','question':'=线上问题','answer':'真实回答','citations':[{'text':'出处'}]})
    return run['id']


def dataset(client, name='每日回流'):
    response = client.post('/api/evaluation/datasets', json={'name':name,'description':'人工收录'})
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_immutable_case_snapshot_dedup_annotations_archive_and_export(client):
    rid = finished_run(); did = dataset(client)
    body = {'datasetId':did,'sourceKind':'run','sourceId':rid,'label':'badcase','note':'引用不完整','tags':['检索遗漏','检索遗漏'],'expectedAnswer':'正确引用'}
    created = client.post('/api/evaluation/cases', json=body)
    assert created.status_code == 200, created.text
    value = created.json()['case']; cid = value['id']
    assert not created.json()['duplicate']
    assert value['snapshot']['run']['versionId'] == 'immutable-v1'
    assert value['snapshot']['spans'][0]['output'] == '原始工具结果'
    assert value['snapshot']['citations'][0]['text'] == '出处'
    assert 'must-not-leak' not in json.dumps(value)
    assert '不能混入后来的对话' not in json.dumps(value,ensure_ascii=False)
    assert value['tags'] == ['检索遗漏']
    # Legacy and trace entry points for the same source have one membership.
    duplicate = client.post('/api/evaluation/cases', json={**body,'sourceKind':'log','label':'goodcase'})
    assert duplicate.json()['duplicate'] and duplicate.json()['case']['id'] == cid
    assert duplicate.json()['case']['label'] == 'badcase'
    # Collection remains after original source content is pruned/changed.
    obs.patch(rid, input=None, output=None)
    edited = client.put('/api/evaluation/cases/'+cid, json={'label':'goodcase','reviewStatus':'reviewed','note':'已人工复核','tags':['准确'],'expectedAnswer':'验收标准','input':'篡改','snapshot':{}})
    assert edited.status_code == 200, edited.text
    assert edited.json()['input']['question'] == '=线上问题'
    assert edited.json()['output'] == '真实回答' and edited.json()['snapshot'] == value['snapshot']
    listing = client.get('/api/evaluation/cases', params={'datasetId':did,'label':'goodcase','reviewStatus':'reviewed','q':'准确'}).json()
    assert listing['total'] == 1 and listing['stats']['good'] == 1 and 'snapshot' not in listing['items'][0]
    assert client.get('/api/evaluation/cases?q=does-not-exist').json()['total'] == 0
    sets = client.get('/api/evaluation/datasets').json()
    assert sets[0]['total'] == 1 and sets[0]['good'] == 1
    exported = client.get('/api/evaluation/cases?export=jsonl').text
    assert json.loads(exported)['snapshot'] == value['snapshot']
    csv = client.get('/api/evaluation/cases?export=csv')
    assert csv.status_code == 200 and 'text/csv' in csv.headers['content-type']
    assert client.put('/api/evaluation/cases/'+cid,json={'label':'goodcase','archived':True}).status_code == 200
    assert client.get('/api/evaluation/cases').json()['total'] == 0
    archived = client.get('/api/evaluation/cases?archived=true').json()
    assert archived['total'] == 1 and archived['items'][0]['note'] == '已人工复核'
    assert client.put('/api/evaluation/cases/'+cid,json={'label':'goodcase','archived':False}).status_code == 200
    with db.pool.connection() as conn: assert db.require(conn,'evaluationCases',cid)['snapshot'] == value['snapshot']
    # Agent/Flow conversations appear in the daily dialogue log too.
    assert client.get('/api/observability/runs?kind=chat').json()['total'] == 1


def test_case_permissions_validation_legacy_and_concurrent_dedup(client):
    did=dataset(client);rid=finished_run()
    for role in ('user','knowledge'):
        headers={'X-Role':role}
        assert client.get('/api/evaluation/datasets',headers=headers).status_code == 403
        assert client.get('/api/evaluation/cases?export=jsonl',headers=headers).status_code == 403
        assert client.post('/api/evaluation/cases',headers=headers,json={'datasetId':did,'sourceKind':'run','sourceId':rid}).status_code == 403
    pending=obs.start('agent','尚在执行','test-browser')
    assert client.get('/api/evaluation/source/run/'+pending['id']).status_code == 422
    assert client.post('/api/evaluation/cases',json={'datasetId':did,'sourceKind':'run','sourceId':rid,'label':'arbitrary'}).status_code == 422
    assert client.post('/api/evaluation/datasets',json={'name':'  '}).status_code == 422
    assert client.get('/api/evaluation/cases?start=invalid').status_code == 422
    with db.pool.connection() as conn:
        db.put(conn,'logs',{'id':'old-chat','kind':'chat','question':'=HYPERLINK("bad")','answer':'历史回答','createdAt':db.now()})
        db.put(conn,'logs',{'id':'not-chat','kind':'model','question':'模型连接测试'})
    body={'datasetId':did,'sourceKind':'log','sourceId':'old-chat','label':'badcase'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post('/api/evaluation/cases',json=body),range(2)))
    assert all(r.status_code==200 for r in results), [r.text for r in results]
    assert sorted(r.json()['duplicate'] for r in results)==[False,True]
    assert results[0].json()['case']['snapshot']['capture']=='legacy_summary'
    assert "'=HYPERLINK" in client.get('/api/evaluation/cases?export=csv').text
    assert client.get('/api/evaluation/source/log/not-chat').status_code == 422
    did2=dataset(client,'另一个业务')
    assert not client.post('/api/evaluation/cases',json={**body,'datasetId':did2}).json()['duplicate']
    cid=results[0].json()['case']['id']
    assert client.put('/api/evaluation/cases/'+cid,json={'datasetId':did2,'label':'goodcase'}).status_code==422
    assert client.get('/api/evaluation/cases?size=1').json()['total']==2
    assert len(client.get('/api/evaluation/cases?size=1').json()['items'])==1
