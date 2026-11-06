import { cardAction } from '../cardAction';
import { useRef, useState } from 'react';
import { Alert, App, Button, Dropdown, Empty, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Tooltip } from 'antd';
import type { InputRef } from 'antd';
import { ArrowDownToLine, ArrowUpRight, Check, CircleAlert, Cpu, Database, Ellipsis, Eye, FileScan, KeyRound, Layers, Plus, Radio, Settings2, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import type { ModelConfig, ModelKind, Provider, ProviderConfig, WorkspaceState } from '../types';
import { uid, useWorkspace } from '../store';
import { api } from '../api';
import './model-logs.css';

const providers: Provider[] = ['通义千问', 'OpenRouter', 'AIHubMix'];
const kinds: ModelKind[] = ['LLM', 'Embedding', 'Rerank', 'OCR', 'Vision'];
const descriptions: Record<ModelKind, string> = { LLM: '生成有依据的回答', Embedding: '将知识转换为检索向量', Rerank: '对召回结果重新排序', OCR: '提取扫描件中的文字与表格', Vision: '理解照片、图表与示意图' };
const kindIcons = { LLM: Sparkles, Embedding: Database, Rerank: Layers, OCR: FileScan, Vision: Eye };
const baseUrls: Record<Provider, string> = { '通义千问': 'https://dashscope.aliyuncs.com/compatible-mode/v1', OpenRouter: 'https://openrouter.ai/api/v1', AIHubMix: 'https://aihubmix.com/v1' };
type ModelForm = Pick<ModelConfig, 'provider' | 'name' | 'modelId' | 'type' | 'dimensions'> & { providerConfigId: string };
type ProviderForm = Pick<ProviderConfig, 'provider' | 'name' | 'baseUrl'>;
interface CatalogModel { id: string; name: string; types: ModelKind[]; dimensions?: number; }
const isJinaNano = (modelId: string) => modelId.trim().toLowerCase().split('/').at(-1) === 'jina-embeddings-v5-text-nano';

export default function Models() {
  const { state, updateState, role, refresh, flush, navigate, setActiveAssistantId, setActiveSessionId } = useWorkspace();
  const { message, modal } = App.useApp();
  const connections = state.providerConfigs ?? [];
  const [provider, setProvider] = useState<Provider>('通义千问');
  const [kindFilter, setKindFilter] = useState<ModelKind | 'all'>('all');
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [providerOpen, setProviderOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ProviderConfig | null>(null);
  const [providerBusy, setProviderBusy] = useState(false);
  const [testing, setTesting] = useState<ModelConfig | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [fetchingCatalog, setFetchingCatalog] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<{ connection: ProviderConfig; models: CatalogModel[]; message?: string } | null>(null);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [binding, setBinding] = useState<ModelConfig | null>(null);
  const [bindingAssistantId, setBindingAssistantId] = useState<string>();
  const [bindingBusy, setBindingBusy] = useState(false);
  const secretInput = useRef<InputRef>(null);
  const [form] = Form.useForm<ModelForm>();
  const [providerForm] = Form.useForm<ProviderForm>();
  const watchedKind = Form.useWatch('type', { form, preserve: true });
  const watchedModelId = Form.useWatch('modelId', { form, preserve: true }) ?? '';
  const watchedProvider = Form.useWatch('provider', { form, preserve: true }) ?? provider;
  const watchedConnection = Form.useWatch('providerConfigId', { form, preserve: true });
  const selectedConnection = connections.find(item => item.id === watchedConnection);
  const availableConnections = connections.filter(item => item.provider === watchedProvider);
  const visibleConnections = connections.filter(item => item.provider === provider);
  const visibleModels = state.models.filter(model => model.provider === provider && (kindFilter === 'all' || model.type === kindFilter));

  if (role !== 'admin') return <Empty description="模型配置仅向管理员开放" />;

  const references = (model: ModelConfig) => [
    ...state.knowledgeBases.filter(kb => kb.embeddingModelId === model.id).map(kb => `知识库「${kb.name}」`),
    ...state.documents.filter(doc => doc.embeddingConfig?.id === model.id).map(doc => `已发布索引「${doc.name}」`),
    ...state.assistants.filter(assistant => assistant.modelId === model.id).map(assistant => `助手「${assistant.name}」`),
  ];
  const embeddingLocked = (model: ModelConfig) => model.type === 'Embedding' && (state.knowledgeBases.some(kb => kb.embeddingModelId === model.id) || state.documents.some(doc => doc.embeddingConfig?.id === model.id));
  const canBind = (model: ModelConfig) => model.type === 'LLM' && !!model.modelId.trim() && !isJinaNano(model.modelId) && !!model.hasKey && !connections.find(item => item.id === model.providerConfigId)?.credentialError;
  const preferredConnection = (vendor: Provider) => connections.find(item => item.provider === vendor && item.hasKey && !item.credentialError) ?? connections.find(item => item.provider === vendor);
  const openEditor = (model?: ModelConfig, connection?: ProviderConfig, catalogModel?: CatalogModel) => {
    const vendor = model?.provider ?? connection?.provider ?? provider;
    setEditing(model ?? null);
    form.resetFields();
    form.setFieldsValue(model ? { ...model, providerConfigId: model.providerConfigId ?? preferredConnection(vendor)?.id, dimensions: model.dimensions ?? 1024 } : {
      provider: vendor, providerConfigId: connection?.id ?? preferredConnection(vendor)?.id,
      type: catalogModel && isJinaNano(catalogModel.id) ? 'Embedding' : catalogModel ? catalogModel.types?.[0] : 'LLM', dimensions: catalogModel && isJinaNano(catalogModel.id) ? 768 : catalogModel?.dimensions ?? 1024,
      name: catalogModel?.name ?? '', modelId: catalogModel?.id ?? '',
    });
    setEditOpen(true);
  };
  const openProviderEditor = (connection?: ProviderConfig) => {
    setEditingProvider(connection ?? null);
    providerForm.resetFields();
    providerForm.setFieldsValue(connection ?? { provider, name: `${provider} · ${visibleConnections.length ? '新连接' : '默认连接'}`, baseUrl: baseUrls[provider] });
    setProviderOpen(true);
  };
  const saveProvider = async () => {
    try {
      const values = await providerForm.validateFields();
      const supplied = secretInput.current?.input?.value ?? '';
      const secret = supplied.trim().replace(/^Bearer\s+/i, '');
      if (supplied.trim() && (!secret || /^Bearer$/i.test(secret) || !/^[\x21-\x7E]+$/.test(secret))) { message.error('API Key 只能包含可见英文字符，不能含中文、空格或换行。请到服务商控制台复制实际密钥。'); return; }
      if ((!editingProvider?.hasKey || editingProvider?.credentialError) && !secret) { message.warning('请到服务商控制台重新复制实际 API Key，替换当前无效密钥'); return; }
      setProviderBusy(true);
      await flush();
      await api(`/api/providers/${editingProvider?.id ?? uid()}`, { method: 'PUT', body: JSON.stringify({ ...values, apiKey: secret }) });
      await refresh(); setProviderOpen(false); setProvider(values.provider);
      message.success('服务商连接已保存，关联模型将共用此密钥');
    } catch (error) { if (!(error as { errorFields?: unknown }).errorFields) message.error((error as Error).message); }
    finally { setProviderBusy(false); }
  };
  const deleteProvider = (connection: ProviderConfig) => {
    const usedBy = state.models.filter(model => model.providerConfigId === connection.id);
    if (usedBy.length) { modal.info({ title: '该连接正在使用中', content: `已有 ${usedBy.length} 个模型使用此连接。请先迁移或删除这些模型，再删除连接。` }); return; }
    modal.confirm({ title: `删除连接「${connection.name}」？`, content: '将删除此连接及加密保存的密钥。', okText: '删除连接', cancelText: '取消', okButtonProps: { danger: true }, onOk: async () => {
      try { await flush(); await api(`/api/providers/${connection.id}`, { method: 'DELETE' }); await refresh(); message.success('连接已删除'); }
      catch (error) { message.error((error as Error).message); throw error; }
    } });
  };
  const saveModel = async () => {
    try {
      const values = await form.validateFields();
      if (editing && references(editing).length && values.type !== editing.type) { message.warning('正在使用的模型不可更改用途类型，请另建模型配置。'); return; }
      if (editing && embeddingLocked(editing) && (values.modelId !== editing.modelId || values.provider !== editing.provider || connections.find(item => item.id === values.providerConfigId)?.baseUrl !== editing.baseUrl || values.dimensions !== editing.dimensions)) { message.warning('此 Embedding 已被知识库或已发布索引引用。请新增配置，再迁移知识库并重建索引。'); return; }
      const payload = { ...values, dimensions: values.type === 'Embedding' ? values.dimensions : undefined };
      setModelBusy(true); await flush();
      await api(`/api/models/${editing?.id ?? uid()}`, { method: 'PUT', body: JSON.stringify(payload) });
      await refresh(); setEditOpen(false); setProvider(values.provider);
      message.success('模型已保存，将使用所选服务商连接的密钥');
    } catch (error) { if (!(error as { errorFields?: unknown }).errorFields) message.error((error as Error).message); }
    finally { setModelBusy(false); }
  };
  const deleteModel = (model: ModelConfig) => {
    const usedBy = references(model);
    if (usedBy.length) { modal.info({ title: '该模型正在使用中', content: <p>{usedBy.join('、')}正在引用此配置。请先完成迁移后再删除。</p> }); return; }
    if (model.isDefault) { message.warning('请先将同类型的其他模型设为默认，再删除此配置。'); return; }
    modal.confirm({ title: `删除「${model.name}」？`, content: '只移除模型用途配置，服务商连接与密钥会保留。', okText: '删除模型', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => {
      updateState(previous => ({ ...previous, models: previous.models.filter(item => item.id !== model.id) }));
    } });
  };
  const setDefault = (model: ModelConfig) => {
    if (model.status !== 'connected') { message.warning('请先完成此模型能力的连接检测。'); return; }
    updateState(previous => ({ ...previous, models: previous.models.map(item => item.type === model.type ? { ...item, isDefault: item.id === model.id } : item) }));
  };
  const runTest = async () => {
    if (!testing) return; setTestBusy(true);
    try {
      await flush();
      const result = await api<{ message: string; duration: number }>(`/api/models/${testing.id}/test`, { method: 'POST' });
      await refresh(); setTesting(null);
      modal.success({ title: '模型连接检测通过', content: <div><p>{result.message}</p><p className="muted">实际耗时 {result.duration}s，详情已写入调用日志。</p></div> });
    } catch (error) { message.error((error as Error).message); await refresh(); }
    finally { setTestBusy(false); }
  };
  const fetchModels = async (connection: ProviderConfig) => {
    if (!connection.hasKey || connection.credentialError) { openProviderEditor(connection); return; }
    setFetchingCatalog(connection.id); setCatalogQuery('');
    try {
      await flush();
      const result = await api<{ models: CatalogModel[]; message?: string }>(`/api/providers/${connection.id}/models`, { method: 'POST' });
      setCatalog({ connection, ...result });
    } catch (error) { message.error((error as Error).message); }
    finally { setFetchingCatalog(null); }
  };
  const changeExternal = (enabled: boolean) => {
    const save = async () => { try { await api('/api/settings', { method: 'PUT', body: JSON.stringify({ allowExternalProcessing: enabled }) }); await refresh(); message.success(enabled ? '已允许使用配置的云端服务处理资料' : '已关闭云端资料处理'); } catch (error) { message.error((error as Error).message); } };
    if (enabled) modal.confirm({ title: '允许将资料发送至配置的云端模型？', content: '开启后，OCR会发送相应图片，Embedding/Rerank会发送文本片段，对话会发送问题、历史和检索资料。请确认服务商、账号与地域符合资料要求。获取模型目录与连接检测仅使用服务配置或内置内容。', okText: '允许云端处理', cancelText: '暂不开启', onOk: save }); else void save();
  };
  const openBinding = (model: ModelConfig) => {
    if (!canBind(model)) { message.warning('请先填写真实语言模型 ID，并配置有效服务商密钥'); return; }
    setBinding(model); setBindingAssistantId(state.assistants.find(item => item.modelId === model.id)?.id ?? state.assistants[0]?.id);
  };
  const saveBinding = async (goToChat: boolean) => {
    if (!binding || !bindingAssistantId || !canBind(binding)) return;
    setBindingBusy(true);
    try {
      const targetId = bindingAssistantId;
      const modelId = binding.id;
      updateState(previous => ({ ...previous, assistants: previous.assistants.map(item => item.id === targetId ? { ...item, modelId } : item) }));
      await flush();
      const saved = await api<WorkspaceState>('/api/workspace');
      if (!saved.assistants.some(item => item.id === targetId && item.modelId === modelId)) throw new Error('助手模型绑定未保存，请查看提示后重试');
      await refresh(); setBinding(null); message.success('已更新所选助手的语言模型');
      if (goToChat) { setActiveSessionId(null); setActiveAssistantId(targetId); navigate('chat'); }
    } catch (error) { message.error((error as Error).message); }
    finally { setBindingBusy(false); }
  };

  return <div className="page-body model-page">
    <div className="page-heading"><div><div className="eyebrow">MODEL PROVIDERS</div><h1>模型服务</h1><p className="muted">配置一次服务商密钥，让不同用途的模型共用连接。</p></div><Button type="primary" icon={<Plus size={16} />} onClick={() => openEditor()}>添加模型</Button></div>
    <div className="ml-demo-note"><ShieldCheck size={17} /><span>允许云端处理资料：开启后才会发送导入内容和对话资料；模型目录与连接检测不发送企业资料。</span><Switch aria-label="允许云端处理资料" checked={!!state.settings?.allowExternalProcessing} onChange={changeExternal} /></div>
    <div className="model-capability-strip">{kinds.map(kind => { const Icon = kindIcons[kind]; const model = state.models.find(item => item.type === kind && item.isDefault); return <div className="model-capability" key={kind}><div className="model-capability-icon"><Icon size={18} /></div><div><strong>{kind}</strong><Tooltip title={model?.name ?? '请配置并设置默认模型'}><span className={model ? '' : 'muted'}>{model?.name ?? '尚未设置默认'}</span></Tooltip></div><span className={`model-capability-dot ${model?.status === 'connected' ? 'ready' : ''}`} /></div>; })}</div>
    <div className="surface model-main-surface">
      <Tabs activeKey={provider} onChange={value => setProvider(value as Provider)} items={providers.map(item => ({ key: item, label: <span className="provider-tab"><span className={`provider-symbol ${item === '通义千问' ? 'qwen' : item === 'OpenRouter' ? 'router' : 'hub'}`}>{item === '通义千问' ? 'Q' : item === 'OpenRouter' ? <ArrowUpRight size={15} /> : 'A'}</span>{item}<span className="provider-count">{state.models.filter(model => model.provider === item).length}</span></span> }))} />
      <section className="provider-connections" aria-label={`${provider}的服务商连接`}>
        <div className="provider-connections-heading"><div><h2>服务商连接</h2><p>同一连接下的所有模型共用 API Key 和服务地址。</p></div><Button icon={<Plus size={14} />} onClick={() => openProviderEditor()}>添加连接</Button></div>
        {visibleConnections.length ? <div className="provider-connection-list">{visibleConnections.map(connection => <article className="provider-connection-card" key={connection.id} {...cardAction(()=>openProviderEditor(connection),`配置${connection.name}`)}>
          <div className="provider-connection-key"><KeyRound size={21} /></div><div className="provider-connection-info"><div><strong>{connection.name}</strong><Tag color={connection.credentialError ? 'error' : connection.hasKey ? 'green' : 'default'}>{connection.credentialError ? '密钥需修复' : connection.hasKey ? '密钥已配置' : '待配置密钥'}</Tag></div><code title={connection.baseUrl}>{connection.baseUrl}</code><span>{state.models.filter(model => model.providerConfigId === connection.id).length} 个模型共用此连接 · {connection.credentialError ?? (connection.hasKey ? '模型权限以服务商账号为准' : '先配置密钥，再选择模型用途')}</span></div>
          <div className="provider-connection-actions"><Button type={connection.hasKey && !connection.credentialError ? 'default' : 'primary'} icon={<Settings2 size={14} />} onClick={() => openProviderEditor(connection)}>{connection.credentialError ? '修复 API Key' : connection.hasKey ? '编辑连接' : '配置 API Key'}</Button><Button icon={<ArrowDownToLine size={14} />} loading={fetchingCatalog === connection.id} disabled={!!fetchingCatalog && fetchingCatalog !== connection.id} onClick={() => void fetchModels(connection)}>获取模型目录</Button><Tooltip title="删除连接"><Button type="text" aria-label={`删除连接${connection.name}`} icon={<Trash2 size={14} />} onClick={() => deleteProvider(connection)} /></Tooltip></div>
        </article>)}</div> : <div className="provider-connection-empty"><KeyRound size={22} /><div><strong>先连接 {provider}</strong><p>保存一次 API Key，后续添加 LLM、Embedding、Rerank、OCR 和 Vision 模型时无需重复填写。</p></div><Button type="primary" onClick={() => openProviderEditor()}>配置服务商</Button></div>}
      </section>
      <div className="model-toolbar"><span className="muted">已添加 {state.models.filter(model => model.provider === provider).length} 个模型用途</span><Select aria-label="筛选模型能力" value={kindFilter} onChange={setKindFilter} style={{ width: 160 }} options={[{ value: 'all', label: '全部模型类型' }, ...kinds.map(kind => ({ value: kind, label: kind }))]} /></div>
      {visibleModels.length ? <div className="model-card-grid">{visibleModels.map(model => { const Icon = kindIcons[model.type]; const usedBy = references(model); const connection = connections.find(item => item.id === model.providerConfigId); return <article className="model-card" key={model.id} {...cardAction(()=>openEditor(model),`配置${model.name}`)}>
        <div className="model-card-top"><span className="model-card-icon"><Icon size={20} /></span><Tag>{model.type}</Tag>{model.isDefault && <Tag color="blue" className="model-default"><Check size={11} />默认</Tag>}<Dropdown menu={{ items: [{ key: 'edit', label: '编辑模型用途' }, ...(model.type === 'LLM' ? [{ key: 'bind', label: '用于问答助手', disabled: !canBind(model) }] : []), { key: 'default', label: '设为默认模型', disabled: model.isDefault }, { type: 'divider' }, { key: 'delete', label: '删除模型', danger: true }], onClick: ({ key }) => key === 'edit' ? openEditor(model) : key === 'bind' ? openBinding(model) : key === 'default' ? setDefault(model) : deleteModel(model) }} trigger={['click']}><Button type="text" aria-label={`${model.name}的更多操作`} icon={<Ellipsis size={19} />} /></Dropdown></div>
        <h3>{model.name}</h3><div className="model-id" title={model.modelId}>{model.modelId || '尚未填写模型 ID'}</div><p className="model-description">{descriptions[model.type]}</p>
        <div className="model-config-lines"><div><span>服务商连接</span><Tooltip title={connection?.baseUrl ?? model.baseUrl}><code>{connection?.name ?? '请关联服务商连接'}</code></Tooltip></div><div><span>{model.type === 'Embedding' ? '向量维度' : '配置引用'}</span><span>{model.type === 'Embedding' ? `${model.dimensions ?? '—'} 维` : `${usedBy.length} 处`}</span></div></div>
        {model.lastError && <Alert type="error" showIcon title="最近调用失败" description={model.lastError} style={{ marginBottom: 14, fontSize: 12, overflowWrap: 'anywhere' }} />}<div className="model-card-bottom"><span className={`model-connection ${model.status}`}><span className="status-dot" />{connection?.credentialError ? '密钥格式有误' : !model.hasKey ? '连接待配置密钥' : model.status === 'connected' ? '模型已连接' : model.status === 'failed' ? '连接异常' : '待模型检测'}</span><Button size="small" icon={<Radio size={13} />} disabled={!model.hasKey || !model.modelId || !!connection?.credentialError} onClick={() => setTesting(model)}>连接检测</Button></div>
      </article>; })}</div> : <div className="model-empty"><Empty description="还没有此类型的模型用途"><Button onClick={() => openEditor()}>添加模型</Button></Empty></div>}
    </div>
    <div className="model-footnote"><KeyRound size={15} /><span>同一服务商可配置多个账号或地域。模型共用所选连接的密钥，实际可用范围由账号权限决定；更新密钥后需分别确认各用途模型可用。</span></div>

    <Modal open={providerOpen} title={editingProvider ? '编辑服务商连接' : '添加服务商连接'} onCancel={() => { if (!providerBusy) setProviderOpen(false); }} onOk={() => void saveProvider()} confirmLoading={providerBusy} okText="保存连接" cancelText="取消" width={620} forceRender>
      <Alert type="info" showIcon title="一个连接，一份共享密钥" description="LLM、Embedding、Rerank、OCR、Vision 模型均可引用此连接。密钥仅在本机后端加密保存，不会回传浏览器。" style={{ marginBottom: 22 }} />
      <Form form={providerForm} layout="vertical" preserve={false}>
        <Form.Item label="服务商" name="provider" rules={[{ required: true }]}><Select disabled={!!editingProvider} onChange={(value: Provider) => providerForm.setFieldsValue({ baseUrl: baseUrls[value], name: `${value} · 新连接` })} options={providers.map(value => ({ label: value, value }))} /></Form.Item>
        <Form.Item label="连接名称" name="name" rules={[{ required: true, whitespace: true, message: '请输入连接名称' }, { max: 80, message: '名称最多 80 个字符' }]} extra="例如：通义千问 · 北京、AIHubMix · 团队账号。"><Input maxLength={80} placeholder="为账号或地域取一个易识别的名称" /></Form.Item>
        <Form.Item label="Base URL" name="baseUrl" rules={[{ required: true, message: '请输入服务地址' }, { pattern: /^https?:\/\/[^\s]+$/, message: '请输入有效的 HTTP(S) 服务地址' }]} extra="填写兼容接口基路径，不追加 /chat/completions 或 /embeddings。"><Input placeholder="https://…/v1" /></Form.Item>
      </Form>
      {editingProvider?.credentialError && <Alert type="error" showIcon title="已保存的密钥格式无效" description={editingProvider.credentialError} style={{ marginBottom: 16 }} />}<label className="model-secret-label" htmlFor="provider-api-secret">API Key</label>{providerOpen && <Input.Password key={editingProvider?.id ?? 'new-provider'} ref={secretInput} id="provider-api-secret" autoComplete="new-password" placeholder={editingProvider?.hasKey ? '已保存密钥；留空保留，输入则替换' : '输入此服务商账号的 API Key'} />}
      <p className="model-reference-note"><KeyRound size={14} />从服务商控制台复制实际密钥，仅接受可见英文字符；不要填写中文说明、空格或换行。可粘贴单个 Bearer 前缀，保存时会自动移除。</p><p className="model-reference-note"><CircleAlert size={14} />更新密钥会应用到所有关联模型，并将连接检测状态改为待检测。被知识库索引引用的服务地址如需变更，请新增连接后迁移。</p>
    </Modal>

    <Modal open={editOpen} title={editing ? '编辑模型用途' : '添加模型用途'} onCancel={() => { if (!modelBusy) setEditOpen(false); }} onOk={() => void saveModel()} confirmLoading={modelBusy} okText="保存模型" cancelText="取消" width={620} forceRender>
      <Alert type="info" showIcon title="直接复用服务商连接" description="这里仅设置模型和用途，无需重复填写 API Key。可输入该服务商支持的任意模型 ID，实际调用以账号权限和模型能力为准。" style={{ marginBottom: 22 }} />
      <Form form={form} layout="vertical" preserve={false}>
        <div className="model-form-row"><Form.Item label="服务商" name="provider" rules={[{ required: true }]}><Select onChange={(value: Provider) => form.setFieldValue('providerConfigId', preferredConnection(value)?.id)} options={providers.map(value => ({ label: value, value }))} /></Form.Item><Form.Item label="模型能力" name="type" rules={[{ required: true }]}><Select placeholder="请选择模型能力" options={kinds.map(value => ({ value, label: value }))} /></Form.Item></div>
        <Form.Item label="服务商连接" name="providerConfigId" rules={[{ required: true, message: '请先配置并选择服务商连接' }]} extra={selectedConnection ? `${selectedConnection.baseUrl} · ${selectedConnection.credentialError ? '已保存密钥格式无效，请先修复' : selectedConnection.hasKey ? '继承已保存密钥' : '此连接尚未配置密钥'}` : '请先在服务商连接区添加账号或地域配置。'}><Select placeholder="选择共享 API Key 的连接" options={availableConnections.map(item => ({ value: item.id, label: `${item.name}${item.credentialError ? ' · 密钥需修复' : item.hasKey ? '' : ' · 待配置密钥'}` }))} /></Form.Item>
        <Form.Item label="显示名称" name="name" rules={[{ required: true, whitespace: true, message: '请输入便于识别的模型名称' }, { max: 50, message: '名称最多 50 个字符' }]}><Input placeholder="例如：企业问答模型" maxLength={50} /></Form.Item>
        <Form.Item label="请求模型 ID" name="modelId" extra="复制服务商的请求 ID，不要填写展示名称；从模型目录添加会自动填写 ID。" dependencies={['type']} rules={[{ required: true, whitespace: true, message: '请输入服务商的模型 ID' }, { validator: async (_, value: string = '') => { if (/\s/.test(value.trim())) throw new Error('请求模型 ID 不能含空格，请复制服务商的请求 ID，而不是展示名称'); if (isJinaNano(value) && form.getFieldValue('type') !== 'Embedding') throw new Error('该 Jina 模型用于 Embedding，不能作为语言模型或其他能力调用'); } }]}><Input placeholder="例如：qwen-plus" onChange={event => { if (isJinaNano(event.target.value)) form.setFieldsValue({ type: 'Embedding', dimensions: 768 }); }} /></Form.Item>{isJinaNano(watchedModelId) && <Alert type="info" showIcon title="这是 Embedding 向量模型" description="jina-embeddings-v5-text-nano 默认输出 768 维，用于知识库索引与语义检索。问答助手需另选 LLM 模型生成回答。" style={{ marginBottom: 18 }} />}
        {watchedKind === 'Embedding' && <Form.Item label="向量维度" name="dimensions" rules={[{ required: true, message: '请输入模型输出的向量维度' }]} extra="维度须与模型输出一致；已入库的向量不能直接切换模型。"><InputNumber min={1} max={16000} precision={0} style={{ width: '100%' }} /></Form.Item>}
      </Form>
      {editing && references(editing).length > 0 && <p className="model-reference-note"><CircleAlert size={14} />已被 {references(editing).length} 处引用。{embeddingLocked(editing) ? '此向量模型的型号、服务商、地址及维度需保持一致；变更请新建配置并重建索引。' : '用途类型需保持一致；同类型语言模型可更换型号或服务商连接。'}</p>}
    </Modal>

    <Modal open={!!catalog} title={`${catalog?.connection.name ?? ''} · 模型目录`} onCancel={() => setCatalog(null)} footer={<Button onClick={() => setCatalog(null)}>关闭</Button>} width={850} destroyOnHidden>
      <Alert type="info" showIcon title="目录来自所选服务商" description={catalog?.message ?? '模型目录不保证账号拥有全部调用权限。选择模型后设置用途；未列出的模型仍可手动填写 ID。'} style={{ marginBottom: 18 }} />
      <Input.Search aria-label="搜索服务商模型目录" placeholder="搜索模型名称或 ID" value={catalogQuery} onChange={event => setCatalogQuery(event.target.value)} allowClear style={{ marginBottom: 14 }} />
      <Table<CatalogModel> rowKey="id" size="small" dataSource={(catalog?.models ?? []).filter(item => `${item.name} ${item.id}`.toLowerCase().includes(catalogQuery.toLowerCase()))} pagination={{ pageSize: 7, showSizeChanger: false, showTotal: total => `共 ${total} 个模型` }} locale={{ emptyText: <Empty description="暂无匹配模型，可在添加模型中手动填写模型 ID" /> }} columns={[
        { title: '模型', dataIndex: 'name', render: (name: string, row) => <div className="provider-catalog-name"><strong>{name || row.id}</strong><code>{row.id}</code></div> },
        { title: '目录能力', dataIndex: 'types', width: 170, render: (types: ModelKind[]) => types?.length ? <Space size={[2, 4]} wrap>{types.map(type => <Tag key={type}>{type}</Tag>)}</Space> : <span className="muted">添加时选择</span> },
        { title: '', width: 100, render: (_, row) => <Button size="small" onClick={() => { if (catalog) { openEditor(undefined, catalog.connection, row); setCatalog(null); } }}>添加用途</Button> },
      ]} />
    </Modal>

    <Modal open={!!binding} title="用于问答助手" onCancel={() => { if (!bindingBusy) setBinding(null); }} footer={<Space><Button disabled={bindingBusy} onClick={() => setBinding(null)}>取消</Button><Button loading={bindingBusy} disabled={!bindingAssistantId} onClick={() => void saveBinding(false)}>保存绑定</Button><Button type="primary" loading={bindingBusy} disabled={!bindingAssistantId} onClick={() => void saveBinding(true)}>保存并开始对话</Button></Space>} width={560} destroyOnHidden>
      <Alert type="info" showIcon title={`语言模型：${binding?.name ?? ''}`} description="选择要更换模型的助手。此操作只修改所选助手的回答模型，知识库与检索设置保持原样。" style={{ marginBottom: 20 }} />
      {state.assistants.length ? <><label className="model-secret-label">问答助手</label><Select aria-label="选择使用此语言模型的助手" value={bindingAssistantId} onChange={setBindingAssistantId} style={{ width: '100%' }} options={state.assistants.map(item => ({ value: item.id, label: `${item.name} · 当前：${state.models.find(model => model.id === item.modelId)?.name ?? '模型已移除'}` }))} /><p className="model-reference-note">开始对话前仍需开启云端资料处理，并确保助手关联的知识库有已发布内容。</p></> : <Empty description="还没有问答助手"><Button onClick={() => { setBinding(null); navigate('assistants'); }}>前往创建助手</Button></Empty>}
    </Modal>

    <Modal open={!!testing} title="模型连接检测" okText={testBusy ? '正在检测…' : '开始连接检测'} cancelText="取消" onOk={runTest} confirmLoading={testBusy} onCancel={() => { if (!testBusy) setTesting(null); }} closable={!testBusy} mask={{ closable: !testBusy }} cancelButtonProps={{ disabled: testBusy }} destroyOnHidden>
      <div className="model-test-target"><Cpu size={23} /><div><strong>{testing?.name}</strong><p className="muted">{testing?.provider} · {testing?.type} · {connections.find(item => item.id === testing?.providerConfigId)?.name}</p></div></div>
      <Alert type="info" showIcon title="使用服务商共享密钥发送真实请求" description="只检测当前模型及其能力，不代表此账号的所有模型均可用。请求使用内置内容，可能产生少量费用。" />
      <p className="model-reference-note">返回结果、实际用量与耗时会记录到模型调用日志。</p>
    </Modal>
  </div>;
}
