import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { recordExperience } from '../lib/experience';
import { Loading, Notice } from './ui';
interface Item { id: string; kind: string; name: string; path: string }
const labels: Record<string,string> = {app:'应用',knowledge:'知识库',file:'文件',navigation:'功能'};
export function WorkspaceSearch({query, navigation, onSelected}: {query: string; navigation: Item[]; onSelected: () => void}) {
  const [items,setItems] = useState<Item[]>([]);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setError('');setItems([]);
    if(!query.trim()){setBusy(false);return;}
    setBusy(true);
    const timer = window.setTimeout(() => {
      recordExperience('search_started');
      void apiFetch<{items:Item[]}>(`/workspace-search?q=${encodeURIComponent(query.trim())}`,{signal:controller.signal})
        .then(result => {if(!controller.signal.aborted)setItems(result.items);})
        .catch(caught => {if(!controller.signal.aborted)setError(errorMessage(caught));})
        .finally(() => {if(!controller.signal.aborted)setBusy(false);});
    },250);
    return () => {window.clearTimeout(timer);controller.abort();};
  },[query]);
  const visible = [...navigation.filter(item => !query || item.name.includes(query.trim())),...items];
  return <div className="local-search-results" data-search-results="true" onKeyDown={event => {
    if(!['ArrowDown','ArrowUp'].includes(event.key)) return;
    const links = Array.from(event.currentTarget.querySelectorAll('a')); const index = links.indexOf(document.activeElement as HTMLAnchorElement);
    if(links.length){event.preventDefault();links[(index + (event.key === 'ArrowDown' ? 1 : links.length-1)) % links.length]?.focus();}
  }}>
    {busy ? <Loading text="搜索资源…"/> : null}{error ? <Notice tone="error">{error}</Notice> : null}
    {visible.map(item => <Link key={item.kind+item.id} to={item.path} onClick={()=>{recordExperience('search_selected');onSelected();}}><span className="grow">{item.name}<small className="faint"> · {labels[item.kind]}</small></span><ArrowRight size={15}/></Link>)}
    {!busy && !error && !visible.length ? <p role="status">没有找到“{query}”。试试应用名、知识库名或文件名。</p> : null}
  </div>;
}
