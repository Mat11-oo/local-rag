import asyncio
import csv
import hmac
import io
import json
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from psycopg.types.json import Jsonb
from . import db, models, integrations as bridge, telemetry as obs, runtime

router = APIRouter(prefix='/api')


def role(request): return request.headers.get('x-role', 'admin')
def owner(request):
    from .main import owner as get_owner
    return get_owner(request)
def edit(request, admin=False):
    from .main import editor
    editor(request, admin)

def allowed(run, request):
    if role(request) == 'admin': return True
    if role(request) == 'knowledge' and run['kind'] == 'knowledge': return True
    return run.get('ownerId') == owner(request)


def require_run(rid, request):
    run = obs.get_run(rid)
    if not allowed(run, request): raise HTTPException(404, '运行不存在')
    return run


@router.get('/integrations')
def integrations(request: Request):
    edit(request)
    return {kind: bridge.public_config(kind) for kind in bridge.KINDS} | {'catalog': bridge.catalog()}


@router.put('/integrations/{kind}/{rid}')
def save_integration(kind: str, rid: str, body: dict, request: Request):
    edit(request, True)
    return bridge.save(kind, rid, body)


@router.delete('/integrations/{kind}/{rid}')
def delete_integration(kind: str, rid: str, request: Request):
    edit(request, True)
    if kind not in bridge.KINDS: raise ValueError('配置类型无效')
    with db.pool.connection() as conn:
        apps = db.items(conn, 'assistants')
        if any(rid == app.get('runnerId') or rid in app.get('skillIds', []) or any(rid in t.split(':')[1:2] for t in app.get('toolIds', [])) for app in apps):
            raise ValueError('配置正在被应用引用，请先解除引用或停用连接')
        conn.execute('DELETE FROM resources WHERE kind=%s AND id=%s', (kind, rid))
        conn.execute('DELETE FROM model_secrets WHERE id IN (%s,%s)', ('integration-' + rid, 'integration-' + rid + '-webhook'))
    return {'ok': True}


@router.post('/mcp/{rid}/discover')
async def discover_mcp(rid: str, request: Request):
    edit(request, True)
    return await bridge.discover(rid)


@router.post('/mcp/{rid}/resource')
async def resource(rid: str, body: dict, request: Request):
    edit(request, True)
    config = bridge.public_config('mcpConnections', rid)
    uri = body.get('uri')
    if uri not in [r.get('uri') for r in config.get('resources', [])]: raise ValueError('资源未在发现目录中')
    from pydantic import AnyUrl
    async with bridge.mcp_session(config) as client:
        return (await client.read_resource(AnyUrl(uri))).model_dump(mode='json')


@router.post('/mcp/{rid}/prompt')
async def prompt(rid: str, body: dict, request: Request):
    edit(request, True)
    config = bridge.public_config('mcpConnections', rid)
    if body.get('name') not in [p.get('name') for p in config.get('prompts', [])]: raise ValueError('模板未在发现目录中')
    async with bridge.mcp_session(config) as client:
        return (await client.get_prompt(body['name'], body.get('arguments', {}))).model_dump(mode='json')


@router.post('/tools/test')
async def test_tool(body: dict, request: Request):
    edit(request, True)
    tid = body.get('toolId', '')
    run = obs.start('tool', '工具主动测试', owner(request), inputs=body.get('arguments', {}), debug=True)
    obs.patch(run['id'], status='running', startedAt=db.now())
    with obs.scope(run['id']):
        span = obs.Span('tool', tid, body.get('arguments', {}))
        try:
            result = await bridge.call(tid, body.get('arguments', {}), {'toolIds': [tid], 'kbIds': body.get('kbIds', [])})
            span.end(result); obs.finish(run['id'], 'succeeded', result)
        except Exception as exc:
            error = models.safe_error(exc)
            span.end(status='failed', error=error); obs.finish(run['id'], 'failed', error=error)
    return obs.get_run(run['id'])


@router.put('/applications/{aid}')
def save_application(aid: str, body: dict, request: Request):
    edit(request)
    value = {**body, 'id': aid, 'type': body.get('type', 'simple'), 'updatedAt': db.now()}
    if value['type'] not in ('simple', 'agent', 'chatflow'): raise ValueError('应用类型无效')
    if not value.get('name', '').strip(): raise ValueError('请输入名称')
    value.setdefault('kbIds', []); value.setdefault('modelId', ''); value.setdefault('welcome', '你好，请描述你的任务。')
    value.setdefault('examples', []); value.setdefault('prompt', ''); value.setdefault('topK', 5); value.setdefault('rerank', False)
    value['maxSteps'] = max(1, min(40, int(value.get('maxSteps', 8))))
    value['timeout'] = max(5, min(1800, int(value.get('timeout', 120))))
    value['maxParallel'] = max(1,min(4,int(value.get('maxParallel',3))))
    value['maxRetries'] = max(0,min(3,int(value.get('maxRetries',0))))
    with db.pool.connection() as conn:
        old = db.get(conn, 'assistants', aid) or {}
        value['publishedVersion'] = old.get('publishedVersion')
        for kid in value['kbIds']: db.require(conn, 'knowledgeBases', kid)
        if value.get('modelId'): db.require(conn, 'models', value['modelId'])
        db.put(conn, 'assistants', value)
    return value


@router.post('/applications/{aid}/validate')
def validate_application(aid: str, request: Request):
    edit(request)
    with db.pool.connection() as conn: app = db.require(conn, 'assistants', aid)
    return {'valid': True, 'order': runtime.validate(app)}


@router.post('/applications/{aid}/publish')
def publish_application(aid: str, request: Request):
    edit(request)
    with db.pool.connection() as conn:
        conn.execute("SELECT id FROM resources WHERE kind='assistants' AND id=%s FOR UPDATE", (aid,))
        app = db.require(conn, 'assistants', aid)
        runtime.validate(app)
        definition = {k: v for k, v in app.items() if k not in ('publishedVersion', 'updatedAt')}
        vid = db.uid()
        db.put(conn, 'applicationVersions', {'id': vid, 'appId': aid, 'createdAt': db.now(), 'definition': definition})
        app['publishedVersion'] = vid; db.put(conn, 'assistants', app)
    return {'versionId': vid}


@router.get('/applications/{aid}/versions')
def versions(aid: str, request: Request):
    edit(request)
    with db.pool.connection() as conn:
        return [v for v in db.items(conn, 'applicationVersions') if v['appId'] == aid]


@router.post('/applications/{aid}/runs')
def start_run(aid: str, body: dict, request: Request):
    with db.pool.connection() as conn: app = db.require(conn, 'assistants', aid)
    debug = bool(body.get('debug'))
    if debug: edit(request)
    elif not app.get('publishedVersion'): raise ValueError('请先发布应用版本')
    if app.get('type', 'simple') == 'simple': raise ValueError('简易问答请使用对话入口')
    inputs = body.get('input', {})
    if not isinstance(inputs, dict) or len(json.dumps(inputs)) > 100000: raise ValueError('输入格式或大小无效')
    return runtime.enqueue(app, inputs, owner(request), debug=debug)


@router.get('/runs/{rid}')
def run_detail(rid: str, request: Request):
    run = require_run(rid, request)
    with db.pool.connection() as conn:
        spans = [r['data'] for r in conn.execute('SELECT data FROM obs_spans WHERE run_id=%s ORDER BY created_at', (rid,))]
        usage = [r['data'] for r in conn.execute('SELECT data FROM obs_usage WHERE run_id=%s ORDER BY created_at', (rid,))]
        events = [r['data'] for r in conn.execute('SELECT data FROM obs_events WHERE run_id=%s ORDER BY seq DESC', (rid,))]
    run.pop('definition', None); run.pop('checkpoint', None)
    return {'run': run, 'spans': spans, 'usage': usage, 'events': events[::-1]}


@router.get('/runs/{rid}/implementation')
def implementation(rid: str, request: Request, kind: str = 'model'):
    require_run(rid, request)
    import inspect, hashlib
    mapping = {'model': runtime._generation_once, 'tool': runtime.tool_call, 'agent': runtime.agent, 'node': runtime.flow, 'skill_load': runtime.agent}
    if kind not in mapping: raise ValueError('此类步骤无本地运行器源码可展示')
    source = inspect.getsource(mapping[kind])
    return {'source': source, 'file': 'backend/app/runtime.py', 'function': mapping[kind].__name__, 'sha256': hashlib.sha256(source.encode()).hexdigest(), 'scope': '当前本地运行器实现；不代表历史版本或远端工具内部源码'}


@router.post('/runs/{rid}/cancel')
async def cancel(rid: str, request: Request):
    run = require_run(rid, request)
    if run['status'] in obs.TERMINAL: return run
    obs.patch(rid, cancelRequested=True)
    task = runtime._tasks.get(rid)
    if task: task.cancel()
    else:
        obs.finish(rid, 'cancelled', error='用户取消')
        runtime.save_chat(rid)
    if run.get('source') == 'external':
        config = bridge.public_config('runnerConnections', run['definition']['runnerId'])
        if config.get('cancelUrl') and run.get('remoteRunId'):
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    key = bridge.secret(config['id'])
                    response = await client.post(config['cancelUrl'], json={'runId': run['remoteRunId']}, headers={'Authorization': 'Bearer ' + key} if key else {})
                    response.raise_for_status(); obs.patch(rid, remoteCancel='confirmed')
            except Exception: obs.patch(rid, remoteCancel='unconfirmed')
        else: obs.patch(rid, remoteCancel='unsupported')
    return obs.get_run(rid)


@router.post('/runs/{rid}/resume')
def resume(rid: str, body: dict, request: Request):
    run = require_run(rid, request)
    if run['status'] not in ('waiting_approval', 'paused', 'failed'): raise ValueError('当前状态不可恢复')
    if any(k.startswith('inflight') and v for k,v in run.get('checkpoint', {}).items()):
        raise ValueError('存在结果不明确的在途工具调用，请先核对外部结果；本次运行不能自动重放')
    if body.get('approve') is False:
        obs.finish(rid, 'cancelled', error='人工拒绝执行'); runtime.save_chat(rid)
    else:
        approvals = run.get('approvals', [])
        if run.get('pending'):
            if body.get('approvalKey') != run['pending']['key']: raise ValueError('确认对象已变化，请刷新后重新确认')
            approvals = [*approvals, run['pending']['key']]
        obs.patch(rid, status='queued', cancelRequested=False, approvals=approvals, error=None)
        obs.event(rid, 'run.resumed', {'approval': run.get('pending')})
    return obs.get_run(rid)


@router.get('/runs/{rid}/events')
async def events(rid: str, request: Request, after: int = 0):
    require_run(rid, request)
    async def stream():
        cursor = after
        while not await request.is_disconnected():
            with db.pool.connection() as conn:
                rows = conn.execute('SELECT seq,data FROM obs_events WHERE run_id=%s AND seq>%s ORDER BY seq LIMIT 200', (rid, cursor)).fetchall()
            for row in rows:
                cursor = row['seq']
                yield f'id: {cursor}\nevent: observation\ndata: {json.dumps(row["data"], ensure_ascii=False)}\n\n'
            if obs.get_run(rid)['status'] in obs.TERMINAL: break
            if not rows: yield ': keepalive\n\n'
            await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type='text/event-stream')


def query_scope(request):
    if role(request) == 'admin': return '', []
    if role(request) == 'knowledge': return " AND (data->>'ownerId'=%s OR data->>'kind'='knowledge')", [owner(request)]
    return " AND data->>'ownerId'=%s", [owner(request)]


@router.get('/observability/runs')
def list_runs(request: Request, page: int = 1, size: int = 20, kind: str = '', status: str = '', q: str = '', days: int = 7, appId: str = '', source: str = '', export: bool = False):
    clause, args = query_scope(request)
    clause = 'created_at >= %s' + clause
    args = [datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days))), *args]
    for key, value in [('kind', kind), ('status', status), ('appId', appId), ('source', source)]:
        if key == 'kind' and value == 'chat': clause += " AND (data->>'kind'='chat' OR coalesce(data->>'sessionId','')<>'')"
        elif value: clause += f" AND data->>'{key}'=%s"; args.append(value)
    if q: clause += ' AND (id ILIKE %s OR data->>\'name\' ILIKE %s OR data->>\'input\' ILIKE %s OR data->>\'error\' ILIKE %s)'; args.extend(['%' + q + '%'] * 4)
    size = max(1, min(100, size)); page = max(1, page)
    with db.pool.connection() as conn:
        total = conn.execute('SELECT count(*) AS n FROM obs_runs WHERE ' + clause, args).fetchone()['n']
        limit, offset = (10000, 0) if export else (size, (page - 1) * size)
        rows = conn.execute("SELECT data - 'definition' - 'checkpoint' AS data FROM obs_runs WHERE " + clause + ' ORDER BY created_at DESC LIMIT %s OFFSET %s', [*args, limit, offset]).fetchall()
    items = [r['data'] for r in rows]
    if export:
        stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(['运行ID', '名称', '类型', '状态', '创建时间', '耗时', '错误'])
        def cell(v):
            s = str(v or '')
            return "'" + s if s[:1] in ('=', '+', '-', '@') else s
        for r in items: writer.writerow([cell(r.get(k)) for k in ('id', 'name', 'kind', 'status', 'createdAt', 'duration', 'error')])
        return Response('\ufeff' + stream.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=runtime-records.csv'})
    return {'items': items, 'total': total, 'page': page, 'size': size}


@router.get('/observability/summary')
def summary(request: Request, days: int = 7):
    scope, extra = query_scope(request)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days)))
    with db.pool.connection() as conn:
        stats = conn.execute("SELECT count(*) AS total,count(*) FILTER(WHERE data->>'status'='succeeded') AS succeeded,count(*) FILTER(WHERE data->>'status'='failed') AS failed,count(*) FILTER(WHERE data->>'capture' IN ('basic','interrupted','summary_only')) AS incomplete,percentile_cont(.5) WITHIN GROUP(ORDER BY (data->>'duration')::float) AS p50,percentile_cont(.95) WITHIN GROUP(ORDER BY (data->>'duration')::float) AS p95 FROM obs_runs WHERE created_at>=%s" + scope, [cutoff, *extra]).fetchone()
        daily = conn.execute("SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD') AS day,count(*) AS count FROM obs_runs WHERE created_at>=%s" + scope + ' GROUP BY 1 ORDER BY 1', [cutoff, *extra]).fetchall()
        usage = conn.execute("SELECT u.data FROM obs_usage u JOIN obs_runs r ON u.run_id=r.id WHERE r.created_at>=%s" + scope.replace("data->", "r.data->"), [cutoff, *extra]).fetchall()
        alerts = db.items(conn, 'alerts') if role(request) == 'admin' else []
    entries = [r['data'] for r in usage]; currencies = {}
    for entry in entries:
        if entry.get('cost') is not None:
            currency = entry.get('currency') or 'UNKNOWN'
            currencies[currency] = currencies.get(currency, 0) + entry['cost']
    return {**stats, 'daily': daily, 'inputTokens': sum(e.get('inputTokens') or 0 for e in entries), 'outputTokens': sum(e.get('outputTokens') or 0 for e in entries), 'usageRequests': len(entries), 'unknownUsage': sum(e.get('inputTokens') is None and e.get('outputTokens') is None for e in entries), 'unknownCost': sum(e.get('costStatus') != 'estimated' for e in entries), 'estimatedCosts': currencies, 'alerts': alerts}


@router.get('/observability/usage')
def usage_entries(request: Request, page: int = 1, days: int = 7, model: str = ''):
    scope, extra = query_scope(request)
    where = 'r.created_at>=%s' + scope.replace('data->', 'r.data->')
    args = [datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days))), *extra]
    if model: where += " AND u.data->>'modelId' ILIKE %s"; args.append('%' + model + '%')
    with db.pool.connection() as conn:
        total = conn.execute('SELECT count(*) AS n FROM obs_usage u JOIN obs_runs r ON u.run_id=r.id WHERE ' + where, args).fetchone()['n']
        rows = conn.execute('SELECT u.data FROM obs_usage u JOIN obs_runs r ON u.run_id=r.id WHERE ' + where + ' ORDER BY u.created_at DESC LIMIT 20 OFFSET %s', [*args, max(0, page - 1) * 20]).fetchall()
    return {'items': [r['data'] for r in rows], 'total': total}


@router.post('/alerts/{aid}/ack')
def ack(aid: str, request: Request):
    edit(request, True)
    with db.pool.connection() as conn:
        alert = db.require(conn, 'alerts', aid); alert.update(status='acknowledged', acknowledgedAt=db.now()); db.put(conn, 'alerts', alert)
    return alert


@router.post('/runners/{rid}/webhook-token')
def webhook_token(rid: str, request: Request):
    edit(request, True); bridge.public_config('runnerConnections', rid)
    token = secrets.token_urlsafe(32)
    with db.pool.connection() as conn:
        encrypted = models.cipher().encrypt(token.encode()).decode()
        conn.execute('INSERT INTO model_secrets(id,encrypted) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET encrypted=EXCLUDED.encrypted', ('integration-' + rid + '-webhook', encrypted))
    return {'token': token, 'scope': rid, 'note': '仅此次返回；重新生成将使旧令牌失效'}


def remote_auth(connection_id, request):
    expected = bridge.secret(connection_id + '-webhook')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
    if not expected or not hmac.compare_digest(expected, supplied): raise HTTPException(401, '事件接入令牌无效')


@router.post('/external/{connection_id}/runs')
def import_run(connection_id: str, body: dict, request: Request):
    remote_auth(connection_id, request)
    config = bridge.public_config('runnerConnections', connection_id)
    return obs.start('agent', config['name'], source='external', inputs=body.get('input'), runnerId=connection_id, remoteRunId=body.get('remoteRunId'), status='running', startedAt=db.now(), capture='reported_events')


@router.post('/external/{connection_id}/runs/{rid}/events')
def import_events(connection_id: str, rid: str, body: dict, request: Request):
    remote_auth(connection_id, request); run = obs.get_run(rid)
    if run.get('runnerId') != connection_id and run.get('definition', {}).get('runnerId') != connection_id: raise HTTPException(403, '运行不属于该连接')
    events = body.get('events', [])
    if not isinstance(events, list) or len(events) > 100: raise ValueError('每批最多100条事件')
    for event in events:
        if not event.get('id') or len(json.dumps(event)) > 200000: raise ValueError('事件缺少 ID 或超过大小限制')
        eid = connection_id + ':' + str(event['id'])
        with db.pool.connection() as conn:
            result = conn.execute('INSERT INTO obs_events(id,run_id,data) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING id', (eid, rid, Jsonb(obs.clean({**event, 'runId': rid, 'receivedAt': db.now()})))).fetchone()
        if not result: continue
        with obs.scope(rid):
            if event['type'] == 'span': runtime.remote_span(rid, event)
            elif event['type'] == 'usage': obs.usage(event.get('model', {}), event.get('usage', {}), request_id=eid, source='remote')
            elif event['type'] == 'result' and run['status'] not in obs.TERMINAL: obs.finish(rid, 'succeeded', event.get('output'))
            elif event['type'] == 'error' and run['status'] not in obs.TERMINAL: obs.finish(rid, 'failed', error=event.get('message'))
    return {'accepted': len(events)}


async def chat_response(assistant, body, request):
    question = str(body['question']); sid = body.get('sessionId') or db.uid()
    if not assistant.get('publishedVersion'): raise ValueError('应用尚未发布，请先在应用中心发布版本')
    with db.pool.connection() as conn:
        conn.execute("SELECT id FROM resources WHERE kind='sessions' AND id=%s FOR UPDATE", (sid,))
        session = db.get(conn, 'sessions', sid) or {'id': sid, 'ownerId': owner(request), 'assistantId': assistant['id'], 'title': question[:30], 'messages': [], 'createdAt': db.now()}
        if session.get('ownerId') != owner(request) or session['assistantId'] != assistant['id']: raise HTTPException(404, '会话不存在')
        if session.get('activeRun'):
            try:
                if obs.get_run(session['activeRun'])['status'] not in obs.TERMINAL: raise ValueError('本会话已有运行，请在看板处理或停止')
            except ValueError as exc:
                if '已有运行' in str(exc): raise
        history = session['messages']
        if body.get('retry'):
            last = next((i for i in range(len(history) - 1, -1, -1) if history[i]['role'] == 'user'), len(history))
            history = history[:last]
        run = runtime.enqueue(assistant, {'question': question, 'history': history[-6:]}, owner(request), sid)
        message_id = db.uid()
        session['messages'] = history + [{'id': db.uid(), 'role': 'user', 'content': question, 'createdAt': db.now()}, {'id': message_id, 'role': 'assistant', 'content': '', 'createdAt': db.now(), 'traceId': run['id']}]
        session['activeRun'] = run['id']; db.put(conn, 'sessions', session)
    def packet(name, data): return 'event: ' + name + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n'
    async def stream():
        yield packet('meta', {'session': session, 'messageId': message_id, 'traceId': run['id']})
        previous = ''; last_status = ''
        try:
            while not await request.is_disconnected():
                current = obs.get_run(run['id'])
                if current['status'] != last_status:
                    last_status = current['status']; yield packet('stage', {'name': current['status']})
                output = current.get('liveOutput') or current.get('output') or ''
                if not isinstance(output, str): output = json.dumps(output, ensure_ascii=False)
                if output.startswith(previous) and len(output) > len(previous): yield packet('token', {'delta': output[len(previous):]}); previous = output
                if current['status'] in obs.TERMINAL:
                    if current.get('error'): yield packet('error', {'message': current['error']})
                    break
                if current['status'] in ('waiting_approval', 'paused'):
                    yield packet('token', {'delta': '\n运行等待处理，请在看板打开本次运行进行确认或恢复。'})
                    break
                await asyncio.sleep(.4)
        finally:
            # Execution persists independently; closing a page does not imply cancelling an external effect.
            pass
        yield packet('done', {'sessionId': sid, 'traceId': run['id']})
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})

@router.post('/runners/{rid}/test')
def test_runner(rid: str, body: dict, request: Request):
    edit(request, True)
    config = bridge.public_config('runnerConnections', rid)
    app = {'id': 'test-' + rid, 'name': config['name'] + ' · 契约测试', 'type': 'agent', 'runtimeSource': 'external', 'runnerId': rid, 'timeout': config.get('timeout', 30)}
    return runtime.enqueue(app, body.get('input', {'question': '连接契约测试'}), owner(request), debug=True)
