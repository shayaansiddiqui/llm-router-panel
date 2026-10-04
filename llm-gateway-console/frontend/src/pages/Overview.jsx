import { Activity, ArrowRight, Braces, Server, Workflow } from 'lucide-react';
import { Card, DataTable, EmptyState, Loading, Metric } from '@/components/common';
import { Button } from '@/components/ui/button';
import { LogTable } from '@/components/log-table';
import { useResource } from '@/hooks/use-resource';

export function Overview({ providers, refreshKey, onNavigate }) {
  const { data, loading, error } = useResource('/api/dashboard', refreshKey);
  if (error) return <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm">Could not load the overview: {error}. Use Refresh to retry.</div>;
  if (loading) return <Loading label="Loading router overview" />;
  const metrics = data.attempt_metrics;
  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border bg-card p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-2xl"><p className="text-xs font-semibold uppercase tracking-widest text-primary">Routing workspace</p><h2 className="mt-3 text-2xl font-semibold tracking-tight">One gateway. Your AI computers.</h2><p className="mt-3 text-sm leading-relaxed text-muted-foreground">Register endpoints, import their models, and control where requests go. Clients can specify a model or let Python select from permitted model records using routing preferences and stored evidence.</p></div>
          <Button onClick={() => onNavigate('Nodes')}>Manage nodes<ArrowRight className="h-4 w-4" /></Button>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={Server} label="Registered nodes" value={data.provider_count} />
        <Metric icon={Activity} label="Routing enabled" value={data.active_provider_count} />
        <Metric icon={Braces} label="Model records" value={data.model_count} />
        <Metric icon={Workflow} label="Recorded attempts" value={data.log_count} />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title="Node inventory" description="Enabled is an administrative setting, not proof that a computer is online." action={<Button variant="ghost" size="sm" onClick={() => onNavigate('Nodes')}>View all</Button>}>
          <DataTable headers={['Node', 'Routing', 'Priority']} rows={providers.slice(0, 6).map((provider) => [<div><p className="font-medium">{provider.name}</p><p className="mt-1 max-w-xs truncate text-xs text-muted-foreground">{provider.endpoint_url}</p></div>, provider.is_active ? 'Enabled' : 'Disabled', provider.priority])} empty="No nodes registered. Add a gsai endpoint on the Nodes page." />
        </Card>
        <Card title="Observed performance" description="All-time upstream attempts, including retries; these are not unique client requests.">
          {metrics?.completed_count > 0 ? <dl className="grid gap-4"><div className="flex justify-between gap-3"><dt className="text-sm text-muted-foreground">Successful / completed attempts</dt><dd className="font-semibold">{metrics.success_count} / {metrics.completed_count}</dd></div><div className="flex justify-between gap-3"><dt className="text-sm text-muted-foreground">Average successful duration</dt><dd className="font-semibold">{metrics.average_success_duration_ms == null ? '—' : `${Math.round(metrics.average_success_duration_ms)} ms`}</dd></div><p className="text-xs leading-relaxed text-muted-foreground">Duration includes the upstream response or stream. It is not time to first token, and does not measure answer quality.</p></dl> : <EmptyState>Performance appears after the first completed gateway attempt.</EmptyState>}
        </Card>
      </div>
      <Card title="Routing capabilities" description="What the current backend actually supports.">
        <div className="grid gap-5 md:grid-cols-3">
          <div><p className="text-sm font-semibold">Available now</p><p className="mt-2 text-sm leading-relaxed text-muted-foreground">Model inventory, key permissions, and priority-based failover.</p><Button variant="link" className="mt-2 px-0" onClick={() => onNavigate('Nodes')}>Manage node priorities<ArrowRight className="h-4 w-4" /></Button></div>
          <div><p className="text-sm font-semibold">Node dispatch</p><p className="mt-2 text-sm leading-relaxed text-muted-foreground">Equal-priority nodes share traffic using gateway-observed active requests. Native queue depth, GPU capacity and node heartbeat are not implemented.</p></div>
          <div><p className="text-sm font-semibold">Local AI model selection</p><p className="mt-2 text-sm leading-relaxed text-muted-foreground">Local Ollama selects from the permitted, reachable inventory with thinking off. New imported models enter automatically. This judgement is not a measured quality guarantee. Selector failures use only a configured eligible fallback.</p></div>
        </div>
      </Card>
      <Card title="Recent attempts" description="Each row is an upstream attempt; a failed attempt may be followed by successful failover." action={<Button variant="ghost" size="sm" onClick={() => onNavigate('Requests')}>Inspect requests</Button>}><LogTable logs={data.recent_logs} /></Card>
    </section>
  );
}
