import { lazy, Suspense, useEffect, useState } from 'react';
import { Button, Input, Modal, Popover, Select, Tooltip } from 'antd';
import { ArrowRight, BookOpen, ClipboardCheck, Bot, ChartNoAxesCombined, CircleHelp, Database, FileClock, Grid2X2, LayoutDashboard, RefreshCw, Search, Settings, Settings2, ShieldCheck, Sparkles, Wrench, X } from 'lucide-react';
import type { Page } from './types';
import { useWorkspace } from './store';
import { canVisit } from './routing';
import './workspace.css';
import { ThemeSelector } from './theme';

const Evaluation = lazy(() => import('./pages/Evaluation'));
const Knowledge = lazy(() => import('./pages/Knowledge'));
const ImportWizard = lazy(() => import('./ImportWizard').then(module => ({ default: module.ImportWizard })));
const Chat = lazy(() => import('./pages/Chat'));
const Overview = lazy(() => import('./pages/Overview'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Assistants = lazy(() => import('./pages/Assistants'));
const Insights = lazy(() => import('./pages/WorkspacePanels').then(module => ({ default: module.Insights })));
const Tools = lazy(() => import('./pages/WorkspacePanels').then(module => ({ default: module.Tools })));
const SettingsPanel = lazy(() => import('./pages/WorkspacePanels').then(module => ({ default: module.SettingsPanel })));
const navigation: { page: Page; title: string; icon: typeof BookOpen }[] = [
  { page: 'overview', title: '工作台', icon: LayoutDashboard },
  { page: 'assistants', title: '应用', icon: Grid2X2 },
  { page: 'knowledge', title: '知识库', icon: Database },
  { page: 'tools', title: '工具', icon: Wrench },
  { page: 'insights', title: '看板', icon: ChartNoAxesCombined },
  { page: 'evaluation', title: '评测集', icon: ClipboardCheck },
];
const labels: Partial<Record<Page, string>> = { tasks: '导入任务', models: '模型服务', logs: '运行日志', chat: '对话', settings: '设置' };

export default function App() {
  const { state, page, navigate, role, setRole, setActiveKbId, setActiveAssistantId, setActiveSessionId, importOpen, setImportOpen, refresh, backendReady, syncing, connectionError } = useWorkspace();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setSearchOpen(value => !value); } };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  }, []);
  const visibleNav = navigation.filter(item => canVisit(role, item.page));
  const searchNav = [...visibleNav, ...[{ page: 'tasks' as Page, title: '导入任务', icon: FileClock }, { page: 'models' as Page, title: '模型服务', icon: Settings2 }, { page: 'logs' as Page, title: '运行日志', icon: ChartNoAxesCombined }].filter(item => canVisit(role, item.page))];
  const activeNav = page === 'tasks' ? 'knowledge' : page === 'models' ? 'tools' : page === 'logs' ? 'insights' : page === 'chat' ? 'overview' : page;
  const jump = (next: Page) => { navigate(next); setSearchOpen(false); setQuery(''); };
  const normalized = query.trim().toLocaleLowerCase();
  const matchedNav = searchNav.filter(item => !normalized || item.title.toLocaleLowerCase().includes(normalized));
  const matchedKbs = role !== 'user' && normalized ? state.knowledgeBases.filter(kb => `${kb.name} ${kb.description}`.toLocaleLowerCase().includes(normalized)) : [];
  const matchedApps = normalized ? state.assistants.filter(app => `${app.name} ${app.description}`.toLocaleLowerCase().includes(normalized)) : [];
  return <div className="zh-shell">
    <aside className="zh-rail" aria-label="Local RAG主导航">
      <button className="zh-logo" aria-label="Local RAG工作台" onClick={() => navigate('overview')} title="Local RAG">LR</button>
      <Tooltip title={connectionError || (syncing ? '正在保存到本地数据库' : backendReady ? '本地服务已连接，数据保存在本机' : '正在连接本地服务')} placement="right"><span className={`zh-local ${backendReady ? 'connected' : ''}`}><i />{syncing ? '保存中' : '本地'}</span></Tooltip>
      <nav>{visibleNav.map(item => { const Icon = item.icon; return <button key={item.page} className={`zh-rail-item ${activeNav === item.page ? 'active' : ''}`} aria-label={item.title} aria-current={activeNav === item.page ? 'page' : undefined} onClick={() => { navigate(item.page); if (item.page === 'knowledge') setActiveKbId(null); }}><Icon size={21} strokeWidth={1.7} /><span>{item.title}</span></button>; })}</nav>
      <div className="zh-rail-spacer" />
      <Tooltip title="搜索工作空间 · ⌘ K" placement="right"><button className="zh-rail-item" aria-label="搜索工作空间" onClick={() => setSearchOpen(true)}><Search size={19} /><span>搜索</span></button></Tooltip>
      <button className="zh-rail-item" aria-label="使用帮助" onClick={() => setHelpOpen(true)}><CircleHelp size={19} /><span>帮助</span></button>
      {role === 'admin' && <button className={`zh-rail-item ${page === 'settings' ? 'active' : ''}`} aria-label="设置" aria-current={page === 'settings' ? 'page' : undefined} onClick={() => navigate('settings')}><Settings size={20} strokeWidth={1.7} /><span>设置</span></button>}
      <Popover trigger="click" placement="rightBottom" content={<div className="zh-role-popover"><strong>本地工作空间</strong><ThemeSelector/><p>当前操作角色</p><Select aria-label="切换操作角色" value={role} onChange={setRole} options={[{ value: 'admin', label: '管理员' }, { value: 'knowledge', label: '知识管理员' }, { value: 'user', label: '使用者' }]} /><small>角色用于操作分工，尚未接入账号登录。</small><Button type="text" icon={<RefreshCw size={13} />} onClick={() => void refresh()}>刷新数据</Button></div>}><button className="zh-avatar" aria-label={`切换角色：${role === 'admin' ? '管理员' : role === 'knowledge' ? '知识管理员' : '使用者'}`}>{role === 'admin' ? '管' : role === 'knowledge' ? '知' : '用'}</button></Popover>
    </aside>
    <div className={`zh-canvas zh-canvas-${page}`}>
      <main className={`content-area ${page === 'chat' ? 'chat-content-area' : ''} ${page === 'overview' ? 'zh-workbench-area' : ''}`} aria-label={navigation.find(item => item.page === page)?.title || labels[page] || '工作空间'}>
        {!backendReady ? <div className="zh-connection-state"><Database size={32} /><h1>{connectionError ? '暂时无法连接本地服务' : '正在打开Local RAG'}</h1><p>{connectionError || '正在读取工作空间和已保存的资料…'}</p><Button type="primary" icon={<RefreshCw size={15} />} onClick={() => void refresh()}>重新连接</Button></div> : <Suspense fallback={<div className="page-loading"><span />正在打开工作空间…</div>}>
          {page === 'overview' ? <Overview /> : page === 'assistants' ? <Assistants /> : page === 'knowledge' ? <Knowledge /> : page === 'tasks' ? <><button className="zh-back-link" onClick={() => navigate('knowledge')}>← 返回知识库</button><Tasks /></> : page === 'chat' ? <Chat /> : page === 'tools' || page === 'models' ? <Tools key={page} initialTab={page === 'models' ? 'models' : 'tools'} /> : page === 'evaluation' ? <Evaluation /> : page === 'settings' ? <SettingsPanel /> : <Insights key={page} initialTab={page === 'logs' ? 'logs' : 'overview'} />}
        </Suspense>}
      </main>
    </div>
    {role !== 'user' && importOpen && <Suspense fallback={null}><ImportWizard /></Suspense>}
    <Modal open={searchOpen} onCancel={() => setSearchOpen(false)} footer={null} closable={false} width={600} className="search-modal"><div className="search-modal-input"><Search size={20} /><Input autoFocus aria-label="搜索工作空间内容" placeholder="搜索应用、知识库或功能…" variant="borderless" value={query} onChange={event => setQuery(event.target.value)} /><button className="icon-button" onClick={() => setSearchOpen(false)} aria-label="关闭搜索"><X size={16} /></button></div><div className="search-results"><span className="eyebrow">{normalized ? '搜索结果' : '快速前往'}</span>{matchedNav.map(item => { const Icon = item.icon; return <button key={item.page} onClick={() => jump(item.page)}><Icon size={17} /><span>{item.title}</span><ArrowRight size={15} /></button>; })}{matchedKbs.map(kb => <button key={kb.id} onClick={() => { jump('knowledge'); setActiveKbId(kb.id); }}><Database size={17} /><span>{kb.name}<small>知识库</small></span><ArrowRight size={15} /></button>)}{matchedApps.map(app => <button key={app.id} onClick={() => { setActiveAssistantId(app.id); setActiveSessionId(null); jump('chat'); }}><Bot size={17} /><span>{app.name}<small>应用</small></span><ArrowRight size={15} /></button>)}{!matchedNav.length && !matchedKbs.length && !matchedApps.length && <div className="search-empty">没有找到匹配内容，请调整关键词。</div>}</div><div className="search-modal-footer">⌘ / Ctrl + K 打开搜索<span>Esc 关闭</span></div></Modal>
    <Modal open={helpOpen} onCancel={() => setHelpOpen(false)} title={<span className="modal-title-icon"><Sparkles size={19} />开始使用Local RAG</span>} width={620} footer={<Button type="primary" onClick={() => { setHelpOpen(false); navigate(role === 'user' ? 'overview' : 'knowledge'); }}>打开{role === 'user' ? '工作台' : '知识库'}<ArrowRight size={14} /></Button>}><p className="muted">从团队资料到有据可查的答案，在一个工作空间内完成。</p><div className="guide-steps">{[{ icon: Settings2, title: '连接模型', text: '在工具 → 模型中配置服务商连接及实际模型。' }, { icon: Database, title: '整理知识', text: '创建知识库，上传文件、检查分段，再发布检索索引。' }, { icon: Grid2X2, title: '配置应用', text: '创建简易应用，关联知识库、模型与提示词。' }, { icon: ChartNoAxesCombined, title: '使用与观测', text: '从工作台发起对话，在看板查看真实调用、反馈与运行日志。' }].map((step, index) => { const Icon = step.icon; return <div key={step.title}><span><Icon size={19} /></span><section><b>{index + 1}. {step.title}</b><p>{step.text}</p></section></div>; })}</div><div className="subtle-note"><ShieldCheck size={16} /><span>文件和配置由本地后端保存。云端处理范围由“工具 → 模型”中的开关控制；工具与 Agent 调用受应用授权和运行限制控制。</span></div></Modal>
  </div>;
}
