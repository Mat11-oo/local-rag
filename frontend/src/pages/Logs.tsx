import { cardAction } from '../cardAction';
import { useMemo, useState } from 'react';
import { App, Button, Collapse, DatePicker, Descriptions, Drawer, Empty, Input, Select, Table, Tabs, Tag, Timeline, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ArrowDownToLine, ArrowRight, Check, CircleAlert, Clock3, Copy, FileText, Layers, MessageSquare, Search, Timer, Zap } from 'lucide-react';
import CaseCollect from './CaseCollect';
import type { CaseSource } from '../evaluation-types';
import type { LogRecord } from '../types';
import { formatTime, useWorkspace } from '../store';
import './model-logs.css';

type AuditRow = Omit<LogRecord, 'status'> & { status: LogRecord['status'] | 'processing'; taskProgress?: number };
const statusLabels = { success: '成功', failed: '失败', stopped: '已停止', processing: '处理中' };
const statusColors = { success: 'green', failed: 'red', stopped: 'default', processing: 'blue' };
const durationLabel = (seconds: number) => seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(2)} s`;
const numberLabel = (value: number) => value.toLocaleString('zh-CN');
const tokenLabel = (value: number | null) => value == null ? '未返回' : numberLabel(value);
const totalTokenLabel = (row: AuditRow) => {
  if (row.kind === 'import') return '—';
  if (row.inputTokens == null && row.outputTokens == null) return '未返回';
  const knownTokens = (row.inputTokens ?? 0) + (row.outputTokens ?? 0);
  return row.inputTokens == null || row.outputTokens == null ? `${numberLabel(knownTokens)} + 未返回` : numberLabel(knownTokens);
};
function csvCell(value: string | number) { const safe = typeof value === 'string' && /^[=+\-@]/.test(value) ? `'${value}` : String(value); return `"${safe.replace(/"/g, '""')}"`; }

export default function Logs() {
  const[caseSource,setCaseSource]=useState<CaseSource|null>(null);
  const { state, role } = useWorkspace();
  const { message } = App.useApp();
  const [tab, setTab] = useState<'chat' | 'model' | 'import'>(role === 'knowledge' ? 'import' : 'chat');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [timeRange, setTimeRange] = useState<[number, number] | null>(null);
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const [page, setPage] = useState(1);
  const knowledgeRole = role === 'knowledge';
  const activeTab = knowledgeRole && tab === 'chat' ? 'import' : tab;
  const detailAllowed = !knowledgeRole || selected?.kind === 'import' || selected?.kind === 'model' && /^检索(测试|调试)/.test(selected.question);

  const rows = useMemo<AuditRow[]>(() => {
    const taskRows: AuditRow[] = state.tasks.map(task => ({ id: `import-${task.id}`, kind: 'import', question: task.name, answer: task.status === 'ready' ? '文档索引已经发布，知识可以被检索。' : task.error ?? `当前阶段：${task.stage}`, kbIds: [task.kbId], model: '文档解析流水线', provider: '本地', status: task.status === 'ready' || task.status === 'parsed' ? 'success' : task.status === 'failed' ? 'failed' : 'processing', inputTokens: 0, outputTokens: 0, duration: (task.stages||[]).reduce((sum,item)=>sum+item.duration,0), firstToken: 0, createdAt: task.createdAt, citations: [], error: task.error, taskProgress: task.progress, stages: (task.stages||[]).map(item=>({...item,status:item.status==='failed'?'failed' as const:'success' as const})) }));
    return [...state.logs, ...taskRows].filter(row => row.kind === activeTab).filter(row => !knowledgeRole || row.kind === 'import' || row.kind === 'model' && /^检索(测试|调试)/.test(row.question)).filter(row => status === 'all' || row.status === status).filter(row => !timeRange || new Date(row.createdAt).getTime() >= timeRange[0] && new Date(row.createdAt).getTime() <= timeRange[1]).filter(row => `${row.question} ${row.answer} ${row.model} ${row.provider} ${row.id} ${row.error ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [state.logs, state.tasks, activeTab, knowledgeRole, status, timeRange, query]);
  const totalTokens = rows.reduce((sum, row) => sum + (row.inputTokens??0) + (row.outputTokens??0), 0);
  const hasReturnedTokens = rows.some(row => row.kind !== 'import' && (row.inputTokens != null || row.outputTokens != null));
  const completed = rows.filter(row => row.status !== 'processing');
  const averageDuration = completed.length ? completed.reduce((sum, row) => sum + row.duration, 0) / completed.length : 0;
  const successRate = completed.length ? Math.round(completed.filter(row => row.status === 'success').length / completed.length * 100) : null;

  if (role === 'user') return <Empty description="日志检测器向管理员和知识管理员开放" />;

  const exportCsv = () => {
    if (!rows.length) { message.info('当前筛选条件下没有可导出的日志'); return; }
    const content = '\uFEFF' + [['请求 ID', '类型', '时间', '状态', '问题或任务', '回答或结果', '模型', '服务商', '输入 Token（实际）', '输出 Token（实际）', '耗时秒（实际）'], ...rows.map(row => [row.id, row.kind, formatTime(row.createdAt), statusLabels[row.status], row.question, row.answer, row.model, row.provider, row.kind === 'import' ? '不适用' : row.inputTokens??'未返回', row.kind === 'import' ? '不适用' : row.outputTokens??'未返回', row.duration])].map(line => line.map(csvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a'); link.href = url; link.download = `Local-RAG-运行日志-${activeTab}-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); message.success(`已导出当前筛选的 ${rows.length} 条运行日志`);
  };
  const copyId = async (id: string) => { try { await navigator.clipboard.writeText(id); message.success('请求 ID 已复制'); } catch { message.info('浏览器不支持复制，请直接选择请求 ID'); } };
  const columns: ColumnsType<AuditRow> = [
    { title: activeTab === 'import' ? '文档 / 任务' : activeTab === 'model' ? '调用内容' : '对话内容', dataIndex: 'question', key: 'question', width: '32%', render: (value: string, row) => <button className="log-question" onClick={() => setSelected(row)}><span className="log-row-icon">{activeTab === 'import' ? <FileText size={16} /> : activeTab === 'model' ? <Zap size={16} /> : <MessageSquare size={16} />}</span><span><strong title={value}>{value}</strong><small>{activeTab === 'import' ? state.knowledgeBases.find(kb => kb.id === row.kbIds[0])?.name ?? '知识库已删除' : state.assistants.find(assistant => assistant.id === row.assistantId)?.name ?? row.provider}</small></span></button> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (value: AuditRow['status']) => <Tag color={statusColors[value]}>{statusLabels[value]}</Tag> },
    { title: activeTab === 'import' ? '处理方式' : '模型', dataIndex: 'model', key: 'model', ellipsis: true, render: (value: string) => <span className="log-model-name">{value}</span> },
    { title: <Tooltip title="Token来自服务商实际返回；本地导入不统计Token">Token · 实际</Tooltip>, key: 'tokens', width: 145, render: (_, row) => <Tooltip title={row.kind === 'import' ? '本地导入不统计Token' : `输入：${tokenLabel(row.inputTokens)}；输出：${tokenLabel(row.outputTokens)}`}><span className={row.kind === 'import' || row.inputTokens == null && row.outputTokens == null ? 'muted' : 'log-numeric'}>{totalTokenLabel(row)}</span></Tooltip> },
    { title: '耗时 · 实际', dataIndex: 'duration', key: 'duration', width: 115, render: (value: number, row) => <span className="log-numeric">{row.status === 'processing' ? '处理中' : durationLabel(value)}</span> },
    { title: '时间', dataIndex: 'createdAt', key: 'createdAt', width: 130, render: (value: string) => <span className="log-time">{formatTime(value)}</span>, sorter: (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime() },
    { title: '', key: 'detail', width: 64, render: (_, row) => <Button type="text" aria-label={`查看${row.question}的日志详情`} icon={<ArrowRight size={16} />} onClick={() => setSelected(row)} /> },
  ];
  const resetPagination = () => setPage(1);

  return <div className="page-body logs-page">
    <div className="page-heading"><div><div className="eyebrow">OBSERVABILITY</div><h1>运行日志</h1><p className="muted">从一次提问到每个处理环节，让知识服务有迹可循。</p></div><Button icon={<ArrowDownToLine size={16} />} onClick={exportCsv}>导出当前结果</Button></div>
    <div className="ml-demo-note"><CircleAlert size={16} /><span>{knowledgeRole ? '知识管理员仅可查看导入与检索调试日志。' : '记录实际调用与耗时；Token仅采用服务商返回值，未返回时显示“未返回”。'} </span><Tag>本地运行</Tag></div>
    <div className="logs-metric-grid"><div className="surface log-metric" {...cardAction(()=>{setStatus("all");resetPagination();document.getElementById("log-records")?.scrollIntoView({behavior:"smooth"});},"查看统计明细")}><div><span className="metric-label">当前记录</span><strong>{numberLabel(rows.length)}<small>条</small></strong></div><span className="log-metric-icon"><Layers size={20} /></span></div><div className="surface log-metric" {...cardAction(()=>{setTab("model");setStatus("all");resetPagination();document.getElementById("log-records")?.scrollIntoView({behavior:"smooth"});},"查看统计明细")}><div><Tooltip title="仅累加当前筛选结果中服务商已返回的输入、输出Token；未返回的部分不计入，不能代表完整消耗。"><span className="metric-label">累计 Token · 仅已返回值</span></Tooltip><strong>{activeTab === 'import' || !rows.length ? '—' : hasReturnedTokens ? numberLabel(totalTokens) : '未返回'}<small>{activeTab === 'import' ? '不统计' : hasReturnedTokens ? 'tokens' : ''}</small></strong></div><span className="log-metric-icon"><Zap size={20} /></span></div><div className="surface log-metric" {...cardAction(()=>{setStatus("all");resetPagination();document.getElementById("log-records")?.scrollIntoView({behavior:"smooth"});},"查看统计明细")}><div><span className="metric-label">平均耗时 · 实际</span><strong>{completed.length ? averageDuration.toFixed(2) : '—'}<small>秒 / 次</small></strong></div><span className="log-metric-icon"><Timer size={20} /></span></div><div className="surface log-metric" {...cardAction(()=>{setStatus("success");resetPagination();document.getElementById("log-records")?.scrollIntoView({behavior:"smooth"});},"查看统计明细")}><div><span className="metric-label">完成记录成功率</span><strong>{successRate === null ? '—' : successRate}<small>%</small></strong></div><span className="log-metric-icon green"><Check size={20} /></span></div></div>
    <div id="log-records" className="surface logs-table-surface">
      <Tabs activeKey={activeTab} onChange={value => { setTab(value as typeof tab); setStatus('all'); resetPagination(); }} items={knowledgeRole ? [{ key: 'import', label: '导入日志' }, { key: 'model', label: '检索调试' }] : [{ key: 'chat', label: '对话日志' }, { key: 'model', label: '模型调用' }, { key: 'import', label: '导入日志' }]} />
      <div className="logs-toolbar"><Input aria-label="搜索日志" prefix={<Search size={16} />} placeholder="搜索内容、模型或请求 ID" value={query} onChange={event => { setQuery(event.target.value); resetPagination(); }} allowClear style={{ width: 300 }} /><div className="logs-filters"><DatePicker.RangePicker aria-label="筛选日志时间" placeholder={['开始日期', '结束日期']} onChange={dates => { setTimeRange(dates?.[0] && dates?.[1] ? [dates[0].startOf('day').valueOf(), dates[1].endOf('day').valueOf()] : null); resetPagination(); }} /><Select aria-label="筛选日志状态" value={status} onChange={value => { setStatus(value); resetPagination(); }} style={{ width: 120 }} options={[{ value: 'all', label: '全部状态' }, { value: 'success', label: '成功' }, { value: 'failed', label: '失败' }, ...(activeTab === 'import' ? [{ value: 'processing', label: '处理中' }] : [{ value: 'stopped', label: '已停止' }])]} /></div></div>
      <Table<AuditRow> rowKey="id" columns={columns} dataSource={rows} scroll={{ x: 960 }} pagination={{ current: page, pageSize: 8, onChange: setPage, showSizeChanger: false, showTotal: total => `共 ${total} 条记录` }} locale={{ emptyText: <div className="log-empty"><Empty description={query || status !== 'all' || timeRange ? '没有符合条件的日志，请调整筛选条件' : activeTab === 'model' ? '尚无调用记录，可前往模型服务进行实际检测' : '尚无日志记录，完成一次导入或对话后将在这里展示'} /></div> }} />
    </div>
    <div className="model-footnote"><Clock3 size={15} /><span>日志保存在本地后端数据库，刷新页面或重启服务后可继续查看。</span></div>
    <Drawer open={!!selected && detailAllowed} title="调用详情" size={590} onClose={() => setSelected(null)} destroyOnHidden>
      {selected && detailAllowed && <div className="log-detail">{role==='admin'&&selected.kind==='chat'&&<Button style={{marginBottom:16}} onClick={()=>setCaseSource({sourceKind:'log',sourceId:selected.id})}>收录 Case</Button>}<div className="log-detail-heading"><Tag color={statusColors[selected.status]}>{statusLabels[selected.status]}</Tag><Tag>{selected.kind === 'chat' ? '对话日志' : selected.kind === 'model' ? '模型调用' : '导入日志'}</Tag><Tag>实际数据</Tag><span className="muted">{formatTime(selected.createdAt)}</span></div><div className="log-trace"><div><span className="muted">请求 ID</span><code>{selected.id}</code></div><Button aria-label="复制请求 ID" type="text" icon={<Copy size={15} />} onClick={() => copyId(selected.id)} /></div>
      <Descriptions size="small" column={2} items={[{ key: 'model', label: '模型 / 流水线', children: selected.model, span: 2 }, { key: 'provider', label: '服务商', children: selected.provider }, { key: 'duration', label: '耗时 · 实际', children: selected.status === 'processing' ? '处理中' : durationLabel(selected.duration) }, { key: 'input', label: '输入 Token', children: selected.kind === 'import' ? '不适用' : tokenLabel(selected.inputTokens) }, { key: 'output', label: '输出 Token', children: selected.kind === 'import' ? '不适用' : tokenLabel(selected.outputTokens) }, ...(selected.kind === 'chat' ? [{ key: 'first', label: '首字耗时', children: selected.firstToken == null ? '未返回' : durationLabel(selected.firstToken) }] : []), ...(selected.taskProgress !== undefined ? [{ key: 'progress', label: '处理进度', children: `${selected.taskProgress}%` }] : [])]} />
      {selected.error && <div className="log-error"><CircleAlert size={16} /><div><strong>异常信息</strong><p>{selected.error}</p></div></div>}
      <section className="log-detail-section"><h3>{selected.kind === 'import' ? '导入文件' : '输入内容'}</h3><div className="log-text-block question">{selected.question}</div></section>
      <section className="log-detail-section"><h3>{selected.kind === 'chat' ? '模型回答' : '处理结果'}</h3><div className="log-text-block">{selected.answer || '暂无结果'}</div></section>
      {selected.citations.length > 0 && <section className="log-detail-section"><h3>知识引用 <span>{selected.citations.length}</span></h3><Collapse size="small" items={selected.citations.map((citation, index) => ({ key: citation.id || `${index}`, label: <span className="log-citation-label"><FileText size={14} />{citation.name}<small>{citation.page ? `第 ${citation.page} 页` : citation.sheet ? citation.sheet : '知识片段'}</small></span>, children: <div className="log-citation-text"><strong>{citation.title}</strong><p>{citation.text}</p></div> }))} /></section>}
      <section className="log-detail-section"><h3>处理链路 <span>实际耗时</span></h3><Timeline items={selected.stages.map((stage, index) => ({ key: `${stage.name}-${index}`, color: stage.status === 'failed' ? 'red' : 'blue', content: <div className="log-stage"><span>{stage.name}</span><span>{durationLabel(stage.duration)}{stage.status === 'failed' && <Tag color="red">失败</Tag>}</span></div> }))} /></section>
      </div>}
    </Drawer>
    <CaseCollect source={caseSource} onClose={()=>setCaseSource(null)}/>
  </div>;
}
