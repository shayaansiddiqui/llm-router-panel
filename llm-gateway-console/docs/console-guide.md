# Router and gsai operator guide

The console's **Docs** section contains the full interactive handbook, including
the API reference. Open `#docs`; old `#api-docs` bookmarks open its API chapter.
This file is the offline setup and handoff checklist. For detailed routing policy,
read [model selection](model-selection.md).

## Contents

- [Components and ownership](#components-and-ownership)
- [Install the router and sign in](#install-the-router-and-sign-in)
- [Local testing](#local-testing)
- [Connect a remote gsai computer](#connect-a-remote-gsai-computer)
- [Register the node](#register-the-node)
- [Credential handoff](#credential-handoff)
- [Connect your application](#connect-your-application)
- [Verify routing](#verify-routing)
- [Operations and troubleshooting](#operations-and-troubleshooting)
- [Publication checklist](#publication-checklist)
- [Glossary](#glossary)

## Components and ownership

| Component | Where it runs | Responsibility |
| --- | --- | --- |
| Router backend / console | Development computer or VPS | Client API, access checks, selection, dispatch, logs |
| Local 2B selector | Ollama reachable from the backend | Choose an eligible model; not generate the application answer |
| Answer model | Each AI computer | Generate the answer using that computer's resources |
| gsai | Each remotely published AI computer | Set up a model, publish/protect it and manage its background service |

gsai is not the central smart router. `gsai connect` does not automatically
enroll a computer in the console. The node owner supplies connection information;
the router administrator registers it and configures client access.

```text
Application → Router → local 2B selection → eligible node → answer model
```

Start in this order: **install/sign in → first local answer → second computer →
application access → production publication**. If an administrator already gave
you a console URL and login, skip router installation. If you only own an AI
computer, follow the gsai chapter and hand its connection details to the router
administrator; you do not need to run another router.

## Install the router and sign in

### 1. Prerequisites and project files

On the **router computer**, install [Python](https://www.python.org/downloads/),
[Node.js](https://nodejs.org/en/download) (includes npm) and Git. These source
development examples use Python 3.12 and Node.js 22. The frontend uses Vite 6;
see its [runtime requirements](https://v6.vite.dev/guide/). This is not a packaged
production installer. Python dependency downloads can be large.

Obtain the current router checkout from your maintainer. Its root must contain
`llm-gateway-console/backend` and `llm-gateway-console/frontend`; the gsai CLI
repository is a different project. Start the commands below from that root.
If already in backend/frontend, skip the corresponding `cd` line.

Check `python3.12 --version`, `node --version`, `npm --version` and `git --version`.
On Windows use `py -3.12 --version` and `npm.cmd --version`. If a command is
missing, install the prerequisite and reopen the terminal. Ordinary gsai node
owners do **not** need Python, Node.js or Git for the native CLI installation.

### 2. Backend: first installation in terminal A

macOS/Linux:

```sh
cd llm-gateway-console/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
fi
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Windows PowerShell:

```powershell
cd llm-gateway-console/backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Keep any existing `.venv`, `.env` and database. Do not recreate a working
environment unnecessarily. Resolve dependency installation failures before
continuing. Open `backend/.env` in your editor and replace the example values:

- `ADMIN_USERNAME`: your chosen panel login name.
- `ADMIN_PASSWORD`: your own strong password, saved securely.
- `ADMIN_SESSION_SECRET`: the random value printed by the last command.

Do not leave `change-this` values or literal placeholders. Keep other defaults
for the local test. Never commit or share `.env`. Then start the backend, still
in terminal A inside backend:

```sh
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows equivalent:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Check:** leave terminal A running. Expect “Application startup complete”. Open
`http://127.0.0.1:8000/health` in a browser and expect `{"status":"ok"}`. This
checks the router process only, not inference. If the port is occupied, identify
the existing process instead of launching a duplicate.

### 3. Website: terminal B

Open another terminal in the router repository root. macOS/Linux:

```sh
cd llm-gateway-console/frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:8000 VITE_PUBLIC_GATEWAY_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Windows PowerShell:

```powershell
cd llm-gateway-console/frontend
npm.cmd install
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_PUBLIC_GATEWAY_URL = "http://127.0.0.1:8000"
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

### 4. First login and later launches

Open `http://127.0.0.1:5173`. Sign in with exactly the username/password from
backend `.env`, **not** a Cloudflare login, node token or gateway key.

**Check:** Overview opens, workspace points to `http://127.0.0.1:8000`, and both
terminals remain running. Zero nodes is normal. Continue to Local testing.
For a failed login, check your `.env` and restart backend after edits. For
network/CORS errors, check backend startup and that `ADMIN_CORS_ORIGINS` includes
the exact `http://127.0.0.1:5173` origin; do not disable authentication.

On later launches, use the backend start block in backend and frontend run
command in frontend. Reinstall dependencies only when necessary, such as after
requirements change. Ctrl+C stops a development server without deleting saved
configuration/models. Backend `.env` edits need a backend restart; `VITE_`
changes need a frontend restart. Production needs a separate deployment.

## Local testing

When Ollama and the router backend are on the same computer, Cloudflare is not
required. [Install/open Ollama](https://ollama.com/download), then inspect installed models and install the
selector if missing:

```sh
ollama list
ollama pull qwen3.5:2b
curl -fsS http://127.0.0.1:11434/v1/models
```

Register `http://127.0.0.1:11434/v1` in **Nodes**, with the token blank for
ordinary direct local Ollama. Create, Fetch models, inspect **Models**, and test
an explicit model in **Playground** before Auto.

**Check each milestone:**

1. `ollama list` includes `qwen3.5:2b`; `/v1/models` returns a `data` list with
   installed names. Connection refused means Ollama is not running. On Windows,
   use `curl.exe` instead of the PowerShell `curl` alias.
2. **Nodes** contains your Local Ollama record; **Models** lists the exact name.
   “0 new models, already existed” is normal and does not prove inference works.
3. Choose the explicit `qwen3.5:2b` model/node pair in **Playground**, leave its
   optional API key blank, enter “Say hello in one sentence.” and Run. Expect a
   nonempty final answer, selected model displayed, and a successful attempt in
   **Requests**. Reasoning without final text is not a completed answer.
4. Test **Automatic model selection** next; Models must show the selector
   available. Preview selection tests a decision, not generation. Auto is not
   guaranteed to choose the smallest model for every greeting.

At this point you have one node and a real answer. Add a remote computer next,
or proceed to Connect your application.

Loopback means the backend computer. From a VPS/container it does not reach your
laptop. Never expose unauthenticated Ollama to the internet to work around this.
A direct Ollama endpoint lists all installed models; gsai exposes only its
selected setup model.

## Connect a remote gsai computer

Repeat this on **each** AI computer, as its owning user. Each computer needs its
own hostname, tunnel and node token.

### Install

macOS/Linux:

```sh
curl -fsSL https://get.gettingstarted.app/install.sh | sh
gsai version
gsai help
```

Windows PowerShell:

```powershell
irm https://get.gettingstarted.app/install.ps1 | iex
gsai version
gsai help
```

Follow installer PATH instructions. Restart a Windows terminal/IDE if it cannot
find the executable. Cloning the CLI repository alone is not installation.
Use the installed `gsai help COMMAND` to check release-specific options.

### Prepare the account and model

Use your own Cloudflare identity invited to the account containing the intended
**Active DNS zone**. Installing gsai does not grant access to `gettingstarted.app`.
Ask the domain administrator for the account name, intended domain, accepted
invitation, DNS/tunnel access and an unused hostname.

Permissions must permit zone read, DNS read/edit and cloudflared connector
read/write. Current granular connector names include
`Cloudflare One Connector: cloudflared Read` and `Write`; see the official
[tunnel permissions reference](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/remote-tunnel-permissions/).
The team domain does not need to be moved to a new personal account.

```sh
gsai doctor
gsai setup
gsai connect
```

1. Doctor inspects readiness; it does not install a model or authorize Cloudflare.
2. Setup selects/downloads or reuses an Ollama model appropriate for the computer.
3. Connect opens the default browser. Complete consent with the correct account
   on the same computer within five minutes. The loopback OAuth callback is
   `http://127.0.0.1:17891/oauth/callback`, not the public node URL.
4. Back in the terminal, verify the account/domain, create a new managed tunnel
   and choose an unused hostname. Existing DNS records are not overwritten.
5. Generate a strong node token, review and apply configuration. Save the token
   securely when shown. Do not copy another computer's tunnel credentials.

### Get connection information

```sh
gsai status
gsai --json status
```

Record the printed **Endpoint**, including `/v1`, and exact **Model** name.
Keep the node token separately. `status` never prints it; a stored hash cannot
recover it. To replace a lost token:

```sh
gsai config auth
```

Generate a new token, then update the saved node in the router and direct clients.
“Reachable (authentication required)” is expected without the original token;
verify authenticated inference separately. Keep the computer awake and online.

**Check before handoff:** status shows Online and Healthy; record the exact
endpoint/model, owner and expected availability. Share the node token through a
separate secure channel. The router still needs to register this computer.

## Register the node

1. Sign into the router's administrator console.
2. Open **Nodes** and give the computer a descriptive name.
3. Set Endpoint URL to the exact `gsai status` endpoint, including `/v1`.
4. Paste the **node token**, without `Bearer`, into Node access token.
5. Enable routing, select a provider priority and create the record.
6. Review import results; if import failed, fix connectivity/security and
   **Fetch models** again. A failed import can leave a saved node record.
7. Confirm exact names in **Models**, test explicitly in **Playground**, then Auto.
8. Configure allowed nodes/models for application keys under **API Keys**.

Smaller priority numbers are earlier dispatch tiers, not model quality.
Enabled is administrative state, not an online/heartbeat guarantee. Import does
not download models. Removing a node record does not stop gsai on its computer.
Removed upstream models are not automatically pruned: review stale inventory.

**Check the second computer:** select this new model/node pair explicitly in
Playground and Run “Say hello in one sentence.” Confirm a nonempty final answer
and a successful Requests row naming this node. Then test Auto. Successful model
listing alone is not an authenticated inference test.

## Credential handoff

| Information | Who needs it | How to share |
| --- | --- | --- |
| Account name/domain/invitation | Node owner and domain administrator | Ordinary configuration handoff; no passwords |
| Endpoint/exact model/owner/expected availability | Router administrator | Configuration handoff |
| Node access token | Router administrator and authorized direct clients | Separate secure channel/password manager |
| Gateway client key | Application owner | Secret manager; never substitute a node token |
| Panel admin password/session | Console administrator only | Private; never distribute to application users |

Cloudflare credentials manage DNS/tunnels; they do not authenticate inference.
Node tokens authenticate router → computer. Gateway keys authenticate
application → router. Rotating a node token requires updating its Nodes record.

Signed-in Playground with no client key uses the protected admin API. This does
not disable public gateway authentication. The current public gateway permits
anonymous requests only when there are zero key records. Once any key record
exists, a valid active key is needed; disabling all keys does not enable anonymous
access. Create a scoped active key before publishing the gateway.

## Connect your application

1. In **API Keys**, click **Create API Key** and enter an application name.
2. Select allowed nodes or specific model records. An unrestricted key (no
   selections) can access all active inventory; empty restrictions do not mean
   no access. A node-wide grant includes its available models; a model-specific
   grant is narrower. Review permissions as new computers/models are added.
3. Keep **Active** checked and click **Create key**. Copy the actual secret using
   the row's copy control, not the key name or masked text.
4. Save it in a server-side secret manager, never a public frontend bundle.
   An older key without a copyable secret may need **Regenerate**; that
   invalidates the old value, so update all clients using it.

For the local workspace, run this in a separate macOS/Linux terminal. It asks
for the key without showing it or placing its literal value in shell history:

```sh
printf 'Gateway key: '
read -r -s GSAI_GATEWAY_KEY
printf '\n'
curl -N 'http://127.0.0.1:8000/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $GSAI_GATEWAY_KEY" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say hello in one sentence."}],"stream":true}'
unset GSAI_GATEWAY_KEY
```

Windows PowerShell (nonstreaming JSON for the first test):

```powershell
$gatewaySecret = Read-Host 'Gateway key' -AsSecureString
$gatewayKey = ([PSCredential]::new('gateway', $gatewaySecret)).GetNetworkCredential().Password
$gatewayHeaders = @{ Authorization = "Bearer $gatewayKey" }
$gatewayBody = @{ model = "auto"; messages = @(@{ role = "user"; content = "Say hello in one sentence." }); stream = $false } | ConvertTo-Json -Depth 5
try {
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/chat/completions' -Headers $gatewayHeaders -ContentType 'application/json' -Body $gatewayBody
} finally { Remove-Variable gatewayKey, gatewaySecret, gatewayHeaders, gatewayBody }
```

Replace the loopback base with your administrator-provided **router** URL when
the service is hosted elsewhere. This sends a real inference request.

**Check:** cURL returns `data:` events ending in `[DONE]`; PowerShell returns
a JSON completion. Confirm final answer text and actual model, then inspect
Requests. For 401 check the gateway key; for 403 check its permissions. Isolate
Auto failures by substituting an exact permitted model name for `auto`.
The app uses one router URL/key; it does not need each computer's endpoint/token.
Blank-key signed-in Playground remains a separate admin-authenticated path.

## Verify routing

The application calls the router's `/v1/chat/completions`, not a node's tunnel.
Use the URL for the environment actually running. A configured public hostname
in documentation is not proof of deployment.

Omit `model` or send `auto`. The default backend asks local `qwen3.5:2b`, with
thinking off, to select from permitted/reachable candidates. Answer-model thinking
is not disabled. New imported eligible models join without editing a fixed catalog.
No encoder calibration is required in default `local_llm` mode.

The chat API also treats `"model": null` as Auto. An empty string (`"model": ""`)
or whitespace-only string is invalid and returns 400; leaving a field out is
different from sending an empty value. The API-reference request builder defaults
to **Automatic — omit model field**. If your SDK requires a model argument, use
`"auto"`. The response reports the actual answering model, not `auto`.

Use **Models → Preview selection** to run the selector without answer generation.
Use **Playground** for real generation and **Requests** for upstream attempts.
Selection is a heuristic, not proven task competence. A selector failure uses only
a configured eligible fallback; otherwise it reports 503.

Supported loopback Ollama text chats request up to 16K context by default, capped
by advertised capacity. Remote/generic providers retain their runtime settings.
Auto streams that reach a generation limit before any final answer may try two
different eligible models without a manual cap. Partial answers, tool calls and
explicit model requests are not replayed. Recovery does not detect wrong answers
and cannot guarantee success. See the selection guide for exact limits.

## Operations and troubleshooting

| Task or symptom | Action |
| --- | --- |
| Start / stop | `gsai start` / `gsai stop`; configuration retained |
| Change selected model | `gsai setup`; Fetch models and review inventory afterwards |
| Check CLI updates | `gsai update --check` |
| Update connected node | stop → update → version → start → status |
| Disconnect | `gsai disconnect`; requires original Cloudflare account access |
| Node import 401 | Node token, rotation or public expiry; not gateway key |
| Application 401 | Active gateway client key and scope |
| Tunnel HTML / 502 | Node service, local runtime and connector health; test node directly |
| Selector 503 | Ollama on backend computer, installed selector, URL/deadline/fallback |
| No compatible model 503 | Permissions, live inventory, context/capabilities or explicit quality constraint |
| Busy / 429 | Respect Retry-After; reduce concurrency; gsai has two inference slots |
| CORS / OPTIONS 400 | Exact frontend origin in ADMIN_CORS_ORIGINS; restart backend |

Use `gsai --verbose status` for detail. Redact secrets before sharing diagnostics.
The node uses its OS user service manager; availability can depend on the owning
user's session. Stopping gsai does not uninstall models or independently running
Ollama. Public expiry does not necessarily disconnect the tunnel.

## Publication checklist

- Use the README's local startup commands for development; do not deploy the
  Vite development server or uvicorn `--reload` as a production service.
- Run the selector where the VPS backend can reach it. A laptop's selector is
  not automatically reachable at the VPS's `127.0.0.1`.
- Use supervised services, persistent protected database, HTTPS, secure backups,
  strong admin credentials, exact CORS origins and scoped gateway keys.
- Configure reverse-proxy streaming and adequate timeouts without buffering.
- Register node endpoints reachable from the backend; do not use laptop loopback
  URLs in VPS node records.
- Verify explicit inference, Auto, streaming, permissions and recovery before
  publishing. Observe resources; a large context consumes more RAM.

The console does not deploy itself to the VPS. gsai publishes nodes, not this
router. Live GPU capacity, external queue telemetry, heartbeat and automatic
enrollment are not implemented.

## Glossary

| Term | Meaning |
| --- | --- |
| Router / gateway | Central API that selects a model and forwards application requests |
| Console / backend | Website / Python service it talks to; both must run |
| Node / provider | Saved answering endpoint, usually an AI computer |
| Model / inventory | Text generator / saved model-name list, not proof of availability |
| Endpoint / `/v1` | Base API URL; append `/models` or `/chat/completions`, not a second `/v1` |
| `127.0.0.1` / localhost | The connecting computer/container, not another laptop or VPS |
| Selector / Auto | Local 2B chooses a permitted model; that answer model generates the response |
| Token / key / scope | Authentication secret / allowed access; node and gateway secrets differ |
| Cloudflare account / zone / tunnel | Access owner / managed domain / connection publishing a node |
| Context / output budget | Input-history-generation capacity / generation allowance; thinking can share the budget |
| Streaming / reasoning | Chunks arriving incrementally / provider thinking, not the final answer |
| Priority / fallback / recovery | Dispatch order / failure handling / bounded supported model retry, not a quality guarantee |
