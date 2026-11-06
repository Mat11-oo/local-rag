import type { HTMLAttributes } from 'react';
// Keep nested controls independent, including controls rendered through a portal.
export function cardAction(open:()=>void,label:string):HTMLAttributes<HTMLElement>{
 return {'aria-label':label,role:'link',tabIndex:0,'data-card-action':'true',onClick:e=>{if(!e.currentTarget.contains(e.target as Node)||e.defaultPrevented||(e.target as Element).closest('button,a,input,select,textarea,[role="button"],[role="combobox"],[role="menuitem"]'))return;open();},onKeyDown:e=>{if(e.target!==e.currentTarget||!['Enter',' '].includes(e.key))return;e.preventDefault();open();}} as HTMLAttributes<HTMLElement>;
}
