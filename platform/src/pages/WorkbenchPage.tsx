import { ArrowRight, BookOpen, Bot, ChevronRight, Clock3, Database, FileText, LayoutGrid, Layers3, MessageSquare, Plus, Search, Sparkles, Star } from 'lucide-react';
import { useEffect, useState, type CSSProperties } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiFetch, errorMessage, type ApiKnowledgeBase, type ApiModelOption, type ApiEvaluationSet } from '../api/client';
import { ReadinessChecklist } from '../components/ReadinessChecklist';
import { fdeApi, type FDEApp } from '../api/fde';
import { isManager, useAuth } from '../auth';
import { Loading, Notice } from '../components/ui';
import '../legacy-workbench.css';

type Scene = 'all' | 'knowledge' | 'draft';
const scenes = [
  {id:'all' as const, title:'全部应用', description:'团队的 AI 工作入口', color:'#3370ff', icon:LayoutGrid},
  {id:'knowledge' as const, title:'知识问答', description:'基于企业资料寻找答案', color:'#12b76a', icon:BookOpen},
  {id:'draft' as const, title:'待配置应用', description:'完成配置、评测后发布', color:'#7a5af8', icon:Sparkles},
];
function storedList(key: string): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem(key) ?? '[]'); return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []; }
  catch { return []; }
}
function greeting() {
  const hour = Number(new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'numeric',hour12:false}).format(new Date()));
  return hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
}
const published = (app: FDEApp) => app.is_enabled && Boolean(app.published_version_id);
export function WorkbenchPage() {
  const navigate = useNavigate();
  const {me} = useAuth();
  const staff = isManager(me?.role);
  const [apps,setApps] = useState<FDEApp[] | null>(null);
  const [kbs,setKbs] = useState<ApiKnowledgeBase[] | null>(null);
  const [models,setModels] = useState<ApiModelOption[]>([]);
  const [sets,setSets] = useState<ApiEvaluationSet[]>([]);
  const [error,setError] = useState('');
  const [sideError,setSideError] = useState('');
  const [scene,setScene] = useState<Scene>('all');
  const [query,setQuery] = useState('');
  const [favorites,setFavorites] = useState(() => storedList('zhishu.favorite-apps'));
  const [recent,setRecent] = useState(() => storedList('zhishu.recent-apps'));
  useEffect(() => {
    let active = true;
    void fdeApi.list().then(list => {if(active) setApps(list.filter(app => staff || published(app)));}).catch(caught => {if(active) setError(errorMessage(caught));});
    if(staff) void Promise.all([apiFetch<ApiKnowledgeBase[]>('/knowledge-bases'), apiFetch<ApiModelOption[]>('/model-options'),apiFetch<ApiEvaluationSet[]>('/evaluation-sets')])
      .then(([bases,options,evaluations]) => {if(active){setKbs(bases);setModels(options);setSets(evaluations);}}).catch(caught => {if(active) setSideError(errorMessage(caught));});
    return () => {active = false;};
  },[staff]);
  const openApp = (app: FDEApp) => {
    const next = [app.id,...recent.filter(id => id !== app.id)].slice(0,4);
    setRecent(next);
    try {localStorage.setItem('zhishu.recent-apps',JSON.stringify(next));} catch { /* Session remains usable. */ }
    navigate(published(app) ? `/chat/${app.id}` : `/apps/${app.id}`);
  };
  const toggleFavorite = (id: string) => {
    const next = favorites.includes(id) ? favorites.filter(value => value !== id) : [...favorites,id];
    setFavorites(next);
    try {localStorage.setItem('zhishu.favorite-apps',JSON.stringify(next));} catch { /* Session remains usable. */ }
  };
  const matches = (app: FDEApp, key: Scene) => key === 'all' || (key === 'knowledge' ? app.manifest.knowledge_base_ids.length > 0 : !published(app));
  const visible = (apps ?? []).filter(app => matches(app,scene) && `${app.name} ${app.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  const favoriteApps = (apps ?? []).filter(app => favorites.includes(app.id));
  const recentApps = recent.map(id => apps?.find(app => app.id === id)).filter((app): app is FDEApp => Boolean(app));
  const stats = staff ? [
    {label:'企业知识库',value:kbs?.length,suffix:'个',path:'/knowledge'},
    {label:'知识文件',value:kbs?.reduce((n,kb) => n+kb.file_count,0),suffix:'份',path:'/knowledge'},
    {label:'知识分段',value:kbs?.reduce((n,kb) => n+(kb.total_chunk_count ?? kb.chunk_count),0),suffix:'条',path:'/knowledge'},
    {label:'应用草稿',value:apps?.filter(app => !published(app)).length,suffix:'个',path:'/apps'},
  ] : [{label:'可用应用',value:apps?.length,suffix:'个',path:'/workbench'},{label:'我的收藏',value:favoriteApps.length,suffix:'个',path:'/workbench'}];
  return <div className="legacy-workbench"><div className="zh-workbench"><div className="zh-workbench-inner">
    <header className="zh-workbench-heading"><div><h1>{greeting()}，开始今天的工作</h1><p>选择一个业务应用开始工作，让知识和 AI 融入每一个任务。</p></div><span className="zh-workbench-live"><i/>本地工作空间</span></header>
    <div className="zh-workbench-search"><Search size={18}/><input aria-label="搜索工作台应用" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索应用，例如「知识问答」「写作助手」"/>{query ? <button onClick={() => setQuery('')}>清空</button> : null}</div>
    {error ? <Notice tone="error">{error}</Notice> : null}
    {!apps && !error ? <Loading/> : null}
    {staff && apps && kbs ? <ReadinessChecklist apps={apps} knowledge={kbs} models={models} sets={sets}/> : null}
    <div className="zh-workbench-layout"><div className="zh-workbench-content">
      <div className="zh-workbench-scenes" aria-label="应用场景">{scenes.filter(item => staff || item.id !== 'draft').map(item => {
        const Icon = item.icon;
        return <button key={item.id} className={scene === item.id ? 'is-active' : ''} style={{'--scene-color':item.color} as CSSProperties} aria-pressed={scene === item.id} onClick={() => setScene(item.id)}><div><Icon size={17}/><strong>{item.title}</strong></div><p>{item.description}</p><span>{(apps ?? []).filter(app => matches(app,item.id)).length} 个应用</span></button>;
      })}</div>
      <div className="zh-workbench-section-title"><h2>{scenes.find(item => item.id === scene)?.title}</h2><span>{visible.length} 个</span>{staff ? <button onClick={() => navigate('/apps')}>管理应用<ArrowRight size={13}/></button> : null}</div>
      <p className="draft-context">{scene === 'draft' ? '这些草稿需要完成配置与评测后再发布。' : '卡片会区分已发布应用和待配置草稿；业务使用者只看到已发布应用。'}{staff && apps?.some(app=>app.description.startsWith('【迁移草稿】')) ? <> 迁移草稿仅保留基础配置，<Link to="/settings?tab=local">查看旧流程使用说明</Link>。</> : null}</p>
      <div className="zh-workbench-apps">{visible.map(app => {
        const model = models.find(item => item.id === app.manifest.llm_model_id);
        return <article className="zh-workbench-app-card" key={app.id}>
          <div className="zh-workbench-app-top"><span className="zh-workbench-app-icon"><Bot size={23}/></span><div><h3><button onClick={() => openApp(app)}>{app.name}</button></h3><span className="zh-workbench-tag">{app.manifest.type === 'agent' ? 'Agent' : '简易应用'}{published(app) ? '' : ' · 草稿'}</span></div><button className={`zh-workbench-star ${favorites.includes(app.id) ? 'is-favorite' : ''}`} aria-label={`${favorites.includes(app.id) ? '取消收藏' : '收藏'}${app.name}`} aria-pressed={favorites.includes(app.id)} onClick={() => toggleFavorite(app.id)}><Star size={17} fill={favorites.includes(app.id) ? 'currentColor' : 'none'}/></button></div>
          <p className="zh-workbench-app-description">{app.description || '连接模型与企业知识，协助完成日常工作。'}</p>
          <div className="zh-workbench-app-details"><span><Database size={12}/>{app.manifest.knowledge_base_ids.length} 个知识库</span><span>{model?.display_name || '待配置模型'}</span></div>
          <footer><span><i className={published(app) ? 'is-ready' : ''}/>{published(app) ? '已发布' : '尚未发布'}</span><button onClick={() => openApp(app)}>{published(app) ? '开始使用' : '继续配置'}<ArrowRight size={14}/></button></footer>
        </article>;
      })}{staff && !query ? <button className="zh-workbench-create-card" onClick={() => navigate('/apps?create=1')}><span><Plus size={22}/></span><strong>创建业务应用</strong><p>配置模型、关联知识库，<br/>搭建属于团队的 AI 助手。</p><b>前往应用中心<ArrowRight size={13}/></b></button> : null}</div>
      {apps && !visible.length && (query || !staff) ? <div className="zh-workbench-empty"><Search size={28}/><strong>{query ? '没有匹配的应用' : '还没有可用应用'}</strong><p>{query ? '试试其他关键词。' : '应用发布后会出现在这里。'}</p></div> : null}
      <section className="zh-workbench-start"><div className="zh-workbench-section-title"><h2>从知识到答案</h2><span>连接你的工作流程</span></div><div className="zh-workbench-start-grid">{staff ? <button onClick={() => navigate('/knowledge')}><span className="zh-workbench-step-icon"><BookOpen size={19}/></span><div><strong>沉淀团队知识</strong><p>导入资料，构建可检索的知识库</p></div><ChevronRight size={15}/></button> : null}<button onClick={() => {const app = apps?.find(published); if(app) openApp(app); else if(staff) navigate('/apps');}}><span className="zh-workbench-step-icon"><MessageSquare size={19}/></span><div><strong>开启有据可查的对话</strong><p>提出问题，结合原始来源核对答案</p></div><ChevronRight size={15}/></button></div></section>
    </div><aside className="zh-workbench-aside">
      <section className="zh-workbench-side-card"><h2><Star size={16} color="#fdb022"/>我的收藏</h2>{favoriteApps.length ? favoriteApps.map(app => <button className="zh-workbench-side-row" key={app.id} onClick={() => openApp(app)}><span className="zh-workbench-small-icon"><Bot size={16}/></span><span>{app.name}</span><ChevronRight size={14}/></button>) : <p className="zh-workbench-side-empty">点击应用卡片右上角的星标，将常用应用放在这里。</p>}</section>
      <section className="zh-workbench-side-card"><h2><Clock3 size={16}/>最近使用</h2>{recentApps.length ? recentApps.map(app => <button className="zh-workbench-side-row" key={app.id} onClick={() => openApp(app)}><span className="zh-workbench-small-icon"><MessageSquare size={15}/></span><span>{app.name}</span><ChevronRight size={14}/></button>) : <p className="zh-workbench-side-empty">开始使用应用后，最近记录会显示在这里。</p>}</section>
      <section className="zh-workbench-side-card zh-workbench-stat-card"><h2><Layers3 size={16}/>工作空间沉淀</h2><div className="zh-workbench-stats">{stats.map(stat => <button key={stat.label} onClick={() => navigate(stat.path)}><span>{stat.label}</span><strong>{stat.value?.toLocaleString() ?? '—'}<small>{stat.suffix}</small></strong></button>)}</div>{sideError ? <p>{sideError}</p> : <p>来自当前工作空间的实际记录</p>}</section>
      {staff ? <button className="zh-workbench-need-card" onClick={() => navigate('/apps?create=1')}><Sparkles size={22}/><span><strong>没有合适的应用？</strong><small>从知识问答助手开始搭建</small></span><ArrowRight size={16}/></button> : null}
      <div className="zh-workbench-privacy"><FileText size={13}/><span>资料与会话保存在本机数据库</span></div>
    </aside></div>
  </div></div></div>;
}
