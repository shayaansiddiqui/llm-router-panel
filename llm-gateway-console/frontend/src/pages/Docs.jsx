import { useState } from 'react';
import { ArrowRight, BookOpenText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Callout, CodeBlock, InlineCode, SectionCard } from '@/components/api-docs';
import { DataTable } from '@/components/common';
import { API_BASE_URL, PUBLIC_GATEWAY_URL } from '@/lib/api';
import { cn } from '@/lib/utils';
import { APIDocs } from '@/pages/APIDocs';
import { RouterSetupGuide } from '@/components/router-setup-guide';

const TOPICS = [
  ['start', 'Start here'], ['setup', 'Install & sign in'], ['local', 'First local answer'], ['gsai', 'Add a gsai computer'],
  ['register', 'Register nodes & models'], ['keys', 'Connect your application'],
  ['routing', 'How routing works'], ['security', 'Accounts, tokens & access'], ['operations', 'Operate & troubleshoot'],
  ['deployment', 'Publish the router'], ['api', 'API reference'], ['glossary', 'Glossary'],
];

function Steps({ children }) {
  return <ol className="list-decimal space-y-3 pl-5 text-sm leading-7">{children}</ol>;
}

function Text({ children }) {
  return <p className="text-sm leading-7 text-muted-foreground">{children}</p>;
}

function Subheading({ children }) {
  return <h3 className="text-lg font-semibold tracking-tight">{children}</h3>;
}

export function Docs({ providers, refreshKey, onNavigate }) {
  const [topic, setTopic] = useState(() => window.location.hash === '#api-docs' ? 'api' : 'start');
  const go = (page) => <Button variant="outline" size="sm" onClick={() => onNavigate(page)}>Open {page}<ArrowRight className="h-4 w-4" /></Button>;
  const example = `curl -N '${API_BASE_URL}/v1/chat/completions' \\\n  -H 'Content-Type: application/json' \\\n  -H 'Authorization: Bearer YOUR_GATEWAY_CLIENT_KEY' \\\n  -d '{"model":"auto","messages":[{"role":"user","content":"Say hello."}],"stream":true}'`;
  return (
    <section className="grid gap-6">
      <Callout title="One router. Multiple AI computers.">Start with local testing, or set up each remote computer with gsai. Then register its endpoint in this console. The API reference is one chapter of this guide, not a substitute for node setup.</Callout>
      <div className="grid items-start gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Documentation contents" className="flex gap-1 overflow-x-auto rounded-xl border bg-card p-2 xl:sticky xl:top-28 xl:grid">
          {TOPICS.map(([id, label], index) => <button key={id} type="button" aria-current={topic === id ? 'page' : undefined} aria-controls="docs-chapter" onClick={() => setTopic(id)} className={cn('flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-accent', topic === id ? 'bg-primary/10 font-semibold text-primary' : 'text-muted-foreground')}>
            <span className="text-xs tabular-nums opacity-60">{String(index + 1).padStart(2, '0')}</span>{label}
          </button>)}
        </nav>
        <article id="docs-chapter" aria-label={TOPICS.find(([id]) => id === topic)?.[1]} className="min-w-0 space-y-6">
          <header className="border-b pb-4"><p className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-muted-foreground"><BookOpenText className="h-4 w-4" />GettingStarted AI guide</p><h2 className="text-2xl font-semibold tracking-tight">{TOPICS.find(([id]) => id === topic)?.[1]}</h2></header>

          {topic === 'start' && <>
            <Text>The router is the central Python backend. Ollama runs answer models on your computers. gsai publishes one computer’s selected model through a secure Cloudflare tunnel. The console manages nodes, models, client access and request records.</Text>
            <CodeBlock label="Request flow" value={'Application → Router /v1/chat/completions\n              → local 2B selects a permitted model\n              → selected node → Ollama → streamed answer'} />
            <DataTable headers={['Component', 'Runs where', 'Responsibility']} rows={[
              ['Router backend + console', 'Your development computer or VPS', 'One client API, model selection, node dispatch, access checks and logs'],
              ['Selector qwen3.5:2b', 'Ollama reachable from the router backend', 'Short nonthinking model-choice request; not the answer'],
              ['Answer node', 'Each AI computer', 'Runs its model and generates the answer'],
              ['gsai', 'Each remotely published AI computer', 'Setup, node security, tunnel and background service; not a smart router'],
            ]} />
            <Subheading>Choose your first setup path</Subheading>
            <Steps><li><strong>Router administrator:</strong> first follow Install & sign in. If the console already runs, use your administrator-provided URL and login.</li><li><strong>Get your first answer:</strong> follow First local answer. Cloudflare and gsai connect are not needed on the same computer.</li><li><strong>Add a second computer:</strong> follow Add a gsai computer on that computer, then Register nodes & models in the existing console. Do not install a second router.</li><li><strong>Connect an application:</strong> create a scoped gateway key and test the router endpoint in Connect your application.</li></Steps>
            <Callout title="Connecting is not enrollment">gsai connect does not register the computer in this router. Add each node separately in Nodes. Importing a model record does not download a model to its computer.</Callout>
            <Callout title="What you need">One computer running the router and website; Ollama with qwen3.5:2b reachable from that backend for Auto; at least one answering model. Remote gsai nodes additionally need an account with access to the intended Cloudflare domain. Application users need only the router URL and their gateway key, not a Cloudflare account.</Callout>
            <div className="flex flex-wrap gap-2"><Button onClick={() => setTopic('setup')}>Install & sign in</Button><Button variant="outline" onClick={() => setTopic('local')}>Console already running</Button></div>
          </>}

          {topic === 'setup' && <><RouterSetupGuide /><Button onClick={() => setTopic('local')}>Next: first local answer<ArrowRight className="h-4 w-4" /></Button></>}

          {topic === 'local' && <>
            <Text>These steps assume the router backend and Ollama run on the same computer. From a VPS or Docker container, 127.0.0.1 means that VPS/container, not your laptop.</Text>
            <Steps><li>Install and open <a className="underline" href="https://ollama.com/download" target="_blank" rel="noreferrer">Ollama</a>. Inspect installed models with the command below.</li><li>Install the selector model if it is not already present. Other answer models are your choice; size is not a guarantee of suitability.</li><li>Under Nodes, use the local endpoint below. Direct local Ollama normally does not need a node token; leave that field blank.</li><li>Create the node, then Fetch models. Confirm exact names under Models.</li><li>In Playground, select an explicit model first. Then choose Automatic model selection and inspect the selected model and Requests.</li></Steps>
            <CodeBlock label="On the backend computer" value={'ollama list\nollama pull qwen3.5:2b\ncurl -fsS http://127.0.0.1:11434/v1/models'} />
            <CodeBlock label="Nodes form" value={'Name: Local Ollama\nEndpoint URL: http://127.0.0.1:11434/v1\nNode access token: leave blank\nPriority: 1\nEnable routing: checked'} />
            <Subheading>Check each milestone before continuing</Subheading>
            <Steps><li><strong>Ollama:</strong> list includes qwen3.5:2b; /v1/models returns a data list containing installed names. Connection refused means Ollama is not running. On Windows use curl.exe instead of the PowerShell curl alias.</li><li><strong>Inventory:</strong> Nodes contains Local Ollama and Models lists the exact installed name. “0 new models, already existed” is normal. It is not an inference test.</li><li><strong>First answer:</strong> open Playground, choose qwen3.5:2b explicitly, leave API key blank, enter “Say hello in one sentence.” and Run. Expect a nonempty final answer, the selected model below it, and a successful attempt in Requests. Reasoning alone is not a final answer.</li><li><strong>Auto:</strong> select Automatic model selection and run the same prompt. Models must show the selector available. Preview selection checks a decision only; Playground checks actual generation. Auto is not guaranteed to choose the smallest model for every greeting.</li></Steps>
            <Callout title="You have completed local setup">One registered node, at least one imported model and a real final answer prove the basic path works. Next add a second computer, or connect an application. Changing to a VPS later requires replacing laptop loopback addresses.</Callout>
            <Callout title="Local is not public">The loopback endpoint is only usable from this computer. Do not expose unauthenticated Ollama to the internet. For a different computer, use gsai with a protected tunnel or a deliberately secured private-network endpoint.</Callout>
            <Text>Direct Ollama lists all installed models. A gsai endpoint lists only the model selected by gsai setup, even if that computer has several Ollama models installed.</Text>
            <div className="flex flex-wrap gap-2">{go('Nodes')}{go('Models')}{go('Playground')}</div>
            <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => setTopic('gsai')}>Add a second computer</Button><Button onClick={() => setTopic('keys')}>Connect an application</Button></div>
          </>}

          {topic === 'gsai' && <>
            <Subheading>1. Install on each AI computer</Subheading>
            <Text>Use the published native CLI; cloning its repository alone does not install the gsai command. Run as the user who will own the background node. Supported release targets include macOS, Linux and Windows on AMD64/ARM64; Ollama has separate OS and hardware requirements.</Text>
            <CodeBlock label="macOS / Linux" value={'curl -fsSL https://get.gettingstarted.app/install.sh | sh\ngsai version\ngsai help'} />
            <CodeBlock label="Windows PowerShell" value={'irm https://get.gettingstarted.app/install.ps1 | iex\ngsai version\ngsai help'} />
            <Text>If gsai is not found, follow the installer’s PATH instructions; restart the terminal/IDE after a Windows installation. The normal installation does not require Go, Python, Node.js or Docker on the AI computer.</Text>
            <Subheading>2. Inspect hardware and select the local model</Subheading>
            <CodeBlock label="On the AI computer" value={'gsai doctor\ngsai setup'} />
            <Text>Doctor checks readiness; it does not install a model or grant Cloudflare access. Setup lets you select a recommended or installed Ollama model, approves runtime installation if necessary, and downloads/reuses the selected model. Keep enough disk/RAM available. Keep the computer awake while serving.</Text>
            <Subheading>3. Confirm the Cloudflare account before connecting</Subheading>
            <Callout title="Which account?">Use your own Cloudflare identity with access to the account containing the intended Active DNS zone. For a team domain, accept that administrator’s invitation first. Installing gsai does not grant access to gettingstarted.app. Ask for the account name, domain, required DNS/tunnel access and an unused hostname.</Callout>
            <Text>Access must allow zone read, DNS read/edit and cloudflared connector read/write. Current connector permission names include Cloudflare One Connector: cloudflared Read/Write. See the <a className="underline" href="https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/remote-tunnel-permissions/" target="_blank" rel="noreferrer">Cloudflare permissions reference</a>. A new personal account without the team’s domain will not work.</Text>
            <Subheading>4. Authorize, connect and save the token</Subheading>
            <CodeBlock label="On that same computer" value={'gsai connect'} />
            <Steps><li>Keep the terminal open. Sign in through the default browser using the intended Cloudflare identity/account.</li><li>Complete authorization on the same computer within five minutes. The loopback callback is <InlineCode>http://127.0.0.1:17891/oauth/callback</InlineCode>; it is not your public node address.</li><li>Return to the terminal. Verify the domain and account, create a new gsai-managed tunnel and choose an unused hostname.</li><li>Choose Generate a strong access token. Review and Apply configuration.</li><li>Save the node token securely when shown. Then run status and register the node in this console.</li></Steps>
            <CodeBlock label="Inspect this node" value={'gsai status\ngsai --json status'} />
            <CodeBlock label="Illustrative output — use your own values" value={'Node status   Online\nEndpoint      https://YOUR-COMPUTER.YOUR-DOMAIN/v1\nModel         MODEL-FROM-SETUP\nTunnel        YOUR-TUNNEL\nAccess        token\nLocal health  Healthy\nRemote health Reachable (authentication required)'} />
            <Text>Copy Endpoint and Model from status. Token is not printed there: it is shown when generated, and only its hash is stored. “Authentication required” in remote health is expected without the token; it is not proof that authenticated inference works.</Text>
            <Callout title="Check: ready for handoff">Status should show Online and Healthy. Send the router administrator the endpoint, exact model, computer owner and expected availability. Share the node token separately through a secure channel. Keep the AI computer awake; do not share Cloudflare passwords or tunnel credentials.</Callout>
            <Subheading>5. Lost token or another computer?</Subheading>
            <CodeBlock label="Replace a lost node token" value={'gsai config auth\ngsai status'} />
            <Text>Generate a replacement, then update the node’s token in this panel and any direct clients. Do not look for the original token in a hash. Each additional computer needs its own setup, hostname, tunnel and node token; do not copy tunnel credentials between computers.</Text>
            <Subheading>Optional: a computer without a usable browser</Subheading>
            <Text>Browser authorization is the normal path. For advanced/headless setup, gsai can use CLOUDFLARE_API_TOKEN instead. Ask the domain administrator for an appropriately scoped Cloudflare API token covering the intended zone/account. This is not the node token. Read gsai help connect for installed-release options; do not paste credentials into command history or shared screenshots. Domain/tunnel/security selection is still interactive.</Text>
            <Callout title="No OAuth client registration needed">A node operator does not create a new public OAuth application, upload a logo or wait for gsai’s publisher to approve the computer. Account invitations, domain activation and administrator policies can still require action. If you see a session/CSRF error, cancel the failed flow and restart gsai connect in the same browser session instead of reusing an old callback URL.</Callout>
            <Button onClick={() => setTopic('register')}>Next: register this node<ArrowRight className="h-4 w-4" /></Button>
          </>}

          {topic === 'register' && <>
            <Steps><li>Run <InlineCode>gsai status</InlineCode> on the AI computer. Securely obtain the token generated during connect/config.</li><li>Open Nodes and enter a descriptive name, the exact endpoint including <InlineCode>/v1</InlineCode>, and the node token without <InlineCode>Bearer</InlineCode>.</li><li>Keep Enable routing checked. Lower priority numbers are tried first; equal-priority deployments share gateway-observed active requests. Enabled does not mean online.</li><li>Click Create. A successful creation attempts model import. If import fails, the node record can still exist: fix connectivity/token, then click Fetch models.</li><li>Open Models and confirm the expected exact model name. The import creates records; it does not install or download anything.</li><li>Test explicitly in Playground, then Auto. If a gateway client key will be used, allow the intended nodes/models in API Keys.</li></Steps>
            <DataTable headers={['Nodes field', 'Value to use']} rows={[
              ['Endpoint URL', 'The Endpoint from gsai status, already ending in /v1'],
              ['Node access token', 'Generated gsai node token, not a Cloudflare credential'],
              ['Priority', 'Smaller number = earlier provider tier; not model quality'],
              ['Timeout', 'Provider inactivity timeout in seconds; blank uses server default (180)'],
            ]} />
            <Text>After changing a gsai model with setup, Fetch models again. Removed upstream models are not automatically pruned from this inventory; review stale records and client permissions. Changing a node token requires editing the saved node here. Removing a node record does not stop or uninstall gsai on that computer.</Text>
            <Callout title="Check: the second computer really answers">In Playground choose the imported model/node pair for this new computer explicitly, not Auto. Run “Say hello in one sentence.” Confirm a final answer and that Requests names this node. Then test Auto and review client-key permissions. A saved node or successful model listing alone does not prove that inference works.</Callout>
            <Subheading>Verify the node directly before blaming the router</Subheading>
            <CodeBlock label="macOS / Linux: substitute your own endpoint" value={'GSAI_ENDPOINT=\'https://YOUR-HOSTNAME/v1\'\nprintf \'Node token: \'\nread -r -s GSAI_NODE_TOKEN\nprintf \'\\n\'\ncurl -fsS "$GSAI_ENDPOINT/models" \\\n  -H "Authorization: Bearer $GSAI_NODE_TOKEN"\nunset GSAI_NODE_TOKEN'} />
            <Text>Append /models or /chat/completions to the printed endpoint, not a second /v1. Health is at the hostname’s /health route outside /v1. Token-protected nodes also require authentication for health/model listing.</Text>
            <CodeBlock label="Windows PowerShell: direct node model-list check" value={'$gsaiEndpoint = \'https://YOUR-HOSTNAME/v1\'\n$gsaiSecret = Read-Host \'Node token\' -AsSecureString\n$gsaiNodeToken = ([PSCredential]::new(\'gsai\', $gsaiSecret)).GetNetworkCredential().Password\n$gsaiHeaders = @{ Authorization = "Bearer $gsaiNodeToken" }\ntry {\n    Invoke-RestMethod -Uri "$gsaiEndpoint/models" -Headers $gsaiHeaders\n} finally {\n    Remove-Variable gsaiNodeToken, gsaiSecret, gsaiHeaders\n}'} />
            <div className="flex flex-wrap gap-2">{go('Nodes')}{go('Models')}{go('Playground')}</div>
          </>}

          {topic === 'routing' && <>
            <Subheading>One endpoint for your application</Subheading>
            <Text>Send model: auto or omit model. The default local selector qwen3.5:2b returns one eligible model name with thinking off. The answer model keeps its own thinking settings. Explicit model requests bypass selection.</Text>
            <Steps><li>Apply client-key permissions, enabled model/node filters and any provider restriction.</li><li>Check the nodes’ authenticated live model inventories. Filter required capabilities and the request’s context budget.</li><li>Give local 2B the dynamic candidate list, latest user text and up to two bounded previous user excerpts. Newly imported eligible models appear without editing a fixed catalog.</li><li>Validate the selector’s JSON and model name. Dispatch to an eligible deployment of the selected model.</li><li>Stream the answer and record upstream attempts. The complete retained input conversation goes to the answering model, not just the selector’s excerpts.</li></Steps>
            <CodeBlock label="Backend .env — defaults for local testing" value={'ROUTER_SELECTION_MODE=local_llm\nROUTER_SELECTOR_URL=http://127.0.0.1:11434\nROUTER_SELECTOR_MODEL=qwen3.5:2b\nROUTER_SELECTOR_TIMEOUT_SECONDS=15\nOLLAMA_CHAT_CONTEXT_TOKENS=16384'} />
            <Callout title="The selector runs beside the backend">When the router moves to a VPS, its 127.0.0.1 is the VPS. Install/run the selector there or configure an accessible selector service. Installing 2B only on your laptop does not make it available to the VPS. No model is automatically downloaded by the router.</Callout>
            <Subheading>Fallback and recovery are different</Subheading>
            <Text>If selector generation times out or returns invalid JSON, only the eligible fallback you configured in Models is used. No configured fallback means a clear 503; there is no hidden largest-model default.</Text>
            <Text>For automatic streams with no manual output cap, a generation-limit finish before any final answer can trigger at most two different permitted models. The switch is visible; each attempt starts a new generation with the original input. Final-answer text, tool calls, explicit model requests and manual caps are not automatically replayed. All attempts can still fail. This does not detect a plausible but incorrect answer.</Text>
            <Subheading>Context, thinking and conversation memory</Subheading>
            <Text>Supported direct loopback Ollama text chats on port 11434 use native /api/chat with context up to 16K by default, bounded by advertised model capacity. No manual output cap means native num_predict=-1. Larger allocations need more RAM. Remote/generic providers and unsupported native features keep OpenAI forwarding and provider runtime settings; this console cannot guarantee their context allocation.</Text>
            <Text>Playground keeps at most ten completed conversation turns / 64 KiB in page memory. It sends the recent complete turns that fit a conservative byte-based context screen. Older turns can be omitted with a notice. Reasoning, tool calls and incomplete answers are not remembered. New chat, model/system changes or leaving the page clear memory. This is not permanent model memory or training.</Text>
            <Callout title="Current limitations">Selection is an AI judgement, not measured proof of competence. It can choose the wrong size or overuse a large model. Traffic duration and HTTP success do not measure answer quality. Native GPU capacity, external queue depth, heartbeat and automatic node enrollment are not implemented. Explicit min_quality cannot be certified in local-LLM mode. The older learned router is optional, not the default.</Callout>
            <Text>Use Models → Preview selection to run the selector without generating an answer. Inspect the returned model in Playground and upstream attempts in Requests. Recovery is recorded separately; initial HTTP selection headers describe the original plan, while the final response model identifies the answer model.</Text>
            <div className="flex flex-wrap gap-2">{go('Models')}{go('Requests')}</div>
          </>}

          {topic === 'keys' && <>
            <Text>Get an answer in signed-in Playground first. Its blank-key mode uses your protected admin session and does not require a client key. An external application instead calls the router’s /v1 API with a gateway client key. It never receives the upstream node token.</Text>
            <Subheading>1. Create and scope a gateway key</Subheading>
            <Steps><li>Open API Keys → Create API Key. Give it a recognizable application name, such as Local test app.</li><li>Select the intended node(s) or specific model records in the access controls. A node-wide grant includes its available models; a specific-model grant is narrower. Leaving all restrictions empty grants access to all active inventory, not zero access.</li><li>Keep Active checked and click Create key. Use the key row’s copy control to copy the actual secret, not its name or masked display.</li><li>Save it in your application’s server-side secret storage. Never put it in a public website bundle, source control or screenshots.</li><li>If an older key has no copyable secret, Regenerate replaces it. Update every client using the old key; regeneration invalidates that old value.</li></Steps>
            <Subheading>2. Send the first application request</Subheading>
            <CodeBlock label="Actual workspace endpoint" value={`${API_BASE_URL}/v1/chat/completions`} />
            <CodeBlock label="macOS / Linux — enter the key privately" value={[
              "printf 'Gateway key: '", 'read -r -s GSAI_GATEWAY_KEY', "printf '\\n'",
              `curl -N '${API_BASE_URL}/v1/chat/completions' \\`,
              "  -H 'Content-Type: application/json' \\",
              '  -H "Authorization: Bearer $GSAI_GATEWAY_KEY" \\',
              '  -d \'{"model":"auto","messages":[{"role":"user","content":"Say hello in one sentence."}],"stream":true}\'',
              'unset GSAI_GATEWAY_KEY',
            ].join('\n')} />
            <CodeBlock label="Windows PowerShell — first response as JSON" value={[
              "$gatewaySecret = Read-Host 'Gateway key' -AsSecureString",
              "$gatewayKey = ([PSCredential]::new('gateway', $gatewaySecret)).GetNetworkCredential().Password",
              '$gatewayHeaders = @{ Authorization = "Bearer $gatewayKey" }',
              '$gatewayBody = @{ model = "auto"; messages = @(@{ role = "user"; content = "Say hello in one sentence." }); stream = $false } | ConvertTo-Json -Depth 5',
              'try {',
              `    Invoke-RestMethod -Method Post -Uri '${API_BASE_URL}/v1/chat/completions' -Headers $gatewayHeaders -ContentType 'application/json' -Body $gatewayBody`,
              '} finally { Remove-Variable gatewayKey, gatewaySecret, gatewayHeaders, gatewayBody }',
            ].join('\n')} />
            <Callout title="Check: application access works">The streaming command returns data: events ending with [DONE]; PowerShell returns a JSON completion. Check for a nonempty final answer and the actual model, then inspect Requests. 401 means a missing/invalid/inactive gateway key; 403 means its scope does not permit the requested access. A 503 from Auto can be isolated by replacing auto with an exact permitted installed model name.</Callout>
            <Text>These commands make a real inference request. For deliberate local anonymous testing, the gateway only allows no-key calls while there are zero key records. Creating any key record changes that policy; disabling all keys does not restore anonymous access. Keep a scoped active key before internet exposure.</Text>
            <Callout title="One URL, two different paths">Applications call the router endpoint above. The router calls the private node endpoints you saved in Nodes. Your app does not need one URL or token per computer. This example uses the current workspace, not a claim that a public hostname has been deployed.</Callout>
            {go('API Keys')}
          </>}

          {topic === 'security' && <>
            <DataTable headers={['Credential', 'Used for', 'Not interchangeable with']} rows={[
              ['Cloudflare identity / OAuth / API token', 'Create/manage domain DNS and tunnels in gsai connect/disconnect', 'Node access token or gateway client key'],
              ['gsai node access token', 'Authenticate router → AI computer; put in Nodes', 'Cloudflare token or panel login'],
              ['Panel admin login/session', 'Manage the console; blank-key Playground uses its admin-only API', 'Public application gateway key'],
              ['Gateway client key', 'Authenticate application → router; configure scope in API Keys', 'Node token'],
            ]} />
            <Subheading>Playground versus application access</Subheading>
            <Text>Signed-in Playground can run without a client key using the protected admin endpoint. Enter a client key only when you want to test its permissions. An application should use the public /v1 API with a gateway client key; never distribute an admin session or node token in browser code.</Text>
            <Callout title="Do not publish an anonymous gateway accidentally">Current code allows unauthenticated /v1 requests when there are zero gateway key records. Once any key record exists, a valid active key is required; disabling all keys does not restore anonymous access. Create an active, scoped gateway key before publishing. Admin routes stay protected.</Callout>
            <Text>gsai’s Public without a token option is separate from gateway access. It exposes that computer’s inference resources to anyone with the node URL. Public expiry can reject new requests without disconnecting its tunnel. Prefer node token mode and keep token copies in a password manager. Never paste tokens into screenshots, shared logs, docs or commits.</Text>
            <Text>A client key with no node/model restrictions allows all active inventory. To restrict access, configure explicit allowed nodes/models. When a new computer is added, review permissions rather than assuming an existing restricted key can access it.</Text>
            <Text>The backend stores upstream node credentials to make requests; protect its database, backups and environment. Admin defaults must be changed before deployment, using a strong password and session secret. The browser’s admin token is stored locally; sign out on shared computers.</Text>
            {go('API Keys')}
          </>}

          {topic === 'operations' && <>
            <Subheading>Common node operations</Subheading>
            <DataTable headers={['Command on the AI computer', 'Effect']} rows={[
              ['gsai status / gsai --json status', 'Inspect endpoint/model/access/health; never prints the node token'],
              ['gsai start / gsai stop', 'Start/stop the configured node; keep configuration'],
              ['gsai setup', 'Change the selected model; keep connected hostname/tunnel'],
              ['gsai config auth', 'Replace node token or deliberately change public access'],
              ['gsai update --check / gsai update', 'Check/install CLI updates; not Ollama or model updates'],
              ['gsai disconnect', 'Confirm removal of route/startup/node credentials; not model files'],
              ['gsai help COMMAND', 'Read installed-version command options'],
            ]} />
            <Text>For a connected node update, stop it, update, confirm version, start and inspect status. Background service managers are launchd on macOS, user systemd on Linux and Task Scheduler on Windows. Keep the owner’s session and computer available; do not assume the node runs before login. Disconnect requires Cloudflare access to the original account.</Text>
            <CodeBlock label="Update a connected node" value={'gsai stop\ngsai update\ngsai version\ngsai start\ngsai status'} />
            <Subheading>Diagnose the layer that failed</Subheading>
            <DataTable headers={['Symptom', 'Check / next action']} rows={[
              ['gsai not found', 'Installer PATH instructions; restart terminal/IDE. A checkout is not installation.'],
              ['No Cloudflare domain / authorization forbidden', 'Correct account, invitation accepted, Active zone, DNS/tunnel permissions and account OAuth policy. Restart connect; keep callback in the same computer/browser session.'],
              ['401 fetching models', 'Wrong/missing node token in Nodes, rotated token or expired public access. Do not use a gateway key here.'],
              ['401 in application', 'Gateway client key absent/invalid/inactive; blank-key admin Playground is a separate path.'],
              ['403', 'Client scope or exact configured node model; inspect response source.'],
              ['502 / HTML from tunnel', 'gsai status, local Ollama/service, tunnel connectivity; do not assume a token error. Test direct node first.'],
              ['503 selector unavailable', 'Ollama on backend computer, installed selector name, selector URL/deadline and eligible configured fallback. Explicit testing can bypass selector.'],
              ['503 no compatible model', 'Reachable inventory, client scope, context budget, capability profiles or explicit min_quality.'],
              ['429 or node busy', 'Respect Retry-After and reduce simultaneous requests. gsai currently allows two concurrent inference requests.'],
              ['Reasoning only / length finish', 'Auto may try two alternatives without a manual cap. Check runtime context/RAM; partial answers are not replayed.'],
              ['CORS / OPTIONS 400', 'Backend ADMIN_CORS_ORIGINS must include the exact frontend origin; restart after .env changes.'],
            ]} />
            <Text>Requests shows upstream attempts, not unique client requests. Provider failover and model recovery can create multiple rows. A success HTTP status is not a benchmark score. Refresh node/model inventories after changing endpoints, credentials or selected models.</Text>
            <CodeBlock label="Verbose diagnostics on the AI computer" value={'gsai --verbose status\ngsai --verbose connect'} />
            <Text>Read technical details before sharing them and redact credentials. On macOS, gsai logs are under ~/Library/Application Support/gsai/logs. On Linux use journalctl --user -u gsai.service. Keep local configuration and tunnel credentials private; do not delete them to diagnose a service.</Text>
            {go('Requests')}
          </>}

          {topic === 'deployment' && <>
            <Text>Complete local installation and real inference first. Publication is a separate administrator task; adding a gsai computer does not publish this website or router.</Text>
            <Button variant="outline" onClick={() => setTopic('setup')}>Local installation instructions</Button>
            <Subheading>Know which URL you are using</Subheading>
            <CodeBlock label="Current workspace backend" value={API_BASE_URL} />
            <CodeBlock label="Configured public API example base — not a deployment check" value={PUBLIC_GATEWAY_URL} />
            <Callout title="A hostname in documentation does not publish the router">The public URL is configuration, not proof that a service is running there. 127.0.0.1 is local only. gsai publishes individual nodes; it does not deploy this router or website.</Callout>
            <Subheading>Production handoff checklist</Subheading>
            <Steps><li>Deploy backend and built frontend with a supervised production service, HTTPS reverse proxy and persistent protected database. Do not use uvicorn --reload or the Vite development server as production hosting.</li><li>Place the selector runtime where the backend can reach it. Confirm sufficient CPU/RAM, installed selector model and realistic deadlines.</li><li>Register each node’s reachable endpoint/token from the VPS perspective. Laptop loopback URLs are not usable from the VPS.</li><li>Set real admin secrets, exact CORS origins and frontend API/public URL configuration. Create an active scoped gateway key before internet exposure.</li><li>Configure proxy timeouts and streaming without response buffering. Protect admin access and keep upstream tokens out of client code.</li><li>Verify explicit inference, Auto, streaming, permissions and recovery. Back up the database securely and monitor node availability and resources.</li></Steps>
            <Text>No automated VPS deployment or global Ollama runtime reconfiguration is performed by the console. Native 16K chat allocation applies only to supported direct loopback Ollama requests; gsai/remote nodes retain their own runtime settings.</Text>
          </>}

          {topic === 'glossary' && <>
            <DataTable headers={['Term', 'Plain-language meaning']} rows={[
              ['Router / gateway', 'The central service your application calls; chooses a model and forwards the request.'],
              ['Console / backend', 'Console is the website; backend is the Python service it talks to. Both must be running.'],
              ['Node / provider', 'A saved answering endpoint, usually a computer running Ollama directly or through gsai. One computer can host multiple models.'],
              ['Model / inventory', 'Model generates text; inventory is the router’s saved list of model names, not proof they are online.'],
              ['Endpoint / /v1', 'A base URL for an API. Add /models or /chat/completions to a node base ending in /v1, not a second /v1.'],
              ['127.0.0.1 / localhost', 'The computer or container making the connection—not another laptop or VPS.'],
              ['Selector / Auto', 'The local 2B model makes a short choice from eligible models. The chosen answer model then generates the response.'],
              ['Token / key / scope', 'A secret authenticates a caller. Scope limits its allowed nodes/models. Node tokens and gateway keys are different secrets.'],
              ['Cloudflare account / zone / tunnel', 'Account owns access; zone is a managed domain; tunnel publishes a protected node without opening an inbound port.'],
              ['Context / output budget', 'Context holds input/history and generation. Thinking and final text can share the output budget; larger allocations consume more RAM.'],
              ['Streaming / reasoning', 'Streaming sends chunks as they arrive. Reasoning is provider-returned thinking, not the final answer.'],
              ['Priority / fallback / recovery', 'Priority orders eligible nodes; fallback handles selection/provider failures; recovery may try another model after a supported generation-limit failure. None guarantees correctness.'],
              ['HTTP 200 / 401 / 403 / 502 / 503', 'Success / missing authentication / forbidden access / upstream failure / unavailable eligible route. Read the response message to identify the failing layer.'],
            ]} />
          </>}

          {topic === 'api' && <>
            <Callout title="Choose the correct environment">Playground uses the current workspace backend. The reference below uses the configured public example base; that hostname may not be deployed. For local application testing, use the current workspace URL.</Callout>
            <CodeBlock label="Application request to this workspace — replace the gateway key" value={example} />
            <Text>This sends a real request and consumes model resources when you run it. Use a gateway client key, not your admin session or node token. With zero gateway key records, remove the Authorization line for deliberate local anonymous testing only.</Text>
            <APIDocs providers={providers} refreshKey={refreshKey} />
          </>}
          {topic !== 'api' && <SectionCard><div className="flex flex-wrap items-center justify-between gap-3"><Text>Ready to connect an application? The API reference includes request examples, endpoints, streaming fields and error codes.</Text><Button variant="outline" onClick={() => setTopic('api')}>API reference<ArrowRight className="h-4 w-4" /></Button></div></SectionCard>}
        </article>
      </div>
    </section>
  );
}
