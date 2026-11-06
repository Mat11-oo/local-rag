import { cardAction } from '../cardAction';
import { useState } from 'react';
import { ArrowRight, BookOpen, Bot, ChevronRight, Clock3, Database, FileText, Grid2X2, Layers3, MessageSquare, Plus, Search, Sparkles, Star } from 'lucide-react';
import { formatTime, useWorkspace } from '../store';
import type { AssistantConfig } from '../types';
import './workbench.css';

type Scene = 'all' | 'knowledge' | 'general';
const FAVORITES_KEY = 'zhishu.favorite-apps';
const scenes: { id: Scene; title: string; description: string; color: string; icon: typeof BookOpen }[] = [
  { id: 'all', title: '全部应用', description: '团队的 AI 工作入口', color: '#3370ff', icon: Grid2X2 },
  { id: 'knowledge', title: '知识问答', description: '基于企业资料寻找答案', color: '#12b76a', icon: BookOpen },
  { id: 'general', title: '待配置应用', description: '关联知识库后开始使用', color: '#7a5af8', icon: Sparkles },
];
function greeting() {
  const hour = Number(new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', hour12: false }).formatToParts(new Date()).find(part => part.type === 'hour')?.value);
  return hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
}
function readFavorites(): string[] {
  try { const saved: unknown = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]'); return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string') : []; }
  catch { return []; }
}

export default function Overview() {
  const { state, navigate, setActiveAssistantId, setActiveSessionId, role } = useWorkspace();
  const [scene, setScene] = useState<Scene>('all');
  const [query, setQuery] = useState('');
  const [favorites, setFavorites] = useState<string[]>(readFavorites);
  const applications = state.assistants.filter(app => (scene === 'all' || (scene === 'knowledge' ? app.kbIds.length > 0 : !app.kbIds.length)) && `${app.name} ${app.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  const favoriteApps = state.assistants.filter(app => favorites.includes(app.id));
  const recent = state.sessions.filter(session => state.assistants.some(app => app.id === session.assistantId)).sort((a, b) => (b.messages.at(-1)?.createdAt || b.createdAt).localeCompare(a.messages.at(-1)?.createdAt || a.createdAt)).slice(0, 4);
  const publishedDocs = state.documents.filter(doc => doc.enabled && doc.activeVersion);
  const myQuestions = (appId?: string) => state.sessions.filter(session => !appId || session.assistantId === appId).reduce((total, session) => total + session.messages.filter(item => item.role === 'user').length, 0);
  const stats = role === 'user' ? [
    { label: '可用应用', value: state.assistants.length, suffix: '个' },
    { label: '我的会话', value: state.sessions.length, suffix: '段' },
    { label: '我的提问', value: myQuestions(), suffix: '次' },
    { label: '我的收藏', value: favoriteApps.length, suffix: '个' },
  ] : [
    { label: role === 'admin' ? '近期调用' : '我的提问', value: role === 'admin' ? state.logs.filter(log => log.kind === 'chat').length : myQuestions(), suffix: '次' },
    { label: '企业知识库', value: state.knowledgeBases.length, suffix: '个' },
    { label: '已发布文档', value: publishedDocs.length, suffix: '份' },
    { label: '知识分段', value: publishedDocs.reduce((total, doc) => total + doc.chunks.length, 0), suffix: '条' },
  ];
  const openApp = (app: AssistantConfig) => { setActiveSessionId(null); setActiveAssistantId(app.id); navigate('chat'); };
  const toggleFavorite = (id: string) => {
    const next = favorites.includes(id) ? favorites.filter(value => value !== id) : [...favorites, id];
    setFavorites(next);
    try { localStorage.setItem(FAVORITES_KEY, JSON.stringify(next)); } catch { /* Favorites remain usable for this visit when browser storage is unavailable. */ }
  };
  return <div className="zh-workbench">
    <div className="zh-workbench-inner">
      <header className="zh-workbench-heading"><div><h1>{greeting()}，开始今天的工作</h1><p>选择一个业务应用开始工作，让知识和 AI 融入每一个任务。</p></div><span className="zh-workbench-live"><i />Local RAG</span></header>
      <div className="zh-workbench-search"><Search size={18} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索应用，例如「知识问答」「写作助手」" aria-label="搜索工作台应用" />{query && <button onClick={() => setQuery('')} aria-label="清空应用搜索">清空</button>}</div>
      <div className="zh-workbench-layout">
        <div className="zh-workbench-content">
          <div className="zh-workbench-scenes" aria-label="应用场景">{scenes.map(item => { const Icon = item.icon; const count = state.assistants.filter(app => item.id === 'all' || (item.id === 'knowledge' ? app.kbIds.length > 0 : !app.kbIds.length)).length; return <button key={item.id} className={scene === item.id ? 'is-active' : ''} style={{ '--scene-color': item.color } as React.CSSProperties} onClick={() => setScene(item.id)} aria-pressed={scene === item.id}><div><Icon size={17} /><strong>{item.title}</strong></div><p>{item.description}</p><span>{count} 个应用</span></button>; })}</div>
          <div className="zh-workbench-section-title"><h2>{scenes.find(item => item.id === scene)?.title}</h2><span>{applications.length} 个</span>{role !== 'user' && <button onClick={() => navigate('assistants')}>管理应用<ArrowRight size={13} /></button>}</div>
          <div id="workbench-apps" className="zh-workbench-apps">{applications.map((app, index) => {
            const model = state.models.find(item => item.id === app.modelId);
            const usageCount = role === 'admin' ? state.logs.filter(log => log.kind === 'chat' && log.assistantId === app.id).length : myQuestions(app.id);
            return <article className="zh-workbench-app-card" key={app.id} {...cardAction(()=>openApp(app),`打开${app.name}`)}>
              <div className="zh-workbench-app-top"><span className={`zh-workbench-app-icon tone-${index % 4}`}><Bot size={23} /></span><div><h3><button onClick={() => openApp(app)}>{app.name}</button></h3><span className="zh-workbench-tag">{app.type==='agent'?'Agent':app.type==='chatflow'?'Chat Flow':'简易应用'}</span></div><button className={`zh-workbench-star ${favorites.includes(app.id) ? 'is-favorite' : ''}`} onClick={() => toggleFavorite(app.id)} aria-label={`${favorites.includes(app.id) ? '取消收藏' : '收藏'}${app.name}`} aria-pressed={favorites.includes(app.id)}><Star size={17} fill={favorites.includes(app.id) ? 'currentColor' : 'none'} /></button></div>
              <p className="zh-workbench-app-description">{app.description || app.welcome || '连接模型与企业知识，协助完成日常工作。'}</p>
              <div className="zh-workbench-app-details"><span><Database size={12} />{app.kbIds.length ? `${app.kbIds.length} 个知识库` : '待关联知识库'}</span><span title={model?.name}>{model?.name || '待配置模型'}</span></div>
              <footer><span><i className={model?.status === 'connected' && app.kbIds.length ? 'is-ready' : ''} />{role === 'admin' ? '近期调用' : '我的提问'} {usageCount} 次</span><button onClick={() => openApp(app)}>开始使用<ArrowRight size={14} /></button></footer>
            </article>;
          })}{role !== 'user' && !query && <button className="zh-workbench-create-card" onClick={() => navigate('assistants')}><span><Plus size={22} /></span><strong>创建业务应用</strong><p>配置模型、关联知识库，<br />搭建属于团队的 AI 助手。</p><b>前往应用中心<ArrowRight size={13} /></b></button>}</div>
          {!applications.length && (query || role === 'user') && <div className="zh-workbench-empty"><Search size={28} /><strong>{query ? '没有匹配的应用' : '还没有可用应用'}</strong><p>{query ? '试试其他关键词，或选择其他应用场景。' : '请联系管理员创建应用并配置模型。'}</p></div>}
          <section className="zh-workbench-start"><div className="zh-workbench-section-title"><h2>从知识到答案</h2><span>连接你的工作流程</span></div><div className="zh-workbench-start-grid"><button onClick={() => navigate(role === 'user' ? 'chat' : 'knowledge')}><span className="zh-workbench-step-icon"><BookOpen size={19} /></span><div><strong>沉淀团队知识</strong><p>导入资料，构建可检索的知识库</p></div><ChevronRight size={15} /></button><button onClick={() => navigate('chat')}><span className="zh-workbench-step-icon purple"><MessageSquare size={19} /></span><div><strong>开启有据可查的对话</strong><p>提出问题，结合原始来源核对答案</p></div><ChevronRight size={15} /></button></div></section>
        </div>
        <aside className="zh-workbench-aside">
          <section id="workbench-favorites" className="zh-workbench-side-card"><h2><Star size={16} color="#fdb022" />我的收藏</h2>{favoriteApps.length ? favoriteApps.map(app => <button className="zh-workbench-side-row" key={app.id} onClick={() => openApp(app)}><span className="zh-workbench-small-icon"><Bot size={16} /></span><span>{app.name}</span><ChevronRight size={14} /></button>) : <p className="zh-workbench-side-empty">点击应用卡片右上角的星标，将常用应用放在这里。</p>}</section>
          <section className="zh-workbench-side-card"><h2><Clock3 size={16} />最近使用</h2>{recent.length ? recent.map(session => { const app = state.assistants.find(item => item.id === session.assistantId)!; return <button className="zh-workbench-side-row zh-workbench-recent" key={session.id} onClick={() => { setActiveSessionId(session.id); setActiveAssistantId(app.id); navigate('chat'); }}><span className="zh-workbench-small-icon"><MessageSquare size={15} /></span><span><strong>{session.title}</strong><small>{app.name} · {formatTime(session.messages.at(-1)?.createdAt || session.createdAt)}</small></span></button>; }) : <p className="zh-workbench-side-empty">开始一次对话后，最近使用的应用会显示在这里。</p>}</section>
          <section className="zh-workbench-side-card zh-workbench-stat-card"><h2><Layers3 size={16} />{role === 'user' ? '我的使用记录' : '工作空间沉淀'}</h2><div className="zh-workbench-stats">{stats.map(stat => <div key={stat.label} {...cardAction(()=>{if(role==="user"&&(stat.label.includes("应用")||stat.label.includes("收藏"))){document.getElementById(stat.label.includes("收藏")?"workbench-favorites":"workbench-apps")?.scrollIntoView({behavior:"smooth"});return;}navigate(stat.label.includes("应用")||stat.label.includes("收藏")?"assistants":stat.label.includes("知识")||stat.label.includes("文档")||stat.label.includes("分段")?"knowledge":role==="user"?"chat":"insights");},`查看${stat.label}明细`)}><span>{stat.label}</span><strong>{stat.value.toLocaleString()}<small>{stat.suffix}</small></strong></div>)}</div><p>{role === 'admin' ? '近期调用按当前加载日志统计' : role === 'user' ? '来自我的会话与本机收藏记录' : '来自知识空间与我的会话记录'}</p></section>
          {role !== 'user' && <button className="zh-workbench-need-card" onClick={() => navigate('assistants')}><Sparkles size={22} /><span><strong>没有合适的应用？</strong><small>从知识问答助手开始搭建</small></span><ArrowRight size={16} /></button>}
          <div className="zh-workbench-privacy"><FileText size={13} /><span>资料与会话保存在本机数据库</span></div>
        </aside>
      </div>
    </div>
  </div>;
}
