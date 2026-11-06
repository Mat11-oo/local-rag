import { useState } from 'react';
import { Alert, Button, Modal, Radio, Select, Steps, Switch, Tag } from 'antd';
import { ArrowLeft, ArrowRight, CheckCircle2, CircleAlert, Cloud, FileSpreadsheet, FileText, Image, LockKeyhole, Plus, RotateCw, Trash2, UploadCloud } from 'lucide-react';
import './import-prototype.css';

type Stage = 'pending' | 'parsed' | 'failed' | 'ready';
type DemoFile = { id: string; name: string; detail: string; stage: Stage };
const samples: DemoFile[] = [
  { id: 'policy', name: '员工手册（示例）.pdf', detail: 'PDF · 含扫描页和图片', stage: 'pending' },
  { id: 'table', name: '费用标准（示例）.xlsx', detail: '电子表格 · 多个工作表', stage: 'pending' },
  { id: 'guide', name: '报销指南（示例）.md', detail: 'Markdown · 文字文档', stage: 'pending' },
];
const states: Record<Stage, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'default' },
  parsed: { label: '解析完成 · 待构建', color: 'warning' },
  failed: { label: '解析失败', color: 'error' },
  ready: { label: '索引已发布', color: 'success' },
};

export default function ImportPrototype({ fixedKnowledge = false }: { fixedKnowledge?: boolean }) {
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<DemoFile[]>([]);
  const [duplicate, setDuplicate] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [ocr, setOcr] = useState(false);
  const [vision, setVision] = useState(false);
  const [metadata, setMetadata] = useState(false);
  const [index, setIndex] = useState<'keyword' | 'hybrid'>('keyword');
  const [selected, setSelected] = useState('');
  const [publicationNotice, setPublicationNotice] = useState(false);
  const preview = files.find(file => file.id === selected) || files[0];
  const parsedCount = files.filter(file => file.stage === 'parsed').length;
  const failedCount = files.filter(file => file.stage === 'failed').length;
  const readyCount = files.filter(file => file.stage === 'ready').length;
  const cloudEnabled = cloud && (ocr || vision || metadata || index === 'hybrid');

  function addSamples() {
    setFiles(current => {
      const existing = new Set(current.map(file => file.name));
      return [...current, ...samples.filter(file => !existing.has(file.name)).map(file => ({ ...file }))];
    });
  }
  function parseDemo() {
    setFiles(current => current.map((file, i) => ({ ...file, stage: i === 1 ? 'failed' : 'parsed' })));
    setSelected(files[0]?.id || '');
    setPublicationNotice(false);
    setStep(2);
  }
  function simulatePublish() {
    setFiles(current => current.map(file => file.stage === 'parsed' ? { ...file, stage: 'ready' } : file));
    setPublicationNotice(true);
  }
  function changeCloud(value: boolean) {
    setCloud(value);
    if (!value) { setOcr(false); setVision(false); setMetadata(false); setIndex('keyword'); }
  }
  return <section className="proto-imp" aria-label="导入知识交互原型">
    <header className="proto-imp-heading"><div><p className="proto-imp-eyebrow">KNOWLEDGE IMPORT</p><h1>导入知识</h1><p>把资料整理成可查阅、可引用的知识。</p></div><Tag color="blue">交互演示 · 不上传文件</Tag></header>
    <div className="proto-imp-shell">
      <div className="proto-imp-top"><div><strong>资料处理流程</strong><p>每一步都可查看处理范围与当前状态</p></div><span><LockKeyhole size={15} /> 示例内容，不连接真实服务</span></div>
      <Steps current={step} size="small" items={[{ title: '选择文件' }, { title: '处理设置' }, { title: '预览与发布' }]} />
      <div className="proto-imp-content">
        {step === 0 && <>
          <div className="proto-imp-title"><div><h2>选择需要导入的资料</h2><p>选择知识库并添加资料，系统会在下一步展示处理方式。</p></div><span>步骤 1 / 3</span></div>
          <label className="proto-imp-label" htmlFor="proto-imp-kb">目标知识库</label>
          <Select id="proto-imp-kb" value={fixedKnowledge ? 'policies' : undefined} defaultValue={fixedKnowledge ? undefined : 'team'} disabled={fixedKnowledge} style={{ width: '100%' }} options={[{ value: 'team', label: '团队知识库（示例）' }, { value: 'policies', label: '制度与流程（示例）' }]} />
          <div className="proto-imp-drop"><span><UploadCloud size={28} /></span><strong>选择演示文件，体验导入流程</strong><p>支持 DOCX、PDF、Markdown、图片和电子表格</p><Button icon={<Plus size={15} />} onClick={addSamples}>添加 3 个演示文件</Button><small>这是交互原型，不读取、上传或处理真实文件</small></div>
          <div className="proto-imp-list-heading"><strong>已选择文件 <span>{files.length}</span></strong><Button type="link" disabled={!files.length} onClick={() => setDuplicate(true)}>模拟添加同名文件</Button></div>
          {files.length === 0 ? <div className="proto-imp-empty">还没有选择文件，添加演示文件开始体验</div> : files.map(file => <div className="proto-imp-file" key={file.id}><span className="proto-imp-file-icon">{file.name.endsWith('.xlsx') ? <FileSpreadsheet size={18} /> : <FileText size={18} />}</span><div><strong>{file.name}</strong><small>{file.detail}</small></div><Tag>待处理</Tag><Button type="text" aria-label={`移除 ${file.name}`} icon={<Trash2 size={16} />} onClick={() => setFiles(current => current.filter(item => item.id !== file.id))} /></div>)}
        </>}
        {step === 1 && <>
          <div className="proto-imp-title"><div><h2>设置本次处理方式</h2><p>先了解哪些内容会被处理，再决定是否使用云服务。</p></div><span>步骤 2 / 3</span></div>
          <div className="proto-imp-summary"><div><CheckCircle2 size={18} /><span><strong>本地文字与表格解析</strong><small>读取文档中可提取的文字和表格</small></span></div><Tag color="success">默认进行</Tag></div>
          <div className="proto-imp-cloud"><div><Cloud size={19} /><span><strong>允许本次使用云端处理（演示）</strong><small>实际功能受管理员的云端处理设置控制。示意开关不改变真实设置。</small></span></div><Switch checked={cloud} onChange={changeCloud} aria-label="允许本次使用云端处理（演示）" /></div>
          <div className="proto-imp-options">
            <div><span className="proto-imp-option-icon"><FileText size={17} /></span><section><strong>OCR 文字识别</strong><p>识别扫描 PDF 和图片中的文字。</p><small>{!cloud ? '开启云端处理后可选择；实际需配置 OCR 模型' : '示例状态：实际使用时还需配置 OCR 模型'}</small></section><Switch checked={ocr} disabled={!cloud} onChange={setOcr} aria-label="OCR 文字识别" /></div>
            <div><span className="proto-imp-option-icon"><Image size={17} /></span><section><strong>图片与图表理解</strong><p>为照片、示意图与图表生成内容描述。</p><small>{!cloud ? '未开启时，不会理解图片和图表' : '示例状态：实际使用时还需配置视觉模型'}</small></section><Switch checked={vision} disabled={!cloud} onChange={setVision} aria-label="图片与图表理解" /></div>
            <div><span className="proto-imp-option-icon"><Plus size={17} /></span><section><strong>自动抽取文档元数据</strong><p>提取时间、版本、主体、负责人、关键词及可能的问题。</p><small>{!cloud ? '未开启时，可在解析后人工补充' : '示例状态：实际使用时还需配置语言模型'}</small></section><Switch checked={metadata} disabled={!cloud} onChange={setMetadata} aria-label="自动抽取文档元数据" /></div>
          </div>
          <div className="proto-imp-index"><div><h3>选择索引方式</h3><p>索引构建发布后，文档才可用于检索和问答。</p></div><Radio.Group value={index} onChange={event => setIndex(event.target.value)}><Radio value="keyword">关键词索引 <small>本地处理，适合编号和关键词</small></Radio><Radio value="hybrid" disabled={!cloud}>关键词 + 向量索引 <small>增加语义检索，需要云端 Embedding</small></Radio></Radio.Group></div>
          {cloudEnabled ? <Alert type="warning" showIcon title="所选云端能力会发送相应资料并可能产生费用" description={`本次选择：${[ocr && 'OCR 图片', vision && '视觉图片', metadata && '元数据正文', index === 'hybrid' && '向量化正文'].filter(Boolean).join('、')}。原型仅展示说明，不发起调用。`} /> : <Alert type="info" showIcon title="当前仅演示本地处理" description="未开启 OCR 或图片理解时，扫描件中的图片文字与图表可能无法进入知识库。" />}
        </>}
        {step === 2 && <>
          <div className="proto-imp-title"><div><h2>预览处理结果并发布</h2><p>解析完成不等于可检索，核对后还需构建索引。</p></div><span>步骤 3 / 3</span></div>
          <div className="proto-imp-counts"><span><b>{parsedCount}</b> 待构建</span><span><b>{failedCount}</b> 处理失败</span><span><b>{readyCount}</b> 已发布</span></div>
          <div className="proto-imp-preview-grid"><div className="proto-imp-preview-files"><strong>本次资料</strong>{files.map(file => <button key={file.id} className={preview?.id === file.id ? 'proto-imp-active' : ''} onClick={() => setSelected(file.id)}><FileText size={16} /><span>{file.name}<small>{states[file.stage].label}</small></span></button>)}</div>
            <div className="proto-imp-preview-main">{preview && <><div className="proto-imp-preview-head"><div><strong>{preview.name}</strong><small>{preview.detail}</small></div><Tag color={states[preview.stage].color}>{states[preview.stage].label}</Tag></div>
              {preview.stage === 'failed' ? <div className="proto-imp-failure"><CircleAlert size={21} /><div><strong>演示：解析失败</strong><p>示例原因：表格内容无法读取。若已有已发布版本，仍可继续检索旧版本。</p><Button icon={<RotateCw size={14} />} onClick={() => setFiles(current => current.map(file => file.id === preview.id ? { ...file, stage: 'parsed' } : file))}>模拟重新解析</Button></div></div> : <><div className="proto-imp-excerpt"><div><span>示例内容片段</span><Tag>本地文字</Tag></div><p>这里展示解析后的正文、表格与来源信息，供知识管理员在发布前核对。</p><small>此处为固定示例，不代表真实文件解析结果。</small></div><div className="proto-imp-metadata"><strong>文档元数据</strong><p>{metadata ? '已选择自动抽取；实际结果需结合模型调用并核对原文依据。' : '本次未开启自动抽取；可以在实际使用时手动补充。'}</p><div><Tag>时间</Tag><Tag>版本</Tag><Tag>主体</Tag><Tag>负责人</Tag><Tag>关键词</Tag><Tag>候选问题</Tag></div></div></>}
              {preview.stage === 'ready' && <Alert type="success" showIcon title="演示状态：索引已发布" description="原型不会创建实际索引或改变已有文档。" />}</>}
            </div></div>
          {publicationNotice && <Alert type="info" showIcon title="已更新演示状态" description="仅已解析的演示文件显示为已发布；失败文件保持原状，可以选择重新解析。" />}
        </>}
      </div>
      <footer className="proto-imp-footer"><span>{step === 0 ? '当前仅提供演示文件' : step === 1 ? `处理 ${files.length} 个演示文件` : '构建状态仅为演示'}</span><div>{step > 0 && <Button icon={<ArrowLeft size={14} />} onClick={() => setStep(step - 1)}>上一步</Button>}{step === 0 && <Button type="primary" disabled={!files.length} onClick={() => setStep(1)}>下一步：处理设置 <ArrowRight size={14} /></Button>}{step === 1 && <Button type="primary" onClick={parseDemo}>模拟解析并预览 <ArrowRight size={14} /></Button>}{step === 2 && <Button type="primary" disabled={!parsedCount} onClick={simulatePublish}>模拟发布已解析文件（{parsedCount}）<ArrowRight size={14} /></Button>}</div></footer>
    </div>
    <Modal open={duplicate} title="发现同名文件" onCancel={() => setDuplicate(false)} footer={<><Button onClick={() => setDuplicate(false)}>跳过同名文件</Button><Button type="primary" onClick={() => { const source = files[0]; if (source) setFiles(current => [...current, { ...source, id: `duplicate-${Date.now()}` }]); setDuplicate(false); }}>保留两个文件</Button></>}><p>演示：已存在“{files[0]?.name}”。同名文件可能来自不同目录，请选择跳过或保留。</p><p className="proto-imp-muted">仅影响当前演示列表，不会覆盖真实文档。</p></Modal>
  </section>;
}
