import { CheckCircle2, Circle, ArrowRight } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { recordExperience } from '../lib/experience';
import { Link } from 'react-router-dom';
import { apiFetch, type ApiEvaluationSet, type ApiKnowledgeBase, type ApiModelOption } from '../api/client';
import { useAuth } from '../auth';
import type { FDEApp } from '../api/fde';
export function ReadinessChecklist({apps,knowledge,models,sets}: {apps:FDEApp[];knowledge:ApiKnowledgeBase[];models:ApiModelOption[];sets:ApiEvaluationSet[]}) {
 const {me}=useAuth();const recorded=useRef(false);const [selected,setSelected]=useState('');
 const [debug,setDebug]=useState({app:'',confirmed:false,error:false});
 useEffect(()=>{if(!recorded.current){recorded.current=true;recordExperience('onboarding_opened');}},[]);
 const candidate=apps.find(app=>app.id===selected)??apps.find(app=>app.manifest.llm_model_id&&app.manifest.knowledge_base_ids.length)??apps[0];
 const id=candidate?.id;
 useEffect(()=>{let active=true;if(id)void apiFetch<{debug_confirmed:boolean}>(`/fde/apps/${id}/readiness`).then(value=>{if(active)setDebug({app:id,confirmed:value.debug_confirmed,error:false});}).catch(()=>{if(active)setDebug({app:id,confirmed:false,error:true});});return()=>{active=false;};},[id]);
 const model=models.find(model=>model.id===candidate?.manifest.llm_model_id);
 const configured=Boolean(model?.model_type==='llm'&&model.is_enabled&&model.connection_status==='connected'&&model.provider!=='mock');
 const linkedIds=candidate?.manifest.knowledge_base_ids??[];
 const linked=linkedIds.length>0&&linkedIds.every(id=>knowledge.some(kb=>kb.id===id));
 const searchable=linked&&linkedIds.every(id=>knowledge.some(kb=>kb.id===id&&(kb.total_chunk_count??0)>0));
 const quality=sets.some(set=>set.app_id===id&&(set.quality_count??0)>0&&set.latest_run?.status==='success'&&!set.latest_run.simulated&&set.latest_run.matches_draft&&set.latest_run.matches_criteria);
 const released=Boolean(candidate?.is_enabled&&candidate?.published_version_id);
 const path=id?`/apps/${id}`:'/apps?create=1';
 const steps=[
  {name:'验证应用使用的对话模型',done:configured,path:me?.role==='admin'?'/tools?tab=models':path},
  {name:'关联知识库',done:linked,path},
  {name:'准备应用可检索资料',done:searchable,path:linkedIds[0]?`/knowledge/${linkedIds[0]}`:'/knowledge'},
  {name:'调试并人工核对答案',done:debug.app===id&&debug.confirmed,path},
  {name:'完成回答质量评测',done:quality,path:id?`${path}?tab=eval`:'/evaluation-sets'},
  {name:'发布后开始使用',done:released,path},
 ];const next=steps.find(step=>!step.done);
 return <section className="onboarding" aria-label="首次使用就绪清单"><details open={!released}><summary><strong>{released?'此应用已发布':'完成准备，获得第一条有依据的回答'}</strong></summary>
 {apps.length?<label>检查应用 <select className="select sm" aria-label="检查应用" value={id??''} onChange={event=>setSelected(event.target.value)}>{apps.map(app=><option key={app.id} value={app.id}>{app.name}</option>)}</select></label>:null}
 <p>{knowledge.length?`已有 ${knowledge.length} 个知识库、${knowledge.reduce((n,kb)=>n+kb.file_count,0)} 份资料，无需重复导入。`:'先准备资料，再关联应用。'}{!released?' 当前应用尚未发布。':''}清单仅判断所选应用。</p>
 <p>当前模型：{model?.display_name??'未选择'} · {configured?'已连通':model?.connection_status==='error'?'连接异常，请重新验证':'尚未验证真实连通'}。{debug.error?'调试确认记录读取失败，请重新打开工作台。':''}</p>
 <ol>{steps.map(step=><li key={step.name}>{step.done?<CheckCircle2 size={16}/>:<Circle size={16}/>}<Link to={step.path}>{step.name}</Link><small>{step.done?'已具备':'待确认'}</small></li>)}</ol>
 <p>调试成功后需主动核对引用与答案并确认；修改草稿后确认失效。规则通过不保证所有业务问题正确，测试替身不算真实验收。</p>
 {next?<Link className="btn primary next-step" to={next.path}>下一步：{next.name}<ArrowRight size={15}/></Link>:<Link className="btn primary" to={`/chat/${id}`}>使用此应用</Link>}
 </details></section>;
}
