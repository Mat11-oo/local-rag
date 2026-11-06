import hashlib
import json
import re
import time

import jieba

from . import db, models

jieba.setLogLevel(40)
STOPWORDS = {'什么', '怎么', '如何', '哪些', '需要', '请问', '是否', '可以', '我们', '公司', '这个', '这些', '一下', '关于', '多少', '的', '了', '和', '是', '在', '有', '吗', '呢', '请', '我', '想', '帮', '你'}


def tokens(text):
    return list(dict.fromkeys(token.lower() for token in jieba.cut_for_search(text, HMM=False) if token not in STOPWORDS and re.fullmatch(r'[\w\u4e00-\u9fff.-]+', token) and (len(token) > 1 or token.isdigit())))


def profile(model):
    config = {key: model.get(key) for key in ('id', 'provider', 'modelId', 'baseUrl', 'dimensions')}
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:24]


def search(kb_ids, query, mode='hybrid', top_k=5, use_rerank=False, metadata_filters=None):
    started = time.perf_counter()
    if not kb_ids:
        return [], [{'name': '知识范围为空', 'duration': 0, 'status': 'success'}], 'keyword'
    if mode not in ('keyword', 'vector', 'hybrid'):
        raise ValueError('未知检索方式')
    candidate_lists = []
    scope = """FROM chunk_index c JOIN resources d ON d.kind='documents' AND d.id=c.doc_id
      WHERE c.kb_id=ANY(%s) AND COALESCE((d.data->>'enabled')::boolean,false)
      AND d.data->>'activeVersion'=c.version"""
    scope_params = [kb_ids]
    if metadata_filters is not None and not isinstance(metadata_filters, dict):
        raise ValueError('元数据筛选参数无效')
    for field, value in (metadata_filters or {}).items():
        if field not in ('dates', 'versions', 'subjects', 'owners', 'keywords'):
            raise ValueError('不支持的元数据筛选字段')
        if value:
            if not isinstance(value, str) or len(value) > 250:
                raise ValueError('元数据筛选值无效')
            scope += ' AND c.metadata @> %s::jsonb'
            scope_params.append(json.dumps({'documentMetadata': {field: [value]}}, ensure_ascii=False))
    with db.pool.connection() as conn:
        if mode != 'vector':
            words = tokens(query)
            if words:
                expression = ' | '.join("'" + word.replace("'", '') + "'" for word in words[:30])
                sql = 'SELECT c.id,c.doc_id,c.content,c.metadata,ts_rank_cd(c.search,to_tsquery(\'simple\',%s)) AS score ' + scope + " AND c.search @@ to_tsquery('simple',%s) ORDER BY score DESC LIMIT 40"
                rows = conn.execute(sql, (expression, *scope_params, expression)).fetchall()
                candidate_lists.append(rows)
        profiles = conn.execute('SELECT DISTINCT c.profile,d.data->\'embeddingConfig\' AS model ' + scope + " AND c.embedding IS NOT NULL", scope_params).fetchall() if mode != 'keyword' else []
    if mode == 'vector' and not profiles:
        if any((metadata_filters or {}).values()):
            return [], [{'name': '已发布元数据条件未命中可用向量分段', 'duration': round(time.perf_counter() - started, 4), 'status': 'success'}], 'vector'
        raise ValueError('该知识库尚无向量索引，请配置 Embedding 并重新构建；当前可使用关键词检索')
    for group in profiles:
        model = group['model']
        if not model:
            continue
        models.require_external()
        vector = models.CloudEmbeddings(model, models.key_for(model['id']), kb_ids).embed_query(query)
        vector_text = '[' + ','.join(map(str, vector)) + ']'
        with db.pool.connection() as conn:
            rows = conn.execute('SELECT c.id,c.doc_id,c.content,c.metadata,1-(c.embedding <=> %s::vector) AS score ' + scope + ' AND c.profile=%s AND c.embedding IS NOT NULL ORDER BY c.embedding <=> %s::vector LIMIT 40', (vector_text, *scope_params, group['profile'], vector_text)).fetchall()
        candidate_lists.append(rows)
    combined = {}
    for rows in candidate_lists:
        for rank, row in enumerate(rows):
            entry = combined.setdefault(row['id'], {**row, 'score': 0.0})
            entry['score'] += 1 / (60 + rank + 1)
    results = sorted(combined.values(), key=lambda entry: entry['score'], reverse=True)[:40]
    actual_mode = 'hybrid' if profiles and mode == 'hybrid' else 'vector' if profiles else 'keyword'
    stages = [{'name': {'keyword': 'PostgreSQL 中文关键词检索', 'vector': 'pgvector 语义检索', 'hybrid': '语义与关键词召回 · RRF 融合'}[actual_mode], 'duration': round(time.perf_counter() - started, 4), 'status': 'success'}]
    if any((metadata_filters or {}).values()):
        stages.append({'name': '已发布元数据条件过滤', 'duration': 0, 'status': 'success'})
    if use_rerank and results:
        before = time.perf_counter()
        model, key = models.model_for('Rerank')
        ordered = models.rerank(model, key, query, [entry['content'] for entry in results], top_k)
        results = [{**results[item['index']], 'score': float(item['relevance_score']), 'scoreType': 'rerank'} for item in ordered]
        stages.append({'name': 'Rerank 相关性重排', 'duration': round(time.perf_counter() - before, 4), 'status': 'success'})
    citations = []
    for rank, entry in enumerate(results[:top_k]):
        metadata = entry['metadata']
        citations.append({'id': str(rank + 1), 'documentId': entry['doc_id'], 'chunkId': metadata['id'], 'name': metadata['documentName'], 'title': metadata['title'], 'text': entry['content'], 'kind': metadata['kind'], 'page': metadata.get('page'), 'sheet': metadata.get('sheet'), 'imageUrl': metadata.get('imageUrl'), 'version': metadata.get('version'), 'score': entry['score'], 'scoreType': entry.get('scoreType', 'rrf'), 'metadata': metadata.get('documentMetadata', {}), 'suggestedQuestions': metadata.get('suggestedQuestions', [])})
    return citations, stages, actual_mode
