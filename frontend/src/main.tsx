import React from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp } from 'antd';
import { ThemeRoot } from './theme';
import { WorkspaceProvider } from './store';
import App from './App';
import './styles.css';
const PrototypeApp = React.lazy(() => import('./prototype/PrototypeApp'));
const isPrototype = new URLSearchParams(window.location.search).get('view') === 'prototype-1';
ReactDOM.createRoot(document.getElementById('root')!).render(
 <React.StrictMode><ThemeRoot><AntApp>{isPrototype?<React.Suspense fallback={<div className="page-loading">正在打开交互原型…</div>}><PrototypeApp/></React.Suspense>:<WorkspaceProvider><App/></WorkspaceProvider>}</AntApp></ThemeRoot></React.StrictMode>
);
