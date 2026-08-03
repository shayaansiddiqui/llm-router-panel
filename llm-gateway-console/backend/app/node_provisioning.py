from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from .cloudflare import CloudflareClient, CloudflareError
from .config import Settings, get_settings
from .database import fetch_all, fetch_one, get_db, utc_now
from .node_naming import (
    HostnameValidationError,
    collision_hostname,
    tunnel_id_from_cname,
    validate_managed_hostname,
)
from .schemas import NodeCommitIn, NodePrepareIn


MAX_TUNNEL_CANDIDATES = 50
GSAI_DNS_COMMENT = "Managed by gsai node provisioning"
COMMIT_CLAIM_TTL = timedelta(minutes=5)


@dataclass
class ProvisioningArtifacts:
    tunnel_id: str = ""
    created_tunnel: bool = False
    previous_tunnel_config: dict[str, Any] | None = None
    dns_record_id: str = ""
    created_dns_record: bool = False
    access_app_id: str = ""
    created_access_app: bool = False


class NodeProvisioningService:
    def __init__(self, settings: Settings | None = None, cloudflare: CloudflareClient | None = None):
        self.settings = settings or get_settings()
        self.cloudflare = cloudflare or CloudflareClient(self.settings)

    async def prepare(self, token_row: dict[str, Any], request: NodePrepareIn) -> dict[str, Any]:
        self.cloudflare.require_configuration()
        preferred_hostname = self._validated_hostname(request.suggested_hostname)
        existing_node = fetch_one("SELECT * FROM nodes WHERE installation_id = ?", (request.installation_id,))

        tunnels, dns_records = await asyncio.gather(
            self.cloudflare.list_tunnels(),
            self.cloudflare.list_dns_records(),
        )
        tunnels = tunnels[:MAX_TUNNEL_CANDIDATES]
        assigned_tunnels = {
            str(row["tunnel_id"]): row
            for row in fetch_all(
                "SELECT id, installation_id, tunnel_id, tunnel_managed FROM nodes WHERE tunnel_id IS NOT NULL"
            )
        }
        tunnel_candidates = await asyncio.gather(
            *[
                self._tunnel_candidate(tunnel, request.installation_id, assigned_tunnels)
                for tunnel in tunnels
            ]
        )

        dns_by_name = {str(record.get("name", "")).lower().rstrip("."): record for record in dns_records}
        if existing_node and existing_node.get("hostname"):
            suggested_hostname = str(existing_node["hostname"])
        else:
            suggested_hostname = self._available_suggestion(
                preferred_hostname,
                request.installation_id,
                dns_by_name,
            )

        hostname_candidates = self._hostname_candidates(
            dns_records=dns_records,
            installation_id=request.installation_id,
            suggested_hostname=suggested_hostname,
        )
        if existing_node:
            current_hostname = str(existing_node.get("hostname") or "")
            hostname_candidates = [
                candidate for candidate in hostname_candidates if candidate["hostname"] == current_hostname
            ]
            tunnel_candidates = [candidate for candidate in tunnel_candidates if candidate["current_node"]]

        session_id = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.settings.node_enrollment_ttl_seconds)
        with get_db() as db:
            db.execute(
                "DELETE FROM node_enrollment_sessions WHERE expires_at < ? OR committed_at IS NOT NULL",
                (now.isoformat(),),
            )
            db.execute(
                """
                INSERT INTO node_enrollment_sessions (
                    id, enrollment_token_id, installation_id, request_json,
                    suggested_hostname, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    token_row["id"],
                    request.installation_id,
                    request.model_dump_json(),
                    suggested_hostname,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )

        return {
            "session_id": session_id,
            "zone": self.settings.node_managed_zone,
            "suggested_hostname": suggested_hostname,
            "allow_new_tunnel": existing_node is None,
            "current_access_mode": str(existing_node.get("access_mode") or "") if existing_node else "",
            "current_public_expires_at": existing_node.get("public_expires_at") if existing_node else None,
            "tunnels": tunnel_candidates,
            "hostnames": hostname_candidates,
            "expires_at": expires_at.isoformat(),
        }

    async def commit(self, token_row: dict[str, Any], request: NodeCommitIn) -> dict[str, Any]:
        session = fetch_one("SELECT * FROM node_enrollment_sessions WHERE id = ?", (request.session_id,))
        if not session or session["enrollment_token_id"] != token_row["id"]:
            raise HTTPException(status_code=404, detail="Enrollment session was not found.")
        if session.get("committed_at"):
            raise HTTPException(status_code=409, detail="Enrollment session has already been committed.")
        if is_expired(str(session["expires_at"])):
            raise HTTPException(status_code=410, detail="Enrollment session has expired. Run gsai connect again.")

        prepared_request = NodePrepareIn.model_validate_json(str(session["request_json"]))
        existing_node = fetch_one(
            "SELECT * FROM nodes WHERE installation_id = ?", (prepared_request.installation_id,)
        )
        hostname = self._validated_hostname(request.hostname)
        self._validate_access(request)

        if existing_node:
            if request.tunnel.mode != "existing" or request.tunnel.id != existing_node.get("tunnel_id"):
                raise HTTPException(
                    status_code=409,
                    detail="This node is already connected. Disconnect it before replacing its tunnel.",
                )
            if hostname != existing_node.get("hostname"):
                raise HTTPException(
                    status_code=409,
                    detail="This node is already connected. Disconnect it before replacing its hostname.",
                )
            if request.access.mode != existing_node.get("access_mode"):
                raise HTTPException(
                    status_code=409,
                    detail="Disconnect and reconnect the node before changing its access mode.",
                )

        claim_id = secrets.token_urlsafe(24)
        self._claim_enrollment_token(token_row, claim_id)
        node_id = str(existing_node["id"]) if existing_node else secrets.token_hex(16)
        artifacts = ProvisioningArtifacts()
        api_key = ""
        node_secret = f"gsai_node_{secrets.token_urlsafe(32)}"

        try:
            tunnel_id, tunnel_name, tunnel_token = await self._select_tunnel(
                request=request,
                installation_id=prepared_request.installation_id,
                node_id=node_id,
                hostname=hostname,
                artifacts=artifacts,
            )
            await self._configure_tunnel(tunnel_id, hostname, artifacts)
            dns_record_id = await self._ensure_dns(hostname, tunnel_id, artifacts, existing_node)

            access_app_id = ""
            if request.access.mode == "gateway":
                if existing_node and existing_node.get("access_app_id"):
                    access_app_id = str(existing_node["access_app_id"])
                else:
                    application = await self.cloudflare.create_gateway_access_application(hostname, node_id)
                    access_app_id = str(application.get("id", ""))
                    if not access_app_id:
                        raise CloudflareError("Cloudflare did not return an Access application ID")
                    artifacts.access_app_id = access_app_id
                    artifacts.created_access_app = True
            elif request.access.mode == "api_key":
                api_key = f"gsai_live_{secrets.token_urlsafe(32)}"

            public_expires_at = (
                (str(existing_node.get("public_expires_at") or "") or None)
                if existing_node
                else self._public_expiry(request)
            )
            provider_id = self._save_node(
                node_id=node_id,
                prepared_request=prepared_request,
                hostname=hostname,
                tunnel_id=tunnel_id,
                tunnel_name=tunnel_name,
                tunnel_managed=(
                    artifacts.created_tunnel
                    or bool(existing_node and existing_node.get("tunnel_managed"))
                    or existing_node is None
                ),
                dns_record_id=dns_record_id,
                access_mode=request.access.mode,
                access_app_id=access_app_id,
                public_expires_at=public_expires_at,
                api_key=api_key,
                node_secret=node_secret,
                token_row=token_row,
                session=session,
                claim_id=claim_id,
                existing_node=existing_node,
            )
        except Exception:
            await self._rollback(artifacts)
            try:
                self._release_enrollment_claim(token_row, claim_id)
            except Exception:
                # Do not hide the provisioning failure. A leaked claim expires
                # automatically and can never turn into a consumed token.
                pass
            raise

        return {
            "node_id": node_id,
            "provider_id": provider_id,
            "hostname": hostname,
            "endpoint": f"https://{hostname}/v1",
            "tunnel_id": tunnel_id,
            "tunnel_name": tunnel_name,
            "tunnel_token": tunnel_token,
            "node_secret": node_secret,
            "api_key": api_key or None,
            "access_mode": request.access.mode,
            "public_expires_at": public_expires_at,
            "status": "offline",
            "reconnected": existing_node is not None,
        }

    def activate(self, node: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with get_db() as db:
            db.execute(
                "UPDATE nodes SET status = 'online', last_seen_at = ?, updated_at = ? WHERE id = ?",
                (now, now, node["id"]),
            )
            if node.get("provider_id"):
                db.execute(
                    "UPDATE providers SET is_active = 1, updated_at = ? WHERE id = ?",
                    (now, node["provider_id"]),
                )
        return {"node_id": node["id"], "status": "online", "last_seen_at": now}

    def heartbeat(self, node: dict[str, Any]) -> dict[str, Any]:
        return self.activate(node)

    def mark_offline(self, node: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with get_db() as db:
            db.execute(
                "UPDATE nodes SET status = 'offline', updated_at = ? WHERE id = ?",
                (now, node["id"]),
            )
            if node.get("provider_id"):
                db.execute(
                    "UPDATE providers SET is_active = 0, updated_at = ? WHERE id = ?",
                    (now, node["provider_id"]),
                )
        return {"node_id": node["id"], "status": "offline"}

    async def delete_node(self, node: dict[str, Any]) -> None:
        node_id = str(node["id"])
        with get_db() as db:
            db.execute(
                "UPDATE nodes SET status = 'disconnecting', updated_at = ? WHERE id = ?",
                (utc_now(), node_id),
            )
            if node.get("provider_id"):
                db.execute("UPDATE providers SET is_active = 0 WHERE id = ?", (node["provider_id"],))

        try:
            if node.get("tunnel_id"):
                tunnel_id = str(node["tunnel_id"])
                try:
                    await self.cloudflare.put_tunnel_configuration(
                        tunnel_id,
                        {"ingress": [{"service": "http_status:404"}]},
                    )
                    await self.cloudflare.cleanup_tunnel_connections(tunnel_id)
                except CloudflareError as exc:
                    if exc.status_code != 404:
                        raise
            if node.get("access_app_id"):
                await self.cloudflare.delete_access_application(str(node["access_app_id"]))
            if node.get("dns_record_id"):
                await self.cloudflare.delete_dns_record(str(node["dns_record_id"]))
            if node.get("tunnel_id"):
                if node.get("tunnel_managed"):
                    await self.cloudflare.delete_tunnel(str(node["tunnel_id"]))
        except Exception:
            with get_db() as db:
                db.execute(
                    "UPDATE nodes SET status = 'disconnect_failed', updated_at = ? WHERE id = ?",
                    (utc_now(), node_id),
                )
            raise

        with get_db() as db:
            provider_id = node.get("provider_id")
            db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            if provider_id:
                db.execute("DELETE FROM models WHERE provider_id = ?", (provider_id,))
                db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))

    async def _tunnel_candidate(
        self,
        tunnel: dict[str, Any],
        installation_id: str,
        assigned_tunnels: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        tunnel_id = str(tunnel.get("id", ""))
        assigned = assigned_tunnels.get(tunnel_id)
        current_node = bool(assigned and assigned["installation_id"] == installation_id)
        eligible = current_node
        reason = ""

        if not tunnel_id:
            eligible = False
            reason = "Cloudflare did not return a tunnel ID."
        elif assigned and not current_node:
            eligible = False
            reason = "Assigned to another gsai node."
        elif not current_node:
            if str(tunnel.get("config_src", "")) != "cloudflare":
                reason = "Locally managed tunnels cannot be adopted safely."
            else:
                connections, configuration = await asyncio.gather(
                    self.cloudflare.get_tunnel_connections(tunnel_id),
                    self.cloudflare.get_tunnel_configuration(tunnel_id),
                )
                if connections:
                    reason = "Tunnel has active connectors."
                elif not tunnel_configuration_is_empty(configuration):
                    reason = "Tunnel already contains published application routes."
                else:
                    eligible = True

        return {
            "id": tunnel_id,
            "name": str(tunnel.get("name") or tunnel_id),
            "status": str(tunnel.get("status") or "Unknown"),
            "hostname": "",
            "eligible": eligible,
            "reason": reason,
            "current_node": current_node,
            "ownership_transfer": bool(eligible and not current_node),
        }

    def _hostname_candidates(
        self,
        *,
        dns_records: list[dict[str, Any]],
        installation_id: str,
        suggested_hostname: str,
    ) -> list[dict[str, Any]]:
        assigned_hostnames = {
            str(row["hostname"]): row
            for row in fetch_all("SELECT installation_id, hostname FROM nodes WHERE hostname IS NOT NULL")
        }
        candidates: list[dict[str, Any]] = []
        for record in dns_records:
            hostname = str(record.get("name", "")).lower().rstrip(".")
            if not hostname or hostname == suggested_hostname:
                continue
            try:
                hostname = self._validated_hostname(hostname)
            except HTTPException:
                continue
            tunnel_id = tunnel_id_from_cname(str(record.get("content", "")))
            if not tunnel_id:
                continue
            assigned = assigned_hostnames.get(hostname)
            current_node = bool(assigned and assigned["installation_id"] == installation_id)
            managed_record = str(record.get("comment") or "") == GSAI_DNS_COMMENT
            eligible = current_node or (not assigned and managed_record)
            reason = ""
            if assigned and not current_node:
                reason = "Assigned to another gsai node."
            elif not managed_record and not current_node:
                reason = "Existing DNS record is not managed by gsai and will not be overwritten."
            candidates.append(
                {
                    "hostname": hostname,
                    "tunnel_id": tunnel_id,
                    "eligible": eligible,
                    "reason": reason,
                    "current_node": current_node,
                }
            )
        return sorted(candidates, key=lambda item: (not item["current_node"], not item["eligible"], item["hostname"]))

    def _available_suggestion(
        self,
        preferred_hostname: str,
        installation_id: str,
        dns_by_name: dict[str, dict[str, Any]],
    ) -> str:
        if preferred_hostname not in dns_by_name:
            return preferred_hostname
        suffix = installation_id.replace("-", "")[:6] or secrets.token_hex(3)
        candidate = collision_hostname(preferred_hostname, self.settings.node_managed_zone, suffix)
        if candidate not in dns_by_name:
            return candidate
        for attempt in range(2, 100):
            candidate = collision_hostname(
                preferred_hostname,
                self.settings.node_managed_zone,
                f"{suffix}{attempt}",
            )
            if candidate not in dns_by_name:
                return candidate
        raise HTTPException(status_code=409, detail="A unique managed hostname could not be allocated.")

    async def _select_tunnel(
        self,
        *,
        request: NodeCommitIn,
        installation_id: str,
        node_id: str,
        hostname: str,
        artifacts: ProvisioningArtifacts,
    ) -> tuple[str, str, str]:
        if request.tunnel.mode == "create":
            label = hostname.split(".", 1)[0]
            tunnel_name = f"gsai-{label[:70]}-{node_id[:8]}"
            created = await self.cloudflare.create_tunnel(tunnel_name)
            artifacts.tunnel_id = created.id
            artifacts.created_tunnel = True
            return created.id, created.name, created.token

        tunnel_id = request.tunnel.id or ""
        if not tunnel_id:
            raise HTTPException(status_code=422, detail="Existing tunnel selection requires a tunnel ID.")
        assigned = fetch_one("SELECT installation_id FROM nodes WHERE tunnel_id = ?", (tunnel_id,))
        if assigned and assigned["installation_id"] != installation_id:
            raise HTTPException(status_code=409, detail="Selected tunnel belongs to another gsai node.")
        tunnel = await self.cloudflare.get_tunnel(tunnel_id)
        if not assigned:
            connections, configuration = await asyncio.gather(
                self.cloudflare.get_tunnel_connections(tunnel_id),
                self.cloudflare.get_tunnel_configuration(tunnel_id),
            )
            if connections or not tunnel_configuration_is_empty(configuration):
                raise HTTPException(status_code=409, detail="Selected tunnel is no longer available.")
        token = await self.cloudflare.get_tunnel_token(tunnel_id)
        artifacts.tunnel_id = tunnel_id
        return tunnel_id, str(tunnel.get("name") or tunnel_id), token

    async def _configure_tunnel(
        self, tunnel_id: str, hostname: str, artifacts: ProvisioningArtifacts
    ) -> None:
        if not artifacts.created_tunnel:
            artifacts.previous_tunnel_config = await self.cloudflare.get_tunnel_configuration(tunnel_id)
        config = {
            "ingress": [
                {
                    "hostname": hostname,
                    "service": self.settings.node_agent_origin,
                    "originRequest": {},
                },
                {"service": "http_status:404"},
            ]
        }
        await self.cloudflare.put_tunnel_configuration(tunnel_id, config)

    async def _ensure_dns(
        self,
        hostname: str,
        tunnel_id: str,
        artifacts: ProvisioningArtifacts,
        existing_node: dict[str, Any] | None,
    ) -> str:
        record = await self.cloudflare.find_dns_record(hostname)
        if record:
            record_tunnel_id = tunnel_id_from_cname(str(record.get("content", "")))
            current_record_id = str(existing_node.get("dns_record_id") or "") if existing_node else ""
            if record_tunnel_id != tunnel_id or (str(record.get("id", "")) != current_record_id and str(record.get("comment") or "") != GSAI_DNS_COMMENT):
                raise HTTPException(status_code=409, detail="Selected hostname is already used by another DNS record.")
            artifacts.dns_record_id = str(record.get("id", ""))
            return artifacts.dns_record_id

        record = await self.cloudflare.create_tunnel_dns_record(hostname, tunnel_id)
        record_id = str(record.get("id", ""))
        if not record_id:
            raise CloudflareError("Cloudflare did not return a DNS record ID")
        artifacts.dns_record_id = record_id
        artifacts.created_dns_record = True
        return record_id

    def _save_node(
        self,
        *,
        node_id: str,
        prepared_request: NodePrepareIn,
        hostname: str,
        tunnel_id: str,
        tunnel_name: str,
        tunnel_managed: bool,
        dns_record_id: str,
        access_mode: str,
        access_app_id: str,
        public_expires_at: str | None,
        api_key: str,
        node_secret: str,
        token_row: dict[str, Any],
        session: dict[str, Any],
        claim_id: str,
        existing_node: dict[str, Any] | None,
    ) -> int:
        now = utc_now()
        cf_client_id = self.settings.cloudflare_access_client_id if access_mode == "gateway" else None
        cf_client_secret = self.settings.cloudflare_access_client_secret if access_mode == "gateway" else None
        if access_mode == "gateway" and (not cf_client_id or not cf_client_secret):
            raise CloudflareError("Gateway-only access requires Cloudflare Access client credentials")

        with get_db() as db:
            if existing_node and existing_node.get("provider_id"):
                provider_id = int(existing_node["provider_id"])
                db.execute(
                    """
                    UPDATE providers
                    SET name = ?, endpoint_url = ?, api_key = ?, is_active = 0,
                        cf_access_client_id = ?, cf_access_client_secret = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        f"node-{node_id[:12]}",
                        f"https://{hostname}",
                        node_secret,
                        cf_client_id,
                        cf_client_secret,
                        now,
                        provider_id,
                    ),
                )
            else:
                cursor = db.execute(
                    """
                    INSERT INTO providers (
                        name, endpoint_url, api_key, is_active, priority,
                        timeout_seconds, cf_access_client_id, cf_access_client_secret,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 0, 100, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"node-{node_id[:12]}",
                        f"https://{hostname}",
                        node_secret,
                        max(self.settings.provider_request_timeout_seconds, 300),
                        cf_client_id,
                        cf_client_secret,
                        now,
                        now,
                    ),
                )
                provider_id = int(cursor.lastrowid)

            db.execute(
                "UPDATE models SET is_active = 0, updated_at = ? WHERE provider_id = ?",
                (now, provider_id),
            )
            model = db.execute(
                "SELECT id FROM models WHERE provider_id = ? AND name = ?",
                (provider_id, prepared_request.model),
            ).fetchone()
            if model is None:
                db.execute(
                    """
                    INSERT INTO models (provider_id, name, display_name, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (provider_id, prepared_request.model, prepared_request.model, now, now),
                )
            else:
                db.execute(
                    """
                    UPDATE models
                    SET display_name = ?, is_active = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (prepared_request.model, now, model["id"]),
                )

            api_key_hash = hash_secret(api_key) if api_key else None
            db.execute(
                """
                INSERT INTO nodes (
                    id, installation_id, username, computer_name, platform,
                    architecture, runtime, model_name, status, tunnel_id,
                    tunnel_name, tunnel_managed, hostname, dns_record_id,
                    access_mode, access_app_id, public_expires_at, api_key_hash,
                    node_secret_hash, provider_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'offline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(installation_id) DO UPDATE SET
                    username = excluded.username,
                    computer_name = excluded.computer_name,
                    platform = excluded.platform,
                    architecture = excluded.architecture,
                    runtime = excluded.runtime,
                    model_name = excluded.model_name,
                    status = 'offline',
                    tunnel_id = excluded.tunnel_id,
                    tunnel_name = excluded.tunnel_name,
                    tunnel_managed = excluded.tunnel_managed,
                    hostname = excluded.hostname,
                    dns_record_id = excluded.dns_record_id,
                    access_mode = excluded.access_mode,
                    access_app_id = excluded.access_app_id,
                    public_expires_at = excluded.public_expires_at,
                    api_key_hash = excluded.api_key_hash,
                    node_secret_hash = excluded.node_secret_hash,
                    provider_id = excluded.provider_id,
                    updated_at = excluded.updated_at
                """,
                (
                    node_id,
                    prepared_request.installation_id,
                    prepared_request.username,
                    prepared_request.computer_name,
                    prepared_request.platform,
                    prepared_request.architecture,
                    prepared_request.runtime,
                    prepared_request.model,
                    tunnel_id,
                    tunnel_name,
                    int(tunnel_managed),
                    hostname,
                    dns_record_id,
                    access_mode,
                    access_app_id or None,
                    public_expires_at,
                    api_key_hash,
                    hash_secret(node_secret),
                    provider_id,
                    now,
                    now,
                ),
            )
            updated = db.execute(
                """
                UPDATE node_enrollment_tokens
                SET used_at = ?, claim_id = NULL, claim_expires_at = NULL
                WHERE id = ? AND used_at IS NULL AND claim_id = ?
                """,
                (now, token_row["id"], claim_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Enrollment token was consumed concurrently")
            db.execute(
                "UPDATE node_enrollment_sessions SET committed_at = ? WHERE id = ? AND committed_at IS NULL",
                (now, session["id"]),
            )
        return provider_id

    def _claim_enrollment_token(self, token_row: dict[str, Any], claim_id: str) -> None:
        now = datetime.now(timezone.utc)
        claim_expires_at = now + COMMIT_CLAIM_TTL
        with get_db() as db:
            claimed = db.execute(
                """
                UPDATE node_enrollment_tokens
                SET claim_id = ?, claim_expires_at = ?
                WHERE id = ?
                  AND used_at IS NULL
                  AND (claim_id IS NULL OR claim_expires_at IS NULL OR claim_expires_at < ?)
                """,
                (claim_id, claim_expires_at.isoformat(), token_row["id"], now.isoformat()),
            )
            if claimed.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="This enrollment token is already completing another connection.",
                )

    def _release_enrollment_claim(self, token_row: dict[str, Any], claim_id: str) -> None:
        with get_db() as db:
            db.execute(
                """
                UPDATE node_enrollment_tokens
                SET claim_id = NULL, claim_expires_at = NULL
                WHERE id = ? AND used_at IS NULL AND claim_id = ?
                """,
                (token_row["id"], claim_id),
            )

    async def _rollback(self, artifacts: ProvisioningArtifacts) -> None:
        operations = []
        if artifacts.created_access_app and artifacts.access_app_id:
            operations.append(self.cloudflare.delete_access_application(artifacts.access_app_id))
        if artifacts.created_dns_record and artifacts.dns_record_id:
            operations.append(self.cloudflare.delete_dns_record(artifacts.dns_record_id))
        if artifacts.created_tunnel and artifacts.tunnel_id:
            operations.append(self.cloudflare.delete_tunnel(artifacts.tunnel_id))
        elif artifacts.tunnel_id and artifacts.previous_tunnel_config is not None:
            operations.append(
                self.cloudflare.put_tunnel_configuration(
                    artifacts.tunnel_id,
                    artifacts.previous_tunnel_config,
                )
            )
        if operations:
            await asyncio.gather(*operations, return_exceptions=True)

    def _validated_hostname(self, value: str) -> str:
        try:
            return validate_managed_hostname(value, self.settings.node_managed_zone)
        except HostnameValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _validate_access(self, request: NodeCommitIn) -> None:
        ttl = request.access.public_ttl_seconds
        if request.access.mode != "public" and ttl != 0:
            raise HTTPException(status_code=422, detail="Public TTL is only valid for public access mode.")
        if ttl > self.settings.node_public_max_ttl_seconds:
            raise HTTPException(status_code=422, detail="Requested public duration exceeds the server limit.")

    def _public_expiry(self, request: NodeCommitIn) -> str | None:
        if request.access.mode != "public" or request.access.public_ttl_seconds == 0:
            return None
        return (
            datetime.now(timezone.utc) + timedelta(seconds=request.access.public_ttl_seconds)
        ).isoformat()


def tunnel_configuration_is_empty(configuration: dict[str, Any]) -> bool:
    ingress = configuration.get("ingress", [])
    if not ingress:
        return True
    return (
        len(ingress) == 1
        and isinstance(ingress[0], dict)
        and ingress[0].get("service") == "http_status:404"
        and not ingress[0].get("hostname")
        and not ingress[0].get("path")
    )


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_expired(value: str) -> bool:
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def deactivate_stale_nodes(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=active_settings.node_heartbeat_timeout_seconds
    )
    stale_nodes = fetch_all(
        """
        SELECT id, provider_id
        FROM nodes
        WHERE status = 'online' AND (last_seen_at IS NULL OR last_seen_at < ?)
        """,
        (cutoff.isoformat(),),
    )
    if not stale_nodes:
        return
    now = utc_now()
    node_ids = [str(node["id"]) for node in stale_nodes]
    provider_ids = [int(node["provider_id"]) for node in stale_nodes if node.get("provider_id")]
    with get_db() as db:
        db.executemany(
            "UPDATE nodes SET status = 'offline', updated_at = ? WHERE id = ?",
            [(now, node_id) for node_id in node_ids],
        )
        if provider_ids:
            db.executemany(
                "UPDATE providers SET is_active = 0, updated_at = ? WHERE id = ?",
                [(now, provider_id) for provider_id in provider_ids],
            )
