from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import fnmatch
import json
import secrets
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import get_settings, get_router_settings
from .database import fetch_all, fetch_one, get_db, init_db, utc_now
from .node_readiness import rank_ready_candidates
from .llm_selector import selector_inventory
from .ollama_chat import chat_request, stream_chunks as ollama_stream_chunks, completion as ollama_completion
from .stream_recovery import recover as recover_stream
from .automatic_preparation import automatic_preparation
from .learned_router import evaluation_rows, snapshot, TRAINER_VERSION, artifact_from_json
from .node_scheduler import reserve_provider, renew as renew_node_lease, release as release_node_lease
from .semantic_router import configuration as router_configuration, encode, MAX_EVALUATIONS
from .schemas import (
    AdminLoginIn,
    ApiKeyIn,
    ModelIn,
    ModelRoutingProfileIn,
    RoutingEvaluationIn,
    RoutingDefaultsIn,
    ProviderIn,
    RoutingRuleIn,
)

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Gateway-Routing-Policy", "X-Gateway-Routing-Decision",
                    "X-Gateway-Decision-Id", "X-Gateway-Selected-Model-Id", "X-Gateway-Selected-Provider-Id"],
)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR, check_dir=False), name="frontend-assets")


@app.middleware("http")
async def protect_admin_api(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path == "/api/auth/login":
        return await call_next(request)

    token = bearer_token(request)
    if not token or not verify_admin_token(token):
        return JSONResponse(status_code=401, content={"detail": "Admin authentication required."})
    return await call_next(request)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    automatic_preparation.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await automatic_preparation.stop()


def normalize_bool(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in ("is_active",):
        if key in normalized:
            normalized[key] = bool(normalized[key])
    return normalized


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return f"lgc_{secrets.token_urlsafe(32)}"


def bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def sign_admin_payload(payload_part: str) -> str:
    signature = hmac.new(
        settings.admin_session_secret.encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return b64url_encode(signature)


def create_admin_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + settings.admin_session_ttl_seconds,
    }
    payload_part = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_part}.{sign_admin_payload(payload_part)}"


def verify_admin_token(token: str) -> dict[str, Any] | None:
    try:
        payload_part, signature_part = token.split(".", 1)
        expected_signature = sign_admin_payload(payload_part)
        if not secrets.compare_digest(signature_part, expected_signature):
            return None
        payload = json.loads(b64url_decode(payload_part))
    except Exception:
        return None

    if payload.get("exp", 0) < int(time.time()):
        return None
    if payload.get("sub") != settings.admin_username:
        return None
    return payload


def verify_admin_credentials(username: str, password: str) -> bool:
    return secrets.compare_digest(username, settings.admin_username) and secrets.compare_digest(password, settings.admin_password)


def api_key_count() -> int:
    row = fetch_one("SELECT COUNT(*) AS count FROM api_keys")
    return int(row["count"]) if row else 0


def api_key_provider_ids(api_key_id: int) -> list[int]:
    rows = fetch_all("SELECT provider_id FROM api_key_providers WHERE api_key_id = ?", (api_key_id,))
    return [int(row["provider_id"]) for row in rows]


def api_key_model_ids(api_key_id: int) -> list[int]:
    rows = fetch_all("SELECT model_id FROM api_key_models WHERE api_key_id = ?", (api_key_id,))
    return [int(row["model_id"]) for row in rows]


def api_key_model_rows(api_key_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT models.id, models.name, models.provider_id
        FROM api_key_models
        JOIN models ON models.id = api_key_models.model_id
        WHERE api_key_models.api_key_id = ?
        """,
        (api_key_id,),
    )


def api_key_model_names(api_key_id: int) -> list[str]:
    rows = fetch_all(
        """
        SELECT models.name
        FROM api_key_models
        JOIN models ON models.id = api_key_models.model_id
        WHERE api_key_models.api_key_id = ?
        """,
        (api_key_id,),
    )
    return [str(row["name"]) for row in rows]


def api_key_model_provider_ids(api_key_id: int) -> list[int]:
    rows = fetch_all(
        """
        SELECT DISTINCT models.provider_id
        FROM api_key_models
        JOIN models ON models.id = api_key_models.model_id
        WHERE api_key_models.api_key_id = ? AND models.provider_id IS NOT NULL
        """,
        (api_key_id,),
    )
    return [int(row["provider_id"]) for row in rows]


def hydrate_api_key_scopes(api_key: dict[str, Any]) -> dict[str, Any]:
    direct_provider_ids = api_key_provider_ids(api_key["id"])
    model_rows = api_key_model_rows(api_key["id"])
    model_provider_ids = [int(row["provider_id"]) for row in model_rows if row["provider_id"] is not None]
    api_key["direct_provider_ids"] = direct_provider_ids
    api_key["provider_ids"] = sorted(set(direct_provider_ids + model_provider_ids))
    api_key["model_ids"] = api_key_model_ids(api_key["id"])
    api_key["model_names"] = [str(row["name"]) for row in model_rows]
    return api_key


def authenticate_gateway_api_key(request: Request) -> dict[str, Any] | None:
    if api_key_count() == 0:
        return None

    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key.")

    api_key = fetch_one(
        """
        SELECT api_keys.*
        FROM api_keys
        WHERE api_keys.key_hash = ?
        """,
        (hash_api_key(token),),
    )
    if not api_key or not api_key["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key.")

    api_key = hydrate_api_key_scopes(api_key)
    with get_db() as db:
        db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (utc_now(), api_key["id"]))
    return api_key


def requested_provider_name(payload: dict[str, Any]) -> str | None:
    value = payload.get("provider")
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="provider must be a string.")
    return value.strip() or None


def resolve_provider_by_name(provider_name: str | None) -> dict[str, Any] | None:
    if not provider_name:
        return None

    providers = fetch_all(
        """
        SELECT *
        FROM providers
        WHERE lower(name) = lower(?)
        ORDER BY id ASC
        """,
        (provider_name,),
    )
    if not providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' was not found.")

    provider = normalize_bool(providers[0])
    if not provider["is_active"]:
        raise HTTPException(status_code=503, detail=f"Provider '{provider['name']}' is not active.")
    return provider


def model_rows_by_name(model_name: str | None) -> list[dict[str, Any]]:
    if not model_name:
        return []
    return [normalize_bool(row) for row in fetch_all("SELECT * FROM models WHERE name = ?", (model_name,))]


def active_model_provider_ids(model_name: str | None) -> set[int]:
    rows = fetch_all(
        """
        SELECT DISTINCT provider_id
        FROM models
        WHERE name = ? AND is_active = 1 AND provider_id IS NOT NULL
        """,
        (model_name,),
    ) if model_name else []
    return {int(row["provider_id"]) for row in rows}


def validate_provider_model_pair(provider: dict[str, Any] | None, model_name: str | None) -> None:
    if not provider or not model_name:
        return

    model_rows = model_rows_by_name(model_name)
    if not model_rows:
        return

    compatible_rows = [
        model for model in model_rows
        if model["provider_id"] is None or int(model["provider_id"]) == int(provider["id"])
    ]
    if not compatible_rows:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_name}' is not available under provider '{provider['name']}'.",
        )
    if not any(model["is_active"] for model in compatible_rows):
        raise HTTPException(
            status_code=503,
            detail=f"Model '{model_name}' is not active under provider '{provider['name']}'.",
        )


def validate_gateway_api_key(
    request: Request,
    requested_model: str | None,
    requested_provider: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    api_key = authenticate_gateway_api_key(request)
    if not api_key:
        return None

    direct_provider_ids = api_key["direct_provider_ids"]
    model_rows = api_key_model_rows(api_key["id"])
    provider_ids = api_key["provider_ids"]
    model_names = api_key["model_names"]

    if requested_provider and provider_ids and requested_provider["id"] not in provider_ids:
        raise HTTPException(status_code=403, detail="API key is not allowed to use this provider.")

    requested_provider_id = requested_provider["id"] if requested_provider else None
    allowed_by_model = any(
        row["name"] == requested_model
        and (requested_provider_id is None or row["provider_id"] is None or int(row["provider_id"]) == requested_provider_id)
        for row in model_rows
    )
    allowed_by_provider = False
    if direct_provider_ids:
        if requested_provider:
            allowed_by_provider = requested_provider["id"] in direct_provider_ids
        elif requested_model:
            requested_model_rows = model_rows_by_name(requested_model)
            allowed_by_provider = (
                not requested_model_rows
                or any(row["provider_id"] is None or int(row["provider_id"]) in direct_provider_ids for row in requested_model_rows)
            )
        else:
            allowed_by_provider = True

    if model_names and not allowed_by_model and not allowed_by_provider:
        raise HTTPException(status_code=403, detail="API key is not allowed to use this model.")

    return api_key


def scoped_public_models(api_key: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT models.*, providers.name AS provider_name
        FROM models
        LEFT JOIN providers ON providers.id = models.provider_id
        WHERE models.is_active = 1 AND (providers.id IS NULL OR providers.is_active = 1)
        ORDER BY models.name ASC, models.id ASC
        """
    )
    if not api_key:
        return rows

    direct_provider_ids = set(api_key["direct_provider_ids"])
    allowed_model_ids = set(api_key["model_ids"])
    if not direct_provider_ids and not allowed_model_ids:
        return rows

    scoped_rows = []
    for row in rows:
        provider_id = row["provider_id"]
        provider_allowed = provider_id is not None and int(provider_id) in direct_provider_ids
        model_allowed = int(row["id"]) in allowed_model_ids
        if provider_allowed or model_allowed:
            scoped_rows.append(row)
    return scoped_rows


def scoped_public_providers(api_key: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    providers = fetch_all(
        """
        SELECT *
        FROM providers
        WHERE is_active = 1
        ORDER BY priority ASC, id ASC
        """
    )
    if not api_key or not api_key.get("provider_ids"):
        return providers

    allowed_provider_ids = set(api_key["provider_ids"])
    return [provider for provider in providers if provider["id"] in allowed_provider_ids]


def list_active_providers(
    model_name: str | None,
    api_key: dict[str, Any] | None = None,
    requested_provider: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if requested_provider:
        return [requested_provider]

    providers = fetch_all(
        """
        SELECT * FROM providers
        WHERE is_active = 1
        ORDER BY priority ASC, id ASC
        """
    )
    if api_key and api_key.get("provider_ids"):
        allowed_provider_ids = set(api_key["provider_ids"])
        providers = [provider for provider in providers if provider["id"] in allowed_provider_ids]

    model_provider_ids = active_model_provider_ids(model_name)
    if model_provider_ids:
        providers = [provider for provider in providers if provider["id"] in model_provider_ids]

    if not model_name:
        return providers

    rules = fetch_all(
        """
        SELECT routing_rules.*, providers.is_active AS provider_is_active
        FROM routing_rules
        LEFT JOIN providers ON providers.id = routing_rules.provider_id
        WHERE routing_rules.is_active = 1
        ORDER BY routing_rules.priority ASC, routing_rules.id ASC
        """
    )
    ordered_ids: list[int] = []
    for rule in rules:
        if rule["provider_id"] and rule["provider_is_active"] and fnmatch.fnmatch(model_name, rule["model_pattern"]):
            ordered_ids.append(rule["provider_id"])

    provider_by_id = {provider["id"]: provider for provider in providers}
    selected = [provider_by_id[provider_id] for provider_id in ordered_ids if provider_id in provider_by_id]
    selected_ids = {provider["id"] for provider in selected}
    selected.extend(provider for provider in providers if provider["id"] not in selected_ids)
    return selected


def provider_chat_url(endpoint_url: str) -> str:
    url = endpoint_url.rstrip("/")
    if url.endswith("/v1/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def provider_models_url(endpoint_url: str) -> str:
    url = endpoint_url.rstrip("/")
    if url.endswith("/v1/models"):
        return url
    if url.endswith("/v1"):
        return f"{url}/models"
    return f"{url}/v1/models"


def extract_model_names(payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        for item in payload["data"]:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
    elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
        for item in payload["models"]:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
            elif isinstance(item, str):
                names.append(item)
    return sorted(set(names))


async def fetch_model_names_for_provider(provider: dict[str, Any]) -> list[str]:
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"

    timeout = provider["timeout_seconds"] or settings.provider_request_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(provider_models_url(provider["endpoint_url"]), headers=headers)

    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"Provider returned HTTP {response.status_code}: {response.text[:300]}",
        )

    try:
        return extract_model_names(response.json())
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Provider returned invalid JSON.") from exc


def save_provider_models(provider_id: int, model_names: list[str]) -> dict[str, int]:
    now = utc_now()
    created = 0
    skipped = 0
    with get_db() as db:
        for model_name in model_names:
            exists = db.execute(
                "SELECT id FROM models WHERE provider_id = ? AND name = ?",
                (provider_id, model_name),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            db.execute(
                """
                INSERT INTO models (provider_id, name, display_name, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (provider_id, model_name, model_name, 1, now, now),
            )
            created += 1
    return {"found": len(model_names), "created": created, "skipped": skipped}


def save_request_log(
    *,
    requested_model: str | None,
    provider: dict[str, Any] | None,
    status: str,
    status_code: int | None,
    error_message: str | None,
    duration_ms: int,
) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO request_logs (
                requested_model, provider_id, provider_name, status, status_code,
                error_message, duration_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requested_model,
                provider["id"] if provider else None,
                provider["name"] if provider else None,
                status,
                status_code,
                error_message,
                duration_ms,
                utc_now(),
            ),
        )


def provider_request_headers(provider: dict[str, Any], *, stream: bool = False) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    return headers


def record_dispatch(decision_id, provider_id):
    if not decision_id:
        return
    with get_db() as db:
        row = db.execute('SELECT decision_json FROM routing_decisions WHERE id=?', (decision_id,)).fetchone()
        if row:
            decision = json.loads(row['decision_json'])
            decision['served_provider_id'] = provider_id
            db.execute('UPDATE routing_decisions SET decision_json=? WHERE id=?',
                       (json.dumps(decision, allow_nan=False), decision_id))


async def iter_provider_stream(
    *,
    client: httpx.AsyncClient,
    response: httpx.Response,
    provider: dict[str, Any],
    requested_model: str,
    started: float,
    lease: str,
    native: bool = False,
) -> AsyncIterator[bytes]:
    status = "success"
    error_message = None
    renewed = time.monotonic()
    try:
        chunks = ollama_stream_chunks(response) if native else response.aiter_bytes()
        async for chunk in chunks:
            if time.monotonic() - renewed >= 30:
                renew_node_lease(lease)
                renewed = time.monotonic()
            if chunk:
                yield chunk
    except asyncio.CancelledError:
        status = "cancelled"
        error_message = "Client disconnected during stream."
        raise
    except Exception as exc:
        status = "failed"
        error_message = f"{type(exc).__name__}: {str(exc) or 'Upstream stream failed.'}"[:500]
        raise
    finally:
        release_node_lease(lease)
        duration_ms = int((time.perf_counter() - started) * 1000)
        await response.aclose()
        await client.aclose()
        save_request_log(
            requested_model=requested_model,
            provider=provider,
            status=status,
            status_code=response.status_code,
            error_message=error_message,
            duration_ms=duration_ms,
        )


async def stream_chat_completion(
    *,
    providers: list[dict[str, Any]],
    forward_payload: dict[str, Any],
    requested_model: str,
    balance_nodes: bool = False,
    decision_id: str | None = None,
) -> StreamingResponse:
    last_error = "No provider attempted."
    remaining = list(providers)
    while remaining:
        provider, lease = reserve_provider(remaining if balance_nodes else remaining[:1])
        remaining = [item for item in remaining if item['id'] != provider['id']]
        handed_off = False
        started = time.perf_counter()
        timeout = provider["timeout_seconds"] or settings.provider_request_timeout_seconds
        client = httpx.AsyncClient(timeout=timeout)

        try:
            url, body, native = await chat_request(provider, forward_payload, provider_chat_url(provider['endpoint_url']))
            request = client.build_request(
                "POST",
                url,
                json=body,
                headers=provider_request_headers(provider, stream=True),
            )
            response = await client.send(request, stream=True)

            if response.is_success:
                record_dispatch(decision_id, provider['id'])
                async def cleanup_stream(client=client, response=response, lease=lease):
                    release_node_lease(lease)
                    await response.aclose()
                    await client.aclose()
                stream = StreamingResponse(
                    iter_provider_stream(
                        client=client,
                        response=response,
                        provider=provider,
                        requested_model=requested_model,
                        started=started,
                        lease=lease,
                        native=native,
                    ),
                    status_code=response.status_code,
                    background=BackgroundTask(cleanup_stream),
                    media_type='text/event-stream' if native else response.headers.get("content-type", "text/event-stream"),
                    headers={
                        "Cache-Control": response.headers.get("cache-control", "no-cache"),
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                        "X-Gateway-Selected-Provider-Id": str(provider['id']),
                    },
                )
                handed_off = True
                return stream

            error_body = bytearray()
            async for chunk in response.aiter_bytes():
                error_body.extend(chunk[:4096-len(error_body)])
                if len(error_body) >= 4096:
                    break
            duration_ms = int((time.perf_counter() - started) * 1000)
            last_error = f"{provider['name']} returned HTTP {response.status_code}"
            save_request_log(
                requested_model=requested_model,
                provider=provider,
                status="failed",
                status_code=response.status_code,
                error_message=error_body.decode("utf-8", errors="replace")[:500],
                duration_ms=duration_ms,
            )
            await response.aclose()
            await client.aclose()
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            failure = f"{type(exc).__name__}: {str(exc) or 'Upstream request failed (timeout or connection error).'}"
            last_error = f"{provider['name']} failed: {failure}"
            save_request_log(
                requested_model=requested_model,
                provider=provider,
                status="failed",
                status_code=None,
                error_message=failure[:500],
                duration_ms=duration_ms,
            )
            await client.aclose()
        finally:
            if not handed_off:
                release_node_lease(lease)
                await client.aclose()

    raise HTTPException(status_code=502, detail=f"All providers failed. Last error: {last_error}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def public_models(request: Request) -> dict[str, Any]:
    api_key = authenticate_gateway_api_key(request)
    models = scoped_public_models(api_key)
    return {
        "object": "list",
        "data": [
            {
                "id": model["name"],
                "object": "model",
                "created": 0,
                "owned_by": model["provider_name"] or "gateway",
                "provider": model["provider_name"],
            }
            for model in models
        ],
    }


@app.get("/v1/providers")
def public_providers(request: Request) -> dict[str, Any]:
    api_key = authenticate_gateway_api_key(request)
    providers = scoped_public_providers(api_key)
    models = scoped_public_models(api_key)
    models_by_provider: dict[int, list[str]] = {}
    for model in models:
        if model["provider_id"] is None:
            continue
        models_by_provider.setdefault(int(model["provider_id"]), []).append(model["name"])

    return {
        "object": "list",
        "data": [
            {
                "id": provider["name"],
                "object": "provider",
                "priority": provider["priority"],
                "models": models_by_provider.get(int(provider["id"]), []),
            }
            for provider in providers
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    return await execute_chat_completion(request, admin_playground=False)


@app.post("/api/playground/chat/completions")
async def playground_chat_completions(request: Request) -> Any:
    # Admin-only inference uses the same routing/forwarding/logging pipeline.
    # Verify here as well as in middleware; no caller-controlled bypass flag.
    token = bearer_token(request)
    if not token or not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    return await execute_chat_completion(request, admin_playground=True)


async def execute_chat_completion(request: Request, *, admin_playground: bool) -> Any:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Request body exceeds 4 MiB.")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Request body must contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    requested_model = payload.get("model")
    automatic = requested_model is None or requested_model == "auto"
    if not automatic and (not isinstance(requested_model, str) or not requested_model.strip()):
        raise HTTPException(status_code=400, detail="model must be a non-empty string.")
    if not automatic:
        requested_model = requested_model.strip()

    provider_name = requested_provider_name(payload)
    requested_provider = resolve_provider_by_name(provider_name)
    decision_headers = {}
    if automatic or "routing" in payload:
        api_key = None if admin_playground else authenticate_gateway_api_key(request)
        candidates, decision = await rank_ready_candidates(
            payload,
            scoped_public_models(api_key),
            scoped_public_providers(api_key),
            provider_id=requested_provider["id"] if requested_provider else None,
            model_name=None if automatic else requested_model,
        )
        if not candidates:
            if not decision.get("reachable_model_records"):
                explanation = "No permitted model passed the live inventory check. Check the node connection and imported model records."
            elif not decision.get("compatible_candidates"):
                explanation = ("Reachable models do not meet the request capabilities or context budget "
                               f"({decision.get('context_screening_budget')} estimated units). Start a new chat, reduce the output limit, or use a compatible explicit model.")
            elif not decision.get("relevant_measured_candidates"):
                explanation = ("Prepared models do not satisfy the explicit minimum quality requirement. A fallback cannot bypass that requirement."
                    if decision.get('current_predictors') else
                    "No current trained predictor or measured fallback is ready within your permitted models. Check Models preparation/training status; new or changed models wait for compatible measurements and background fitting.")
            else:
                explanation = "No evaluated candidate meets the automatic quality floor for this request. Select a model explicitly or improve the relevant evaluation coverage."
            raise HTTPException(
                status_code=503,
                detail=explanation,
            )
        selected = candidates[0]
        requested_model = selected.model_name
        # Failover is limited to the selected model and candidates that passed
        # the same capability, quality and API-key filters. No silent model swap.
        providers = []
        seen = set()
        for candidate in candidates:
            if candidate.model_name == requested_model and candidate.provider["id"] not in seen:
                providers.append(candidate.provider)
                seen.add(candidate.provider["id"])
        decision_headers = {
            "X-Gateway-Routing-Policy": decision["policy"],
            "X-Gateway-Selected-Model-Id": str(selected.model_id),
            "X-Gateway-Routing-Decision": (decision.get('selection') or {}).get('decision_type', 'explicit_model'),
        }
        # Bounded audit records contain no messages, keys, embeddings or weights.
        with get_db() as db:
            cursor = db.execute('''INSERT INTO routing_decisions(selected_model_id,decision_json,created_at)
                VALUES(?,?,?)''', (selected.model_id, json.dumps({
                    'policy': decision['policy'], 'selection': decision.get('selection'),
                    'selected': selected.public(), 'context_screening_budget': decision['context_screening_budget'],
                }, allow_nan=False), utc_now()))
            decision_headers['X-Gateway-Decision-Id'] = str(cursor.lastrowid)
            db.execute('DELETE FROM routing_decisions WHERE id NOT IN (SELECT id FROM routing_decisions ORDER BY id DESC LIMIT 1000)')
    else:
        validate_provider_model_pair(requested_provider, requested_model)
        api_key = None if admin_playground else validate_gateway_api_key(request, requested_model, requested_provider)
        providers = list_active_providers(requested_model, api_key, requested_provider)

    payload["model"] = requested_model

    if not providers:
        raise HTTPException(status_code=503, detail="No active permitted LLM providers are configured.")

    forward_payload = dict(payload)
    forward_payload.pop("provider", None)
    forward_payload.pop("routing", None)

    if forward_payload.get("stream") is True:
        response = await stream_chat_completion(
            providers=providers,
            forward_payload=forward_payload,
            requested_model=requested_model,
            balance_nodes=automatic,
            decision_id=decision_headers.get('X-Gateway-Decision-Id'),
        )
        if (automatic and settings.router_selection_mode == 'local_llm'
                and 'max_tokens' not in payload and 'max_completion_tokens' not in payload
                and not payload.get('tools') and not payload.get('functions')):
            attempted_names = [requested_model]
            async def next_model_stream(failed_models):
                remaining_models = [row for row in scoped_public_models(api_key) if row['name'] not in attempted_names]
                retry_payload = {**payload, 'routing': {**payload.get('routing', {}), 'preference': 'quality'}}
                choices, retry_decision = await rank_ready_candidates(
                    retry_payload, remaining_models, scoped_public_providers(api_key),
                    provider_id=requested_provider['id'] if requested_provider else None,
                )
                if not choices:
                    return None
                next_name = choices[0].model_name
                attempted_names.append(next_name)
                next_providers = list({row.provider['id']: row.provider for row in choices
                                       if row.model_name == next_name}.values())
                with get_db() as db:
                    original = db.execute('SELECT decision_json FROM routing_decisions WHERE id=?',
                        (decision_headers.get('X-Gateway-Decision-Id'),)).fetchone()
                    if original:
                        audit = json.loads(original['decision_json'])
                        audit.setdefault('recovery_attempts', []).append({
                            'failed_models': attempted_names[:-1], 'selected_model': next_name,
                            'selection': retry_decision.get('selection'),
                            'reason': 'generation_limit_without_final_answer'})
                        db.execute('UPDATE routing_decisions SET decision_json=? WHERE id=?',
                            (json.dumps(audit, allow_nan=False), decision_headers.get('X-Gateway-Decision-Id')))
                return await stream_chat_completion(providers=next_providers,
                    forward_payload={**forward_payload, 'model': next_name}, requested_model=next_name,
                    balance_nodes=True, decision_id=decision_headers.get('X-Gateway-Decision-Id'))
            response = StreamingResponse(recover_stream(response, next_model_stream),
                media_type='text/event-stream', headers=dict(response.headers),
                background=response.background)
        response.headers.update(decision_headers)
        return response

    last_error = "No provider attempted."
    remaining = list(providers)
    while remaining:
        provider, lease = reserve_provider(remaining if automatic else remaining[:1])
        remaining = [item for item in remaining if item['id'] != provider['id']]
        started = time.perf_counter()
        timeout = provider["timeout_seconds"] or settings.provider_request_timeout_seconds

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                url, body, native = await chat_request(provider, forward_payload, provider_chat_url(provider['endpoint_url']))
                response = await client.post(
                    url,
                    json=body,
                    headers=provider_request_headers(provider),
                )
            duration_ms = int((time.perf_counter() - started) * 1000)

            if response.is_success:
                record_dispatch(decision_headers.get('X-Gateway-Decision-Id'), provider['id'])
                save_request_log(
                    requested_model=requested_model,
                    provider=provider,
                    status="success",
                    status_code=response.status_code,
                    error_message=None,
                    duration_ms=duration_ms,
                )
                return Response(
                    content=json.dumps(ollama_completion(response.json(), stream=False)).encode() if native else response.content,
                    status_code=response.status_code,
                    media_type='application/json' if native else response.headers.get("content-type", "application/json"),
                    headers={**decision_headers, 'X-Gateway-Selected-Provider-Id': str(provider['id'])},
                )

            last_error = f"{provider['name']} returned HTTP {response.status_code}"
            save_request_log(
                requested_model=requested_model,
                provider=provider,
                status="failed",
                status_code=response.status_code,
                error_message=response.text[:500],
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            failure = f"{type(exc).__name__}: {str(exc) or 'Upstream request failed (timeout or connection error).'}"
            last_error = f"{provider['name']} failed: {failure}"
            save_request_log(
                requested_model=requested_model,
                provider=provider,
                status="failed",
                status_code=None,
                error_message=failure[:500],
                duration_ms=duration_ms,
            )

        finally:
            release_node_lease(lease)
    raise HTTPException(status_code=502, detail=f"All providers failed. Last error: {last_error}")


@app.post("/api/auth/login")
def admin_login(credentials: AdminLoginIn) -> dict[str, Any]:
    if not verify_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")
    return {
        "token": create_admin_token(settings.admin_username),
        "token_type": "bearer",
        "expires_in": settings.admin_session_ttl_seconds,
        "username": settings.admin_username,
    }


@app.get("/api/auth/me")
def admin_me(request: Request) -> dict[str, str]:
    token = bearer_token(request)
    payload = verify_admin_token(token or "")
    if not payload:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    return {"username": str(payload["sub"])}


@app.post("/api/auth/logout")
def admin_logout() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    provider_count = fetch_one("SELECT COUNT(*) AS count FROM providers")["count"]
    active_provider_count = fetch_one("SELECT COUNT(*) AS count FROM providers WHERE is_active = 1")["count"]
    model_count = fetch_one("SELECT COUNT(*) AS count FROM models")["count"]
    log_count = fetch_one("SELECT COUNT(*) AS count FROM request_logs")["count"]
    recent_logs = fetch_all("SELECT * FROM request_logs ORDER BY id DESC LIMIT 8")
    attempt_metrics = fetch_one(
        """
        SELECT
            COUNT(CASE WHEN status IN ('success', 'failed') THEN 1 END) AS completed_count,
            COUNT(CASE WHEN status = 'success' THEN 1 END) AS success_count,
            AVG(CASE WHEN status = 'success' THEN duration_ms END) AS average_success_duration_ms
        FROM request_logs
        """
    )
    return {
        "provider_count": provider_count,
        "active_provider_count": active_provider_count,
        "model_count": model_count,
        "log_count": log_count,
        "recent_logs": recent_logs,
        "attempt_metrics": attempt_metrics,
    }


@app.get("/api/providers")
def get_providers() -> list[dict[str, Any]]:
    return [normalize_bool(row) for row in fetch_all("SELECT * FROM providers ORDER BY priority ASC, id ASC")]


@app.post("/api/providers")
async def create_provider(provider: ProviderIn) -> dict[str, Any]:
    now = utc_now()
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO providers (name, endpoint_url, api_key, is_active, priority, timeout_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider.name,
                provider.endpoint_url,
                provider.api_key,
                int(provider.is_active),
                provider.priority,
                provider.timeout_seconds,
                now,
                now,
            ),
        )
        provider_id = cursor.lastrowid
    created_provider = normalize_bool(fetch_one("SELECT * FROM providers WHERE id = ?", (provider_id,)))
    try:
        model_names = await fetch_model_names_for_provider(created_provider)
        created_provider["model_fetch"] = save_provider_models(provider_id, model_names)
    except Exception as exc:
        created_provider["model_fetch"] = {"found": 0, "created": 0, "skipped": 0, "error": str(exc)}
    automatic_preparation.notify()
    return created_provider


@app.put("/api/providers/{provider_id}")
def update_provider(provider_id: int, provider: ProviderIn) -> dict[str, Any]:
    with get_db() as db:
        db.execute(
            """
            UPDATE providers
            SET name = ?, endpoint_url = ?, api_key = ?, is_active = ?, priority = ?, timeout_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                provider.name,
                provider.endpoint_url,
                provider.api_key,
                int(provider.is_active),
                provider.priority,
                provider.timeout_seconds,
                utc_now(),
                provider_id,
            ),
        )
    updated = fetch_one("SELECT * FROM providers WHERE id = ?", (provider_id,))
    if not updated:
        raise HTTPException(status_code=404, detail="Provider not found.")
    automatic_preparation.notify()
    return normalize_bool(updated)


@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: int) -> dict[str, bool]:
    with get_db() as db:
        db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
    return {"ok": True}


@app.post("/api/providers/{provider_id}/fetch-models")
async def fetch_provider_models(provider_id: int) -> dict[str, Any]:
    provider = fetch_one("SELECT * FROM providers WHERE id = ?", (provider_id,))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    try:
        model_names = await fetch_model_names_for_provider(provider)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch provider models: {exc}") from exc

    result = save_provider_models(provider_id, model_names)
    automatic_preparation.notify()
    return {"provider_id": provider_id, **result}


@app.get("/api/models")
def get_models() -> list[dict[str, Any]]:
    return [normalize_bool(row) for row in fetch_all("SELECT * FROM models ORDER BY name ASC, id ASC")]


@app.get("/api/models/{model_id}/routing-profile")
def get_model_routing_profile(model_id: int) -> dict[str, Any]:
    if not fetch_one("SELECT id FROM models WHERE id = ?", (model_id,)):
        raise HTTPException(status_code=404, detail="Model not found.")
    profile = fetch_one("SELECT * FROM model_routing_profiles WHERE model_id = ?", (model_id,))
    if not profile:
        return {"model_id": model_id, "profile": None}
    return {
        "model_id": model_id,
        "profile": {
            "capabilities": json.loads(profile["capabilities_json"]),
            "context_tokens": profile["context_tokens"],
            "task_quality": json.loads(profile["task_quality_json"]),
            "evidence_source": profile["evidence_source"],
            "model_revision": profile["model_revision"],
        },
        "updated_at": profile["updated_at"],
    }


@app.put("/api/models/{model_id}/routing-profile")
def put_model_routing_profile(model_id: int, profile: ModelRoutingProfileIn) -> dict[str, Any]:
    with get_db() as db:
        if not db.execute("SELECT id FROM models WHERE id = ?", (model_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Model not found.")
        db.execute(
            """
            INSERT INTO model_routing_profiles
                (model_id, capabilities_json, context_tokens, task_quality_json, evidence_source, updated_at, model_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
                capabilities_json = excluded.capabilities_json,
                context_tokens = excluded.context_tokens,
                task_quality_json = excluded.task_quality_json,
                evidence_source = excluded.evidence_source,
                updated_at = excluded.updated_at,
                model_revision = excluded.model_revision
            """,
            (model_id, json.dumps(sorted(set(profile.capabilities))), profile.context_tokens,
             json.dumps(profile.model_dump()["task_quality"]), profile.evidence_source, utc_now(), profile.model_revision),
        )
        db.execute("DELETE FROM routing_runtime_identity WHERE model_id = ?", (model_id,))
    automatic_preparation.notify()
    return get_model_routing_profile(model_id)


@app.post("/api/router/preview")
async def preview_model_routing(payload: dict[str, Any]) -> dict[str, Any]:
    """Admin-only inspection; local_llm mode generates a selector choice, not an answer."""
    provider = resolve_provider_by_name(requested_provider_name(payload))
    model_name = payload.get("model")
    if model_name is not None and (not isinstance(model_name, str) or not model_name.strip()):
        raise HTTPException(status_code=400, detail="model must be a non-empty string.")
    candidates, policy = await rank_ready_candidates(
        payload, scoped_public_models(), scoped_public_providers(),
        provider_id=provider["id"] if provider else None,
        model_name=model_name.strip() if model_name and model_name != "auto" else None,
    )
    return {
        "policy": policy,
        "selected": candidates[0].public() if candidates else None,
        "candidates": [candidate.public() for candidate in candidates],
        "scope": "admin_inventory; actual inference additionally applies the client API key scope",
    }


@app.get("/api/router/readiness")
async def router_readiness() -> dict[str, Any]:
    """Configuration is not a claim that encoder loading or quality is verified."""
    import importlib.util
    from datetime import datetime, timedelta, timezone
    router_settings = get_router_settings()
    if settings.router_selection_mode == 'local_llm':
        installed = await selector_inventory()
        return {
            'mode': 'local_llm', 'configured': installed, 'dependencies_installed': True,
            'selector_model': settings.router_selector_model, 'selector_available': installed,
            'thinking': False, 'timeout_seconds': settings.router_selector_timeout_seconds,
            'local_chat_context_tokens': max(2048, settings.ollama_chat_context_tokens),
            'automatic_preparation': False, 'preparation': None, 'predictors': [],
            'defaults': fetch_one('SELECT fallback_model_id FROM routing_defaults WHERE id=1') or {'fallback_model_id': None},
            'models': fetch_all('''SELECT m.id,m.name,m.provider_id,m.is_active,
                n.is_active AS provider_active FROM models m
                LEFT JOIN providers n ON n.id=m.provider_id ORDER BY m.id'''),
        }
    preparation = fetch_one("SELECT status,message,completed,total,updated_at FROM routing_preparation WHERE id=1")
    if preparation and preparation['status'] in {'running', 'checking'}:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        if preparation['updated_at'] < cutoff:
            preparation = {**preparation, 'status': 'interrupted', 'message': 'Preparation heartbeat expired; rerun the preparation command.'}
    predictors = fetch_all('SELECT model_id,model_revision,snapshot_revision,artifact_json,updated_at FROM routing_predictors')
    current_rows = {}
    try:
        for row in evaluation_rows():
            current_rows.setdefault(row['model_id'], []).append(row)
    except ValueError:
        pass
    fingerprints = {model_id: snapshot(rows) for model_id, rows in current_rows.items()}
    summaries = []
    for predictor in predictors:
        try:
            artifact = artifact_from_json(predictor['artifact_json'])
            summaries.append({key: predictor[key] for key in ('model_id', 'model_revision', 'snapshot_revision', 'updated_at')} | {
                'status': artifact.get('status') if fingerprints.get(predictor['model_id']) == predictor['snapshot_revision'] else 'stale',
                'sample_count': artifact.get('sample_count'),
                'validation': artifact.get('validation'),
            })
        except (ValueError, TypeError, KeyError):
            summaries.append({'model_id': predictor['model_id'], 'status': 'invalid'})
    return {**router_configuration(), "encoder_loaded": "not_checked",
            "trainer_version": TRAINER_VERSION,
            "predictors": summaries,
            "defaults": fetch_one('SELECT fallback_model_id FROM routing_defaults WHERE id=1') or {'fallback_model_id': None},
            "automatic_preparation": settings.router_auto_prepare,
            "dependencies_installed": all(importlib.util.find_spec(package) is not None for package in ('sentence_transformers', 'onnxruntime', 'numpy', 'threadpoolctl')),
            "preparation": preparation,
            "preparation_command": "make router-setup",
            "models": fetch_all("""SELECT m.id, m.name, m.provider_id, m.is_active, n.is_active AS provider_active, p.model_revision,
                COUNT(e.case_id) AS current_evaluations FROM models m
                LEFT JOIN providers n ON n.id=m.provider_id
                LEFT JOIN model_routing_profiles p ON p.model_id = m.id
                LEFT JOIN routing_evaluations e ON e.model_id = m.id
                  AND e.model_revision = p.model_revision AND e.encoder_revision = ? AND e.rubric = ?
                GROUP BY m.id ORDER BY m.id""",
                (router_settings.router_encoder_revision, router_settings.router_evaluation_rubric))}


@app.put('/api/router/defaults')
def put_router_defaults(defaults: RoutingDefaultsIn):
    with get_db() as db:
        if defaults.fallback_model_id is not None and not db.execute('''SELECT m.id FROM models m
            JOIN providers p ON p.id=m.provider_id WHERE m.id=? AND m.is_active=1 AND p.is_active=1''',
            (defaults.fallback_model_id,)).fetchone():
            raise HTTPException(400, 'Fallback must reference an enabled provider-bound model.')
        db.execute('''INSERT INTO routing_defaults(id,fallback_model_id) VALUES(1,?)
            ON CONFLICT(id) DO UPDATE SET fallback_model_id=excluded.fallback_model_id''', (defaults.fallback_model_id,))
    return defaults.model_dump()


@app.get('/api/router/decisions')
def router_decisions():
    return [{'id': row['id'], 'selected_model_id': row['selected_model_id'],
             'created_at': row['created_at'], 'decision': json.loads(row['decision_json'])} for row in
            fetch_all('SELECT id,selected_model_id,decision_json,created_at FROM routing_decisions ORDER BY id DESC LIMIT 100')]


@app.put("/api/models/{model_id}/evaluations/{case_id}")
def put_routing_evaluation(model_id: int, case_id: str, evaluation: RoutingEvaluationIn) -> dict[str, Any]:
    router_settings = get_router_settings()
    if case_id != evaluation.case_id:
        raise HTTPException(400, "case_id in the path and body must match.")
    if evaluation.rubric != router_settings.router_evaluation_rubric:
        raise HTTPException(400, "Evaluation rubric must match the configured router rubric.")
    profile = fetch_one("SELECT model_revision FROM model_routing_profiles WHERE model_id = ?", (model_id,))
    if not profile or profile["model_revision"] != evaluation.model_revision:
        raise HTTPException(409, "Set a matching model revision in the routing profile before importing evaluations.")
    vector = encode(evaluation.request_text)
    if get_router_settings().router_encoder_revision != router_settings.router_encoder_revision:
        raise HTTPException(409, "Encoder configuration changed during evaluation import.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        # Recheck under the write lock to avoid a concurrent profile update.
        profile = db.execute("SELECT model_revision FROM model_routing_profiles WHERE model_id = ?", (model_id,)).fetchone()
        if not profile or profile["model_revision"] != evaluation.model_revision:
            raise HTTPException(409, "Model revision changed during evaluation import.")
        case = db.execute("SELECT request_text FROM routing_evaluations WHERE case_id = ? LIMIT 1", (case_id,)).fetchone()
        if case and case["request_text"] != evaluation.request_text:
            raise HTTPException(409, "Shared case IDs must identify identical request text.")
        exists = db.execute("SELECT 1 FROM routing_evaluations WHERE model_id = ? AND case_id = ?", (model_id, case_id)).fetchone()
        if not exists and db.execute("SELECT COUNT(*) FROM routing_evaluations").fetchone()[0] >= MAX_EVALUATIONS:
            raise HTTPException(409, "Evaluation storage limit reached; archive evaluations first.")
        db.execute("""INSERT INTO routing_evaluations
            (model_id, case_id, model_revision, rubric, encoder_revision, request_text, embedding_json, score, source, updated_at, latency_ms,evaluation_group)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id, case_id) DO UPDATE SET model_revision=excluded.model_revision,
            rubric=excluded.rubric, encoder_revision=excluded.encoder_revision,
            request_text=excluded.request_text, embedding_json=excluded.embedding_json,
            score=excluded.score, source=excluded.source, updated_at=excluded.updated_at, latency_ms=excluded.latency_ms,
            evaluation_group=excluded.evaluation_group""",
            (model_id, case_id, evaluation.model_revision, evaluation.rubric,
             router_settings.router_encoder_revision, evaluation.request_text, json.dumps(vector),
             evaluation.score, evaluation.source, utc_now(), evaluation.latency_ms,evaluation.evaluation_group))
    automatic_preparation.notify()
    return {"model_id": model_id, "case_id": case_id, "stored": True}


@app.delete("/api/models/{model_id}/evaluations/{case_id}")
def delete_routing_evaluation(model_id: int, case_id: str) -> dict[str, Any]:
    with get_db() as db:
        deleted = db.execute("DELETE FROM routing_evaluations WHERE model_id = ? AND case_id = ?", (model_id, case_id)).rowcount
    if not deleted:
        raise HTTPException(404, "Evaluation not found.")
    automatic_preparation.notify()
    return {"deleted": True}


@app.post("/api/models")
def create_model(model: ModelIn) -> dict[str, Any]:
    now = utc_now()
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO models (provider_id, name, display_name, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (model.provider_id, model.name, model.display_name, int(model.is_active), now, now),
        )
        model_id = cursor.lastrowid
    return normalize_bool(fetch_one("SELECT * FROM models WHERE id = ?", (model_id,)))


@app.delete("/api/models/{model_id}")
def delete_model(model_id: int) -> dict[str, bool]:
    with get_db() as db:
        db.execute("DELETE FROM models WHERE id = ?", (model_id,))
    return {"ok": True}


@app.get("/api/api-keys")
def get_api_keys() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT api_keys.id, api_keys.name, api_keys.key_prefix, api_keys.key_value,
               api_keys.is_active, api_keys.last_used_at,
               api_keys.created_at, api_keys.updated_at
        FROM api_keys
        ORDER BY api_keys.id DESC
        """
    )
    result = []
    for row in rows:
        api_key = normalize_bool(row)
        providers = fetch_all(
            """
            SELECT providers.id, providers.name
            FROM api_key_providers
            JOIN providers ON providers.id = api_key_providers.provider_id
            WHERE api_key_providers.api_key_id = ?
            ORDER BY providers.name ASC
            """,
            (api_key["id"],),
        )
        models = fetch_all(
            """
            SELECT models.id, models.name, models.display_name, models.provider_id, providers.name AS provider_name
            FROM api_key_models
            JOIN models ON models.id = api_key_models.model_id
            LEFT JOIN providers ON providers.id = models.provider_id
            WHERE api_key_models.api_key_id = ?
            ORDER BY models.name ASC
            """,
            (api_key["id"],),
        )
        api_key["provider_ids"] = [provider["id"] for provider in providers]
        api_key["provider_names"] = [provider["name"] for provider in providers]
        api_key["model_ids"] = [model["id"] for model in models]
        api_key["model_names"] = [model["display_name"] or model["name"] for model in models]
        api_key["model_provider_names"] = [model["provider_name"] for model in models]
        result.append(api_key)
    return result


@app.post("/api/api-keys")
def create_api_key(api_key: ApiKeyIn) -> dict[str, Any]:
    raw_key = generate_api_key()
    now = utc_now()
    provider_ids = sorted(set(api_key.provider_ids))
    model_ids = sorted(set(api_key.model_ids))
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO api_keys (
                name, key_prefix, key_hash, key_value, is_active,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                api_key.name,
                raw_key[:12],
                hash_api_key(raw_key),
                raw_key,
                int(api_key.is_active),
                now,
                now,
            ),
        )
        api_key_id = cursor.lastrowid
        db.executemany(
            "INSERT OR IGNORE INTO api_key_providers (api_key_id, provider_id) VALUES (?, ?)",
            [(api_key_id, provider_id) for provider_id in provider_ids],
        )
        db.executemany(
            "INSERT OR IGNORE INTO api_key_models (api_key_id, model_id) VALUES (?, ?)",
            [(api_key_id, model_id) for model_id in model_ids],
        )

    created = normalize_bool(fetch_one("SELECT * FROM api_keys WHERE id = ?", (api_key_id,)))
    return {
        "id": created["id"],
        "name": created["name"],
        "key_prefix": created["key_prefix"],
        "provider_ids": provider_ids,
        "model_ids": model_ids,
        "is_active": created["is_active"],
        "created_at": created["created_at"],
        "updated_at": created["updated_at"],
        "api_key": raw_key,
    }


@app.post("/api/api-keys/{api_key_id}/regenerate")
def regenerate_api_key(api_key_id: int) -> dict[str, Any]:
    raw_key = generate_api_key()
    with get_db() as db:
        cursor = db.execute(
            """
            UPDATE api_keys
            SET key_prefix = ?, key_hash = ?, key_value = ?, updated_at = ?
            WHERE id = ?
            """,
            (raw_key[:12], hash_api_key(raw_key), raw_key, utc_now(), api_key_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="API key not found.")

    updated = normalize_bool(fetch_one("SELECT * FROM api_keys WHERE id = ?", (api_key_id,)))
    return {
        "id": updated["id"],
        "name": updated["name"],
        "key_prefix": updated["key_prefix"],
        "key_value": updated["key_value"],
        "is_active": updated["is_active"],
        "last_used_at": updated["last_used_at"],
        "created_at": updated["created_at"],
        "updated_at": updated["updated_at"],
        "api_key": raw_key,
    }


@app.put("/api/api-keys/{api_key_id}")
def update_api_key(api_key_id: int, api_key: ApiKeyIn) -> dict[str, Any]:
    provider_ids = sorted(set(api_key.provider_ids))
    model_ids = sorted(set(api_key.model_ids))
    with get_db() as db:
        db.execute(
            """
            UPDATE api_keys
            SET name = ?, is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                api_key.name,
                int(api_key.is_active),
                utc_now(),
                api_key_id,
            ),
        )
        db.execute("DELETE FROM api_key_providers WHERE api_key_id = ?", (api_key_id,))
        db.execute("DELETE FROM api_key_models WHERE api_key_id = ?", (api_key_id,))
        db.executemany(
            "INSERT OR IGNORE INTO api_key_providers (api_key_id, provider_id) VALUES (?, ?)",
            [(api_key_id, provider_id) for provider_id in provider_ids],
        )
        db.executemany(
            "INSERT OR IGNORE INTO api_key_models (api_key_id, model_id) VALUES (?, ?)",
            [(api_key_id, model_id) for model_id in model_ids],
        )
    updated = fetch_one("SELECT * FROM api_keys WHERE id = ?", (api_key_id,))
    if not updated:
        raise HTTPException(status_code=404, detail="API key not found.")
    return normalize_bool(updated)


@app.delete("/api/api-keys/{api_key_id}")
def delete_api_key(api_key_id: int) -> dict[str, bool]:
    with get_db() as db:
        db.execute("DELETE FROM api_keys WHERE id = ?", (api_key_id,))
    return {"ok": True}


@app.get("/api/routing-rules")
def get_routing_rules() -> list[dict[str, Any]]:
    return [normalize_bool(row) for row in fetch_all("SELECT * FROM routing_rules ORDER BY priority ASC, id ASC")]


@app.post("/api/routing-rules")
def create_routing_rule(rule: RoutingRuleIn) -> dict[str, Any]:
    now = utc_now()
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO routing_rules (name, model_pattern, provider_id, priority, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rule.name, rule.model_pattern, rule.provider_id, rule.priority, int(rule.is_active), now, now),
        )
        rule_id = cursor.lastrowid
    return normalize_bool(fetch_one("SELECT * FROM routing_rules WHERE id = ?", (rule_id,)))


@app.delete("/api/routing-rules/{rule_id}")
def delete_routing_rule(rule_id: int) -> dict[str, bool]:
    with get_db() as db:
        db.execute("DELETE FROM routing_rules WHERE id = ?", (rule_id,))
    return {"ok": True}


@app.get("/api/logs")
def get_logs() -> list[dict[str, Any]]:
    return fetch_all("SELECT * FROM request_logs ORDER BY id DESC LIMIT 200")


def serve_frontend_index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found. Run npm run build and copy dist to backend/app/static.")
    response = FileResponse(index_path)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def serve_public_file(filename: str, *, cache_control: str) -> FileResponse:
    file_path = STATIC_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Public document not found.")

    response = FileResponse(file_path)
    response.headers["Cache-Control"] = cache_control
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/gsai-logo.png", include_in_schema=False)
def public_oauth_logo() -> FileResponse:
    return serve_public_file("gsai-logo.png", cache_control="public, max-age=86400")


@app.get("/legal.css", include_in_schema=False)
def public_legal_styles() -> FileResponse:
    return serve_public_file("legal.css", cache_control="public, max-age=3600")


@app.get("/privacy", include_in_schema=False)
def public_privacy_policy() -> FileResponse:
    response = serve_public_file("privacy.html", cache_control="public, max-age=300")
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/terms", include_in_schema=False)
def public_terms_of_service() -> FileResponse:
    response = serve_public_file("terms.html", cache_control="public, max-age=300")
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/", include_in_schema=False)
def frontend_root() -> FileResponse:
    return serve_frontend_index()


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith(("api/", "v1/", "docs", "openapi.json", "health")):
        raise HTTPException(status_code=404, detail="Not found.")
    return serve_frontend_index()
