"""Local representation and off-path-trained quality prediction.

No generation, network downloads, model-name heuristics, or request-text logging.
An encoder is representation, not evidence of a model's answer quality.
"""
from __future__ import annotations

import json
import math
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import get_router_settings
from .learned_router import predict_quality, MIN_SAMPLES
from .encoder_artifact import artifact_revision
from .text_representation import encode_text

MAX_EVALUATIONS = 5000
_lock = threading.Lock()


def configuration() -> dict[str, Any]:
    settings = get_router_settings()
    configured = bool(settings.router_encoder_path and settings.router_encoder_revision
                      and settings.router_evaluation_rubric)
    return {"configured": configured, "encoder_revision": settings.router_encoder_revision or None,
            "rubric": settings.router_evaluation_rubric or None,
            "minimum_training_samples": MIN_SAMPLES, "maximum_cases": MAX_EVALUATIONS,
            "minimum_similarity": settings.router_min_similarity,
            "mode": "validated_per_model_ridge_prediction",
            "uncertain_policy": "measured_default",
            "capacity_telemetry": "not_implemented"}


def encoder():
    settings = get_router_settings()
    if not configuration()["configured"]:
        raise HTTPException(503, "Automatic routing requires a local encoder and scored evaluation data. See docs/model-selection.md.")
    path = Path(settings.router_encoder_path).expanduser().resolve()
    if not path.is_dir() or not (path / "onnx" / "model.onnx").is_file():
        raise HTTPException(503, "Router encoder artifact is missing; automatic routing is unavailable.")
    if not 0 < settings.router_encoder_threads <= 8 or not 0 < settings.router_min_similarity < 1:
        raise HTTPException(503, "Router encoder configuration is invalid.")
    return load_encoder(str(path), settings.router_encoder_revision, settings.router_encoder_threads)


@lru_cache(maxsize=1)
def load_encoder(path_string: str, revision: str, threads: int):
    path = Path(path_string)
    try:
        if artifact_revision(path) != revision:
            raise ValueError("Encoder identity mismatch")
        import onnxruntime
        from sentence_transformers import SentenceTransformer
        session = onnxruntime.SessionOptions()
        session.intra_op_num_threads = threads
        session.inter_op_num_threads = 1
        model_config = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        # Transformers 4.57.6 misdetects locally saved non-Mistral artifacts
        # from 4.57.3+ as Mistral. Opt out only for verified BERT metadata;
        # applying the Mistral regex patch would change this encoder's tokens.
        tokenizer_kwargs = {'fix_mistral_regex': False} if model_config.get('model_type') == 'bert' else {}
        return SentenceTransformer(
            str(path), backend="onnx", device="cpu", local_files_only=True, trust_remote_code=False,
            tokenizer_kwargs=tokenizer_kwargs,
            model_kwargs={"export": False, "file_name": "onnx/model.onnx",
                          "provider": "CPUExecutionProvider", "session_options": session},
        )
    except Exception as exc:
        # Do not disclose local paths, dependency traces, or prompt content.
        raise HTTPException(503, "Local router encoder could not load. Check the offline artifact and optional dependencies.") from exc


def encode(text: str) -> list[float]:
    """Encode bounded windows instead of silently truncating the request."""
    if not _lock.acquire(timeout=0.25):
        raise HTTPException(503, "Routing encoder is busy. Retry with backoff or supply an explicit model.")
    try:
        model = encoder()
        try:
            vector = encode_text(model, text)
        except ValueError as exc:
            raise HTTPException(422, "Request exceeds routing window capacity or representation is invalid. Supply an explicit model.") from exc
        except Exception as exc:
            raise HTTPException(503, "Local routing encoding failed.") from exc
    finally:
        _lock.release()
    if not vector or any(not math.isfinite(value) for value in vector):
        raise HTTPException(503, "Encoder returned an invalid representation.")
    return vector


def request_text(payload: dict[str, Any]) -> str:
    # Latest user message identifies the immediate task; history is deliberately
    # not silently summarized. Structured capability checks happen separately.
    for message in reversed(payload["messages"]):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else "\n".join(
            part["text"] for part in (content or [])
            if part.get("type") == "text"
        )
        if text.strip():
            if len(text) > 8192:
                raise HTTPException(422, "Routing text exceeds 8192 characters. Supply an explicit model.")
            return text
        # Do not classify an older task when the latest user request is image-only.
        break
    raise HTTPException(422, "Semantic routing requires text in the latest user request; use an explicit model for image-only requests.")


def quality_predictions(payload: dict[str, Any], revisions: dict[int, str | None]) -> dict[int, dict[str, Any]]:
    settings = get_router_settings()
    latest = request_text(payload)
    # Bounded user context helps interpret follow-ups, without summarization or
    # storing generated reasoning. The latest request is never truncated.
    users = [message for message in payload['messages'] if message.get('role') == 'user']
    previous = []
    remaining = 8192 - len(latest)
    for message in reversed(users[:-1][-2:]):
        content = message.get('content')
        if isinstance(content, str) and content.strip() and remaining > 2:
            excerpt = content[-min(1024, remaining-2):]
            previous.insert(0, excerpt)
            remaining -= len(excerpt) + 2
    text = '\n\n'.join([*previous, latest])
    try:
        query = encode(text)
        unavailable = False
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        query = None
        unavailable = True
    current = get_router_settings()
    if (current.router_encoder_revision, current.router_evaluation_rubric) != (settings.router_encoder_revision, settings.router_evaluation_rubric):
        raise HTTPException(503, "Router configuration changed during selection; retry the request.")
    try:
        predictions = predict_quality(query, revisions)
    except ValueError as exc:
        raise HTTPException(503, 'Router evaluation capacity or predictor data is invalid.') from exc
    for prediction in predictions.values():
        prediction['encoder_unavailable'] = unavailable
        prediction['context_source'] = 'latest_and_up_to_two_bounded_previous_user_messages'
    current = get_router_settings()
    if (current.router_encoder_revision, current.router_evaluation_rubric) != (settings.router_encoder_revision, settings.router_evaluation_rubric):
        raise HTTPException(503, 'Router configuration changed during prediction; retry the request.')
    return predictions
