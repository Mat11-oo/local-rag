"""Persistent run/span/event records; only leaf requests create usage ledger entries."""
import contextvars
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from psycopg.types.json import Jsonb
from . import db

current_run = contextvars.ContextVar('observation_run', default=None)
current_span = contextvars.ContextVar('observation_span', default=None)
TERMINAL = {'succeeded', 'failed', 'cancelled', 'partially_completed'}
SECRET = re.compile(r'api.?key|authorization|password|secret|access.?token|refresh.?token', re.I)


def clean(value, depth=0):
    if depth > 15:
        return '[嵌套过深]'
    if isinstance(value, dict):
        return {str(k): '[已脱敏]' if SECRET.search(str(k)) else clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v, depth + 1) for v in value[:500]]
    if isinstance(value, str):
        from .models import safe_error
        value = re.sub(r'Bearer\s+\S+', 'Bearer [已脱敏]', value, flags=re.I)
        value = re.sub(r'sk-[A-Za-z0-9_-]{8,}', '[密钥已隐藏]', value)
        return value[:100000] + ('\n[内容截断，原长度 %d]' % len(value) if len(value) > 100000 else '')
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:10000]


def setup(conn):
    for table in ('obs_runs', 'obs_spans', 'obs_usage'):
        conn.execute(f'CREATE TABLE IF NOT EXISTS {table}(id text PRIMARY KEY,run_id text NOT NULL,data jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now())')
        conn.execute(f'CREATE INDEX IF NOT EXISTS {table}_run ON {table}(run_id)')
        conn.execute(f'CREATE INDEX IF NOT EXISTS {table}_created ON {table}(created_at DESC)')
    conn.execute('CREATE TABLE IF NOT EXISTS obs_events(seq bigserial PRIMARY KEY,id text UNIQUE NOT NULL,run_id text NOT NULL,data jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now())')
    conn.execute('CREATE INDEX IF NOT EXISTS obs_events_run ON obs_events(run_id,seq)')
    conn.execute("CREATE INDEX IF NOT EXISTS obs_runs_state ON obs_runs((data->>'status'))")


def insert(table, value, conn=None):
    def write(c):
        c.execute(f'INSERT INTO {table}(id,run_id,data) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING', (value['id'], value.get('runId', value['id']), Jsonb(clean(value))))
    if conn:
        write(conn)
    else:
        with db.pool.connection() as c:
            write(c)
    return value


def get_run(rid):
    with db.pool.connection() as conn:
        row = conn.execute('SELECT data FROM obs_runs WHERE id=%s', (rid,)).fetchone()
    if not row:
        raise ValueError('运行记录不存在')
    return row['data']


def patch(rid, **values):
    with db.pool.connection() as conn:
        row = conn.execute('SELECT data FROM obs_runs WHERE id=%s FOR UPDATE', (rid,)).fetchone()
        if not row:
            raise ValueError('运行记录不存在')
        value = {**row['data'], **clean(values), 'updatedAt': db.now()}
        conn.execute('UPDATE obs_runs SET data=%s,updated_at=now() WHERE id=%s', (Jsonb(value), rid))
    return value


def checkpoint(rid, key, value):
    with db.pool.connection() as conn:
        row = conn.execute('SELECT data FROM obs_runs WHERE id=%s FOR UPDATE', (rid,)).fetchone()
        data = row['data']
        data.setdefault('checkpoint', {})[key] = clean(value)
        conn.execute('UPDATE obs_runs SET data=%s,updated_at=now() WHERE id=%s', (Jsonb(data), rid))


def event(rid, kind, value=None, eid=None, span_id=None):
    value = {'id': eid or db.uid(), 'runId': rid, 'spanId': span_id or current_span.get(), 'type': kind, 'occurredAt': db.now(), 'receivedAt': db.now(), 'payload': clean(value or {})}
    with db.pool.connection() as conn:
        conn.execute('INSERT INTO obs_events(id,run_id,data) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING', (value['id'], rid, Jsonb(value)))
    return value


def start(kind, name, owner='local', app_id=None, inputs=None, rid=None, **extra):
    rid = rid or db.uid()
    value = {'id': rid, 'runId': rid, 'kind': kind, 'name': name, 'ownerId': owner, 'appId': app_id, 'input': clean(inputs), 'status': 'queued', 'createdAt': db.now(), 'updatedAt': db.now(), 'source': 'internal', 'capture': 'complete', 'checkpoint': {}, **extra}
    insert('obs_runs', value)
    event(rid, 'run.created', {'kind': kind})
    return value


def finish(rid, status, output=None, error=None, **extra):
    value = get_run(rid)
    elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(value.get('startedAt') or value['createdAt'])).total_seconds())
    result = patch(rid, status=status, output=output, error=clean(error), endedAt=db.now(), duration=round(elapsed, 4), **extra)
    event(rid, 'run.' + status, {'error': error})
    with db.pool.connection() as conn:
        rules = db.items(conn, 'alertRules')
        for rule in rules:
            triggered = rule.get('enabled', True) and ((rule.get('metric') == 'failure' and status == 'failed') or (rule.get('metric') == 'duration' and elapsed > float(rule.get('threshold', 60))))
            if rule.get('enabled',True) and rule.get('metric')=='cost':
                amount=conn.execute("SELECT COALESCE(sum((data->>'cost')::numeric),0) AS amount FROM obs_usage WHERE run_id=%s AND data->>'currency'=%s",(rid,rule.get('currency','CNY'))).fetchone()['amount']
                triggered=float(amount)>float(rule.get('threshold',1))
            if triggered:
                db.put(conn, 'alerts', {'id': rid + '-' + rule['id'], 'runId': rid, 'ruleId': rule['id'], 'name': rule['name'], 'status': 'open', 'createdAt': db.now(), 'detail': error or f'耗时 {elapsed:.2f}s'})
    return result


@contextmanager
def scope(rid, parent=None):
    a = current_run.set(rid); b = current_span.set(parent)
    try:
        yield
    finally:
        current_span.reset(b); current_run.reset(a)


class Span:
    def __init__(self, kind, name, inputs=None, attributes=None, parent=None):
        self.run_id = current_run.get()
        self.value = {'id': db.uid(), 'runId': self.run_id, 'parentId': parent or current_span.get(), 'kind': kind, 'name': name, 'input': clean(inputs), 'attributes': clean(attributes or {}), 'status': 'running', 'createdAt': db.now()}
        self.finished = False
        if self.run_id:
            insert('obs_spans', self.value)
            event(self.run_id, 'span.started', {'name': name, 'kind': kind}, span_id=self.value['id'])

    def end(self, output=None, status='succeeded', error=None):
        if self.finished or not self.run_id:
            return
        self.finished = True
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(self.value['createdAt'])).total_seconds()
        self.value.update(output=clean(output), status=status, error=clean(error), endedAt=db.now(), duration=round(elapsed, 4))
        with db.pool.connection() as conn:
            conn.execute('UPDATE obs_spans SET data=%s,updated_at=now() WHERE id=%s', (Jsonb(self.value), self.value['id']))
        event(self.run_id, 'span.' + status, {'error': error}, span_id=self.value['id'])

    def __enter__(self):
        self.token = current_span.set(self.value['id'])
        return self

    def __exit__(self, kind, exc, traceback):
        self.end(status='failed' if exc else 'succeeded', error=str(exc) if exc else None)
        current_span.reset(self.token)


def usage(model, counts, span_id=None, request_id=None, source='provider'):
    rid = current_run.get()
    if not rid:
        return
    counts = counts or {}
    entry = {'id': request_id or db.uid(), 'runId': rid, 'spanId': span_id or current_span.get(), 'modelId': model.get('modelId'), 'modelConfigId': model.get('id'), 'provider': model.get('provider'), 'providerConfigId': model.get('providerConfigId'), 'inputTokens': counts.get('inputTokens'), 'outputTokens': counts.get('outputTokens'), 'rawUsage': counts.get('rawUsage', {}), 'source': source, 'createdAt': db.now(), 'cost': None, 'currency': None, 'costStatus': 'unknown'}
    with db.pool.connection() as conn:
        rules = [r for r in db.items(conn, 'priceRules') if r.get('modelId') == entry['modelId'] and (not r.get('providerConfigId') or r['providerConfigId'] == entry['providerConfigId']) and r.get('effectiveAt', '') <= entry['createdAt'] and r.get('enabled', True)]
    rules.sort(key=lambda r: r.get('effectiveAt', ''), reverse=True)
    if rules and (entry['inputTokens'] is not None or entry['outputTokens'] is not None):
        rule = rules[0]
        cost = Decimal(0)
        complete = True
        for field, price in [('inputTokens', 'inputPerMillion'), ('outputTokens', 'outputPerMillion')]:
            count = entry[field]
            if count is None:
                if model.get('type') in ('Embedding', 'Rerank') and field == 'outputTokens':
                    continue
                complete = False
                continue
            if rule.get(price) is None:
                complete = False
            else:
                cost += Decimal(str(count)) * Decimal(str(rule[price])) / 1000000
        entry.update(cost=float(cost), currency=rule.get('currency', 'CNY'), priceRuleId=rule['id'], priceSnapshot=rule, costStatus='estimated' if complete else 'partial')
    insert('obs_usage', entry)
    event(rid, 'usage.recorded', {'entryId': entry['id']}, span_id=entry['spanId'])
    return entry


def legacy_model(log):
    rid = current_run.get()
    standalone = not rid
    if standalone:
        rid = start('model', log.get('question', '模型服务请求'), 'model-service', inputs={'summary': log.get('question')}, capture='summary_only')['id']
        patch(rid, status='running', startedAt=db.now())
    with scope(rid, current_span.get()):
        _legacy_model(log)
    if standalone:
        finish(rid, 'failed' if log.get('status') == 'failed' else 'succeeded', log.get('answer'), log.get('error'))


def _legacy_model(log):
    model = {'id': log.get('modelConfigId'), 'modelId': log.get('model'), 'provider': log.get('provider'), 'providerConfigId': log.get('providerConfigId'), 'type': log.get('modelType')}
    span = Span('model', log.get('question', '模型请求'), {'summary': log.get('question'), 'capture': 'summary_only'}, {'model': model})
    span.end(log.get('answer'), 'failed' if log.get('status') == 'failed' else 'succeeded', log.get('error'))
    usage(model, log, span.value['id'], request_id=log['id'])
