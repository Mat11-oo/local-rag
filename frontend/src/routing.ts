import type { Page } from './types';

export const pagePaths: Record<Page, string> = {
  overview: '/workbench', assistants: '/apps', knowledge: '/knowledge',
  evaluation: '/evaluation', tools: '/tools', insights: '/insights', settings: '/settings',
  chat: '/chat', tasks: '/knowledge-tasks', models: '/models', logs: '/logs',
};

export function readLocation() {
  const raw = window.location.hash.slice(1).split('?')[0] || '/workbench';
  const path = raw.replace(/\/$/, '') || '/workbench';
  const page = (Object.entries(pagePaths).find(([, value]) => value === path)?.[0]
    || (path.startsWith('/knowledge/') ? 'knowledge' : path.startsWith('/chat/') ? 'chat' : 'overview')) as Page;
  let entityId: string | null = null;
  try { entityId = decodeURIComponent(path.split('/')[2] || '') || null; } catch { /* Fall back to the list for malformed links. */ }
  return { page, entityId, sessionId: new URLSearchParams(window.location.hash.split('?')[1] || '').get('session') };
}

export function canVisit(role: string, page: Page) {
  if (role === 'user') return page === 'overview' || page === 'chat';
  if (role === 'knowledge') return !['models', 'tools', 'settings', 'evaluation'].includes(page);
  return true;
}
