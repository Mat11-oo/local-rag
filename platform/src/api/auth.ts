import { apiFetch, TOKEN_KEY as tokenKey } from './client';

export function getAccessToken() {
  return window.localStorage.getItem(tokenKey);
}

export function setAccessToken(token: string | null) {
  if (token) window.localStorage.setItem(tokenKey, token);
  else window.localStorage.removeItem(tokenKey);
}

export async function login(email: string, password: string) {
  const response = await apiFetch<{ token: string; user: { id: string; email: string; display_name: string; memberships: Array<{ workspace_id: string; role: 'admin' | 'manager' | 'user' }> } }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
  setAccessToken(response.token);
  return response;
}

export async function logout() {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } finally {
    setAccessToken(null);
  }
}

export type Me = {
  auth_type: string;
  role: 'admin' | 'manager' | 'user';
  workspace_id: string;
  user?: { id: string; email: string; display_name: string };
};

export const fetchMe = () => apiFetch<Me>('/auth/me');
