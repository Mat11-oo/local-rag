import type { Role } from './types';
let role: Role = 'admin';
let browserId = localStorage.getItem('knowhub-browser-id');
if (!browserId) { browserId = crypto.randomUUID(); localStorage.setItem('knowhub-browser-id', browserId); }
export const setApiRole = (value: Role) => { role = value; };
export const apiHeaders = () => ({ 'X-Role': role, 'X-Browser-Id': browserId! });
export async function api<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
 const headers = { ...apiHeaders(), ...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options.headers };
 const response = await fetch(path, { ...options, headers });
 if (!response.ok) { const result = await response.json().catch(() => ({})); throw new Error(typeof result.detail === 'string' ? result.detail : `请求失败（${response.status}），请检查后端服务`); }
 return response.json();
}
