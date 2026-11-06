import ReactMarkdown from 'react-markdown';
import { useToast } from './ui';
import remarkGfm from 'remark-gfm';
import { useState, type ReactNode } from 'react';
function CodeBlock({children}: {children?:ReactNode}) {
  const toast=useToast();
  const [copied,setCopied] = useState(false);
  return <div className="answer-code"><button className="btn sm" onClick={async event => {
    const content = event.currentTarget.parentElement?.querySelector('pre')?.textContent ?? '';
    try {await navigator.clipboard.writeText(content);setCopied(true);} catch {setCopied(false);toast('复制失败，请选择代码手动复制','error');}
  }}>{copied ? '已复制代码' : '复制代码'}</button><pre>{children}</pre></div>;
}
export function Markdown({text}: {text:string}) {
  return <div className="doc answer-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    pre: ({children}) => <CodeBlock>{children}</CodeBlock>,
    table: ({children}) => <div className="answer-table"><table>{children}</table></div>,
    img: ({alt}) => <span className="faint">[图片：{alt || '未命名'}，未自动加载外部资源]</span>,
    a: ({href,children}) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
  }}>{text}</ReactMarkdown></div>;
}
