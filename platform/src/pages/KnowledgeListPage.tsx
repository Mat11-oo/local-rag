import { BookText, Database, Plus, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiFetch, errorMessage, type ApiKnowledgeBase, type ApiModelOption } from '../api/client';
import { fdeApi, type FDEApp } from '../api/fde';
import { useAuth } from '../auth';
import { Empty, Field, Loading, Modal, Notice, Spinner, Tag, formatTime, useToast } from '../components/ui';
import { Pagination } from '../components/Pagination';
import { useListState, useListScroll, usePageReset } from '../lib/listState';
import { modelsOf } from '../lib/knowledge';

const COLORS = ['#3370ff', '#12b76a', '#7a5af8', '#f79009', '#dd2590', '#0e9384'];

export function KnowledgeListPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [items, setItems] = useState<ApiKnowledgeBase[] | null>(null);
  const [apps, setApps] = useState<FDEApp[]>([]);
  const [options, setOptions] = useState<ApiModelOption[]>([]);
  const [error, setError] = useState('');
  const [associated,setAssociated]=useListState('knowledge-app','all');
  const [q,setQ]=useListState('knowledge-query','');
  const [status,setStatus]=useListState('knowledge-status','all');
  const [order,setOrder]=useListState('knowledge-order','updated');
  const [page,setPage]=useListState('knowledge-page',1);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const { me } = useAuth();
  const [form, setForm] = useState({ name: '', description: '', embedding_model_id: '', rerank_model_id: '', ocr_model_id: '', llm_id: '' });

  useEffect(() => {
    Promise.all([apiFetch<ApiKnowledgeBase[]>('/knowledge-bases'), apiFetch<ApiModelOption[]>('/model-options'), fdeApi.list()])
      .then(([kbs, models, loadedApps]) => {
        setItems(kbs);
        setOptions(models);
        setApps(loadedApps);
        setForm((current) => ({ ...current, embedding_model_id: current.embedding_model_id || modelsOf(models, 'embedding')[0]?.id || '' }));
      })
      .catch((caught) => setError(errorMessage(caught)));
  }, []);

  const usedBy = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const app of apps) for (const id of app.manifest.knowledge_base_ids) (map[id] ??= []).push(app.name);
    return map;
  }, [apps]);

  const create = async () => {
    setBusy(true);
    try {
      const created = await apiFetch<ApiKnowledgeBase>('/knowledge-bases', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim(),
          embedding_model_id: form.embedding_model_id || null,
          rerank_model_id: form.rerank_model_id || null,
          ocr_model_id: form.ocr_model_id || null,
          semantic_llm_model_id: form.llm_id || null,
          metadata_llm_model_id: form.llm_id || null,
        }),
      });
      toast(`已创建「${created.name}」，下一步导入数据`);
      navigate(`/knowledge/${created.id}/import`);
    } catch (caught) {
      toast(errorMessage(caught), 'error');
    } finally {
      setBusy(false);
    }
  };

  const list = (items ?? []).filter(item=>associated==='all'||apps.some(app=>app.id===associated&&app.manifest.knowledge_base_ids.includes(item.id))).filter(item => (!q || `${item.name}${item.description}`.toLowerCase().includes(q.toLowerCase())) && (status==='all' || (status==='semantic' ? item.semantic_ready : status==='fulltext' ? !item.semantic_ready && (item.total_chunk_count??0)>0 : !(item.total_chunk_count??0))))
    .sort((a,b)=>order==='name' ? a.name.localeCompare(b.name,'zh-CN') : b.updated_at.localeCompare(a.updated_at));
  const scrollRef=useListScroll('knowledge',items !== null);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(list.length/20)));
  usePageReset(()=>setPage(1),JSON.stringify([q,status,order,associated]));
  const select = (key: keyof typeof form, type: ApiModelOption['model_type'], emptyLabel?: string) => (
    <select className="select" value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })}>
      {emptyLabel ? <option value="">{emptyLabel}</option> : !modelsOf(options, type).length ? <option value="">暂无可用模型</option> : null}
      {modelsOf(options, type).map((model) => <option key={model.id} value={model.id}>{model.display_name} · {model.provider}</option>)}
    </select>
  );

  return (
    <div className="page" ref={scrollRef}>
      <div className="page-head">
        <div className="grow"><h1>知识库</h1><p>管理企业知识资产。每个文件可以单独选择切块方式，导入前先预览效果。</p></div>
        <div className="search-box" style={{ width: 240 }}><Search size={15} /><input className="input" aria-label="搜索知识库" placeholder="搜索知识库" value={q} onChange={(event) => setQ(event.target.value)} /></div>
        <button className="btn primary" onClick={() => setOpen(true)}><Plus size={16} />新建知识库</button>
      </div>
      <div className="row wrap" style={{marginBottom:16}}><select className="select sm" aria-label="关联应用筛选" value={associated} onChange={event=>setAssociated(event.target.value)}><option value="all">全部关联应用</option>{apps.filter(app=>app.manifest.knowledge_base_ids.length>0).map(app=><option key={app.id} value={app.id}>{app.name}</option>)}</select><select className="select sm" aria-label="知识库能力筛选" value={status} onChange={event=>setStatus(event.target.value)}><option value="all">全部能力</option><option value="semantic">语义与全文可用</option><option value="fulltext">仅全文可用</option><option value="empty">等待导入</option></select><select className="select sm" aria-label="知识库排序" value={order} onChange={event=>setOrder(event.target.value)}><option value="updated">最近更新</option><option value="name">按名称</option></select></div>
      {error ? <Notice tone="error" title="无法加载知识库">{error}</Notice> : null}
      {!items && !error ? <Loading /> : null}
      {items && !list.length ? <Empty icon={<Database size={26} />} title={items.length ? '没有匹配的知识库' : '还没有知识库'} desc="创建知识库并导入文档后，应用就能基于它回答问题。" action={<button className="btn primary" onClick={() => setOpen(true)}><Plus size={15} />新建知识库</button>} /> : null}
      <div className="grid auto">
        {list.slice((currentPage-1)*20,currentPage*20).map((kb, index) => (
          <Link key={kb.id} className="card pad hover" to={`/knowledge/${kb.id}`} aria-label={`打开知识库 ${kb.name}`}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <span className="avatar-tile lg" style={{ background: COLORS[index % COLORS.length] }}><BookText size={20} /></span>
              <div className="grow">
                <strong style={{ fontSize: 15 }}>{kb.name}</strong>
                <div className="row" style={{ marginTop: 4 }}><Tag tone={kb.semantic_ready ? 'green' : 'orange'}>{kb.semantic_ready ? '语义与全文可用' : (kb.total_chunk_count ?? 0) > 0 ? '全文可用 · 向量未就绪' : '等待导入资料'}</Tag></div>
              </div>
            </div>
            <p className="muted clamp-2" style={{ fontSize: 13, marginTop: 10, minHeight: 42 }}>{kb.description || '暂无简介'}</p>
            <div className="row" style={{ marginTop: 12, gap: 16, fontSize: 13 }}>
              <span><strong>{kb.file_count}</strong> <span className="faint">个文件</span></span>
              <span><strong>{(kb.total_chunk_count ?? kb.chunk_count).toLocaleString()}</strong> <span className="faint">个分块 · {kb.chunk_count} 已向量化</span></span>
              <span className="grow" />
              <span className="faint">{formatTime(kb.updated_at)}</span>
            </div>
            <div className="divider" style={{ margin: '12px 0' }} />
            <div className="row faint"><span>{usedBy[kb.id]?.length ? `被 ${usedBy[kb.id].length} 个应用引用：` : '尚未被应用引用'}</span><span className="ellipsis grow">{usedBy[kb.id]?.join('、')}</span></div>
          </Link>
        ))}
      </div>

      <Pagination page={currentPage} total={list.length} onChange={setPage}/>
      <Modal open={open} title="新建知识库" onClose={() => setOpen(false)}
        footer={<><button className="btn" onClick={() => setOpen(false)}>取消</button><button className="btn primary" disabled={!form.name.trim() || busy} onClick={() => void create()}>{busy ? <Spinner /> : null}创建并导入数据</button></>}>
        <Field label="名称" required><input className="input" autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：售后服务政策" /></Field>
        <Field label="简介" hint="Agent 会据此判断何时检索本库"><textarea className="textarea" style={{ minHeight: 64 }} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明知识库包含哪些内容、适合回答什么问题" /></Field>
        <div className="form-grid">
          <Field label="索引模型" required hint="更换需全库重建">{select('embedding_model_id', 'embedding')}</Field>
          <Field label="重排模型">{select('rerank_model_id', 'rerank', '不使用')}</Field>
          <Field label="文本理解模型" hint="语义分块、元数据抽取、问答对生成">{select('llm_id', 'llm', '不使用（规则抽取）')}</Field>
          <Field label="图片理解 / OCR">{select('ocr_model_id', 'ocr', '不处理图片')}</Field>
        </div>
        {!modelsOf(options, 'embedding').length ? <Notice tone="warn" title="没有可用的索引模型" action={me?.role === 'admin' ? <Link className="btn sm" to="/tools?tab=models">去接入</Link> : undefined}>{me?.role === 'admin' ? '接入 Embedding 模型后才能语义检索；否则只能使用全文检索。' : '请联系管理员接入 Embedding 模型；否则只能使用全文检索。'}</Notice> : null}
      </Modal>
    </div>
  );
}
