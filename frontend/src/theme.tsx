import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ConfigProvider, Select, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import './theme.css';
type Mode = 'system' | 'light' | 'dark';
function initial(): Mode { try { const value = localStorage.getItem('zhishu.theme'); return value === 'dark' || value === 'light' ? value : 'system'; } catch { return 'system'; } }
const first = initial();
const systemDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;
document.documentElement.dataset.theme = first === 'system' ? systemDark() ? 'dark' : 'light' : first;
const ThemeContext = createContext<{mode:Mode; setMode:(mode:Mode)=>void}>({mode:'system',setMode:()=>{}});
export function ThemeRoot({children}:{children:ReactNode}) {
 const [mode,setMode] = useState<Mode>(first); const [dark,setDark] = useState(systemDark);
 useEffect(()=>{const media=window.matchMedia('(prefers-color-scheme: dark)');const change=()=>setDark(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 const resolved=mode==='system'?(dark?'dark':'light'):mode;
 useEffect(()=>{document.documentElement.dataset.theme=resolved;try{localStorage.setItem('zhishu.theme',mode);}catch{/* In-memory preference remains active. */}},[mode,resolved]);
 return <ThemeContext.Provider value={{mode,setMode}}><ConfigProvider locale={zhCN} theme={{algorithm:resolved==='dark'?antdTheme.darkAlgorithm:antdTheme.defaultAlgorithm,token:{colorPrimary:'#6c5ce7',borderRadius:8,fontSize:13,controlHeight:34,fontFamily:'-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif'},components:{Button:{primaryShadow:'none'},Table:{headerSplitColor:'transparent'},Tabs:{titleFontSize:13}}}}>{children}</ConfigProvider></ThemeContext.Provider>;
}
export function ThemeSelector(){const{mode,setMode}=useContext(ThemeContext);return <Select aria-label="界面主题" style={{width:130}} value={mode} onChange={setMode} options={[{value:'system',label:'跟随系统'},{value:'light',label:'浅色主题'},{value:'dark',label:'深色主题'}]}/>;}
