from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import get_settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dict_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    db_dir = os.path.dirname(settings.database_path)
    if db_dir:
        os.makedirs(db_dir, mode=0o700, exist_ok=True)

    conn = sqlite3.connect(settings.database_path)
    if (
        os.name != "nt"
        and settings.database_path != ":memory:"
        and not settings.database_path.startswith("file:")
    ):
        os.chmod(settings.database_path, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                endpoint_url TEXT NOT NULL,
                api_key TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 1,
                timeout_seconds INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER,
                name TEXT NOT NULL,
                display_name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS routing_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                model_pattern TEXT NOT NULL DEFAULT '*',
                provider_id INTEGER,
                priority INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_model TEXT,
                provider_id INTEGER,
                provider_name TEXT,
                status TEXT NOT NULL,
                status_code INTEGER,
                error_message TEXT,
                duration_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_value TEXT,
                provider_id INTEGER,
                model_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_used_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL,
                FOREIGN KEY(model_id) REFERENCES models(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS api_key_providers (
                api_key_id INTEGER NOT NULL,
                provider_id INTEGER NOT NULL,
                PRIMARY KEY (api_key_id, provider_id),
                FOREIGN KEY(api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_key_models (
                api_key_id INTEGER NOT NULL,
                model_id INTEGER NOT NULL,
                PRIMARY KEY (api_key_id, model_id),
                FOREIGN KEY(api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE,
                FOREIGN KEY(model_id) REFERENCES models(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS node_enrollment_tokens (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_prefix TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                claim_id TEXT,
                claim_expires_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS node_enrollment_sessions (
                id TEXT PRIMARY KEY,
                enrollment_token_id TEXT NOT NULL,
                installation_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                suggested_hostname TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                committed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(enrollment_token_id) REFERENCES node_enrollment_tokens(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                installation_id TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                computer_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                architecture TEXT NOT NULL,
                runtime TEXT NOT NULL,
                model_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'provisioning',
                tunnel_id TEXT UNIQUE,
                tunnel_name TEXT,
                tunnel_managed INTEGER NOT NULL DEFAULT 0,
                hostname TEXT UNIQUE,
                dns_record_id TEXT,
                access_mode TEXT NOT NULL,
                access_app_id TEXT,
                public_expires_at TEXT,
                api_key_hash TEXT,
                node_secret_hash TEXT,
                provider_id INTEGER,
                last_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
            CREATE INDEX IF NOT EXISTS idx_enrollment_sessions_expiry ON node_enrollment_sessions(expires_at);
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "key_value" not in columns:
            db.execute("ALTER TABLE api_keys ADD COLUMN key_value TEXT")

        provider_columns = {row["name"] for row in db.execute("PRAGMA table_info(providers)").fetchall()}
        if "cf_access_client_id" not in provider_columns:
            db.execute("ALTER TABLE providers ADD COLUMN cf_access_client_id TEXT")
        if "cf_access_client_secret" not in provider_columns:
            db.execute("ALTER TABLE providers ADD COLUMN cf_access_client_secret TEXT")

        node_columns = {row["name"] for row in db.execute("PRAGMA table_info(nodes)").fetchall()}
        if "node_secret_hash" not in node_columns:
            db.execute("ALTER TABLE nodes ADD COLUMN node_secret_hash TEXT")

        enrollment_token_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(node_enrollment_tokens)").fetchall()
        }
        if "claim_id" not in enrollment_token_columns:
            db.execute("ALTER TABLE node_enrollment_tokens ADD COLUMN claim_id TEXT")
        if "claim_expires_at" not in enrollment_token_columns:
            db.execute("ALTER TABLE node_enrollment_tokens ADD COLUMN claim_expires_at TEXT")


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return [dict_from_row(row) for row in rows]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(query, params).fetchone()
        return dict_from_row(row) if row else None
