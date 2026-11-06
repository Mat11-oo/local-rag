import { ServiceProblem } from '../components/ServiceProblem';
import { AlertTriangle, ArrowLeft, CheckCircle2, Cloud, CloudOff, Play, Rocket } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { recordExperience, failureKind } from '../lib/experience';
import { useAuth } from '../auth';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { apiFetch, ApiError, errorMessage, type ApiEvaluationSet, type ApiKnowledgeBase, type ApiModelOption, type ApiToolConfig } from '../api/client';
import { evalApi } from '../api/evaluation';
import { fdeApi, type AppManifest, type AppTemplate, type FDEApp, type ValidationIssue } from '../api/fde';
import { ChatPanel } from '../components/ChatPanel';
import { AppTile, Field, Loading, Modal, Notice, Spinner, Tag, useToast } from '../components/ui';
import { AppConfigForm } from '../editors/AppConfigForm';
import { appStatus, TYPE_META } from '../lib/apps';
import { EvalTab, LogsTab, PublishTab, VersionsTab } from './AppTabs';

const TABS = [
  { key: 'edit', name: '编排' },
  { key: 'publish', name: '发布渠道' },
  { key: 'eval', name: '评测' },
  { key: 'logs', name: '运行记录' },
  { key: 'versions', name: '版本' },
] as const;
type TabKey = (typeof TABS)[number]['key'];

type SaveState = 'saved' | 'dirty' | 'saving' | 'error';

export function AppEditorPage() {
  const { appId = '' } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = (params.get('tab') as TabKey) || 'edit';
  const [app, setApp] = useState<FDEApp | null>(null);
  const [manifest, setManifest] = useState<AppManifest | null>(null);
  const [resources, setResources] = useState<{ templates: AppTemplate[]; models: ApiModelOption[]; knowledge: ApiKnowledgeBase[]; tools: ApiToolConfig[] }>({ templates: [], models: [], knowledge: [], tools: [] });
  const [save, setSave] = useState<SaveState>('saved');
  const [saveError, setSaveError] = useState('');
  const [error, setError] = useState('');
  const [errorStatus,setErrorStatus]=useState(0);
  const [publishing, setPublishing] = useState(false);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const {me} = useAuth();
  const draftKey = `local-rag.draft.${me?.workspace_id}.${me?.user?.id ?? 'local'}.${appId}`;
  const [recovery,setRecovery] = useState<AppManifest | null>(null);
  const [localError,setLocalError] = useState('');
  const retainDraft = useCallback((value:AppManifest) => {
    try {localStorage.setItem(draftKey,JSON.stringify({schema:1,manifest:value,at:new Date().toISOString()}));setLocalError('');}
    catch {setLocalError('本机草稿备份失败，请勿关闭页面。可复制或导出配置后重试。');}
  },[draftKey]);
  const latest = useRef<AppManifest | null>(null);
  const savedManifest = useRef<AppManifest | null>(null);

  const reload = useCallback(async () => {
    const loaded = await fdeApi.get(appId);
    setApp(loaded);
    return loaded;
  }, [appId]);

  useEffect(() => {
    Promise.all([
      fdeApi.get(appId), fdeApi.templates(), apiFetch<ApiModelOption[]>('/model-options'),
      apiFetch<ApiKnowledgeBase[]>('/knowledge-bases'), apiFetch<ApiToolConfig[]>('/tools').catch(() => [] as ApiToolConfig[]),
    ]).then(([loaded, templates, models, knowledge, tools]) => {
      setApp(loaded);
      const withDefaults = { ...loaded.manifest, experience: loaded.manifest.experience ?? { opening: '', suggestions: [] } };
      setManifest(withDefaults);
      latest.current = withDefaults;
      savedManifest.current = withDefaults;
      try {
        const stored = JSON.parse(localStorage.getItem(draftKey) ?? 'null');
        if(stored?.schema === 1 && stored.manifest?.name && stored.manifest?.schema_version && JSON.stringify(stored.manifest) !== JSON.stringify(withDefaults)) setRecovery(stored.manifest);
      } catch {setLocalError('无法读取本机草稿备份。服务器草稿仍可使用。');}
      setResources({ templates, models, knowledge, tools });
    }).catch((caught) => {setError(errorMessage(caught));setErrorStatus(caught instanceof ApiError?caught.status:0);});
  }, [appId, draftKey]);

  const persist = useCallback(() => {
    const operation = saveQueue.current.catch(() => undefined).then(async () => {
      const value = latest.current;
      if(!value)return;
      const wasError=saveRef.current === 'error'||Boolean(saveError);retainDraft(value);setSave('saving');
      try {
        const saved = await fdeApi.save(appId,value);setApp(saved);savedManifest.current=value;
        if(latest.current === value){
          if(wasError)recordExperience('save_recovered');
          setSave('saved');
          try {const backup=JSON.parse(localStorage.getItem(draftKey)??'null');if(JSON.stringify(backup?.manifest)===JSON.stringify(value))localStorage.removeItem(draftKey);} catch { /* Retain unreadable backups for recovery. */ }
        } else setSave('dirty');
        setSaveError('');
      }catch(caught){recordExperience('save_failed',undefined,{failure_kind:failureKind(caught)});setSave('error');setSaveError(errorMessage(caught));throw caught;}
    });
    saveQueue.current = operation;return operation;
  },[appId,draftKey,retainDraft,saveError]);

  // 修改后 1 秒自动保存草稿；草稿不影响线上版本
  useEffect(() => {
    if (save !== 'dirty') return undefined;
    const timer = window.setTimeout(() => { void persist().catch(() => undefined); }, 1000);
    return () => window.clearTimeout(timer);
  }, [save, manifest, persist]);

  // 离开页面时补存尚未保存的修改，并在关闭标签页前提醒
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (saveRef.current !== 'saved') event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
      if (saveRef.current !== 'saved' && latest.current) retainDraft(latest.current);
    };
  }, [appId, retainDraft]);

  const ensureSaved = useCallback(async () => {
    await saveQueue.current.catch(() => undefined);
    if (latest.current !== savedManifest.current) await persist();
  }, [persist]);

  const patch = (value: Partial<AppManifest>) => {
    if(!latest.current)return;
    const next = {...latest.current,...value};latest.current=next;
    retainDraft(next);setManifest(next);setSave('dirty');
  };

  const exportDraft = () => {
    if(!latest.current)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(latest.current,null,2)],{type:'application/json'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download='Local-RAG-未同步草稿.json';anchor.click();
    window.setTimeout(()=>URL.revokeObjectURL(url),1000);
  };

  if (error) return <ServiceProblem message={error} status={errorStatus} onRetry={()=>window.location.reload()}/>;
  if (!app || !manifest) return <Loading />;
  const status = appStatus(app);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="topbar" style={{ flexWrap: 'wrap', height: 'auto', minHeight: 56 }}>
        <button className="btn ghost sm icon" aria-label="返回应用列表" onClick={() => navigate('/apps')}><ArrowLeft size={16} /></button>
        <AppTile templateKey={manifest.template_key} type={manifest.type} size="sm" />
        <div className="title row" style={{ gap: 6 }}>{manifest.name || '未命名应用'}<Tag tone={TYPE_META[manifest.type].tone}>{TYPE_META[manifest.type].name}</Tag></div>
        <div className="tabs" style={{ marginLeft: 12 }}>
          {TABS.map((item) => <button key={item.key} className={`tab ${tab === item.key ? 'active' : ''}`} onClick={() => setParams(item.key === 'edit' ? {} : { tab: item.key })}>{item.name}</button>)}
        </div>
        <span className="grow" />
        <span className="faint row" style={{ gap: 4 }} title={saveError}>
          {save === 'saving' ? <><Spinner size={13} />保存中</> : save === 'dirty' ? <><Cloud size={13} />有未保存修改</> : save === 'error' ? <><CloudOff size={13} color="#f04438" /><span style={{ color: '#b42318' }}>保存失败</span></> : <><Cloud size={13} />草稿已保存</>}
        </span>
        <Tag tone={status.tone}>{status.label}</Tag>
        <button className="btn" disabled={!app.is_enabled || !app.published_version_id} onClick={() => navigate(`/chat/${app.id}`)}><Play size={14} />使用线上版</button>
        <button className="btn primary" onClick={async () => { try { await ensureSaved(); setPublishing(true); } catch { toast('请先修正草稿保存错误', 'error'); } }}><Rocket size={14} />发布</button>
      </div>
      {recovery ? <Notice tone="warn" title="发现本机未同步草稿" action={<><button className="btn" onClick={()=>{setManifest(recovery);latest.current=recovery;setSave('dirty');setRecovery(null);}}>恢复草稿</button><button className="btn" onClick={()=>{localStorage.removeItem(draftKey);setRecovery(null);}}>使用服务器版本</button></>}>本机备份可能比服务器新。恢复后请核对内容；不会自动替换已发布版本。</Notice> : null}
      {localError ? <Notice tone="error">{localError}</Notice> : null}
      {save !== 'saved' ? <p className="draft-context" role="status">当前修改尚未同步。离开后可从本机备份恢复；发布和调试需先保存成功。</p> : null}
      {save === 'error' ? <div style={{ padding: '8px 16px' }}><Notice tone="error" title={localError ? "草稿保存失败，本机备份也未完成" : "草稿保存失败，本机备份已保留"} action={<><button className="btn" onClick={()=>void persist().catch(()=>undefined)}>重试保存</button><button className="btn" onClick={exportDraft}>导出当前草稿</button></>}>{saveError}</Notice></div> : null}

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: tab === 'edit' ? 'hidden' : 'auto' }}>
        {/* 编排区常驻挂载：切换到其他 Tab 再回来，调试对话不会丢失 */}
        <div style={{ flex: 1, display: tab === 'edit' ? 'flex' : 'none', minHeight: 0, flexWrap: 'wrap' }}>
          <div style={{ width: 560, maxWidth: '100%', flex: 'none', overflow: 'auto', padding: '4px 24px 24px', borderRight: '1px solid var(--border)', maxHeight: '100%' }}>
            <AppConfigForm manifest={manifest} patch={patch} {...resources} />
          </div>
          <div className="grow" style={{ display: 'flex', flexDirection: 'column', minWidth: 320, background: 'var(--bg-soft)', minHeight: 0, height: '100%' }}>
            <ChatPanel key={manifest.type} appId={app.id} manifest={manifest} mode="debug" beforeSend={ensureSaved}
              title={<><strong>调试预览</strong><Tag tone="orange">草稿</Tag><span className="faint">运行记录进入看板 · 渠道「调试」</span></>} />
          </div>
          </div>
        {tab === 'publish' ? <PublishTab app={app} onChanged={() => void reload()} /> : null}
        {tab === 'eval' ? <EvalTab app={app} /> : null}
        {tab === 'logs' ? <LogsTab app={app} /> : null}
        {tab === 'versions' ? <VersionsTab app={app} onChanged={() => void reload()} /> : null}
      </div>

      <PublishModal open={publishing} app={app} onClose={() => setPublishing(false)} onPublished={async () => { setPublishing(false); await reload(); }} />
    </div>
  );
}

function PublishModal({ open, app, onClose, onPublished }: { open: boolean; app: FDEApp; onClose: () => void; onPublished: () => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null);
  const [gates, setGates] = useState<ApiEvaluationSet[]>([]);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setIssues(null);
    setNotes('');
    Promise.all([fdeApi.validate(app.id), evalApi.list(app.id)])
      .then(([validation, sets]) => { setIssues(validation.issues); setGates(sets.filter((item) => item.is_release_gate)); })
      .catch((caught) => toast(errorMessage(caught), 'error'));
  }, [open, app.id, toast]);

  const errors = issues?.filter((item) => item.severity === 'error') ?? [];
  const warnings = issues?.filter((item) => item.severity === 'warning') ?? [];
  const gatePassed = (set: ApiEvaluationSet) => (set.quality_count ?? 0) > 0 && !!set.latest_run && !set.latest_run.failed_count && set.latest_run.passed_count >= set.ready_count && set.latest_run.status === 'success' && set.latest_run.matches_draft === true && set.latest_run.matches_criteria === true;
  const gateBlocked = gates.some((set) => !gatePassed(set));
  const nextVersion = (app.versions[0]?.version ?? 0) + 1;

  const publish = async () => {
    setBusy(true);
    try {
      const released = await fdeApi.release(app.id, notes.trim());
      toast(`已发布 v${released.published_version?.version ?? ''}，工作台与各渠道即时生效`);
      onPublished();
    } catch (caught) {
      toast(errorMessage(caught), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title={`发布 v${nextVersion}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>取消</button><button className="btn primary" disabled={busy || !issues || errors.length > 0 || gateBlocked || !notes.trim()} onClick={() => void publish()}>{busy ? <Spinner /> : <Rocket size={14} />}创建版本并发布</button></>}>
      {!issues ? <Loading text="正在校验" /> : <>
        <div className="section-title" style={{ marginTop: 0 }}>1. 配置校验</div>
        {errors.length ? <Notice tone="error" title={`${errors.length} 个问题必须修复`}><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{errors.map((item) => <li key={item.path + item.code}>{item.message}</li>)}</ul></Notice> : <Notice tone="success">校验通过</Notice>}
        {warnings.length ? <div style={{ marginTop: 8 }}><Notice tone="warn" title="建议处理"><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{warnings.map((item) => <li key={item.path + item.code}>{item.message}</li>)}</ul></Notice></div> : null}

        <div className="section-title">2. 质量门禁</div><p className="faint">执行成功不代表答案正确。门禁至少需要一条带明确内容判定的 Case，并基于当前草稿重新运行。</p>
        {!gates.length ? <Notice tone="info" title="未设置发布门禁" action={<button className="btn sm" onClick={() => { onClose(); navigate(`/apps/${app.id}?tab=eval`); }}>去设置</button>}>建议把一个评测集设为门禁，发布前自动要求全部通过。</Notice> : gates.map((set) => {
          const run = set.latest_run;
          const passed = gatePassed(set);
          const stale = run && (run.matches_draft === false || run.matches_criteria === false);
          return (
            <div key={set.id} className="row" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', marginBottom: 6 }}>
              {passed ? <CheckCircle2 size={16} color="#12b76a" /> : <AlertTriangle size={16} color="#f79009" />}
              <span className="grow">{set.name}{!(set.quality_count ?? 0) ? <strong className="quality-warning"> 尚未验证回答质量</strong> : null}<span className="faint"> · {!run ? '尚未运行' : stale ? '草稿或评测标准已修改，需重新运行' : `最近 ${run.passed_count}/${set.ready_count} 通过${set.needs_standard_count ? `（${set.needs_standard_count} 条待补标准未计入）` : ''}`}</span></span>
              {!passed ? <button className="btn sm" onClick={() => navigate(`/evaluation-sets?set=${set.id}`)}>去运行</button> : null}
            </div>
          );
        })}

        <div className="section-title">3. 版本说明</div>
        <Field label="本次改了什么" required><textarea className="textarea" style={{ minHeight: 70 }} value={notes} placeholder="例如：新增订单查询工具；竞品比价转人工" onChange={(event) => setNotes(event.target.value)} /></Field>
        <p className="faint">发布会把当前草稿固化为不可变版本 v{nextVersion}，可随时回滚；草稿与最新版本相同时直接发布该版本。</p>
      </>}
    </Modal>
  );
}
