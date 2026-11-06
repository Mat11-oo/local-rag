import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth';
import { ToastProvider } from './components/ui';
import './styles.css';
import './legacy-style.css';
import { ThemeRoot } from './theme';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeRoot><BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter></ThemeRoot>
  </StrictMode>,
);
