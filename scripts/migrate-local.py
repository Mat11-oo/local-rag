#!/usr/bin/env python3
"""Read-only legacy export and idempotent import into the isolated platform DB."""
import asyncio
import hashlib
import json
import mimetypes
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from platform_local import ROOT, PLATFORM, DATA, PYTHON, configuration, environment


def stable(kind, value):
    return str(uuid5(NAMESPACE_URL, f'knowhub-local:{kind}:{value}'))


def case_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ('message', 'question', 'answer', 'text', 'content', 'output'):
            if isinstance(value.get(key), str):
                return value[key]
    return json.dumps(value, ensure_ascii=False) if value is not None else ''


@contextmanager
def source_database():
    import psycopg
    config_path = ROOT / '.data/database.json'
    if not config_path.exists():
        raise RuntimeError('未找到旧版 .data/database.json，未执行迁移。')
    config = json.loads(config_path.read_text())
    pg_ctl = ROOT / '.runtime/pgsql/bin/pg_ctl'
    cluster = ROOT / '.data/postgres'
    started = False
    try:
        try:
            connection = psycopg.connect(config['url'], connect_timeout=3)
        except psycopg.OperationalError:
            if not pg_ctl.exists():
                raise RuntimeError('旧数据库未运行，且缺少本地 PostgreSQL；请先启动旧数据库。') from None
            socket_dir = Path('/tmp') / f'knowhub-pg-{os.getuid()}'
            socket_dir.mkdir(mode=0o700, exist_ok=True)
            options = f'-h 127.0.0.1 -p 55432 -k {shlex.quote(str(socket_dir))}'
            subprocess.run([str(pg_ctl), '-D', str(cluster), '-l', str(ROOT / '.data/postgres.log'),
                            '-o', options, '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
            started = True
            connection = psycopg.connect(config['url'], connect_timeout=5)
        with connection:
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            yield connection
    finally:
        if started:
            subprocess.run([str(pg_ctl), '-D', str(cluster), '-m', 'fast', '-w', 'stop'],
                           check=True, stdout=subprocess.DEVNULL)


def export_source():
    from cryptography.fernet import Fernet
    from psycopg.rows import dict_row
    with source_database() as connection:
        connection.row_factory = dict_row
        resources = defaultdict(list)
        for row in connection.execute('SELECT kind,data FROM resources ORDER BY created_at'):
            resources[row['kind']].append(row['data'])
        # Keep all historic records as private local evidence, never expose across new users.
        indexes = list(connection.execute('SELECT id,doc_id,version,content,metadata,embedding::text AS embedding FROM chunk_index'))
        provider_secrets = {r['id']: r['encrypted'] for r in connection.execute('SELECT * FROM provider_secrets')}
        model_secrets = {r['id']: r['encrypted'] for r in connection.execute('SELECT * FROM model_secrets')}
    snapshot = DATA / 'legacy-resources.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps(resources, ensure_ascii=False, default=str))
        snapshot.chmod(0o600)
    key = ROOT / '.data/master.key'
    cipher = Fernet(key.read_bytes()) if key.exists() else None
    keys = {}
    providers = {p['id']: p for p in resources['providerConfigs']}
    warnings = []
    for model in resources['models']:
        pid = model.get('providerConfigId')
        token = provider_secrets.get(pid) if pid else model_secrets.get(model['id'])
        if token:
            try:
                if cipher is None:
                    raise ValueError('missing master key')
                keys[model['id']] = cipher.decrypt(token.encode()).decode()
            except Exception:
                warnings.append({'kind': 'credential_unavailable', 'id': model['id']})
    return resources, indexes, providers, keys, warnings


async def migrate(resources, indexes, providers, keys, warnings):
    from sqlalchemy import select
    from app.bootstrap import bootstrap_defaults
    from app.db import SessionLocal, init_db, engine
    from app.fde.manifest import Manifest, Tool, Experience, Delivery
    from app.models import (KnowledgeBase, KnowledgeFile, DocumentChunk, ModelConfig, QAApp,
                            EvaluationSuite, EvaluationCase, DEFAULT_WORKSPACE_ID)
    from app.security import encrypt_secret
    await init_db()
    await bootstrap_defaults()
    added = Counter()
    original = Counter({k: len(v) for k, v in resources.items()})
    async with SessionLocal() as session:
        for item in resources['models']:
            mid = stable('model', item['id'])
            if await session.get(ModelConfig, mid):
                continue
            provider = providers.get(item.get('providerConfigId'), {})
            label = provider.get('provider') or item.get('provider', '')
            mapped = {'通义千问': 'tongyi', 'OpenRouter': 'openrouter', 'AIHubMix': 'aihubmix', 'DeepSeek': 'deepseek'}.get(label)
            kind = {'LLM': 'llm', 'Embedding': 'embedding', 'Rerank': 'rerank', 'OCR': 'ocr', 'Vision': 'ocr'}.get(item.get('type'))
            if not mapped or not kind:
                warnings.append({'kind': 'unsupported_model', 'id': item['id']})
                continue
            config = {'legacy_model_id': item['id'], 'legacy_provider_id': item.get('providerConfigId')}
            if item.get('dimensions'):
                config['dimensions'] = item['dimensions']
            for before, after in [('inputPrice', 'input_price_per_million'), ('outputPrice', 'output_price_per_million'), ('currency', 'currency')]:
                if item.get(before) is not None:
                    config[after] = item[before]
            session.add(ModelConfig(id=mid, workspace_id=DEFAULT_WORKSPACE_ID, display_name=item['name'],
                provider=mapped, model_type=kind, model_name=item.get('modelId') or '',
                base_url=provider.get('baseUrl') or item.get('baseUrl', ''),
                api_key_encrypted=encrypt_secret(keys.get(item['id'])), is_enabled=item.get('enabled', True),
                connection_status='untested', config=config))
            added['models'] += 1
        await session.flush()
        async def model_id(value):
            mid = stable('model', value)
            return mid if value and await session.get(ModelConfig, mid) else None
        for item in resources['knowledgeBases']:
            kid = stable('kb', item['id'])
            if await session.get(KnowledgeBase, kid):
                continue
            session.add(KnowledgeBase(id=kid, workspace_id=DEFAULT_WORKSPACE_ID, name=item['name'],
                description=item.get('description', ''), embedding_model_id=await model_id(item.get('embeddingModelId')),
                rerank_model_id=await model_id(item.get('rerankModelId')), chunk_method='heading'))
            added['knowledgeBases'] += 1
        await session.flush()
        active_indexes = defaultdict(list)
        by_document = {d['id']: d for d in resources['documents']}
        for row in indexes:
            doc = by_document.get(row['doc_id'], {})
            if doc.get('enabled', True) and row['version'] == doc.get('activeVersion'):
                active_indexes[row['doc_id']].append(row)
        for item in resources['documents']:
            fid = stable('file', item['id'])
            if await session.get(KnowledgeFile, fid):
                continue
            kid = stable('kb', item['kbId'])
            if not await session.get(KnowledgeBase, kid):
                warnings.append({'kind': 'missing_knowledge_base', 'id': item['id']})
                continue
            source_path = (ROOT / '.data' / item.get('storagePath', '')).resolve()
            source_root = (ROOT / '.data').resolve()
            if source_root not in source_path.parents or not source_path.is_file():
                warnings.append({'kind': 'missing_original_file', 'id': item['id']})
                continue
            storage_key = f"legacy/{fid}/{Path(item['name']).name}"
            target = DATA / 'uploads' / storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            rows = active_indexes[item['id']]
            session.add(KnowledgeFile(id=fid, knowledge_base_id=kid, filename=item['name'],
                content_type=mimetypes.guess_type(item['name'])[0] or 'application/octet-stream',
                extension=source_path.suffix.lower() or Path(item['name']).suffix.lower(),
                size_bytes=source_path.stat().st_size, storage_key=storage_key,
                checksum_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                status='completed' if rows else 'failed',
                error_message=None if rows else '旧版未启用或未发布索引；原文件已保留，请确认后重新构建。',
                page_count=item.get('pages'), chunk_count=len(rows),
                document_metadata={**(item.get('metadata') or {}), 'legacy_document_id': item['id']},
                chunk_config={'method': 'heading'}))
            await session.flush()
            for ordinal, row in enumerate(rows):
                metadata = row['metadata'] or {}
                embedding = json.loads(row['embedding']) if row['embedding'] else None
                session.add(DocumentChunk(id=stable('chunk', row['id']), knowledge_base_id=kid, file_id=fid,
                    ordinal=ordinal, title=metadata.get('title') or '', content=row['content'],
                    char_count=len(row['content']), page_number=metadata.get('page'), embedding=embedding,
                    metadata_json={**metadata, 'legacy_chunk_id': row['id']}))
                if embedding:
                    kb = await session.get(KnowledgeBase, kid)
                    kb.embedding_dimension = len(embedding)
                added['chunks'] += 1
            added['files'] += 1
        await session.flush()
        for item in resources['assistants']:
            advanced = item.get('type', 'simple') not in ('simple', 'qa')
            if advanced:
                warnings.append({'kind': 'legacy_runtime_retained', 'id': item['id'], 'type': item.get('type')})
            aid = stable('app', item['id'])
            if await session.get(QAApp, aid):
                continue
            knowledge = []
            for value in item.get('kbIds', []):
                kb = await session.get(KnowledgeBase, stable('kb', value))
                if kb:
                    knowledge.append(kb)
            llm = await model_id(item.get('modelId'))
            top_k = max(1, min(item.get('topK', 5), 50))
            description = item.get('description', '')
            if advanced:
                description = '【迁移草稿】原应用为 ' + item['type'] + '，此草稿仅迁移基础提示词和知识库；完整流程请从旧版运行。\n' + description
            manifest = Manifest(name=item['name'], description=description, template_key='qa',
                system_prompt=item.get('prompt') or '请依据知识库回答并提供引用，不足时如实说明。',
                llm_model_id=llm, knowledge_base_ids=[kb.id for kb in knowledge],
                tools=[Tool(name='knowledge_retrieval', config={'mode': 'fulltext', 'top_k': top_k, 'score_threshold': 0})],
                experience=Experience(opening=item.get('welcome', ''), suggestions=item.get('examples', [])[:8]),
                delivery=Delivery(show_citations=True))
            session.add(QAApp(id=aid, workspace_id=DEFAULT_WORKSPACE_ID, name=item['name'],
                description=description, system_prompt=manifest.system_prompt,
                llm_model_id=llm, top_k=top_k, score_threshold=0, knowledge_bases=knowledge,
                draft_manifest=manifest.model_dump(mode='json'), is_enabled=False, status='draft'))
            added['apps'] += 1
        await session.flush()
        # Old datasets were cross-app; new suites belong to one application.
        datasets = {d['id']: d for d in resources['evaluationDatasets']}
        for item in resources['evaluationCases']:
            if item.get('archived'):
                continue
            aid = stable('app', item.get('appId', ''))
            if not await session.get(QAApp, aid):
                warnings.append({'kind': 'case_without_app', 'id': item['id']})
                continue
            cid = stable('case', item['id'])
            if await session.get(EvaluationCase, cid):
                continue
            sid = stable('suite', item['datasetId'] + ':' + aid)
            if not await session.get(EvaluationSuite, sid):
                source = datasets.get(item['datasetId'], {})
                session.add(EvaluationSuite(id=sid, app_id=aid, name=source.get('name') or '旧版评测集',
                    description=source.get('description', ''), is_release_gate=False))
                await session.flush()
                added['evaluationSets'] += 1
            expected = case_text(item.get('expectedAnswer', ''))
            message = case_text(item.get('input', ''))
            session.add(EvaluationCase(id=cid, suite_id=sid, name=(message or '旧版 Case')[:180],
                message=message, actual_output=case_text(item.get('output', '')), expected_output=expected,
                case_type='good' if item.get('label') == 'goodcase' else 'bad',
                readiness='ready' if expected.strip() else 'needs_standard', tags=item.get('tags', []),
                source_snapshot={'legacy': item}))
            added['cases'] += 1
        await session.commit()
    await engine.dispose()
    return {'sourceCounts': dict(original), 'importedThisRun': dict(added), 'warnings': warnings,
            'legacyEvidence': str(DATA / 'legacy-resources.json'),
            'retainedInLegacy': ['sessions', 'logs', 'jobs', 'runtime integrations', 'advanced apps', 'applicationVersions'],
            'networkCalls': 0, 'appsPublished': 0}


def main():
    if Path(sys.executable).resolve() != PYTHON.resolve():
        os.execv(str(PYTHON), [str(PYTHON), __file__, *sys.argv[1:]])
    os.umask(0o077)
    # Never write the target database while its server is active.
    import socket
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8001)) == 0:
            raise SystemExit('请先停止新版服务，再迁移。')
    os.environ.update(environment())
    sys.path.insert(0, str(PLATFORM / 'backend'))
    report_path = DATA / 'migration-report.json'
    if report_path.exists() and '--resume' not in sys.argv:
        print('迁移已执行；报告：.data/platform/migration-report.json。需要导入新增记录时使用 --resume。')
        return
    target = DATA / 'knowledge_hub.db'
    if target.exists():
        from datetime import datetime
        backup = DATA / ('before-migration-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')
        with sqlite3.connect(target) as original, sqlite3.connect(backup) as saved:
            original.backup(saved)
    resources, indexes, providers, keys, warnings = export_source()
    report = asyncio.run(migrate(resources, indexes, providers, keys, warnings))
    if not report_path.exists():
        local = configuration()
        settings = resources.get('settings') or [{}]
        local['allowExternalProcessing'] = bool(settings[0].get('allowExternalProcessing', False))
        (DATA / 'local.json').write_text(json.dumps(local, ensure_ascii=False, indent=2))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'imported': report['importedThisRun'], 'warnings': len(warnings),
                      'report': '.data/platform/migration-report.json'}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exceptions may contain credentials in SQL/connection diagnostics.
        print(f'迁移未完成（{type(error).__name__}）；旧资料未修改。修复后可重新执行。', file=sys.stderr)
        raise SystemExit(1)
