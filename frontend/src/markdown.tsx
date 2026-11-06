import type { Components } from 'react-markdown';
// Imported content must not silently load third-party image URLs.
export const markdownComponents:Components={
 img:({src,alt})=>typeof src==='string'&&src.startsWith('/api/documents/')?<img src={src} alt={alt||'资料图片'}/>:<span className="muted">外部图片未自动加载{alt?`（${alt}）`:''}，请通过原始文件查看。</span>,
 a:({href,children})=><a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
};
