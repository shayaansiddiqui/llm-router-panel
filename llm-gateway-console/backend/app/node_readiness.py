"""Bounded, authenticated inventory preflight. Reachable does not mean idle."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import Any

import httpx
from fastapi import HTTPException

from .config import get_settings
from .model_router import rank_candidates, routing_requirements
from .database import fetch_all
from .llm_selector import select_candidates
from .ollama_chat import runtime_metadata, text_chat_supported

_probe_slots = asyncio.Semaphore(8)
_inventory_cache: dict[tuple, tuple[float, set[str]]] = {}


async def rank_ready_candidates(payload: dict[str, Any], models: list[dict[str, Any]],
                                providers: list[dict[str, Any]], **restrictions):
    routing_requirements(payload)  # Reject malformed input before network work.
    timeout = max(0.1, min(get_settings().router_probe_timeout_seconds, 10))
    eligible = [p for p in providers if p["is_active"]
                and (restrictions.get("provider_id") is None or p["id"] == restrictions["provider_id"])]
    if len(eligible) > 256:
        raise HTTPException(503, "Node inventory exceeds preflight capacity; narrow the provider scope.")
    identities = {row['model_id']: row for row in fetch_all('SELECT * FROM routing_runtime_identity')}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        async def inspect(provider):
            expected = [(m, identities[m['id']]) for m in models
                        if m['provider_id'] == provider['id'] and m['id'] in identities]
            if get_settings().router_selection_mode == 'local_llm':
                expected = []  # Historical calibration identities no longer gate this mode.
            identity_key = tuple(sorted((m['name'], identity['model_digest'], identity['runtime_version'], identity['endpoint_url'])
                                        for m, identity in expected))
            cache_key = (provider["id"], provider["endpoint_url"], provider.get("api_key"), identity_key)
            cached = _inventory_cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return provider["id"], cached[1]
            base = provider["endpoint_url"].rstrip("/")
            url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
            headers = {"Authorization": f"Bearer {provider['api_key']}"} if provider.get("api_key") else {}
            try:
                await asyncio.wait_for(_probe_slots.acquire(), timeout=timeout)
            except asyncio.TimeoutError:
                return provider["id"], set()
            try:
                try:
                    async with client.stream("GET", url, headers=headers) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 256 * 1024:
                                return provider["id"], set()
                    inventory = json.loads(body)
                    records = inventory.get("data", inventory.get("models", []))
                    names = {entry.get("id", entry.get("name")) for entry in records if isinstance(entry, dict)}
                    names = {name for name in names if isinstance(name, str)}
                    if expected:
                        native = base[:-3] if base.endswith('/v1') else base
                        async def native_inventory(path):
                            async with client.stream('GET', native + path, headers=headers) as reply:
                                reply.raise_for_status()
                                value = bytearray()
                                async for chunk in reply.aiter_bytes():
                                    value.extend(chunk)
                                    if len(value) > 256 * 1024:
                                        raise ValueError('Native inventory too large')
                            return json.loads(value)
                        tags, runtime = await asyncio.gather(native_inventory('/api/tags'), native_inventory('/api/version'))
                        digests = {row.get('name', row.get('model')): row.get('digest')
                                   for row in tags.get('models', []) if isinstance(row, dict)}
                        for model, identity in expected:
                            if (identity['endpoint_url'] != provider['endpoint_url']
                                or digests.get(model['name']) != identity['model_digest']
                                or runtime.get('version') != identity['runtime_version']):
                                names.discard(model['name'])
                    if len(_inventory_cache) >= 256:
                        _inventory_cache.clear()
                    _inventory_cache[cache_key] = (time.monotonic() + 5, names)
                    return provider["id"], names
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    return provider["id"], set()
            finally:
                _probe_slots.release()
        async def bounded_inspect(provider):
            try:
                # httpx read timeouts are per chunk; also bound total probe time.
                return await asyncio.wait_for(inspect(provider), timeout=timeout * 2)
            except asyncio.TimeoutError:
                return provider["id"], set()
        readiness = dict(await asyncio.gather(*(bounded_inspect(provider) for provider in eligible)))
    live_models = [m for m in models if m["name"] in readiness.get(m["provider_id"], set())]
    runtime_profiles = {}
    stripped = {key: value for key, value in payload.items() if key not in {'routing', 'provider'}}
    if get_settings().router_selection_mode == 'local_llm' and text_chat_supported(stripped):
        if len(live_models) > 128:
            raise HTTPException(503, 'Live model inventory too large; narrow the provider scope.')
        slots = asyncio.Semaphore(4)
        provider_map = {row['id']: row for row in providers}
        async def metadata_for(model):
            async with slots:
                value = await runtime_metadata(provider_map[model['provider_id']]['endpoint_url'], model['name'])
                if value:
                    runtime_profiles[model['id']] = value
        await asyncio.gather(*(metadata_for(model) for model in live_models))
    candidates, policy = await asyncio.to_thread(rank_candidates, payload, live_models, providers,
                                                 runtime_profiles=runtime_profiles, **restrictions)
    if restrictions.get('model_name') is None:
        mode = get_settings().router_selection_mode
        if mode == 'local_llm':
            candidates, policy = await select_candidates(payload, candidates, policy)
        elif mode != 'learned':
            raise HTTPException(503, 'Invalid ROUTER_SELECTION_MODE; use local_llm or learned.')
    candidates = [replace(c, warnings=[w for w in c.warnings if w != "live_health_and_capacity_unknown"]
                          + ["capacity_unknown_inventory_probe_is_not_a_reservation"],
                          evidence={**c.evidence, "inventory_probe": "reachable_model_present"}) for c in candidates]
    return candidates, {**policy, "readiness": "authenticated_inventory_preflight_cached_up_to_5_seconds",
                        "reachable_model_records": len(live_models),
                        "capacity": "native_capacity_unknown; dispatch_balances_gateway_observed_inflight_within_priority_tiers", "unreachable_or_missing_inventory_nodes":
                        sum(not names for names in readiness.values())}
