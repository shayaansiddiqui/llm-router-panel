# LLM Gateway Console

LLM Gateway Console is a small admin panel for managing one public LLM gateway.

New to the project? Start with the [beginner setup and operator guide](docs/console-guide.md):
prerequisites, first login, a real local answer, a second gsai computer, and an
application key. The same handbook is available under **Docs** after signing in.
Installing gsai alone does not install this website or register a node here.

Client applications call one stable API domain:

```text
https://ai.gettingstarted.app
```

The gateway routes requests to configured providers. Clients may specify a
model or omit it for local AI selection. By default, the backend asks local
Ollama `qwen3.5:2b` to select from the permitted, reachable model inventory,
with thinking off and a short JSON-only reply. Clients do not send task labels
or model purpose descriptions. Equal-priority nodes are balanced using gateway-observed
active requests; native GPU capacity and queue telemetry are not implemented.

See [Python model selection](docs/model-selection.md) for the request contract,
profile APIs, scoring policy, uncertainty, and current limitations.

The selector must already be installed in Ollama on the backend computer.
Defaults are `ROUTER_SELECTION_MODE=local_llm`,
`ROUTER_SELECTOR_URL=http://127.0.0.1:11434`, and
`ROUTER_SELECTOR_MODEL=qwen3.5:2b`. Models shows its availability and lets you
preview a decision. Newly imported models enter the dynamic list automatically;
no benchmark preparation or encoder training is required in this mode.
Selection adds a local inference call and is a heuristic, not proof of quality.
Its 15-second deadline includes queue time. On timeout/invalid output, only an
explicitly configured eligible fallback in Models is used; otherwise 503 is
returned. Explicit model requests bypass the selector. Thinking on the answer
model is unchanged. The previous evidence-trained router remains optional under
`ROUTER_SELECTION_MODE=learned`; its calibration requirements apply only there.

```text
Client App
  -> LLM Gateway
  -> Selected Provider
  -> LLM Backend
  -> Response back to Client App
```

The gateway does not run models. It only receives requests, checks access, selects a provider, forwards the request, and logs the result.

## Main Idea

Instead of every app calling different LLM backends directly, all apps call the gateway.

Example provider backends:

```text
olares      -> https://ai-1.gettingstarted.app
mac-studio  -> https://ai-2.gettingstarted.app
```

Client apps only need to know:

```text
https://ai.gettingstarted.app/v1/chat/completions
```

## Playground

Open **Playground** in the console to send a real model request without cURL:

1. Select a model/node pair, or **Automatic model selection** with the local
   selector running. Explicit model tests bypass selection.
2. No client API key is required. With the key field blank, Playground uses
   your signed-in admin session through an admin-only endpoint. To test client
   permissions, optionally enter a gateway client key in **Settings**. This is
   not a gsai node token; client key permissions are enforced when supplied.
3. Enter a prompt and select **Run** (or Cmd/Ctrl + Enter). Optional system
   instructions, temperature, and output limits are in **Settings**.
4. Inspect the answer, returned model name, full response/usage, and elapsed
   time. Switch between **Output** and **JSON**, or copy the response. Use
   **Requests** to inspect the actual upstream attempts and failover.

Blank-key requests use `/api/playground/chat/completions`, which requires a
valid admin session. Client-key requests use `/v1/chat/completions`. This does
not disable authentication on the public gateway or expose upstream tokens.
Both paths share routing, model forwarding, and request logging.

The page uses the current workspace backend (`VITE_API_BASE_URL`), not the
configured public example domain shown in Docs → API reference. Keys are kept only in page memory.
Each submission is a streaming request with bounded conversation memory.
Playground keeps up to ten completed user/assistant turns (at most 64 KiB)
in page memory, never in browser storage. It sends a recent suffix of complete
turns that fits the conservative configured local-chat context budget (16,384
by default; legacy learned mode uses 4,096) after reserving
system text, the current prompt, 1,024 tokens of overhead, and output tokens
(a 2,048-token history reservation when no manual output cap is set; this
reservation does not impose a generation limit on the upstream model).
This byte-based screening is not an exact tokenizer calculation. Older turns
are dropped with a notice; no silent summarization or extra AI call is used.
Only nonempty answers ending normally with `stop` are retained; reasoning,
tool calls, truncated responses, and interrupted generations are excluded.
**New chat**, a model selection change, a system instruction change, or leaving
the page clears memory. Automatic routing may choose a different model on a
follow-up, but the permitted recent conversation is still sent to it. Routing
analysis uses the latest user text and up to two bounded previous user excerpts;
it does not generate a conversation summary.
Thinking and answer chunks update separately as they arrive. If an upstream
returns a normal JSON response instead, Playground can display it as well.
The JSON view reconstructs the completion from streaming chunks; it is not a
raw SSE event log. Usage is displayed when the provider supplies it.
Cancel stops browser waiting but does not guarantee upstream inference stops.
Interrupted streams retain partial text and are marked incomplete. There is
no automatic replay after final-answer text or tool calls. In local-LLM Auto
mode, a reasoning-only `length` finish with no explicit output cap can trigger
up to two alternative models, preserving the original input and permissions.
A visible SSE recovery event clears the failed reasoning from the active view;
the final response reports the answering model. This is a new generation, not
a continuation and not a general detector of wrong answers. Normal stops,
manual limits, explicit model requests and nonstream requests are not replayed.
Requests time out after ten minutes, and response bodies are limited to 2 MiB.
The default upstream timeout is 180 seconds (inactivity between reads, not the
total generation time); explicit node timeouts and environment overrides take
precedence. Reload/restart the backend after changing its environment settings.
Reported duration includes routing and model loading; it is not time to first
token or a quality score. Tests consume the selected computer's resources.

Thinking follows the upstream model's default; Playground does not disable it.
Final answer text appears in **Output**, provider-returned `reasoning` or
`reasoning_content` appears separately in **Reasoning**, and **JSON** preserves
the full response. An empty answer is reported explicitly, never replaced by
raw reasoning JSON. Providers that do not return a reasoning field have no
Reasoning tab.

By default Playground omits `max_tokens`, leaving generation limits to the
provider/model instead of imposing a 2,048-token cap. An optional token limit
can be set up to 8,192 in Settings; thinking may consume the same budget as
the final answer. If `finish_reason` is `length`, the response is marked
incomplete and distinguishes a requested cap from a provider/model limit.
**Use model defaults** removes an optional cap without automatically retrying.
Model context limits, server inactivity timeout, and the ten-minute browser
deadline still apply. A final answer cannot be guaranteed simply by omitting
the output cap. **Run** starts a fresh request, not a continuation.

Direct loopback Ollama text chats on port 11434 use native `/api/chat`, with
`options.num_ctx` defaulting to 16,384 and capped by live `/api/show` metadata.
Set `OLLAMA_CHAT_CONTEXT_TOKENS` to change this allocation; restart the backend.
With no manual cap, native generation uses `num_predict=-1` rather than an
old Modelfile output cap. Thinking settings are not disabled. Larger contexts
consume more RAM/KV-cache memory, so the model’s advertised maximum is not
blindly allocated. Unsupported native payloads (images, tools, extra fields)
and remote/generic providers retain OpenAI forwarding and their runtime defaults.
If native metadata cannot be verified, the OpenAI path is retained; no larger
runtime context is claimed. Header selection IDs describe the initial routing
plan; recovery attempts are recorded separately and the final body identifies
the model that actually answered.

## Public OAuth Pages

The gateway also serves the public publisher resources used by the gsai
Cloudflare OAuth client:

```text
Client URL:          https://ai.gettingstarted.app
Logo URL:            https://ai.gettingstarted.app/gsai-logo.png
Privacy Policy URL:  https://ai.gettingstarted.app/privacy
Terms of Service URL: https://ai.gettingstarted.app/terms
```

The privacy policy and terms are static HTML documents so they remain readable
without the admin session or client-side JavaScript.

## Request Flow

When a client sends a chat request:

1. The gateway receives the request.
2. The gateway checks the client API key.
3. The gateway checks which providers and models that key can use.
4. The gateway reads the requested model, or selects one when omitted/auto.
5. If the request includes a provider name, that provider is used.
6. If no provider is sent, the gateway chooses one automatically.
7. The request is forwarded to the selected provider.
8. The provider response is returned to the client.
9. A request log is saved.

## Automatic Routing

If the client does not send `provider`, the gateway chooses the provider.

Example:

```json
{
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "temperature": 0.7
}
```

Automatic routing uses:

- active/passive provider status
- API key permissions
- requested model
- provider priority
- provider timeout/failure handling

Lower priority numbers run first. Priority `1` is tried before priority `2`.

If the first provider fails or times out, the gateway can try the next valid provider.

## Token Streaming

Clients can request streaming responses with:

```json
{
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "stream": true
}
```

When `stream` is `true`, the gateway forwards the request as a stream and passes token chunks back to the client.

Failover can happen before the stream starts. Once a provider starts streaming tokens, the gateway keeps that stream connected to the same provider.

## Targeted Provider Routing

If the client sends `provider`, the gateway targets that provider by name.

Example:

```json
{
  "provider": "olares",
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "temperature": 0.7
}
```

In this mode, the gateway does not fail over to another provider. It validates the selected provider and forwards the request only there.

The `provider` field is removed before forwarding, so the backend receives a normal OpenAI-compatible request.

## Admin Panel Pages

### Overview

Shows a quick overview of the gateway:

- number of providers
- active providers
- available models
- logged requests
- recent request activity

Also shows all-time completed/successful upstream attempts and average
successful duration. Retries are counted separately; these are not unique
client requests. Streaming duration includes the full stream, not time to
first token. Enabled providers are administrative settings, not live health
signals. The page explicitly separates available routing features from
unimplemented heartbeat and capacity-aware scheduling.

### Nodes

Used to manage LLM backends.

Each provider has:

- name
- endpoint URL
- optional API key
- active/passive status
- priority
- timeout

Nodes are stored as providers in the existing backend API. They can be gsai
computers or other OpenAI-compatible services. Use the endpoint printed by
`gsai status`, including `/v1`, and the node access token without a `Bearer`
prefix. Node registration attempts to import models; **Fetch models** can
retry the import. A failed import does not undo a saved node.

### Models

Shows model records imported from providers. Import is not continuous
synchronization or a readiness probe. Models removed on a computer are not
automatically pruned from the inventory.

Example:

```text
qwen2.5-coder:32b-instruct-q8_0 -> olares
qwen3.6:35b                     -> olares
```

Clients may request models by name or use Python selection. Imported model
names alone do not establish capabilities or task quality; the separate
routing-profile API stores deployed metadata/revisions, and evaluation APIs
store scored shared cases. The Models page shows readiness and selection
diagnostics. If the local selector is unavailable, use an explicit model;
automatic requests fail clearly instead of guessing. See the linked selection
guide for operator setup and limitations.

### API Keys

Used to create client keys for apps and services.

Each API key can allow:

- all providers and all models
- selected providers
- selected models under selected providers

This makes it possible to give different apps different access levels.

### Docs

The built-in handbook is at `#docs`; old `#api-docs` bookmarks still open the
API-reference chapter. It covers operators and application developers, with
chapter navigation and copyable examples:

It includes:

- architecture and a first-run checklist
- router prerequisites, safe .env setup, Windows/macOS/Linux startup and first login
- local Ollama testing versus remote gsai nodes
- gsai installation, Cloudflare account selection, setup/connect/status
- obtaining and rotating node tokens; adding more computers
- node registration and model import
- local selector decisions, runtime context, recovery and limitations
- separate admin, Cloudflare, node and gateway credentials
- operating/updating nodes and diagnosing failures by layer
- local router startup and production handoff checklist
- HTTP API reference and application examples
- creating/scoping/copying a gateway key and checking a real application response
- a glossary and expected success checks, not just model-list screenshots

Docs shows the current workspace backend separately from the configured public
example URL. A configured hostname is not proof of deployment. App clients use
the router URL for the environment actually running, not an individual node.
See the [operator handoff](docs/console-guide.md) for an offline checklist.

### Requests

Shows the latest 200 upstream attempts, with outcome filters, HTTP/error
details, and duration. Failover may produce multiple rows for one client
request. Removing a node or model record requires confirmation and does not
stop gsai or delete the computer's installed models.

Useful for checking:

- requested model
- selected provider
- success or failure
- latency
- provider errors

## Public Endpoint

Chat completions:

```text
POST https://ai.gettingstarted.app/v1/chat/completions
```

Authentication:

```text
Authorization: Bearer <API_KEY>
```

## Local development

Run the backend and frontend in separate terminals. These commands bind to
loopback only and do not deploy to the VPS.

Backend, from `llm-gateway-console/backend`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use the existing local `.env` if present; otherwise create it from
`.env.example` and set your own admin password and session secret.
`ADMIN_CORS_ORIGINS` must include `http://localhost:5173` and
`http://127.0.0.1:5173`. Restart the backend after editing `.env`.
Do not publish credentials or commit the local environment file.

Frontend, from `llm-gateway-console/frontend`:

```sh
npm install
VITE_API_BASE_URL=http://127.0.0.1:8000 VITE_PUBLIC_GATEWAY_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173`; sign in with the backend `.env` admin
credentials. Backend API documentation is at `http://127.0.0.1:8000/docs`.
The backend uses the configured database, so panel mutations change those
records even in local development. Stop each process with `Ctrl+C`.

## Example Request

```bash
curl https://ai.gettingstarted.app/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <API_KEY>" \
  -d '{
    "provider": "olares",
    "model": "qwen2.5-coder:32b-instruct-q8_0",
    "messages": [
      {
        "role": "user",
        "content": "Write a short welcome message."
      }
    ],
    "temperature": 0.7
  }'
```

## Summary

The gateway gives all client apps one stable API endpoint.

Providers can change behind the scenes without changing client apps.

API keys control who can use which providers and models.

Logs show what happened for each request.

The admin panel is only for managing the gateway; client apps should call the public API endpoint.
  
