import { useState } from 'react';
import { Button, Input, Modal, Segmented, Tag } from 'antd';
import { ArrowLeft, BookOpen, ChevronRight, Database, FileText, Plus, Search, Settings2, Upload } from 'lucide-react';
import ImportPrototype from './ImportPrototype';
import QualityPrototype from './QualityPrototype';
import './knowledge-prototype.css';

type Tab = '文档' | '导入资料' | '切分与质量' | '检索调试' | '设置';
const docs = [
 {name:'采购管理办法（示例）.pdf',type:'PDF 文档',updated:'2026-10-26',chunks:18,status:'可检索',color:'green'},
 {name:'费用报销标准（示例）.xlsx',type:'电子表格',updated:'2026-10-26',chunks:8,status:'待构建',color:'gold'},
 {name:'新员工指南（示例）.md',type:'Markdown',updated:'2026-10-25',chunks:12,status:'解析失败',color:'red'},
];

export default function KnowledgePrototype(){
 const [detail,setDetail]=useState(false);
 const [tab,setTab]=useState<Tab>('文档');
 const [selectedDoc,setSelectedDoc]=useState<(typeof docs)[number] | null>(null);
 const [query,setQuery]=useState('');
 const [term,setTerm]=useState('');
 const [searched,setSearched]=useState(false);
 const [mode,setMode]=useState('混合检索');
 const visible=docs.filter(doc=>doc.name.toLowerCase().includes(query.toLowerCase()));
 return <div className={`proto-kb-page ${detail ? 'proto-kb-detail-layout' : ''}`}>
 {!detail?<><header className="proto-kb-heading"><div><span className="proto-kb-eyebrow">KNOWLEDGE BASE</span><h1>知识库</h1><p>集中管理文档、分段与检索范围。</p></div><Button type="primary" icon={<Plus size={15}/>} onClick={()=>setDetail(true)}>查看示例知识库</Button></header>
 <div className="proto-kb-statbar"><div><Database size={19}/><span><b>1</b><small>示例知识库</small></span></div><div><FileText size={19}/><span><b>3</b><small>示例文档</small></span></div><div><BookOpen size={19}/><span><b>1</b><small>示例可检索文档</small></span></div></div>
 <div className="proto-kb-sectionhead"><div><h2>全部知识库</h2><p>选择知识库，查看文档及处理状态。</p></div><Tag>以下均为虚构示例</Tag></div>
 <div className="proto-kb-cards">{[{name:'制度与流程',desc:'沉淀团队日常制度与办事流程',count:'3 份示例文档'}].map(item=><button className="proto-kb-library" key={item.name} onClick={()=>setDetail(true)}><span className="proto-kb-icon"><Database size={20}/></span><span><strong>{item.name}</strong><small>{item.desc}</small><em>{item.count} · 点击查看示例</em></span><ChevronRight size={16}/></button>)}</div></>:<><aside className="proto-kb-subnav"><button className="proto-kb-back" onClick={()=>{setDetail(false);setQuery('');}}><ArrowLeft size={15}/> 返回知识库</button><div className="proto-kb-subtitle"><span className="proto-kb-icon"><Database size={20}/></span><div><strong>制度与流程</strong><small>示例知识库</small></div></div><div className="proto-kb-subgroup">知识管理</div>{(['文档','导入资料','切分与质量','检索调试','设置'] as Tab[]).map(item=><button className={`proto-kb-sublink ${tab===item?'active':''}`} key={item} onClick={()=>setTab(item)}>{item==='文档'?<FileText size={15}/>:item==='导入资料'?<Upload size={15}/>:item==='切分与质量'?<BookOpen size={15}/>:item==='检索调试'?<Search size={15}/>:<Settings2 size={15}/>}<span>{item}</span></button>)}<div className="proto-kb-subnote">示例 · 3 份文档<br/>1 份可检索</div></aside><div className="proto-kb-detail-main"><header className="proto-kb-heading"><div><span className="proto-kb-eyebrow">KNOWLEDGE BASE / DATASET</span><h1>制度与流程 <Tag color="blue">示例</Tag></h1><p>管理资料、检查知识分段并了解检索方式。</p></div></header>
 <div className="proto-kb-detail-title"><strong>{tab}</strong><span>管理知识内容与来源</span></div>
 {tab==='文档'?<section className="proto-kb-surface"><div className="proto-kb-toolbar"><div><h2>文档列表</h2><p>解析完成后仍需构建索引，发布后才能检索。</p></div><Input aria-label="筛选示例文档" value={query} onChange={event=>setQuery(event.target.value)} prefix={<Search size={15}/>} placeholder="搜索示例文档" allowClear style={{width:240}}/></div><div className="proto-kb-table-wrap"><table className="proto-kb-table"><thead><tr><th>文件名称</th><th>知识分段</th><th>处理状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{visible.map(doc=><tr key={doc.name}><td><div className="proto-kb-file"><span><FileText size={17}/></span><div><strong>{doc.name}</strong><small>{doc.type} · 示例</small></div></div></td><td>{doc.chunks} 个</td><td><Tag color={doc.color}>{doc.status}</Tag></td><td>{doc.updated}</td><td><Button type="link" onClick={()=>setSelectedDoc(doc)}>查看详情</Button></td></tr>)}</tbody></table>{!visible.length&&<div className="proto-kb-empty">没有匹配的示例文档</div>}</div></section>:tab==='导入资料'?<ImportPrototype fixedKnowledge/>:tab==='切分与质量'?<QualityPrototype/>:tab==='检索调试'?<div className="proto-kb-split"><section className="proto-kb-surface proto-kb-panel"><div className="proto-kb-panel-heading"><h2>检索设置</h2><Tag>交互示意</Tag></div><p>输入问题，了解正式功能中如何查看检索片段。</p><Input.TextArea value={term} onChange={event=>setTerm(event.target.value)} rows={3} placeholder="输入一个示例问题" aria-label="示例检索问题"/><h3>检索方式</h3><Segmented value={mode} onChange={value=>setMode(String(value))} options={['关键词','语义','混合检索']}/><div className="proto-kb-hint">正式功能中的检索可能调用模型并产生费用。原型不会发起请求。</div><Button type="primary" disabled={!term.trim()} onClick={()=>setSearched(true)}>查看示例结果</Button></section><section className="proto-kb-surface proto-kb-panel"><div className="proto-kb-panel-heading"><h2>召回片段</h2><Tag>{searched?'固定示例':'等待输入'}</Tag></div>{searched?<div className="proto-kb-chunk"><span>虚构示例 · 采购管理办法 · 第 3 节</span><p>部门负责人审核申请内容；涉及预算调整时，还需由财务负责人审核。</p><small>该内容与输入问题无关，仅演示结果布局，不代表已执行检索。</small></div>:<div className="proto-kb-empty">输入问题后，可查看结果卡片的示例样式。</div>}</section></div>:<section className="proto-kb-surface proto-kb-panel"><h2>知识库设置</h2><p>正式系统可维护名称、描述、标签和向量模型；模型变更可能需要重建索引。</p><div className="proto-kb-option"><strong>知识库名称</strong><span>制度与流程（示例）</span></div><div className="proto-kb-option"><strong>索引范围</strong><span>已发布、已启用的文档</span></div><div className="proto-kb-hint">这里只展示布局，不会更改正式系统的知识库设置。</div></section>}
 </div></>}
 <Modal title="文档详情 · 示例" open={!!selectedDoc} onCancel={()=>setSelectedDoc(null)} footer={<Button onClick={()=>setSelectedDoc(null)}>关闭</Button>}>{selectedDoc&&<div className="proto-kb-document-detail"><p><strong>{selectedDoc.name}</strong></p><p>处理状态：<Tag color={selectedDoc.color}>{selectedDoc.status}</Tag></p><p>知识分段：{selectedDoc.chunks} 个 · 示例</p><p>{selectedDoc.status==='待构建'?'解析已完成，尚未构建并发布索引。':selectedDoc.status==='解析失败'?'示例：文档解析未完成，请检查文件或处理配置。':'示例文档已发布，可用于检索。'}</p><div className="proto-kb-chunk"><span>内容示例</span><p>本区域用于展示当前文档的解析内容、处理状态与来源信息。</p></div></div>}</Modal>
 </div>;
}
