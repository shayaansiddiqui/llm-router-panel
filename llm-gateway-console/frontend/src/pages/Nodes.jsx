import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Clipboard, KeyRound, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Card, DataTable, EmptyState, StatusBadge } from '@/components/common';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';

const expirationOptions = [
  { label: '15 minutes', seconds: 900 },
  { label: '1 hour', seconds: 3600 },
  { label: '24 hours', seconds: 86400 },
];

function displayDate(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
}

function tokenStatus(token) {
  if (token.used_at) return { active: false, label: 'Used' };
  if (new Date(token.expires_at).getTime() <= Date.now()) return { active: false, label: 'Expired' };
  return { active: true, label: 'Ready' };
}

export function Nodes({ refreshKey }) {
  const [nodes, setNodes] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [name, setName] = useState('CLI enrollment');
  const [expiresIn, setExpiresIn] = useState(900);
  const [issuedToken, setIssuedToken] = useState(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [nodeRows, tokenRows] = await Promise.all([
        api('/api/nodes'),
        api('/api/node-enrollment-tokens'),
      ]);
      setNodes(nodeRows);
      setTokens(tokenRows);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const activeCount = useMemo(
    () => nodes.filter((node) => node.status === 'online' && node.provider_active).length,
    [nodes],
  );

  async function createToken(event) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const result = await api('/api/node-enrollment-tokens', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), expires_in_seconds: Number(expiresIn) }),
      });
      setIssuedToken(result);
      setCopied(false);
      await load();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function copyToken() {
    if (!issuedToken?.token) return;
    try {
      await navigator.clipboard.writeText(issuedToken.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function revokeToken(token) {
    if (!window.confirm(`Revoke enrollment token "${token.name}"?`)) return;
    setError('');
    try {
      await api(`/api/node-enrollment-tokens/${encodeURIComponent(token.id)}`, { method: 'DELETE' });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function removeNode(node) {
    const accepted = window.confirm(
      `Remove ${node.hostname}? This deletes its managed tunnel route and cannot be undone.`,
    );
    if (!accepted) return;
    setError('');
    try {
      await api(`/api/nodes/${encodeURIComponent(node.id)}`, { method: 'DELETE' });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section className="grid gap-5">
      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Card title="Connect a Node" description="Create a short-lived, single-use token for gsai connect.">
          <form className="grid gap-4" onSubmit={createToken}>
            <Label className="grid gap-2">
              Token name
              <Input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} required />
            </Label>
            <Label className="grid gap-2">
              Expires after
              <select
                className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                value={expiresIn}
                onChange={(event) => setExpiresIn(Number(event.target.value))}
              >
                {expirationOptions.map((option) => (
                  <option key={option.seconds} value={option.seconds}>{option.label}</option>
                ))}
              </select>
            </Label>
            <Button type="submit" className="w-fit" disabled={submitting || !name.trim()}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create token
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">
              The token can enroll one computer and is never displayed again after this dialog closes.
            </p>
          </form>
        </Card>

        <Card
          title="AI Nodes"
          description={`${activeCount} online · ${nodes.length} connected`}
          action={<Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw className={loading ? 'animate-spin' : ''} />Refresh</Button>}
        >
          {loading && !nodes.length ? (
            <EmptyState>Loading connected nodes…</EmptyState>
          ) : (
            <DataTable
              headers={['Node', 'Model', 'Tunnel', 'Access', 'Status', 'Last seen', '']}
              rows={nodes.map((node) => [
                <div className="grid gap-1">
                  <a className="font-medium hover:underline" href={node.endpoint_url || `https://${node.hostname}/v1`} target="_blank" rel="noreferrer">{node.hostname}</a>
                  <span className="text-xs text-muted-foreground">{node.username || 'unknown'} · {node.computer_name || node.platform}</span>
                </div>,
                <code className="text-xs">{node.model_name}</code>,
                <span className="text-sm">{node.tunnel_name || node.tunnel_id || '-'}</span>,
                <span className="capitalize">{String(node.access_mode || '').replace('_', ' ')}</span>,
                <StatusBadge active={node.status === 'online' && node.provider_active} label={node.status} />,
                <span className="whitespace-nowrap text-xs text-muted-foreground">{displayDate(node.last_seen_at)}</span>,
                <Button variant="destructive" size="icon" onClick={() => removeNode(node)} aria-label={`Remove ${node.hostname}`}><Trash2 /></Button>,
              ])}
              empty="No computers are connected yet. Create a token, then run gsai connect."
            />
          )}
        </Card>
      </div>

      <Card title="Enrollment Tokens" description="Tokens are single-use and should be revoked when no longer needed.">
        <DataTable
          headers={['Name', 'Prefix', 'Status', 'Expires', '']}
          rows={tokens.map((token) => {
            const status = tokenStatus(token);
            return [
              <span className="font-medium">{token.name}</span>,
              <code className="text-xs">{token.token_prefix}…</code>,
              <StatusBadge active={status.active} label={status.label} />,
              <span className="whitespace-nowrap text-sm">{displayDate(token.expires_at)}</span>,
              <Button variant="destructive" size="icon" onClick={() => revokeToken(token)} aria-label={`Revoke ${token.name}`}><Trash2 /></Button>,
            ];
          })}
          empty="No enrollment tokens have been created."
        />
      </Card>

      <Dialog open={Boolean(issuedToken)} onOpenChange={(open) => { if (!open) setIssuedToken(null); }}>
        <DialogContent className="sm:max-w-xl" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Enrollment token created</DialogTitle>
            <DialogDescription>Copy it now. The Gateway stores only its hash and cannot show this value again.</DialogDescription>
          </DialogHeader>
          {issuedToken && (
            <div className="grid gap-3">
              <code className="break-all rounded-lg border bg-muted/40 p-3 text-xs leading-5">{issuedToken.token}</code>
              <div className="rounded-lg border bg-background p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground"><KeyRound className="h-4 w-4" />Run on the computer</div>
                <code className="break-all text-xs">gsai connect --token {issuedToken.token}</code>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIssuedToken(null)}>I stored it safely</Button>
            <Button onClick={copyToken}>{copied ? <Check /> : <Clipboard />}{copied ? 'Copied' : 'Copy token'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
