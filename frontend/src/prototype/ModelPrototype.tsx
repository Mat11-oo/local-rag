import { useState } from 'react';
import { Alert, Button, Input, Modal, Select, Tag } from 'antd';
import { ArrowRight, CheckCircle2, CircleAlert, CircleHelp, Cpu, ExternalLink, KeyRound, Plus, Search, ShieldCheck } from 'lucide-react';
import './model-prototype.css';

type Vendor = 'AIHubMix' | '通义千问' | 'OpenRouter';
type Kind = 'LLM' | 'Embedding' | 'Rerank' | 'OCR' | 'Vision';
type ExampleModel = { key: string; name: string; modelId: string; kind: Kind; lastCall: '失败' | '未检测'; };

const exampleModels: Record<Vendor, ExampleModel[]> = {
  AIHubMix: [
    { key: 'chat', name: '日常问答模型', modelId: 'DeepSeek V4.1 Flash 1017', kind: 'LLM', lastCall: '失败' },
    { key: 'embed', name: '知识向量模型', modelId: 'jina-embeddings-v5-text-nano', kind: 'Embedding', lastCall: '未检测' },
  ],
  通义千问: [{ key: 'qwen', name: '通义对话模型', modelId: 'qwen-plus', kind: 'LLM', lastCall: '未检测' }],
  OpenRouter: [],
};
const vendorDescription: Record<Vendor, string> = {
  AIHubMix: '连接后可配置该服务商下的多种模型用途',
  通义千问: '配置对应地域的服务地址和 API Key',
  OpenRouter: '使用一个服务商连接管理多个模型',
};
const emptyModel = (): ExampleModel => ({ key: '', name: '', modelId: '', kind: 'LLM', lastCall: '未检测' });

export default function ModelPrototype() {
  const [vendor, setVendor] = useState<Vendor>('AIHubMix');
  const [models, setModels] = useState(exampleModels);
  const [edit, setEdit] = useState<ExampleModel | null>(null);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [detectOpen, setDetectOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [connectionName, setConnectionName] = useState('AIHubMix · 默认连接');
  const [baseUrl, setBaseUrl] = useState('https://aihubmix.com/v1');

  const openConnection = () => {
    setConnectionName(`${vendor} · 默认连接`);
    setBaseUrl(vendor === 'AIHubMix' ? 'https://aihubmix.com/v1' : vendor === '通义千问' ? 'https://dashscope.aliyuncs.com/compatible-mode/v1' : 'https://openrouter.ai/api/v1');
    setConnectionOpen(true);
  };
  const saveEdit = () => {
    if (!edit || !edit.name.trim() || !edit.modelId.trim() || /\s/.test(edit.modelId.trim())) return;
    const saved = { ...edit, key: edit.key || `new-${Date.now()}`, modelId: edit.modelId.trim(), lastCall: '未检测' as const };
    setModels(previous => ({ ...previous, [vendor]: edit.key ? previous[vendor].map(item => item.key === edit.key ? saved : item) : [...previous[vendor], saved] }));
    setEdit(null);
    setNotice('示例模型已更新。仅保存在当前原型页面，不代表实际配置或连接已更新。');
  };
  const selectCatalogModel = () => {
    setEdit(previous => ({ ...(previous ?? emptyModel()), name: previous?.name || 'DeepSeek 对话模型', modelId: 'deepseek-v4.1-flash-1017', kind: 'LLM' }));
    setCatalogOpen(false);
  };
  const failure = models[vendor].find(item => item.lastCall === '失败');
  const invalidModelId = !!edit?.modelId.trim() && /\s/.test(edit.modelId.trim());

  return <div className="proto-model-page">
    <div className="proto-model-heading"><div><div className="proto-model-eyebrow">MODEL SERVICES</div><h1>模型服务</h1><p>集中管理服务商连接和模型用途，让每个环节使用合适的模型。</p></div><Button icon={<Plus size={15}/>} type="primary" onClick={() => setEdit(emptyModel())}>添加模型</Button></div>

    <div className="proto-model-intro"><span className="proto-model-intro-icon"><ShieldCheck size={19}/></span><div><strong>一个服务商连接，多个模型共用</strong><p>先配置服务地址和 API Key，再添加对话、向量和重排等模型。模型的可用范围取决于服务商和账号权限。</p></div><span className="proto-model-intro-step">01 配置连接 <ArrowRight size={14}/> 02 添加模型</span></div>
    {notice && <Alert className="proto-model-notice" type="info" showIcon message={notice} closable onClose={() => setNotice('')}/>}

    <div className="proto-model-layout"><aside className="proto-model-vendors"><div className="proto-model-section-label">模型服务商</div>{(['AIHubMix', '通义千问', 'OpenRouter'] as Vendor[]).map((item, index) => <button type="button" key={item} className={`proto-model-vendor ${vendor === item ? 'is-active' : ''}`} onClick={() => { setVendor(item); setNotice(''); }}><span className={`proto-model-vendor-logo logo-${index}`}>{item === '通义千问' ? '通' : item === 'AIHubMix' ? 'A' : 'O'}</span><span><strong>{item}</strong><small>{item === 'OpenRouter' ? '示例：未配置模型' : `${models[item].length} 个示例模型`}</small></span><span className="proto-model-vendor-arrow">›</span></button>)}</aside>

      <div className="proto-model-main"><section className="proto-model-surface"><div className="proto-model-section-head"><div><span className="proto-model-eyebrow">PROVIDER CONNECTION</span><h2>{vendor} 服务商连接</h2><p>{vendorDescription[vendor]}</p></div><Button icon={<KeyRound size={15}/>} onClick={openConnection}>管理连接</Button></div><div className="proto-model-connection"><span className="proto-model-connection-icon"><KeyRound size={18}/></span><div><strong>{vendor} · 默认连接 <Tag color="default">示例数据</Tag></strong><p>密钥由服务商连接管理，关联模型共用同一连接。</p></div><span className="proto-model-status"><span/>配置示意</span></div><p className="proto-model-hint"><CircleHelp size={14}/>保存服务商配置与模型可调用是不同状态；需要时请由管理员主动发起连接检测。</p></section>

        {failure && <section className="proto-model-error"><span className="proto-model-error-icon"><CircleAlert size={19}/></span><div><strong>示例：最近一次调用失败</strong><p>服务商提示模型 ID 无效。展示名称不能直接作为请求模型 ID；请到模型目录复制实际请求 ID。</p><div className="proto-model-error-meta">示例请求：<code>{failure.modelId}</code><span> · </span>错误类型：模型 ID 无效</div><div className="proto-model-error-actions"><Button size="small" onClick={() => setEdit({ ...failure })}>修改请求模型 ID</Button><Button size="small" type="link" onClick={() => { setCatalogQuery(''); setCatalogOpen(true); }}>查看模型目录示意 <ArrowRight size={13}/></Button></div></div></section>}

        <section className="proto-model-surface proto-model-list"><div className="proto-model-section-head"><div><span className="proto-model-eyebrow">MODEL CONFIGURATION</span><h2>模型用途</h2><p>分别为对话、知识索引和其他处理环节选择模型。</p></div><Button icon={<Search size={14}/>} onClick={() => { setCatalogQuery(''); setCatalogOpen(true); }}>查看模型目录示意</Button></div>
          {models[vendor].length ? <div className="proto-model-table"><div className="proto-model-table-head"><span>模型名称 / 请求模型 ID</span><span>用途</span><span>配置状态</span><span>最近调用</span><span>操作</span></div>{models[vendor].map(model => <div className="proto-model-table-row" key={model.key}><div className="proto-model-name"><span className="proto-model-chip-icon"><Cpu size={17}/></span><div><strong>{model.name}</strong><small>{model.modelId}</small></div></div><span><Tag color={model.kind === 'LLM' ? 'blue' : 'purple'}>{model.kind}</Tag></span><span>已填写 · 示意</span><span><span className={`proto-model-call ${model.lastCall === '失败' ? 'failed' : ''}`}>{model.lastCall === '失败' ? <CircleAlert size={14}/> : <CircleHelp size={14}/>} {model.lastCall}</span></span><div className="proto-model-row-actions"><button onClick={() => setEdit({ ...model })}>编辑</button><button onClick={() => setDetectOpen(true)}>检测</button></div></div>)}</div> : <div className="proto-model-empty"><Cpu size={25}/><strong>还没有示例模型</strong><p>添加模型用途后，可以在相应流程中选择使用。</p><Button onClick={() => setEdit(emptyModel())}>添加示例模型</Button></div>}
          <div className="proto-model-list-foot"><CheckCircle2 size={15}/> 请求模型 ID 由服务商提供；不同用途需要分别选择支持该能力的模型。</div></section>
      </div>
    </div>

    <Modal title={`${vendor} 服务商连接 · 原型示意`} open={connectionOpen} onCancel={() => setConnectionOpen(false)} onOk={() => { setConnectionOpen(false); setNotice('示例连接已更新，仅用于展示交互，不会保存真实密钥或调用服务商。'); }} okText="保存示例" cancelText="取消" destroyOnHidden>
      <Alert type="info" showIcon message="这是隔离原型，请勿输入真实 API Key。不会保存或验证任何真实连接。"/><div className="proto-model-form"><label>连接名称<Input value={connectionName} onChange={event => setConnectionName(event.target.value)}/></label><label>服务地址<Input value={baseUrl} onChange={event => setBaseUrl(event.target.value)}/></label><label>API Key<Input.Password disabled placeholder="真实密钥输入仅在正式功能中提供"/></label><p>该连接下的模型用途共用服务商密钥。保存配置不代表连接检测通过。</p></div>
    </Modal>

    <Modal title={`${edit?.key ? '编辑模型' : '添加模型'} · 原型示意`} open={!!edit} onCancel={() => setEdit(null)} onOk={saveEdit} okText="保存示例" cancelText="取消" okButtonProps={{ disabled: !edit?.name.trim() || !edit?.modelId.trim() || invalidModelId }} destroyOnHidden>
      {edit && <div className="proto-model-form"><Alert type="info" showIcon message="修改仅用于展示，不会影响真实模型配置。"/><label>模型展示名称<Input value={edit.name} placeholder="例如：日常问答模型" onChange={event => setEdit({ ...edit, name: event.target.value })}/><small>便于团队识别的名称，不会发送给服务商。</small></label><label>请求模型 ID<Input status={invalidModelId ? 'error' : undefined} value={edit.modelId} placeholder="复制服务商提供的请求模型 ID" onChange={event => setEdit({ ...edit, modelId: event.target.value })}/><small className={invalidModelId ? 'is-error' : ''}>{invalidModelId ? '模型 ID 不能包含空格；请复制实际请求 ID，而非展示名称。' : '实际发给服务商的模型标识；与上方展示名称可能不同。'}</small></label><Button icon={<Search size={14}/>} onClick={() => { setCatalogQuery(''); setCatalogOpen(true); }}>从模型目录示意中选择</Button><label>模型用途<Select value={edit.kind} onChange={value => setEdit({ ...edit, kind: value })} options={(['LLM', 'Embedding', 'Rerank', 'OCR', 'Vision'] as Kind[]).map(value => ({ value, label: value }))}/></label></div>}
    </Modal>

    <Modal title={`${vendor} 模型目录 · 原型示意`} open={catalogOpen} onCancel={() => setCatalogOpen(false)} footer={null} destroyOnHidden><Alert type="info" showIcon message="以下为示例，不是实时目录；选择后填入请求模型 ID。"/><div className="proto-model-catalog"><Input prefix={<Search size={15}/>} value={catalogQuery} placeholder="搜索名称或请求模型 ID" onChange={event => setCatalogQuery(event.target.value)}/>{vendor === 'AIHubMix' && (!catalogQuery || 'deepseek v4.1 flash 1017 deepseek-v4.1-flash-1017'.includes(catalogQuery.toLowerCase())) ? <div className="proto-model-catalog-item"><div><strong>DeepSeek V4.1 Flash 1017</strong><p>请求模型 ID：<code>deepseek-v4.1-flash-1017</code></p></div><Button type="primary" size="small" onClick={selectCatalogModel}>选择示例</Button></div> : <p className="proto-model-hint">没有匹配的示例模型。正式功能可从服务商获取目录，或手动填写模型 ID。</p>}{vendor === 'AIHubMix' && <a href="https://aihubmix.com/models" target="_blank" rel="noreferrer">打开 AIHubMix 官方模型目录 <ExternalLink size={13}/></a>}</div></Modal>

    <Modal title="连接检测说明" open={detectOpen} onCancel={() => setDetectOpen(false)} footer={<Button type="primary" onClick={() => setDetectOpen(false)}>知道了</Button>}><Alert type="info" showIcon message="原型不发起请求，也不会显示虚假的检测结果。"/><p className="proto-model-modal-copy">正式版中，连接检测由管理员主动发起，可能产生 API 调用费用；检测结果只反映当次调用，不保证后续始终可用。</p></Modal>
  </div>;
}
