"""Shared capability/context filtering and optional legacy evidence ranking.

Local LLM selection runs asynchronously after this filter and live inventory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from .database import fetch_all
from .config import get_settings
from .schemas import ModelRoutingProfileIn, RoutingOptions
from .semantic_router import quality_predictions
from .selection_policy import rank_sufficient_candidates


# Policy weights, not model quality claims. Profiles and observations supply data.
WEIGHTS = {
    "balanced": {"quality": 0.45, "speed": 0.30, "reliability": 0.25},
    "fast": {"quality": 0.15, "speed": 0.60, "reliability": 0.25},
    "quality": {"quality": 0.70, "speed": 0.05, "reliability": 0.25},
}
MIN_SAMPLES = 5


@dataclass(frozen=True)
class Candidate:
    model_id: int
    model_name: str
    provider: dict[str, Any]
    score: float
    evidence: dict[str, Any]
    warnings: list[str]

    def public(self) -> dict[str, Any]:
        # Never return provider credentials or the upstream request payload.
        return {
            "model_id": self.model_id,
            "model": self.model_name,
            "provider_id": self.provider["id"],
            "provider": self.provider["name"],
            "score": round(self.score, 6),
            "evidence": self.evidence,
            "warnings": self.warnings,
        }


def routing_requirements(payload: dict[str, Any]) -> tuple[RoutingOptions, set[str], int]:
    try:
        options = RoutingOptions.model_validate(payload.get("routing", {}))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid routing options.") from exc

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="Automatic routing requires non-empty messages.")
    modalities = payload.get("modalities", ["text"])
    if not isinstance(modalities, list) or any(value != "text" for value in modalities):
        raise HTTPException(status_code=400, detail="Automatic routing does not support audio output.")
    if "functions" in payload or "function_call" in payload:
        raise HTTPException(status_code=400, detail="Use tools instead of legacy function-calling fields for automatic routing.")
    required = set(options.required_capabilities)
    text_bytes = 0
    for message in messages:
        if not isinstance(message, dict):
            raise HTTPException(status_code=400, detail="Each message must be an object.")
        if message.get("role") not in {"system", "developer", "user", "assistant", "tool"}:
            raise HTTPException(status_code=400, detail="Invalid message role.")
        if message.get("tool_calls"):
            required.add("tools")
            text_bytes += len(json.dumps(message["tool_calls"], ensure_ascii=False).encode("utf-8"))
        content = message.get("content")
        if isinstance(content, str):
            text_bytes += len(content.encode("utf-8"))
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    raise HTTPException(status_code=400, detail="Invalid message content part.")
                if part.get("type") == "image_url":
                    required.add("vision")
                elif part.get("type") == "text" and isinstance(part.get("text"), str):
                    text_bytes += len(part["text"].encode("utf-8"))
                else:
                    raise HTTPException(status_code=400, detail="Automatic routing supports text and image_url content only.")
        elif content is not None:
            raise HTTPException(status_code=400, detail="Invalid message content.")
    tools = payload.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            raise HTTPException(status_code=400, detail="tools must be an array.")
        if tools:
            required.add("tools")
            text_bytes += len(json.dumps(tools, ensure_ascii=False).encode("utf-8"))
    response_format = payload.get("response_format")
    if response_format is not None:
        if not isinstance(response_format, dict):
            raise HTTPException(status_code=400, detail="response_format must be an object.")
        if response_format.get("type") == "json_schema":
            required.add("json_schema")
            text_bytes += len(json.dumps(response_format, ensure_ascii=False).encode("utf-8"))
    output_tokens = payload.get("max_completion_tokens", payload.get("max_tokens", 1024))
    if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens <= 0:
        raise HTTPException(status_code=400, detail="Output token budget must be a positive integer.")
    # Deliberately conservative screening estimate, not a tokenizer measurement.
    # Image-token usage is unknown; report that rather than claiming an exact fit.
    estimated_context = text_bytes + 1024 + output_tokens
    return options, required, max(options.min_context_tokens, estimated_context)


def rank_candidates(
    payload: dict[str, Any],
    models: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    *,
    provider_id: int | None = None,
    model_name: str | None = None,
    runtime_profiles: dict | None = None,
) -> tuple[list[Candidate], dict[str, Any]]:
    options, required, context_budget = routing_requirements(payload)
    profiles = {row["model_id"]: row for row in fetch_all("SELECT * FROM model_routing_profiles")}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    observations = {
        (row["provider_id"], row["requested_model"]): row
        for row in fetch_all(
            """
            SELECT provider_id, requested_model, COUNT(*) AS attempts,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
                   AVG(CASE WHEN status = 'success' THEN duration_ms END) AS duration_ms
            FROM request_logs
            WHERE created_at >= ? AND status IN ('success', 'failed')
            GROUP BY provider_id, requested_model
            """,
            (cutoff,),
        )
    }
    provider_map = {
        row["id"]: row for row in providers
        if row["is_active"] and (provider_id is None or row["id"] == provider_id)
    }
    weights = WEIGHTS[options.preference]
    candidates = []
    for model in models:
        provider = provider_map.get(model["provider_id"])
        if not provider or not model["is_active"] or (model_name and model["name"] != model_name):
            continue
        profile = profiles.get(model["id"], {})
        runtime = (runtime_profiles or {}).get(model['id'])
        if runtime:
            profile = {**profile, 'context_tokens': runtime['context_tokens'],
                       'capabilities_json': json.dumps(runtime['capabilities']),
                       'evidence_source': 'Local Ollama live advertised capabilities and requested native runtime context'}
        try:
            validated = ModelRoutingProfileIn.model_validate({
                "capabilities": json.loads(profile.get("capabilities_json", "[]")),
                "context_tokens": profile.get("context_tokens"),
                "task_quality": json.loads(profile.get("task_quality_json", "{}")),
                "evidence_source": profile.get("evidence_source", "unknown"),
            })
            capabilities = set(validated.capabilities)
            quality_map = validated.model_dump()["task_quality"]
        except (ValueError, TypeError, ValidationError):
            continue  # Corrupt metadata cannot justify a routing decision.
        if not required.issubset(capabilities):
            continue
        context_limit = validated.context_tokens
        if options.min_context_tokens and context_limit is None:
            continue
        if context_limit is not None and context_budget > context_limit:
            continue

        measurement = quality_map.get(options.task, {})
        quality_known = measurement.get("sample_count", 0) >= MIN_SAMPLES
        quality = measurement.get("score") if quality_known else None
        if model_name is not None and options.min_quality is not None and (quality is None or quality < options.min_quality):
            continue
        stats = observations.get((provider["id"], model["name"]), {})
        attempts = stats.get("attempts", 0)
        successes = stats.get("successes", 0)
        duration = stats.get("duration_ms") if successes >= MIN_SAMPLES else None
        # A neutral reliability prior prevents one success from implying certainty.
        reliability = (successes + 1) / (attempts + 2)
        speed_score = 0.5 if duration is None else 2000 / (2000 + max(duration, 0))
        # Unknown quality gets no quality credit, never an invented benchmark score.
        score = (
            weights["quality"] * (quality if quality is not None else 0)
            + weights["speed"] * speed_score
            + weights["reliability"] * reliability
        )
        warnings = ["live_health_and_capacity_unknown", "context_budget_is_a_screening_estimate"]
        if quality is None:
            warnings.append("task_quality_unknown_or_insufficient_samples")
        if duration is None:
            warnings.append("duration_unknown_or_insufficient_samples")
        if context_limit is None:
            warnings.append("context_limit_unknown")
        if "vision" in required:
            warnings.append("image_token_budget_not_measured")
        candidates.append(Candidate(
            model_id=model["id"], model_name=model["name"], provider=provider,
            score=score, warnings=warnings,
            evidence={
                "task_quality": quality,
                "quality_measurement": measurement if quality_known else None,
                "profile_source": profile.get("evidence_source"),
                "average_success_duration_ms": duration,
                "attempts_24h": attempts,
                "successes_24h": successes,
                "reliability_estimate": round(reliability, 6),
                "speed_policy_score": round(speed_score, 6),
                "context_tokens": context_limit,
            },
        ))
    candidates.sort(key=lambda row: (-row.score, row.provider["priority"], row.provider["id"], row.model_id))
    automatic = model_name is None
    selection = None
    compatible_count = len(candidates)
    measured_count = 0
    prediction_count = 0
    if automatic and candidates and get_settings().router_selection_mode == 'learned':
        predictions = quality_predictions(payload, {
            row.model_id: profiles.get(row.model_id, {}).get("model_revision") for row in candidates
        })
        prediction_count = len(predictions)
        measured = []
        for row in candidates:
            prediction = predictions.get(row.model_id)
            if prediction is None or (options.min_quality is not None and prediction["score"] < options.min_quality):
                continue
            score = (weights["quality"] * prediction["score"]
                     + weights["speed"] * row.evidence["speed_policy_score"]
                     + weights["reliability"] * row.evidence["reliability_estimate"])
            measured.append(Candidate(row.model_id, row.model_name, row.provider, score,
                {**row.evidence, "task_quality": None, "quality_measurement": None,
                 "semantic_quality": prediction},
                [warning for warning in row.warnings if warning != "task_quality_unknown_or_insufficient_samples"]
                + ["quality_prediction_not_a_quality_guarantee", "bounded_user_context", "long_text_uses_weighted_windows"]))
        measured_count = len(measured)
        candidates, selection = rank_sufficient_candidates(measured, options.preference)
    return candidates, {
        "policy": ("local-llm-selector-v1" if get_settings().router_selection_mode == 'local_llm'
                   else "validated-learned-router-v5") if automatic else "explicit-model-v1",
        "selection": selection,
        "compatible_candidates": compatible_count,
        "relevant_measured_candidates": measured_count if automatic else None,
        "current_predictors": prediction_count if automatic else None,
        "task": None if automatic else options.task,
        "preference": options.preference,
        "weights": None if automatic else weights,
        "required_capabilities": sorted(required),
        "context_screening_budget": context_budget,
        "task_source": "not_required" if automatic else "caller_or_default",
        "duration_metric": "full_upstream_attempt_not_time_to_first_token",
    }
