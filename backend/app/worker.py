import hashlib
import json
import time
import threading

from psycopg.types.json import Jsonb

from . import db, models, retrieval, metadata as document_metadata
from .parsing import parse_document


def _run_one(job):
    started = time.perf_counter()
    jid, doc_id, options = job['id'], job['doc_id'], job['options']
    stages = []
    heartbeat_stop = threading.Event()
    def heartbeat():
        while not heartbeat_stop.wait(25):
            try:
                with db.pool.connection() as conn:
                    conn.execute("UPDATE jobs SET lease_until=now()+interval '120 seconds' WHERE id=%s AND status='running'", (jid,))
            except Exception:
                pass
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        with db.pool.connection() as conn:
            doc = db.require(conn, 'documents', doc_id)
        if job['action'] == 'parse':
            db.update_job(jid, '正在解析文件', 5)
            parse_warnings, extracted_blocks = [], []
            chunks, pages = parse_document(doc, options, lambda stage, progress: db.update_job(jid, stage, progress), warnings=parse_warnings, extracted_blocks=extracted_blocks)
            parsed_at = time.perf_counter()
            file_warnings = list(parse_warnings)
            with db.pool.connection() as conn:
                latest = db.require(conn, 'documents', doc_id)
                latest.update(chunks=chunks, sourceBlocks=extracted_blocks, pages=pages, contentFingerprint=document_metadata.source_fingerprint(chunks), metadataStatus='processing' if options.get('metadata', False) else 'skipped')
                db.put(conn, 'documents', latest)
            db.update_job(jid, '正文解析完成', 81, timing={'name': '文件解析与结构分段', 'duration': round(parsed_at - started, 4), 'status': 'success'})
            working = {**doc, 'chunks': chunks}
            if options.get('metadata', False):
                metadata = document_metadata.extract(working, options.get('metadataModelId'), lambda stage, progress: db.update_job(jid, stage, 82 + int(progress * 0.15)))
                if metadata.get('error'):
                    parse_warnings.append('正文已解析，元数据抽取未完整完成：' + metadata['error'])
                parse_warnings.extend(metadata.get('warnings', []))
            else:
                metadata = {**document_metadata.empty_payload(), 'status': 'skipped', 'schemaVersion': 1, 'sourceFingerprint': document_metadata.source_fingerprint(chunks), 'warnings': []}
            metadata['revision'] = db.uid()
            with db.pool.connection() as conn:
                latest = db.require(conn, 'documents', doc_id)
                if document_metadata.source_fingerprint(latest.get('chunks', [])) != document_metadata.source_fingerprint(chunks):
                    raise ValueError('元数据抽取期间正文已变化，请重新解析')
                latest.update(chunks=chunks, pages=pages, status='parsed', indexStatus='parsed', parseOptions=options, parseWarnings=file_warnings, metadata=metadata, metadataStatus=metadata['status'], metadataError=metadata.get('error'), error=None)
                db.put(conn, 'documents', latest)
                conn.execute("UPDATE jobs SET data=jsonb_set(data,'{warnings}',%s::jsonb),updated_at=now() WHERE id=%s", (Jsonb(parse_warnings), jid))
            db.update_job(jid, '解析完成（含提醒），待确认构建' if parse_warnings else '正文与元数据已解析，待确认构建' if options.get('metadata', False) else '解析完成，待确认构建', 100, 'parsed', timing={'name': '文档元数据抽取' if options.get('metadata', False) else '元数据抽取已跳过', 'duration': round(time.perf_counter() - parsed_at, 4), 'status': 'failed' if metadata.get('error') else 'success'})
            return
        if job['action'] == 'metadata':
            fingerprint = document_metadata.source_fingerprint(doc.get('chunks', []))
            result = document_metadata.extract(doc, options.get('metadataModelId'), lambda stage, progress: db.update_job(jid, stage, progress))
            result['revision'] = db.uid()
            with db.pool.connection() as conn:
                latest = db.require(conn, 'documents', doc_id)
                if document_metadata.source_fingerprint(latest.get('chunks', [])) != fingerprint:
                    raise ValueError('抽取期间正文已变化，请重新抽取元数据')
                if result['status'] != 'failed' or not document_metadata.has_current_metadata(latest):
                    latest['metadata'] = result
                latest.update(metadataStatus=result['status'], metadataError=result.get('error'), contentFingerprint=fingerprint)
                if result['status'] != 'failed':
                    latest['indexStatus'] = 'parsed'
                    latest['status'] = 'ready' if latest.get('activeVersion') else 'parsed'
                db.put(conn, 'documents', latest)
                conn.execute("UPDATE jobs SET data=jsonb_set(data,'{warnings}',%s::jsonb),updated_at=now() WHERE id=%s", (Jsonb(result.get('warnings', [])), jid))
            db.update_job(jid, '元数据抽取失败，已有正文与索引保留' if result['status'] == 'failed' else '元数据部分完成，核对后构建索引' if result['status'] == 'partial' else '元数据已抽取，待确认构建索引', 100, 'failed' if result['status'] == 'failed' else 'parsed', result.get('error'), timing={'name': '文档元数据抽取', 'duration': round(time.perf_counter() - started, 4), 'status': 'failed' if result.get('error') else 'success'})
            return
        chunks = doc.get('chunks') or []
        if not chunks:
            raise ValueError('文档尚未解析，请先重新解析')
        fingerprint = document_metadata.index_fingerprint(doc)
        metadata_payload = document_metadata.current_payload(doc)
        index_entries = [document_metadata.index_context(doc, chunk, metadata_payload) for chunk in chunks]
        with db.pool.connection() as conn:
            kb = db.require(conn, 'knowledgeBases', doc['kbId'])
        model, key = (None, None)
        index_mode = options.get('indexMode', 'keyword')
        if index_mode == 'hybrid':
            model, key = models.model_for('Embedding', kb.get('embeddingModelId'))
        vector_profile = retrieval.profile(model) if model else 'keyword'
        version = db.uid()
        vectors = [None] * len(chunks)
        if model:
            embedder = models.CloudEmbeddings(model, key, [doc['kbId']])
            for offset in range(0, len(chunks), 10):
                db.update_job(jid, f'向量化 {min(offset + 10, len(chunks))}/{len(chunks)} 分段', 10 + int(65 * offset / len(chunks)))
                vectors[offset:offset + 10] = embedder.embed_documents([entry[0] for entry in index_entries[offset:offset + 10]])
        db.update_job(jid, '写入关键词与知识索引', 85)
        with db.pool.connection() as conn:
            latest = db.require(conn, 'documents', doc_id)
            latest_kb = db.require(conn, 'knowledgeBases', doc['kbId'])
            latest_model = models.resolve_model(db.require(conn, 'models', model['id']), conn) if model else None
            if document_metadata.index_fingerprint(latest) != fingerprint or (model and (latest_kb.get('embeddingModelId') != model['id'] or retrieval.profile(latest_model) != vector_profile)):
                raise ValueError('构建期间分段或模型配置发生变化，请重试构建')
            for chunk, vector, (index_text, filters, questions) in zip(chunks, vectors, index_entries):
                metadata = {**chunk, 'documentName': doc['name'], 'version': version, 'documentMetadata': filters, 'suggestedQuestions': questions}
                encoded = '[' + ','.join(map(str, vector)) + ']' if vector is not None else None
                words = ' '.join(retrieval.tokens(index_text))
                conn.execute("INSERT INTO chunk_index(id,doc_id,kb_id,version,profile,content,metadata,embedding,search) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::vector,to_tsvector('simple',%s))", (db.uid(), doc_id, doc['kbId'], version, vector_profile, chunk['text'], Jsonb(metadata), encoded, words))
            latest.update(status='ready', indexStatus='ready', activeVersion=version, indexMode=index_mode, embeddingConfig=model, contentFingerprint=document_metadata.source_fingerprint(chunks), indexedMetadataRevision=(doc.get('metadata') or {}).get('revision') if document_metadata.has_current_metadata(doc) else None, error=None)
            db.put(conn, 'documents', latest)
            latest_kb['updatedAt'] = db.now(); db.put(conn, 'knowledgeBases', latest_kb)
            conn.execute('DELETE FROM chunk_index WHERE doc_id=%s AND version<>%s', (doc_id, version))
        db.update_job(jid, '索引已就绪', 100, 'ready', timing={'name': '向量化与索引发布' if model else '本地关键词索引发布', 'duration': round(time.perf_counter() - started, 4), 'status': 'success'})
    except Exception as exc:
        error = models.safe_error(exc)
        with db.pool.connection() as conn:
            doc = db.get(conn, 'documents', doc_id)
            if doc:
                if job['action'] == 'metadata':
                    doc.update(metadataStatus='failed', metadataError=error)
                else:
                    doc.update(status='ready' if doc.get('activeVersion') else 'failed', indexStatus='failed', error=error)
                db.put(conn, 'documents', doc)
            task = conn.execute('SELECT data FROM jobs WHERE id=%s', (jid,)).fetchone()
        db.update_job(jid, {'parse': '解析失败', 'metadata': '元数据抽取失败'}.get(job['action'], '索引构建失败'), (task['data'] if task else {}).get('progress', 0), 'failed', error, timing={'name': '文档处理失败', 'duration': round(time.perf_counter() - started, 4), 'status': 'failed'})
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(1)


def run_one(job):
    from . import telemetry as obs
    rid = f"knowledge-{job['id']}-{job.get('attempts', 0)}"
    with db.pool.connection() as conn:
        doc = db.get(conn, 'documents', job['doc_id']) or {}
    obs.start('knowledge', doc.get('name', '知识构建'), inputs={'action': job['action'], 'options': job['options'], 'documentId': job['doc_id']}, rid=rid, kbId=doc.get('kbId'), taskId=job['id'])
    obs.patch(rid, status='running', startedAt=db.now())
    with obs.scope(rid):
        stage = obs.Span('pipeline', job['action'], {'documentId': job['doc_id']})
        try:
            _run_one(job)
            with db.pool.connection() as conn:
                task = conn.execute('SELECT data FROM jobs WHERE id=%s', (job['id'],)).fetchone()
            task = task['data'] if task else {}
            for item in task.get('stages', []):
                span = obs.Span('stage', item['name'], attributes={'reportedDuration': item.get('duration')})
                span.end(status='failed' if item.get('status') == 'failed' else 'succeeded')
            status = 'failed' if task.get('status') == 'failed' else 'succeeded'
            stage.end(task, status, task.get('error')); obs.finish(rid, status, task, task.get('error'))
        except BaseException as exc:
            stage.end(status='failed', error=str(exc)); obs.finish(rid, 'failed', error=str(exc)); raise


def main():
    db.connect()
    guard = db.pool.getconn()
    if not guard.execute("SELECT pg_try_advisory_lock(7342910626) AS acquired").fetchone()['acquired']:
        raise RuntimeError('已有任务进程运行，无需重复启动')
    guard.commit()
    with db.pool.connection() as conn:
        conn.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE status='running'")
    print('KnowHub 文档 worker 已就绪', flush=True)
    while True:
        try:
            job = db.claim_job()
            if job:
                run_one(job)
            else:
                time.sleep(0.5)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print('worker: ' + models.safe_error(exc), flush=True)
            time.sleep(2)


if __name__ == '__main__':
    main()
