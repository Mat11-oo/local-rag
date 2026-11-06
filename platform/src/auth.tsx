import { createContext, useCallback, useContext, useEffect, useState, type PropsWithChildren } from 'react';
import { fetchMe, getAccessToken, login as apiLogin, logout as apiLogout, type Me } from './api/auth';
import type { Role } from './types';
import { apiFetch, setLocalMode, ApiError, errorMessage } from './api/client';

type AuthState = {
  me: Me | null;
  loading: boolean;
  connectionError: string;
  connectionStatus: number;
  retry: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setRole: (role: Role) => void;
};

const AuthCtx = createContext<AuthState>({ me: null, loading: true, connectionError: '', connectionStatus: 0, retry: () => undefined, login: async () => undefined, logout: async () => undefined, setRole: () => undefined });

export function AuthProvider({ children }: PropsWithChildren) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState('');
  const [connectionStatus,setConnectionStatus]=useState(0);

  const refresh = useCallback(async (): Promise<Me | null> => {
    setLoading(true);
    setConnectionError('');setConnectionStatus(0);
    try {
      const mode = await apiFetch<{local_no_login: boolean}>('/auth/mode');
      setLocalMode(mode.local_no_login);
      if (!mode.local_no_login && !getAccessToken()) {
        setMe(null);
        return null;
      }
      const loaded = await fetchMe();
      setMe(loaded);
      return loaded;
    } catch (caught) {
      setConnectionError(errorMessage(caught));setConnectionStatus(caught instanceof ApiError ? caught.status : 0);
      setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const expired = () => {setMe(null);setConnectionStatus(401);setConnectionError('登录状态已失效，请重新登录后继续。');};
    window.addEventListener('fde-session-expired', expired);
    return () => window.removeEventListener('fde-session-expired', expired);
  }, [refresh]);

  const login = async (email: string, password: string) => {
    await apiLogin(email, password);
    // 登录成功但取不到账号信息（如没有业务空间权限）时要明确报错，而不是悄悄退回登录页
    if (!(await refresh())) throw new Error('登录成功，但无法获取账号信息，请确认已加入业务空间后重试');
  };

  const logout = async () => {
    await apiLogout();
    setMe(null);
  };

  const setRole = (role: Role) => {
    if (me?.auth_type !== 'local') return;
    window.localStorage.setItem('zhishu.local-role', role);
    // Reset page data as well as navigation when changing the operation view.
    window.location.assign('/workbench');
  };
  return <AuthCtx.Provider value={{ me, loading, connectionError, connectionStatus, retry: () => { void refresh(); }, login, logout, setRole }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export function isManager(role: Role | undefined) {
  return role === 'admin' || role === 'manager';
}
