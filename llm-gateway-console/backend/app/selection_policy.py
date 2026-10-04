"""Quality admission before latency ranking, without names or size heuristics.

Thresholds are explicit policy choices, not calibrated accuracy guarantees.
Calibration latency is a short-answer proxy, not predicted live queue time.
"""
import math
from dataclasses import replace
from .database import fetch_one

QUALITY_FLOOR = 0.80
QUALITY_GAPS = {'balanced': 0.02, 'fast': 0.05, 'quality': 0.0}


def rank_sufficient_candidates(candidates, preference):
    if not candidates:
        return [], {'quality_floor': QUALITY_FLOOR, 'quality_gap': QUALITY_GAPS[preference]}

    def mean(candidate):
        prediction = candidate.evidence['semantic_quality']
        return prediction['neighbor_mean'] if prediction['neighbor_mean'] is not None else prediction['baseline_mean']

    measured = candidates
    candidates = [candidate for candidate in measured
                  if candidate.evidence['semantic_quality'].get('learned_eligible')
                  and candidate.evidence['semantic_quality']['uncertainty_penalty'] <= 0.25]
    if not candidates:
        return rank_default(measured, 'fallback_low_confidence')
    best = max(mean(candidate) for candidate in candidates)
    threshold = max(QUALITY_FLOOR, best - QUALITY_GAPS[preference])
    below_floor = best < QUALITY_FLOOR
    if below_floor:
        return rank_default(measured, 'fallback_predicted_quality_below_floor')
    admitted = [candidate for candidate in candidates if mean(candidate) + 1e-9 >= threshold]
    known = [candidate for candidate in admitted if candidate.evidence['semantic_quality'].get('calibration_latency_ms') is not None]
    # Require comparable speed for the whole quality-admitted cohort. Missing
    # measurements are not treated as fast and do not grant winner-only priors.
    use_speed = (len(known) == len(admitted) and
                 len({candidate.evidence['semantic_quality']['case_set_revision'] for candidate in admitted}) == 1)
    slowest = max((candidate.evidence['semantic_quality']['calibration_latency_ms'] for candidate in known), default=1)

    annotated = []
    for candidate in candidates:
        sufficient = mean(candidate) + 1e-9 >= threshold
        latency = candidate.evidence['semantic_quality'].get('calibration_latency_ms')
        evidence = {**candidate.evidence, 'selection': {
            'observed_quality_mean': mean(candidate), 'quality_threshold': threshold,
            'quality_sufficient': sufficient, 'below_policy_floor': below_floor,
            'latency_used': use_speed and sufficient,
            'traffic_reliability_used': False,
        }}
        score = (2 + (1 - latency / (slowest + 1)) if use_speed and sufficient
                 else 2 + mean(candidate) if sufficient else mean(candidate))
        warnings = list(candidate.warnings)
        if not use_speed:
            warnings.append('comparable_calibration_latency_missing; quality_only_fallback')
        warnings.append('short_nonthinking_benchmark_latency_is_not_live_thinking_latency')
        annotated.append(replace(candidate, score=score, evidence=evidence, warnings=warnings))

    def key(candidate):
        evidence = candidate.evidence['selection']
        sufficient = evidence['quality_sufficient']
        latency = candidate.evidence['semantic_quality'].get('calibration_latency_ms', math.inf)
        return (not sufficient, latency if use_speed and sufficient else 0,
                -mean(candidate), candidate.provider['priority'], candidate.provider['id'], candidate.model_id)

    # Rejected records are diagnostic only, not eligible failover targets.
    eligible = [candidate for candidate in annotated if candidate.evidence['selection']['quality_sufficient']]
    return sorted(eligible, key=key), {
        'quality_floor': QUALITY_FLOOR, 'quality_gap': QUALITY_GAPS[preference],
        'admission_threshold': threshold, 'below_policy_floor': below_floor,
        'latency_used': use_speed, 'traffic_reliability_used': False,
        'rejected_model_ids': [candidate.model_id for candidate in annotated
                               if not candidate.evidence['selection']['quality_sufficient']],
        'method': 'fastest_within_observed_quality_band' if use_speed else 'quality_only_missing_comparable_latency',
        'decision_type': 'learned_selection',
    }


def rank_default(candidates, reason):
    """Explicit default policy, not a fabricated request-specific prediction."""
    if not candidates:
        return [], {'decision_type': 'unavailable', 'reason': 'no_current_measured_predictor'}
    defaults = fetch_one('SELECT fallback_model_id FROM routing_defaults WHERE id=1') or {}
    configured = defaults.get('fallback_model_id')
    selected = next((candidate for candidate in candidates if candidate.model_id == configured), None)
    source = 'operator_configured' if selected else 'highest_shared_suite_mean'
    if selected is None:
        # Prefer the largest comparable cohort before comparing aggregate
        # grades. Scores from disjoint case sets are not interchangeable.
        cohorts = {}
        for candidate in candidates:
            cohort = candidate.evidence['semantic_quality']['case_set_revision']
            cohorts.setdefault(cohort, []).append(candidate)
        cohort = max(cohorts, key=lambda key: (len({candidate.evidence['semantic_quality']['model_revision'] for candidate in cohorts[key]}),
            cohorts[key][0].evidence['semantic_quality']['sample_count'], key))
        selected = min(cohorts[cohort], key=lambda candidate: (
            -candidate.evidence['semantic_quality']['baseline_mean'],
            candidate.provider['priority'], candidate.provider['id'], candidate.model_id))
    # Fail over only to equivalent selected model records within the same
    # measured cohort, never to an uncalibrated or API-key-forbidden model.
    matching = [candidate for candidate in candidates if candidate.model_name == selected.model_name
                and candidate.evidence['semantic_quality']['case_set_revision'] == selected.evidence['semantic_quality']['case_set_revision']]
    matching.sort(key=lambda candidate: (candidate.model_id != selected.model_id,
                                         candidate.provider['priority'], candidate.model_id))
    ranked = [replace(candidate,
        score=candidate.evidence['semantic_quality']['baseline_mean'],
        evidence={**candidate.evidence, 'selection': {
            'decision_type': reason, 'default_source': source,
            'request_specific_quality_established': False,
        }}, warnings=[*candidate.warnings, reason,
                      'default_model_is_not_a_task_quality_guarantee']) for candidate in matching]
    return ranked, {'decision_type': reason, 'default_source': source,
                    'configured_default_eligible': selected.model_id == configured,
                    'method': 'measured_default_not_request_specific', 'latency_used': False}
