import { useEffect, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { startNewExperienceTask } from '../lib/experience';
import { Notice } from './ui';
interface Summary {days:number;events:Record<string,number>;sessions:number;sample_count:number;truncated:boolean;mean_completed_chat_ms:number|null;scope:string;tasks:{started:number;completed:number;unfinished_by_last_event:Record<string,number>;mean_first_trusted_ms:number|null;recovered_operations:number;mean_recovery_ms:number|null;failure_categories:Record<string,number>}}
const labels:Record<string,string>={task_started:'开始任务',trusted_answer_confirmed:'人工确认可信回答',onboarding_opened:'查看就绪清单',import_started:'开始导入',import_completed:'导入成功',import_failed:'导入失败',preview_failed:'预览失败',save_failed:'草稿保存失败',save_recovered:'保存恢复成功',search_started:'发起资源搜索',search_selected:'选择搜索结果',chat_started:'开始对话',chat_completed:'收到完整响应',chat_failed:'对话失败',chat_wait_cancelled:'取消前端等待',network:'连接失败',auth:'登录失效',permission:'权限不足',missing:'资源不存在',validation:'参数或业务校验',provider:'模型、工具或处理服务异常',unknown:'未分类'};
const duration=(value:number|null)=>value===null?'暂无样本':`${(value/1000).toFixed(1)} 秒`;
export function ExperienceSummary(){
 const [data,setData]=useState<Summary|null>(null),[error,setError]=useState(''),[days,setDays]=useState(7),[refresh,setRefresh]=useState(0);
 useEffect(()=>{let active=true;setError('');void apiFetch<Summary>(`/experience/summary?days=${days}`).then(value=>{if(active)setData(value);}).catch(caught=>{if(active)setError(errorMessage(caught));});return()=>{active=false;};},[days,refresh]);
 return <section className="card" style={{padding:20,marginTop:16}}><h2>体验观察 · 任务与恢复</h2><div className="row wrap"><select className="select sm" aria-label="观察时间范围" value={days} onChange={event=>{setData(null);setDays(Number(event.target.value));}}>{[1,7,30].map(value=><option key={value} value={value}>最近 {value} 天</option>)}</select><button className="btn sm" onClick={()=>setRefresh(value=>value+1)}>刷新观察</button><button className="btn sm" onClick={()=>{startNewExperienceTask();setRefresh(value=>value+1);}}>开始记录新任务</button></div>
 <p>仅记录固定事件、随机任务 / 操作 / 会话标识、耗时、失败类别及工作空间与操作身份；不记录搜索词、提示词、资料或回答正文。任务在当前标签页跨页面、刷新后延续。</p>
 {error?<Notice tone="error">{error}</Notice>:data?<><p>{data.sample_count} 条事件 · {data.sessions} 个浏览器会话{data.truncated?'（窗口超过 5000 条，以下只统计最近样本，不是全量指标）':''}</p>
 <p>记录任务 {data.tasks.started} · 用户确认可信回答的任务 {data.tasks.completed} · 首次可信回答平均耗时：{duration(data.tasks.mean_first_trusted_ms)}</p>
 <p>错误恢复 {data.tasks.recovered_operations} 次 · 平均恢复耗时：{duration(data.tasks.mean_recovery_ms)} · 完整响应平均等待：{duration(data.mean_completed_chat_ms)}</p>
 <h3>尚未完成任务的最后记录位置</h3>{Object.keys(data.tasks.unfinished_by_last_event).length?<ul>{Object.entries(data.tasks.unfinished_by_last_event).map(([event,count])=><li key={event}>{labels[event]??event}：{count}</li>)}</ul>:<p>暂无未完成任务样本。</p>}
 <h3>失败分类</h3>{Object.keys(data.tasks.failure_categories).length?<ul>{Object.entries(data.tasks.failure_categories).map(([event,count])=><li key={event}>{labels[event]??event}：{count}</li>)}</ul>:<p>暂无失败样本。</p>}
 <details><summary>事件明细与口径</summary><div className="row wrap">{Object.entries(data.events).map(([event,count])=><span className="tag" key={event}>{labels[event]??event} {count}</span>)}</div><p>首次可信回答：从本任务首次事件到用户主动核对引用后确认的首条有效回答；服务端排除测试替身、无引用与转人工结果。恢复耗时：同一操作首次失败到成功，跨刷新保留；历史无标识事件只计事件数，不推算任务指标。时间窗口外开始的任务不纳入首次完成耗时。</p></details><small>{data.scope}</small></>:<p>正在读取…</p>}
 </section>;
}
