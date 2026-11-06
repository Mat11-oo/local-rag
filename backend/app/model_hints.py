"""Verified capability hints; unknown model IDs remain user-configurable."""

# Jina's official model card: https://jina.ai/en-US/models/jina-embeddings-v5-text-nano/
MODEL_HINTS = {
    'jina-embeddings-v5-text-nano': {'types': ['Embedding'], 'dimensions': 768},
}


def validate_model_kind(model_id, kind):
    hint = MODEL_HINTS.get(model_id)
    if hint and kind not in hint['types']:
        raise ValueError(f'{model_id} 是 Embedding 向量模型，请选择 Embedding 用途；生成回答需另选 LLM 对话模型')
