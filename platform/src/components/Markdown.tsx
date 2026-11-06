import { lazy, Suspense } from 'react';
const Content=lazy(()=>import('./MarkdownContent').then(module=>({default:module.Markdown})));
export function Markdown({text}:{text:string}) {
  return <Suspense fallback={<div style={{whiteSpace:'pre-wrap'}}>{text}</div>}><Content text={text}/></Suspense>;
}
