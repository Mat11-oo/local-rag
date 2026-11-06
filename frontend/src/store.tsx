import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { App } from 'antd';
import type { ImportTask, Page, Role, WorkspaceState } from './types';
import { api, apiHeaders, setApiRole } from './api';
import { canVisit, pagePaths, readLocation } from './routing';
export const uid = () => crypto.randomUUID();
export const now = () => new Date().toISOString();
export const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const EMPTY: WorkspaceState = {providerConfigs:[],knowledgeBases:[],documents:[],tasks:[],models:[],assistants:[],sessions:[],logs:[],settings:{allowExternalProcessing:false}};
interface ContextValue {
 state: WorkspaceState; updateState: Dispatch<SetStateAction<WorkspaceState>>;
 role: Role; setRole: (role: Role) => void; page: Page; navigate: (page: Page) => void;
 activeKbId: string | null; setActiveKbId: (id: string | null) => void;
 activeAssistantId: string; setActiveAssistantId: (id: string) => void;
 activeSessionId: string | null; setActiveSessionId: (id: string | null) => void;
 importOpen: boolean; setImportOpen: (open: boolean) => void;
 refresh: () => Promise<void>; flush: () => Promise<void>; backendReady:boolean; syncing:boolean; connectionError:string;
 retryDocument:(id:string,reparse?:boolean,action?:ImportTask['action'])=>Promise<ImportTask|null>;
}
const WorkspaceContext = createContext<ContextValue | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
 const {message,modal}=App.useApp();
 const [state,setState]=useState<WorkspaceState>(EMPTY); const stateRef=useRef(state);
 const queue=useRef<Promise<unknown>>(Promise.resolve()); const pending=useRef(0); const revision=useRef('');
 const [role,changeRole]=useState<Role>('admin'); const [page,setPage]=useState<Page>(()=>readLocation().page);
 const [activeKbId,setActiveKbId]=useState<string|null>(()=>readLocation().page==='knowledge'?readLocation().entityId:null); const [activeAssistantId,setActiveAssistantId]=useState(()=>readLocation().page==='chat'?readLocation().entityId||'assistant-general':'assistant-general');
 const [activeSessionId,setActiveSessionId]=useState<string|null>(()=>readLocation().sessionId);
 const [importOpen,setImportOpen]=useState(false); const [backendReady,setReady]=useState(false); const [connectionError,setError]=useState(''); const [syncing,setSyncing]=useState(false);
 const connected=useRef(false);
 const apply=useCallback((next:WorkspaceState)=>{connected.current=true;stateRef.current=next;setState(next);setReady(true);setError('');},[]);
 const refresh=useCallback(async()=>{if(pending.current)return;try{apply(await api<WorkspaceState>('/api/workspace'));}catch(error){connected.current=false;setReady(false);setError((error as Error).message);}},[apply]);
 const flush=useCallback(async()=>{await queue.current;},[]);
 const retryDocument=useCallback(async(id:string,reparse=false,action?:ImportTask['action']):Promise<ImportTask|null>=>{
  const current=stateRef.current;const doc=current.documents.find(item=>item.id===id);
  const ready=(type:string)=>!!current.settings?.allowExternalProcessing&&current.models.some(model=>model.type===type&&model.isDefault&&model.hasKey&&model.status==='connected');
  const options={ocr:ready('OCR'),vision:ready('Vision')};
  const submit=async()=>{const task=await api<ImportTask>(`/api/documents/${id}/retry`,{method:'POST',body:JSON.stringify({options,...(action?{action}:reparse?{action:'parse'}:{})})});await refresh();message.success('已提交真实处理任务');return task;};
  if(doc&&(reparse||!doc.chunks.length))return new Promise(resolve=>{modal.confirm({title:'使用当前模型配置重新解析？',content:(options.ocr||options.vision?'将按当前已就绪的默认OCR/视觉模型处理图片或扫描页，相应内容会发送至所配置的服务商。':'将重新读取本机原始文件，提取文字和表格。当前未启用云端图片处理。')+' 若启用自动元数据抽取，还会把解析后的正文发送给配置的LLM。重新解析会替换预览分段；已有索引保留，确认构建后才发布新版本。',okText:'重新解析',cancelText:'取消',onCancel:()=>resolve(null),onOk:async()=>{try{resolve(await submit());}catch(error){message.error((error as Error).message);resolve(null);}}});});
  try{return await submit();}catch(error){message.error((error as Error).message);return null;}
 },[refresh,message,modal]);
 const updateState=useCallback<Dispatch<SetStateAction<WorkspaceState>>>((update)=>{
  const previous=stateRef.current; const next=typeof update==='function'?update(previous):update;
  const operations:unknown[]=[];
  for(const kind of ['knowledgeBases','documents','assistants','sessions','models'] as const){
   const old=new Map(previous[kind].map(item=>[item.id,item])); const fresh=new Map(next[kind].map(item=>[item.id,item]));
   for(const [id,value] of fresh){if(JSON.stringify(old.get(id))!==JSON.stringify(value)){
    const before=old.get(id) as unknown as Record<string,unknown>|undefined;
    const after=value as unknown as Record<string,unknown>;
    const changedFields=Object.keys(after).filter(key=>JSON.stringify(before?.[key])!==JSON.stringify(after[key]));
    operations.push({kind,id,action:'put',value,changedFields});
   }}
   for(const id of old.keys()){if(!fresh.has(id))operations.push({kind,id,action:'delete'});}
  }
  if(!operations.length)return;
  const mutationHeaders=apiHeaders();
  stateRef.current=next;setState(next);pending.current++;setSyncing(true);
  queue.current=queue.current.catch(()=>undefined).then(async()=>{
   try{const saved=await api<WorkspaceState>('/api/workspace/mutations',{method:'POST',headers:mutationHeaders,body:JSON.stringify({operations})});if(pending.current===1){if(apiHeaders()['X-Role']===mutationHeaders['X-Role'])apply(saved);else apply(await api<WorkspaceState>('/api/workspace'));}}
   catch(error){message.error((error as Error).message);if(pending.current===1){try{apply(await api<WorkspaceState>('/api/workspace'));}catch{setError('保存失败，请检查本地后端服务');}}}
   finally{pending.current--;if(!pending.current)setSyncing(false);}
  });
 },[apply,message]);
 useEffect(()=>{void refresh();const timer=window.setInterval(async()=>{if(pending.current)return;try{const result=await api<{revision:string}>('/api/version');if(result.revision!==revision.current||!connected.current){revision.current=result.revision;await refresh();}}catch{await refresh();}},1500);return()=>clearInterval(timer);},[refresh]);
 const setRole=useCallback((next:Role)=>{setApiRole(next);changeRole(next);setActiveKbId(null);setImportOpen(false);setActiveSessionId(null);setPage(next==='knowledge'?'knowledge':'overview');void refresh();},[refresh]);
 const navigate=useCallback((next:Page)=>{if(!canVisit(role,next))return;if(next!==page)window.history.pushState(null,'',`${window.location.pathname}${window.location.search}#${pagePaths[next]}`);setPage(next);if(next!=='knowledge')setActiveKbId(null);},[role,page]);
 useEffect(()=>{
  const syncLocation=()=>{const route=readLocation();if(!canVisit(role,route.page)){setPage('overview');window.history.replaceState(null,'',`${window.location.pathname}${window.location.search}#/workbench`);return;}setPage(route.page);setActiveKbId(route.page==='knowledge'?route.entityId:null);if(route.page==='chat'){if(route.entityId)setActiveAssistantId(route.entityId);setActiveSessionId(route.sessionId);}};
  window.addEventListener('hashchange',syncLocation);window.addEventListener('popstate',syncLocation);return()=>{window.removeEventListener('hashchange',syncLocation);window.removeEventListener('popstate',syncLocation);};
 },[role]);
 useEffect(()=>{
  let path=pagePaths[page];
  if(page==='knowledge'&&activeKbId)path+=`/${encodeURIComponent(activeKbId)}`;
  if(page==='chat'){path+=`/${encodeURIComponent(activeAssistantId)}`;if(activeSessionId)path+=`?session=${encodeURIComponent(activeSessionId)}`;}
  if(window.location.hash!==`#${path}`)window.history.replaceState(null,'',`${window.location.pathname}${window.location.search}#${path}`);
 },[page,activeKbId,activeAssistantId,activeSessionId]);
 return <WorkspaceContext.Provider value={{state,updateState,role,setRole,page,navigate,activeKbId,setActiveKbId,activeAssistantId,setActiveAssistantId,activeSessionId,setActiveSessionId,importOpen,setImportOpen,refresh,flush,backendReady,syncing,connectionError,retryDocument}}>{children}</WorkspaceContext.Provider>;
}
export function useWorkspace(){const value=useContext(WorkspaceContext);if(!value)throw new Error('WorkspaceProvider is required');return value;}
