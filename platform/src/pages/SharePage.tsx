import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { fdeApi, type FDEApp } from '../api/fde';
import { ChatPanel } from '../components/ChatPanel';
import { AppTile, Loading, Notice } from '../components/ui';

/** 免登录分享页：只展示应用本身，不显示平台导航。 */
export function SharePage() {
  const { token = '' } = useParams();
  const [app, setApp] = useState<FDEApp | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { fdeApi.publicShare(token).then(setApp).catch((caught) => setError(errorMessage(caught))); }, [token]);

  if (error) return <div className="login-shell"><div className="card pad" style={{ maxWidth: 420 }}><Notice tone="error" title="无法打开分享链接">{error}</Notice></div></div>;
  if (!app) return <Loading />;
  const manifest = app.published_version?.manifest ?? app.manifest;
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>
      <header className="row" style={{ padding: '12px 20px', background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
        <AppTile templateKey={manifest.template_key} type={manifest.type} size="sm" />
        <strong>{app.name}</strong><span className="faint">{app.description}</span>
      </header>
      <main style={{ flex: 1, minHeight: 0, maxWidth: 960, width: '100%', margin: '0 auto', background: 'var(--surface)' }}>
        <ChatPanel appId={app.id} manifest={manifest} mode="share" shareToken={token} />
      </main>
    </div>
  );
}
