import { useEffect, useMemo, useState } from 'react';
import { BookOpenText, KeyRound, Route, Server, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Callout,
  CodeBlock,
  CopyButton,
  DocsSection,
  ExpandableEndpoint,
  InlineCode,
  MethodPill,
  ReferenceShell,
  SectionCard,
} from '@/components/api-docs';
import { DataTable, ShadSelect, StatusBadge } from '@/components/common';
import { api, PUBLIC_GATEWAY_URL } from '@/lib/api';
import { cn } from '@/lib/utils';

const AUTO_PROVIDER = '__auto__';
const DEFAULT_MODEL = 'qwen2.5-coder:32b-instruct-q8_0';
const SNIPPETS = ['cURL', 'JavaScript', 'Python', 'JSON'];
const PATHS = {
  chat: '/v1/chat/completions',
  models: '/v1/models',
  providers: '/v1/providers',
  health: '/health',
};
const NAV_ITEMS = [
  ['endpoints', 'Endpoints'],
  ['authentication', 'Authentication'],
  ['chat', 'Chat Completions'],
  ['catalog-api', 'Models & Providers'],
  ['routing', 'Routing'],
  ['errors', 'Errors'],
  ['catalog', 'Configured Catalog'],
];

function fieldLabel(value) {
  return <InlineCode>{value}</InlineCode>;
}

function fullUrl(path) {
  return `${PUBLIC_GATEWAY_URL}${path}`;
}

function uniqueModelOptions(sourceModels, fallbackModel, providerNameById) {
  if (!sourceModels.length) {
    return [{ value: fallbackModel, label: fallbackModel }];
  }

  const seen = new Set();
  return sourceModels.reduce((options, model) => {
    if (seen.has(model.name)) return options;
    seen.add(model.name);
    const providerName = providerNameById[model.provider_id];
    options.push({
      value: model.name,
      label: providerName ? `${model.name} (${providerName})` : model.name,
    });
    return options;
  }, []);
}

function providerResponseExample(providers, modelsByProvider) {
  const data = providers.slice(0, 2).map((provider) => ({
    id: provider.name,
    object: 'provider',
    priority: provider.priority,
    models: modelsByProvider[provider.id] || [],
  }));

  return JSON.stringify({ object: 'list', data }, null, 2);
}

function modelsResponseExample(models, providerNameById) {
  const data = models.slice(0, 3).map((model) => ({
    id: model.name,
    object: 'model',
    owned_by: providerNameById[model.provider_id] || 'gateway',
    provider: providerNameById[model.provider_id] || null,
  }));

  return JSON.stringify({ object: 'list', data }, null, 2);
}

export function APIDocs({ providers, refreshKey }) {
  const [models, setModels] = useState([]);
  const [selectedProviderName, setSelectedProviderName] = useState('');
  const [selectedModelName, setSelectedModelName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [prompt, setPrompt] = useState('Write a short welcome message.');
  const [temperature, setTemperature] = useState('0.7');
  const [snippet, setSnippet] = useState('cURL');

  const providerNameById = useMemo(() => Object.fromEntries(providers.map((provider) => [provider.id, provider.name])), [providers]);
  const activeProviders = useMemo(() => providers.filter((provider) => provider.is_active), [providers]);
  const selectedProvider = selectedProviderName === AUTO_PROVIDER
    ? null
    : providers.find((provider) => provider.name === selectedProviderName) || null;
  const visibleModels = useMemo(() => {
    if (!selectedProvider) return models;
    return models.filter((model) => model.provider_id === selectedProvider.id);
  }, [models, selectedProvider]);
  const modelsByProvider = useMemo(() => (
    models.reduce((groups, model) => {
      if (!model.provider_id) return groups;
      groups[model.provider_id] = groups[model.provider_id] || [];
      groups[model.provider_id].push(model.name);
      return groups;
    }, {})
  ), [models]);
  const fallbackModel = visibleModels.find((model) => model.is_active)?.name
    || visibleModels[0]?.name
    || models.find((model) => model.is_active)?.name
    || models[0]?.name
    || DEFAULT_MODEL;
  const modelOptions = useMemo(
    () => uniqueModelOptions(visibleModels.length ? visibleModels : models, fallbackModel, providerNameById),
    [fallbackModel, models, providerNameById, visibleModels],
  );
  const providerOptions = useMemo(() => [
    { value: AUTO_PROVIDER, label: 'Automatic routing' },
    ...providers.map((provider) => ({
      value: provider.name,
      label: `${provider.name}${provider.is_active ? '' : ' (passive)'}`,
    })),
  ], [providers]);
  const numericTemperature = Number.isFinite(Number(temperature)) ? Number(temperature) : 0.7;
  const authToken = apiKey.trim() || '<API_KEY>';

  useEffect(() => {
    api('/api/models').then(setModels).catch(console.error);
  }, [refreshKey]);

  useEffect(() => {
    const defaultProvider = activeProviders[0] || providers[0];
    if (!selectedProviderName) {
      setSelectedProviderName(defaultProvider?.name || AUTO_PROVIDER);
      return;
    }
    if (selectedProviderName !== AUTO_PROVIDER && !providers.some((provider) => provider.name === selectedProviderName)) {
      setSelectedProviderName(defaultProvider?.name || AUTO_PROVIDER);
    }
  }, [activeProviders, providers, selectedProviderName]);

  useEffect(() => {
    if (!visibleModels.some((model) => model.name === selectedModelName)) {
      setSelectedModelName(fallbackModel);
    }
  }, [fallbackModel, selectedModelName, visibleModels]);

  const requestPayload = useMemo(() => ({
    ...(selectedProvider ? { provider: selectedProvider.name } : {}),
    model: selectedModelName || fallbackModel,
    messages: [{ role: 'user', content: prompt || 'Hello' }],
    temperature: numericTemperature,
  }), [fallbackModel, numericTemperature, prompt, selectedModelName, selectedProvider]);
  const requestBody = useMemo(() => JSON.stringify(requestPayload, null, 2), [requestPayload]);
  const snippets = useMemo(() => ({
    cURL: `curl ${fullUrl(PATHS.chat)} \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${authToken}" \\
  -d '${requestBody}'`,
    JavaScript: `const response = await fetch("${fullUrl(PATHS.chat)}", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer ${authToken}"
  },
  body: JSON.stringify(${requestBody})
});

const data = await response.json();`,
    Python: `import requests

response = requests.post(
    "${fullUrl(PATHS.chat)}",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer ${authToken}",
    },
    json=${requestBody},
)

data = response.json()`,
    JSON: requestBody,
  }), [authToken, requestBody]);
  const chatResponseExample = useMemo(() => JSON.stringify({
    id: 'chatcmpl_...',
    object: 'chat.completion',
    model: requestPayload.model,
    choices: [
      {
        index: 0,
        message: { role: 'assistant', content: 'Welcome to the gateway.' },
        finish_reason: 'stop',
      },
    ],
  }, null, 2), [requestPayload.model]);
  const modelsCurl = `curl ${fullUrl(PATHS.models)} \\
  -H "Authorization: Bearer ${authToken}"`;
  const providersCurl = `curl ${fullUrl(PATHS.providers)} \\
  -H "Authorization: Bearer ${authToken}"`;
  const healthCurl = `curl ${fullUrl(PATHS.health)}`;
  const healthResponseExample = JSON.stringify({ status: 'ok' }, null, 2);

  return (
    <section className="grid gap-8">
      <header className="border-b pb-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <BookOpenText className="h-4 w-4" />
              Developer documentation
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">LLM Gateway API</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Public HTTP API for client applications. Use the gateway domain, not provider tunnel URLs, from app code.
            </p>
          </div>

          <div className="w-full rounded-lg border bg-card p-3 shadow-sm lg:max-w-xl">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Base URL</div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <code className="min-w-0 flex-1 overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-sm">{PUBLIC_GATEWAY_URL}</code>
              <CopyButton value={PUBLIC_GATEWAY_URL} label="Copy" variant="outline" className="justify-center" />
            </div>
          </div>
        </div>
      </header>

      <div className="grid gap-8 xl:grid-cols-[190px_minmax(0,1fr)_minmax(380px,440px)]">
        <aside className="hidden xl:block">
          <nav className="sticky top-24 grid gap-1 border-l pl-3 text-sm">
            {NAV_ITEMS.map(([id, label]) => (
              <a key={id} href={`#${id}`} className="rounded-md px-2 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground">
                {label}
              </a>
            ))}
          </nav>
        </aside>

        <main className="grid min-w-0 gap-10">
          <DocsSection id="endpoints" title="Endpoints" description="Paths are relative to the public base URL.">
            <ReferenceShell>
              <ExpandableEndpoint
                method="POST"
                path={PATHS.chat}
                title="Create chat completion"
                description="OpenAI-compatible chat request. Supports optional provider targeting."
                defaultOpen
              >
                <div className="grid gap-4 lg:grid-cols-2">
                  <CodeBlock label="Example request" value={snippets.cURL} />
                  <CodeBlock label="Example response" value={chatResponseExample} />
                </div>
              </ExpandableEndpoint>

              <ExpandableEndpoint
                method="GET"
                path={PATHS.models}
                title="List models"
                description="Returns models visible to the API key, including provider ownership."
              >
                <div className="grid gap-4 lg:grid-cols-2">
                  <CodeBlock label="Example request" value={modelsCurl} />
                  <CodeBlock label="Example response" value={modelsResponseExample(models, providerNameById)} />
                </div>
              </ExpandableEndpoint>

              <ExpandableEndpoint
                method="GET"
                path={PATHS.providers}
                title="List providers"
                description="Returns provider names visible to the API key and their model names."
              >
                <div className="grid gap-4 lg:grid-cols-2">
                  <CodeBlock label="Example request" value={providersCurl} />
                  <CodeBlock label="Example response" value={providerResponseExample(activeProviders, modelsByProvider)} />
                </div>
              </ExpandableEndpoint>

              <ExpandableEndpoint
                method="GET"
                path={PATHS.health}
                title="Health check"
                auth="No auth"
                description="Returns basic process health for uptime checks."
              >
                <div className="grid gap-4 lg:grid-cols-2">
                  <CodeBlock label="Example request" value={healthCurl} />
                  <CodeBlock label="Example response" value={healthResponseExample} />
                </div>
              </ExpandableEndpoint>
            </ReferenceShell>
          </DocsSection>

          <DocsSection id="authentication" title="Authentication">
            <SectionCard>
              <DataTable
                headers={['Header', 'Value', 'Applies to']}
                rows={[
                  [fieldLabel('Authorization'), fieldLabel('Bearer <API_KEY>'), 'All /v1 endpoints when keys exist.'],
                  [fieldLabel('Content-Type'), fieldLabel('application/json'), 'POST request bodies.'],
                ]}
              />
            </SectionCard>
          </DocsSection>

          <DocsSection id="chat" title="Create Chat Completion" description="The gateway forwards a provider-compatible OpenAI chat payload.">
            <div className="grid gap-5">
              <ReferenceShell>
                <div className="flex flex-col gap-3 border-b px-4 py-4 md:flex-row md:items-center md:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <MethodPill method="POST" />
                    <code className="font-mono text-sm font-semibold">{PATHS.chat}</code>
                  </div>
                  <CopyButton value={fullUrl(PATHS.chat)} label="Copy URL" variant="outline" />
                </div>
                <div className="p-4">
                  <DataTable
                    headers={['Body field', 'Type', 'Required', 'Description']}
                    rows={[
                      [fieldLabel('model'), 'string', 'Yes', 'Model requested by the client.'],
                      [fieldLabel('messages'), 'array', 'Yes', 'OpenAI-style chat messages.'],
                      [fieldLabel('provider'), 'string', 'No', 'Provider name. Omit for automatic routing.'],
                      [fieldLabel('temperature'), 'number', 'No', 'Forwarded to the selected provider.'],
                      [fieldLabel('stream'), 'boolean', 'No', 'Accepted as payload; streaming proxy is not defined in this MVP.'],
                    ]}
                  />
                </div>
              </ReferenceShell>

              <div className="grid gap-4 lg:grid-cols-2">
                <CodeBlock label="Request body" value={requestBody} />
                <CodeBlock label="200 response" value={chatResponseExample} />
              </div>
            </div>
          </DocsSection>

          <DocsSection id="catalog-api" title="Models and Providers API">
            <div className="grid gap-5">
              <SectionCard>
                <DataTable
                  headers={['Endpoint', 'Use when', 'Auth']}
                  rows={[
                    [fieldLabel('GET /v1/models'), 'A client needs a model picker or wants to validate model access.', 'Bearer key'],
                    [fieldLabel('GET /v1/providers'), 'A client needs provider targeting. Most clients can skip this and use automatic routing.', 'Bearer key'],
                  ]}
                />
              </SectionCard>

              <div className="grid gap-4 lg:grid-cols-2">
                <CodeBlock label="GET /v1/models response" value={modelsResponseExample(models, providerNameById)} />
                <CodeBlock label="GET /v1/providers response" value={providerResponseExample(activeProviders, modelsByProvider)} />
              </div>
            </div>
          </DocsSection>

          <DocsSection id="routing" title="Routing Rules">
            <SectionCard className="grid gap-4">
              <div className="grid gap-3 lg:grid-cols-2">
                <Callout title="Automatic routing">
                  Omit <InlineCode>provider</InlineCode>. The gateway filters active providers by API key scope, model ownership, routing rules, then priority. It can fail over to the next provider.
                </Callout>
                <Callout title="Targeted provider">
                  Send <InlineCode>provider</InlineCode> as the provider name. The gateway validates that provider/model pair and only tries that provider.
                </Callout>
              </div>

              <DataTable
                headers={['Order', 'Automatic', 'Targeted']}
                rows={[
                  ['1', 'Validate API key scope', 'Validate API key scope'],
                  ['2', 'Filter active providers', 'Resolve provider by name'],
                  ['3', 'Filter by model ownership', 'Check provider is active'],
                  ['4', 'Apply rules, then priority', 'Check provider/model compatibility'],
                  ['5', 'Try candidates with failover', 'Forward to selected provider only'],
                ]}
              />
            </SectionCard>
          </DocsSection>

          <DocsSection id="errors" title="Errors">
            <SectionCard className="grid gap-4">
              <DataTable
                headers={['Status', 'Meaning']}
                rows={[
                  ['400', 'Invalid JSON body, invalid provider type, missing model, or provider/model mismatch.'],
                  ['401', 'Missing, invalid, or inactive API key.'],
                  ['403', 'API key scope does not allow the requested provider or model.'],
                  ['404', 'Requested provider name does not exist.'],
                  ['502', 'Every attempted provider failed.'],
                  ['503', 'No permitted provider is active, or selected provider/model is inactive.'],
                ]}
              />
              <CodeBlock label="Error shape" value={JSON.stringify({ detail: 'API key is not allowed to use this provider.' }, null, 2)} />
            </SectionCard>
          </DocsSection>

          <DocsSection id="catalog" title="Configured Catalog">
            <div className="grid gap-5">
              <SectionCard>
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <Server className="h-4 w-4 text-muted-foreground" />
                  Providers
                </div>
                <DataTable
                  headers={['Name', 'Priority', 'Models', 'Status']}
                  empty="No providers configured."
                  rows={providers.map((provider) => [
                    fieldLabel(provider.name),
                    provider.priority,
                    modelsByProvider[provider.id]?.length || 0,
                    <StatusBadge active={provider.is_active} />,
                  ])}
                />
              </SectionCard>

              <SectionCard>
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <Terminal className="h-4 w-4 text-muted-foreground" />
                  Models
                </div>
                <DataTable
                  headers={['Model', 'Provider', 'Status']}
                  empty="No models imported yet."
                  rows={models.map((model) => [
                    fieldLabel(model.name),
                    providerNameById[model.provider_id] || '-',
                    <StatusBadge active={model.is_active} />,
                  ])}
                />
              </SectionCard>
            </div>
          </DocsSection>
        </main>

        <aside className="grid h-fit gap-4 xl:sticky xl:top-24">
          <SectionCard className="p-0">
            <div className="border-b p-4">
              <div className="flex items-center gap-2 font-semibold">
                <Route className="h-4 w-4 text-muted-foreground" />
                Example request
              </div>
            </div>

            <div className="grid gap-3 p-4">
              <div className="grid gap-2">
                <span className="text-sm font-medium">API key</span>
                <Input value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="lgc_..." />
              </div>
              <div className="grid gap-2">
                <span className="text-sm font-medium">Provider</span>
                <ShadSelect value={selectedProviderName} onChange={setSelectedProviderName} placeholder="Automatic routing" options={providerOptions} />
              </div>
              <div className="grid gap-2">
                <span className="text-sm font-medium">Model</span>
                <ShadSelect value={selectedModelName} onChange={setSelectedModelName} placeholder="Select model" options={modelOptions} />
              </div>
              <div className="grid gap-2">
                <span className="text-sm font-medium">Prompt</span>
                <textarea
                  className="min-h-20 rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <span className="text-sm font-medium">Temperature</span>
                <Input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(event) => setTemperature(event.target.value)} />
              </div>
            </div>
          </SectionCard>

          <ReferenceShell>
            <div className="flex flex-wrap gap-1 border-b p-3">
              {SNIPPETS.map((item) => (
                <Button
                  key={item}
                  type="button"
                  variant={snippet === item ? 'secondary' : 'ghost'}
                  size="sm"
                  onClick={() => setSnippet(item)}
                  className={cn('h-8', snippet === item && 'font-semibold')}
                >
                  {item}
                </Button>
              ))}
            </div>
            <div className="p-3">
              <CodeBlock label={snippet} value={snippets[snippet]} />
            </div>
          </ReferenceShell>

          <SectionCard>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <KeyRound className="h-4 w-4 text-muted-foreground" />
              Required headers
            </div>
            <div className="grid gap-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Authorization</span>
                <InlineCode>Bearer &lt;API_KEY&gt;</InlineCode>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Content-Type</span>
                <InlineCode>application/json</InlineCode>
              </div>
            </div>
          </SectionCard>
        </aside>
      </div>
    </section>
  );
}
