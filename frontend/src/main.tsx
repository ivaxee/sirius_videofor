import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/roboto-condensed/600.css';
import './styles.css';
import App from './App';

// Админка — отдельный чанк: не утяжеляет загрузку для разметчиков.
const Admin = lazy(() => import('./admin/Admin'));
const isAdmin = location.pathname.replace(/\/+$/, '') === '/admin';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isAdmin ? (
      <Suspense fallback={null}>
        <Admin />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
);

if (import.meta.env.PROD && 'serviceWorker' in navigator && !isAdmin) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}
