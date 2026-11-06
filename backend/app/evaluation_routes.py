"""Manual production-case curation. Source snapshots stay independent of log retention."""
import csv
import io
import json
from fastapi import APIRouter, Request
from fastapi.responses import Response
from . import db, telemetry as obs
from .runtime_routes import edit, owner

router = APIRouter(prefix='/api/evaluation')


def text(value, limit=10000):
    if not isinstance(value, str): raise ValueError('文本格式无效')
    if len(value) > limit: raise ValueError(f'文本不可超过 {limit} 字')
    return value.strip()


def annotations(body):
    label = body.get('label', 'badcase')
    if label not in ('goodcase', 'badcase'): raise ValueError('请选择 goodcase 或 badcase')
    status = body.get('reviewStatus', 'pending')
    if status not in ('pending', 'reviewed'): raise ValueError('复核状态无效')
    tags = body.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 20: raise ValueError('标签最多20个')
    return {'label': label, 'reviewStatus': status, 'tags': list(dict.fromkeys(text(t, 60) for t in tags if t)), 'note': text(body.get('note', '')), 'expectedAnswer': text(body.get('expectedAnswer', ''), 30000)}


def source_snapshot(kind, sid, request):
    if kind not in ('run', 'log'): raise ValueError('来源类型无效')
    with db.pool.connection() as conn:
        row = conn.execute('SELECT data FROM obs_runs WHERE id=%s', (sid,)).fetchone()
        if kind == 'run' or row:
            if not row: raise ValueError('运行记录不存在')
            run = row['data']
            if run['status'] not in obs.TERMINAL: raise ValueError('请等待运行结束再收录，确保输入输出固定')
            run = {k: v for k, v in run.items() if k not in ('definition', 'checkpoint', 'approvals', 'pending')}
            spans = [r['data'] for r in conn.execute('SELECT data FROM obs_spans WHERE run_id=%s ORDER BY created_at LIMIT 301', (sid,))]
            events = [r['data'] for r in conn.execute('SELECT data FROM obs_events WHERE run_id=%s ORDER BY seq LIMIT 101', (sid,))]
            usage = [r['data'] for r in conn.execute('SELECT data FROM obs_usage WHERE run_id=%s ORDER BY created_at LIMIT 501', (sid,))]
            log = db.get(conn, 'logs', sid)
            session = db.get(conn, 'sessions', run.get('sessionId', ''))
            messages = session.get('messages', []) if session else []
            index = next((i for i, m in enumerate(messages) if m.get('traceId') == sid), None)
            # Keep only the original context through this answer, excluding later turns.
            conversation = messages[max(0, index - 12):index + 1] if index is not None else []
            snap = obs.clean({'run': run, 'spans': spans[:300], 'events': events[:100], 'usage': usage[:500], 'citations': (log or {}).get('citations', []), 'conversation': conversation, 'limits': {'spansTruncated': len(spans)>300, 'eventsTruncated': len(events)>100, 'usageTruncated': len(usage)>500}})
            while len(json.dumps(snap, ensure_ascii=False).encode()) > 2000000 and (snap['events'] or snap['spans'] or snap['usage']):
                if snap['events']: snap['events'].pop(); snap['limits']['eventsTruncated'] = True
                elif snap['spans']: snap['spans'].pop(); snap['limits']['spansTruncated'] = True
                else: snap['usage'].pop(); snap['limits']['usageTruncated'] = True
            inputs, output = run.get('input'), run.get('output')
            return {'sourceKind': 'run', 'sourceId': sid, 'runId': sid, 'appId': run.get('appId', ''), 'appName': run.get('name', ''), 'sourceCreatedAt': run.get('createdAt'), 'sourceStatus': run['status'], 'input': inputs, 'output': output, 'snapshot': snap, 'sourceKey': 'run:' + sid}
        log = db.require(conn, 'logs', sid)
        if log.get('kind') != 'chat': raise ValueError('历史回流仅支持对话日志')
        return obs.clean({'sourceKind': 'log', 'sourceId': sid, 'appId': log.get('assistantId', ''), 'appName': (db.get(conn, 'assistants', log.get('assistantId', '')) or {}).get('name', '历史对话'), 'sourceCreatedAt': log.get('createdAt'), 'sourceStatus': log.get('status'), 'input': log.get('question'), 'output': log.get('answer'), 'snapshot': {'log': log, 'capture': 'legacy_summary'}, 'sourceKey': 'log:' + sid})


@router.get('/source/{kind}/{sid}')
def preview(kind: str, sid: str, request: Request):
    edit(request, True)
    result = source_snapshot(kind, sid, request)
    return {k: v for k, v in result.items() if k != 'snapshot'}


@router.get('/datasets')
def datasets(request: Request):
    edit(request, True)
    with db.pool.connection() as conn:
        rows = conn.execute("SELECT d.data, count(c.id) FILTER (WHERE coalesce(c.data->>'archived','false')='false') AS total, count(c.id) FILTER (WHERE c.data->>'label'='goodcase' AND coalesce(c.data->>'archived','false')='false') AS good, count(c.id) FILTER (WHERE c.data->>'label'='badcase' AND coalesce(c.data->>'archived','false')='false') AS bad FROM resources d LEFT JOIN resources c ON c.kind='evaluationCases' AND c.data->>'datasetId'=d.id WHERE d.kind='evaluationDatasets' GROUP BY d.id,d.data,d.created_at ORDER BY d.created_at DESC").fetchall()
    return [{'total': r['total'], 'good': r['good'], 'bad': r['bad'], **r['data']} for r in rows]


@router.post('/datasets')
def create_dataset(body: dict, request: Request):
    edit(request, True)
    name = text(body.get('name', ''), 100)
    if not name: raise ValueError('请输入评测集名称')
    value = {'id': db.uid(), 'name': name, 'description': text(body.get('description', ''), 2000), 'createdAt': db.now(), 'updatedAt': db.now(), 'createdBy': owner(request)}
    with db.pool.connection() as conn: db.put(conn, 'evaluationDatasets', value)
    return value


@router.put('/datasets/{did}')
def update_dataset(did: str, body: dict, request: Request):
    edit(request, True)
    name = text(body.get('name', ''), 100)
    if not name: raise ValueError('请输入评测集名称')
    with db.pool.connection() as conn:
        conn.execute("SELECT id FROM resources WHERE kind='evaluationDatasets' AND id=%s FOR UPDATE", (did,))
        value = db.require(conn, 'evaluationDatasets', did)
        value.update(name=name, description=text(body.get('description', ''), 2000), updatedAt=db.now())
        db.put(conn, 'evaluationDatasets', value)
    return value


@router.post('/cases')
def collect(body: dict, request: Request):
    edit(request, True)
    note = annotations(body)
    did = str(body.get('datasetId', ''))
    src = source_snapshot(str(body.get('sourceKind', 'run')), str(body.get('sourceId', '')), request)
    with db.pool.connection() as conn:
        # Lock the parent so simultaneous clicks cannot create duplicate memberships.
        conn.execute("SELECT id FROM resources WHERE kind='evaluationDatasets' AND id=%s FOR UPDATE", (did,))
        db.require(conn, 'evaluationDatasets', did)
        existing = conn.execute("SELECT data FROM resources WHERE kind='evaluationCases' AND data->>'datasetId'=%s AND data->>'sourceKey'=%s", (did, src['sourceKey'])).fetchone()
        if existing: return {'case': existing['data'], 'duplicate': True}
        value = obs.clean({**src, **note, 'id': db.uid(), 'datasetId': did, 'createdAt': db.now(), 'updatedAt': db.now(), 'createdBy': owner(request), 'archived': False})
        db.put(conn, 'evaluationCases', value)
    return {'case': value, 'duplicate': False}


def case_query(datasetId, label, reviewStatus, q, archived, start, end, appId):
    clause = "kind='evaluationCases' AND coalesce(data->>'archived','false')=%s"
    args = ['true' if archived else 'false']
    for field, value in [('datasetId', datasetId), ('label', label), ('reviewStatus', reviewStatus), ('appId', appId)]:
        if value: clause += f" AND data->>'{field}'=%s"; args.append(value)
    for field, op, value in [('createdAt', '>=', start), ('createdAt', '<', end)]:
        if value: 
            from datetime import datetime
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None: raise ValueError('时间筛选需要时区')
            clause += f" AND (data->>'{field}')::timestamptz {op} %s"; args.append(parsed)
    if q:
        clause += " AND (data->>'input' ILIKE %s OR data->>'output' ILIKE %s OR data->>'note' ILIKE %s OR data->>'tags' ILIKE %s OR data->>'appName' ILIKE %s OR data->>'sourceId' ILIKE %s)"
        args.extend(['%' + q + '%'] * 6)
    return clause, args


@router.get('/cases')
def list_cases(request: Request, datasetId: str = '', label: str = '', reviewStatus: str = '', q: str = '', archived: bool = False, start: str = '', end: str = '', appId: str = '', page: int = 1, size: int = 20, export: str = ''):
    edit(request, True)
    clause, args = case_query(datasetId, label, reviewStatus, q, archived, start, end, appId)
    size = max(1, min(size, 100)); page = max(1, page)
    with db.pool.connection() as conn:
        total = conn.execute('SELECT count(*) AS n FROM resources WHERE ' + clause, args).fetchone()['n']
        stats = conn.execute("SELECT count(*) FILTER (WHERE data->>'label'='goodcase') AS good,count(*) FILTER (WHERE data->>'label'='badcase') AS bad,count(*) FILTER (WHERE data->>'reviewStatus'='pending') AS pending FROM resources WHERE " + clause, args).fetchone()
        if export:
            if export not in ('csv', 'jsonl'): raise ValueError('导出格式无效')
            if total > 10000: raise ValueError('单次导出最多10000条，请缩小筛选范围')
            rows = conn.execute('SELECT data FROM resources WHERE ' + clause + ' ORDER BY created_at DESC LIMIT 10000', args)
        else:
            rows = conn.execute("SELECT data - 'snapshot' AS data FROM resources WHERE " + clause + ' ORDER BY created_at DESC LIMIT %s OFFSET %s', [*args, size, (page - 1)*size])
        values = [r['data'] for r in rows]
    if export == 'jsonl':
        return Response('\n'.join(json.dumps(v, ensure_ascii=False) for v in values), media_type='application/x-ndjson', headers={'Content-Disposition': 'attachment; filename=local-rag-cases.jsonl'})
    if export == 'csv':
        stream = io.StringIO(); writer = csv.writer(stream)
        fields = ['id', 'datasetId', 'label', 'reviewStatus', 'input', 'output', 'expectedAnswer', 'note', 'tags', 'appName', 'sourceKind', 'sourceId', 'sourceCreatedAt', 'createdAt']
        writer.writerow(fields)
        for value in values:
            cells = [json.dumps(value.get(k), ensure_ascii=False) if isinstance(value.get(k), (dict, list)) else str(value.get(k) or '') for k in fields]
            writer.writerow(["'"+c if c.lstrip()[:1] in ('=', '+', '-', '@') else c for c in cells])
        return Response('\ufeff' + stream.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=local-rag-cases.csv'})
    return {'items': values, 'total': total, 'page': page, 'stats': stats}


@router.get('/cases/{cid}')
def detail(cid: str, request: Request):
    edit(request, True)
    with db.pool.connection() as conn: return db.require(conn, 'evaluationCases', cid)


@router.put('/cases/{cid}')
def update_case(cid: str, body: dict, request: Request):
    edit(request, True)
    with db.pool.connection() as conn:
        conn.execute("SELECT id FROM resources WHERE kind='evaluationCases' AND id=%s FOR UPDATE", (cid,))
        value = db.require(conn, 'evaluationCases', cid)
        if 'datasetId' in body and body['datasetId'] != value['datasetId']: raise ValueError('样本来源与所属评测集不可覆盖，请在目标评测集中重新收录')
        fields = annotations({**value, **body})
        value.update(obs.clean(fields), updatedAt=db.now(), updatedBy=owner(request))
        if 'archived' in body:
            if not isinstance(body['archived'], bool): raise ValueError('归档状态无效')
            value['archived'] = body['archived']
        db.put(conn, 'evaluationCases', value)
    return value
