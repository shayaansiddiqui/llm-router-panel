from __future__ import annotations

import re


DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RESERVED_LABELS = {
    "admin",
    "ai",
    "api",
    "ftp",
    "get",
    "imap",
    "mail",
    "ns1",
    "ns2",
    "smtp",
    "status",
    "www",
}


class HostnameValidationError(ValueError):
    pass


def normalize_zone(value: str) -> str:
    zone = value.strip().lower().rstrip(".")
    if not zone or len(zone) > 253 or "." not in zone:
        raise HostnameValidationError("Managed zone is not a valid public DNS zone.")
    if any(not DNS_LABEL_PATTERN.fullmatch(label) for label in zone.split(".")):
        raise HostnameValidationError("Managed zone contains an invalid DNS label.")
    return zone


def validate_managed_hostname(value: str, zone: str) -> str:
    hostname = value.strip().lower().rstrip(".")
    zone = normalize_zone(zone)
    if len(hostname) > 253 or any(character in hostname for character in "/:@*?# "):
        raise HostnameValidationError("Hostname must be a plain DNS name without a URL, port, path, or wildcard.")
    suffix = f".{zone}"
    if not hostname.endswith(suffix):
        raise HostnameValidationError(f"Hostname must be under {zone}.")
    label = hostname[: -len(suffix)]
    if "." in label or not DNS_LABEL_PATTERN.fullmatch(label):
        raise HostnameValidationError(f"Hostname must contain one valid DNS label before {zone}.")
    if label in RESERVED_LABELS:
        raise HostnameValidationError(f"Hostname label '{label}' is reserved.")
    return hostname


def collision_hostname(preferred_hostname: str, zone: str, suffix: str) -> str:
    preferred_hostname = validate_managed_hostname(preferred_hostname, zone)
    zone = normalize_zone(zone)
    label = preferred_hostname[: -(len(zone) + 1)]
    safe_suffix = re.sub(r"[^a-z0-9]", "", suffix.lower())[:12] or "node"
    maximum_base = 63 - len(safe_suffix) - 1
    base = label[:maximum_base].rstrip("-") or "node"
    return f"{base}-{safe_suffix}.{zone}"


def tunnel_id_from_cname(content: str) -> str | None:
    suffix = ".cfargotunnel.com"
    value = content.strip().lower().rstrip(".")
    if not value.endswith(suffix):
        return None
    tunnel_id = value[: -len(suffix)]
    return tunnel_id or None
