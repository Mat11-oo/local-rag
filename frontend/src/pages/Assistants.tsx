import { cardAction } from '../cardAction';
import { useState } from 'react';
import { App, Alert, Button, Empty, Form, Input, Modal, Popconfirm, Select, Slider, Switch, Tag, Tooltip } from 'antd';
import { ArrowRight, Bot, ChevronRight, Database, LayoutGrid, List, MessageSquare, Plus, Search, Settings2, ShieldCheck, Trash2, Workflow } from 'lucide-react';
import { uid, useWorkspace } from '../store';
import type { AssistantConfig } from '../types';
import './chat.css';
import './applications.css';
import AdvancedApplications from './AdvancedApplications';

type AssistantForm = Omit<AssistantConfig, 'id' | 'examples'> & { examplesText: string };
type ApplicationType = 'all' | 'simple' | 'chatflow' | 'agent';
const applicationTypes = [
 { id: 'simple', name: '简易应用', description: '配置提示词和知识库，快速搭建有据可查的问答应用。', icon: MessageSquare, color: '#3370ff', available: true },
 { id: 'chatflow', name: 'Chat Flow', description: '通过可视化节点编排复杂业务流程。支持节点调试、发布与运行追踪。', icon: Workflow, color: '#7a5af8', available: true },
 { id: 'agent', name: 'Agent', description: '由模型规划任务并调用工具。支持内置与外部运行器。', icon: Bot, color: '#12b76a', available: true },
] as const;

export default function Assistants() {
 const { state, updateState, setActiveAssistantId, setActiveSessionId, navigate, role } = useWorkspace();
 const { message } = App.useApp();
 const [editingId, setEditingId] = useState<string | null>(null);
 const [open, setOpen] = useState(false);
 const [typeOpen, setTypeOpen] = useState(false);
 const [advancedCreate,setAdvancedCreate]=useState<'chatflow'|'agent'|null>(null);
 const [search, setSearch] = useState('');
 const [applicationType, setApplicationType] = useState<ApplicationType>('all');
 const [view, setView] = useState<'grid' | 'list'>('grid');
 const [form] = Form.useForm<AssistantForm>();
 const selectedKbs: string[] = Form.useWatch('kbIds', { form, preserve: true }) ?? [];
 const rerank = Form.useWatch('rerank', { form, preserve: true });
 const modelId = Form.useWatch('modelId', { form, preserve: true });
 const filtered = state.assistants.filter(item => (!item.type||item.type==='simple')).filter(item => `${item.name}${item.description}`.toLowerCase().includes(search.trim().toLowerCase()));
 const llms = state.models.filter(item => item.type === 'LLM');
 const hasReranker = state.models.some(item => item.type === 'Rerank' && item.status === 'connected');
 const unsupported = applicationType === 'chatflow' || applicationType === 'agent';
 const profileFor = (kbId: string) => state.knowledgeBases.find(kb => kb.id === kbId)?.embeddingModelId;
 const compatible = (kbIds: string[]) => new Set(kbIds.map(profileFor)).size <= 1;
 const startEdit = (assistant?: AssistantConfig) => {
  setTypeOpen(false); form.resetFields(); setEditingId(assistant?.id ?? null);
  form.setFieldsValue(assistant ? { ...assistant, examplesText: assistant.examples.join('\n') } : {
   name: '', description: '', kbIds: [], modelId: llms.find(item => item.isDefault)?.id ?? llms[0]?.id,
   welcome: '你好，我是企业知识助手。你可以向我询问制度、流程与业务知识。',
   examplesText: '差旅报销需要准备哪些材料？\n新员工入职需要办理哪些手续？',
   prompt: '请根据已关联知识库中的资料回答问题，提供清晰的来源引用。没有足够依据时，请明确说明，不编造信息。',
   rerank: hasReranker && !!state.settings?.allowExternalProcessing, topK: 5,
  });
  setOpen(true);
 };
 const save = async () => {
  try {
   const values = await form.validateFields();
   if (!compatible(values.kbIds)) { message.error('关联知识库的 Embedding 配置不兼容，请选择使用相同配置的知识库。'); return; }
   if (!state.models.some(item => item.id === values.modelId && item.type === 'LLM')) { message.error('请选择有效的语言模型。'); return; }
   const assistant: AssistantConfig = {
    id: editingId ?? uid(), name: values.name.trim(), description: values.description?.trim() ?? '', kbIds: values.kbIds,
    modelId: values.modelId, welcome: values.welcome.trim(), prompt: values.prompt.trim(),
    examples: values.examplesText.split('\n').map(item => item.trim()).filter(Boolean).slice(0, 4), rerank: !!values.rerank, topK: values.topK,
   };
   updateState(previous => ({ ...previous, assistants: editingId ? previous.assistants.map(item => item.id === editingId ? assistant : item) : [...previous.assistants, assistant] }));
   setOpen(false); message.success(editingId ? '应用配置已提交保存' : '应用已提交创建');
  } catch { /* Validation errors stay beside their fields. */ }
 };
 const goChat = (id: string) => { setActiveSessionId(null); setActiveAssistantId(id); navigate('chat'); };
 const actions = (assistant: AssistantConfig) => <div className="zh-apps-card-actions"><Tooltip title="配置应用"><Button aria-label={`配置${assistant.name}`} type="text" size="small" icon={<Settings2 size={15} />} onClick={() => startEdit(assistant)} /></Tooltip><Popconfirm title={`删除“${assistant.name}”？`} description="已有对话与日志会保留。" okText="删除" cancelText="取消" onConfirm={() => { updateState(previous => ({ ...previous, assistants: previous.assistants.filter(item => item.id !== assistant.id) })); message.success('已提交删除应用'); }}><Tooltip title="删除应用"><Button aria-label={`删除${assistant.name}`} type="text" size="small" icon={<Trash2 size={15} />} /></Tooltip></Popconfirm></div>;

 return <div className="zh-apps-page">
  <div className="zh-apps-heading"><div><h1>应用</h1><p>把模型、知识和业务流程，组合成团队可直接使用的 AI 应用。</p></div><Button type="primary" icon={<Plus size={16} />} onClick={() => setTypeOpen(true)}>创建应用</Button></div>
  <div className="zh-apps-tabs" role="tablist" aria-label="应用类型">{([{id:'all',name:'全部应用'},{id:'simple',name:'简易应用'},{id:'chatflow',name:'Chat Flow'},{id:'agent',name:'Agent'}] as const).map(item => <button key={item.id} id={`zh-apps-tab-${item.id}`} role="tab" aria-controls="zh-apps-results" aria-selected={applicationType === item.id} className={applicationType === item.id ? 'active' : ''} onClick={() => setApplicationType(item.id)}>{item.name}<span>{state.assistants.filter(a=>item.id==='all'||(a.type||'simple')===item.id).length}</span></button>)}</div>
  <div className="zh-apps-toolbar"><Input prefix={<Search size={16} />} allowClear aria-label="搜索应用" placeholder="搜索应用名称或描述" value={search} onChange={event => setSearch(event.target.value)} /><span className="zh-apps-results-count">{unsupported ? state.assistants.filter(a=>a.type===applicationType).length : applicationType==='all'?state.assistants.length:filtered.length} 个应用</span><div className="zh-apps-view-toggle" role="group" aria-label="显示方式"><Tooltip title="卡片视图"><button aria-label="卡片视图" aria-pressed={view === 'grid'} className={view === 'grid' ? 'active' : ''} onClick={() => setView('grid')}><LayoutGrid size={16} /></button></Tooltip><Tooltip title="列表视图"><button aria-label="列表视图" aria-pressed={view === 'list'} className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}><List size={17} /></button></Tooltip></div></div>
  <div id="zh-apps-results" role="tabpanel" aria-labelledby={`zh-apps-tab-${applicationType}`}>
  {unsupported ? <AdvancedApplications filter={applicationType}/> : filtered.length ? view === 'grid' ? <div className="zh-apps-grid">{filtered.map((assistant, index) => {
   const linked = state.knowledgeBases.filter(kb => assistant.kbIds.includes(kb.id));
   const model = state.models.find(item => item.id === assistant.modelId);
   const documentCount = state.documents.filter(doc => assistant.kbIds.includes(doc.kbId) && doc.activeVersion && doc.enabled).length;
   const calls = role === 'admin' ? state.logs.filter(log => log.kind === 'chat' && log.assistantId === assistant.id).length : state.sessions.filter(session => session.assistantId === assistant.id).reduce((sum, session) => sum + session.messages.filter(message => message.role === 'user').length, 0);
   return <article className="zh-apps-card" key={assistant.id} {...cardAction(()=>goChat(assistant.id),`打开${assistant.name}`)}>
    <div className="zh-apps-card-top"><button className={`zh-apps-card-identity tone-${index % 3}`} onClick={() => goChat(assistant.id)} aria-label={`使用${assistant.name}`}><MessageSquare size={22} /></button><div className="zh-apps-card-name"><button onClick={() => goChat(assistant.id)}>{assistant.name}</button><Tag color="blue">简易应用</Tag></div>{actions(assistant)}</div>
    <p className="zh-apps-description">{assistant.description || '连接团队知识，提供有来源的问答。'}</p>
    <div className="zh-apps-kb-tags">{linked.length ? linked.slice(0, 2).map(kb => <Tag key={kb.id}><Database size={12} />{kb.name}</Tag>) : <span>尚未关联知识库</span>}{linked.length > 2 && <Tag>+{linked.length - 2}</Tag>}</div>
    <div className="zh-apps-model"><span className={model?.status === 'connected' ? 'ready' : 'pending'} /><span>{model?.name ?? '未选择模型'}</span>{model?.status !== 'connected' && <small>待配置 / 检测</small>}</div>
    <footer><span>{documentCount} 份可检索文档<span className="zh-apps-dot">·</span>{calls} 次{role === 'admin' ? '近期调用' : '我的提问'}</span><button onClick={() => goChat(assistant.id)}>开始使用 <ArrowRight size={14} /></button></footer>
   </article>;
  })}<button className="zh-apps-create-card" onClick={() => setTypeOpen(true)}><span><Plus size={23} /></span><strong>创建应用</strong><p>让一个业务场景拥有自己的 AI 助手</p></button></div> : <div className="zh-apps-table-wrap"><table className="zh-apps-table"><thead><tr><th>应用名称</th><th>类型</th><th>关联知识库</th><th>语言模型</th><th>{role === 'admin' ? '近期调用' : '我的提问'}</th><th>操作</th></tr></thead><tbody>{filtered.map(assistant => {
   const model = state.models.find(item => item.id === assistant.modelId);
   return <tr key={assistant.id}><td><button className="zh-apps-table-name" onClick={() => goChat(assistant.id)}><span><MessageSquare size={17} /></span><div><strong>{assistant.name}</strong><small>{assistant.description || '知识问答应用'}</small></div></button></td><td><Tag color="blue">简易应用</Tag></td><td>{assistant.kbIds.map(id => state.knowledgeBases.find(kb => kb.id === id)?.name).filter(Boolean).join('、') || '未关联'}</td><td>{model?.name ?? '未选择模型'}</td><td>{role === 'admin' ? state.logs.filter(log => log.kind === 'chat' && log.assistantId === assistant.id).length : state.sessions.filter(session => session.assistantId === assistant.id).reduce((sum, session) => sum + session.messages.filter(message => message.role === 'user').length, 0)}</td><td><div className="zh-apps-table-actions"><Button type="link" size="small" onClick={() => goChat(assistant.id)}>使用 <ChevronRight size={13} /></Button>{actions(assistant)}</div></td></tr>;
  })}</tbody></table></div> : <div className="zh-apps-empty"><Empty description={search ? '没有找到匹配的应用，试试其他关键词' : '创建第一个应用，连接团队的知识'}>{!search && <Button type="primary" onClick={() => setTypeOpen(true)}>创建应用</Button>}</Empty></div>}
  </div>
  {applicationType==='all'&&<AdvancedApplications filter="all" createType={advancedCreate} onCreated={()=>setAdvancedCreate(null)}/>}
  {applicationType!=='all'&&<AdvancedApplications filter="hidden" createType={advancedCreate} onCreated={()=>setAdvancedCreate(null)}/>}
  <div className="zh-apps-note"><ShieldCheck size={15} /><span>应用配置保存在本机。仅检索已发布、已启用的关联资料；近期调用按当前加载的运行日志统计。</span></div>
  <Modal title="创建应用" open={typeOpen} onCancel={() => setTypeOpen(false)} footer={null} width={730} className="zh-apps-type-modal"><p className="zh-apps-type-intro">选择适合你的应用类型。</p><div className="zh-apps-type-options">{applicationTypes.map(item => { const Icon = item.icon; return <button key={item.id} disabled={!item.available} className={item.available ? '' : 'unavailable'} onClick={() => {if(item.id==='simple')startEdit();else{setTypeOpen(false);setAdvancedCreate(item.id);}}}><span style={{background: `${item.color}12`, color: item.color}}><Icon size={23} /></span><strong>{item.name}</strong><p>{item.description}</p><small>{item.available ? <>开始创建 <ArrowRight size={13} /></> : '尚未接入'}</small></button>; })}</div></Modal>
  <Modal title={<span className="zh-apps-editor-title"><MessageSquare size={19} />{editingId ? '配置应用' : '创建简易应用'}<Tag color="blue">简易应用</Tag></span>} open={open} onCancel={() => setOpen(false)} onOk={() => void save()} okText="保存配置" cancelText="取消" width={780} forceRender className="zh-apps-editor">
   <Form form={form} layout="vertical" className="assistant-form" requiredMark="optional">
    <div className="assistant-form-section"><span>01</span><div><strong>基本信息</strong><p>让使用者一眼理解这个应用能帮什么忙。</p></div></div>
    <div className="assistant-form-grid"><Form.Item name="name" label="应用名称" rules={[{ required: true, whitespace: true, message: '请输入应用名称' }, { max: 30, message: '名称最多30个字' }]}><Input placeholder="例如：员工服务助手" maxLength={30} /></Form.Item><Form.Item name="modelId" label="语言模型" rules={[{ required: true, message: '请选择语言模型' }]}><Select placeholder="选择回答模型" options={llms.map(item => ({ value: item.id, label: `${item.name}${item.status === 'connected' ? '' : ' · 未就绪'}` }))} /></Form.Item></div>
    <Form.Item name="description" label="应用说明"><Input placeholder="例如：解答人事制度、差旅与日常办公问题" maxLength={100} showCount /></Form.Item>
    <div className="assistant-form-section"><span>02</span><div><strong>知识与回答规则</strong><p>选择这个应用可以检索的资料范围。</p></div></div>
    <Form.Item name="kbIds" label="关联知识库" rules={[{ required: true, type: 'array', min: 1, message: '请至少关联一个知识库' }, { validator: async (_, value: string[] = []) => { if (!compatible(value)) throw new Error('多个知识库必须使用相同的 Embedding 配置'); } }]} extra="多库问答要求使用相同的 Embedding 配置，避免混用向量空间。"><Select mode="multiple" placeholder="选择一个或多个知识库" options={state.knowledgeBases.map(kb => ({ value: kb.id, label: kb.name, disabled: !selectedKbs.includes(kb.id) && selectedKbs.length > 0 && profileFor(kb.id) !== profileFor(selectedKbs[0]) }))} /></Form.Item>
    <Form.Item name="prompt" label="回答规则" rules={[{ required: true, whitespace: true, message: '请输入回答规则' }]}><Input.TextArea rows={3} maxLength={2000} placeholder="说明回答的范围、语气和引用要求" /></Form.Item>
    <div className="assistant-retrieval-settings"><div><strong>结果重排</strong><p>对召回片段再次排序，优先选择相关资料。</p></div><Form.Item name="rerank" valuePropName="checked" noStyle><Switch aria-label="启用结果重排" /></Form.Item></div>
    {rerank && !hasReranker && <Alert type="warning" showIcon title="尚无就绪的 Rerank 模型；可保存配置，管理员完成连接检测后再对话。" style={{ marginBottom: 16 }} />}
    <Form.Item name="topK" label="最多引用片段数" extra="控制检索后交给语言模型的资料数量；更多资料会增加输入用量。"><Slider min={1} max={10} marks={{ 1: '1', 5: '5', 10: '10' }} /></Form.Item>
    <div className="assistant-form-section"><span>03</span><div><strong>对话体验</strong><p>用清晰的欢迎语和示例，引导使用者开始提问。</p></div></div>
    <Form.Item name="welcome" label="开场白" rules={[{ required: true, whitespace: true, message: '请输入开场白' }]}><Input.TextArea rows={2} maxLength={300} /></Form.Item>
    <Form.Item name="examplesText" label="示例问题" extra="每行一个问题，最多展示4个。"><Input.TextArea rows={3} placeholder="差旅报销需要哪些材料？&#10;新员工如何办理入职？" maxLength={500} /></Form.Item>
    <div className="assistant-form-preview"><MessageSquare size={17} /><div><strong>保存后即可调试</strong><p>已选择 {selectedKbs.length} 个知识库 · {state.models.find(item => item.id === modelId)?.name ?? '尚未选择模型'}。对话会调用配置的真实模型服务。</p></div></div>
   </Form>
   {!state.settings?.allowExternalProcessing && <Alert type="info" showIcon title="当前未开启云端处理" description="可以保存应用配置。生成回答前，需要管理员在工具的模型服务中确认并开启云端处理。" />}
   {modelId && !state.models.find(item => item.id === modelId)?.hasKey && <Alert style={{marginTop:12}} type="warning" showIcon title="所选模型尚未配置密钥" action={role === 'admin' ? <Button size="small" onClick={() => { setOpen(false); navigate('models'); }}>配置模型</Button> : undefined} />}
  </Modal>
 </div>;
}
