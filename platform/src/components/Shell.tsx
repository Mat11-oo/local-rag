import { Activity, Blocks, ClipboardCheck, Database, LayoutGrid, LogOut, Wrench, Settings, Search, CircleHelp, type LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState, type PropsWithChildren } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { isManager, useAuth } from '../auth';
import { ThemeSelector } from '../theme';
import { Modal } from './ui';
import { WorkspaceSearch } from './WorkspaceSearch';
import type { Role } from '../types';

type NavItem = { to: string; label: string; icon: LucideIcon; roles: Role[] };
const ALL: Role[] = ['admin', 'manager', 'user'];
const STAFF: Role[] = ['admin', 'manager'];
export const NAV: NavItem[] = [
  { to: '/workbench', label: '工作台', icon: LayoutGrid, roles: ALL },
  { to: '/apps', label: '应用', icon: Blocks, roles: STAFF },
  { to: '/knowledge', label: '知识库', icon: Database, roles: STAFF },
  { to: '/tools', label: '工具', icon: Wrench, roles: ['admin'] },
  { to: '/observability', label: '看板', icon: Activity, roles: STAFF },
  { to: '/evaluation-sets', label: '评测集', icon: ClipboardCheck, roles: STAFF },
];
const ROLE_LABEL: Record<Role, string> = { admin: '管理员', manager: '应用管理员', user: '使用者' };
export function canVisit(role: Role, path: string) {
  if (path.startsWith('/chat/') || path.startsWith('/workbench')) return true;
  if (path.startsWith('/settings')) return role === 'admin';
  const item = NAV.find(nav => path.startsWith(nav.to));
  return item ? item.roles.includes(role) : isManager(role);
}
export function Shell({ children }: PropsWithChildren) {
  const { me, logout, setRole } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [menu, setMenu] = useState(false);
  const [search, setSearch] = useState(false);
  const [help, setHelp] = useState(false);
  const [query, setQuery] = useState('');
  const [more, setMore] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const role = me?.role ?? 'user';
  const local = me?.auth_type === 'local';
  const visible = NAV.filter(item => item.roles.includes(role));
  useEffect(() => { setMenu(false); setMore(false); setSearch(false); setQuery(''); }, [pathname]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setSearch(value => !value);
      }
    };
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  }, []);
  useEffect(() => {
    if (!menu) return;
    const close = (event: PointerEvent) => { if (!menuRef.current?.contains(event.target as Node)) setMenu(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [menu]);
  return <div className="shell">
    <nav className="nav" aria-label="主导航">
      <button className="nav-logo" title="Local RAG" aria-label="Local RAG工作台" onClick={() => navigate('/workbench')}>LR</button>
      <span className="nav-local"><i />本地</span>
      {visible.map(({to, label, icon: Icon}) => <NavLink key={to} to={to} data-mobile-hidden={!(['/workbench','/apps','/knowledge'].includes(to))} className={`nav-item ${pathname.startsWith(to) || (to === '/workbench' && pathname.startsWith('/chat/')) ? 'active' : ''}`}><Icon size={21} strokeWidth={1.7} aria-hidden="true"/><span>{label}</span></NavLink>)}
      <button className="nav-item mobile-more-button" onClick={() => setMore(true)} aria-label="更多功能"><Blocks size={20}/><span>更多</span></button>
      <div className="nav-spacer" />
      <button className="nav-item desktop-nav-extra" aria-label="搜索工作空间" title="搜索工作空间 · ⌘ K" onClick={() => setSearch(true)}><Search size={19}/><span>搜索</span></button>
      <button className="nav-item desktop-nav-extra" aria-label="使用帮助" onClick={() => setHelp(true)}><CircleHelp size={19}/><span>帮助</span></button>
      {role === 'admin' ? <NavLink to="/settings" className={`nav-item desktop-nav-extra ${pathname.startsWith('/settings') ? 'active' : ''}`}><Settings size={20}/><span>设置</span></NavLink> : null}
      <div className="nav-user" ref={menuRef}>
        <button className="nav-avatar" aria-label={local ? `切换角色：${ROLE_LABEL[role]}` : '账号菜单'} aria-expanded={menu} onClick={() => setMenu(!menu)}>{ROLE_LABEL[role].slice(0,1)}</button>
        {menu ? <div className="card nav-user-menu">
          <strong>{local ? '本地工作空间' : me?.user?.display_name}</strong>
          <ThemeSelector/>
          {local ? <><p>当前操作角色</p><select className="select" aria-label="切换操作角色" value={role} onChange={event => setRole(event.target.value as Role)}>{Object.entries(ROLE_LABEL).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><small>角色用于本地操作分工，当前无需账号登录。</small></> : <><div className="faint">{me?.user?.email}</div><button className="btn sm" onClick={async () => { await logout(); navigate('/login'); }}><LogOut size={14}/>退出登录</button></>}
        </div> : null}
      </div>
    </nav>
    <main className="main">{children}</main>
    <Modal open={more} title="更多功能" onClose={() => setMore(false)}><div className="local-search-results">{visible.map(({to,label,icon:Icon}) => <NavLink key={to} to={to} onClick={()=>setMore(false)}><Icon size={18}/>{label}</NavLink>)}{role === 'admin' ? <NavLink to="/settings">设置</NavLink> : null}<button className="btn" onClick={() => {setMore(false);setSearch(true);}}>搜索工作空间</button><button className="btn" onClick={() => {setMore(false);setHelp(true);}}>使用帮助</button></div></Modal>
    <Modal open={search} title="搜索工作空间" onClose={() => setSearch(false)}>
      <input autoFocus className="input" aria-label="搜索功能" onKeyDown={event=>{if(event.key==='ArrowDown'){event.preventDefault();document.querySelector<HTMLAnchorElement>('[data-search-results] a')?.focus();}}} placeholder="搜索应用、知识库、文件或功能" value={query} onChange={event => setQuery(event.target.value)}/>
      <WorkspaceSearch query={query} navigation={visible.map(item => ({id:item.to,path:item.to,name:item.label,kind:'navigation'}))} onSelected={() => setSearch(false)}/>
    </Modal>
    <Modal open={help} title="开始使用 Local RAG" onClose={() => setHelp(false)}>
      <div className="col"><p>1. 在“工具 → 模型”接入服务商和模型。</p><p>2. 创建知识库，导入文件并检查真实分块。</p><p>3. 配置应用，在草稿中调试并运行评测。</p><p>4. 发布后从工作台使用，在看板查看 Trace 和反馈。</p></div>
    </Modal>
  </div>;
}
