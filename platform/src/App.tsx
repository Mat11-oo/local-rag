import { lazy, Suspense, type PropsWithChildren } from 'react';
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom';
import { useAuth } from './auth';
import { canVisit, Shell } from './components/Shell';
import { Loading } from './components/ui';
import { ServiceProblem } from './components/ServiceProblem';
const AppEditorPage=lazy(()=>import('./pages/AppEditorPage').then(module=>({default:module.AppEditorPage})));
const AppsPage=lazy(()=>import('./pages/AppsPage').then(module=>({default:module.AppsPage})));
const ChatRunPage=lazy(()=>import('./pages/ChatRunPage').then(module=>({default:module.ChatRunPage})));
const EvaluationSetsPage=lazy(()=>import('./pages/EvaluationSetsPage').then(module=>({default:module.EvaluationSetsPage})));
const ImportWizardPage=lazy(()=>import('./pages/ImportWizardPage').then(module=>({default:module.ImportWizardPage})));
const KnowledgeDetailPage=lazy(()=>import('./pages/KnowledgeDetailPage').then(module=>({default:module.KnowledgeDetailPage})));
const KnowledgeListPage=lazy(()=>import('./pages/KnowledgeListPage').then(module=>({default:module.KnowledgeListPage})));
const LoginPage=lazy(()=>import('./pages/LoginPage').then(module=>({default:module.LoginPage})));
const ObservabilityPage=lazy(()=>import('./pages/ObservabilityPage').then(module=>({default:module.ObservabilityPage})));
const SettingsPage=lazy(()=>import('./pages/SettingsPage').then(module=>({default:module.SettingsPage})));
const SharePage=lazy(()=>import('./pages/SharePage').then(module=>({default:module.SharePage})));
const ToolsPage=lazy(()=>import('./pages/ToolsPage').then(module=>({default:module.ToolsPage})));
const WorkbenchPage=lazy(()=>import('./pages/WorkbenchPage').then(module=>({default:module.WorkbenchPage})));

function Protected({ children }: PropsWithChildren) {
  const { me, loading, connectionError, connectionStatus, retry } = useAuth();
  const location = useLocation();
  if (loading) return <Loading text="正在连接工作空间" />;
  if (connectionError) return <ServiceProblem message={connectionError} status={connectionStatus} onRetry={retry}/>;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (!canVisit(me.role, location.pathname)) return <Shell><ServiceProblem status={403} message="当前操作角色没有访问此功能的权限。"/></Shell>;
  return <Shell>{children}</Shell>;
}

function EditorRoute() {const {appId} = useParams();return <AppEditorPage key={appId}/>;}

export default function App() {
  return (
    <Suspense fallback={<Loading text="正在打开页面…"/>}><Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/share/:token" element={<SharePage />} />
      <Route path="/workbench" element={<Protected><WorkbenchPage /></Protected>} />
      <Route path="/chat/:appId" element={<Protected><ChatRunPage /></Protected>} />
      <Route path="/apps" element={<Protected><AppsPage /></Protected>} />
      <Route path="/apps/:appId" element={<Protected><EditorRoute /></Protected>} />
      <Route path="/knowledge" element={<Protected><KnowledgeListPage /></Protected>} />
      <Route path="/knowledge/:kbId/import" element={<Protected><ImportWizardPage /></Protected>} />
      <Route path="/knowledge/:kbId/*" element={<Protected><KnowledgeDetailPage /></Protected>} />
      <Route path="/observability" element={<Protected><ObservabilityPage /></Protected>} />
      <Route path="/evaluation-sets" element={<Protected><EvaluationSetsPage /></Protected>} />
      <Route path="/tools" element={<Protected><ToolsPage /></Protected>} />
      <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />
      <Route path="/" element={<Navigate to="/workbench" replace />} /><Route path="*" element={<Protected><ServiceProblem status={404} message="页面地址不存在，或入口已经调整。"/></Protected>} />
    </Routes></Suspense>
  );
}
