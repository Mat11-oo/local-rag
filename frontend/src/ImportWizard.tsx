import { useEffect, useState } from 'react';
import { Alert, App, Button, Collapse, Empty, Form, Input, InputNumber, Modal, Progress, Radio, Select, Space, Spin, Steps, Switch, Tag, Upload } from 'antd';
import { ArrowRight, Check, CircleAlert, FileImage, FileSpreadsheet, FileText, Layers, RotateCcw, Settings2, UploadCloud, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from './api';
import './pages/knowledge.css';
import { DocumentMetadataPanel } from './DocumentMetadataPanel';
import { markdownComponents } from './markdown';
import { ParsingNotice } from './ParsingNotice';
import { uid, useWorkspace } from './store';
import type { Chunk, DocStatus, ImportTask } from './types';

interface PendingFile { id: string; file: Blob; name: string; type: string; size: number; documentId?: string; }
interface SplitOptions { mode: string; chunkSize: number; overlap: number; separator?: string; }
interface SplitPreview { chunks: Chunk[]; sourceFingerprint: string; options: SplitOptions; warnings?: string[]; }
interface PreviewSnapshot { key: string; entries: Record<string, SplitPreview>; errors: Record<string, string>; }
const splitMethods = [
  { value: 'structure', title: '标题与段落优先', description: '保留标题结构，依次按段落、句子拆分。' },
  { value: 'length', title: '固定长度切分', description: '按字符长度切分，适合结构较少的长文本。' },
  { value: 'paragraph', title: '按段落切分', description: '按空行划分段落，超长段落再细分。' },
  { value: 'separator', title: '自定义分隔符', description: '按指定标记划分内容，超长内容再细分。' },
];
const kindLabels = { text: '文本', table: '表格', image: '图片描述' };
const statusLabels: Record<DocStatus, string> = { ready: '已就绪', processing: '处理中', parsed: '待索引', failed: '处理失败' };
function Status({ value }: { value: DocStatus }) {
  return <Tag color={value === 'failed' ? 'error' : value === 'ready' ? 'green' : value === 'parsed' ? 'gold' : 'processing'}>{statusLabels[value]}</Tag>;
}
function DocumentIcon({ type }: { type: string }) {
  const Icon = ['png', 'jpg', 'jpeg', 'webp'].includes(type.toLowerCase()) ? FileImage : ['xlsx', 'xls', 'csv'].includes(type.toLowerCase()) ? FileSpreadsheet : FileText;
  return <Icon size={18} />;
}

export function ImportWizard() {
  const { state, importOpen, setImportOpen, activeKbId, setActiveKbId, navigate, role, refresh, flush, retryDocument } = useWorkspace();
  const { message } = App.useApp();
  const [step, setStep] = useState(0);
  const [kbId, setKbId] = useState(activeKbId || state.knowledgeBases[0]?.id || '');
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [uploadedIds, setUploadedIds] = useState<string[]>([]);
  const [taskIds, setTaskIds] = useState<string[]>([]);
  const [chunkSize, setChunkSize] = useState<number | null>(800);
  const [overlap, setOverlap] = useState<number | null>(100);
  const [mode, setMode] = useState('structure');
  const [separator, setSeparator] = useState('\\n\\n');
  const [ocr, setOcr] = useState(false);
  const [vision, setVision] = useState(false);
  const [metadataEnabled, setMetadataEnabled] = useState(true);
  const [metadataModelId, setMetadataModelId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [previewId, setPreviewId] = useState('');
  const [indexMode, setIndexMode] = useState<'keyword' | 'hybrid'>('keyword');
  const [previewSnapshot, setPreviewSnapshot] = useState<PreviewSnapshot>({ key: '', entries: {}, errors: {} });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [buildErrors, setBuildErrors] = useState<string[]>([]);
  const parametersLocked = busy || taskIds.length > 0;

  const selectedKb = state.knowledgeBases.find(kb => kb.id === kbId);
  const documents = state.documents.filter(doc => uploadedIds.includes(doc.id));
  const preview = documents.find(doc => doc.id === previewId) || documents[0];
  const parsed = documents.filter(doc => doc.chunks.length && doc.status !== 'processing' && !doc.error);
  const tasks = state.tasks.filter(task => taskIds.includes(task.id));
  const parsing = documents.some(doc => doc.status === 'processing');
  const canCloud = !!state.settings?.allowExternalProcessing;
  const metadataModels = state.models.filter(model => model.type === 'LLM' && model.modelId.trim() && model.hasKey && !state.providerConfigs.find(connection => connection.id === model.providerConfigId)?.credentialError);
  const effectiveMetadataModelId = metadataModels.find(model => model.id === metadataModelId)?.id ?? metadataModels.find(model => model.isDefault && model.status === 'connected')?.id ?? metadataModels.find(model => model.status === 'connected')?.id ?? metadataModels.find(model => model.isDefault)?.id ?? metadataModels[0]?.id;
  const canExtractMetadata = canCloud && !!effectiveMetadataModelId;
  const available = (type: string) => canCloud && state.models.some(model => model.type === type && model.hasKey && model.status === 'connected' && model.isDefault);
  const canEmbed = canCloud && state.models.some(model => model.id === selectedKb?.embeddingModelId && model.hasKey && model.status === 'connected');
  const decodedSeparator = separator.replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\r/g, '\r');
  const invalidSplit = chunkSize === null || !Number.isInteger(chunkSize) || chunkSize < 200 || chunkSize > 4000
    ? '分段长度须为 200–4000 的整数。'
    : overlap === null || !Number.isInteger(overlap) || overlap < 0 || overlap >= chunkSize
      ? '重叠长度须为非负整数，且小于分段长度。'
      : mode === 'separator' && (!decodedSeparator || decodedSeparator.length > 100)
        ? '请输入 1–100 个字符的分隔符。' : '';
  const splitOptions: SplitOptions = { mode, chunkSize: chunkSize ?? 800, overlap: overlap ?? 100, ...(mode === 'separator' ? { separator: decodedSeparator } : {}) };
  const splitKey = JSON.stringify(splitOptions);
  const sourceKey = JSON.stringify(documents.map(doc => [doc.id, doc.status, doc.contentFingerprint, doc.chunks.length, doc.error]));
  const requestKey = `${sourceKey}:${splitKey}`;
  const previewsCurrent = previewSnapshot.key === requestKey;
  const previewResult = preview ? previewSnapshot.entries[preview.id] : undefined;
  const previewError = preview ? previewSnapshot.errors[preview.id] : undefined;
  const previewUpdating = !invalidSplit && (previewLoading || !previewsCurrent);
  const chunks = previewResult?.chunks ?? preview?.chunks ?? [];
  const previewChars = chunks.reduce((total, chunk) => total + chunk.text.length, 0);
  const canBuild = !busy && !parsing && !invalidSplit && previewsCurrent && !previewLoading && parsed.length > 0
    && parsed.every(doc => !!previewSnapshot.entries[doc.id]) && (indexMode !== 'hybrid' || canEmbed);
  const unuploaded = files.filter(file => !file.documentId);

  useEffect(() => {
    if (importOpen && !uploadedIds.length) {
      setKbId(current => activeKbId || (state.knowledgeBases.some(kb => kb.id === current) ? current : state.knowledgeBases[0]?.id || ''));
    }
  }, [importOpen, activeKbId]);

  useEffect(() => {
    if (!importOpen || step !== 1 || invalidSplit) { setPreviewLoading(false); return; }
    const controller = new AbortController();
    setPreviewLoading(true);
    const timer = window.setTimeout(async () => {
      const sources = JSON.parse(sourceKey) as [string, DocStatus, string | undefined, number, string | undefined][];
      const results = await Promise.all(sources.filter(([, status, , count, error]) => status !== 'processing' && count > 0 && !error).map(async ([id]) => {
        try {
          const result = await api<SplitPreview>(`/api/documents/${id}/split-preview`, { method: 'POST', signal: controller.signal, body: splitKey });
          return { id, result, error: '' };
        } catch (error) { return { id, result: undefined, error: (error as Error).message }; }
      }));
      if (controller.signal.aborted) return;
      const entries: Record<string, SplitPreview> = {};
      const errors: Record<string, string> = {};
      for (const result of results) {
        if (result.result) entries[result.id] = result.result;
        else errors[result.id] = result.error;
      }
      setPreviewSnapshot({ key: `${sourceKey}:${splitKey}`, entries, errors });
      setPreviewLoading(false);
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [importOpen, step, sourceKey, splitKey, invalidSplit, previewRevision]);

  function addFile(file: Blob & { name: string; size: number }) {
    const type = file.name.split('.').pop()?.toLowerCase() || '';
    if (!['docx', 'pdf', 'md', 'txt', 'png', 'jpg', 'jpeg', 'webp', 'xlsx', 'xls', 'csv'].includes(type)) { message.error('不支持此格式，Word 请使用 DOCX'); return; }
    if (file.size === 0 || file.size > 50 * 1024 * 1024) { message.error('请选择非空且不超过 50 MB 的文件'); return; }
    setFiles(previous => previous.some(item => item.name === file.name) ? previous : [...previous, { id: uid(), file, name: file.name, type, size: file.size }]);
  }

  async function parse() {
    if (!selectedKb || !files.length || busy) return;
    setBusy(true);
    const ids = [...uploadedIds];
    try {
      await flush();
      for (const file of unuploaded) {
        try {
          const data = new FormData();
          data.append('file', file.file, file.name);
          data.append('options', JSON.stringify({ ...splitOptions, ocr, vision, metadata: metadataEnabled && canExtractMetadata, metadataModelId: effectiveMetadataModelId }));
          const result = await api<{ documentId: string; taskId: string }>(`/api/knowledge/${kbId}/upload`, { method: 'POST', body: data });
          ids.push(result.documentId);
          setFiles(previous => previous.map(item => item.id === file.id ? { ...item, documentId: result.documentId } : item));
        } catch (error) { message.error(`${file.name}：${(error as Error).message}`); }
      }
      if (ids.length) { setUploadedIds(ids); setPreviewId(current => current || ids[0]); await refresh(); setStep(1); }
    } finally { setBusy(false); }
  }

  async function build() {
    if (!canBuild) return;
    setBusy(true);
    const ids = [...taskIds];
    const errors: string[] = [];
    const submitted = new Set(tasks.map(task => task.docId));
    try {
      await flush();
      for (const doc of parsed.filter(doc => !submitted.has(doc.id))) {
        try {
          const task = await api<ImportTask>(`/api/documents/${doc.id}/build`, { method: 'POST', body: JSON.stringify({ indexMode, splitOptions, sourceFingerprint: previewSnapshot.entries[doc.id].sourceFingerprint }) });
          ids.push(task.id);
          setTaskIds([...ids]);
        } catch (error) { errors.push(`${doc.name}：${(error as Error).message}`); }
      }
      setBuildErrors(errors);
      await refresh();
      if (ids.length) setStep(2);
      else if (errors.length) { message.error(errors[0]); setPreviewRevision(value => value + 1); }
    } finally { setBusy(false); }
  }

  async function retry(docId: string) {
    const task = await retryDocument(docId);
    if (task && step === 2) setTaskIds(previous => [task.id, ...previous.filter(id => state.tasks.find(item => item.id === id)?.docId !== docId)]);
  }

  function resetImport() {
    setStep(0); setFiles([]); setUploadedIds([]); setTaskIds([]); setPreviewId(''); setBuildErrors([]);
    setPreviewSnapshot({ key: '', entries: {}, errors: {} });
  }

  const processingOptions = <>
    <div className="kh-parse-row"><div><strong>云端 OCR 识别</strong><p>扫描 PDF 和图片文字；{available('OCR') ? '默认 OCR 模型已就绪' : '须配置默认 OCR 模型并开启云端处理'}</p></div><Switch aria-label="启用云端OCR" checked={ocr && available('OCR')} disabled={busy || !!uploadedIds.length || !available('OCR')} onChange={setOcr} /></div>
    <div className="kh-parse-row"><div><strong>图片与图表理解</strong><p>理解照片、示意图与图表；{available('Vision') ? '默认视觉模型已就绪' : '须配置默认 Vision 模型并开启云端处理'}</p></div><Switch aria-label="启用图片理解" checked={vision && available('Vision')} disabled={busy || !!uploadedIds.length || !available('Vision')} onChange={setVision} /></div>
    <div className="kh-parse-row"><div><strong>自动构建文档元数据</strong><p>抽取时间、版本、主体、负责人、关键词和候选问题；{canExtractMetadata ? '使用所选 LLM 处理正文' : '配置 LLM 并允许云端处理后可用，也可解析后人工补充'}</p></div><Switch aria-label="自动构建文档元数据" checked={metadataEnabled && canExtractMetadata} disabled={busy || !!uploadedIds.length || !canExtractMetadata} onChange={setMetadataEnabled} /></div>
    {metadataEnabled && canExtractMetadata && <Form layout="vertical"><Form.Item label="元数据抽取模型"><Select aria-label="导入时的元数据抽取模型" disabled={busy || !!uploadedIds.length} value={effectiveMetadataModelId} onChange={setMetadataModelId} options={metadataModels.map(model => ({ value: model.id, label: `${model.name} · ${model.provider}` }))} /></Form.Item></Form>}
    <p className="kh-split-help">OCR、图片理解和元数据抽取会发送相应内容至配置的模型服务商，并可能产生费用。图片文件需启用 OCR 或图片理解。</p>
  </>;

  return <Modal open={importOpen && role !== 'user'} onCancel={() => setImportOpen(false)} width={step === 1 ? 1240 : 880} className={`kh-import-modal${step === 1 ? ' kh-import-workspace' : ''}`} title={<div className="kh-import-title"><span><UploadCloud size={21} /></span><div>导入知识<small>{step === 1 ? '左侧调整参数，右侧即时查看切分结果' : '真实上传、解析并构建知识索引'}</small></div></div>} footer={<div className="kh-wizard-footer"><span className="muted">{step === 1 ? `当前参数应用于本次导入的 ${documents.length} 个文档` : '资料保存在本机，云端处理受管理员开关控制'}</span><Space wrap>
    {step === 0 && <Button type="primary" loading={busy} disabled={!files.length || !selectedKb} onClick={() => void parse()}>{uploadedIds.length && !unuploaded.length ? '返回参数与预览' : '下一步：参数与预览'}<ArrowRight size={14} /></Button>}
    {step === 1 && <><Button disabled={busy} onClick={() => setStep(0)}>上一步</Button><Button type="primary" loading={busy} disabled={!canBuild} onClick={() => void build()}>确认并构建索引{parsed.length > 0 ? `（${parsed.length}）` : ''}<ArrowRight size={14} /></Button></>}
    {step === 2 && <><Button onClick={() => { setImportOpen(false); navigate('tasks'); }}>查看导入任务</Button><Button onClick={resetImport}>继续导入</Button><Button type="primary" onClick={() => { setImportOpen(false); navigate('knowledge'); setActiveKbId(kbId); }}>返回知识库</Button></>}
  </Space></div>}>
    <Steps className="kh-import-steps" current={step} size="small" items={[{ title: '选择文件' }, { title: '参数设置与预览' }, { title: '构建知识' }]} />
    <div className="kh-wizard-content">
      {step === 0 && <>
        <label className="kh-field-label" htmlFor="import-knowledge-base">导入到知识库</label><Select id="import-knowledge-base" value={kbId || undefined} disabled={busy || !!uploadedIds.length} onChange={setKbId} style={{ width: '100%' }} placeholder="请先创建知识库" options={state.knowledgeBases.map(kb => ({ value: kb.id, label: kb.name }))} />
        <div className="kh-dropzone"><Upload.Dragger disabled={busy} multiple showUploadList={false} accept=".docx,.pdf,.md,.txt,.png,.jpg,.jpeg,.webp,.xlsx,.xls,.csv" beforeUpload={file => { addFile(file); return Upload.LIST_IGNORE; }}><span className="kh-upload-symbol"><UploadCloud size={30} /></span><h3>拖拽本地文件到这里，或<span>点击选择</span></h3><p>DOCX、PDF、Markdown、图片、XLSX / XLS、CSV</p><small>文件将保存至本机 · 单文件不超过 50 MB</small></Upload.Dragger></div>
        {files.map(file => <div className="kh-pending-file" key={file.id}><span className={`kh-file kh-file-${file.type}`}><DocumentIcon type={file.type} /></span><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(1)} KB</span><Tag>{file.documentId ? '已上传' : '待上传'}</Tag>{!file.documentId && <Button type="text" disabled={busy} aria-label={`移除${file.name}`} icon={<X size={14} />} onClick={() => setFiles(previous => previous.filter(item => item.id !== file.id))} />}</div>)}
        <Collapse className="kh-import-processing" items={[{ key: 'processing', label: '解析选项 · OCR、图片理解与元数据', children: processingOptions }]} />
        <Alert type="info" showIcon title="上传后直接进入参数与预览" description="文字、Word 和表格可在本地解析。切分方式、分段长度和索引方式可在下一步调整，并同时查看真实结果。" />
      </>}
      {step === 1 && <div className="kh-split-workspace">
        <aside className="kh-split-settings" aria-label="切分与索引参数">
          <div className="kh-split-panel-heading"><h3><Settings2 size={17} /> 参数设置</h3><p>调整后自动更新右侧预览</p></div>
          <h4 className="kh-split-section-title">切分方式</h4>
          {taskIds.length > 0 && <Alert type="info" showIcon title="已有文档提交构建" description="本次剩余文档沿用同一组参数。需要调整时，可在文档详情重新解析或构建。" />}
          <Radio.Group aria-label="切分方式" className="kh-split-methods" value={mode} disabled={parametersLocked} onChange={event => setMode(event.target.value)}>{splitMethods.map(method => <Radio key={method.value} value={method.value}><strong>{method.title}{method.value === 'structure' && <Tag color="blue">推荐</Tag>}</strong><small>{method.description}</small></Radio>)}</Radio.Group>
          <Form layout="vertical" disabled={parametersLocked}>
            {mode === 'separator' && <Form.Item label="自定义分隔符" validateStatus={!decodedSeparator || decodedSeparator.length > 100 ? 'error' : undefined} help="按字面文本匹配；支持 \\n 换行、\\t 制表符。"><Input aria-label="自定义分隔符" value={separator} onChange={event => setSeparator(event.target.value)} placeholder="例如：\\n\\n 或 ###" maxLength={200} /></Form.Item>}
            <div className="kh-split-number-fields"><Form.Item label="分段长度（字符）"><InputNumber aria-label="分段长度（字符）" min={200} max={4000} step={100} precision={0} value={chunkSize} onChange={setChunkSize} /></Form.Item><Form.Item label="重叠长度（字符）"><InputNumber aria-label="重叠长度（字符）" min={0} max={chunkSize ? chunkSize - 1 : 3999} precision={0} value={overlap} onChange={setOverlap} /></Form.Item></div>
          </Form>
          {invalidSplit && <Alert type="error" showIcon title={invalidSplit} />}
          <p className="kh-split-help">文本按所选策略切分；表格与图片描述保持完整。段落和自定义分隔符之间独立切分，重叠仅用于段内细分。</p>
          <h4 className="kh-split-section-title">索引方式</h4>
          <Radio.Group aria-label="索引方式" className="kh-index-methods" value={indexMode} disabled={parametersLocked} onChange={event => setIndexMode(event.target.value)}>
            <Radio value="keyword"><strong>关键词索引<Tag>本地</Tag></strong><small>按关键词匹配，无需模型，适合术语和编号检索。</small></Radio>
            <Radio value="hybrid" disabled={!canEmbed}><strong>关键词 + 向量索引<Tag color="blue">混合</Tag></strong><small>结合关键词与语义召回，需要 Embedding 模型。</small></Radio>
          </Radio.Group>
          {!canEmbed && <p className="kh-split-help">混合索引需配置此知识库的 Embedding 模型，并在模型服务中开启云端处理。</p>}
          {indexMode === 'hybrid' && <Alert type={canEmbed ? 'info' : 'warning'} showIcon title={canEmbed ? `向量模型：${state.models.find(model => model.id === selectedKb?.embeddingModelId)?.name}` : '向量模型当前不可用，请切换关键词索引或检查配置'} description="确认构建后，将把分段内容发送至该模型服务商进行向量化。" />}
        </aside>
        <section className="kh-split-preview" aria-label="切分数据预览" aria-busy={previewUpdating || parsing}>
          <div className="kh-split-preview-heading"><div><h3>数据预览</h3><p className="muted">{previewUpdating ? '正在按当前参数更新切分结果…' : parsing ? '文件正在解析，完成后自动展示' : '以下分段将用于构建所选索引'}</p></div><Select aria-label="选择预览文档" value={preview?.id} onChange={setPreviewId} options={documents.map(doc => ({ value: doc.id, label: doc.name }))} /></div>
          <div className="kh-split-preview-stats"><Tag color="blue">{chunks.length} 个分段</Tag><Tag>{previewChars.toLocaleString()} 字符</Tag><Tag>平均 {chunks.length ? Math.round(previewChars / chunks.length).toLocaleString() : 0} 字符 / 段</Tag>{previewUpdating ? <Spin size="small" /> : preview && <Status value={preview.status} />}</div>
          <div className="kh-split-preview-content">
            {unuploaded.length > 0 && <Alert type="warning" showIcon title={`${unuploaded.length} 个文件尚未上传成功`} description="可返回上一步重试；本次构建仅包含已上传且解析成功的文档。" />}
            {documents.some(doc => !!doc.error) && <Alert type="warning" showIcon title="部分文档解析失败" description="请切换文档查看原因并重试；仅解析成功的文档会参与本次构建。" />}
            {preview?.error && <Alert type="error" showIcon title="解析未完成" description={preview.error} action={<Button onClick={() => void retry(preview.id)}>重试</Button>} />}
            {previewError && previewsCurrent && <Alert type="error" showIcon title="切分预览失败" description={previewError} action={<Button onClick={() => setPreviewRevision(value => value + 1)}>重试预览</Button>} />}
            {previewsCurrent && Object.entries(previewSnapshot.errors).some(([id]) => id !== preview?.id) && <Alert type="warning" showIcon title="其他文档的切分预览失败" description="请切换文档查看错误，重试成功后再构建索引。" />}
            <ParsingNotice warnings={[...(preview?.parseWarnings ?? []), ...(previewResult?.warnings ?? [])]} />
            {invalidSplit && <Alert type="warning" showIcon title="参数尚未生效" description="请修正左侧参数，右侧将自动更新。当前显示上一次可用结果。" />}
            {preview && <Collapse className="kh-split-meta" items={[{ key: 'metadata', label: '文档元数据', children: <><p className="kh-split-help">更改切分后，原有元数据引用可能需要重新核对。构建后可在文档详情补充或重新抽取。</p><DocumentMetadataPanel document={preview} readOnly /></> }]} />}
            <div className={`kh-split-preview-list${previewUpdating || invalidSplit ? ' kh-split-preview-pending' : ''}`}>{chunks.map((chunk, index) => <article className="kh-chunk" key={chunk.id}><div className="kh-chunk-top"><Space size={8}><span className="kh-chunk-index">{String(index + 1).padStart(2, '0')}</span><Tag>{kindLabels[chunk.kind]}</Tag></Space><span className="muted">{chunk.text.length.toLocaleString()} 字符</span></div><h4>{chunk.title}</h4>{chunk.imageUrl && <figure className="demo-source-image"><img src={chunk.imageUrl} alt="已上传文件中的原图" /></figure>}<div className="kh-markdown"><ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>{chunk.text}</ReactMarkdown></div><div className="kh-chunk-foot"><span>{preview?.name}{chunk.sheet ? ` · ${chunk.sheet}` : chunk.page ? ` · 第 ${chunk.page} 页` : ''}</span><span>分段 {index + 1}</span></div></article>)}</div>
            {!chunks.length && <div className="kh-split-empty">{parsing || previewUpdating ? <><Spin /><p>正在读取文件并生成真实分段…</p></> : <Empty description="暂无可用内容，请检查文件解析结果" />}</div>}
          </div>
        </section>
      </div>}
      {step === 2 && <>
        <div className="kh-build-header"><span className={tasks.some(task => task.status === 'processing') ? 'processing' : tasks.some(task => task.status === 'failed') ? 'has-error' : ''}>{tasks.some(task => task.status === 'processing') ? <Layers size={27} /> : tasks.some(task => task.status === 'failed') ? <CircleAlert size={27} /> : <Check size={27} />}</span><h3>{tasks.some(task => task.status === 'processing') ? '正在构建知识索引' : tasks.some(task => task.status === 'failed') ? '部分任务需要处理' : '知识索引已就绪'}</h3><p>{splitMethods.find(method => method.value === mode)?.title} · {indexMode === 'hybrid' ? '关键词 + 向量索引' : '本地关键词索引'} · 进度来自后端任务</p></div>
        {!!buildErrors.length && <Alert type="error" showIcon title="部分文档未提交成功" description={<>{buildErrors.map(error => <div key={error}>{error}</div>)}</>} action={<Button onClick={() => { setStep(1); setPreviewRevision(value => value + 1); }}>返回预览重试</Button>} />}
        {tasks.map(task => <div className="kh-build-task" key={task.id}><div><strong>{task.name}</strong><Status value={task.status} /></div><Progress percent={task.progress} status={task.status === 'failed' ? 'exception' : task.status === 'ready' ? 'success' : 'active'} /><footer><span>{task.error || task.stage}</span>{task.status === 'failed' && <Button icon={<RotateCcw size={13} />} onClick={() => void retry(task.docId)}>重试</Button>}</footer></div>)}
      </>}
    </div>
  </Modal>;
}
