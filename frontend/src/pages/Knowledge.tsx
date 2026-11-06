import { cardAction } from '../cardAction';
import { useEffect, useState } from 'react';
import { ParsingNotice } from '../ParsingNotice';
import { DocumentMetadataPanel } from '../DocumentMetadataPanel';
import { Alert, App, Button, Drawer, Dropdown, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Select, Space, Switch, Table, Tabs, Tag, Tooltip } from 'antd';
import type { TableColumnsType } from 'antd';
import { ArrowLeft, ArrowRight, BookOpen, ChevronRight, CircleAlert, Database, FileImage, FileSpreadsheet, FileText, FileClock, FolderOpen, Layers, MoreHorizontal, Pencil, Plus, RotateCcw, Search, Settings2, Sparkles, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../markdown';
import { formatTime, now, uid, useWorkspace } from '../store';
import type { Chunk, DocumentRecord, DocStatus, KnowledgeBase } from '../types';
import './knowledge.css';
import { api } from '../api';
import type { Citation } from '../types';

const kbPalette: Record<string, string> = { blue: '#365ee7', green: '#389c7e', purple: '#8c69cf', orange: '#ce914d', cyan: '#369cac', pink: '#c47b9d' };
const kbColor = (color: string) => /^#[0-9a-f]{6}$/i.test(color) ? color : kbPalette[color] || kbPalette.blue;
const statusLabels: Record<DocStatus, string> = { ready: '已就绪', processing: '构建中', parsed: '待索引', failed: '处理失败' };
const statusColors: Record<DocStatus, string> = { ready: 'green', processing: 'blue', parsed: 'gold', failed: 'red' };
const kinds = { text: '文本', table: '表格', image: '图片描述' };
const metadataFilterLabels = {dates:'时间',versions:'版本',subjects:'主体',owners:'负责人',keywords:'关键词'} as const;

function DocumentIcon({ type, size = 20 }: { type: string; size?: number }) {
  const value = type.toLowerCase();
  if (['png', 'jpg', 'jpeg', 'webp'].includes(value)) return <FileImage size={size} />;
  if (['xlsx', 'xls', 'csv'].includes(value)) return <FileSpreadsheet size={size} />;
  return <FileText size={size} />;
}

function Status({ value }: { value: DocStatus }) { return <Tag color={statusColors[value]} variant="filled">{statusLabels[value]}</Tag>; }

export default function Knowledge() {
  const { state, updateState, activeKbId, setActiveKbId, setImportOpen, navigate, refresh, flush, retryDocument } = useWorkspace();
  const { message, modal } = App.useApp();
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('全部');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);
  const [kbForm] = Form.useForm();
  const [settingsForm] = Form.useForm();
  const [tab, setTab] = useState('documents');
  const [docSearch, setDocSearch] = useState('');
  const [status, setStatus] = useState<string>('all');
  const [selectedDocs, setSelectedDocs] = useState<React.Key[]>([]);
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);
  const [editingChunk, setEditingChunk] = useState<{ docId: string; chunk: Chunk } | null>(null);
  const [chunkTitle, setChunkTitle] = useState('');
  const [chunkText, setChunkText] = useState('');
  const [chunkSearch, setChunkSearch] = useState('');
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<{ doc: DocumentRecord; chunk: Chunk; score: number; indexMetadata?:Record<string,string[]> }[]>([]);
  const [retrieval, setRetrieval] = useState('keyword');
  const [rerank, setRerank] = useState(false);
  const [topK, setTopK] = useState(5);
  const [metadataFilters,setMetadataFilters] = useState<Record<string,string>>({});
  const [buildDocId, setBuildDocId] = useState<string | null>(null);
  const [buildMode, setBuildMode] = useState<'keyword' | 'hybrid'>('keyword');
  const [building, setBuilding] = useState(false);
  const kb = state.knowledgeBases.find(item => item.id === activeKbId);
  const documents = state.documents.filter(doc => doc.kbId === kb?.id);
  const previewDoc = state.documents.find(doc => doc.id === previewDocId);
  const allTags = [...new Set(state.knowledgeBases.flatMap(item => item.tags))];
  const embeddings = state.models.filter(model => model.type === 'Embedding');
  const buildDoc = state.documents.find(doc => doc.id === buildDocId);
  const buildKb = state.knowledgeBases.find(item => item.id === buildDoc?.kbId);
  const canBuildVectors = !!state.settings?.allowExternalProcessing && state.models.some(model => model.id === buildKb?.embeddingModelId && model.status === 'connected' && model.hasKey);
  const visibleKbs = state.knowledgeBases.filter(item => (`${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase())) && (category === '全部' || item.tags.includes(category)));

  useEffect(() => { setTab('documents'); setSelectedDocs([]); setDocSearch(''); setSearched(false); setResults([]); setMetadataFilters({}); }, [activeKbId]);
  useEffect(() => { if (kb && tab === 'settings') settingsForm.setFieldsValue({ name: kb.name, description: kb.description, tags: kb.tags, embeddingModelId: kb.embeddingModelId }); }, [kb?.id, settingsForm, tab]);

  function openEditor(value?: KnowledgeBase) {
    setEditingKb(value || null);
    kbForm.resetFields();
    kbForm.setFieldsValue(value || { name: '', description: '', tags: [], embeddingModelId: embeddings.find(model => model.isDefault)?.id || embeddings[0]?.id });
    setEditorOpen(true);
  }

  async function saveKb() {
    const values = await kbForm.validateFields();
    const name = values.name.trim();
    if (state.knowledgeBases.some(item => item.id !== editingKb?.id && item.name === name)) { message.warning('已存在同名知识库，请修改名称'); return; }
    const next: KnowledgeBase = { id: editingKb?.id || uid(), color: editingKb?.color || '#365ee7', name, description: values.description?.trim() || '', tags: values.tags || [], embeddingModelId: values.embeddingModelId || '', updatedAt: now() };
    updateState(previous => ({ ...previous, knowledgeBases: editingKb ? previous.knowledgeBases.map(item => item.id === next.id ? next : item) : [...previous.knowledgeBases, next] }));
    setEditorOpen(false);
    message.success(editingKb ? '知识库设置已保存' : '知识库创建成功，可以导入知识了');
  }

  function deleteKb(value: KnowledgeBase) {
    modal.confirm({ title: `删除「${value.name}」？`, content: '该知识库内的文档、分段和导入任务将被删除，已关联的助手也会移除此知识库。', okText: '删除知识库', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => {
      updateState(previous => ({ ...previous, knowledgeBases: previous.knowledgeBases.filter(item => item.id !== value.id), documents: previous.documents.filter(doc => doc.kbId !== value.id), tasks: previous.tasks.filter(task => task.kbId !== value.id), assistants: previous.assistants.map(item => ({ ...item, kbIds: item.kbIds.filter(id => id !== value.id) })) }));
      if (activeKbId === value.id) setActiveKbId(null);
      message.success('知识库已删除');
    } });
  }

  function deleteDocs(ids: string[]) {
    updateState(previous => ({ ...previous, documents: previous.documents.filter(doc => !ids.includes(doc.id)), tasks: previous.tasks.filter(task => !ids.includes(task.docId)) }));
    setSelectedDocs([]);
    if (previewDocId && ids.includes(previewDocId)) setPreviewDocId(null);
    message.success(`已删除 ${ids.length} 个文档`);
  }

  async function rebuild(doc: DocumentRecord) {
    await flush();
    if (!doc.chunks.length || doc.error) { await retryDocument(doc.id); return; }
    setBuildMode(doc.indexMode || 'keyword'); setBuildDocId(doc.id);
  }

  async function publishIndex() {
    if (!buildDoc) return;
    setBuilding(true);
    try {
      await flush();
      await api(`/api/documents/${buildDoc.id}/build`, {method:'POST', body:JSON.stringify({indexMode:buildMode})});
      await refresh(); setBuildDocId(null); message.success('已提交索引构建任务，可在导入任务中查看进度');
    } catch (error) { message.error((error as Error).message); }
    finally { setBuilding(false); }
  }

  function openChunk(docId: string, chunk: Chunk) { setEditingChunk({ docId, chunk }); setChunkTitle(chunk.title); setChunkText(chunk.text); }
  function saveChunk() {
    if (!editingChunk || !chunkText.trim() || !chunkTitle.trim()) { message.warning('请填写分段标题和内容'); return; }
    updateState(previous => ({ ...previous, documents: previous.documents.map(doc => doc.id === editingChunk.docId ? { ...doc, chunks: doc.chunks.map(chunk => chunk.id === editingChunk.chunk.id ? { ...chunk, title: chunkTitle.trim(), text: chunkText.trim() } : chunk) } : doc) }));
    setEditingChunk(null);
    message.success('分段已保存，将自动重新构建索引');
  }

  async function runSearch() {
    if (!query.trim() || !kb) {message.warning('先输入检索问题');return;}
    setSearching(true);setSearched(true);
    try {await flush();const response=await api<{results:(Citation & {chunkId:string})[]}>('/api/search',{method:'POST',body:JSON.stringify({kbIds:[kb.id],query,mode:retrieval,rerank,topK,metadataFilters})});
      setResults(response.results.flatMap(item=>{const doc=state.documents.find(doc=>doc.id===item.documentId);return doc?[{doc,chunk:{id:item.chunkId,title:item.title,text:item.text,kind:item.kind,page:item.page,sheet:item.sheet,imageUrl:item.imageUrl},score:item.score??0,indexMetadata:item.metadata}]:[];}));await refresh();
    }catch(error){setResults([]);message.error((error as Error).message);}finally{setSearching(false);}
  }

  const columns: TableColumnsType<DocumentRecord> = [
    { title: '文档名称', dataIndex: 'name', width: '35%', render: (_, doc) => <button className="kh-doc-link" onClick={() => setPreviewDocId(doc.id)}><span className={`kh-file kh-file-${doc.type.toLowerCase()}`}><DocumentIcon type={doc.type} /></span><span><strong>{doc.name}</strong><small>{doc.type.toUpperCase()} · {doc.size}</small></span></button> },
    { title: '处理状态', dataIndex: 'status', render: (value: DocStatus, doc) => <div><Status value={value} />{doc.error && <Tooltip title={doc.error}><CircleAlert size={14} color="#dc5353" /></Tooltip>}{!!doc.parseWarnings?.length && <Tooltip title={doc.parseWarnings.join(' ')}><Tag color="gold">解析提醒</Tag></Tooltip>}</div> },
    { title: '元数据', width: 110, render: (_, doc) => <Tag color={doc.metadataStatus==='ready'?'green':doc.metadataStatus==='failed'?'error':'default'}>{doc.metadataStatus==='ready'?'已构建':doc.metadataStatus==='partial'?'部分完成':doc.metadataStatus==='processing'?'抽取中':doc.metadataStatus==='failed'?'待处理':doc.metadataStatus==='stale'?'需更新':'未构建'}</Tag> },
    { title: '分段', render: (_, doc) => <span className="kh-numeric">{doc.chunks.length}<span className="muted"> 段</span></span> },
    { title: '导入时间', dataIndex: 'createdAt', render: (value: string) => <span className="muted kh-date">{formatTime(value)}</span> },
    { title: '检索启用', render: (_, doc) => <Tooltip title={!doc.activeVersion ? '索引就绪后可参与检索' : '控制当前已发布索引是否参与知识检索'}><Switch size="small" checked={doc.enabled} disabled={!doc.activeVersion} aria-label={`启用${doc.name}检索`} onChange={enabled => updateState(previous => ({ ...previous, documents: previous.documents.map(item => item.id === doc.id ? { ...item, enabled } : item) }))} /></Tooltip> },
    { title: '', width: 48, render: (_, doc) => <Dropdown trigger={['click']} menu={{ items: [{ key: 'preview', icon: <FileText size={14} />, label: '查看内容' }, { key: 'rebuild', icon: <RotateCcw size={14} />, label: doc.error ? '重试处理' : '构建知识索引', disabled: doc.indexStatus === 'processing' }, { key: 'metadata', icon: <Sparkles size={14} />, label: '查看与补抽元数据' }, { key: 'reparse', icon: <FileText size={14} />, label: '重新解析原始文件', disabled: doc.indexStatus === 'processing' }, { type: 'divider' }, { key: 'delete', icon: <Trash2 size={14} />, danger: true, label: '删除文档' }], onClick: ({ key }) => { if (key === 'preview' || key === 'metadata') setPreviewDocId(doc.id); if (key === 'rebuild') void rebuild(doc); if (key === 'reparse') void retryDocument(doc.id, true); if (key === 'delete') modal.confirm({ title: '删除该文档？', content: '文档及其分段将从知识库中移除。', okText: '删除', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => deleteDocs([doc.id]) }); } }}><Button type="text" aria-label={`${doc.name}更多操作`} icon={<MoreHorizontal size={18} />} /></Dropdown> },
  ];

  const renderChunk = (doc: DocumentRecord, chunk: Chunk, index: number) => <article className="kh-chunk" key={chunk.id}>
    <div className="kh-chunk-top"><Space size={8}><span className="kh-chunk-index">{String(index + 1).padStart(2, '0')}</span><Tag variant="filled">{kinds[chunk.kind]}</Tag></Space><Button size="small" type="text" icon={<Pencil size={13} />} onClick={() => openChunk(doc.id, chunk)} disabled={doc.indexStatus === 'processing'}>编辑</Button></div>
    <h4>{chunk.title}</h4>{chunk.imageUrl && <figure className="demo-source-image"><img src={chunk.imageUrl} alt="文件中的原图" /><figcaption>上传文件的原图或对应 PDF 页</figcaption></figure>}<div className="kh-markdown"><ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>{chunk.text}</ReactMarkdown></div>
    <div className="kh-chunk-foot"><span>{doc.name}{chunk.sheet ? ` · ${chunk.sheet}` : chunk.page ? ` · 第 ${chunk.page} 页` : ` · ${chunk.title}`}</span><span>{chunk.text.length} 字符</span></div>
  </article>;

  return <div className={`page-body kh-page ${kb ? 'kh-detail-page' : 'kh-library-page'}`}>
    {!kb ? <>
      <header className="kh-library-heading"><div><h1>知识库</h1><p>管理企业知识资产，导入资料、检查分段，再构建可检索的知识。</p></div><div className="kh-library-actions"><Input prefix={<Search size={16} />} aria-label="搜索知识库" placeholder="搜索知识库" value={search} onChange={event => setSearch(event.target.value)} allowClear /><Button type="primary" icon={<Plus size={16} />} onClick={() => openEditor()}>新建知识库</Button></div></header>
      <div className="kh-library-toolbar"><div className="kh-category-tabs" aria-label="知识库分类">{['全部', ...allTags].map(tag => <button key={tag} onClick={() => setCategory(tag)} className={category === tag ? 'active' : ''} aria-pressed={category === tag}>{tag}{tag === '全部' && <span>{state.knowledgeBases.length}</span>}</button>)}</div><span className="kh-library-total">{state.documents.length} 个文件 · {state.documents.reduce((count, doc) => count + doc.chunks.length, 0).toLocaleString()} 个分块</span></div>
      {visibleKbs.length ? <div className="kh-kb-grid">{visibleKbs.map(item => {
        const docs = state.documents.filter(doc => doc.kbId === item.id);
        const ready = docs.filter(doc => doc.activeVersion && doc.enabled);
        const linkedApps = state.assistants.filter(assistant => assistant.kbIds.includes(item.id));
        const processing = docs.some(doc => doc.status === 'processing');
        const failed = docs.some(doc => doc.status === 'failed');
        return <article className="kh-kb-card" key={item.id} {...cardAction(()=>{setTab("documents");setActiveKbId(item.id);},`进入${item.name}`)}>
          <div className="kh-kb-top"><button className="kh-kb-identity" onClick={() => setActiveKbId(item.id)} aria-label={`打开${item.name}`}><span className="kh-kb-symbol" style={{ backgroundColor: kbColor(item.color) }}><Database size={23} strokeWidth={1.8} /></span><span><strong className="kh-kb-name">{item.name}</strong><span className="kh-kb-kind">通用知识库 <Tag color={processing ? 'blue' : failed ? 'orange' : ready.length ? 'green' : 'default'}>{processing ? '构建中' : failed ? '需关注' : ready.length ? '已就绪' : '待导入'}</Tag></span></span></button><Dropdown trigger={['click']} menu={{ items: [{ key: 'edit', label: '编辑知识库', icon: <Pencil size={14} /> }, { key: 'delete', label: '删除知识库', icon: <Trash2 size={14} />, danger: true }], onClick: ({ key }) => key === 'edit' ? openEditor(item) : deleteKb(item) }}><Button type="text" aria-label={`${item.name}更多操作`} icon={<MoreHorizontal size={18} />} /></Dropdown></div>
          <button className="kh-kb-body" onClick={() => setActiveKbId(item.id)}><p>{item.description || '添加描述，说明知识范围与适用的业务场景。'}</p></button>
          {item.tags.length > 0 && <div className="kh-kb-tags">{item.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</div>}
          <div className="kh-kb-numbers"><span><strong>{docs.length}</strong> 个文件</span><span><strong>{docs.reduce((count, doc) => count + doc.chunks.length, 0).toLocaleString()}</strong> 个分块</span><span className="kh-kb-model" title={state.models.find(model => model.id === item.embeddingModelId)?.name || '本地关键词索引'}>{state.models.find(model => model.id === item.embeddingModelId)?.name || '关键词索引'}</span></div>
          <div className="kh-kb-bottom"><span title={linkedApps.map(assistant => assistant.name).join('、')}>被 {linkedApps.length} 个应用引用{linkedApps.length > 0 ? `：${linkedApps.map(assistant => assistant.name).join('、')}` : ''}</span><small>{formatTime(item.updatedAt)}</small></div>
        </article>;
      })}</div> : <div className="surface kh-empty"><Empty description={search || category !== '全部' ? '没有找到符合条件的知识库' : '创建第一个知识库，开始组织企业资料'} />{!search && category === '全部' && <Button type="primary" onClick={() => openEditor()}>新建知识库</Button>}</div>}
      <div className="kh-bottom-tip"><Sparkles size={16} /><span>从文档到答案，只需三步：创建知识库、导入知识、开始对话。</span><button onClick={() => { if (state.knowledgeBases.length) setImportOpen(true); else openEditor(); }}>开始体验 <ArrowRight size={14} /></button></div>
    </> : <>
      <aside className="kh-sub-sidebar">
        <button className="kh-back" onClick={() => setActiveKbId(null)}><ArrowLeft size={15} />全部知识库</button>
        <div className="kh-sub-identity"><span className="kh-kb-symbol" style={{ backgroundColor: kbColor(kb.color) }}><Database size={20} /></span><div><strong>{kb.name}</strong><small>通用知识库</small></div></div>
        <nav aria-label="知识库导航">
          <button className={`kh-sub-link ${tab === 'documents' || tab === 'chunks' ? 'active' : ''}`} onClick={() => setTab('documents')} aria-current={tab === 'documents' || tab === 'chunks' ? 'page' : undefined}><FileText size={16} />数据集</button>
          <button className={`kh-sub-link ${tab === 'retrieval' ? 'active' : ''}`} onClick={() => setTab('retrieval')} aria-current={tab === 'retrieval' ? 'page' : undefined}><Search size={16} />检索测试</button>
          <button className={`kh-sub-link ${tab === 'settings' ? 'active' : ''}`} onClick={() => setTab('settings')} aria-current={tab === 'settings' ? 'page' : undefined}><Settings2 size={16} />配置</button>
        </nav>
        <dl className="kh-sub-properties"><dt>文件</dt><dd>{documents.length}</dd><dt>分块</dt><dd>{documents.reduce((count, doc) => count + doc.chunks.length, 0).toLocaleString()}</dd><dt>索引模型</dt><dd>{state.models.find(model => model.id === kb.embeddingModelId)?.name || '关键词索引'}</dd><dt>可检索</dt><dd>{documents.filter(doc => doc.activeVersion && doc.enabled).length} 个文件</dd></dl>
        <button className="kh-sub-link kh-task-link" onClick={() => navigate('tasks')}><FileClock size={16} />导入任务<ChevronRight size={13} /></button>
        <div className="kh-sub-apps"><span>引用本库的应用</span>{state.assistants.filter(assistant => assistant.kbIds.includes(kb.id)).map(assistant => <button className="kh-sub-link" key={assistant.id} onClick={() => navigate('assistants')}><BookOpen size={15} /><span>{assistant.name}</span></button>)}{!state.assistants.some(assistant => assistant.kbIds.includes(kb.id)) && <p>尚无应用引用此知识库</p>}</div>
      </aside>
      <section className="kh-detail-main">
        <header className="kh-detail-main-heading"><div><h1>{tab === 'retrieval' ? '检索测试' : tab === 'settings' ? '配置' : '数据集'}</h1><p>{tab === 'retrieval' ? '测试知识召回，检查答案可用的资料来源。' : tab === 'settings' ? '管理知识库基本信息和索引模型。' : '管理导入文件，预览内容与分块，检查知识索引状态。'}</p></div>{(tab === 'documents' || tab === 'chunks') && <div className="kh-detail-actions"><Button icon={<FileClock size={15} />} onClick={() => navigate('tasks')}>导入任务</Button><Button type="primary" icon={<Plus size={16} />} onClick={() => setImportOpen(true)}>导入数据</Button></div>}</header>
        {(tab === 'documents' || tab === 'chunks') && <div className="kh-dataset-switch" role="group" aria-label="数据集视图"><button className={tab === 'documents' ? 'active' : ''} aria-pressed={tab === 'documents'} onClick={() => setTab('documents')}><FileText size={14} />文件列表</button><button className={tab === 'chunks' ? 'active' : ''} aria-pressed={tab === 'chunks'} onClick={() => setTab('chunks')}><Layers size={14} />分段浏览</button></div>}
      <Tabs activeKey={tab} onChange={setTab} renderTabBar={() => <></>} className="kh-detail-tabs" items={[
        { key: 'documents', label: '知识文档', children: <div className="surface kh-document-surface"><div className="toolbar kh-document-toolbar"><Space><Input prefix={<Search size={16} />} placeholder="搜索文档名称" allowClear value={docSearch} onChange={event => setDocSearch(event.target.value)} style={{ width: 260 }} /><Select value={status} style={{ width: 135 }} onChange={setStatus} options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))]} /></Space><span className="kh-document-count">共 {documents.filter(doc => doc.name.toLowerCase().includes(docSearch.toLowerCase()) && (status === 'all' || doc.status === status)).length} 个文件</span></div>
          {selectedDocs.length > 0 && <div className="kh-selection-bar"><span>已选中 {selectedDocs.length} 个文档</span><Popconfirm title="删除选中的文档？" description="同时删除对应分段和导入任务。" onConfirm={() => deleteDocs(selectedDocs.map(String))} okText="删除" cancelText="取消"><Button danger size="small" icon={<Trash2 size={13} />}>批量删除</Button></Popconfirm><Button type="text" size="small" onClick={() => setSelectedDocs([])}>取消选择</Button></div>}
          <Table rowKey="id" columns={columns} dataSource={documents.filter(doc => doc.name.toLowerCase().includes(docSearch.toLowerCase()) && (status === 'all' || doc.status === status))} rowSelection={{ selectedRowKeys: selectedDocs, onChange: keys => setSelectedDocs(keys) }} pagination={{ pageSize: 8, hideOnSinglePage: true }} locale={{ emptyText: <div className="kh-empty"><FolderOpen size={36} color="#aab4ca" /><p>这里还没有知识文档</p><Button type="primary" onClick={() => setImportOpen(true)}>导入第一份知识</Button></div> }} scroll={{ x: 850 }} />
          <div className="kh-table-note"><CircleAlert size={14} />已发布且启用的索引参与检索；重新解析期间保留已有版本，未发布的预览内容不参与检索。</div></div> },
        { key: 'chunks', label: '知识分段', children: <><div className="kh-chunks-toolbar"><span className="muted">保留语义完整，让检索找到正确的知识。</span><Input prefix={<Search size={15} />} placeholder="搜索分段内容" value={chunkSearch} onChange={event => setChunkSearch(event.target.value)} style={{ width: 280 }} allowClear /></div><div className="kh-chunks-grid">{documents.flatMap(doc => doc.chunks.filter(chunk => `${chunk.title} ${chunk.text}`.includes(chunkSearch)).map((chunk, index) => renderChunk(doc, chunk, index)))}</div>{!documents.some(doc => doc.chunks.some(chunk => `${chunk.title} ${chunk.text}`.includes(chunkSearch))) && <Empty description="暂无匹配的知识分段" />}</> },
        { key: 'retrieval', label: '检索测试', children: <div className="kh-retrieval-layout"><div className="surface kh-retrieval-config"><h3>测试知识召回</h3><p className="muted">先确认能找到资料，再优化回答质量。</p><Alert type="info" showIcon title="真实知识检索" description="关键词检索无需模型。语义/混合检索和重排会使用配置的模型，需要先开启云端处理。" /><label className="kh-field-label">检索问题</label><Input.TextArea value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：差旅报销需要准备哪些材料？" rows={4} /><div className="kh-suggested-query"><button onClick={() => setQuery('差旅报销需要哪些材料')}>试试：差旅报销需要哪些材料？</button></div><label className="kh-field-label">检索方式</label><Radio.Group value={retrieval} onChange={event => setRetrieval(event.target.value)} options={[{ value: 'hybrid', label: '混合检索' }, { value: 'vector', label: '语义检索' }, { value: 'keyword', label: '关键词' }]} /><div className="metadata-retrieval-filters">{Object.entries(metadataFilterLabels).map(([field,label])=><label key={field}>{label}<Select allowClear showSearch optionFilterProp="label" placeholder="不限" value={metadataFilters[field]||undefined} onChange={value=>setMetadataFilters(previous=>({...previous,[field]:value||''}))} options={Array.from(new Set(documents.flatMap(doc=>(doc.metadata?.[field as keyof typeof metadataFilterLabels]??[]).map(item=>item.value)))).sort().map(value=>({value,label:value}))}/></label>)}</div><p className="muted">筛选作用于已发布索引；元数据修改后需构建发布。</p><div className="kh-setting-row"><span>结果重排 <small>使用默认 Rerank 模型</small></span><Switch checked={rerank} onChange={setRerank} /></div><div className="kh-setting-row"><span>返回分段数量</span><InputNumber min={1} max={20} value={topK} onChange={value => setTopK(value || 5)} /></div><Button block type="primary" size="large" icon={<Search size={16} />} loading={searching} onClick={runSearch}>开始检索测试</Button></div><div className="surface kh-retrieval-results"><div className="section-heading"><h3>召回结果</h3>{searched && <Tag variant="filled">{results.length} 个分段</Tag>}</div>{!searched ? <div className="kh-retrieval-empty"><span><Search size={30} /></span><h4>找到每个答案背后的依据</h4><p>输入一个业务问题，查看命中的文档和知识分段。</p></div> : results.length ? <>{results.map((result, index) => <div className="kh-result" key={result.chunk.id}><div className="kh-result-title"><span className="kh-result-rank">{index + 1}</span><strong>{result.chunk.title}</strong><Tag color="blue" variant="filled">{result.score.toFixed(4)} 检索分数</Tag></div><p>{result.chunk.text.slice(0, 260)}</p>{result.indexMetadata&&<Space size={[3,4]} wrap>{['versions','subjects','owners'].flatMap(field=>(result.indexMetadata?.[field]??[]).slice(0,3).map(value=><Tag key={`${field}-${value}`}>{metadataFilterLabels[field as keyof typeof metadataFilterLabels]}：{value}</Tag>))}</Space>}<button onClick={() => setPreviewDocId(result.doc.id)}><FileText size={13} />{result.doc.name} · {result.chunk.sheet || (result.chunk.page ? `第 ${result.chunk.page} 页` : result.chunk.title)}<ChevronRight size={13} /></button></div>)}<p className="kh-result-note">结果来自当前知识库已发布的真实索引，点击来源核对内容。</p></> : <Empty description="未命中资料，请调整关键词，或检查文档是否已就绪并启用。" />}</div></div> },
        { key: 'settings', label: '知识库设置', children: <div className="surface kh-settings"><h3>基本信息</h3><p className="muted">清晰的名称和描述，帮助团队快速找到知识。</p><Form layout="vertical" form={settingsForm} onFinish={values => { if (!kb) return; if (state.knowledgeBases.some(item => item.id !== kb.id && item.name === values.name.trim())) { message.warning('已存在同名知识库'); return; } const changedModel = values.embeddingModelId !== kb.embeddingModelId; const apply = () => { updateState(previous=>({...previous,knowledgeBases:previous.knowledgeBases.map(item=>item.id===kb.id?{...item,...values,name:values.name.trim(),updatedAt:now()}:item)}));message.success('设置已保存，模型变更会由后端重新构建索引'); }; if (changedModel && documents.length) modal.confirm({ title: '切换向量模型并重新构建？', content: '模型切换后将重新构建索引。已有索引在新版本成功发布前保持可用；需要配置对应模型并允许云端处理。', okText: '确认切换', cancelText: '取消', onOk: apply }); else apply(); }}><Form.Item name="name" label="知识库名称" rules={[{ required: true, whitespace: true, message: '请输入知识库名称' }]}><Input maxLength={40} showCount /></Form.Item><Form.Item name="description" label="知识库描述"><Input.TextArea rows={3} maxLength={160} showCount /></Form.Item><Form.Item name="tags" label="分类标签"><Select mode="tags" options={allTags.map(tag => ({ value: tag, label: tag }))} placeholder="输入或选择分类" maxCount={5} /></Form.Item><Form.Item name="embeddingModelId" label="向量模型" extra="同一知识库使用统一的向量模型。更换模型需要重新构建索引。"><Select options={[{value:'',label:'仅使用本地关键词索引'},...embeddings.map(model => ({ value: model.id, label: `${model.name} · ${model.provider}` }))]} placeholder="请选择向量模型" /></Form.Item><Button type="primary" htmlType="submit">保存设置</Button></Form><div className="kh-danger-zone"><div><strong>删除知识库</strong><p>删除该知识库中的所有文档与分段，操作无法撤销。</p></div><Button danger onClick={() => deleteKb(kb)}>删除知识库</Button></div></div> },
      ]} />
      </section>
    </>}
    <Modal forceRender title={editingKb ? '编辑知识库' : '新建知识库'} open={editorOpen} onCancel={() => setEditorOpen(false)} onOk={saveKb} okText={editingKb ? '保存修改' : '创建知识库'} cancelText="取消" width={520}><p className="muted">围绕一个主题组织知识，例如人事制度、产品手册或项目资料。</p><Form form={kbForm} layout="vertical"><Form.Item label="知识库名称" name="name" rules={[{ required: true, whitespace: true, message: '请输入知识库名称' }]}><Input placeholder="例如：企业人事制度" maxLength={40} showCount /></Form.Item><Form.Item label="描述" name="description"><Input.TextArea placeholder="说明知识范围与适用场景" rows={3} maxLength={160} showCount /></Form.Item><Form.Item label="分类标签" name="tags"><Select mode="tags" maxCount={5} placeholder="选择或输入标签" options={allTags.map(tag => ({ value: tag, label: tag }))} /></Form.Item><Form.Item label="向量模型" name="embeddingModelId" extra={editingKb ? "切换向量模型请进入知识库设置，将重新构建文档索引。" : "可先使用本地关键词索引；向量索引需配置模型。"}><Select disabled={!!editingKb} placeholder="选择向量模型" options={[{value:'',label:'仅使用本地关键词索引'},...embeddings.map(model => ({ value: model.id, label: `${model.name} · ${model.provider}` }))]} /></Form.Item></Form></Modal>
    <Drawer title="文档内容" open={!!previewDoc} size={730} onClose={() => setPreviewDocId(null)}><div className="kh-document-preview">{previewDoc && <><div className="kh-preview-heading"><span className={`kh-file kh-file-${previewDoc.type.toLowerCase()}`}><DocumentIcon type={previewDoc.type} size={26} /></span><div><h3>{previewDoc.name}</h3><p className="muted">{previewDoc.size} · {previewDoc.chunks.length} 个分段 · {formatTime(previewDoc.createdAt)}</p></div><Status value={previewDoc.status} /><Button href={`/api/documents/${previewDoc.id}/file`} target="_blank" rel="noopener noreferrer">打开原始文件</Button></div>{previewDoc.error && <Alert type="error" showIcon title="文档处理失败" description={previewDoc.error} action={<Button onClick={() => rebuild(previewDoc)}>重试</Button>} />}<ParsingNotice warnings={previewDoc.parseWarnings}/><DocumentMetadataPanel document={previewDoc} onBuild={()=>void rebuild(previewDoc)}/>{previewDoc.indexStatus==='parsed'&&<Alert type="info" showIcon title="解析结果等待发布索引" description={previewDoc.activeVersion?"当前检索继续使用之前发布的版本。确认本次解析后，再构建新索引。":"确认解析内容后，构建索引才能参与检索。"} action={<Button onClick={()=>void rebuild(previewDoc)}>构建知识索引</Button>}/>}<Alert showIcon type="info" title="文件解析结果" description="以下内容由已上传文件实际提取；OCR 与图片理解内容请结合原图核对。" /><div className="kh-preview-chunks">{previewDoc.chunks.map((chunk, index) => renderChunk(previewDoc, chunk, index))}</div>{!previewDoc.chunks.length && <Empty description="暂无分段，处理完成后可查看内容" />}</>}</div></Drawer>
    <Modal open={!!buildDoc} title="构建知识索引" onCancel={()=>setBuildDocId(null)} onOk={()=>void publishIndex()} confirmLoading={building} okButtonProps={{disabled:buildMode==='hybrid'&&!canBuildVectors}} okText="开始构建" cancelText="取消"><p>{buildDoc?.name}</p><Radio.Group value={buildMode} onChange={event=>setBuildMode(event.target.value)} options={[{value:'keyword',label:'本地关键词索引（无需模型）'},{value:'hybrid',label:'关键词＋云端向量索引',disabled:!canBuildVectors}]}/><p className="muted">向量索引需先连接此知识库的 Embedding 模型并允许云端处理。新版本发布前，已有索引保持可用。</p><ParsingNotice warnings={buildDoc?.parseWarnings}/></Modal>
    <Modal title="编辑知识分段" open={!!editingChunk} onCancel={() => setEditingChunk(null)} onOk={saveChunk} okText="保存分段" cancelText="取消" width={700}><p className="muted">修改后会持久保存并重新构建索引，发布前继续使用已有索引。</p><label className="kh-field-label">分段标题</label><Input value={chunkTitle} onChange={event => setChunkTitle(event.target.value)} maxLength={120} /><label className="kh-field-label">分段内容 · 支持 Markdown</label><Input.TextArea rows={13} value={chunkText} onChange={event => setChunkText(event.target.value)} /></Modal>
  </div>;
}

export { ImportWizard } from '../ImportWizard';
