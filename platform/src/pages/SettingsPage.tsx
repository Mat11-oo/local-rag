import { Copy, KeyRound, Plus, Trash2, Users } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch, errorMessage } from '../api/client';
import { useAuth } from '../auth';
import { ConfirmModal, Empty, Field, Loading, Modal, Notice, Spinner, Tag, formatTime, useToast } from '../components/ui';
import type { Role } from '../types';
import { LocalEnvironment } from '../components/LocalEnvironment';

type Tab = 'members' | 'tokens' | 'local';
type Member = { id: string; email: string; display_name: string; is_active: boolean; role: Role; joined_at: string };
type ApiClientItem = { id: string; name: string; role: 'admin' | 'manager'; scopes: string[]; last_used_at: string | null };

const ROLE_LABEL: Record<Role, string> = { admin: '管理员', manager: '应用管理员', user: '业务使用者' };
const SCOPES: Array<[string, string]> = [
  ['apps:run', '运行应用'], ['apps:read', '读取应用'], ['apps:write', '修改应用'], ['apps:evaluate', '运行评测'],
  ['knowledge:read', '读取知识库'], ['knowledge:write', '写入知识库'], ['models:read', '读取模型'], ['tools:read', '读取工具'], ['tools:write', '修改工具'], ['logs:read', '读取日志'],
];

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('tab');
  const tab: Tab = selected === 'tokens' || selected === 'local' ? selected : 'members';
  return (
    <div className="page" style={{ maxWidth: 1080 }}>
      <div className="page-head"><div className="grow"><h1>设置</h1><p>管理业务空间成员和业务系统调用用的 API Token。</p></div></div>
      <div className="seg" style={{ marginBottom: 16 }}>
        <button className={tab === 'members' ? 'active' : ''} onClick={() => setParams({ tab: 'members' })}><Users size={14} />成员</button>
        <button className={tab === 'tokens' ? 'active' : ''} onClick={() => setParams({ tab: 'tokens' })}><KeyRound size={14} />API Token</button>
        <button className={tab === 'local' ? 'active' : ''} onClick={() => setParams({ tab: 'local' })}>本地环境</button>
      </div>
      {tab === 'members' ? <MembersView /> : tab === 'tokens' ? <TokensView /> : <LocalEnvironment />}
    </div>
  );
}

function MembersView() {
  const toast = useToast();
  const { me } = useAuth();
  const [items, setItems] = useState<Member[] | null>(null);
  const [error, setError] = useState('');
  const [inviting, setInviting] = useState(false);
  const [form, setForm] = useState({ email: '', display_name: '', password: '', role: 'user' as Role });
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<Member | null>(null);

  const load = useCallback(() => apiFetch<Member[]>('/auth/users').then((list) => { setItems(list); setError(''); }).catch((caught) => setError(errorMessage(caught))), []);
  useEffect(() => { void load(); }, [load]);

  const invite = async () => {
    setBusy(true);
    try {
      await apiFetch('/auth/users', { method: 'POST', body: JSON.stringify({ ...form, email: form.email.trim(), display_name: form.display_name.trim() }) });
      toast('成员已加入');
      setInviting(false);
      setForm({ email: '', display_name: '', password: '', role: 'user' });
      await load();
    } catch (caught) { toast(errorMessage(caught), 'error'); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}><span className="grow" /><button className="btn primary" onClick={() => setInviting(true)}><Plus size={15} />添加成员</button></div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {!items && !error ? <Loading /> : null}
      {items?.length ? (
        <table className="table">
          <thead><tr><th>成员</th><th>角色</th><th>加入时间</th><th /></tr></thead>
          <tbody>{items.map((member) => {
            const self = member.id === me?.user?.id;
            return (
              <tr key={member.id}>
                <td><strong>{member.display_name}</strong>{self ? <Tag tone="blue">我</Tag> : null}<div className="faint">{member.email}</div></td>
                <td><select className="select sm" style={{ width: 140 }} aria-label={`${member.display_name} 的角色`} value={member.role} disabled={self} onChange={async (event) => { try { await apiFetch(`/auth/users/${member.id}`, { method: 'PATCH', body: JSON.stringify({ role: event.target.value }) }); toast('角色已更新'); await load(); } catch (caught) { toast(errorMessage(caught), 'error'); } }}>{Object.entries(ROLE_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></td>
                <td className="faint">{formatTime(member.joined_at)}</td>
                <td>{self ? null : <button className="btn sm ghost icon" aria-label={`移除 ${member.display_name}`} onClick={() => setRemoving(member)}><Trash2 size={14} /></button>}</td>
              </tr>
            );
          })}</tbody>
        </table>
      ) : null}
      <Modal open={inviting} title="添加成员" onClose={() => setInviting(false)} footer={<><button className="btn" onClick={() => setInviting(false)}>取消</button><button className="btn primary" disabled={busy || !form.email.includes('@') || !form.display_name.trim() || form.password.length < 8} onClick={() => void invite()}>{busy ? <Spinner /> : null}添加</button></>}>
        <Field label="邮箱" required><input className="input" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></Field>
        <Field label="姓名" required><input className="input" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></Field>
        <Field label="初始密码" required hint="至少 8 位；已有账号的用户沿用原密码"><input className="input" type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></Field>
        <Field label="角色"><select className="select" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as Role })}>{Object.entries(ROLE_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      </Modal>
      <ConfirmModal open={!!removing} danger title="移出成员" confirmText="移出" body={<>「{removing?.display_name}」将无法再访问当前业务空间。</>} onClose={() => setRemoving(null)}
        onConfirm={async () => { if (!removing) return; try { await apiFetch(`/auth/users/${removing.id}`, { method: 'DELETE' }); toast('已移出'); await load(); } catch (caught) { toast(errorMessage(caught), 'error'); } }} />
    </>
  );
}

function TokensView() {
  const toast = useToast();
  const [items, setItems] = useState<ApiClientItem[] | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', role: 'manager' as 'admin' | 'manager', scopes: ['apps:run'] });
  const [created, setCreated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState<ApiClientItem | null>(null);

  const load = useCallback(() => apiFetch<ApiClientItem[]>('/auth/api-clients').then((list) => { setItems(list); setError(''); }).catch((caught) => setError(errorMessage(caught))), []);
  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    setBusy(true);
    try {
      const result = await apiFetch<{ token: string }>('/auth/api-clients', { method: 'POST', body: JSON.stringify({ ...form, name: form.name.trim() }) });
      setCreated(result.token);
      await load();
    } catch (caught) { toast(errorMessage(caught), 'error'); } finally { setBusy(false); }
  };
  const close = () => { setCreating(false); setCreated(null); setForm({ name: '', role: 'manager', scopes: ['apps:run'] }); };
  const copy = (text: string) => { void navigator.clipboard?.writeText(text); toast('已复制'); };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}><p className="faint grow">业务系统调用应用或推送知识库文件时使用。Token 只在创建时显示一次。</p><button className="btn primary" onClick={() => setCreating(true)}><Plus size={15} />创建 Token</button></div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {!items && !error ? <Loading /> : null}
      {items && !items.length ? <Empty icon={<KeyRound size={26} />} title="还没有 API Token" /> : null}
      {items?.length ? (
        <table className="table">
          <thead><tr><th>名称</th><th>角色</th><th>权限</th><th>最近使用</th><th /></tr></thead>
          <tbody>{items.map((item) => (
            <tr key={item.id}>
              <td><strong>{item.name}</strong></td>
              <td><Tag>{ROLE_LABEL[item.role]}</Tag></td>
              <td><div className="row wrap" style={{ gap: 4 }}>{item.scopes.map((scope) => <Tag key={scope}>{scope}</Tag>)}</div></td>
              <td className="faint">{item.last_used_at ? formatTime(item.last_used_at) : '从未使用'}</td>
              <td><button className="btn sm ghost" onClick={() => setRevoking(item)}><Trash2 size={13} />吊销</button></td>
            </tr>
          ))}</tbody>
        </table>
      ) : null}
      <Modal open={creating} title="创建 API Token" onClose={close}
        footer={created ? <button className="btn primary" onClick={close}>完成</button> : <><button className="btn" onClick={close}>取消</button><button className="btn primary" disabled={busy || !form.name.trim() || !form.scopes.length} onClick={() => void create()}>{busy ? <Spinner /> : null}创建</button></>}>
        {created ? <>
          <Notice tone="success" title="Token 已创建">请立即复制保存，关闭后无法再次查看。</Notice>
          <div className="row" style={{ marginTop: 12 }}><input className="input mono" readOnly value={created} /><button className="btn" onClick={() => copy(created)}><Copy size={14} />复制</button></div>
        </> : <>
          <Field label="名称" required><input className="input" value={form.name} placeholder="例如：客服系统" onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
          <Field label="角色"><select className="select" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as 'admin' | 'manager' })}><option value="manager">应用管理员</option><option value="admin">管理员</option></select></Field>
          <Field label="权限" required>
            <div className="grid c2" style={{ gap: 6 }}>
              {SCOPES.map(([scope, label]) => (
                <label key={scope} className="row" style={{ fontSize: 13 }}>
                  <input type="checkbox" checked={form.scopes.includes(scope)} onChange={(event) => setForm({ ...form, scopes: event.target.checked ? [...form.scopes, scope] : form.scopes.filter((item) => item !== scope) })} />
                  {label}<span className="faint mono">{scope}</span>
                </label>
              ))}
            </div>
          </Field>
        </>}
      </Modal>
      <ConfirmModal open={!!revoking} danger title="吊销 Token" confirmText="吊销" body={<>吊销后使用「{revoking?.name}」的业务系统会立即失去访问权限。</>} onClose={() => setRevoking(null)}
        onConfirm={async () => { if (!revoking) return; try { await apiFetch(`/auth/api-clients/${revoking.id}`, { method: 'DELETE' }); toast('已吊销'); await load(); } catch (caught) { toast(errorMessage(caught), 'error'); } }} />
    </>
  );
}
