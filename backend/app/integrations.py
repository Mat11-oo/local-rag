"""MCP connections, HTTP tools, skills and external runner configuration."""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, parse_qsl
import httpx
from psycopg.types.json import Jsonb
from . import db, models, telemetry as obs

KINDS = {'mcpConnections', 'httpTools', 'skills', 'runnerConnections', 'priceRules', 'alertRules', 'captureSettings'}


def secret(rid):
    with db.pool.connection() as conn:
        row = conn.execute('SELECT encrypted FROM model_secrets WHERE id=%s', ('integration-' + rid,)).fetchone()
    return models.cipher().decrypt(row['encrypted'].encode()).decode() if row else ''


def url(value):
    parsed = urlsplit(str(value))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('请填写不含账号、密钥或片段的 HTTP(S) 地址')
    if any(obs.SECRET.search(k) for k, _ in parse_qsl(parsed.query)):
        raise ValueError('请通过密钥字段配置鉴权，不要将密钥放入 URL')
    return value


def save(kind, rid, body):
    if kind not in KINDS or not re.fullmatch(r'[\w-]{1,128}', rid):
        raise ValueError('配置类型或 ID 无效')
    value = {k: v for k, v in body.items() if k not in ('secret', 'apiKey', 'token', 'hasSecret', 'tools', 'capabilities', 'status', 'lastError')}
    if not str(value.get('name', '')).strip():
        raise ValueError('名称不可为空')
    value.update(id=rid, updatedAt=db.now())
    value['timeout'] = max(1, min(300, int(value.get('timeout', 30))))
    if kind == 'mcpConnections':
        if value.get('transport', 'http') == 'stdio':
            if not str(value.get('command', '')).strip() or not isinstance(value.get('args', []), list):
                raise ValueError('本地 MCP 需要启动命令和参数数组')
        else:
            url(value.get('url'))
    if kind in ('runnerConnections', 'httpTools'):
        url(value.get('url'))
        if value.get('cancelUrl'): url(value['cancelUrl'])
    if kind == 'httpTools' and value.get('method', 'GET') not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        raise ValueError('HTTP 方法无效')
    if kind == 'captureSettings':
        value['retentionDays'] = max(1,min(3650,int(value.get('retentionDays',30))))
    if kind == 'skills':
        content = str(value.get('content', ''))
        if not content or len(content) > 50000:
            raise ValueError('Skill 说明须为 1–50000 字符')
        value['fingerprint'] = __import__('hashlib').sha256(content.encode()).hexdigest()
        value['version'] = str(value.get('version', '1'))[:80]
    if kind == 'priceRules':
        if not value.get('modelId') or value.get('currency', 'CNY') not in ('CNY', 'USD', 'EUR'):
            raise ValueError('请选择模型和支持的币种')
        for key in ('inputPerMillion', 'outputPerMillion'):
            if value.get(key) is not None and float(value[key]) < 0:
                raise ValueError('单价不可为负数')
        from datetime import datetime, timezone
        try:
            effective = datetime.fromisoformat(value.get('effectiveAt') or db.now())
            if effective.tzinfo is None: raise ValueError()
            value['effectiveAt'] = effective.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError): raise ValueError('生效时间需要包含时区')
    with db.pool.connection() as conn:
        old = db.get(conn, kind, rid) or {}
        if kind == 'priceRules' and old:
            raise ValueError('价格版本不可覆盖，请新建价格规则以保留历史口径')
        if kind == 'mcpConnections':
            value['approvedFingerprints'] = {tool['name']: __import__('hashlib').sha256(json.dumps(tool.get('inputSchema', {}), sort_keys=True).encode()).hexdigest() for tool in old.get('tools', []) if tool['name'] in value.get('allowedTools', [])}
        supplied = body.get('secret')
        if supplied is not None and str(supplied).strip():
            encrypted = models.cipher().encrypt(str(supplied).strip().encode()).decode()
            conn.execute('INSERT INTO model_secrets(id,encrypted) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET encrypted=EXCLUDED.encrypted', ('integration-' + rid, encrypted))
            value['hasSecret'] = True
        else:
            value['hasSecret'] = old.get('hasSecret', False)
        changed = any(old.get(k) != value.get(k) for k in ('url','command','args','env','transport','timeout')) or bool(supplied)
        db.put(conn, kind, {**old, **value, 'status': ('unverified' if changed else old.get('status','unverified')) if kind in ('mcpConnections', 'runnerConnections') else 'configured'})
    return public_config(kind, rid)


def public_config(kind, rid=None):
    with db.pool.connection() as conn:
        return db.require(conn, kind, rid) if rid else db.items(conn, kind)


@asynccontextmanager
async def mcp_session(config):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    from datetime import timedelta
    if any(obs.SECRET.search(str(k)) for k in config.get('env', {})):
        raise ValueError('敏感环境变量请通过密钥字段注入')
    key = secret(config['id'])
    timeout = config.get('timeout', 30)
    if config.get('transport') == 'stdio':
        import os
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'TMPDIR', 'SYSTEMROOT')}
        env.update({str(k): str(v) for k, v in config.get('env', {}).items()})
        if key:
            env[config.get('secretEnv', 'API_KEY')] = key
        params = StdioServerParameters(command=config['command'], args=config.get('args', []), env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                yield session
    else:
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        async with streamablehttp_client(config['url'], headers=headers, timeout=timedelta(seconds=timeout)) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                yield session


async def discover(rid):
    config = public_config('mcpConnections', rid)
    try:
        async with asyncio.timeout(config.get('timeout', 30)):
            async with mcp_session(config) as client:
                response = await client.list_tools()
                tools = [t.model_dump(mode='json') for t in response.tools]
                resources, prompts = [], []
                try:
                    resources = [r.model_dump(mode='json') for r in (await client.list_resources()).resources]
                except Exception:
                    pass
                try:
                    prompts = [p.model_dump(mode='json') for p in (await client.list_prompts()).prompts]
                except Exception:
                    pass
        config.update(tools=tools, resources=resources, prompts=prompts, status='connected', lastError=None, discoveredAt=db.now())
    except Exception as exc:
        config.update(status='failed', lastError=models.safe_error(exc, secret(rid)))
    with db.pool.connection() as conn:
        db.put(conn, 'mcpConnections', config)
    return config


def catalog():
    items = [{'id': 'knowledge_search', 'name': 'knowledge_search', 'description': '检索当前应用关联的已发布知识资料', 'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}, 'kind': 'builtin'}]
    with db.pool.connection() as conn:
        for service in db.items(conn, 'mcpConnections'):
            if not service.get('enabled', True) or service.get('status') != 'connected':
                continue
            for tool in service.get('tools', []):
                fingerprint = __import__('hashlib').sha256(json.dumps(tool.get('inputSchema', {}), sort_keys=True).encode()).hexdigest()
                if tool['name'] in service.get('allowedTools', []) and service.get('approvedFingerprints', {}).get(tool['name']) == fingerprint:
                    items.append({**tool, 'id': 'mcp:' + service['id'] + ':' + tool['name'], 'kind': 'mcp', 'serviceId': service['id'], 'requiresApproval': tool['name'] not in service.get('autoApproveTools', [])})
        for tool in db.items(conn, 'httpTools'):
            if tool.get('enabled', True):
                items.append({**tool, 'id': 'http:' + tool['id'], 'kind': 'http', 'inputSchema': tool.get('inputSchema') or {'type': 'object', 'properties': {}}, 'requiresApproval': tool.get('requiresApproval', True)})
        for app in db.items(conn, 'assistants'):
            if app.get('type') == 'chatflow' and app.get('publishedVersion') and app.get('asTool'):
                items.append({'id': 'flow:' + app['id'], 'kind': 'flow', 'name': app['name'], 'description': app.get('description', ''), 'inputSchema': {'type': 'object', 'properties': {'question': {'type': 'string'}}, 'required': ['question']}, 'requiresApproval': True})
    return items


def validate_arguments(schema, arguments):
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(schema or {'type': 'object'}).iter_errors(arguments))
    if errors:
        raise ValueError('工具参数不符合结构：' + errors[0].message)


def allow_network(config):
    target = config.get('url')
    if target and urlsplit(target).hostname not in ('127.0.0.1', 'localhost', '::1'):
        models.require_external()


async def call(tool_id, arguments, app):
    tool = next((t for t in catalog() if t['id'] == tool_id), None)
    if not tool or tool_id not in (app.get('toolIds', []) + ['knowledge_search']):
        raise ValueError('工具未授权、已停用或目录已变化')
    validate_arguments(tool.get('inputSchema'), arguments)
    if tool_id == 'knowledge_search':
        from .retrieval import search
        result, stages, mode = await asyncio.to_thread(search, app.get('kbIds', []), arguments.get('query', ''), 'keyword', app.get('topK', 5), False)
        return {'results': result, 'mode': mode}
    if tool['kind'] == 'flow':
        from .runtime import flow
        with db.pool.connection() as conn:
            target = db.require(conn, 'assistants', tool_id[5:])
            version = db.require(conn, 'applicationVersions', target['publishedVersion'])
        return await flow(version['definition'], {'question': arguments.get('question', '')}, nested=True)
    if tool['kind'] == 'mcp':
        config = public_config('mcpConnections', tool['serviceId'])
        allow_network(config)
        async with asyncio.timeout(config.get('timeout', 30)):
            async with mcp_session(config) as client:
                result = await client.call_tool(tool['name'], arguments)
                if result.isError:
                    raise ValueError('MCP 工具返回错误：' + json.dumps(result.model_dump(mode='json'), ensure_ascii=False)[:2000])
                return result.model_dump(mode='json')
    config = public_config('httpTools', tool_id[5:])
    allow_network(config)
    key = secret(config['id'])
    async with httpx.AsyncClient(timeout=config.get('timeout', 30), follow_redirects=False) as client:
        method = config.get('method', 'GET')
        response = await client.request(method, config['url'], headers={'Authorization': 'Bearer ' + key} if key else {}, params=arguments if method == 'GET' else None, json=arguments if method != 'GET' else None)
        response.raise_for_status()
        if len(response.content) > 2000000:
            raise ValueError('工具响应超过 2 MB，请在工具端限制结果')
        return response.json() if 'json' in response.headers.get('content-type', '') else response.text
