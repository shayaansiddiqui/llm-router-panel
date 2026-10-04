import { useEffect, useState } from 'react';
import { Card, DataTable, ErrorNotice, Loading } from '@/components/common';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useResource } from '@/hooks/use-resource';
import { useAction } from '@/hooks/use-action';

export function RouterDiagnostics({ refreshKey }) {
  const [pollTick, setPollTick] = useState(0);
  const { data, error, loading } = useResource('/api/router/readiness', `${refreshKey}:${pollTick}`);
  const [text, setText] = useState('');
  const [decision, setDecision] = useState(null);
  const action = useAction();
  useEffect(() => {
    if (data?.mode === 'local_llm') return;
    const preparing = ['running', 'checking'].includes(data?.preparation?.status) ||
      data?.models?.some((model) => model.is_active && model.provider_active && model.current_evaluations >= 20 && !(data.predictors || []).some(
        (predictor) => predictor.model_id === model.id && predictor.status !== 'stale'));
    if (!preparing && !(data?.automatic_preparation && !data?.configured)) return;
    const timer = window.setTimeout(() => setPollTick((value) => value + 1), 3000);
    return () => window.clearTimeout(timer);
  }, [data, pollTick]);
  async function changeDefault(value) {
    await action.run(async () => {
      await api('/api/router/defaults', { method: 'PUT', body: JSON.stringify({ fallback_model_id: value ? Number(value) : null }) });
      setPollTick((tick) => tick + 1);
      setDecision(null);
    });
  }
  async function preview(event) {
    event.preventDefault();
    setDecision(null);
    await action.run(async () => setDecision(await api('/api/router/preview', {
      method: 'POST', body: JSON.stringify({ messages: [{ role: 'user', content: text }] }),
    })));
  }
  if (data?.mode === 'local_llm') return (
    <Card title="Automatic model selection" description="Local Ollama selects from enabled, permitted and reachable models. New imported models enter the candidate list automatically.">
      <ErrorNotice message={error || action.error} />
      <p className="mb-3 text-sm">Selector: {data.selector_model} · Thinking off · {data.selector_available ? 'Installed and Ollama reachable' : 'Selector unavailable'} · Timeout: {data.timeout_seconds}s</p>
      <p className="mb-3 text-sm">Local text chat context: up to {data.local_chat_context_tokens?.toLocaleString()} tokens, bounded by each model’s advertised limit. Thinking remains enabled by model defaults. Automatic streams may try two alternative models if a generation limit produces no final answer.</p>
      {!data.selector_available && <p className="mb-3 text-sm text-destructive">Start local Ollama and install the selector model. Availability checks do not run inference. Explicit model tests remain available.</p>}
      <p className="mb-3 text-sm text-muted-foreground">The selector receives your latest request and up to two previous user excerpts. It returns only a model name. Its judgement is not a measured quality guarantee; no encoder training or benchmark preparation is required in this mode.</p>
      <label className="mb-3 grid gap-2 text-sm">Fallback if the selector fails
        <select className="rounded-md border bg-background p-2" disabled={action.busy} value={data.defaults?.fallback_model_id || ''} onChange={(event) => changeDefault(event.target.value)}>
          <option value="">None — report the selector error</option>
          {data.models.filter((model) => model.is_active && model.provider_active).map((model) => <option key={model.id} value={model.id}>{model.name} — record {model.id}</option>)}
        </select>
      </label>
      <form onSubmit={preview} className="grid gap-3">
        <label htmlFor="routing-preview" className="text-sm font-medium">Preview selection (runs the selector, not the selected answer model)</label>
        <textarea id="routing-preview" value={text} onChange={(event) => { setText(event.target.value); setDecision(null); }} maxLength={6000} rows={3} required className="rounded-md border bg-background p-3 text-sm" placeholder="Enter a sample user request" />
        <Button type="submit" disabled={action.busy || !text.trim()} className="justify-self-start">{action.busy ? 'Selecting…' : 'Preview selection'}</Button>
      </form>
      {decision && <div className="mt-4 grid gap-3" role="status">
        <p className="text-sm">{decision.selected ? `Selected: ${decision.selected.model} on ${decision.selected.provider}` : 'No eligible model.'}</p>
        <p className="text-xs text-muted-foreground">Admin preview; client-key permissions may narrow actual choices. Node capacity is not reserved.</p>
        <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(decision, null, 2)}</pre>
      </div>}
    </Card>
  );
  return (
    <Card title="Automatic selection readiness" description="No model purpose or task labels are required from clients. Automatic selection needs a local encoder and comparable scored evaluation cases; adding a model alone is not calibration.">
      <ErrorNotice message={error || action.error} />
      {loading && !data ? <Loading label="Loading routing readiness" /> : data && <>
        {(!data.configured || !data.dependencies_installed) && <div className="mb-4 rounded-md border bg-muted/30 p-4 text-sm">
          <p className="font-semibold">{data.automatic_preparation ? 'Server-managed preparation' : 'Automatic preparation is disabled'}</p>
          <p className="mt-2">With a direct local Ollama node registered, the server downloads/reuses its pinned encoder and measures 67 short answers and their generation timings per missing or stale model in the background, including SQL concurrency, algorithms, reasoning and security cases. No separate router setup command is needed. It does not download your Ollama models.</p>
          <p className="mt-2">This page updates while preparation is pending. Models and configuration activate together only after success. Generic OpenAI-compatible endpoints are not automatically calibrated by the local Ollama workflow.</p>
          {!data.dependencies_installed && <p className="mt-2 text-destructive">This running environment lacks the current server dependencies. The normal server deployment must install the updated requirements.txt; the server will not mutate its Python environment at runtime.</p>}
        </div>}
        {data.preparation && <p className="mb-3 text-sm" role="status">Preparation: {data.preparation.status} — {data.preparation.message} ({data.preparation.completed}/{data.preparation.total})</p>}
        <p className="mb-3 text-sm">Encoder configuration: {data.configured ? 'Present — loading not checked' : 'Missing'}. Rubric: {data.rubric || 'Not configured'}. Capacity telemetry: not implemented.</p>
        <DataTable headers={['Model', 'Current scored cases', 'Predictor', 'Held-out RMSE']} rows={data.models.map((model) => {
          const predictor = (data.predictors || []).find((item) => item.model_id === model.id);
          return [model.name, model.current_evaluations, predictor?.status || 'Awaiting training', predictor?.validation?.rmse?.toFixed(3) ?? 'Not measured'];
        })} empty="Register model records first." />
        <p className="my-3 text-xs text-muted-foreground">Per-model predictors train in the background on measured answers and use grouped held-out validation. New/stale records do not enter automatic selection before preparation. RMSE is validation error, not a probability of correctness.</p>
        <label className="mb-3 grid gap-2 text-sm">Fallback model
          <select className="rounded-md border bg-background p-2" disabled={action.busy} value={data.defaults?.fallback_model_id || ''} onChange={(event) => changeDefault(event.target.value)}>
            <option value="">Automatic measured default (highest comparable suite score)</option>
            {data.models.filter((model) => model.is_active && model.provider_active).map((model) => <option key={model.id} value={model.id}>{model.name} — record {model.id}</option>)}
          </select>
        </label>
        <p className="mb-3 text-xs text-muted-foreground">Low confidence uses an explicitly labelled default, not a claim of task-specific competence. Fallback still respects permissions, live revision, capabilities and context. Without a prepared compatible model, a service-unavailable response remains necessary.</p>
        <form onSubmit={preview} className="grid gap-3">
          <label htmlFor="routing-preview" className="text-sm font-medium">Inspect a routing decision (no model generation)</label>
          <textarea id="routing-preview" value={text} onChange={(event) => { setText(event.target.value); setDecision(null); }} maxLength={8192} rows={3} required className="rounded-md border bg-background p-3 text-sm" placeholder="Enter a sample user request" />
          <Button type="submit" disabled={action.busy || !text.trim()} className="justify-self-start">{action.busy ? 'Inspecting…' : 'Preview selection'}</Button>
        </form>
        {decision && <div className="mt-4 grid gap-3" role="status">
          <p className="text-sm">{decision.selected ? `Selected: ${decision.selected.model} on ${decision.selected.provider}` : 'No eligible model with sufficient evidence. An explicit model can still be requested.'}</p>
          <p className="text-xs text-muted-foreground">Admin inventory preview; client API-key permissions may narrow actual selection. Upstream inventory is probed, but capacity is not reserved.</p>
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(decision, null, 2)}</pre>
        </div>}
      </>}
    </Card>
  );
}
