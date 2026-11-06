"""Real PostgreSQL/filesystem integration; cloud adapters use an isolated HTTP contract server."""
import io
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from app import db
from app.main import app
from app.worker import run_one


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).resolve().parents[2] / '.data/database.json').read_text())
    schema = 'test_' + uuid.uuid4().hex
    with psycopg.connect(config['url'], autocommit=True) as connection:
        connection.execute('CREATE SCHEMA ' + schema)
    monkeypatch.setenv('DATABASE_URL', make_conninfo(config['url'], options='-c search_path=' + schema + ',public'))
    monkeypatch.setattr(db, 'DATA', tmp_path)
    with TestClient(app, headers={'X-Browser-Id': 'test-browser', 'X-Role': 'admin'}) as value:
        yield value
    with psycopg.connect(config['url'], autocommit=True) as connection:
        connection.execute('DROP SCHEMA ' + schema + ' CASCADE')


def process_job():
    job = db.claim_job()
    assert job, 'a persisted job should be claimable'
    run_one(job)


def upload(client, name, data):
    response = client.post('/api/knowledge/default-kb/upload', files={'file': (name, data)}, data={'options': json.dumps({'chunkSize': 400, 'overlap': 40})})
    assert response.status_code == 200, response.text
    rid = response.json()['documentId']
    process_job()
    return rid


def document(client, rid):
    return next(item for item in client.get('/api/workspace').json()['documents'] if item['id'] == rid)


def publish(client, rid, mode='keyword'):
    result = client.post(f'/api/documents/{rid}/build', json={'indexMode': mode})
    assert result.status_code == 200, result.text
    process_job()
    assert document(client, rid)['status'] == 'ready', document(client, rid)


def test_real_md_index_scope_edit_and_persistence(client):
    content = '# 远程办公制度\n员工每周可申请两天远程办公，须经直属主管审批。制度编号 KH2026REAL。'.encode()
    rid = upload(client, '真实解析验证.md', content)
    doc = document(client, rid)
    assert doc['status'] == 'parsed' and 'KH2026REAL' in doc['chunks'][0]['text']
    assert client.get(f'/api/documents/{rid}/file').content == content
    assert client.post('/api/knowledge/default-kb/upload', files={'file': ('重复.md', content)}).status_code == 422
    publish(client, rid)
    result = client.post('/api/search', json={'kbIds': ['default-kb'], 'query': '远程办公主管审批', 'mode': 'keyword'}).json()
    assert result['results'] and result['results'][0]['documentId'] == rid
    assert 'KH2026REAL' in result['results'][0]['text']
    doc['enabled'] = False
    assert client.post('/api/workspace/mutations', json={'operations': [{'kind': 'documents', 'id': rid, 'action': 'put', 'value': doc}]}).status_code == 200
    assert not client.post('/api/search', json={'kbIds': ['default-kb'], 'query': '远程办公', 'mode': 'keyword'}).json()['results']
    doc['enabled'] = True; doc['chunks'][0]['text'] = '修订制度：每周三天远程办公，编号 UPDATED2026。'
    assert client.post('/api/workspace/mutations', json={'operations': [{'kind': 'documents', 'id': rid, 'action': 'put', 'value': doc}]}).status_code == 200
    process_job()
    assert 'UPDATED2026' in client.post('/api/search', json={'kbIds': ['default-kb'], 'query': 'UPDATED2026', 'mode': 'keyword'}).json()['results'][0]['text']
    assert not client.post('/api/search', json={'kbIds': ['other-kb'], 'query': 'UPDATED2026', 'mode': 'keyword'}).json()['results']
    assert db.snapshot('test-browser')['documents'][0]['id'] == rid


@pytest.mark.parametrize('kind', ['docx', 'xlsx', 'xls', 'csv', 'pdf'])
def test_native_file_formats(client, kind):
    data = io.BytesIO()
    if kind == 'docx':
        from docx import Document
        doc = Document(); doc.add_heading('Safety policy', 1); doc.add_paragraph('Native format VERIFY123.')
        table = doc.add_table(rows=2, cols=2); table.cell(0, 0).text = 'Item'; table.cell(0, 1).text = 'Value'; table.cell(1, 0).text = 'Safety'; table.cell(1, 1).text = 'VERIFY123'; doc.save(data)
    elif kind == 'xlsx':
        from openpyxl import Workbook
        book = Workbook(); book.active.title = '规则'; book.active.append(['项目', '数值']); book.active.append(['验证', 'VERIFY123']); book.create_sheet('其他').append(['多工作表', '保留']); book.save(data)
    elif kind == 'xls':
        import xlwt
        book = xlwt.Workbook(); sheet = book.add_sheet('Legacy'); sheet.write(0, 0, 'Item'); sheet.write(0, 1, 'Value'); sheet.write(1, 0, 'Legacy'); sheet.write(1, 1, 'VERIFY123'); book.save(data)
    elif kind == 'pdf':
        from reportlab.pdfgen.canvas import Canvas
        pdf = Canvas(data); pdf.drawString(80, 700, 'Native format VERIFY123.'); pdf.save()
    else:
        data.write('项目,数值\n测试,VERIFY123\n'.encode('utf-8-sig'))
    rid = upload(client, 'fixture.' + kind, data.getvalue())
    doc = document(client, rid)
    assert doc['status'] == 'parsed', doc
    assert any('VERIFY123' in chunk['text'] for chunk in doc['chunks'])
    if kind == 'docx':
        assert any(chunk['kind'] == 'table' for chunk in doc['chunks'])
        assert all(not chunk.get('page') for chunk in doc['chunks'])
    if kind == 'xlsx':
        assert {chunk['sheet'] for chunk in doc['chunks']} == {'规则', '其他'}
    publish(client, rid)


def test_no_fake_ocr_and_missing_credentials(client):
    from PIL import Image
    data = io.BytesIO(); Image.new('RGB', (50, 50), 'white').save(data, 'PNG')
    rid = upload(client, 'photo.png', data.getvalue())
    doc = document(client, rid)
    assert doc['status'] == 'failed' and not doc['chunks'] and 'OCR' in doc['error']
    assert client.post('/api/models/llm-qwen/test').status_code == 422
    assert client.post('/api/chat/stream', json={'assistantId': 'assistant-general', 'question': '测试'}).status_code == 422
    assert client.post('/api/search', json={'kbIds': ['default-kb'], 'query': 'x', 'mode': 'vector'}).status_code == 422
    assert client.get('/api/workspace', headers={'X-Role': 'user'}).json()['logs'] == []


@pytest.fixture
def cloud_contract():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            calls.append((self.path, body))
            if self.headers.get('Authorization') == 'Bearer rejected-test-key':
                self.send_response(401); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(b'{"error":{"message":"invalid rejected-test-key"}}'); return
            if self.path.endswith('/embeddings'):
                dim = body.get('dimensions', 4)
                data = {'data': [{'index': index, 'embedding': [float((index + i) % 3 + 1) for i in range(dim)]} for index, _ in enumerate(body['input'])], 'usage': {'prompt_tokens': 12, 'total_tokens': 12}}
            elif 'rerank' in self.path:
                results = [{'index': 0, 'relevance_score': 0.95}]
                data = {'output': {'results': results}, 'usage': {'total_tokens': 15}} if 'services/' in self.path else {'results': results, 'usage': {'total_tokens': 15}}
            else:
                if body.get('stream'):
                    chunks = [{'id': 'contract', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'contract-llm', 'choices': [{'index': 0, 'delta': {'content': '依据上传资料，员工可申请远程办公。[1]'}, 'finish_reason': None}]}, {'id': 'contract', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'contract-llm', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}, {'id': 'contract', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'contract-llm', 'choices': [], 'usage': {'prompt_tokens': 37, 'completion_tokens': 11, 'total_tokens': 48}}]
                    raw = ''.join('data: ' + json.dumps(item) + '\n\n' for item in chunks) + 'data: [DONE]\n\n'
                    encoded = raw.encode(); self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Content-Length', str(len(encoded))); self.end_headers(); self.wfile.write(encoded); return
                data = {'id': 'contract', 'object': 'chat.completion', 'created': 1, 'model': 'contract-llm', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '连接成功'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}}
            raw = json.dumps(data).encode(); self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', calls
    server.shutdown(); server.server_close(); thread.join()


def configure(client, base, mid, kind, provider='AIHubMix', key='fixture-secret-key'):
    import hashlib
    pid = 'contract-provider-' + hashlib.sha256((base + provider + key).encode()).hexdigest()[:12]
    configured = client.put('/api/providers/' + pid, json={'name': pid, 'provider': provider, 'baseUrl': base, 'apiKey': key})
    assert configured.status_code == 200, configured.text
    response = client.put('/api/models/' + mid, json={'name': mid, 'modelId': mid, 'type': kind, 'provider': provider, 'providerConfigId': pid, 'dimensions': 4 if kind == 'Embedding' else None})
    assert response.status_code == 200, response.text
    assert key not in response.text


def test_real_adapters_vector_rerank_langchain_stream_and_secrets(client, cloud_contract):
    base, calls = cloud_contract
    configure(client, base, 'contract-embedding', 'Embedding')
    configure(client, base, 'contract-rerank', 'Rerank')
    configure(client, base, 'contract-llm', 'LLM')
    for mid in ('contract-embedding', 'contract-rerank', 'contract-llm'):
        assert client.post('/api/models/' + mid + '/test').status_code == 200
    with db.pool.connection() as conn:
        pid = db.require(conn, 'models', 'contract-llm')['providerConfigId']
        assert conn.execute('SELECT encrypted FROM provider_secrets WHERE id=%s', (pid,)).fetchone()['encrypted'] != 'fixture-secret-key'
    state = client.get('/api/workspace').json(); kb = state['knowledgeBases'][0]; kb['embeddingModelId'] = 'contract-embedding'
    assistant = state['assistants'][0]; assistant['modelId'] = 'contract-llm'; assistant['rerank'] = False
    assert client.post('/api/workspace/mutations', json={'operations': [{'kind': 'knowledgeBases', 'id': kb['id'], 'action': 'put', 'value': kb}, {'kind': 'assistants', 'id': assistant['id'], 'action': 'put', 'value': assistant}]}).status_code == 200
    client.put('/api/settings', json={'allowExternalProcessing': True})
    rid = upload(client, '合同协议测试.md', '# 远程办公\n员工每周可以申请两天远程办公，需要主管审批。'.encode())
    publish(client, rid, 'hybrid')
    result = client.post('/api/search', json={'kbIds': ['default-kb'], 'query': '远程办公', 'mode': 'hybrid'}).json()
    assert result['results'][0]['documentId'] == rid and result['mode'] == 'hybrid'
    response = client.post('/api/chat/stream', json={'assistantId': 'assistant-general', 'question': '如何申请远程办公？'})
    assert response.status_code == 200 and 'event: token' in response.text and 'event: done' in response.text, response.text
    state = client.get('/api/workspace').json(); reply = state['sessions'][0]['messages'][-1]
    assert reply['citations'][0]['documentId'] == rid and reply['tokens'] == 48
    chat_logs = [item for item in state['logs'] if item['kind'] == 'chat']
    assert chat_logs[0]['inputTokens'] == 37 and chat_logs[0]['outputTokens'] == 11
    assert chat_logs[0]['firstToken'] is not None
    assert client.get('/api/workspace', headers={'X-Browser-Id': 'other-browser'}).json()['sessions'] == []
    assert 'fixture-secret-key' not in json.dumps(state)
    configure(client, base, 'contract-qwen-rerank', 'Rerank', provider='通义千问')
    assert client.post('/api/models/contract-qwen-rerank/test').status_code == 200
    assert any('services/rerank/' in path and 'input' in body for path, body in calls)
    configure(client, base, 'contract-rejected', 'LLM', key='rejected-test-key')
    failure = client.post('/api/models/contract-rejected/test')
    assert failure.status_code == 422 and 'rejected-test-key' not in failure.text


def test_job_lease_recovery_and_real_errors(client):
    response = client.post('/api/knowledge/default-kb/upload', files={'file': ('broken.pdf', b'not a pdf')})
    assert response.status_code == 200
    first = db.claim_job(); assert first
    with db.pool.connection() as conn:
        conn.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (first['id'],))
    second = db.claim_job(); assert second['id'] == first['id']
    run_one(second)
    doc = document(client, response.json()['documentId'])
    assert doc['status'] == 'failed' and not doc['chunks']
    assert client.post('/api/knowledge/default-kb/upload', files={'file': ('legacy.doc', b'old')}).status_code == 422
    assert client.put('/api/settings', headers={'X-Role': 'user'}, json={'allowExternalProcessing': True}).status_code == 403


def test_image_model_contract_and_preserve_old_index_on_failure(client, cloud_contract):
    from PIL import Image
    base, calls = cloud_contract
    configure(client, base, 'contract-ocr', 'OCR')
    configure(client, base, 'contract-vision', 'Vision')
    with db.pool.connection() as conn:
        for kind, mid in [('OCR', 'contract-ocr'), ('Vision', 'contract-vision')]:
            for model in db.items(conn, 'models'):
                if model['type'] == kind:
                    model['isDefault'] = model['id'] == mid; db.put(conn, 'models', model)
    client.put('/api/settings', json={'allowExternalProcessing': True})
    image = io.BytesIO(); Image.new('RGB', (80, 80), 'white').save(image, 'PNG')
    response = client.post('/api/knowledge/default-kb/upload', files={'file': ('real-image.png', image.getvalue())}, data={'options': json.dumps({'ocr': False, 'vision': False})})
    rid = response.json()['documentId']; process_job()
    assert document(client, rid)['status'] == 'failed'
    assert client.post(f'/api/documents/{rid}/retry', json={'options': {'ocr': True, 'vision': True}}).status_code == 200
    process_job()
    doc = document(client, rid)
    assert doc['status'] == 'parsed' and {chunk['kind'] for chunk in doc['chunks']} == {'text', 'image'}
    assert client.get(doc['chunks'][0]['imageUrl']).status_code == 200
    image_calls = [body for path, body in calls if path.endswith('/chat/completions')]
    assert any(part.get('image_url', {}).get('url', '').startswith('data:image/jpeg;base64,') for body in image_calls for msg in body['messages'] for part in msg['content'] if isinstance(part, dict))
    second = upload(client, 'stable.md', '# 版本保留\n稳定版本可检索 KEEPOLDINDEX。'.encode()); publish(client, second)
    version = document(client, second)['activeVersion']
    configure(client, base, 'new-embedding', 'Embedding')
    client.put('/api/settings', json={'allowExternalProcessing': False})
    state = client.get('/api/workspace').json(); kb = state['knowledgeBases'][0]; kb['embeddingModelId'] = 'new-embedding'
    assert client.post('/api/workspace/mutations', json={'operations': [{'kind': 'knowledgeBases', 'id': kb['id'], 'action': 'put', 'value': kb}]}).status_code == 200
    process_job(); process_job()
    assert document(client, second)['activeVersion'] == version
    result = client.post('/api/search', json={'kbIds': ['default-kb'], 'query': 'KEEPOLDINDEX', 'mode': 'keyword'}).json()
    assert result['results'][0]['documentId'] == second
