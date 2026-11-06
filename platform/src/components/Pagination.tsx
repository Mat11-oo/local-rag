export function Pagination({page,total,size=20,onChange}:{page:number;total:number;size?:number;onChange:(page:number)=>void}) {
  const pages=Math.max(1,Math.ceil(total/size));
  if(total<=size)return <p className="faint" role="status">共 {total} 条记录</p>;
  return <nav className="row" aria-label="列表分页" style={{margin:'16px 0'}}><span className="faint grow">当前已加载 {total} 条记录 · 第 {page}/{pages} 页</span><button className="btn sm" disabled={page<=1} onClick={()=>onChange(page-1)}>上一页</button><button className="btn sm" disabled={page>=pages} onClick={()=>onChange(page+1)}>下一页</button></nav>;
}
