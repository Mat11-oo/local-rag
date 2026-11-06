import { useState } from 'react';
import { Alert, Button, Drawer, Input, Segmented, Select, Tag } from 'antd';
import { ArrowRight, ArrowUp, BookOpen, Bot, CircleAlert, CircleCheck, Database, FileText, MessageSquare, Settings2, Sparkles } from 'lucide-react';
import './chat-prototype.css';

type Scenario = '引用示例' | '未找到依据' | '模型调用失败';
type MockMessage = { question: string; scenario: Scenario };

export default function ChatPrototype({ role }: { role: 'admin' | 'knowledge' | 'user' }) {
  const [view, setView] = useState<'对话体验' | '助手配置'>('对话体验');
  const [scenario, setScenario] = useState<Scenario>('引用示例');
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<MockMessage[]>([]);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [knowledgeLinked, setKnowledgeLinked] = useState(true);
  const [modelSelected, setModelSelected] = useState(true);

  const send = (value: string) => {
    const question = value.trim();
    if (!question) return;
    setMessages(previous => [...previous, { question, scenario }]);
    setDraft('');
  };

  return <section className="proto-chat-page">
    <div className="proto-chat-heading">
      <div><span className="proto-chat-eyebrow">ASSISTANT &amp; CONVERSATION</span><h1>助手与对话</h1><p>清楚知道助手使用哪些知识，并从回答回到资料。</p></div>
      {role !== 'user' && <Segmented value={view} onChange={value => setView(value as typeof view)} options={['对话体验', '助手配置']} aria-label="切换助手与对话视图" />}
    </div>
    <Alert className="proto-chat-mock-note" type="info" showIcon title="交互原型 · 内容均为模拟" description="下方助手、状态、回答和来源仅用于讨论界面，不连接模型、不查询知识库，也不会保存数据。" />
    {view === '助手配置' ? <div className="proto-chat-config">
      <div className="proto-chat-config-main">
        <div className="proto-chat-card-title"><div><h2>通用知识助手</h2><p>配置此助手回答时使用的模型与知识范围。</p></div><Tag color="blue">模拟配置</Tag></div>
        <div className="proto-chat-field"><label>助手名称</label><Input defaultValue="通用知识助手" aria-label="助手名称（模拟）" /><span>让使用者知道这个助手适合回答什么。</span></div>
        <div className="proto-chat-field"><label>回答模型</label><Select value={modelSelected ? '示例对话模型' : '未选择'} onChange={value => setModelSelected(value !== '未选择')} options={[{ value: '示例对话模型', label: '示例对话模型 · AIHubMix' }, { value: '未选择', label: '暂不选择模型' }]} aria-label="选择回答模型（模拟）" /><span>模型配置和最近调用状态将在对话开始前展示。</span></div>
        <div className="proto-chat-field"><label>关联知识库</label><Select value={knowledgeLinked ? '员工制度库' : '未关联'} onChange={value => setKnowledgeLinked(value !== '未关联')} options={[{ value: '员工制度库', label: '员工制度库 · 3 份已发布文档（模拟）' }, { value: '未关联', label: '暂不关联知识库' }]} aria-label="选择知识库（模拟）" /><span>只有已启用、已发布的文档可用于检索。</span></div>
        <div className="proto-chat-config-actions"><Button type="primary" onClick={() => setView('对话体验')}>查看对话体验 <ArrowRight size={14}/></Button><span>配置仅保留在此原型当前页面中</span></div>
      </div>
      <aside className="proto-chat-readiness"><h2>使用前检查</h2><p>基于本页的模拟配置展示，不能代表真实连通状态。</p><div className="proto-chat-readiness-item">{modelSelected ? <CircleCheck size={17}/> : <CircleAlert size={17}/>}<div><strong>{modelSelected ? '已选择示例模型' : '尚未选择模型'}</strong><span>是否能调用仍以实际配置和调用结果为准</span></div></div><div className="proto-chat-readiness-item">{knowledgeLinked ? <CircleCheck size={17}/> : <CircleAlert size={17}/>}<div><strong>{knowledgeLinked ? '已关联示例知识库' : '尚未关联知识库'}</strong><span>{knowledgeLinked ? '演示中假设有 3 份已发布文档' : '没有关联时无法从知识库检索资料'}</span></div></div><p>模型连接由管理员在模型服务中维护。</p></aside>
    </div> : <div className="proto-chat-workspace">
      <aside className="proto-chat-sidebar"><div className="proto-chat-sidebar-label">当前助手</div><div className="proto-chat-assistant"><span><Bot size={19}/></span><div><strong>通用知识助手</strong><small>回答企业知识问题</small></div></div>{role !== 'user' && <Button block icon={<Settings2 size={15}/>} onClick={() => setView('助手配置')}>查看助手配置</Button>}<div className="proto-chat-sidebar-label proto-chat-side-gap">本次对话范围</div><div className="proto-chat-scope"><Database size={15}/><div><strong>{knowledgeLinked ? '员工制度库' : '未关联知识库'}</strong><small>{knowledgeLinked ? '3 份已发布 · 模拟' : '请先关联知识库'}</small></div></div><div className="proto-chat-scope"><Sparkles size={15}/><div><strong>{modelSelected ? '示例对话模型' : '未选择模型'}</strong><small>实际可用性尚未检测</small></div></div><div className="proto-chat-side-note"><BookOpen size={16}/><span>在正式使用时，可通过来源检查回答依据。</span></div></aside>
      <div className="proto-chat-conversation"><header className="proto-chat-top"><div><strong>通用知识助手</strong><span>模型与知识范围可在左侧查看</span></div><Tag color="blue">原型演示</Tag></header>
        {(!knowledgeLinked || !modelSelected) && <div className="proto-chat-setup-alert"><Alert type="warning" showIcon title={!modelSelected ? '助手尚未选择模型' : '助手尚未关联知识库'} description="这只是模拟的配置状态；完成相关配置后才能进行真实知识问答。" action={<Button size="small" onClick={() => setView('助手配置')}>查看配置</Button>} /></div>}
        <div className="proto-chat-scenarios"><span>选择要查看的示例状态</span><Segmented value={scenario} onChange={value => setScenario(value as Scenario)} options={['引用示例', '未找到依据', '模型调用失败']} aria-label="选择模拟结果" /></div>
        <div className="proto-chat-messages" aria-live="polite">{messages.length === 0 ? <div className="proto-chat-welcome"><span className="proto-chat-welcome-icon"><Sparkles size={26}/></span><h2>从一个问题开始</h2><p>选择上方示例状态，再输入问题或点击下方示例，查看拟议交互。</p><button onClick={() => send('新员工如何申请年假？')}><MessageSquare size={16}/>新员工如何申请年假？<ArrowRight size={15}/></button></div> : messages.map((item, index) => <div className="proto-chat-turn" key={index}><div className="proto-chat-user-message"><span>你 · 模拟提问</span><p>{item.question}</p></div><div className="proto-chat-reply"><span className="proto-chat-reply-avatar"><Bot size={17}/></span><div className="proto-chat-reply-body"><strong>通用知识助手 <small>模拟回答</small></strong>{item.scenario === '引用示例' ? <><p>示例：请在内部系统提交年假申请，并由直属负责人审核。具体天数与条件请以正式制度为准。</p><button className="proto-chat-citation" onClick={() => setSourceOpen(true)}><FileText size={15}/><span>模拟来源 · 员工休假制度.pdf · 第 2 页</span><ArrowRight size={14}/></button></> : item.scenario === '未找到依据' ? <><p>示例：暂未找到足够的资料依据，无法确定答案。</p><div className="proto-chat-result-hint">可以确认资料是否已发布、调整提问，或联系知识管理员。</div><span className="proto-muted">请联系知识管理员检查资料。</span></> : <><p>示例：模型本次未能完成调用。</p><div className="proto-chat-result-hint">模拟原因：模型请求 ID 无效。请管理员核对服务商目录中的请求 ID，并查看详细错误。</div><span className="proto-muted">请联系管理员检查模型配置。</span></>}</div></div></div>)}</div>
        <div className="proto-chat-composer"><Input.TextArea value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(draft); } }} autoSize={{ minRows: 2, maxRows: 4 }} placeholder="输入一个问题，查看所选模拟状态…" aria-label="输入模拟问题"/><div><span>模拟演示，不发送任何内容</span><Button type="primary" icon={<ArrowUp size={16}/>} disabled={!draft.trim()} onClick={() => send(draft)}>发送</Button></div></div>
      </div>
    </div>}
    <Drawer title="模拟来源" open={sourceOpen} onClose={() => setSourceOpen(false)} size={480}><div className="proto-chat-source"><div className="proto-chat-source-title"><FileText size={23}/><div><strong>员工休假制度.pdf</strong><span>第 2 页 · 以下为虚构示例</span></div></div><div className="proto-chat-source-excerpt">员工申请年假时，应在内部系统提交申请，并经直属负责人审核。具体可休天数及适用条件以正式公布的制度为准。</div><p>正式对话中，此处将展示实际召回的资料片段与已有位置。不同文件的可定位程度可能不同。</p></div></Drawer>
  </section>;
}
