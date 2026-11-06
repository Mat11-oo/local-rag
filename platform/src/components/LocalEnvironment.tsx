import { useEffect, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { ExperienceSummary } from './ExperienceSummary';
import { Loading, Notice } from './ui';

interface LocalState {
  allow_external_processing: boolean;
  migration: { source_counts: Record<string, number>; warnings: Array<{ kind: string }>; retained_in_legacy: string[] } | null;
  upstream: { repository?: string; commit?: string };
}

const labels: Record<string, string> = {
  models: '模型配置', knowledgeBases: '知识库', documents: '文件', assistants: '应用',
  evaluationDatasets: '评测集', evaluationCases: '评测 Case', sessions: '旧会话', logs: '旧日志',
};

export function LocalEnvironment() {
  const [state, setState] = useState<LocalState | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    void apiFetch<LocalState>('/local-environment', { signal: abort.signal })
      .then(setState).catch((caught) => { if (!abort.signal.aborted) setError(errorMessage(caught)); });
    return () => abort.abort();
  }, []);

  const toggle = async () => {
    if (!state) return;
    setBusy(true);
    setError('');
    try {
      const result = await apiFetch<{ allow_external_processing: boolean }>('/local-environment/processing', {
        method: 'PUT', body: JSON.stringify({ allow_external_processing: !state.allow_external_processing }),
      });
      setState((previous) => previous ? { ...previous, ...result } : previous);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  };

  return <div className="stack">
    {error ? <Notice tone="error">{error}</Notice> : null}
    {!state && !error ? <Loading /> : null}
    {state ? <>
      <section className="card" style={{ padding: 20 }}>
        <h2>云端资料处理</h2>
        <p>开启后，向量化、重排、OCR、分块增强、AI 设计和应用对话可将对应资料发送到所配置的模型服务商，并可能产生费用。</p>
        <button className="btn" role="switch" aria-checked={state.allow_external_processing} aria-label="允许云端资料处理" disabled={busy} onClick={() => void toggle()}>
          {busy ? '正在保存…' : state.allow_external_processing ? '已开启 · 点击关闭' : '已关闭 · 点击开启'}
        </button>
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2>旧版资料迁移</h2>
        {state.migration ? <>
          <p>以下为旧版来源记录数。模型、知识库、原文件、已启用的发布索引和基础应用配置已迁移；所有应用均保留为草稿。</p>
          <div className="row wrap">{Object.entries(labels).map(([key, label]) => <span className="tag" key={key}>{label} {state.migration?.source_counts[key] ?? 0}</span>)}</div>
          <p>旧会话、运行日志、历史版本、完整 Chat Flow 和外部集成继续保留在旧版。Chat Flow 的新版迁移草稿只含基础配置，不能代替原流程。</p>
          <p>在项目目录运行 <code>python3 scripts/start-local.py --legacy</code> 后，<a href="http://127.0.0.1:5173/" target="_blank" rel="noreferrer">打开旧版</a>。</p>
        </> : <p>尚未执行迁移。在停止新版服务后运行 <code>python3 scripts/migrate-local.py</code>。</p>}
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2>实现来源</h2>
        <p><a href="https://github.com/chusimin/zhishu-rag-platform" target="_blank" rel="noreferrer">知枢参考仓库</a> · {state.upstream.commit?.slice(0, 12) ?? '本地集成版'}</p>
        <p>新版支持简易应用与 Agent。Chat Flow、多渠道嵌入仍按参考 README 标注为尚未开放；应用运行使用非流式响应。</p>
      </section>
    </> : null}
    <ExperienceSummary/>
  </div>;
}
