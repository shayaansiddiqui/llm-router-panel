"""Versioned per-model ridge predictors, trained off the request path.

Scores predict the configured rubric, not universal answer correctness. Grouped
out-of-fold errors measure generalization; they are not confidence intervals.
No model names, parameter counts, generated classifiers or pickle artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from functools import lru_cache

from .config import get_router_settings
from .database import fetch_all, get_db, utc_now

TRAINER_VERSION = 'grouped-ridge-v2'
MIN_SAMPLES = 20
MAX_TRAINING_SAMPLES = 512
MAX_ROWS = 5000
REGULARIZATION = 1.0
_training_lock = threading.Lock()


def snapshot(rows):
    digest = hashlib.sha256(TRAINER_VERSION.encode())
    for row in sorted(rows, key=lambda item: item['case_id']):
        # Includes text/vector identity as well as grades and revision bindings.
        value = [row.get(key) for key in (
            'case_id', 'model_revision', 'encoder_revision', 'rubric',
            'request_text', 'embedding_json', 'score', 'latency_ms', 'evaluation_group', 'updated_at')]
        digest.update(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
    return digest.hexdigest()


def evaluation_rows():
    settings = get_router_settings()
    rows = fetch_all('''SELECT e.* FROM routing_evaluations e
        JOIN model_routing_profiles p ON p.model_id=e.model_id
        JOIN models m ON m.id=e.model_id JOIN providers n ON n.id=m.provider_id
        WHERE e.model_revision=p.model_revision AND e.encoder_revision=? AND e.rubric=?
          AND m.is_active=1 AND n.is_active=1 ORDER BY e.model_id,e.case_id LIMIT ?''',
        (settings.router_encoder_revision, settings.router_evaluation_rubric, MAX_ROWS + 1))
    if len(rows) > MAX_ROWS:
        raise ValueError('Evaluation capacity exceeded; archive obsolete cases before training.')
    return rows


def group_name(row):
    # Operators can explicitly group paraphrases through the evaluation API.
    # Starter IDs group entire task families, keeping greeting paraphrases and
    # closely related exercises out of both sides of a validation split.
    return row.get('evaluation_group') or re.sub(r'[-_]\d+$', '', row['case_id'])


def validated_rows(rows):
    dimension = None
    result = []
    for row in rows:
        try:
            vector = json.loads(row['embedding_json'])
            if (not isinstance(vector, list) or not 1 <= len(vector) <= 4096
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in vector)
                or not math.isfinite(row['score']) or not 0 <= row['score'] <= 1):
                continue
            norm = math.sqrt(sum(v * v for v in vector))
            if not 0.99 <= norm <= 1.01:
                continue
            dimension = dimension or len(vector)
            if len(vector) != dimension:
                continue
            result.append((row, vector))
        except (TypeError, ValueError):
            continue
    return result


def fit_artifact(rows):
    import numpy as np
    from threadpoolctl import threadpool_limits

    valid = validated_rows(rows)
    # Deterministic bounded sampling; no winner's traffic influences training.
    valid = sorted(valid, key=lambda item: hashlib.sha256(item[0]['case_id'].encode()).digest())[:MAX_TRAINING_SAMPLES]
    base = {'trainer': TRAINER_VERSION, 'status': 'insufficient_data',
            'sample_count': len(valid), 'row_count': len(rows), 'regularization': REGULARIZATION,
            'training_case_ids': [row['case_id'] for row, _ in valid],
            'weights': [], 'bias': 0.0, 'validation': None}
    if len(valid) < MIN_SAMPLES:
        return base
    x = np.asarray([vector for _, vector in valid], dtype=np.float64)
    y = np.asarray([row['score'] for row, _ in valid], dtype=np.float64)
    groups = [group_name(row) for row, _ in valid]
    unique = sorted(set(groups))
    base['group_count'] = len(unique)
    if len(unique) < 3:
        return base

    def fit(features, labels):
        center = features.mean(axis=0)
        mean = float(labels.mean())
        centered = features - center
        target = labels - mean
        if len(labels) <= features.shape[1]:
            matrix = centered @ centered.T + REGULARIZATION * np.eye(len(labels))
            weights = centered.T @ np.linalg.solve(matrix, target)
        else:
            matrix = centered.T @ centered + REGULARIZATION * np.eye(features.shape[1])
            weights = np.linalg.solve(matrix, centered.T @ target)
        return weights, mean - float(center @ weights)

    # At most five grouped folds, with no parameter search on held-out answers.
    folds = {group: index % min(5, len(unique)) for index, group in enumerate(unique)}
    errors, baseline_errors = [], []
    with threadpool_limits(limits=2):
        for fold in sorted(set(folds.values())):
            held = np.asarray([folds[group] == fold for group in groups])
            weights, bias = fit(x[~held], y[~held])
            prediction = np.clip(x[held] @ weights + bias, 0, 1)
            errors.extend(((prediction - y[held]) ** 2).tolist())
            baseline_errors.extend(((float(y[~held].mean()) - y[held]) ** 2).tolist())
        weights, bias = fit(x, y)
    rmse = math.sqrt(sum(errors) / len(errors))
    baseline_rmse = math.sqrt(sum(baseline_errors) / len(baseline_errors))
    # Merely fitting training answers does not activate a learned predictor.
    passed = rmse + 0.01 < baseline_rmse
    return {**base, 'status': 'validated' if passed else 'fallback_only',
            'weights': weights.tolist(), 'bias': bias,
            'validation': {'method': 'grouped_out_of_fold', 'folds': len(set(folds.values())),
                           'samples': len(errors), 'rmse': rmse, 'baseline_rmse': baseline_rmse,
                           'passed': passed, 'required_rmse_improvement': 0.01}}


def refresh_predictors(owner=None):
    """Called by the preparation worker; never trains during model selection."""
    if not _training_lock.acquire(blocking=False):
        return
    try:
        rows = evaluation_rows()
        grouped = {}
        for row in rows:
            grouped.setdefault(row['model_id'], []).append(row)
        stored = {row['model_id']: row for row in fetch_all('SELECT * FROM routing_predictors')}
        for model_id, samples in grouped.items():
            fingerprint = snapshot(samples)
            if stored.get(model_id, {}).get('snapshot_revision') == fingerprint:
                try:
                    artifact_from_json(stored[model_id]['artifact_json'])
                    continue
                except (ValueError, KeyError, TypeError):
                    pass  # Repair an invalid artifact from its measured snapshot.
            artifact = fit_artifact(samples)
            binding = samples[0]
            with get_db() as db:
                db.execute('BEGIN IMMEDIATE')
                if owner:
                    lock = db.execute('SELECT owner FROM routing_preparation WHERE id=1').fetchone()
                    if not lock or lock['owner'] != owner:
                        raise ValueError('Predictor training ownership was lost; publication stopped.')
                config = db.execute('SELECT settings_json FROM routing_configuration WHERE id=1').fetchone()
                settings = json.loads(config['settings_json']) if config else {}
                if (settings.get('router_encoder_revision') != binding['encoder_revision']
                    or settings.get('router_evaluation_rubric') != binding['rubric']):
                    continue
                current = [dict(row) for row in db.execute('''SELECT e.* FROM routing_evaluations e
                    JOIN model_routing_profiles p ON p.model_id=e.model_id
                    WHERE e.model_id=? AND e.model_revision=p.model_revision
                      AND e.encoder_revision=? AND e.rubric=? ORDER BY e.case_id''',
                    (model_id, binding['encoder_revision'], binding['rubric']))]
                if snapshot(current) != fingerprint:
                    continue  # A profile/evaluation changed while fitting.
                db.execute('''INSERT INTO routing_predictors
                    (model_id,model_revision,encoder_revision,rubric,snapshot_revision,artifact_json,updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET
                    model_revision=excluded.model_revision,encoder_revision=excluded.encoder_revision,
                    rubric=excluded.rubric,snapshot_revision=excluded.snapshot_revision,
                    artifact_json=excluded.artifact_json,updated_at=excluded.updated_at''',
                    (model_id, binding['model_revision'], binding['encoder_revision'], binding['rubric'],
                     fingerprint, json.dumps(artifact, allow_nan=False), utc_now()))
    finally:
        _training_lock.release()


def run_predictor_preparation(owner=None):
    """Keep lifecycle ownership alive across both calibration and fitting."""
    finished = threading.Event()
    if owner:
        with get_db() as db:
            changed = db.execute('''UPDATE routing_preparation SET status='running',
                message='Fitting and validating per-model quality predictors',updated_at=?
                WHERE id=1 AND owner=?''', (utc_now(), owner)).rowcount
            if not changed:
                raise ValueError('Preparation ownership was lost before predictor fitting.')
        def heartbeat():
            while not finished.wait(10):
                try:
                    with get_db() as db:
                        db.execute('UPDATE routing_preparation SET updated_at=? WHERE id=1 AND owner=?', (utc_now(), owner))
                except Exception:
                    pass  # Publication independently verifies ownership.
        threading.Thread(target=heartbeat, daemon=True).start()
    try:
        refresh_predictors(owner)
        if owner:
            with get_db() as db:
                db.execute('''UPDATE routing_preparation SET status='complete',
                    message='Calibration and predictor fitting checked; inspect per-model validation/fallback status',
                    updated_at=? WHERE id=1 AND owner=?''', (utc_now(), owner))
    finally:
        finished.set()


@lru_cache(maxsize=128)
def artifact_from_json(value):
    artifact = json.loads(value)
    if (not isinstance(artifact, dict) or artifact.get('trainer') != TRAINER_VERSION
        or artifact.get('status') not in {'validated', 'fallback_only', 'insufficient_data'}
        or not isinstance(artifact.get('weights'), list)
        or len(artifact['weights']) > 4096
        or not isinstance(artifact.get('training_case_ids'), list)
        or len(artifact['training_case_ids']) > MAX_TRAINING_SAMPLES
        or any(not isinstance(case, str) for case in artifact['training_case_ids'])):
        raise ValueError('Unsupported predictor version')
    if not all(math.isfinite(v) for v in artifact.get('weights', [])) or not math.isfinite(artifact['bias']):
        raise ValueError('Nonfinite predictor')
    validation = artifact.get('validation')
    if artifact['status'] != 'insufficient_data' and (
        not isinstance(validation, dict) or not isinstance(validation.get('rmse'), (int, float))
        or not math.isfinite(validation['rmse']) or not 0 <= validation['rmse'] <= 1):
        raise ValueError('Invalid predictor validation')
    return artifact


def predict_quality(query, revisions):
    """Return learned estimates and honest fallback evidence for scoped models."""
    rows = evaluation_rows()
    grouped = {}
    for row in rows:
        if row['model_revision'] == revisions.get(row['model_id']):
            grouped.setdefault(row['model_id'], []).append(row)
    predictors = {row['model_id']: row for row in fetch_all('SELECT * FROM routing_predictors')}
    usable = {}
    for model_id, samples in grouped.items():
        record = predictors.get(model_id)
        if not record or record['snapshot_revision'] != snapshot(samples):
            continue  # New/stale models wait for off-path fitting, not fake priors.
        try:
            artifact = artifact_from_json(record['artifact_json'])
            valid = validated_rows(samples)
            if len(valid) < MIN_SAMPLES or artifact['status'] == 'insufficient_data':
                continue
            vectors = {row['case_id']: vector for row, vector in valid if query is None or len(vector) == len(query)}
            if len(vectors) < MIN_SAMPLES:
                continue
            usable[model_id] = (samples, vectors, artifact)
        except (KeyError, ValueError, TypeError):
            continue
    # Identical case cohorts are necessary for cross-model fallback comparisons.
    # A partially profiled model must not shrink an established model cohort.
    cohorts = {}
    for model_id, (_, vectors, _) in usable.items():
        cohorts.setdefault(tuple(sorted(vectors)), []).append(model_id)
    if not cohorts:
        return {}
    predictions = {}
    settings = get_router_settings()
    for model_id in usable:
        samples, vectors, artifact = usable[model_id]
        cohort = tuple(sorted(vectors))
        by_case = {row['case_id']: row for row in samples}
        trained_vectors = [vectors[case] for case in artifact['training_case_ids'] if case in vectors]
        similarity = max((sum(a*b for a, b in zip(query, vector)) for vector in trained_vectors), default=0.0) if query is not None else 0.0
        learned = query is not None and artifact['status'] == 'validated' and len(artifact['weights']) == len(query)
        mean = max(0.0, min(1.0, artifact['bias'] + sum(a*b for a, b in zip(query, artifact['weights'])))) if learned else None
        rmse = artifact['validation']['rmse'] if artifact['validation'] else 1.0
        latency = [by_case[case].get('latency_ms') for case in cohort]
        timed = all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in latency)
        predictions[model_id] = {
            'source': 'learned_ridge_quality' if learned else 'measured_default_only',
            'neighbor_mean': mean, 'baseline_mean': sum(by_case[case]['score'] for case in cohort) / len(cohort),
            'score': max(0.0, mean - rmse) if mean is not None else 0.0,
            'learned_eligible': learned and similarity >= settings.router_min_similarity,
            'maximum_similarity': similarity, 'out_of_distribution': similarity < settings.router_min_similarity,
            'validation': artifact['validation'], 'uncertainty_penalty': rmse,
            'uncertainty_kind': 'heldout_rmse_not_probability_or_confidence_interval',
            'sample_count': len(cohort), 'model_revision': revisions[model_id],
            'case_set_revision': hashlib.sha256(json.dumps(cohort).encode()).hexdigest(),
            'comparable_cohort_size': len(cohorts[cohort]),
            'predictor_revision': predictors[model_id]['snapshot_revision'],
            'calibration_latency_ms': sum(latency) / len(latency) if timed else None,
            'latency_source': 'identical_short_calibration_cases_not_live_load',
        }
    return predictions
