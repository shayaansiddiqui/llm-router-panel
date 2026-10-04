import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { Loading } from '@/components/common';
import { ConsoleLayout, consolePages } from '@/components/console-layout';
import { APIKeys } from '@/pages/APIKeys';
import { Docs } from '@/pages/Docs';
import { Login } from '@/pages/Login';
import { Overview } from '@/pages/Overview';
import { Nodes } from '@/pages/Nodes';
import { Models } from '@/pages/Models';
import { Requests } from '@/pages/Requests';
import { Playground } from '@/pages/Playground';
import { api, clearAdminToken, getAdminToken } from '@/lib/api';
import { useResource } from '@/hooks/use-resource';

function pageFromLocation() {
  const route = window.location.hash.slice(1);
  if (route === 'api-docs') return 'Docs';
  return consolePages.find((item) => item.name.toLowerCase().replaceAll(' ', '-') === route)?.name || 'Overview';
}

function AdminConsole({ onLogout }) {
  const [page, setPage] = useState(pageFromLocation);
  const [refreshKey, setRefreshKey] = useState(0);
  const { data, loading, error } = useResource('/api/providers', refreshKey);
  const providers = data || [];
  useEffect(() => {
    const handleNavigation = () => setPage(pageFromLocation());
    window.addEventListener('hashchange', handleNavigation);
    return () => window.removeEventListener('hashchange', handleNavigation);
  }, []);
  function navigate(name) {
    window.location.hash = name.toLowerCase().replaceAll(' ', '-');
    setPage(name);
  }
  function refresh() { setRefreshKey((value) => value + 1); }
  return (
    <ConsoleLayout page={page} onNavigate={navigate} onRefresh={refresh} onLogout={onLogout}>
      {error ? <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm">Could not load nodes: {error}. Use Refresh to retry.</div> :
        loading && !data ? <Loading label="Loading node inventory" /> : <>
          {page === 'Overview' && <Overview providers={providers} refreshKey={refreshKey} onNavigate={navigate} />}
          {page === 'Nodes' && <Nodes providers={providers} refresh={refresh} />}
          {page === 'Models' && <Models providers={providers} refreshKey={refreshKey} />}
          {page === 'Playground' && <Playground providers={providers} refreshKey={refreshKey} />}
          {page === 'API Keys' && <APIKeys providers={providers} refreshKey={refreshKey} />}
          {page === 'Docs' && <Docs providers={providers} refreshKey={refreshKey} onNavigate={navigate} />}
          {page === 'Requests' && <Requests refreshKey={refreshKey} />}
        </>}
    </ConsoleLayout>
  );
}

function App() {
  const [authState, setAuthState] = useState(getAdminToken() ? 'checking' : 'login');

  useEffect(() => {
    if (authState !== 'checking') return;
    api('/api/auth/me')
      .then(() => setAuthState('authenticated'))
      .catch(() => {
        clearAdminToken();
        setAuthState('login');
      });
  }, [authState]);

  function logout() {
    api('/api/auth/logout', { method: 'POST' }).catch(() => {});
    clearAdminToken();
    setAuthState('login');
  }

  if (authState === 'checking') {
    return <Loading label="Checking admin session" />;
  }

  if (authState !== 'authenticated') {
    return <Login onLogin={() => setAuthState('authenticated')} />;
  }

  return <AdminConsole onLogout={logout} />;
}

createRoot(document.getElementById('root')).render(<App />);
