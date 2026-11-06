import { apiFetch, ApiError } from '../api/client';
type EventName='onboarding_opened'|'task_started'|'trusted_answer_confirmed'|'import_started'|'import_completed'|'import_failed'|'preview_failed'|'save_failed'|'save_recovered'|'search_started'|'search_selected'|'chat_started'|'chat_completed'|'chat_failed'|'chat_wait_cancelled';
type Failure='network'|'auth'|'permission'|'missing'|'validation'|'provider'|'unknown';
export function failureKind(error:unknown):Failure {
 const status=error instanceof ApiError?error.status:0;
 return status===0?'network':status===401?'auth':status===403?'permission':status===404?'missing':status===422?'validation':status>=500?'provider':'unknown';
}
interface Options {operation_id?:string;trace_id?:string;failure_kind?:Failure}
let queue:Promise<boolean>=Promise.resolve(true);
export function recordExperience(event:EventName,duration_ms?:number,options:Options={}) {
 const next=queue.catch(()=>false).then(()=>capture(event,duration_ms,options));queue=next;return next;
}
async function capture(event:EventName,duration_ms?:number,options:Options={}) {
 try {
  const getId=(key:string)=>{let id=sessionStorage.getItem(key);if(!id){id=crypto.randomUUID();sessionStorage.setItem(key,id);}return id;};
  const session_id=getId('local-rag.ux-session');const task_id=getId('local-rag.ux-task');const occurred_at=new Date().toISOString();
  const pending:Record<string,unknown>[]=JSON.parse(sessionStorage.getItem('local-rag.ux-pending')??'[]');
  if(!sessionStorage.getItem('local-rag.task-started')){
   pending.push({id:task_id,session_id,task_id,event:'task_started',occurred_at});
   sessionStorage.setItem('local-rag.task-started','1');
  }

  const category=event.split('_')[0];const key=`local-rag.operation.${category}.${options.operation_id??'active'}`;
  let operation:{id:string;failed_at?:number}|null=JSON.parse(sessionStorage.getItem(key)??'null');
  if(!operation||event.endsWith('_started')&&!operation.failed_at)operation={id:options.operation_id??crypto.randomUUID()};
  if(options.operation_id)operation.id=options.operation_id;
  if(event.endsWith('_failed')&&!operation.failed_at)operation.failed_at=Date.now();
  const recovered=(event.endsWith('_completed')||event==='save_recovered')&&Boolean(operation.failed_at);
  const recovery_ms=recovered?Math.min(86400000,Date.now()-operation.failed_at!):undefined;
  sessionStorage.setItem(key,JSON.stringify(operation));
  if(event!=='task_started')pending.push({id:crypto.randomUUID(),session_id,task_id,event,occurred_at,duration_ms,operation_id:operation.id,recovery_ms,failure_kind:options.failure_kind,trace_id:options.trace_id});
  // A bounded local outbox keeps minimal failure events across disconnection and refresh.
  while(pending.length>200)pending.shift();
  sessionStorage.setItem('local-rag.ux-pending',JSON.stringify(pending));
  if(recovered||event.endsWith('_completed'))sessionStorage.removeItem(key);
  let accepted=true;
  while(pending.length){
   try{await apiFetch('/experience/events',{method:'POST',body:JSON.stringify(pending[0])});}
   catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500&&error.status!==429){accepted=false;}else{return false;}}
   pending.shift();sessionStorage.setItem('local-rag.ux-pending',JSON.stringify(pending));
  }
  return accepted;
 }catch{/* Observation must not block product operations. */return false;}
}
export function startNewExperienceTask(){
 sessionStorage.removeItem('local-rag.ux-task');sessionStorage.removeItem('local-rag.task-started');
 for(const key of Object.keys(sessionStorage))if(key.startsWith('local-rag.operation.'))sessionStorage.removeItem(key);
 void recordExperience('task_started');
}
