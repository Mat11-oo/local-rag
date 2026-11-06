import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Drawer, Empty, Input, Popconfirm, Select, Tag, Tooltip } from 'antd';
import { ArrowLeft, ArrowUp, BookOpen, Bot, Check, ChevronRight, Copy, Database, FileText, MessageSquare, PanelLeft, Plus, RotateCcw, Sparkles, Square, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../markdown';
import { formatTime, now, uid, useWorkspace } from '../store';
import { api, apiHeaders } from '../api';
import RunDetail from './RunDetail';
import type { ChatMessage, ChatSession, Citation } from '../types';
import './chat.css';

export default function Chat() {
  const { state, updateState, activeAssistantId, setActiveAssistantId, activeSessionId, setActiveSessionId, role, navigate, refresh, flush } = useWorkspace();
  const { message } = App.useApp();
  const [sessionId, setSessionId] = useState<string | null>(activeSessionId);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [stage, setStage] = useState('');
  const [source, setSource] = useState<Citation | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [live, setLive] = useState<ChatSession | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [traceView,setTraceView]=useState<string|null>(null);
  const [activeRun,setActiveRun]=useState<string|null>(null);
  const sessionIdRef = useRef(activeSessionId);
  const abort = useRef<AbortController | null>(null);
  const runId = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const assistant = state.assistants.find(item => item.id === activeAssistantId) || state.assistants[0];
  const saved = state.sessions.find(item => item.id === sessionId && item.assistantId === assistant?.id);
  const session = live?.id === sessionId && live.assistantId === assistant?.id ? live : saved;
  const messages = session?.messages || [];
  const histories = state.sessions.filter(item => item.assistantId === assistant?.id).sort((a, b) => (b.messages.at(-1)?.createdAt || b.createdAt).localeCompare(a.messages.at(-1)?.createdAt || a.createdAt));
  const associated = state.knowledgeBases.filter(item => assistant?.kbIds.includes(item.id));
  const model = state.models.find(item => item.id === assistant?.modelId);
  const provider = state.providerConfigs.find(item => item.id === model?.providerConfigId);
  const isSimple=!assistant?.type||assistant.type==='simple';
  const configurationIssue = !isSimple?'':!model?.modelId?.trim() ? '当前应用的语言模型尚未填写具体模型 ID。请在工具与模型中配置聊天型号，再用于此应用。' : provider?.credentialError || (model.status === 'failed' ? model.lastError : '');

  useEffect(() => () => { abort.current?.abort(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages.length, messages.at(-1)?.content]);
  useEffect(() => { if (assistant && assistant.id !== activeAssistantId) setActiveAssistantId(assistant.id); }, [assistant, activeAssistantId, setActiveAssistantId]);
  useEffect(() => { if (!streaming && saved?.messages.at(-1)?.traceId) setLive(null); }, [streaming, saved]);
  useEffect(() => {
    if (activeSessionId === sessionIdRef.current) return;
    abort.current?.abort();
    runId.current++;
    sessionIdRef.current = activeSessionId;
    setSessionId(activeSessionId);
    setStreaming(false);
    setLive(null);
    setDraft('');
  }, [activeSessionId]);

  const stop = () => {if(!isSimple&&activeRun)void api(`/api/runs/${activeRun}/cancel`,{method:'POST'}).catch(error=>message.error(error.message));abort.current?.abort();};
  const switchSession = (id: string | null) => {
    stop(); runId.current++; setStreaming(false); setLive(null);
    sessionIdRef.current = id; setSessionId(id); setActiveSessionId(id);
    setDraft(''); setHistoryOpen(false);
  };
  const changeAssistant = (id: string) => {
    switchSession(state.sessions.find(item => item.assistantId === id)?.id || null);
    setActiveAssistantId(id);
  };
  const startNew = () => {
    if (!assistant) return;
    const id = uid();
    updateState(previous => ({ ...previous, sessions: [{ id, assistantId: assistant.id, title: '新对话', messages: [], createdAt: now() }, ...previous.sessions] }));
    switchSession(id);
  };
  async function sendQuestion(question: string, retry = false) {
    const text = question.trim();
    if (!text || !assistant || streaming) return;
    if (isSimple&&!assistant.kbIds.length) { message.warning('当前应用尚未关联知识库，请先在应用中心完成配置'); return; }
    if (isSimple&&!model?.modelId?.trim()) { message.warning('当前应用尚未选择具体聊天型号，请管理员先配置语言模型'); return; }
    if (isSimple&&provider?.credentialError) { message.error(provider.credentialError); return; }
    if (isSimple&&!model?.hasKey) { message.warning('请管理员先在工具与模型中保存语言模型密钥并检测连接'); return; }
    if (isSimple&&!state.settings?.allowExternalProcessing) { message.warning('尚未允许云端处理，请管理员先确认并开启'); return; }
    const run = ++runId.current;
    const controller = new AbortController(); abort.current = controller;
    setStreaming(true); setStage('正在连接模型'); setDraft('');
    try {
      await flush();
      const response = await fetch('/api/chat/stream', { method: 'POST', headers: { ...apiHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ assistantId: assistant.id, sessionId: session?.id, question: text, retry }), signal: controller.signal });
      if (!response.ok) { const data = await response.json(); throw new Error(typeof data.detail === 'string' ? data.detail : '对话请求失败'); }
      if (!response.body) throw new Error('浏览器不支持流式响应');
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let responseId = '';
      while (true) {
        const part = await reader.read(); if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true }); let boundary = buffer.indexOf('\n\n');
        while (boundary >= 0) {
          const packet = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const event = packet.split('\n').find(line => line.startsWith('event: '))?.slice(7);
          const raw = packet.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
          if (raw && run === runId.current) {
            const data = JSON.parse(raw);
            if (event === 'meta') {
              setActiveRun(data.traceId);
              responseId = data.messageId; sessionIdRef.current = data.session.id;
              setSessionId(data.session.id); setActiveSessionId(data.session.id); setLive(data.session);
            } else if (event === 'token') {
              setLive(previous => previous ? { ...previous, messages: previous.messages.map(item => item.id === responseId ? { ...item, content: item.content + data.delta } : item) } : previous);
            } else if (event === 'stage') setStage(data.name);
            else if (event === 'error') message.error(data.message);
          }
          boundary = buffer.indexOf('\n\n');
        }
      }
    } catch (error) { if ((error as Error).name !== 'AbortError') message.error((error as Error).message); }
    finally { if (run === runId.current) { setStreaming(false); abort.current = null; await refresh(); } }
  }
  const copyAnswer = async (item: ChatMessage) => {
    try { await navigator.clipboard.writeText(item.content); setCopiedId(item.id); message.success('已复制回答'); }
    catch { message.info('请选中文字复制'); }
  };
  const feedback = (id: string, value: 'up' | 'down') => updateState(previous => ({ ...previous, sessions: previous.sessions.map(item => item.id !== sessionId ? item : { ...item, messages: item.messages.map(chat => chat.id !== id ? chat : { ...chat, feedback: chat.feedback === value ? undefined : value }) }) }));
  const lastQuestion = [...messages].reverse().find(item => item.role === 'user')?.content;
  if (!assistant) return <div className="zh-chat-empty"><Empty description="还没有可用的业务应用">{role !== 'user' && <Button type="primary" onClick={() => navigate('assistants')}>创建应用</Button>}</Empty></div>;

  const historyContents = <>
    <button className="chat-back" onClick={() => { setHistoryOpen(false); navigate('overview'); }}><ArrowLeft size={15} />返回工作台</button>
    <div className="chat-history-heading"><span className="chat-mini-label">当前应用</span><Tag variant="filled" color="blue">{assistant.type==='agent'?'Agent':assistant.type==='chatflow'?'Chat Flow':'简易应用'}</Tag></div>
    <Select aria-label="选择业务应用" className="chat-assistant-select" value={assistant.id} onChange={changeAssistant} options={state.assistants.map(item => ({ value: item.id, label: item.name }))} />
    <Button className="chat-new-button" type="primary" ghost icon={<Plus size={16} />} onClick={startNew}>新建对话</Button>
    <div className="chat-mini-label chat-history-label">最近对话<span>{histories.length}</span></div>
    <div className="chat-history-list">{histories.length ? histories.map(item => <div key={item.id} className={`chat-history-item ${sessionId === item.id ? 'is-active' : ''}`}><button className="chat-history-select" onClick={() => switchSession(item.id)} aria-current={sessionId === item.id ? 'true' : undefined}><MessageSquare size={15} /><span>{item.title}</span></button><Popconfirm title="删除这段对话？" okText="删除" cancelText="取消" onConfirm={() => { if (sessionId === item.id) switchSession(null); updateState(previous => ({ ...previous, sessions: previous.sessions.filter(session => session.id !== item.id) })); }}><Button type="text" size="small" aria-label={`删除对话：${item.title}`} icon={<Trash2 size={13} />} /></Popconfirm></div>) : <p className="chat-history-empty">在这里提出问题，让团队知识为你所用。</p>}</div>
    <div className="chat-history-foot"><BookOpen size={16} /><div>答案有据可查<span>关联知识库中的已发布资料</span></div></div>
  </>;
  return <div className="chat-shell">
    <aside className="chat-history">{historyContents}</aside>
    <section className="chat-main">
      <header className="chat-topbar"><button className="chat-mobile-history" onClick={() => setHistoryOpen(true)} aria-label="打开对话历史"><PanelLeft size={20} /></button><div className="chat-current-assistant"><div className="chat-bot-icon"><Bot size={20} /></div><div><strong>{assistant.name}</strong><span><i className={`chat-model-status ${model?.status === 'connected' ? 'is-ready' : ''}`} />{model?.name || '未选择模型'}<span className="chat-separator">·</span>{associated.length} 个知识库</span></div></div><Tag variant="filled" color={model?.status === 'connected' ? 'green' : 'orange'}>{model?.status === 'connected' ? '模型已连接' : '模型待配置'}</Tag>{role !== 'user' && <Button className="chat-manage-app" type="text" size="small" onClick={() => navigate('assistants')}>管理应用<ChevronRight size={13} /></Button>}</header>
      {isSimple&&!assistant.kbIds.length && <div className="chat-configuration-notice"><Alert type="warning" showIcon title="此应用尚未关联知识库" description="关联知识库并发布资料后，才能进行知识问答。" action={role !== 'user' ? <Button size="small" onClick={() => navigate('assistants')}>配置应用</Button> : undefined} /></div>}
      {configurationIssue && <div className="chat-configuration-notice"><Alert type="warning" showIcon title="当前对话模型需要处理" description={configurationIssue} action={role === 'admin' ? <Button size="small" onClick={() => navigate('models')}>处理模型配置</Button> : undefined} /></div>}
      <div className="chat-conversation" aria-live="polite" aria-busy={streaming}>
        {!messages.length ? <div className="chat-welcome"><div className="chat-welcome-symbol"><Bot size={31} strokeWidth={1.7} /></div><span className="chat-welcome-label">{assistant.name}</span><h1>你好，有什么可以帮你？</h1><p>{assistant.welcome}</p><div className="chat-kb-chips">{associated.map(kb => <span key={kb.id}><Database size={13} />{kb.name}</span>)}</div>{isSimple&&(!model?.hasKey || !state.settings?.allowExternalProcessing) && <Alert className="chat-setup-notice" type="info" showIcon title="先连接你的模型服务" description="生成回答需要保存语言模型密钥、检测连接，并由管理员开启云端处理。" action={role === 'admin' ? <Button size="small" onClick={() => navigate('models')}>配置模型</Button> : undefined} />}<div className="chat-example-list">{assistant.examples.map((example, index) => <button key={index} onClick={() => void sendQuestion(example)} disabled={streaming}><span><MessageSquare size={16} />{example}</span><ChevronRight size={15} /></button>)}</div></div> : <div className="chat-message-list">{messages.map((item, index) => <article key={item.id} className={`chat-message chat-message-${item.role}`}>
          <div className={`chat-message-avatar ${item.role === 'assistant' ? 'is-bot' : ''}`}>{item.role === 'assistant' ? <Bot size={18} /> : '我'}</div><div className="chat-message-body"><div className="chat-message-name">{item.role === 'assistant' ? assistant.name : '你'}<time>{formatTime(item.createdAt)}</time></div><div className="chat-message-content">{item.content ? <ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown> : <div className="chat-typing"><i /><i /><i /><span>{streaming ? stage : '等待服务器保存结果…'}</span></div>}</div>
          {!!item.citations?.length && <div className="chat-citations"><span className="chat-citations-label"><BookOpen size={13} />参考来源 · {item.citations.length}</span>{item.citations.map(citation => <button key={`${citation.documentId}-${citation.id}`} onClick={() => setSource(citation)}><span className="chat-citation-number">{citation.id}</span><FileText size={13} /><span>{citation.name}</span><ChevronRight size={13} /></button>)}</div>}
          {item.role === 'assistant' && item.traceId && <div className="chat-message-bottom"><div className="chat-answer-actions"><Button type="text" size="small" aria-label="查看运行链路" onClick={()=>setTraceView(item.traceId||null)}>链路</Button><Tooltip placement="bottom" title="复制回答"><Button type="text" size="small" aria-label="复制回答" onClick={() => void copyAnswer(item)} icon={copiedId === item.id ? <Check size={14} /> : <Copy size={14} />} /></Tooltip><Button type="text" size="small" aria-label="回答有帮助" className={item.feedback === 'up' ? 'is-selected' : ''} icon={<ThumbsUp size={14} />} onClick={() => feedback(item.id, 'up')} /><Button type="text" size="small" aria-label="回答需要改进" className={item.feedback === 'down' ? 'is-selected' : ''} icon={<ThumbsDown size={14} />} onClick={() => feedback(item.id, 'down')} />{index === messages.length - 1 && lastQuestion && <Button type="text" size="small" aria-label="重新生成回答" disabled={streaming} icon={<RotateCcw size={14} />} onClick={() => void sendQuestion(lastQuestion, true)} />}</div><span className="chat-answer-usage">{item.stopped ? '已停止 · ' : ''}{!isSimple?'用量见运行链路':typeof item.tokens === 'number' ? `${item.tokens} Token` : '服务商未返回 Token'}{typeof item.duration === 'number' ? ` · ${item.duration.toFixed(2)}s` : ''}</span></div>}</div>
        </article>)}<div ref={end} /></div>}
      </div>
      <div className="chat-composer-wrap">{streaming && <Button className="chat-stop-button" size="small" icon={<Square size={12} />} onClick={stop}>停止生成</Button>}<div className="chat-composer"><Input.TextArea value={draft} onChange={event => setDraft(event.target.value)} autoSize={{ minRows: 1, maxRows: 5 }} maxLength={3000} placeholder={associated.length ? '向企业知识提问，或描述你需要完成的事…' : '描述你需要完成的事…'} aria-label="输入你的问题" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendQuestion(draft); } }} /><div className="chat-composer-bottom"><span><Database size={13} />{associated.length ? `${associated.length} 个知识库已关联` : isSimple?'待关联知识库':assistant.type==='chatflow'?'使用已发布流程':'按应用授权执行'}</span><div><span className="chat-enter-hint">Enter 发送，Shift + Enter 换行</span><Button type="primary" shape="circle" aria-label="发送问题" icon={<ArrowUp size={19} />} disabled={!draft.trim() || streaming} onClick={() => void sendQuestion(draft)} /></div></div></div><p className="chat-disclaimer">输出来自当前应用执行，请结合来源与运行链路核对。</p></div>
    </section>
    <RunDetail runId={traceView} onClose={()=>setTraceView(null)}/>
    <Drawer className="chat-history-drawer" title="应用与对话" open={historyOpen} onClose={() => setHistoryOpen(false)} placement="left" size={280} destroyOnHidden><div className="chat-mobile-history-content">{historyContents}</div></Drawer>
    <Drawer title={<span className="chat-source-heading"><BookOpen size={18} />知识来源</span>} open={!!source} onClose={() => setSource(null)} size={560}>{source && <div className="chat-source"><div className="chat-source-file"><FileText size={24} /><div><strong>{source.name}</strong><span>{source.page ? `第 ${source.page} 页` : source.sheet ? `工作表 ${source.sheet}` : source.title}</span></div></div><Button href={`/api/documents/${source.documentId}/file${source.page ? `#page=${source.page}` : ''}`} target="_blank" rel="noopener noreferrer">打开原始文件</Button><h2>{source.title}</h2>{source.imageUrl && <figure className="demo-source-image"><img src={source.imageUrl} alt="上传文件中的原图" /></figure>}<div className="chat-source-excerpt"><ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>{source.text}</ReactMarkdown></div><div className="chat-source-note">来源为本次检索实际命中的已发布分段。图片理解为模型生成描述，需结合原图核对。</div></div>}</Drawer>
  </div>;
}
