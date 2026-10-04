"""Opt-in local Ollama calibration; no package installation or server restart."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import urlsplit

import httpx

from .calibration_cases import CASES, SYSTEM, GENERATION_OPTIONS, ANSWER_SCHEMA, RUBRIC, grade
from .config import get_settings, get_router_settings
from .database import get_db, fetch_all, fetch_one, utc_now, init_db
from .encoder_preparation import prepare_default_encoder
from .semantic_router import load_encoder, MAX_EVALUATIONS


def native_base(endpoint: str, allow_remote: bool) -> str:
    url = urlsplit(endpoint)
    if url.username or url.password or url.query or url.fragment or url.path.rstrip('/') not in ('', '/v1'):
        raise ValueError('Preparation requires a direct Ollama endpoint, ending in /v1.')
    local = url.hostname in {'localhost', '127.0.0.1', '::1'}
    if not local and not allow_remote:
        raise ValueError('Non-loopback nodes require --allow-remote. Default preparation is local only.')
    if url.scheme not in ('http', 'https') or (not local and url.scheme != 'https'):
        raise ValueError('Remote preparation requires HTTPS.')
    return f'{url.scheme}://{url.netloc}'


def json_request(client: httpx.Client, method: str, url: str, **kwargs):
    with client.stream(method, url, **kwargs) as response:
        if not response.is_success:
            raise ValueError(f'Ollama request failed with HTTP {response.status_code}; no answer score was recorded.')
        data = bytearray()
        for block in response.iter_bytes():
            data.extend(block)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('Ollama response exceeded 2 MiB.')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Ollama returned an invalid response object.')
    return result


def inspect_model(client: httpx.Client, base: str, name: str):
    version = json_request(client, 'GET', base + '/api/version').get('version')
    tags = json_request(client, 'GET', base + '/api/tags').get('models', [])
    entry = next((row for row in tags if row.get('name') == name or row.get('model') == name), None)
    if not entry:
        raise ValueError(f'{name}: not installed in the selected Ollama runtime.')
    digest = entry.get('digest', '')
    if not isinstance(version, str) or not version or not re.fullmatch(r'(sha256:)?[a-f0-9]{64}', digest):
        raise ValueError('Runtime version or full model digest is unavailable.')
    details = json_request(client, 'POST', base + '/api/show', json={'model': name})
    capabilities = details.get('capabilities', [])
    if 'completion' not in capabilities:
        raise ValueError(f'{name}: runtime does not advertise text completion capability.')
    limits = [value for key, value in details.get('model_info', {}).items()
              if key.endswith('.context_length') and isinstance(value, int) and not isinstance(value, bool) and value > 0]
    revision = hashlib.sha256(json.dumps({'digest': digest, 'runtime': version,
        'parameters': details.get('parameters'), 'template': details.get('template'),
        'system': details.get('system')}, sort_keys=True).encode()).hexdigest()
    profile = {'capabilities': ['text'] + [c for c in ('vision', 'tools') if c in capabilities],
               'context_tokens': min(min(limits), GENERATION_OPTIONS['num_ctx']) if limits else None,
               'evidence_source': 'Ollama /api/show + /api/tags + /api/version; context is capped to the calibration budget, not the advertised maximum or verified future allocation',
               'model_revision': revision}
    return profile, digest, version, 'thinking' in capabilities


def update_progress(owner: str, status: str, message: str, completed: int, total: int):
    with get_db() as db:
        changed = db.execute('''UPDATE routing_preparation SET status=?, message=?, completed=?, total=?, updated_at=?
            WHERE id=1 AND owner=?''', (status, message, completed, total, utc_now(), owner)).rowcount
        if not changed:
            raise ValueError('Preparation lock ownership was lost; results will not be published.')


def prepare(args):
    init_db()
    automatic = getattr(args, 'automatic', False)
    models = fetch_all('''SELECT m.*, p.endpoint_url, p.api_key, p.is_active AS provider_active
        FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.is_active=1 AND p.is_active=1
        ORDER BY p.id, m.id''')
    if args.provider_id is not None:
        models = [m for m in models if m['provider_id'] == args.provider_id]
    if automatic:
        candidates = []
        current_settings = get_router_settings()
        if (current_settings.router_evaluation_rubric
            and not current_settings.router_evaluation_rubric.startswith('starter-exact-answer-v1-')):
            return False  # Never replace an operator's custom audited policy.
        for model in models:
            try:
                base = native_base(model['endpoint_url'], False)
            except ValueError:
                continue  # Automatic preparation does not reach out to arbitrary remote nodes.
            headers = {'Authorization': 'Bearer ' + model['api_key']} if model.get('api_key') else {}
            try:
                with httpx.Client(headers=headers, timeout=15, follow_redirects=False) as client:
                    inspected, _, _, _ = inspect_model(client, base, model['name'])
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                continue  # One offline or non-Ollama node must not block healthy candidates.
            saved = fetch_one('SELECT * FROM model_routing_profiles WHERE model_id=?', (model['id'],))
            count = fetch_one('''SELECT COUNT(*) AS samples FROM routing_evaluations WHERE model_id=?
                AND model_revision=? AND rubric=? AND encoder_revision=?''',
                (model['id'], inspected['model_revision'], RUBRIC, current_settings.router_encoder_revision))['samples']
            ready = bool(saved and saved['model_revision'] == inspected['model_revision']
                         and count >= len(CASES) and current_settings.router_encoder_path
                         and (Path(current_settings.router_encoder_path) / 'onnx' / 'model.onnx').is_file())
            if not ready:
                candidates.append(model)
        models = candidates
    if not models:
        if automatic:
            return False
        raise ValueError('No enabled provider-bound models. Register your Ollama node and fetch models first.')
    if len(models) > 16:
        if automatic:
            models = models[:16]  # Remaining records are picked up on the next check.
        else:
            raise ValueError('Preparation supports at most 16 models per run; use --provider-id to narrow the scope.')
    bases = {m['id']: native_base(m['endpoint_url'], args.allow_remote) for m in models}
    total = len(models) * len(CASES)
    print(f'Preparation will download/reuse one pinned multilingual encoder and run {total} short Ollama generations.')
    print('Models: ' + ', '.join(m['name'] for m in models))
    print('No Ollama models are downloaded. Profiles for these records will be updated only after successful completion.')
    print('This is a starter microtask benchmark, not proof of production answer quality. Memory/CPU will be used.')
    print('After calibration, the server trains per-model predictors; uncertain requests use an explicitly labelled measured default.')
    if not automatic and input('Type PREPARE to proceed: ').strip() != 'PREPARE':
        print('Cancelled. No models were run and no encoder was downloaded.')
        return
    owner = getattr(args, 'controller_owner', None) or uuid.uuid4().hex
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    initial_config = fetch_one('SELECT settings_json FROM routing_configuration WHERE id=1')
    old_profiles = {m['id']: fetch_one('SELECT updated_at FROM model_routing_profiles WHERE model_id=?', (m['id'],)) for m in models}
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT * FROM routing_preparation WHERE id=1').fetchone()
        if (previous and previous['status'] in {'running', 'checking'} and previous['updated_at'] >= cutoff
            and previous['owner'] != owner):
            raise ValueError('Another preparation is running. Wait for completion; do not launch duplicate model runs.')
        db.execute('''INSERT INTO routing_preparation(id,status,message,completed,total,owner,updated_at)
            VALUES(1,'running','Preparing encoder',0,?,?,?) ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,message=excluded.message,completed=0,total=excluded.total,
            owner=excluded.owner,updated_at=excluded.updated_at''', (total, owner, utc_now()))
    finished = threading.Event()
    def heartbeat():
        while not finished.wait(10):
            try:
                with get_db() as db:
                    db.execute('UPDATE routing_preparation SET updated_at=? WHERE id=1 AND owner=? AND status=?',
                               (utc_now(), owner, 'running'))
            except Exception:
                pass  # The atomic publish below still verifies ownership.
    threading.Thread(target=heartbeat, daemon=True).start()
    completed = 0
    published = False
    try:
        update_progress(owner, 'running', 'Checking installed Ollama models before encoder download', completed, total)
        for model in models:
            headers = {'Authorization': 'Bearer ' + model['api_key']} if model.get('api_key') else {}
            with httpx.Client(headers=headers, timeout=15, follow_redirects=False) as client:
                inspect_model(client, bases[model['id']], model['name'])
        update_progress(owner, 'running', 'Downloading or verifying the pinned encoder', completed, total)
        artifact, encoder_revision = prepare_default_encoder(args.artifact_dir)
        update_progress(owner, 'running', 'Loading encoder and representing calibration cases', completed, total)
        local_encoder = load_encoder(str(artifact), encoder_revision, get_settings().router_encoder_threads)
        for case in CASES:
            if len(local_encoder.tokenizer(case.prompt, truncation=False)['input_ids']) > local_encoder.max_seq_length:
                raise ValueError('A calibration case exceeds encoder context; preparation aborted without activation.')
        vectors = local_encoder.encode([c.prompt for c in CASES], normalize_embeddings=True, show_progress_bar=False).tolist()
        results = []
        for model in models:
            headers = {'Authorization': 'Bearer ' + model['api_key']} if model.get('api_key') else {}
            with httpx.Client(headers=headers, timeout=httpx.Timeout(180, connect=10), follow_redirects=False) as client:
                profile, digest, version, thinking = inspect_model(client, bases[model['id']], model['name'])
                scores = []
                latencies = []
                for index, case in enumerate(CASES):
                    update_progress(owner, 'running', f"Evaluating {model['name']} ({index+1}/{len(CASES)})", completed, total)
                    body = {'model': model['name'], 'prompt': case.prompt, 'system': SYSTEM,
                            'format': ANSWER_SCHEMA, 'stream': False, 'options': GENERATION_OPTIONS,
                            'keep_alive': '5m'}
                    if thinking:
                        body['think'] = False
                    result = json_request(client, 'POST', bases[model['id']] + '/api/generate', json=body)
                    if result.get('done') is not True or result.get('done_reason') != 'stop' or not isinstance(result.get('response'), str):
                        raise ValueError('Model response failed to finish normally; no partial calibration will be activated.')
                    scores.append(grade(result['response'], case))
                    durations = [result.get('prompt_eval_duration'), result.get('eval_duration')]
                    if any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) or value < 0 for value in durations) or sum(durations) <= 0:
                        raise ValueError('Ollama did not report valid calibration timings; refusing invented speed measurements.')
                    latencies.append(sum(durations) / 1_000_000)
                    completed += 1
                    print(f"[{completed}/{total}] {model['name']} {case.id}: {scores[-1]:.0f}", flush=True)
                # A runtime/tag update midway invalidates all these measurements.
                checked, checked_digest, checked_version, _ = inspect_model(client, bases[model['id']], model['name'])
                if (checked['model_revision'], checked_digest, checked_version) != (profile['model_revision'], digest, version):
                    raise ValueError('Model/runtime changed during calibration; rerun preparation.')
                results.append((model, profile, digest, version, scores, latencies))
        if not any(any(scores) for _, _, _, _, scores, _ in results):
            raise ValueError('All models failed all starter cases; automatic routing was not activated.')
        with get_db() as db:
            db.execute('BEGIN IMMEDIATE')
            lock = db.execute('SELECT owner FROM routing_preparation WHERE id=1').fetchone()
            current_config = db.execute('SELECT settings_json FROM routing_configuration WHERE id=1').fetchone()
            if not lock or lock['owner'] != owner or (dict(current_config) if current_config else None) != initial_config:
                raise ValueError('Router configuration changed during preparation; refusing to overwrite it.')
            now = utc_now()
            existing = db.execute('SELECT COUNT(*) FROM routing_evaluations').fetchone()[0]
            for model, profile, digest, version, scores, latencies in results:
                current = db.execute('''SELECT m.is_active,m.name,m.provider_id,p.is_active AS provider_active,p.endpoint_url,p.api_key
                    FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.id=?''', (model['id'],)).fetchone()
                current_profile = db.execute('SELECT updated_at FROM model_routing_profiles WHERE model_id=?', (model['id'],)).fetchone()
                if (not current or not current['is_active'] or not current['provider_active']
                    or current['name'] != model['name'] or current['provider_id'] != model['provider_id']
                    or current['endpoint_url'] != model['endpoint_url'] or current['api_key'] != model['api_key']
                    or (dict(current_profile) if current_profile else None) != old_profiles[model['id']]):
                    raise ValueError('Node/model profile changed during preparation; refusing to overwrite user changes.')
                saved_cases = {row['case_id'] for row in db.execute('SELECT case_id FROM routing_evaluations WHERE model_id=?', (model['id'],))}
                existing += sum(RUBRIC + ':' + case.id not in saved_cases for case in CASES)
                if existing > MAX_EVALUATIONS:
                    raise ValueError('Evaluation storage capacity exceeded; previous configuration was preserved.')
                db.execute('''INSERT INTO model_routing_profiles(model_id,capabilities_json,context_tokens,task_quality_json,evidence_source,updated_at,model_revision)
                    VALUES(?,?,?,'{}',?,?,?) ON CONFLICT(model_id) DO UPDATE SET
                    capabilities_json=excluded.capabilities_json,context_tokens=excluded.context_tokens,
                    task_quality_json='{}',evidence_source=excluded.evidence_source,updated_at=excluded.updated_at,model_revision=excluded.model_revision''',
                    (model['id'], json.dumps(profile['capabilities']), profile['context_tokens'], profile['evidence_source'], now, profile['model_revision']))
                db.execute('''INSERT INTO routing_runtime_identity VALUES(?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET
                    model_digest=excluded.model_digest,runtime_version=excluded.runtime_version,endpoint_url=excluded.endpoint_url''',
                    (model['id'], digest, version, model['endpoint_url']))
                # Keep prior audited cases. Replace only this versioned starter suite.
                for case, vector, score, latency in zip(CASES, vectors, scores, latencies):
                    case_id = RUBRIC + ':' + case.id
                    previous_case = db.execute('SELECT request_text FROM routing_evaluations WHERE case_id=? LIMIT 1', (case_id,)).fetchone()
                    if previous_case and previous_case['request_text'] != case.prompt:
                        raise ValueError('A starter case ID has conflicting request text; refusing incompatible benchmark data.')
                    db.execute('''INSERT INTO routing_evaluations
                        (model_id,case_id,model_revision,rubric,encoder_revision,request_text,embedding_json,score,source,updated_at,latency_ms)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(model_id,case_id) DO UPDATE SET model_revision=excluded.model_revision,
                        rubric=excluded.rubric,encoder_revision=excluded.encoder_revision,request_text=excluded.request_text,
                        embedding_json=excluded.embedding_json,score=excluded.score,source=excluded.source,updated_at=excluded.updated_at,latency_ms=excluded.latency_ms''',
                        (model['id'], case_id, profile['model_revision'], RUBRIC, encoder_revision, case.prompt,
                         json.dumps(vector), score, 'Measured Ollama native generation; exact-answer grading; ' + RUBRIC, now, latency))
            configuration = {'router_encoder_path': str(artifact), 'router_encoder_revision': encoder_revision,
                             'router_evaluation_rubric': RUBRIC, 'router_uncertain_policy': 'reject'}
            db.execute('''INSERT INTO routing_configuration VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET
                settings_json=excluded.settings_json,updated_at=excluded.updated_at''', (json.dumps(configuration), now))
            # Keep the controller lease across the handoff to predictor fitting.
            publish_status = 'running' if getattr(args, 'controller_owner', None) else 'complete'
            db.execute('''UPDATE routing_preparation SET status=?,message='Measured calibration activated; predictor fitting follows',completed=?,updated_at=?
                WHERE id=1 AND owner=?''', (publish_status, completed, now, owner))
        published = True
        print('Automatic routing activated with measured starter calibration. Refresh Models; inspect a preview before client use.')
        return True
    except BaseException as exc:
        if not published:
            message = str(exc) if isinstance(exc, ValueError) else 'Preparation interrupted or dependency/runtime failure. Previous configuration was preserved.'
            update_progress(owner, 'failed', message[:512], completed, total)
        raise
    finally:
        finished.set()
