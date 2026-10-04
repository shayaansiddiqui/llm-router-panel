import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, Loader2, Play, RotateCcw, Settings2, Square, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ErrorNotice, ShadSelect } from '@/components/common';
import { API_BASE_URL, getAdminToken } from '@/lib/api';
import { useResource } from '@/hooks/use-resource';
import { readChatStream } from '@/lib/chat-stream';
import { historyForRequest, retainHistory } from '@/lib/chat-history';

const REQUEST_TIMEOUT_MS = 600000;
const RESPONSE_LIMIT = 2 * 1024 * 1024;

function messageText(value) {
  if (typeof value === 'string') return value;
  if (!Array.isArray(value)) return '';
  return value.map((part) => typeof part === 'string' ? part
    : typeof part?.text === 'string' ? part.text : '').filter(Boolean).join('\n');
}

function completionOutput(body) {
  const choice = body?.choices?.[0];
  const message = choice?.message;
  return {
    answer: messageText(message?.content),
    reasoning: messageText(message?.reasoning) || messageText(message?.reasoning_content),
    finishReason: choice?.finish_reason,
    hasToolCalls: Array.isArray(message?.tool_calls) && message.tool_calls.length > 0,
  };
}

// Bound response memory even if a misconfigured upstream ignores max_tokens.
async function readResponse(response) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('The gateway returned an empty response.');
  const decoder = new TextDecoder();
  let size = 0;
  let text = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > RESPONSE_LIMIT) {
        await reader.cancel();
        throw new Error('Response exceeded the Playground 2 MiB limit.');
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

function responseError(status, payload) {
  const detail = payload?.error?.message || payload?.detail;
  if (typeof detail === 'string') return `HTTP ${status}: ${detail.slice(0, 1000)}`;
  if (status === 401 || status === 403) return `HTTP ${status}: Use an active gateway API key with permission for this model and node.`;
  return `HTTP ${status}: The gateway request failed. Check Requests and model readiness.`;
}

export function Playground({ providers, refreshKey }) {
  const { data, loading, error: inventoryError } = useResource('/api/models', refreshKey);
  const { data: routerStatus } = useResource('/api/router/readiness', refreshKey);
  const [selection, setSelection] = useState('auto');
  const [apiKey, setApiKey] = useState('');
  const [prompt, setPrompt] = useState('');
  const [system, setSystem] = useState('');
  const [temperature, setTemperature] = useState('0.2');
  // Do not impose a small generation cap on thinking models by default.
  const [maxTokens, setMaxTokens] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [routingDecision, setRoutingDecision] = useState('');
  const [history, setHistory] = useState([]);
  const [historyNotice, setHistoryNotice] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [outputView, setOutputView] = useState('answer');
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef(null);
  const activeRequest = useRef(null);
  const models = useMemo(() => (data || []).filter((model) => model.is_active &&
    providers.some((provider) => provider.id === model.provider_id && provider.is_active)), [data, providers]);
  const options = useMemo(() => [
    { value: 'auto', label: 'Automatic model selection' },
    ...models.map((model) => ({ value: String(model.id), label: `${model.name} — ${providers.find((p) => p.id === model.provider_id)?.name}` })),
  ], [models, providers]);

  useEffect(() => () => {
    clearTimeout(copyTimer.current);
    activeRequest.current?.controller.abort();
    activeRequest.current = null;
  }, []);

  function newChat() {
    if (activeRequest.current) return;
    setHistory([]);
    setHistoryNotice('');
    setPrompt('');
    setResult(null);
    setRoutingDecision('');
    setError('');
    setCopied(false);
    setOutputView('answer');
  }

  function changeModel(value) {
    if (activeRequest.current) return;
    newChat();
    setSelection(value);
  }

  async function submit(event) {
    event.preventDefault();
    if (activeRequest.current) return;
    setError('');
    const numericTemperature = Number(temperature);
    setRoutingDecision('');
    const numericTokens = maxTokens.trim() ? Number(maxTokens) : null;
    if (!prompt.trim() || !temperature.trim() ||
        !Number.isFinite(numericTemperature) || numericTemperature < 0 || numericTemperature > 2 ||
        (numericTokens !== null && (!Number.isInteger(numericTokens) || numericTokens < 1 || numericTokens > 8192))) {
      setError('Enter a prompt and temperature between 0 and 2. Leave the token limit blank for model defaults, or enter an integer between 1 and 8192.');
      setSettingsOpen(true);
      return;
    }
    const model = models.find((item) => String(item.id) === selection);
    const provider = model && providers.find((item) => item.id === model.provider_id);
    if (selection !== 'auto' && (!model || !provider)) {
      setError('This model or node is no longer enabled. Select an available model.');
      return;
    }
    const key = apiKey.trim();
    if (key && !/^[\x21-\x7e]+$/.test(key)) {
      setError('Paste the gateway API key without the Bearer prefix or whitespace.');
      return;
    }
    const token = key || getAdminToken();
    if (!token) {
      setError('Your admin session has expired. Sign in again to use Playground.');
      return;
    }
    // Reserve response space for history screening without enforcing that
    // reservation as an upstream generation cap.
    const context = historyForRequest(history, system, prompt, numericTokens ?? 2048,
      routerStatus?.mode === 'local_llm' ? routerStatus.local_chat_context_tokens || 16384 : 4096);
    setHistoryNotice(context.dropped ? `${context.dropped} older turn(s) omitted to fit the conversation budget.` : '');
    const payload = {
      model: model?.name || 'auto',
      ...(provider ? { provider: provider.name } : {}),
      messages: [...(system.trim() ? [{ role: 'system', content: system }] : []), ...context.messages, { role: 'user', content: prompt }],
      temperature: numericTemperature, ...(numericTokens !== null ? { max_tokens: numericTokens } : {}), stream: true,
      stream_options: { include_usage: true },
    };
    const request = { controller: new AbortController(), timedOut: false };
    activeRequest.current = request;
    setBusy(true);
    setResult(null);
    setOutputView('answer');
    setCopied(false);
    const started = performance.now();
    const timer = setTimeout(() => { request.timedOut = true; request.controller.abort(); }, REQUEST_TIMEOUT_MS);
    try {
      // Blank key uses the admin-only endpoint. Never send admin credentials
      // to the public gateway or directly to an upstream model.
      const path = key ? '/v1/chat/completions' : '/api/playground/chat/completions';
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST', credentials: 'omit', signal: request.controller.signal,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      if (activeRequest.current === request) setRoutingDecision(response.headers.get('X-Gateway-Routing-Decision') || '');
      let body;
      if (response.ok && response.headers.get('content-type')?.includes('text/event-stream')) {
        body = await readChatStream(response, (partial) => {
          if (activeRequest.current === request) setResult({ body: partial, streaming: true, tokenBudget: numericTokens, duration: Math.round(performance.now() - started) });
        }, RESPONSE_LIMIT);
      } else {
        const text = await readResponse(response);
        try { body = JSON.parse(text); } catch {
          throw new Error(`HTTP ${response.status}: The gateway returned a non-JSON response. Check the backend and node connection.`);
        }
      }
      if (!response.ok) {
        if (!key && response.status === 401) throw new Error('Your admin session has expired. Sign in again to use Playground.');
        if ((response.status === 401 || response.status === 403) && activeRequest.current === request) setSettingsOpen(true);
        throw new Error(responseError(response.status, body));
      }
      if (!Array.isArray(body.choices) || !body.choices.length) throw new Error('The gateway returned no completion choices.');
      if (activeRequest.current === request) {
        setResult({ body, tokenBudget: numericTokens, duration: Math.round(performance.now() - started) });
        setOutputView('answer');
        const completed = completionOutput(body);
        if (completed.finishReason === 'stop' && completed.answer.trim() && !completed.hasToolCalls) {
          const retained = retainHistory([...context.turns, { user: prompt, assistant: completed.answer, model: body.model || model?.name || 'auto' }]);
          setHistory(retained);
          setPrompt('');
          if (!retained.length) setHistoryNotice('This answer exceeds the session memory limit and was not retained.');
        }
      }
    } catch (failure) {
      if (activeRequest.current === request) {
        setResult((previous) => previous ? { ...previous, streaming: false, interrupted: true, duration: Math.round(performance.now() - started) } : previous);
        setError(request.controller.signal.aborted
          ? (request.timedOut ? 'Request timed out after 10 minutes. Partial output was preserved; the upstream model may still be processing.' : 'Request cancelled. Partial output was preserved; upstream cancellation is not guaranteed.')
          : failure.message || 'Could not reach the gateway.');
      }
    } finally {
      clearTimeout(timer);
      if (activeRequest.current === request) { activeRequest.current = null; setBusy(false); }
    }
  }

  const { answer, reasoning, finishReason, hasToolCalls } = completionOutput(result?.body);
  const truncated = finishReason === 'length';
  const output = outputView === 'json' && result ? JSON.stringify(result.body, null, 2)
    : outputView === 'reasoning' ? reasoning : answer.trim() ? answer : '';
  const emptyAnswerMessage = truncated
    ? 'Generation reached the token limit before producing a final answer.'
    : hasToolCalls ? 'The model returned tool calls, not a final answer. Inspect JSON; Playground does not execute tools.'
    : finishReason === 'content_filter' ? 'The provider filtered this response.'
    : busy ? (reasoning ? 'Thinking… Open Reasoning to follow generation.' : 'Generating…')
    : result?.interrupted ? 'Generation was interrupted before a final answer. Partial reasoning may be available.'
    : 'The provider returned no final answer. Inspect Reasoning or JSON for details.';
  function useModelDefaults() {
    setMaxTokens('');
    setSettingsOpen(true);
  }
  async function copyOutput() {
    try {
      await navigator.clipboard.writeText(output);
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch { setError('Could not copy. Select the response text to copy it manually.'); }
  }
  return (
    <form onSubmit={submit} noValidate className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
        <fieldset disabled={busy || loading} className="w-full min-w-0 sm:max-w-sm">
          <legend className="sr-only">Model and node</legend>
          <ShadSelect value={selection} onChange={changeModel} options={options} />
        </fieldset>
        <div className="flex items-center gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={newChat}><RotateCcw />New chat</Button>
          <Button type="button" variant={settingsOpen ? 'secondary' : 'ghost'} onClick={() => setSettingsOpen((value) => !value)} aria-expanded={settingsOpen} aria-controls="playground-settings"><Settings2 />Settings</Button>
          {busy ? <Button type="button" variant="outline" onClick={() => activeRequest.current?.controller.abort()}><Square />Stop</Button>
            : <Button type="submit" disabled={loading || !models.length || !prompt.trim()}><Play />Run</Button>}
        </div>
      </div>
      {(inventoryError || error) && <div className="max-h-28 shrink-0 overflow-y-auto px-5 pt-4"><ErrorNotice message={inventoryError || error} /></div>}
      {historyNotice && <p role="status" className="shrink-0 px-5 py-2 text-xs text-muted-foreground">{historyNotice}</p>}
      {!loading && !models.length && <p className="shrink-0 px-5 pt-4 text-sm text-muted-foreground">Add a node and fetch its models in <a href="#nodes" className="underline">Nodes</a>.</p>}
      <div className={`relative grid min-h-0 flex-1 overflow-hidden ${settingsOpen ? 'xl:grid-cols-[minmax(0,1fr)_280px]' : ''}`}>
        <div className="grid min-h-0 min-w-0 grid-rows-2 md:grid-cols-2 md:grid-rows-1">
          <section className="flex min-h-0 min-w-0 flex-col overflow-hidden border-b md:border-b-0 md:border-r">
            <div className="flex h-12 shrink-0 items-center justify-between px-5"><label htmlFor="playground-prompt" className="text-sm font-medium">Prompt</label><span className="text-xs text-muted-foreground">⌘ / Ctrl + Enter</span></div>
            {history.length > 0 && <details className="max-h-[40%] shrink-0 overflow-y-auto overscroll-contain border-b px-5 pb-3 text-xs">
              <summary className="cursor-pointer text-muted-foreground">Conversation · {history.length} remembered turn(s)</summary>
              <div className="mt-3 grid gap-3">{history.map((turn, index) => <div key={index} className="grid gap-2 rounded-md bg-muted/30 p-3"><p className="whitespace-pre-wrap break-words"><strong>You</strong><br />{turn.user}</p><p className="whitespace-pre-wrap break-words"><strong>{turn.model}</strong><br />{turn.assistant}</p></div>)}</div>
            </details>}
            <textarea id="playground-prompt" disabled={busy} maxLength={8192} value={prompt} onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }}
              placeholder={history.length ? 'Ask a follow-up…' : 'Write a prompt to test your model…'} className="min-h-0 w-full flex-1 resize-none overflow-y-auto overscroll-contain bg-transparent px-5 pb-6 text-sm leading-7 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40" />
          </section>
          <section className="flex min-h-0 min-w-0 flex-col overflow-hidden" aria-label="Model output" aria-busy={busy}>
            <div className="flex h-12 shrink-0 items-center justify-between gap-2 px-5">
              <div className="flex gap-3" role="group" aria-label="Output format">
                {['answer', ...(reasoning ? ['reasoning'] : []), 'json'].map((view) => <button key={view} type="button" onClick={() => { setOutputView(view); setCopied(false); }} aria-pressed={outputView === view} className={`text-sm ${outputView === view ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{view === 'answer' ? 'Output' : view === 'reasoning' ? 'Reasoning' : 'JSON'}</button>)}
              </div>
              <Button type="button" size="icon-sm" variant="ghost" disabled={!output} onClick={copyOutput} aria-label={copied ? 'Copied' : 'Copy output'}>{copied ? <Check /> : <Copy />}</Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]" tabIndex={0} aria-label="Scrollable response">
            {result ? <>
              {outputView === 'reasoning' && <p className="px-5 pb-3 text-xs text-muted-foreground">Provider-returned reasoning, not the final answer.{busy ? ' Streaming…' : truncated || result?.interrupted ? ' This reasoning is incomplete.' : ''}</p>}
              {result?.interrupted && <p className="px-5 pb-3 text-xs text-destructive">Interrupted — output may be incomplete.</p>}
              {output ? <pre className={`whitespace-pre-wrap break-words px-5 pb-6 text-sm leading-7 ${outputView === 'json' ? 'font-mono text-xs' : 'font-sans'}`}>{output}</pre>
                : <div className="px-5 py-6 text-sm leading-6 text-muted-foreground" role="status"><p>{emptyAnswerMessage}</p>{reasoning && <button type="button" className="mt-3 underline" onClick={() => setOutputView('reasoning')}>View reasoning</button>}</div>}
            </>
              : <div className="flex h-full items-center justify-center px-6 py-6 text-sm text-muted-foreground"><span role="status" className="flex items-center gap-2">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? 'Generating…' : 'Your response will appear here.'}</span></div>}
            {truncated && <div className="mx-5 mb-4 rounded-lg border bg-muted/30 p-3 text-xs leading-5" role="status">
              <p>{answer.trim() ? 'The final answer is incomplete.' : 'The model stopped before generating a final answer.'} {result.tokenBudget !== null ? `A ${result.tokenBudget.toLocaleString()}-token cap was requested; the provider reported a length limit.` : 'No Playground token cap was sent. The provider reported a model/context generation limit.'}</p>
              {result.tokenBudget !== null && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={useModelDefaults} className="mt-2">Use model defaults</Button>}
              <p className="mt-2 text-muted-foreground">{result.tokenBudget !== null ? 'Remove the optional cap before the next run. Explicit output limits do not trigger automatic recovery.' : answer.trim() ? 'Partial final answers are not replayed automatically.' : selection === 'auto' ? 'Automatic recovery could not produce a final answer within the eligible alternatives and attempt limit. Check the model runtime settings.' : 'Explicit model requests do not switch models automatically.'} Received output is preserved.</p>
            </div>}
            </div>
          </section>
        </div>
        {settingsOpen && <aside id="playground-settings" className="absolute inset-y-0 right-0 z-10 flex w-72 max-w-full min-h-0 flex-col overflow-hidden border-l bg-card shadow-lg xl:static xl:w-auto xl:shadow-none">
          <div className="flex h-12 shrink-0 items-center justify-between px-5"><h2 className="text-sm font-medium">Settings</h2><Button type="button" size="icon-sm" variant="ghost" aria-label="Close settings" onClick={() => setSettingsOpen(false)}><X /></Button></div>
          <fieldset disabled={busy} className="grid min-h-0 gap-5 overflow-y-auto overscroll-contain px-5 pb-6">
            <label className="grid gap-2 text-xs font-medium">API key (optional)<Input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Leave blank to use your admin session" /><span className="font-normal leading-5 text-muted-foreground">No key needed. Add a client key only to test its permissions.</span></label>
            <label className="grid gap-2 text-xs font-medium">System instruction<textarea className="min-h-28 w-full resize-y rounded-md border bg-card p-3 text-sm font-normal" maxLength={8192} value={system} onChange={(event) => { setSystem(event.target.value); setHistory([]); setHistoryNotice(''); }} placeholder="Optional instructions for the model" /></label>
            <label className="grid gap-2 text-xs font-medium">Temperature<Input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(event.target.value)} /></label>
            <label className="grid gap-2 text-xs font-medium">Token limit (optional)<Input type="number" min="1" max="8192" step="1" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} placeholder="Model default" /><span className="font-normal leading-5 text-muted-foreground">Blank means no Playground output cap. If set, thinking may count toward it. The provider's context/output limits and request timeout still apply.</span></label>
            <p className="text-xs leading-5 text-muted-foreground">Thinking follows the model's default. Playground does not disable it.</p>
            <p className="text-xs leading-5 text-muted-foreground">Auto uses the router configured on the server. Check Models for selector status. Direct tests bypass automatic selection.</p>
            <p className="text-xs leading-5 text-muted-foreground">Session memory keeps up to six complete turns, subject to the context budget. Reasoning and interrupted answers are not remembered. New chat or changing the model clears memory.</p>
          </fieldset>
        </aside>}
      </div>
      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t px-5 py-3 text-xs text-muted-foreground">
        <span>{result ? `${result.body.model || 'Model not reported'} · ${(result.duration / 1000).toFixed(2)} s ${busy ? 'elapsed · streaming' : 'total'}${Number.isFinite(result.body.usage?.total_tokens) ? ` · ${result.body.usage.total_tokens} tokens` : ''}` : 'Conversation memory stays in this page session.'}</span>
        {result?.body?.gateway_recovery && <span role="status">{result.streaming ? 'Trying another model' : 'Model recovery'} · attempt {result.body.gateway_recovery.attempt}</span>}
        {routingDecision && <span role="status" title={routingDecision}>{routingDecision === 'fallback_selector_error' ? 'Fallback · selector failed' : routingDecision.startsWith('fallback_') ? 'Fallback · insufficient routing confidence' : routingDecision === 'local_llm_selection' ? 'Selected by local AI' : routingDecision === 'learned_selection' ? 'Learned selection' : 'Explicit selection'}</span>}
        <a href="#requests" className="hover:text-foreground">View requests →</a>
      </footer>
    </form>
  );
}
