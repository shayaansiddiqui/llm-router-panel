import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  BookOpenText,
  Braces,
  Database,
  Gauge,
  KeyRound,
  ListChecks,
  Loader2,
  LogOut,
  Network,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
  Trash2,
  Workflow,
} from 'lucide-react';
import './styles.css';
import { Card, DataTable, EmptyState, Loading, Metric, ShadSelect, StatusBadge as Badge } from '@/components/common';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { APIKeys } from '@/pages/APIKeys';
import { APIDocs } from '@/pages/APIDocs';
import { Login } from '@/pages/Login';
import { API_BASE_URL, PUBLIC_GATEWAY_URL, api, clearAdminToken, getAdminToken } from '@/lib/api';
import { cn } from './lib/utils';

const pages = [
  { name: 'Dashboard', icon: Gauge },
  { name: 'Providers', icon: Server },
  { name: 'Models', icon: Braces },
  { name: 'API Keys', icon: KeyRound },
  { name: 'API Docs', icon: BookOpenText },
  { name: 'Logs', icon: ListChecks },
];

function Dashboard({ refreshKey }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    api('/api/dashboard').then(setData).catch(console.error);
  }, [refreshKey]);

  if (!data) {
    return <Loading label="Loading dashboard" />;
  }

  return (
    <section className="grid gap-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric icon={Server} label="Providers" value={data.provider_count} />
        <Metric icon={Activity} label="Active Providers" value={data.active_provider_count} />
        <Metric icon={Braces} label="Models" value={data.model_count} />
        <Metric icon={Database} label="Requests Logged" value={data.log_count} />
      </div>
      <Card title="Recent Requests" description="Latest gateway attempts recorded by SQLite.">
        <LogTable logs={data.recent_logs} />
      </Card>
    </section>
  );
}

function Providers({ providers, refresh }) {
  const blank = { name: '', endpoint_url: '', api_key: '', is_active: true, priority: 1, timeout_seconds: '' };
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(blank);
  const [fetchingProviderId, setFetchingProviderId] = useState(null);
  const [fetchMessage, setFetchMessage] = useState('');

  function startEdit(provider) {
    setEditing(provider.id);
    setForm({ ...provider, timeout_seconds: provider.timeout_seconds || '', api_key: provider.api_key || '' });
  }

  async function submit(event) {
    event.preventDefault();
    const body = {
      ...form,
      priority: Number(form.priority || 1),
      timeout_seconds: form.timeout_seconds ? Number(form.timeout_seconds) : null,
    };
    if (editing) {
      await api(`/api/providers/${editing}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      const result = await api('/api/providers', { method: 'POST', body: JSON.stringify(body) });
      if (result.model_fetch?.error) {
        setFetchMessage(`${result.name}: provider saved, but models could not be fetched. ${result.model_fetch.error}`);
      } else if (result.model_fetch) {
        setFetchMessage(`${result.name}: ${result.model_fetch.created} model(s) imported.`);
      }
    }
    setForm(blank);
    setEditing(null);
    refresh();
  }

  async function remove(id) {
    await api(`/api/providers/${id}`, { method: 'DELETE' });
    refresh();
  }

  async function fetchModels(provider) {
    setFetchingProviderId(provider.id);
    setFetchMessage('');
    try {
      const result = await api(`/api/providers/${provider.id}/fetch-models`, { method: 'POST' });
      setFetchMessage(`${provider.name}: ${result.created} new model(s), ${result.skipped} already existed.`);
      refresh();
    } catch (error) {
      setFetchMessage(`${provider.name}: ${error.message}`);
    } finally {
      setFetchingProviderId(null);
    }
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <Card title={editing ? 'Edit Provider' : 'Add Provider'} description="Register an OpenAI-compatible backend URL.">
        <form className="grid gap-4" onSubmit={submit}>
          <Label className="grid gap-2">Name<Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Label>
          <Label className="grid gap-2">
            Endpoint URL
            <Input value={form.endpoint_url} onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })} placeholder="https://ai-1.gettingstarted.app" required />
          </Label>
          <Label className="grid gap-2">API Key<Input value={form.api_key || ''} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="Optional provider key" /></Label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Label className="grid gap-2">Priority<Input type="number" min="1" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} /></Label>
            <Label className="grid gap-2">Timeout<Input type="number" value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} placeholder="Default" /></Label>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm({ ...form, is_active: Boolean(checked) })} />
            Active
          </label>
          <div className="flex gap-2">
            <Button type="submit"><Plus className="h-4 w-4" />{editing ? 'Save' : 'Create'}</Button>
            {editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</Button>}
          </div>
        </form>
      </Card>

      <Card title="Providers" description="Failover order is controlled by priority, then creation order.">
        <div className="grid gap-3">
          {fetchMessage && (
            <div className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              {fetchMessage}
            </div>
          )}
          {providers.map((provider) => (
            <div className="flex flex-col gap-4 rounded-lg border bg-background p-4 sm:flex-row sm:items-center sm:justify-between" key={provider.id}>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{provider.name}</h3>
                  <Badge active={provider.is_active} />
                </div>
                <p className="mt-1 truncate text-sm text-muted-foreground">{provider.endpoint_url}</p>
                <p className="mt-1 text-xs text-muted-foreground">Priority {provider.priority}{provider.timeout_seconds ? ` · ${provider.timeout_seconds}s timeout` : ''}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" onClick={() => fetchModels(provider)} disabled={fetchingProviderId === provider.id}>
                  {fetchingProviderId === provider.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Fetch models
                </Button>
                <Button variant="outline" size="sm" onClick={() => startEdit(provider)}>Edit</Button>
                <Button variant="destructive" size="icon" onClick={() => remove(provider.id)} aria-label="Delete provider"><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
          ))}
          {!providers.length && <EmptyState>No providers configured.</EmptyState>}
        </div>
      </Card>
    </section>
  );
}

function Models({ providers, refreshKey }) {
  const [models, setModels] = useState([]);
  const providerName = useMemo(() => Object.fromEntries(providers.map((p) => [p.id, p.name])), [providers]);

  useEffect(() => {
    api('/api/models').then(setModels).catch(console.error);
  }, [refreshKey]);

  async function remove(id) {
    await api(`/api/models/${id}`, { method: 'DELETE' });
    setModels(models.filter((model) => model.id !== id));
  }

  return (
    <section className="grid gap-5">
      <Card title="Models" description="Models are imported automatically from each provider's /v1/models endpoint.">
        <DataTable
          headers={['Name', 'Provider', 'Status', '']}
          rows={models.map((model) => [
            <span className="font-medium">{model.display_name || model.name}</span>,
            providerName[model.provider_id] || 'Any',
            <Badge active={model.is_active} />,
            <Button variant="destructive" size="icon" onClick={() => remove(model.id)} aria-label="Delete model"><Trash2 className="h-4 w-4" /></Button>,
          ])}
        />
      </Card>
    </section>
  );
}

function RoutingRules({ providers, refreshKey }) {
  const [rules, setRules] = useState([]);
  const [form, setForm] = useState({ name: '', model_pattern: '*', provider_id: '', priority: 1, is_active: true });
  const providerName = useMemo(() => Object.fromEntries(providers.map((p) => [p.id, p.name])), [providers]);

  useEffect(() => {
    api('/api/routing-rules').then(setRules).catch(console.error);
  }, [refreshKey]);

  async function submit(event) {
    event.preventDefault();
    await api('/api/routing-rules', {
      method: 'POST',
      body: JSON.stringify({ ...form, provider_id: form.provider_id ? Number(form.provider_id) : null, priority: Number(form.priority || 1) }),
    });
    setForm({ name: '', model_pattern: '*', provider_id: '', priority: 1, is_active: true });
    api('/api/routing-rules').then(setRules);
  }

  async function remove(id) {
    await api(`/api/routing-rules/${id}`, { method: 'DELETE' });
    setRules(rules.filter((rule) => rule.id !== id));
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <Card title="Add Routing Rule" description="Match requested model names with wildcard patterns.">
        <form className="grid gap-4" onSubmit={submit}>
          <Label className="grid gap-2">Name<Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Prefer Olares for Llama" required /></Label>
          <Label className="grid gap-2">Model Pattern<Input value={form.model_pattern} onChange={(e) => setForm({ ...form, model_pattern: e.target.value })} placeholder="llama*" /></Label>
          <Label className="grid gap-2">
            Provider
            <ShadSelect
              value={form.provider_id}
              onChange={(value) => setForm({ ...form, provider_id: value })}
              placeholder="No provider"
              options={[{ value: '', label: 'No provider' }, ...providers.map((provider) => ({ value: String(provider.id), label: provider.name }))]}
            />
          </Label>
          <Label className="grid gap-2">Priority<Input type="number" min="1" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} /></Label>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm({ ...form, is_active: Boolean(checked) })} />
            Active
          </label>
          <Button type="submit" className="w-fit"><Plus className="h-4 w-4" />Create</Button>
        </form>
      </Card>

      <Card title="Rules" description="Lower priority numbers are evaluated first.">
        <DataTable
          headers={['Rule', 'Pattern', 'Provider', 'Priority', '']}
          rows={rules.map((rule) => [
            <span className="font-medium">{rule.name}</span>,
            <code className="rounded bg-muted px-2 py-1 text-xs">{rule.model_pattern}</code>,
            providerName[rule.provider_id] || 'None',
            rule.priority,
            <Button variant="destructive" size="icon" onClick={() => remove(rule.id)} aria-label="Delete rule"><Trash2 className="h-4 w-4" /></Button>,
          ])}
        />
      </Card>
    </section>
  );
}

function Logs({ refreshKey }) {
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    api('/api/logs').then(setLogs).catch(console.error);
  }, [refreshKey]);

  return (
    <Card title="Request Logs" description="Last 200 gateway attempts.">
      <LogTable logs={logs} />
    </Card>
  );
}

function LogTable({ logs }) {
  return (
    <DataTable
      headers={['Time', 'Model', 'Provider', 'Status', 'Latency']}
      rows={(logs || []).map((log) => [
        new Date(log.created_at).toLocaleString(),
        log.requested_model || '-',
        log.provider_name || '-',
        <Badge active={log.status === 'success'} label={log.status} />,
        `${log.duration_ms} ms`,
      ])}
      empty="No request logs yet."
    />
  );
}

function AdminConsole({ onLogout }) {
  const [page, setPage] = useState('Dashboard');
  const [providers, setProviders] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);

  function refresh() {
    setRefreshKey((value) => value + 1);
  }

  useEffect(() => {
    api('/api/providers').then(setProviders).catch(console.error);
  }, [refreshKey]);

  const headerUrl = page === 'API Docs' ? PUBLIC_GATEWAY_URL : API_BASE_URL;

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-72 border-r bg-card lg:block">
        <div className="flex h-16 items-center gap-3 border-b px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Workflow className="h-5 w-5" />
          </div>
          <div className="grid">
            <strong className="text-sm">LLM Gateway</strong>
            <span className="text-xs text-muted-foreground">Admin Console</span>
          </div>
        </div>
        <nav className="grid gap-1 p-3">
          {pages.map(({ name, icon: Icon }) => (
            <button
              key={name}
              className={cn(
                'flex h-10 items-center gap-3 rounded-md px-3 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
                page === name && 'bg-accent text-accent-foreground'
              )}
              onClick={() => setPage(name)}
            >
              <Icon className="h-4 w-4" />
              {name}
            </button>
          ))}
        </nav>
      </aside>

      <div className="lg:pl-72">
        <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
          <div className="flex min-h-16 flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between lg:px-8">
            <div className="min-w-0">
              <div className="flex items-center gap-2 lg:hidden">
                <Network className="h-5 w-5 text-primary" />
                <span className="text-sm font-semibold">LLM Gateway</span>
              </div>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight lg:mt-0">{page}</h1>
              <p className="truncate text-sm text-muted-foreground">{headerUrl}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge active={providers.some((provider) => provider.is_active)} label={`${providers.filter((provider) => provider.is_active).length} active`} />
              <Button variant="outline" onClick={refresh}><RefreshCw className="h-4 w-4" />Refresh</Button>
              <Button variant="ghost" onClick={onLogout}><LogOut className="h-4 w-4" />Logout</Button>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto border-t px-4 py-2 lg:hidden">
            {pages.map(({ name, icon: Icon }) => (
              <Button key={name} variant={page === name ? 'secondary' : 'ghost'} size="sm" onClick={() => setPage(name)} className="shrink-0">
                <Icon className="h-4 w-4" />
                {name}
              </Button>
            ))}
          </nav>
        </header>

        <main className="px-4 py-6 lg:px-8">
          {page === 'Dashboard' && <Dashboard refreshKey={refreshKey} />}
          {page === 'Providers' && <Providers providers={providers} refresh={refresh} />}
          {page === 'Models' && <Models providers={providers} refreshKey={refreshKey} />}
          {page === 'API Keys' && <APIKeys providers={providers} refreshKey={refreshKey} />}
          {page === 'API Docs' && <APIDocs providers={providers} refreshKey={refreshKey} />}
          {page === 'Logs' && <Logs refreshKey={refreshKey} />}
        </main>
      </div>
    </div>
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
