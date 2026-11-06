"""Persisted DAG and agent execution. Network disconnects do not discard runs."""
import asyncio
import contextvars
import copy
import json
import re
import time
from contextlib import suppress
import httpx
from psycopg.types.json import Jsonb
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, messages_to_dict, messages_from_dict
from . import db, models, integrations as bridge, telemetry as obs

_tasks = {}
_stack = contextvars.ContextVar('flow_stack', default=())
NODE_TYPES = {'start', 'template', 'retrieval', 'llm', 'condition', 'assign', 'extract', 'merge', 'tool', 'agent', 'approval', 'end'}


class SafeFailure(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status_code=status


class Waiting(Exception):
    pass


class Cancelled(Exception):
    pass


def validate(app):
    kind = app.get('type', 'simple')
    if kind not in ('simple', 'chatflow', 'agent'):
        raise ValueError('应用类型无效')
    if not app.get('name', '').strip():
        raise ValueError('应用名称不可为空')
    if kind == 'agent' and app.get('runtimeSource', 'internal') == 'external':
        bridge.public_config('runnerConnections', app.get('runnerId'))
        return []
    if kind == 'chatflow':
        graph = app.get('flow') or {}
        nodes, edges = graph.get('nodes', []), graph.get('edges', [])
        if not nodes or len(nodes) > 80 or len(edges) > 200:
            raise ValueError('流程须包含 1–80 个节点，连线最多 200 条')
        ids = [n.get('id') for n in nodes]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not re.fullmatch(r'[A-Za-z][\w-]{0,63}', i) for i in ids):
            raise ValueError('节点 ID 需唯一，使用英文开头的字母、数字、下划线或短横线')
        if sum(n.get('type') == 'start' for n in nodes) != 1 or not any(n.get('type') == 'end' for n in nodes):
            raise ValueError('流程需要且仅需一个开始节点，以及至少一个结束节点')
        incoming = {i: [] for i in ids}; outgoing = {i: [] for i in ids}
        for edge in edges:
            a, b = edge.get('source'), edge.get('target')
            if a not in incoming or b not in incoming or a == b:
                raise ValueError('连线引用了不存在的节点或自身')
            incoming[b].append(a); outgoing[a].append(b)
        ready = [i for i in ids if not incoming[i]]; order = []
        degree = {i: len(incoming[i]) for i in ids}
        while ready:
            i = ready.pop(0); order.append(i)
            for j in outgoing[i]:
                degree[j] -= 1
                if not degree[j]: ready.append(j)
        if len(order) != len(ids):
            raise ValueError('流程存在循环，请使用无环编排')
        start_id = next(n['id'] for n in nodes if n['type'] == 'start')
        reached = {start_id}
        for i in order:
            if i != start_id and any(p in reached for p in incoming[i]): reached.add(i)
        if len(reached) != len(ids):
            raise ValueError('存在未连接到开始节点的节点')
        ends = {n['id'] for n in nodes if n['type'] == 'end'}
        reaches_end = set(ends)
        for i in reversed(order):
            if any(j in reaches_end for j in outgoing[i]): reaches_end.add(i)
        if set(ids) != reaches_end:
            raise ValueError('存在无法到达结束节点的路径')
        if incoming[start_id] or any(outgoing[i] for i in ends):
            raise ValueError('开始节点不能有入边，结束节点不能有出边')
        for node in nodes:
            if node.get('type') not in NODE_TYPES:
                raise ValueError('不支持的节点类型')
            if node['type'] == 'tool' and node.get('toolId') not in app.get('toolIds', []):
                raise ValueError('工具节点需要在应用中授权该工具')
        return order
    return []


def render(value, values):
    if isinstance(value, dict): return {k: render(v, values) for k, v in value.items()}
    if isinstance(value, list): return [render(v, values) for v in value]
    if not isinstance(value, str): return value
    def read(path):
        result = values
        for key in path.strip().split('.'):
            if not isinstance(result, dict) or key not in result:
                raise ValueError('变量不存在：' + path)
            result = result[key]
        return result
    match = re.fullmatch(r'{{\s*([\w.-]+)\s*}}', value)
    if match: return read(match[1])
    def replace(match):
        result = read(match[1])
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return re.sub(r'{{\s*([\w.-]+)\s*}}', replace, value)


def check():
    run = obs.get_run(obs.current_run.get())
    if run.get('cancelRequested') or run['status'] == 'cancelled':
        raise Cancelled('运行已取消')
    app = run.get('definition', {})
    limit = app.get('maxCost')
    if limit is not None and float(limit) > 0:
        with db.pool.connection() as conn:
            spent = conn.execute("SELECT COALESCE(sum((data->>'cost')::numeric),0) AS amount FROM obs_usage WHERE run_id=%s AND data->>'currency'=%s", (run['id'],app.get('budgetCurrency','CNY'))).fetchone()['amount']
        if float(spent) >= float(limit):
            raise ValueError('BUDGET_REACHED：已知费用达到上限，停止后续调用；并行在途和未回传用量仍可能产生费用')
    return run


def approval(key, detail):
    run = check()
    if key not in run.get('approvals', []):
        obs.patch(run['id'], status='waiting_approval', pending={'key': key, **obs.clean(detail)})
        obs.event(run['id'], 'approval.requested', detail)
        raise Waiting()


async def tool_call(tool_id, arguments, app, key):
    run = check()
    memo = run.get('checkpoint', {}).get('tool:' + key)
    if memo is not None: return memo
    spec = next((t for t in bridge.catalog() if t['id'] == tool_id), None)
    if not spec: raise ValueError('工具已停用或未发现')
    snapshot = app.get('toolSnapshots', {}).get(tool_id)
    if snapshot and snapshot.get('inputSchema') != spec.get('inputSchema'):
        raise ValueError('TOOL_SCHEMA_CHANGED：工具参数结构已变化，请重新检查应用')
    if tool_id not in app.get('toolIds', []) and tool_id != 'knowledge_search':
        raise ValueError('应用未授权此工具')
    bridge.validate_arguments(spec.get('inputSchema'), arguments)
    if spec.get('requiresApproval', False):
        approval(key, {'toolId': tool_id, 'arguments': arguments, 'reason': '此工具需要人工确认'})
    span = obs.Span('tool', spec['name'], arguments, {'toolId': tool_id, 'attemptId': key})
    with obs.scope(run['id'], span.value['id']):
        obs.checkpoint(run['id'], 'inflight:' + key, {'key': key, 'toolId': tool_id, 'startedAt': db.now()})
        try:
            result = await bridge.call(tool_id, arguments, app)
            obs.checkpoint(run['id'], 'tool:' + key, result)
            obs.checkpoint(run['id'], 'inflight:' + key, None)
            span.end(result)
            return result
        except BaseException as exc:
            span.end(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', error=models.safe_error(exc))
            raise


async def _generation_once(app, messages, tools=None):
    check()
    span = obs.Span('model', '模型请求', {'messages': [m.model_dump(mode='json') for m in messages], 'tools': tools or []}, {'modelConfigId': app.get('modelId'), 'executionMode': 'ReAct tool loop', 'messageCount': len(messages)})
    counts = {}; model = None
    try:
        model, key = models.model_for('LLM', app.get('modelId'))
        snapshot = app.get('modelSnapshots', {}).get(model['id'])
        if snapshot and any(snapshot.get(k) != model.get(k) for k in ('modelId','baseUrl','providerConfigId','providerCredentialVersion')):
            raise ValueError('MODEL_CONFIG_CHANGED：模型连接在运行启动后已变化，请重新发起运行')
        client = models.chat_client(model, key, streaming=False)
        # Retries are orchestrated as separate observable attempts, never hidden by the SDK.
        client.max_retries = 0
        if tools: client = client.bind_tools(tools)
        result = await client.ainvoke(messages)
        counts = models.usage_of(result)
        span.end(result.model_dump(mode='json'))
        obs.usage(model, counts, span.value['id'], request_id=span.value['id'])
        return result
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):
            span.end(status='cancelled', error='请求已取消，尚未返回用量')
            if model: obs.usage(model,counts,span.value['id'],request_id=span.value['id'])
            raise
        safe=models.safe_error(exc, locals().get('key',''))
        span.end(status='failed', error=safe)
        if model: obs.usage(model, counts, span.value['id'], request_id=span.value['id'])
        raise SafeFailure(safe,getattr(exc,'status_code',None) or (504 if 'Timeout' in type(exc).__name__ or 'Connection' in type(exc).__name__ else None)) from None


async def generation(app, messages, tools=None):
    retries = max(0, min(3, int(app.get('maxRetries', 0))))
    for attempt in range(retries + 1):
        check()
        try:
            return await _generation_once(app, messages, tools)
        except (Waiting, Cancelled, asyncio.CancelledError):
            raise
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            transient = status == 429 or isinstance(status, int) and status >= 500 or isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
            if not transient or attempt == retries: raise
            obs.event(obs.current_run.get(), 'model.retry', {'attempt': attempt + 1, 'error': models.safe_error(exc)})
            await asyncio.sleep(.5 * (attempt + 1))


async def agent(app, inputs, prefix='agent'):
    run = check(); checkpoint_key = prefix + ':messages'
    stored = run.get('checkpoint', {}).get(checkpoint_key)
    if stored:
        messages = messages_from_dict(stored)
    else:
        instructions = app.get('prompt', '根据用户目标使用已授权工具完成任务。')
        with db.pool.connection() as conn:
            for skill_id in app.get('skillIds', []):
                skill = app.get('skillSnapshots', {}).get(skill_id) or db.require(conn, 'skills', skill_id)
                if not skill.get('enabled', True): raise ValueError('Skill 已停用')
                span = obs.Span('skill_load', skill['name'], {'version': skill.get('version'), 'fingerprint': skill.get('fingerprint')})
                instructions += '\n\n技能：' + skill['name'] + '\n' + skill['content']
                span.end({'content': skill['content'], 'semantics': 'loaded_in_context'})
        history = [HumanMessage(content=str(m.get('content',''))) if m.get('role')=='user' else AIMessage(content=str(m.get('content',''))) for m in inputs.get('history', [])[-6:]]
        messages = [SystemMessage(content=instructions), *history, HumanMessage(content=str(inputs.get('question', '')))]
        obs.checkpoint(run['id'], checkpoint_key, messages_to_dict(messages))
    selected = [t for t in bridge.catalog() if t['id'] in app.get('toolIds', [])]
    mapping = {'tool_' + str(i): t for i, t in enumerate(selected)}
    definitions = [{'type': 'function', 'function': {'name': name, 'description': t.get('description', t['name']), 'parameters': t.get('inputSchema') or {'type': 'object', 'properties': {}}}} for name, t in mapping.items()]
    limit = max(1, min(40, int(app.get('maxSteps', 8))))
    for step in range(limit + 1):
        check()
        if isinstance(messages[-1], AIMessage) and not messages[-1].tool_calls:
            return messages[-1].content
        response = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if response and response.tool_calls:
            for call in response.tool_calls:
                if any(isinstance(m, ToolMessage) and m.tool_call_id == call['id'] for m in messages): continue
                tool = mapping.get(call['name'])
                if not tool: raise ValueError('模型调用了未注册的工具')
                result = await tool_call(tool['id'], call['args'], app, prefix + ':' + call['id'])
                messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call['id']))
                obs.checkpoint(run['id'], checkpoint_key, messages_to_dict(messages))
        model_steps = sum(isinstance(m, AIMessage) for m in messages) - sum(m.get('role')=='assistant' for m in inputs.get('history', [])[-6:])
        if model_steps >= limit:
            raise ValueError('MAX_STEPS：已达到模型调用步数上限')
        response = await generation(app, messages, definitions)
        messages.append(response)
        obs.checkpoint(run['id'], checkpoint_key, messages_to_dict(messages))
        if not response.tool_calls:
            return response.content if isinstance(response.content, str) else json.dumps(response.content, ensure_ascii=False)
        repeated = [(m.tool_calls if isinstance(m, AIMessage) else None) for m in messages if isinstance(m, AIMessage) and m.tool_calls]
        if len(repeated) >= 3:
            fingerprints = [json.dumps([(c['name'], c['args']) for c in calls], sort_keys=True) for calls in repeated[-3:]]
            if len(set(fingerprints)) == 1: raise ValueError('NO_PROGRESS：连续重复工具调用，已停止')
    raise ValueError('MAX_STEPS：达到运行上限')


async def flow(app, inputs, nested=False):
    order = validate(app)
    stack = _stack.get()
    app_id = app['id']
    if app_id in stack or len(stack) >= 4: raise ValueError('流程工具递归调用或嵌套过深')
    token = _stack.set((*stack, app_id))
    try:
        graph = app['flow']; nodes = {n['id']: n for n in graph['nodes']}
        prefix = 'flow:' + ':'.join((*stack, app_id)) + ':'
        run = check(); state = run.get('checkpoint', {}).get(prefix + 'outputs', {})
        skipped = set(run.get('checkpoint', {}).get(prefix + 'skipped', []))
        async def execute_node(node_id):
            check()
            if node_id in state or node_id in skipped: return
            node = nodes[node_id]; kind = node['type']
            incoming = [e for e in graph.get('edges', []) if e['target'] == node_id]
            def active(edge):
                source = edge['source']
                if source in skipped: return False
                condition = edge.get('condition')
                result = state.get(source, {}).get('output', {})
                return condition in (None, '', 'always') or isinstance(result, dict) and str(result.get('branch')).lower() == str(condition).lower()
            if incoming and not any(active(e) for e in incoming):
                skipped.add(node_id)
                span = obs.Span('node', node.get('name', node_id), attributes={'nodeId': node_id, 'nodeType': kind})
                span.end(status='skipped'); obs.checkpoint(run['id'], prefix + 'skipped', list(skipped)); return
            values = {'input': inputs, **state}
            config = render({k: v for k, v in node.items() if k not in ('id', 'type', 'position', 'name')}, values)
            span = obs.Span('node', node.get('name', node_id), config, {'nodeId': node_id, 'nodeType': kind, 'definition': node, 'incomingEdges': incoming, 'contextBefore': values})
            try:
                with obs.scope(run['id'], span.value['id']):
                    if kind == 'start': result = inputs
                    elif kind in ('template', 'end'):
                        result = config.get('template', config.get('value', inputs.get('question', '')))
                    elif kind == 'assign': result = config.get('values', {})
                    elif kind == 'merge': result = {e['source']: state.get(e['source'], {}).get('output') for e in incoming if active(e)}
                    elif kind == 'condition':
                        value = config.get('value', '')
                        expected = config.get('equals', '')
                        matched = str(expected) in str(value) if config.get('operator') == 'contains' else value == expected
                        result = {'branch': 'true' if matched else 'false', 'value': value}
                    elif kind == 'extract':
                        match = re.search(str(config.get('pattern', '(.+)'))[:500], str(config.get('value', ''))[:50000])
                        result = match.groupdict() or match.groups() if match else {}
                    elif kind == 'approval':
                        approval(prefix + node_id, {'reason': config.get('message', '请确认继续流程'), 'input': config.get('value')})
                        result = config.get('value', True)
                    elif kind == 'retrieval':
                        from .retrieval import search
                        result, stages, mode = await asyncio.to_thread(search, config.get('kbIds', app.get('kbIds', [])), str(config.get('query', inputs.get('question', ''))), config.get('mode', 'keyword'), int(config.get('topK', 5)), bool(config.get('rerank', False)))
                    elif kind == 'tool': result = await tool_call(config['toolId'], config.get('arguments', {}), app, prefix + node_id)
                    elif kind == 'llm':
                        result = (await generation({**app, **{k: config[k] for k in ('modelId',) if config.get(k)}}, [SystemMessage(content=str(config.get('system', app.get('prompt', '你是可靠的业务助手。')))), HumanMessage(content=str(config.get('prompt', inputs.get('question', ''))))])).content
                    elif kind == 'agent': result = await agent(app, {'question': config.get('question', inputs.get('question', ''))}, prefix + node_id)
                    else: raise ValueError('不支持的节点')
                state[node_id] = {'output': obs.clean(result)}
                obs.checkpoint(run['id'], prefix + 'outputs', state)
                span.end(result)
            except Waiting:
                span.end(status='waiting_approval'); raise
            except BaseException as exc:
                span.end(status='failed', error=models.safe_error(exc)); raise
        while True:
            remaining = [i for i in order if i not in state and i not in skipped]
            if not remaining: break
            ready = [i for i in remaining if all(e['source'] in state or e['source'] in skipped for e in graph.get('edges', []) if e['target'] == i)]
            if not ready: raise ValueError('流程执行停滞，检查依赖与分支')
            limit = max(1, min(4, int(app.get('maxParallel', 3))))
            results = await asyncio.gather(*(execute_node(i) for i in ready[:limit]), return_exceptions=True)
            failures = [r for r in results if isinstance(r, BaseException)]
            if failures:
                raise next((r for r in failures if not isinstance(r, Waiting)), failures[0])
        outputs = [state[n['id']]['output'] for n in graph['nodes'] if n['type'] == 'end' and n['id'] in state]
        if not outputs: raise ValueError('没有可到达的结束输出，请检查分支条件')
        return outputs[0] if len(outputs) == 1 else outputs
    finally:
        _stack.reset(token)


async def external(app, inputs):
    config = bridge.public_config('runnerConnections', app['runnerId'])
    if not config.get('enabled', True): raise ValueError('外部运行器已停用')
    bridge.allow_network(config)
    key = bridge.secret(config['id']); rid = obs.current_run.get()
    span = obs.Span('external', config['name'], inputs, {'capability': config.get('capability', 'basic')})
    try:
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        async with httpx.AsyncClient(timeout=config.get('timeout', 120), follow_redirects=False) as client:
            async with client.stream('POST', config['url'], json={'input': inputs, 'runId': rid, 'appId': app['id'], 'remoteAppId': config.get('remoteAppId')}, headers=headers) as response:
                response.raise_for_status()
                if 'text/event-stream' in response.headers.get('content-type', ''):
                    output = ''; data_lines = []; bytes_seen = 0
                    async for line in response.aiter_lines():
                        check(); bytes_seen += len(line)
                        if bytes_seen > 5000000: raise ValueError('外部事件超过运行接收上限')
                        if line.startswith('data:'): data_lines.append(line[5:].strip())
                        elif not line and data_lines:
                            data = json.loads('\n'.join(data_lines)); data_lines = []
                            if data.get('type') == 'output.delta':
                                output += str(data.get('delta', '')); obs.patch(rid, liveOutput=output)
                            elif data.get('type') == 'error': raise ValueError(str(data.get('message', '远程执行失败')))
                            else:
                                obs.event(rid, 'remote.' + str(data.get('type', 'event')), data)
                                if data.get('remoteRunId'): obs.patch(rid, remoteRunId=data['remoteRunId'])
                                if data.get('type') == 'span': remote_span(rid, data)
                                if data.get('type') == 'usage': obs.usage(data.get('model', {}), data.get('usage', {}), request_id='remote:' + rid + ':' + str(data.get('requestId', db.uid())), source='remote')
                                if data.get('type') == 'result': output = data.get('output', output)
                    obs.patch(rid, capture='reported_events' if config.get('capability') == 'events' else 'basic')
                    result = output
                else:
                    await response.aread()
                    if len(response.content) > 2000000: raise ValueError('远程响应过大')
                    data = response.json()
                    if data.get('status') in ('failed', 'error'): raise ValueError(str(data.get('error', '远程运行失败')))
                    if 'output' not in data: raise ValueError('外部运行器应返回 output；异步运行器请使用事件适配契约')
                    result = data['output']
                    obs.patch(rid, remoteRunId=data.get('runId'), capture='basic')
                    if data.get('usage'): obs.usage(data.get('model', {}), data['usage'], request_id='remote:' + rid, source='remote')
        span.end(result)
        return result
    except BaseException as exc:
        span.end(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', error=models.safe_error(exc, key))
        if isinstance(exc, asyncio.CancelledError): raise
        raise SafeFailure(models.safe_error(exc,key),getattr(exc,'status_code',None)) from None


def remote_span(rid, data):
    remote_id = str(data.get('spanId', ''))[:128]
    if not remote_id: raise ValueError('外部 span 缺少 spanId')
    span = {'id': 'remote:' + rid + ':' + remote_id, 'runId': rid, 'parentId': 'remote:' + rid + ':' + str(data['parentId']) if data.get('parentId') else None, 'kind': data.get('kind', 'external'), 'name': data.get('name', remote_id), 'input': data.get('input'), 'output': data.get('output'), 'createdAt': data.get('occurredAt', db.now()), 'duration': data.get('duration'), 'status': data.get('status', 'succeeded'), 'source': 'remote', 'error': data.get('error')}
    obs.insert('obs_spans', span)


def enqueue(app, inputs, owner, session_id=None, debug=False):
    with db.pool.connection() as conn:
        version = db.get(conn, 'applicationVersions', app.get('publishedVersion')) if app.get('publishedVersion') and not debug else None
    definition = copy.deepcopy(version['definition'] if version else app)
    definition['toolSnapshots'] = {t['id']: t for t in bridge.catalog() if t['id'] in definition.get('toolIds', [])}
    with db.pool.connection() as conn:
        definition['skillSnapshots'] = {sid: db.require(conn,'skills',sid) for sid in definition.get('skillIds', [])}
        model_ids = {definition.get('modelId')} | {n.get('modelId') for n in definition.get('flow',{}).get('nodes',[])}
        definition['modelSnapshots'] = {mid: models.resolve_model(db.require(conn,'models',mid),conn) for mid in model_ids if mid}
    run = obs.start(definition.get('type', 'agent'), definition['name'], owner, app['id'], inputs, source=definition.get('runtimeSource', 'internal'), definition=definition, versionId=version['id'] if version else 'draft', sessionId=session_id, debug=debug)
    return run


async def execute(rid):
    run = obs.get_run(rid); app = run['definition']
    try:
        obs.patch(rid, status='running', startedAt=run.get('startedAt') or db.now(), pending=None)
        with obs.scope(rid):
            validate(app)
            async with asyncio.timeout(max(5, min(1800, int(app.get('timeout', 120))))):
                if app.get('runtimeSource') == 'external': output = await external(app, run['input'])
                elif app.get('type') == 'chatflow': output = await flow(app, run['input'])
                else: output = await agent(app, run['input'])
                check()
                obs.finish(rid, 'succeeded', output)
        save_chat(rid)
    except Waiting:
        save_chat(rid)
    except (Cancelled, asyncio.CancelledError):
        # Shutdown leaves in-flight external effects visible instead of automatically replaying them.
        latest = obs.get_run(rid)
        if latest.get('cancelRequested'):
            obs.finish(rid, 'cancelled', latest.get('liveOutput'), '用户取消；远程取消状态以服务端确认为准')
            save_chat(rid)
        else:
            obs.patch(rid, status='paused', capture='interrupted', error='运行器停止，可查看检查点后恢复；有副作用的在途工具需先核对状态')
    except BaseException as exc:
        obs.finish(rid, 'failed', error=models.safe_error(exc))
        save_chat(rid)


def save_chat(rid):
    run = obs.get_run(rid)
    if not run.get('sessionId'): return
    text = run.get('output')
    if text is None: text = '运行等待人工确认，请点击回答下方的链路进行处理。' if run['status']=='waiting_approval' else run.get('error') or '运行已结束。'
    if not isinstance(text, str): text = json.dumps(text, ensure_ascii=False)
    with db.pool.connection() as conn:
        row = conn.execute("SELECT data FROM resources WHERE kind='sessions' AND id=%s FOR UPDATE", (run['sessionId'],)).fetchone()
        if not row: return
        session = row['data']
        for message in session['messages']:
            if message.get('traceId') == rid:
                message.update(content=text, duration=run.get('duration'), stopped=run['status'] == 'cancelled', error=run.get('error'))
        if session.get('activeRun') == rid and run['status'] in obs.TERMINAL:
            session.pop('activeRun', None)
        db.put(conn, 'sessions', session)
        if run['status'] not in obs.TERMINAL: return
        db.put(conn, 'logs', {'id': rid, 'kind': 'chat', 'question': str(run['input'].get('question', '')), 'answer': text, 'assistantId': run['appId'], 'kbIds': run['definition'].get('kbIds', []), 'model': run['definition'].get('modelId', '外部运行器'), 'provider': run['source'], 'status': 'success' if run['status'] == 'succeeded' else 'stopped' if run['status'] == 'cancelled' else 'failed', 'inputTokens': None, 'outputTokens': None, 'duration': run.get('duration', 0), 'firstToken': None, 'createdAt': run['createdAt'], 'citations': [], 'stages': [], 'error': run.get('error')})


def prune_payloads():
    with db.pool.connection() as conn:
        configs = db.items(conn,'captureSettings')
        config = next((c for c in configs if c.get('retentionEnabled')), None)
        if not config: return
        from datetime import datetime,timedelta,timezone
        cutoff = datetime.now(timezone.utc)-timedelta(days=max(1,int(config.get('retentionDays',30))))
        conn.execute("UPDATE obs_runs SET data=(data-'input'-'output'-'definition'-'checkpoint') || %s::jsonb WHERE created_at<%s AND data->>'status' IN ('succeeded','failed','cancelled','partially_completed') AND NOT data ? 'payloadExpiredAt'",(Jsonb({'payloadExpiredAt':db.now(),'capture':'expired'}),cutoff))
        conn.execute("UPDATE obs_spans s SET data=s.data-'input'-'output' FROM obs_runs r WHERE s.run_id=r.id AND r.data ? 'payloadExpiredAt'")
        conn.execute("UPDATE obs_events e SET data=e.data-'payload' FROM obs_runs r WHERE e.run_id=r.id AND r.data ? 'payloadExpiredAt'")


async def dispatch():
    with db.pool.connection() as conn:
        conn.execute("UPDATE obs_runs SET data=jsonb_set(jsonb_set(data,'{status}','\"paused\"'),'{error}','\"进程重启，检查执行状态后恢复\"'),updated_at=now() WHERE data->>'status'='running' AND data ? 'definition'")
    last_prune = 0
    try:
        while True:
            if time.monotonic()-last_prune>3600:
                try:
                    prune_payloads()
                except Exception as exc:
                    failure=obs.start('system','观测留存清理异常',inputs={})
                    obs.finish(failure['id'],'failed',error=models.safe_error(exc))
                last_prune=time.monotonic()
            with db.pool.connection() as conn:
                rows = conn.execute("SELECT id,data FROM obs_runs WHERE data->>'status'='queued' AND data ? 'definition' ORDER BY created_at LIMIT 4 FOR UPDATE SKIP LOCKED").fetchall()
                for row in rows:
                    if len(_tasks) >= 3: break
                    if row['id'] in _tasks: continue
                    conn.execute("UPDATE obs_runs SET data=jsonb_set(data,'{status}','\"running\"'),updated_at=now() WHERE id=%s", (row['id'],))
                    task = asyncio.create_task(execute(row['id']))
                    _tasks[row['id']] = task
                    task.add_done_callback(lambda task, rid=row['id']: _tasks.pop(rid, None))
            await asyncio.sleep(.4)
    finally:
        for task in list(_tasks.values()): task.cancel()
        await asyncio.gather(*list(_tasks.values()), return_exceptions=True)
