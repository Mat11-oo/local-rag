import { useMemo, useState } from 'react';
import { Button, Drawer, Input, Select, Tag } from 'antd';
import { Activity, ArrowRight, Bot, CircleHelp, Database, MessageCircle, Percent, ThumbsDown, Users } from 'lucide-react';
import './insights-prototype.css';

type Gap = {question:string; count:number; app:string; knowledge:string};
const gaps:Gap[]=[
 {question:'新员工如何申请办公设备？',count:28,app:'制度问答助手',knowledge:'制度与流程'},
 {question:'报销超过预算应该如何处理？',count:16,app:'制度问答助手',knowledge:'费用管理'},
 {question:'采购申请需要哪些审批材料？',count:11,app:'采购知识助手',knowledge:'采购管理'},
];
const scores=[{name:'制度问答助手',count:412,rate:'89%',color:'#3370ff'}, {name:'采购知识助手',count:286,rate:'85%',color:'#12b76a'}, {name:'项目知识助手',count:168,rate:'82%',color:'#7a5af8'}];
const feedback=[{q:'申请年假需要提前多少天？',app:'制度问答助手',status:'未命中'}, {q:'差旅报销的标准是什么？',app:'制度问答助手',status:'点踩'}, {q:'采购审批流程是什么？',app:'采购知识助手',status:'点踩'}];
const chart7=[64,76,89,67,100,73,82];
const chart30=[48,55,66,61,72,80,71,62,75,83,74,88,81,65,79,86,77,91,82,89,73,85,92,81,78,100,83,88,75,91];

export default function InsightsPrototype(){
 const [range,setRange]=useState<'7'|'30'>('7');
 const [gap,setGap]=useState<Gap|null>(null);
 const [note,setNote]=useState('');
 const [saved,setSaved]=useState(false);
 const data=useMemo(()=>range==='7'?chart7:chart30,[range]);
 const metrics=range==='7'?[['调用次数','866','+18.2%'],['活跃用户','128','+9.4%'],['满意度','89.0%','+1.2 个百分点'],['知识命中率','86.9%','-0.8 个百分点'],['转人工率','6.3%','-2.1 个百分点']]:[['调用次数','3,520','+12.1%'],['活跃用户','386','+8.3%'],['满意度','88.7%','+0.9 个百分点'],['知识命中率','85.8%','+1.1 个百分点'],['转人工率','6.8%','-0.4 个百分点']];
 const icons=[Activity,Users,ThumbsDown,Database,Percent];
 return <div className="proto-insight-page">
  <header className="proto-insight-heading"><div><h1>运营看板</h1><p>了解知识助手的使用情况，并发现需要补充的知识。</p></div><Select aria-label="选择示例时间范围" value={range} onChange={setRange} options={[{value:'7',label:'最近 7 天'},{value:'30',label:'最近 30 天'}]} style={{width:140}}/></header>
  <div className="proto-insight-note"><CircleHelp size={15}/><span>以下数据和变化均为虚构示例，仅用于评审看板布局与交互。</span></div>
  <div className="proto-insight-metrics">{metrics.map(([label,value,change],i)=>{const Icon=icons[i];return <div className="proto-insight-card proto-insight-metric" key={label}><div><Icon size={15}/>{label}</div><strong>{value}</strong><small className={change.startsWith('-')?'down':''}>较上期 {change}</small></div>})}</div>
  <div className="proto-insight-grid"><section className="proto-insight-card proto-insight-plot"><div className="proto-insight-title"><strong>每日调用</strong><span>全部助手 · 示例数据</span></div><div className="proto-insight-chart" role="img" aria-label={`虚构示例：最近 ${range} 天的每日调用趋势`}><div className="proto-insight-gridlines"><i/><i/><i/><i/></div><div className="proto-insight-bars">{data.map((height,i)=><div key={i} className="proto-insight-bar-slot"><div className="proto-insight-bar" style={{height:`${height}%`}} title={`第 ${i+1} 天：示例值 ${height}`}/>{(range==='7'||i%5===0||i===data.length-1)&&<span>{range==='7'?`第 ${i+1} 天`:`${i+1}`}</span>}</div>)}</div></div></section>
   <section className="proto-insight-card proto-insight-ranking"><div className="proto-insight-title"><strong>应用排行</strong><span>示例</span></div>{scores.map((row,i)=><div className="proto-insight-rankrow" key={row.name}><span className="proto-insight-ranknum">{i+1}</span><span className="proto-insight-appicon" style={{background:row.color}}><Bot size={15}/></span><span className="proto-insight-rankname">{row.name}</span><strong>{row.count}</strong><Tag color={i===0?'green':'gold'}>{row.rate}</Tag></div>)}<p className="proto-insight-foot">调用数与满意度为独立指标，计算口径将在正式方案中明确。</p></section></div>
  <div className="proto-insight-grid proto-insight-lower"><section className="proto-insight-card proto-insight-gap"><div className="proto-insight-title"><strong>知识缺口 <Tag>方案示意</Tag></strong><span>集中查看需要补充的问题</span></div><div className="proto-insight-tablewrap"><table><thead><tr><th>问题</th><th>次数</th><th>来源助手</th><th>建议补充到</th><th/></tr></thead><tbody>{gaps.map(row=><tr key={row.question}><td>{row.question}</td><td><Tag color="red">{row.count}</Tag></td><td>{row.app}</td><td><Tag color="blue">{row.knowledge}</Tag></td><td><Button size="small" onClick={()=>{setGap(row);setNote('');setSaved(false);}}>查看 <ArrowRight size={12}/></Button></td></tr>)}</tbody></table></div><p className="proto-insight-foot">示例聚合结果。正式系统需实现来源与判定规则后才能生成真实结果。</p></section>
   <section className="proto-insight-card proto-insight-feedback"><div className="proto-insight-title"><strong>最近反馈</strong><span>示例</span></div>{feedback.map(item=><div className="proto-insight-feedbackrow" key={item.q}><span className="proto-insight-appicon muted"><MessageCircle size={15}/></span><div><strong>{item.q}</strong><small>{item.app} · 示例记录</small></div><Tag color={item.status==='未命中'?'orange':'red'}>{item.status}</Tag></div>)}</section></div>
  <Drawer title="知识缺口 · 示例详情" open={!!gap} onClose={()=>setGap(null)} size={480}>{gap&&<div className="proto-insight-drawer"><p>以下内容为模拟数据，仅展示未来的处理路径。</p><h3>{gap.question}</h3><div><span>来源助手</span><b>{gap.app}</b></div><div><span>出现次数</span><b>{gap.count} 次 · 示例</b></div><div><span>建议补充到</span><b>{gap.knowledge}</b></div><label>补充处理备注（示例）<Input.TextArea value={note} onChange={event=>{setNote(event.target.value);setSaved(false);}} rows={3} placeholder="记录需要补充的信息" /></label><Button type="primary" disabled={!note.trim()} onClick={()=>setSaved(true)}>保存示例备注</Button>{saved&&<p>已在当前原型中记录，不会写入正式数据。</p>}</div>}</Drawer>
 </div>;
}
