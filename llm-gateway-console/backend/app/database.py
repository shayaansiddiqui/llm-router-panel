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
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(settings.database_path)
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
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "key_value" not in columns:
            db.execute("ALTER TABLE api_keys ADD COLUMN key_value TEXT")


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return [dict_from_row(row) for row in rows]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(query, params).fetchone()
        return dict_from_row(row) if row else None
