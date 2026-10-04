import { useState } from 'react';
import { Loader2, Plus, Sparkles, Trash2 } from 'lucide-react';
import { Card, EmptyState, ErrorNotice, StatusBadge as Badge } from '@/components/common';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { useAction } from '@/hooks/use-action';

export function Nodes({ providers, refresh }) {
  const blank = { name: '', endpoint_url: '', api_key: '', is_active: true, priority: 1, timeout_seconds: '' };
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(blank);
  const [fetchingProviderId, setFetchingProviderId] = useState(null);
  const [fetchMessage, setFetchMessage] = useState('');
  const action = useAction();

  function startEdit(provider) {
    setEditing(provider.id);
    setForm({ ...provider, timeout_seconds: provider.timeout_seconds || '', api_key: provider.api_key || '' });
  }

  async function submit(event) {
    event.preventDefault();
    await action.run(async () => {
      const body = {
        ...form,
        priority: Number(form.priority || 1),
        timeout_seconds: form.timeout_seconds ? Number(form.timeout_seconds) : null,
      };
      setFetchMessage('');
      if (editing) {
        await api(`/api/providers/${editing}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        const result = await api('/api/providers', { method: 'POST', body: JSON.stringify(body) });
        if (result.model_fetch?.error) {
          setFetchMessage(`${result.name}: node saved, but models could not be fetched. ${result.model_fetch.error}`);
        } else if (result.model_fetch) {
          setFetchMessage(`${result.name}: ${result.model_fetch.created} model(s) imported.`);
        }
      }
      setForm(blank);
      setEditing(null);
      refresh();
    });
  }

  async function remove(provider) {
    if (!window.confirm(`Remove ${provider.name} from the router? This does not stop gsai on that computer. Review model and API key permissions afterwards.`)) return;
    await action.run(async () => {
      await api(`/api/providers/${provider.id}`, { method: 'DELETE' });
      refresh();
    });
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
      <div className="xl:col-span-2"><ErrorNotice message={action.error} /></div>
      <Card title={editing ? 'Edit node' : 'Register a node'} description="Use the endpoint from gsai status, including /v1. Other OpenAI-compatible backends are supported too.">
        <form className="grid gap-4" onSubmit={submit}>
          <Label className="grid gap-2">Name<Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Label>
          <Label className="grid gap-2">
            Endpoint URL
            <Input value={form.endpoint_url} onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })} placeholder="https://your-computer.example.com/v1" required />
          </Label>
          <Label className="grid gap-2">Node access token<Input type="password" autoComplete="new-password" value={form.api_key || ''} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="Node token, without Bearer prefix" /></Label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Label className="grid gap-2">Priority<Input type="number" min="1" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} /></Label>
            <Label className="grid gap-2">Timeout<Input type="number" value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} placeholder="Default" /></Label>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm({ ...form, is_active: Boolean(checked) })} />
            Enable routing to this node
          </label>
          <div className="flex gap-2">
            <Button type="submit" disabled={action.busy || fetchingProviderId !== null}><Plus className="h-4 w-4" />{action.busy ? 'Saving…' : editing ? 'Save' : 'Create'}</Button>
            {editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</Button>}
          </div>
        </form>
      </Card>

      <Card title="Registered nodes" description="Priority controls failover order. Enabled does not mean online; heartbeat is not implemented.">
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
                  <Badge active={provider.is_active} label={provider.is_active ? 'Enabled' : 'Disabled'} />
                </div>
                <p className="mt-1 truncate text-sm text-muted-foreground">{provider.endpoint_url}</p>
                <p className="mt-1 text-xs text-muted-foreground">Priority {provider.priority}{provider.timeout_seconds ? ` · ${provider.timeout_seconds}s timeout` : ''}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" onClick={() => fetchModels(provider)} disabled={fetchingProviderId !== null || action.busy}>
                  {fetchingProviderId === provider.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Fetch models
                </Button>
                <Button variant="outline" size="sm" disabled={action.busy || fetchingProviderId !== null} onClick={() => startEdit(provider)}>Edit</Button>
                <Button variant="destructive" size="icon" disabled={action.busy || fetchingProviderId !== null} onClick={() => remove(provider)} aria-label={`Remove ${provider.name}`}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
          ))}
          {!providers.length && <EmptyState>No nodes registered. Complete gsai setup and connect on a computer, then add its endpoint here.</EmptyState>}
        </div>
      </Card>
    </section>
  );
}
