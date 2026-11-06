import { useEffect, useState } from 'react';
import type { ApiChunkConfig, ApiKnowledgeBase } from '../api/client';
import { CHUNK_METHODS, hasTextModel } from '../lib/knowledge';
import { Field, Slider, Switch, Tag } from './ui';

export function MethodPicker({ value, kb, onChange, recommended, disabled = [] }: { value: ApiChunkConfig['method']; kb: ApiKnowledgeBase; onChange: (method: ApiChunkConfig['method']) => void; recommended?: string; disabled?: string[] }) {
  return (
    <div className="grid c2" style={{ gap: 8 }}>
      {CHUNK_METHODS.map((method) => {
        const blocked = disabled.includes(method.value) || (method.needsLlm && !kb.semantic_llm_model_id);
        return (
          <button key={method.value} type="button" disabled={blocked} title={blocked ? (method.needsLlm ? '需要先在知识库配置中设置文本理解模型' : '不适用于当前文件') : method.description}
            className={`method-card ${value === method.value ? 'active' : ''}`} style={{ padding: 10, opacity: blocked ? 0.45 : 1, cursor: blocked ? 'not-allowed' : 'pointer' }} onClick={() => onChange(method.value)}>
            <div>
              <h4 style={{ fontSize: 13 }}>{method.label}{recommended === method.value ? <Tag tone="green">推荐</Tag> : null}{method.needsLlm ? <Tag tone="purple">LLM</Tag> : null}</h4>
              <p>{method.bestFor}</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function ChunkConfigFields({ config, patch, kb }: { config: ApiChunkConfig; patch: (value: Partial<ApiChunkConfig>) => void; kb?: ApiKnowledgeBase }) {
  const sized = ['recursive', 'heading', 'separator', 'fixed'].includes(config.method);
  return (
    <div>
      {sized ? <>
        <Field label={config.method === 'heading' ? '单块超长时继续切分' : '块大小'} hint="字"><Slider label="块大小" value={config.chunk_size} min={100} max={4000} step={50} onChange={(v) => patch({ chunk_size: v })} /></Field>
        <Field label="重叠长度" hint="字"><Slider label="重叠长度" value={config.chunk_overlap} min={0} max={Math.min(1000, config.chunk_size - 1)} step={10} onChange={(v) => patch({ chunk_overlap: v })} /></Field>
      </> : null}
      {config.method === 'heading' ? (
        <Field label="按哪一级标题切分">
          <div className="seg">{[1, 2, 3, 4].map((level) => <button type="button" key={level} className={config.heading_level === level ? 'active' : ''} onClick={() => patch({ heading_level: level })}>H1{level > 1 ? `–H${level}` : ''}</button>)}</div>
        </Field>
      ) : null}
      {config.method === 'separator' ? (
        <Field label="分隔符" hint="每行一个；正则以 re: 开头，\n 表示换行">
          <SeparatorInput separators={config.separators} onChange={(separators) => patch({ separators })} />
          <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
            {[['空行', '\n\n'], ['句号', '。'], ['「第X条」', 're:(?=第[一二三四五六七八九十百]+条)'], ['## 标题', '## ']].map(([label, value]) => (
              <button type="button" key={label} className="tag" style={{ cursor: 'pointer' }} onClick={() => !config.separators.includes(value) && patch({ separators: [...config.separators, value] })}>+ {label}</button>
            ))}
          </div>
        </Field>
      ) : null}
      {config.method === 'parent_child' ? <>
        <Field label="父块大小" hint="返回给模型的上下文"><Slider label="父块大小" value={config.parent_chunk_size} min={200} max={12000} step={100} onChange={(v) => patch({ parent_chunk_size: v })} /></Field>
        <Field label="子块大小" hint="用于向量匹配"><Slider label="子块大小" value={config.child_chunk_size} min={80} max={4000} step={20} onChange={(v) => patch({ child_chunk_size: v })} /></Field>
        <Field label="重叠长度" hint="字"><Slider label="重叠长度" value={config.chunk_overlap} min={0} max={Math.min(1000, config.chunk_size - 1)} step={10} onChange={(v) => patch({ chunk_overlap: v })} /></Field>
      </> : null}
      {config.method === 'table_row' ? <Field label="每块行数"><Slider label="每块行数" value={config.rows_per_chunk} min={1} max={20} onChange={(v) => patch({ rows_per_chunk: v })} /></Field> : null}
      {config.method === 'semantic' ? <p className="faint">由知识库配置的文本理解模型按主题切分；结果必须与原文逐字一致，否则构建失败。会产生额外模型调用。</p> : null}
      {config.method === 'page' ? <p className="faint">PDF 每页一块并保留页码；其他格式按段落处理。</p> : null}
      {config.method === 'qa' ? <p className="faint">CSV / Excel 第一列为问题、第二列为答案，每行一个问答分块。</p> : null}
      {kb ? <EnhanceFields config={config} patch={patch} kb={kb} /> : null}
    </div>
  );
}

const encode = (items: string[]) => items.map((item) => item.replace(/\n/g, '\\n')).join('\n');

/** 分隔符每行一个。保留输入框原文（含空行），否则按回车新起的一行会被立即过滤掉。 */
function SeparatorInput({ separators, onChange }: { separators: string[]; onChange: (separators: string[]) => void }) {
  const [text, setText] = useState(() => encode(separators));
  useEffect(() => {
    setText((current) => (encode(current.split('\n').map((item) => item.replace(/\\n/g, '\n')).filter(Boolean)) === encode(separators) ? current : encode(separators)));
  }, [separators]);
  return (
    <textarea className="textarea mono" style={{ minHeight: 80 }} value={text}
      onChange={(event) => { setText(event.target.value); onChange(event.target.value.split('\n').map((item) => item.replace(/\\n/g, '\n')).filter(Boolean)); }} />
  );
}

/** 分块增强：导入时为每个分块抽取关键词、生成问答对，提升口语化提问的命中率。 */
function EnhanceFields({ config, patch, kb }: { config: ApiChunkConfig; patch: (value: Partial<ApiChunkConfig>) => void; kb: ApiKnowledgeBase }) {
  const llm = hasTextModel(kb);
  return (
    <div style={{ borderTop: '1px dashed var(--border)', marginTop: 12, paddingTop: 12 }}>
      <div className="field-label">分块增强<span className="hint">导入时执行，结果可在分块中查看和修改</span></div>
      <div className="col" style={{ gap: 10 }}>
        <div className="row"><span className="grow">抽取关键词<div className="faint">{llm ? '由文本理解模型抽取' : '未配置文本理解模型，按词频规则抽取'}</div></span><Switch on={!!config.enhance_keywords} label="抽取关键词" onChange={(value) => patch({ enhance_keywords: value })} /></div>
        <div className="row"><span className="grow">生成问答对<Tag tone="purple">LLM</Tag><div className="faint">{llm ? '为每个分块生成它能回答的问题与答案，会产生模型调用' : '需要先在知识库「配置」中设置文本理解模型'}</div></span><Switch on={!!config.enhance_qa} disabled={!llm} label="生成问答对" onChange={(value) => patch({ enhance_qa: value })} /></div>
        {config.enhance_qa ? <Field label="每块问答数"><Slider label="每块问答数" value={config.qa_per_chunk ?? 3} min={1} max={5} onChange={(value) => patch({ qa_per_chunk: value })} /></Field> : null}
      </div>
    </div>
  );
}
