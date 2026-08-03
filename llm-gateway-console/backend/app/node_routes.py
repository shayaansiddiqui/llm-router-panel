from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .cloudflare import CloudflareError
from .database import fetch_all, fetch_one, get_db
from .node_provisioning import NodeProvisioningService, hash_secret, is_expired
from .schemas import EnrollmentTokenIn, NodeCommitIn, NodePrepareIn


router = APIRouter()


@router.post("/api/node-enrollment-tokens")
def create_enrollment_token(payload: EnrollmentTokenIn) -> dict[str, Any]:
    raw_token = f"gsai_enroll_{secrets.token_urlsafe(32)}"
    token_id = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=payload.expires_in_seconds)
    with get_db() as db:
        db.execute(
            """
            INSERT INTO node_enrollment_tokens (
                id, name, token_prefix, token_hash, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token_id,
                payload.name.strip(),
                raw_token[:18],
                hash_secret(raw_token),
                expires_at.isoformat(),
                now.isoformat(),
            ),
        )
    return {
        "id": token_id,
        "name": payload.name.strip(),
        "token": raw_token,
        "token_prefix": raw_token[:18],
        "expires_at": expires_at.isoformat(),
        "created_at": now.isoformat(),
    }


@router.get("/api/node-enrollment-tokens")
def list_enrollment_tokens() -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT id, name, token_prefix, expires_at, used_at, created_at
        FROM node_enrollment_tokens
        ORDER BY created_at DESC
        """
    )


@router.delete("/api/node-enrollment-tokens/{token_id}")
def revoke_enrollment_token(token_id: str) -> dict[str, bool]:
    with get_db() as db:
        cursor = db.execute("DELETE FROM node_enrollment_tokens WHERE id = ?", (token_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Enrollment token was not found.")
    return {"ok": True}


@router.get("/api/nodes")
def list_nodes() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT nodes.*, providers.name AS provider_name, providers.is_active AS provider_active
        FROM nodes
        LEFT JOIN providers ON providers.id = nodes.provider_id
        ORDER BY nodes.created_at DESC
        """
    )
    for row in rows:
        row["tunnel_managed"] = bool(row["tunnel_managed"])
        row["provider_active"] = bool(row["provider_active"]) if row["provider_active"] is not None else False
        row.pop("api_key_hash", None)
        row.pop("node_secret_hash", None)
    return rows


@router.delete("/api/nodes/{node_id}")
async def remove_node_as_admin(node_id: str) -> dict[str, bool]:
    node = fetch_one("SELECT * FROM nodes WHERE id = ?", (node_id,))
    if not node:
        raise HTTPException(status_code=404, detail="Node was not found.")
    try:
        await NodeProvisioningService().delete_node(node)
    except CloudflareError as exc:
        raise provisioning_http_error(exc) from exc
    return {"ok": True}


@router.post("/v1/node-enrollments/prepare")
async def prepare_node_enrollment(request: Request, payload: NodePrepareIn) -> dict[str, Any]:
    token = require_enrollment_token(request)
    service = NodeProvisioningService()
    try:
        return await service.prepare(token, payload)
    except CloudflareError as exc:
        raise provisioning_http_error(exc) from exc


@router.post("/v1/node-enrollments/commit")
async def commit_node_enrollment(request: Request, payload: NodeCommitIn) -> dict[str, Any]:
    token = require_enrollment_token(request)
    service = NodeProvisioningService()
    try:
        return await service.commit(token, payload)
    except CloudflareError as exc:
        raise provisioning_http_error(exc) from exc


@router.post("/v1/nodes/{node_id}/activate")
def activate_node(node_id: str, request: Request) -> dict[str, Any]:
    node = require_node_secret(node_id, request)
    return NodeProvisioningService().activate(node)


@router.post("/v1/nodes/{node_id}/heartbeat")
def heartbeat_node(node_id: str, request: Request) -> dict[str, Any]:
    node = require_node_secret(node_id, request)
    return NodeProvisioningService().heartbeat(node)


@router.post("/v1/nodes/{node_id}/offline")
def mark_node_offline(node_id: str, request: Request) -> dict[str, Any]:
    node = require_node_secret(node_id, request)
    return NodeProvisioningService().mark_offline(node)


@router.delete("/v1/nodes/{node_id}")
async def disconnect_node(node_id: str, request: Request) -> dict[str, bool]:
    node = require_node_secret(node_id, request)
    try:
        await NodeProvisioningService().delete_node(node)
    except CloudflareError as exc:
        raise provisioning_http_error(exc) from exc
    return {"ok": True}


def require_enrollment_token(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Enrollment token is required.")
    raw_token = authorization.split(" ", 1)[1].strip()
    if not raw_token.startswith("gsai_enroll_") or len(raw_token) > 256:
        raise HTTPException(status_code=401, detail="Enrollment token is invalid.")
    token = fetch_one(
        "SELECT * FROM node_enrollment_tokens WHERE token_hash = ?",
        (hash_secret(raw_token),),
    )
    if not token:
        raise HTTPException(status_code=401, detail="Enrollment token is invalid.")
    if token.get("used_at"):
        raise HTTPException(status_code=409, detail="Enrollment token has already been used.")
    if is_expired(str(token["expires_at"])):
        raise HTTPException(status_code=410, detail="Enrollment token has expired.")
    return token


def require_node_secret(node_id: str, request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Node credential is required.")
    raw_secret = authorization.split(" ", 1)[1].strip()
    if not raw_secret.startswith("gsai_node_") or len(raw_secret) > 256:
        raise HTTPException(status_code=401, detail="Node credential is invalid.")
    node = fetch_one("SELECT * FROM nodes WHERE id = ?", (node_id,))
    if not node or not node.get("node_secret_hash"):
        raise HTTPException(status_code=404, detail="Node was not found.")
    if not secrets.compare_digest(str(node["node_secret_hash"]), hash_secret(raw_secret)):
        raise HTTPException(status_code=401, detail="Node credential is invalid.")
    return node


def provisioning_http_error(error: CloudflareError) -> HTTPException:
    if "not configured" in str(error).lower() or "requires cloudflare" in str(error).lower():
        return HTTPException(status_code=503, detail=str(error))
    status_code = 503 if error.retryable else 502
    return HTTPException(status_code=status_code, detail=str(error))
