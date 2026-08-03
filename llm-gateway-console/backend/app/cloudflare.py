from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings, get_settings


RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HEX_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")


class CloudflareError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class CreatedTunnel:
    id: str
    name: str
    token: str


class CloudflareClient:
    """Small Cloudflare API boundary used by node provisioning.

    The API token never leaves this backend. The class intentionally exposes
    only operations required by gsai so callers cannot perform arbitrary API
    requests with account-wide credentials.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def require_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("CLOUDFLARE_API_TOKEN", self.settings.cloudflare_api_token),
                ("CLOUDFLARE_ACCOUNT_ID", self.settings.cloudflare_account_id),
                ("CLOUDFLARE_ZONE_ID", self.settings.cloudflare_zone_id),
            )
            if not value
        ]
        if missing:
            raise CloudflareError(f"Cloudflare provisioning is not configured: missing {', '.join(missing)}")
        base_url = urlparse(self.settings.cloudflare_api_base_url)
        if (
            base_url.scheme != "https"
            or base_url.hostname != "api.cloudflare.com"
            or base_url.path.rstrip("/") != "/client/v4"
            or base_url.username
            or base_url.password
            or base_url.query
            or base_url.fragment
        ):
            raise CloudflareError("Cloudflare API base URL must use the official HTTPS origin")
        if not HEX_ID_PATTERN.fullmatch(self.settings.cloudflare_account_id):
            raise CloudflareError("Cloudflare account ID is invalid")
        if not HEX_ID_PATTERN.fullmatch(self.settings.cloudflare_zone_id):
            raise CloudflareError("Cloudflare zone ID is invalid")

    async def list_tunnels(self) -> list[dict[str, Any]]:
        self.require_configuration()
        return await self._list(
            f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel",
            params={"is_deleted": "false", "per_page": 100},
        )

    async def get_tunnel(self, tunnel_id: str) -> dict[str, Any]:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        result = await self._request(
            "GET", f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}"
        )
        return require_mapping(result, "Cloudflare returned an invalid tunnel")

    async def get_tunnel_connections(self, tunnel_id: str) -> list[dict[str, Any]]:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        result = await self._request(
            "GET", f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/connections"
        )
        if result is None:
            return []
        if not isinstance(result, list):
            raise CloudflareError("Cloudflare returned an invalid tunnel connection list")
        return [item for item in result if isinstance(item, dict)]

    async def cleanup_tunnel_connections(self, tunnel_id: str) -> None:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        try:
            await self._request(
                "DELETE",
                f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/connections",
            )
        except CloudflareError as exc:
            if exc.status_code != 404:
                raise

    async def get_tunnel_configuration(self, tunnel_id: str) -> dict[str, Any]:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        try:
            result = await self._request(
                "GET", f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/configurations"
            )
        except CloudflareError as exc:
            if exc.status_code == 404:
                return {"ingress": [{"service": "http_status:404"}]}
            raise
        envelope = require_mapping(result, "Cloudflare returned an invalid tunnel configuration")
        config = envelope.get("config", envelope)
        return require_mapping(config, "Cloudflare returned an invalid tunnel configuration")

    async def create_tunnel(self, name: str) -> CreatedTunnel:
        result = await self._request(
            "POST",
            f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel",
            json_body={"name": name, "config_src": "cloudflare"},
        )
        tunnel = require_mapping(result, "Cloudflare returned an invalid tunnel creation response")
        tunnel_id = str(tunnel.get("id", ""))
        if not tunnel_id:
            raise CloudflareError("Cloudflare did not return a tunnel ID")
        token = str(tunnel.get("token", ""))
        if not token:
            token = await self.get_tunnel_token(tunnel_id)
        return CreatedTunnel(id=tunnel_id, name=str(tunnel.get("name") or name), token=token)

    async def get_tunnel_token(self, tunnel_id: str) -> str:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        result = await self._request(
            "GET", f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/token"
        )
        if not isinstance(result, str) or not result:
            raise CloudflareError("Cloudflare did not return a tunnel token")
        return result

    async def put_tunnel_configuration(self, tunnel_id: str, config: dict[str, Any]) -> None:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        ingress = config.get("ingress")
        if (
            not isinstance(ingress, list)
            or not ingress
            or not isinstance(ingress[-1], dict)
            or ingress[-1].get("service") != "http_status:404"
        ):
            raise CloudflareError("Tunnel configuration must end with a 404 catch-all rule")
        await self._request(
            "PUT",
            f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/configurations",
            json_body={"config": config},
        )

    async def delete_tunnel(self, tunnel_id: str) -> None:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        await self.cleanup_tunnel_connections(tunnel_id)
        try:
            await self._request(
                "DELETE", f"/accounts/{self.settings.cloudflare_account_id}/cfd_tunnel/{tunnel_id}"
            )
        except CloudflareError as exc:
            if exc.status_code != 404:
                raise

    async def list_dns_records(self) -> list[dict[str, Any]]:
        self.require_configuration()
        return await self._list(
            f"/zones/{self.settings.cloudflare_zone_id}/dns_records",
            params={"type": "CNAME", "per_page": 100},
        )

    async def find_dns_record(self, hostname: str) -> dict[str, Any] | None:
        records = await self._list(
            f"/zones/{self.settings.cloudflare_zone_id}/dns_records",
            params={"name": hostname, "per_page": 100},
        )
        return records[0] if records else None

    async def create_tunnel_dns_record(self, hostname: str, tunnel_id: str) -> dict[str, Any]:
        tunnel_id = require_resource_id(tunnel_id, "tunnel")
        result = await self._request(
            "POST",
            f"/zones/{self.settings.cloudflare_zone_id}/dns_records",
            json_body={
                "type": "CNAME",
                "name": hostname,
                "content": f"{tunnel_id}.cfargotunnel.com",
                "proxied": True,
                "ttl": 1,
                "comment": "Managed by gsai node provisioning",
            },
        )
        return require_mapping(result, "Cloudflare returned an invalid DNS record")

    async def delete_dns_record(self, record_id: str) -> None:
        record_id = require_resource_id(record_id, "DNS record")
        try:
            await self._request("DELETE", f"/zones/{self.settings.cloudflare_zone_id}/dns_records/{record_id}")
        except CloudflareError as exc:
            if exc.status_code != 404:
                raise

    async def create_gateway_access_application(self, hostname: str, node_id: str) -> dict[str, Any]:
        token_id = self.settings.cloudflare_access_service_token_id
        if not token_id:
            raise CloudflareError("Gateway-only access requires CLOUDFLARE_ACCESS_SERVICE_TOKEN_ID")
        result = await self._request(
            "POST",
            f"/accounts/{self.settings.cloudflare_account_id}/access/apps",
            json_body={
                "name": f"gsai node {node_id}",
                "domain": hostname,
                "type": "self_hosted",
                "session_duration": "24h",
                "service_auth_401_redirect": True,
                "policies": [
                    {
                        "name": "Gateway service token only",
                        "decision": "non_identity",
                        "precedence": 1,
                        "include": [{"service_token": {"token_id": token_id}}],
                    }
                ],
            },
        )
        return require_mapping(result, "Cloudflare returned an invalid Access application")

    async def delete_access_application(self, application_id: str) -> None:
        application_id = require_resource_id(application_id, "Access application")
        try:
            await self._request(
                "DELETE", f"/accounts/{self.settings.cloudflare_account_id}/access/apps/{application_id}"
            )
        except CloudflareError as exc:
            if exc.status_code != 404:
                raise

    async def _list(self, path: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            page_params = {**params, "page": page}
            result, result_info = await self._request_envelope("GET", path, params=page_params)
            if not isinstance(result, list):
                raise CloudflareError("Cloudflare returned an invalid paginated response")
            items.extend(item for item in result if isinstance(item, dict))
            try:
                total_pages = int((result_info or {}).get("total_pages") or 1)
            except (TypeError, ValueError) as exc:
                raise CloudflareError("Cloudflare returned invalid pagination metadata") from exc
            if total_pages < 1 or total_pages > 100:
                raise CloudflareError("Cloudflare pagination exceeded the safety limit")
            if page >= total_pages:
                return items
            page += 1
            if page > 100:
                raise CloudflareError("Cloudflare pagination exceeded the safety limit")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        result, _ = await self._request_envelope(method, path, params=params, json_body=json_body)
        return result

    async def _request_envelope(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any] | None]:
        self.require_configuration()
        url = self.settings.cloudflare_api_base_url.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {self.settings.cloudflare_api_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
                response = await client.request(method, url, params=params, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise CloudflareError("Cloudflare API request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise CloudflareError("Cloudflare API could not be reached", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudflareError(
                "Cloudflare API returned a non-JSON response",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            ) from exc

        if not isinstance(payload, dict):
            raise CloudflareError(
                "Cloudflare API returned an invalid response envelope",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )

        if response.status_code >= 400 or not payload.get("success", False):
            messages = [
                str(item.get("message"))
                for item in payload.get("errors", [])
                if isinstance(item, dict) and item.get("message")
            ]
            detail = "; ".join(messages) or f"HTTP {response.status_code}"
            raise CloudflareError(
                f"Cloudflare API rejected the request: {detail}",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        result_info = payload.get("result_info")
        return payload.get("result"), result_info if isinstance(result_info, dict) else None


def require_mapping(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CloudflareError(message)
    return value


def require_resource_id(value: str, label: str) -> str:
    if not RESOURCE_ID_PATTERN.fullmatch(value):
        raise CloudflareError(f"Cloudflare {label} ID is invalid")
    return value
