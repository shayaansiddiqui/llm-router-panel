import { useEffect, useState } from 'react';
import { Braces, KeyRound, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { ApiKeyAccessScope } from '@/components/ApiKeyAccessScope';
import { ApiKeySecretCell } from '@/components/ApiKeySecretCell';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, DataTable, StatusBadge } from '@/components/common';
import { api } from '@/lib/api';

export function APIKeys({ providers, refreshKey }) {
  const [apiKeys, setApiKeys] = useState([]);
  const [models, setModels] = useState([]);
  const [visibleKeyIds, setVisibleKeyIds] = useState([]);
  const [copiedKeyId, setCopiedKeyId] = useState(null);
  const [regeneratingKeyId, setRegeneratingKeyId] = useState(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [form, setForm] = useState({ name: '', provider_ids: [], model_ids: [], is_active: true });
  const activeKeyCount = apiKeys.filter((apiKey) => apiKey.is_active).length;

  function load() {
    api('/api/api-keys').then(setApiKeys).catch(console.error);
    api('/api/models').then(setModels).catch(console.error);
  }

  useEffect(() => {
    load();
  }, [refreshKey]);

  async function submit(event) {
    event.preventDefault();
    setIsCreating(true);
    try {
      await api('/api/api-keys', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          provider_ids: form.provider_ids.map(Number),
          model_ids: form.model_ids.map(Number),
        }),
      });
      setForm({ name: '', provider_ids: [], model_ids: [], is_active: true });
      load();
      setIsCreateOpen(false);
    } finally {
      setIsCreating(false);
    }
  }

  function openCreateModal() {
    setForm({ name: '', provider_ids: [], model_ids: [], is_active: true });
    setIsCreateOpen(true);
  }

  function toggleKeyVisibility(id) {
    setVisibleKeyIds((current) => (current.includes(id) ? current.filter((keyId) => keyId !== id) : [...current, id]));
  }

  async function copyApiKey(apiKey) {
    if (!apiKey.key_value) return;
    await navigator.clipboard.writeText(apiKey.key_value);
    setCopiedKeyId(apiKey.id);
    window.setTimeout(() => setCopiedKeyId(null), 1500);
  }

  async function regenerateApiKey(apiKey) {
    setRegeneratingKeyId(apiKey.id);
    try {
      const updated = await api(`/api/api-keys/${apiKey.id}/regenerate`, { method: 'POST' });
      setApiKeys((current) => current.map((item) => (item.id === apiKey.id ? { ...item, ...updated } : item)));
      setVisibleKeyIds((current) => (current.includes(apiKey.id) ? current : [...current, apiKey.id]));
      await navigator.clipboard.writeText(updated.api_key);
      setCopiedKeyId(apiKey.id);
      window.setTimeout(() => setCopiedKeyId(null), 1500);
    } finally {
      setRegeneratingKeyId(null);
    }
  }

  async function remove(id) {
    await api(`/api/api-keys/${id}`, { method: 'DELETE' });
    setApiKeys(apiKeys.filter((apiKey) => apiKey.id !== id));
  }

  return (
    <section className="grid gap-5">
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={KeyRound} label="Active keys" value={activeKeyCount} />
        <MetricCard icon={ShieldCheck} label="Provider scopes" value={providers.length} />
        <MetricCard icon={Braces} label="Model scopes" value={models.length} />
      </div>

      <Card
        title="Issued API Keys"
        description="Manage client access to the gateway."
        action={
          <Button type="button" onClick={openCreateModal}>
            <Plus className="h-4 w-4" />
            Create API Key
          </Button>
        }
      >
        <DataTable
          headers={['Name', 'Secret', 'Provider scope', 'Model scope', 'Status', '']}
          empty={
            <div>
              <div className="font-medium text-foreground">No API keys yet</div>
              <div className="mt-1 text-sm text-muted-foreground">Create a key to start protecting gateway traffic.</div>
            </div>
          }
          rows={apiKeys.map((apiKey) => [
            <span className="font-medium">{apiKey.name}</span>,
            <ApiKeySecretCell
              apiKey={apiKey}
              isVisible={visibleKeyIds.includes(apiKey.id)}
              isCopied={copiedKeyId === apiKey.id}
              isRegenerating={regeneratingKeyId === apiKey.id}
              onToggle={() => toggleKeyVisibility(apiKey.id)}
              onCopy={() => copyApiKey(apiKey)}
              onRegenerate={() => regenerateApiKey(apiKey)}
            />,
            apiKey.provider_names?.length ? apiKey.provider_names.join(', ') : 'All providers',
            apiKey.model_names?.length ? apiKey.model_names.join(', ') : 'All models',
            <StatusBadge active={apiKey.is_active} />,
            <Button variant="destructive" size="icon" onClick={() => remove(apiKey.id)} aria-label="Delete API key"><Trash2 className="h-4 w-4" /></Button>,
          ])}
        />
      </Card>

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Create API Key</DialogTitle>
            <DialogDescription>Issue a client secret for gateway requests.</DialogDescription>
          </DialogHeader>

          <form className="grid gap-5" id="create-api-key-form" onSubmit={submit}>
            <Label className="grid gap-2">
              Key name
              <Input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="Production mobile app"
                required
              />
            </Label>

            <ApiKeyAccessScope
              providers={providers}
              models={models}
              providerIds={form.provider_ids}
              modelIds={form.model_ids}
              onChange={(scope) => setForm((current) => ({ ...current, ...scope }))}
            />

            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <span className="text-sm font-medium">Key status</span>
              <label className="flex items-center gap-2 text-sm font-medium">
                <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm((current) => ({ ...current, is_active: Boolean(checked) }))} />
                Active
              </label>
            </div>
          </form>

          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button type="submit" form="create-api-key-form" disabled={isCreating}>
              {isCreating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create key
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function MetricCard({ icon: Icon, label, value }) {
  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  );
}
