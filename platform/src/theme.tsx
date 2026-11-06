import { createContext, useContext, useEffect, useState, type PropsWithChildren } from 'react';
type Mode = 'system' | 'light' | 'dark';
function initial(): Mode {
  try { const saved = localStorage.getItem('zhishu.theme'); return saved === 'light' || saved === 'dark' ? saved : 'system'; }
  catch { return 'system'; }
}
const ThemeContext = createContext<{mode: Mode; setMode: (mode: Mode) => void}>({mode: 'system', setMode: () => undefined});
export function ThemeRoot({children}: PropsWithChildren) {
  const [mode, setMode] = useState<Mode>(initial);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches);
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const change = () => setSystemDark(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = mode === 'system' ? systemDark ? 'dark' : 'light' : mode;
    try { localStorage.setItem('zhishu.theme', mode); } catch { /* Keep the current session preference. */ }
  }, [mode, systemDark]);
  return <ThemeContext.Provider value={{mode, setMode}}>{children}</ThemeContext.Provider>;
}
export function ThemeSelector() {
  const {mode, setMode} = useContext(ThemeContext);
  return <select className="select" aria-label="界面主题" value={mode} onChange={event => setMode(event.target.value as Mode)}>
    <option value="system">跟随系统</option><option value="light">浅色主题</option><option value="dark">深色主题</option>
  </select>;
}
