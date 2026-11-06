import { useState } from 'react';
import { Alert, Button, InputNumber, Radio, Select, Switch, Tag } from 'antd';
import { BookOpen, ChevronRight, CircleHelp, FileText, Scissors, ShieldCheck, Sparkles } from 'lucide-react';
import './quality-prototype.css';

type Assessment = 'yes' | 'no' | 'unset';
type ExampleCase = {id: string; question: string; category: string; regression: '通过' | '未通过' | '执行错误' | '未执行'; correct: Assessment; citations: Assessment; coverage: Assessment};
const exampleCases: ExampleCase[] = [
 {id:'case-01',question:'采购申请由谁审批？',category:'单文档事实',regression:'通过',correct:'yes',citations:'yes',coverage:'yes'},
 {id:'case-02',question:'哪些情况需要提交补充材料？',category:'表格问答',regression:'未通过',correct:'yes',citations:'no',coverage:'yes'},
 {id:'case-03',question:'新版流程从什么时候生效？',category:'时间与版本',regression:'通过',correct:'yes',citations:'unset',coverage:'unset'},
 {id:'case-04',question:'图片中有哪些风险提示？',category:'图片与图表',regression:'未执行',correct:'unset',citations:'unset',coverage:'unset'},
 {id:'case-05',question:'合同到期后怎样续签？',category:'异常处理',regression:'执行错误',correct:'unset',citations:'unset',coverage:'unset'},
];
const judgmentOptions = [{label:'符合',value:'yes'},{label:'不符合',value:'no'},{label:'未判定',value:'unset'}];

export default function QualityPrototype() {
 const [tab,setTab]=useState<'chunk'|'cases'>('chunk');
 const [chunkSize,setChunkSize]=useState<number|null>(800);
 const [overlap,setOverlap]=useState<number|null>(100);
 const [strategy,setStrategy]=useState('标题与段落');
 const [protectTable,setProtectTable]=useState(true);
 const [cases,setCases]=useState(exampleCases);
 const [selectedId,setSelectedId]=useState('case-01');
 const [selectedChunk,setSelectedChunk]=useState(0);
 const selected=cases.find(item=>item.id===selectedId)!;
 const assessable=cases.filter(item=>item.regression==='通过'||item.regression==='未通过');
 const assessed=assessable.filter(item=>item.correct!=='unset'&&item.citations!=='unset'&&item.coverage!=='unset');
 const good=assessed.filter(item=>item.correct==='yes'&&item.citations==='yes'&&item.coverage==='yes');
 const partial=assessable.filter(item=>[item.correct,item.citations,item.coverage].some(value=>value==='unset')&&[item.correct,item.citations,item.coverage].some(value=>value!=='unset'));
 const missing=assessable.filter(item=>[item.correct,item.citations,item.coverage].every(value=>value==='unset'));
 const executed=cases.filter(item=>item.regression!=='未执行');
 const passed=executed.filter(item=>item.regression==='通过');
 const errors=executed.filter(item=>item.regression==='执行错误');
 const change=(key:'correct'|'citations'|'coverage',value:Assessment)=>setCases(items=>items.map(item=>item.id===selectedId?{...item,[key]:value}:item));
 const chunks=[
  {title:'01 · 适用范围',location:'采购管理办法 · 第 2 节',content:'本办法适用于公司各部门采购申请。申请人应填写采购申请，并说明采购用途、预算及交付时间。',note:'标题与正文保留在同一分段。'},
  {title:'02 · 审批流程',location:'采购管理办法 · 第 3 节',content:'部门负责人审核申请内容；涉及预算调整时，还需由财务负责人审核。审批完成后进入采购执行阶段。',note:'这是示例片段，展示审批角色与上下文。'},
  {title:'03 · 申请材料',location:'采购管理办法 · 表格 1',content:'采购类型｜补充材料\n服务采购｜服务范围与验收标准\n设备采购｜设备清单与技术参数',note:'表头和数据行应关联；表格过长时需提示并保留表头。'},
 ];
 return <div className="proto-quality-page">
  <div className="proto-quality-heading"><div><span className="proto-quality-eyebrow">KNOWLEDGE QUALITY</span><h1>切分与质量</h1><p>从知识切分到案例评估，持续检查答案能否找到可靠依据。</p></div><Tag color="blue">方案原型</Tag></div>
  <Alert type="info" showIcon message="以下为固定示例数据与交互设计，不运行切分或回归，也不代表任何实测结果或企业达标结论。"/>
  <div className="proto-quality-tabs"><button className={tab==='chunk'?'active':''} onClick={()=>setTab('chunk')}><Scissors size={16}/>切分预览</button><button className={tab==='cases'?'active':''} onClick={()=>setTab('cases')}><ShieldCheck size={16}/>回归案例与质量</button></div>
  {tab==='chunk'?<>
   <div className="proto-quality-section-title"><div><h2>切分效果预览</h2><p>通过标题、正文和表格上下文检查切分是否完整。</p></div><Tag>示例文档 · 采购管理办法</Tag></div>
   <div className="proto-quality-layout"><section className="proto-quality-card"><h3>切分参数 <Tag>设计示意</Tag></h3><p className="proto-quality-muted">调整控件仅用于讨论；预览为固定示例，不会据此实际重新切分。</p><label>切分策略<Select value={strategy} onChange={setStrategy} options={[{value:'标题与段落',label:'标题与段落'},{value:'自然段',label:'自然段'},{value:'固定长度',label:'固定长度'},{value:'自定义分隔符',label:'自定义分隔符'}]}/></label><div className="proto-quality-inputs"><label>目标长度（字符）<InputNumber min={100} max={10000} value={chunkSize} onChange={setChunkSize}/></label><label>相邻重叠（字符）<InputNumber min={0} max={5000} value={overlap} onChange={setOverlap}/></label></div><div className="proto-quality-setting"><div><strong>保留表格结构</strong><small>表头与行内容关联，避免脱离上下文。</small></div><Switch checked={protectTable} onChange={setProtectTable}/></div><div className="proto-quality-callout"><CircleHelp size={15}/><span>正式方案需要兼顾标题层级、表格、过短或过长的段落。不同格式的保护方式以最终实现为准。</span></div></section>
    <section className="proto-quality-card"><div className="proto-quality-preview-head"><div><h3>切分片段</h3><p className="proto-quality-muted">3 个固定示例 · 选择片段查看来源</p></div><Tag color="blue">预览示意</Tag></div><div className="proto-quality-chunks">{chunks.map((chunk,index)=><button key={chunk.title} className={selectedChunk===index?'active':''} onClick={()=>setSelectedChunk(index)}><span><strong>{chunk.title}</strong><small>{chunk.location}</small></span><ChevronRight size={15}/></button>)}</div><div className="proto-quality-source"><div><FileText size={15}/><b>原文依据 · {chunks[selectedChunk].location}</b></div><p>{chunks[selectedChunk].content}</p><small>{chunks[selectedChunk].note}</small></div></section>
   </div>
   <section className="proto-quality-card proto-quality-risk"><h3>切分质量关注点</h3><div><span><b>标题丢失</b><small>片段是否保留所属章节及主题。</small></span><span><b>表格断裂</b><small>内容是否保留表头、单位和行关系。</small></span><span><b>片段不完整</b><small>问题答案是否因边界被截断。</small></span><span><b>冗余或遗漏</b><small>重叠是否过多，正文是否被覆盖。</small></span></div><p>以上是建议检查项；原型未自动检测风险或计算质量评分。</p></section>
  </>:<>
   <div className="proto-quality-section-title"><div><h2>回归案例与质量</h2><p>维护代表性问题，分别查看回归结果与人工质量判断。</p></div><Tag>示例案例集 · 5 条</Tag></div>
   <div className="proto-quality-metrics"><div><span>回归通过率 · 示例</span><strong>{executed.length ? `${(100 * passed.length / executed.length).toFixed(1)}%` : '—'}</strong><small>通过 {passed.length} / 已执行 {executed.length}；执行错误 {errors.length}，未执行 {cases.length-executed.length}</small></div><div><span>Good Case 率 · 示例</span><strong>{assessed.length ? `${(100 * good.length / assessed.length).toFixed(1)}%` : '—'}</strong><small>三项均符合 {good.length} / 三项均已判定 {assessed.length}；部分判定 {partial.length}，未判定 {missing.length}</small></div><div><span>Good Case 判断标准</span><strong className="proto-quality-metric-text">正确 · 引用 · 覆盖</strong><small>答案正确、引用准确且覆盖关键内容，三项均需符合。</small></div></div>
   <div className="proto-quality-quality-layout"><section className="proto-quality-card"><div className="proto-quality-preview-head"><div><h3>案例集合 <Tag>示例</Tag></h3><p className="proto-quality-muted">涵盖事实、表格、版本和图片问题。</p></div><BookOpen size={18}/></div><div className="proto-quality-case-list">{cases.map(item=><button key={item.id} className={selectedId===item.id?'active':''} onClick={()=>setSelectedId(item.id)}><span><strong>{item.question}</strong><small>{item.category} · {item.id}</small></span><Tag color={item.regression==='通过'?'green':item.regression==='未通过'?'orange':'default'}>{item.regression} · 示例</Tag></button>)}</div><p className="proto-quality-subnote">示例回归状态是虚构数据，页面不会执行或安排任何测试。</p></section>
    <section className="proto-quality-card"><h3>案例人工判断 <Tag>本页暂存</Tag></h3><p className="proto-quality-muted">选择案例并分别标注三项；关闭或刷新后恢复示例，不会保存。</p><div className="proto-quality-question"><span>示例问题</span><strong>{selected.question}</strong><p>期望检查：回答中的事实是否正确、来源能否支持结论、关键条件是否完整。</p></div>{([{key:'correct',label:'答案正确'},{key:'citations',label:'引用准确'},{key:'coverage',label:'覆盖关键内容'}] as const).map(item=><div className="proto-quality-judgment" key={item.key}><strong>{item.label}</strong><Radio.Group disabled={selected.regression==='未执行'||selected.regression==='执行错误'} size="small" optionType="button" buttonStyle="solid" options={judgmentOptions} value={selected[item.key]} onChange={event=>change(item.key,event.target.value as Assessment)}/></div>)}<div className="proto-quality-callout"><Sparkles size={15}/><span>仅对已执行且有结果的案例判定；三项全部判定后才计入 Good Case 率分母。执行错误、部分判定与未判定分别展示。</span></div></section>
   </div><div className="proto-quality-foot"><Button disabled>执行回归（原型未开放）</Button><span>正式功能需确认案例来源、运行方式及目标门槛后再设计；本次不执行测试脚本。</span></div>
  </>}
 </div>;
}
