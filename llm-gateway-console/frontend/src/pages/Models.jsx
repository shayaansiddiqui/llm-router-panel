import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Card, DataTable, ErrorNotice, Loading, StatusBadge as Badge } from '@/components/common';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useResource } from '@/hooks/use-resource';
import { useAction } from '@/hooks/use-action';
import { RouterDiagnostics } from '@/components/router-diagnostics';

export function Models({ providers, refreshKey }) {
  const [revision, setRevision] = useState(0);
  const { data, loading, error } = useResource('/api/models', `${refreshKey}:${revision}`);
  const action = useAction();
  const providerName = useMemo(() => Object.fromEntries(providers.map((p) => [p.id, p.name])), [providers]);
  async function remove(model) {
    if (!window.confirm(`Remove the router record for ${model.name}? This does not delete the model on the computer. Review client key permissions afterwards.`)) return;
    await action.run(async () => {
      await api(`/api/models/${model.id}`, { method: 'DELETE' });
      setRevision((value) => value + 1);
    });
  }
  if (loading && !data) return <Loading label="Loading model inventory" />;
  return (
    <section className="grid gap-5">
      <ErrorNotice message={error || action.error} />
      <Card title="Model inventory" description="Imported during node registration or Fetch models. Records are not live readiness checks; removed upstream models are not automatically pruned.">
        <DataTable headers={['Model', 'Node', 'Routing', 'Actions']} rows={(data || []).map((model) => [
          <div><span className="font-medium">{model.display_name || model.name}</span><p className="mt-1 font-mono text-xs text-muted-foreground">{model.name}</p></div>,
          providerName[model.provider_id] || 'Unbound / any node',
          <Badge active={model.is_active} label={model.is_active ? 'Enabled' : 'Disabled'} />,
          <Button variant="destructive" size="icon" disabled={action.busy} onClick={() => remove(model)} aria-label={`Remove ${model.name}`}><Trash2 className="h-4 w-4" /></Button>,
        ])} empty="No model records. Register a node, then use Fetch models." />
      </Card>
      <RouterDiagnostics refreshKey={`${refreshKey}:${revision}`} />
    </section>
  );
}
