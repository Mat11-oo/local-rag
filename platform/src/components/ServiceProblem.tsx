import { AlertCircle, RefreshCw } from 'lucide-react';
export function ServiceProblem({message,status=0,onRetry}: {message:string;status?:number;onRetry?:()=>void}) {
 const forbidden=status===403, missing=status===404, expired=status===401;
 const title=forbidden?'无权访问此功能':missing?'没有找到此页面或资源':expired?'登录状态已失效':'暂时无法连接工作空间';
 const hint=forbidden?'请返回工作台，或联系管理员确认权限。本地角色菜单用于切换操作视角。':missing?'请检查地址，或从列表重新选择资源。':expired?'请重新登录后继续。':'请确认本地服务正在运行，恢复连接后重试。已有资料无需重新导入。';
 return <div className="service-problem" role="alert"><AlertCircle size={30}/><h1>{title}</h1><p>{message}</p><small>{hint}</small><div className="row wrap">{onRetry&&!forbidden&&!missing?<button className="btn primary" onClick={onRetry}><RefreshCw size={15}/>重新连接</button>:null}<a className="btn" href={expired?'/login':'/workbench'}>{expired?'重新登录':'返回工作台'}</a>{!forbidden&&!missing&&!expired?<details><summary>连接诊断</summary><p>前端：4173；后端：8001。请在项目目录运行 python3 scripts/start-local.py；本页不会修改服务或数据。</p></details>:null}</div></div>;
}
