# Automatic model selection

## Default: local Ollama selector

`ROUTER_SELECTION_MODE=local_llm` is the default. The backend calls local
`qwen3.5:2b` with `think=false`, temperature 0 and a JSON schema containing
only the dynamically eligible model names. No hard-coded serving-model catalog
or per-model prompt edit is required. The selector itself must be installed in
Ollama on the **backend computer**, not necessarily the browser computer.

1. Filter enabled model/node records by client-key permissions and provider scope.
2. Probe live upstream inventory, then screen requested capabilities and context.
3. Send bounded latest user text and up to two previous user excerpts to the
   selector, with eligible names and available duration observations. No API keys,
   node URLs, system instructions, assistant reasoning or raw images are sent.
4. Accept only complete JSON selecting an eligible name. No free-form reason is
   generated. Selector calls have a 15-second total deadline including queue time,
   two concurrent calls per worker, bounded input/output and no automatic retries.
5. Send the original conversation to the selected answer model, preserving its
   thinking settings and streaming behavior. Equal-priority deployments share
   gateway-observed load. Provider failover retains the selected model.
   For automatic streams only, a reasoning-only generation-limit finish can
   trigger at most two different permitted model names, with a visible retry
   event. Final-answer text, tools and explicit output caps prohibit replay.
   Recovery is a fresh generation, not a guarantee that the next model is stronger.

The selector's judgement is **not validated model competence**. Names/sizes are
hints only. HTTP success and response duration do not measure answer correctness.
The selector may overuse large models or make wrong decisions on new models.
It adds inference latency and competes for memory/compute with answer models.
Representative comparisons remain necessary before claiming routing accuracy.

No benchmark preparation, encoder download or fitting runs in this mode. Historical
calibration records are retained but do not gate selection. Text-only newly
imported models may enter immediately; tools/vision/schema requirements still
need verified capability profiles. Latest user text over 6000 characters requires
an explicit model. The selector receives no assistant turns, whereas the answer
model receives the original retained conversation. Preview runs selector inference
but does not generate an answer. Readiness checks inventory only, not inference.

Configure in backend `.env` (defaults already match local testing):

```dotenv
ROUTER_SELECTION_MODE=local_llm
ROUTER_SELECTOR_URL=http://127.0.0.1:11434
ROUTER_SELECTOR_MODEL=qwen3.5:2b
ROUTER_SELECTOR_TIMEOUT_SECONDS=15
```

Restart the backend after changing selection mode. No Ollama model is downloaded
automatically. If the selector fails or its output is invalid/truncated, only a
configured **eligible** fallback in Models is used. With no eligible configured
fallback the response is 503, not a hidden largest-model default. Explicit
`routing.min_quality` returns 503 in this mode because the selector cannot certify
a numerical quality threshold; explicit-model evaluated routing remains available.
Client scopes, capability/context filters and authentication are never bypassed.

Supported direct loopback Ollama text requests use native `/api/chat` so the
runtime context can actually be requested: `OLLAMA_CHAT_CONTEXT_TOKENS=16384`,
capped by the model's live advertised context. Old calibration context caps do
not override verified native context. No explicit output cap means native
`num_predict=-1`; thinking retains model defaults. Remote/generic endpoints and
unsupported native request features still use OpenAI forwarding unchanged.
Larger contexts need more RAM; exceeding the advertised maximum is not supported.
Recovery records the alternate model in the bounded audit, while initial HTTP
selection headers retain the first plan; inspect the final body for actual model.

Audit policy is `local-llm-selector-v1`; response decision is `local_llm_selection`
or `fallback_selector_error`. Bounded decision records include selector duration,
candidate count and sanitized failure kind, never request text or credentials.

## Optional legacy learned router

The remainder documents `ROUTER_SELECTION_MODE=learned`, not the default.
Use it only with representative validated evaluation data.

Clients do not provide task labels, model purposes, or a fixed model catalog.
Registered model records are the candidate inventory. Model names and parameter
counts are never used to invent quality scores.

This uses versioned per-model ridge predictors, not a universal expert router.
It uses a small local encoder, not an extra generative LLM. It still performs
local ML inference. Accuracy and latency have not been measured in this
workspace; this implementation is not production validation.

## Client request

POST `/v1/chat/completions` using a gateway client API key:

```json
{
  "messages": [
    {"role": "user", "content": "Resolve concurrent stock updates in this Python API."}
  ]
}
```

Omit `model` or set it to `auto`. Optional `routing.preference` is
`balanced`, `fast`, or `quality`. Optional capability/context/quality
requirements remain supported. No `task` is needed; legacy task scores are
only used when an explicit model is supplied with routing options.

Explicit model requests without `routing` retain the existing proxy behavior
and do not need the encoder. They are the operational escape hatch when
automatic routing lacks evidence. Do not silently turn an automatic request
into a priority-based guess.

## What happens

1. Apply client API-key scope and enabled, provider-bound model filters.
2. Probe authenticated upstream `/v1/models`; exclude inaccessible nodes and
   absent model names. Successful inventories are cached for at most five
   seconds. Redirects are not followed, responses are capped at 256 KiB, probe
   concurrency is bounded to eight per process, and inventory is capped at
   256 providers per request. This is not a heartbeat or a capacity reservation.
3. Check verified capabilities for images, tools and JSON-schema output.
   Unknown capabilities cannot satisfy these requirements.
4. Screen context using text bytes plus output allowance and fixed overhead.
   This is conservative screening, not model tokenization; image-token
   budgets are not measured. Unknown context limits cannot satisfy an explicit
   minimum but otherwise remain candidates with a warning.
5. Encode the latest user text and up to two previous user excerpts (at most
   1,024 characters each, combined routing text at most 8,192). No generated
   classification, purpose descriptions or model-name rules are involved.
6. Load matching-revision trained artifacts. Background training needs at
   least 20 valid normalized evaluation embeddings and three task groups.
   Request handling never fits a predictor or downloads an encoder.
7. Predict the configured rubric score through regularized linear regression.
   Grouped held-out RMSE must improve on a constant baseline by at least 0.01.
   Learned selection additionally requires RMSE <= 0.25 and a nearest training
   similarity meeting the configured coverage threshold. RMSE is an error
   estimate, not calibrated probability; the similarity check is only an OOD
   screen, not proof of understanding. No five-neighbor gate applies per request.
8. Admit models whose predicted mean quality is at least 0.80 and within the
   preference's allowed gap from the best observed mean. Rank admitted models
   by measured latency on identical shared evaluation cases. Traffic volume
   and HTTP success history do not increase automatic-selection scores.
   Stable ties use observed quality, provider priority, provider ID and model ID.

Automatic policy: `validated-learned-router-v5`. Balanced allows a 0.02 quality
gap, fast allows 0.05, and quality allows no gap. These are policy choices, not
learned thresholds or confidence guarantees. Explicit `min_quality` still
filters `max(0, prediction - heldout_RMSE)` before admission, including fallback.
When confidence/coverage or the predicted floor is insufficient, selection
uses an explicitly labelled prepared default. This does not certify answer quality.

Latency is used only when all quality-admitted candidates have timings on the
identical case set. Missing or incompatible
timings trigger an explicit quality-only fallback, not a neutral speed score.
Stored latency uses Ollama's prompt evaluation plus generation durations and
excludes loading/network. Starter calibration uses short nonthinking answers;
this proxy does not predict live thinking latency, warm/cold model state, or
queue depth. Thinking on real Playground requests is unchanged.
Custom evaluation imports may optionally supply a positive finite `latency_ms`.
Measure it consistently on identical cases across models and document the timing
protocol in `source`. Omitting it clears an old timing for that updated case;
the router will not fabricate latency for manually scored records.

The following historical weights apply only to explicit-model requests with
the legacy routing options, not automatic selection:

| Preference | Quality | Historical speed | HTTP reliability |
| --- | --- | --- | --- |
| balanced | 0.45 | 0.30 | 0.25 |
| fast | 0.15 | 0.60 | 0.25 |
| quality | 0.70 | 0.05 | 0.25 |

These policy weights are not learned. Duration needs five successful observations;
otherwise a neutral speed prior is used. Speed is `2000/(2000+duration_ms)`.
Reliability is `(successes+1)/(attempts+2)`, over the last 24 hours.
HTTP success does not measure answer correctness. Duration includes the whole
response/stream, is not TTFT, and is not workload-normalized.

Failover stays on the selected model and scoped eligible providers. Once a
stream starts there is no retry or model switch. Inventory can change after
a probe; existing upstream failure handling remains necessary.

## Server-managed preparation

Automatic preparation is enabled by default. Normal server installation uses
`backend/requirements.txt`, which includes the encoder dependencies. The existing
deployment pipeline already installs that file before restarting the service.
There is no runtime pip installation and no separate router-setup command.

Register a direct local Ollama endpoint, such as `http://127.0.0.1:11434/v1`,
and fetch its model inventory. The server does the rest in a background worker:

1. Detect enabled models and inspect native Ollama metadata/digests.
2. Download or reuse the pinned
   [multilingual encoder](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
3. Measure 67 short answers per missing/stale model, including ten English/Turkish
   greetings and 25 SQL transaction/concurrency, algorithmic complexity,
   multi-step reasoning and security cases. Store grades and native timings.
4. Activate model profiles, scored cases and configuration atomically.

With two newly registered models, initial calibration generates 134 short answers.
It consumes model compute and storage; it is not instantaneous. Models shows
pending/checking/running/prepared or failure states without asking users to type
a command. Previously calibrated unchanged models are not benchmarked again
unless the versioned suite changes. This update changes the suite, so models
with old scores are recalibrated automatically; older records are preserved.
New or updated models are discovered at startup, after node/inventory changes,
and during periodic checks. Work is batched to at most 16 models at a time.

The controller runs preparation in a child process, not on the HTTP event loop.
SQLite ownership prevents concurrent workers from running overlapping
calibrations. A preparation run is bounded to one hour; server shutdown stops
its owned child. Failures back off up to 15 minutes and keep previous configuration
active. Stale ownership expires after 15 minutes. Offline/non-native candidates
do not block preparation of accessible local Ollama models.

The source encoder commit is `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
Artifact fingerprints are verified and reused; partially downloaded artifacts
are not silently overwritten. No Ollama model is downloaded by preparation.

The starter grader checks objectively known short answers, using
Unicode/case/diacritic normalization. It covers elementary code interpretation,
arithmetic, extraction, translation, transaction semantics, algorithms and security.
Advanced cases check specific known answers, not full generated program execution.
It is not a comprehensive benchmark of
complex coding/security/reasoning or production tasks. All-zero results are
rejected; network/truncated-response failures do not become fabricated scores.
Calibration context is capped at 4096, or a smaller advertised maximum. This is
a conservative screening budget, not proof of future runtime allocation.

After measurement, the controller fits predictors automatically, including
existing compatible evaluations without regenerating the 67 answers. Each
artifact binds the trainer version, model revision, encoder, rubric and a full
evaluation snapshot hash. Editing/deleting evaluations invalidates it immediately
and queues background refitting. New models never receive guessed quality priors.
Up to 512 deterministically sampled cases per model bound training memory; two
BLAS threads bound solver parallelism. Up to five folds keep related task-group
examples together. Optional `evaluation_group` identifies custom paraphrase groups.
This grouped validation is not independent production validation or a guarantee
of end-to-end router performance on new workloads.

Default policy: prefer a configured, prepared and scoped model record; otherwise
select the highest measured suite mean within the largest identical-case cohort
(ties prefer more cases, then stable cohort identity). Quality, not calibration
speed or model size, determines this fallback. Different case sets are not treated
as comparable averages. Decisions are labelled `fallback_low_confidence` or
`fallback_predicted_quality_below_floor`; artifacts failing validation are
`fallback_only`, not silently treated as trained experts.
Fallback still enforces permissions, inventory/revision, capability, context and
explicit `min_quality`. Without any prepared compatible model, 503 is necessary.
The default never grants access to a forbidden model.

New models participate where matching-revision, matching-rubric evidence exists.
No model-name catalog or parameter-count preference is required. Adding cases
changes the suite fingerprint and triggers server-managed recalibration.
Semantic similarity is not a difficulty classifier: realistic domain-specific
code correctness still needs audited evaluations. This starter suite does not
guarantee that every complex request selects a larger or better model.

### Deployment and scope boundaries

An already-running old environment cannot acquire new code/dependencies merely
by refreshing the browser. Deploy the current server normally. From then on,
no separate encoder command, hand-entered model revision or benchmark import
is needed for supported local Ollama nodes.

`127.0.0.1` means the backend host. On a VPS it does not mean your MacBook.
This automatic workflow supports direct loopback Ollama endpoints with native
`/api/show`, `/api/tags`, `/api/version` and `/api/generate`.
Generic remote OpenAI-compatible endpoints and gsai tunnels exposing only
`/v1` are **not** automatically calibrated here. They require a verified
metadata/evaluation integration; do not describe them as automatically ready.
Installed/evaluated text capability does not establish vision/tool quality.

Set `ROUTER_AUTO_PREPARE=false` to disable background downloads/generations.
A custom audited rubric is preserved instead of being replaced by the starter
workflow. Existing scored records are preserved. For a deliberately
operator-managed setup, advanced commands remain available:

```sh
make router-setup
python scripts/setup_automatic_routing.py --provider-id YOUR_PROVIDER_ID
python scripts/setup_automatic_routing.py --provider-id YOUR_PROVIDER_ID --allow-remote
```

Disable automatic preparation when running an independent manual setup to avoid
competing work. Manual commands ask for `PREPARE`; remote manual preparation
requires HTTPS. Manual setup also fits compatible predictors after measurement.
With automatic preparation disabled, refit imported/edited evaluations using
`python scripts/fit_router_predictors.py`; it performs no model generation or
download. Old environment uncertainty flags do not override the v5 default policy.
All commands use the backend's database and environment.

## Advanced operator-controlled configuration

The sections below describe custom artifact/profile/evaluation APIs. They are
not required for the normal server-managed local Ollama flow.

### 1. Prepare a trusted offline encoder artifact

Use Python 3.10+ and `backend/requirements.txt` (`requirements-router.txt` is a compatibility alias). It pins
Sentence Transformers 5.6.0, Transformers 4.57.6, Optimum 2.1.0, and
Optimum ONNX 0.1.0 together, but is not a full transitive deployment lock.
Resolve and lock the CPU-platform dependencies before production deployment.
Do not independently upgrade Sentence Transformers to 6.1.0: it requires
Transformers 5, while the pinned ONNX adapter requires Transformers below 4.58.
If an earlier install failed with this resolver conflict, rerun the normal
requirements installation using the updated file; do not bypass dependencies
with `--no-deps`.

A suitable encoder must support your languages, produce normalized sentence
embeddings, and have enough context for expected requests. Select an immutable
repository commit, not `main` or `latest`. This advanced path lets the operator
choose an encoder instead of using the pinned server-managed encoder.

From `backend`, the following are operator commands; they have not been run
by this change:

```sh
python -m pip install -r requirements-router.txt
python scripts/prepare_router_encoder.py \
  --repository TRUSTED_SENTENCE_TRANSFORMER_REPOSITORY \
  --revision IMMUTABLE_40_CHARACTER_COMMIT_SHA \
  --output /absolute/path/to/new/encoder-artifact
```

Replace the uppercase placeholders. Export is explicit and may download the
chosen artifact; it is never invoked by startup or inference. Existing output
directories are rejected. The script prints the path and content fingerprint.

Configure the backend environment:

```ini
ROUTER_ENCODER_PATH=/absolute/path/to/new/encoder-artifact
ROUTER_ENCODER_REVISION=THE_PRINTED_CONTENT_FINGERPRINT
ROUTER_EVALUATION_RUBRIC=your-versioned-evaluation-rubric
ROUTER_ENCODER_THREADS=2
ROUTER_MIN_SIMILARITY=0.5
ROUTER_PROBE_TIMEOUT_SECONDS=3
```

Runtime uses CPU ONNX, local files only, no automatic export and no remote
custom code. The model loads once per process, on first use. It verifies the
artifact content fingerprint including tokenizer/pooling/weights. First load
has extra disk/model-loading cost. Restart after changing an artifact/config;
reimport evaluations under the new fingerprint.

Encoder requests are serialized per process; excess wait beyond 250 ms
uses a prepared fallback rather than creating an unbounded encoder queue. If
there is no compatible prepared fallback, the request returns 503. Longer text is
split into at most 64 individually token-checked windows and combined as a
weighted normalized mean; the tail is not silently dropped. This representation
can lose cross-window relationships. More than 8192 characters or excessive
window count returns 422. Image-only requests require an explicit model.

Implementation follows the [official ONNX loading documentation](https://sbert.net/docs/sentence_transformer/usage/efficiency.html).
The pinned package is listed on [PyPI](https://pypi.org/project/sentence-transformers/6.1.0/).

### 2. Establish deployed model metadata

Use an admin session token:

```text
GET /api/models/{model_id}/routing-profile
PUT /api/models/{model_id}/routing-profile
```

The profile accepts:

```json
{
  "capabilities": ["text"],
  "context_tokens": null,
  "task_quality": {},
  "evidence_source": "Verified deployed runtime metadata",
  "model_revision": "actual-deployed-artifact-and-runtime-revision"
}
```

The example is shape only, not evidence. Use real runtime capabilities and
artifact/runtime/quantization identifiers. Name-only `/v1/models` inventory
cannot provide them. Server-managed preparation collects native Ollama metadata;
generic OpenAI-compatible runtime metadata collection is not implemented.
Update the revision after deployment changes. Previous evaluations then cease
to be eligible. Revision identity is operator supplied, not remotely attested.

### 3. Import measured evaluations

Run representative shared requests against the deployed candidates under a
consistent, versioned rubric. Score actual answers using trustworthy reference
answers, executable assertions or audited human assessment. No benchmark runner
is invoked automatically, and an LLM guess is not a measured score.

For each evaluated model/case, use:

```text
PUT /api/models/{model_id}/evaluations/{case_id}
DELETE /api/models/{model_id}/evaluations/{case_id}
```

PUT shape:

```json
{
  "case_id": "your-shared-case-id",
  "model_revision": "matching-profile-revision",
  "rubric": "matching-configured-rubric",
  "request_text": "The actual evaluated user request",
  "score": 0.0,
  "source": "Actual evaluation report/reference identifier"
}
```

The score shown is illustrative; never import invented ratings. Scores must be
finite numbers from 0 to 1. Shared case IDs must have identical request text.
Embedding happens at import. Use the same rubric across models and the same
case set for comparable aggregate defaults/timings. Different case sets can
train per-model predictors but their aggregate grades are never compared as
equivalent defaults. Optional `evaluation_group` keeps related examples in one
held-out fold; without it, case-ID families are inferred by stripping numeric
suffixes. At least three groups are required. Storage is capped at 5000 records.
Updates are transactional and records cascade when their model is deleted.

Evaluation request text and vectors are stored in SQLite. Use redacted/non-
sensitive evaluation examples and protected database backups. Live inference
text/vectors are not persisted by the semantic router. The API validates
structure and revision consistency, not whether the operator's scores are true.

## Inspect readiness without generation

The Models page shows current evaluation counts, predictor status and held-out
RMSE, a fallback selector and a decision preview. `validated` means the grouped
predictor check passed, not that all workloads are supported. `fallback_only`
means fitted data can establish a measured default but learned selection did not
pass validation. Configuration does not prove encoder loading succeeds.

```text
GET /api/router/readiness
POST /api/router/preview
PUT /api/router/defaults
GET /api/router/decisions
```

Preview accepts the same request shape. It probes inventories and encodes text,
but does not generate model answers. It returns candidates, source evidence,
uncertainty warnings and the policy version. It uses admin inventory; inference
additionally applies client key permissions. No upstream tokens or live request
text are included in diagnostics. Response headers identify the policy and
initially selected model record; logs identify each actual upstream attempt.
`X-Gateway-Routing-Decision` distinguishes learned selection from fallback.
`X-Gateway-Decision-Id` references a bounded admin audit record (latest 1,000
stored, latest 100 returned). `X-Gateway-Selected-Provider-Id` identifies the
actual serving node. Decision records store no messages, embeddings, weights or
credentials; the planned node may differ from `served_provider_id` after dispatch.
Set defaults with `{"fallback_model_id": MODEL_RECORD_ID}`; null restores the
automatic measured default. This is a record ID, not a hardcoded model name.

## Failure and deployment boundaries

- 400: malformed routing options/content.
- 422: text exceeds routing window capacity or no usable user text.
- 503: no current prepared predictor/default, no compatible or eligible
  reachable model, or preflight capacity exceeded.
- Profile/evaluation schema failures use normal FastAPI validation responses.
- Existing authentication applies: evaluation and readiness APIs require admin
  credentials. Client inference uses existing gateway key behavior. The legacy
  no-key-configured mode is anonymous; configure client keys before exposing
  this gateway publicly.
- Automatic selection is unavailable until operator preparation is complete;
  explicit-model requests remain usable.

Node dispatch preserves provider priority tiers and atomically balances the
gateway-observed active requests among equal-priority peers. SQLite leases are
shared by workers on the same database, renewed during streams and released on
completion/cancellation. Crash recovery expires leases after 20 minutes.
This does not count traffic outside this gateway or guarantee upstream cancellation.

Not implemented: agent enrollment/heartbeat, live queue/GPU/RAM telemetry,
cross-host distributed admission/capacity reservations, capacity-aware scheduling, automatic metadata
ingestion for generic OpenAI-compatible endpoints, comprehensive production
benchmarking, online policy training, multimodal semantic
analysis, or cross-model retries. Do not call this a completed production
scheduler. No VPS changes, dependency installations, model downloads or runtime
tests were performed while writing this implementation.
