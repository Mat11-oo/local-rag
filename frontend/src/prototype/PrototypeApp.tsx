import { useState } from 'react';
import { Select } from 'antd';
import { ChartNoAxesCombined, CircleAlert, Database, LayoutDashboard, MessageSquare, Settings2 } from 'lucide-react';
import ModelPrototype from './ModelPrototype';
import ChatPrototype from './ChatPrototype';
import KnowledgePrototype from './KnowledgePrototype';
import InsightsPrototype from './InsightsPrototype';
import './prototype.css';
import './reference-layout.css';

type View = 'insights' | 'knowledge' | 'models' | 'chat';
type Role = 'admin' | 'knowledge' | 'user';
const nav: { id: View; title: string; icon: typeof LayoutDashboard }[] = [
 { id: 'knowledge', title: '知识库', icon: Database },
 { id: 'chat', title: '对话', icon: MessageSquare },
 { id: 'insights', title: '看板', icon: ChartNoAxesCombined },
 { id: 'models', title: '模型', icon: Settings2 },
];

export default function PrototypeApp() {
 const [view,setView]=useState<View>('insights');
 const [role,setRole]=useState<Role>('admin');
 const allowed=(target:View)=>target==='chat'||((target==='insights'||target==='knowledge')&&role!=='user')||(target==='models'&&role==='admin');
 return <div className="proto-app"><aside className="proto-sidebar"><div className="proto-brand" aria-label="知序知识中台"><span>知</span></div><div className="proto-nav-demo">原型<br/>示例数据</div><nav aria-label="主要功能">{nav.filter(item=>allowed(item.id)).map(item=>{const Icon=item.icon;return <button className={view===item.id?'active':''} key={item.id} onClick={()=>setView(item.id)} aria-current={view===item.id?'page':undefined}><Icon size={20}/><span>{item.title}</span></button>;})}</nav><div className="proto-nav-avatar" title="演示角色">{role==='admin'?'管':role==='knowledge'?'知':'用'}</div></aside>
  <main className="proto-main"><header className="proto-topbar"><div>工作空间 <span>/</span> <strong>{nav.find(item=>item.id===view)?.title}</strong></div><div className="proto-top-actions"><span>角色体验</span><Select aria-label="选择角色体验" value={role} onChange={(next:Role)=>{setRole(next);setView(next==='user'?'chat':'insights');}} options={[{value:'admin',label:'管理员'},{value:'knowledge',label:'知识管理员'},{value:'user',label:'使用者'}]} style={{width:118}}/><a href="../">返回展示页</a></div></header><div className="proto-banner"><CircleAlert size={15}/><span><b>交互原型</b> · 页面数据、操作结果和对话均为示例，不会读取或修改现有数据，也不会调用模型。角色切换仅用于演示。</span></div>{view==='insights'?<InsightsPrototype/>:view==='knowledge'?<KnowledgePrototype/>:view==='models'?<ModelPrototype/>:<ChatPrototype role={role}/>}</main>
 </div>;
}
