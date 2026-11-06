import { useEffect, useLayoutEffect, useRef, useState } from 'react';
export function useListState<T>(key:string, initial:T) {
  const [value,setValue]=useState<T>(()=>{try{const stored=sessionStorage.getItem(`local-rag.list.${key}`);const parsed:unknown=stored ? JSON.parse(stored) : initial;return typeof parsed === typeof initial ? parsed as T : initial;}catch{return initial;}});
  useEffect(()=>{try{sessionStorage.setItem(`local-rag.list.${key}`,JSON.stringify(value));}catch{/* Optional view preferences. */}},[key,value]);
  return [value,setValue] as const;
}

export function useListScroll(key:string,ready:boolean) {
 const ref=useRef<HTMLDivElement>(null);
 useLayoutEffect(()=>{
  const node=ref.current;if(!node||!ready)return;
  const storageKey=`local-rag.scroll.${key}`;
  try{node.scrollTop=Number(sessionStorage.getItem(storageKey)??0);}catch{/* Optional preference. */}
  const save=()=>{try{sessionStorage.setItem(storageKey,String(node.scrollTop));}catch{/* Optional preference. */}};
  node.addEventListener('scroll',save,{passive:true});return()=>{save();node.removeEventListener('scroll',save);};
 },[key,ready]);return ref;
}
export function usePageReset(reset:()=>void,filters:string){
 const previous=useRef(filters);
 useEffect(()=>{if(previous.current!==filters){previous.current=filters;reset();}},[filters,reset]);
}
