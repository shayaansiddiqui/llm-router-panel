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

            CREATE TABLE IF NOT EXISTS model_routing_profiles (
                model_id INTEGER PRIMARY KEY,
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                context_tokens INTEGER,
                task_quality_json TEXT NOT NULL DEFAULT '{}',
                evidence_source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(model_id) REFERENCES models(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_request_logs_routing
                ON request_logs(provider_id, requested_model, created_at);
            CREATE TABLE IF NOT EXISTS routing_evaluations (
                model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
                case_id TEXT NOT NULL,
                model_revision TEXT NOT NULL,
                rubric TEXT NOT NULL,
                encoder_revision TEXT NOT NULL,
                request_text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(model_id, case_id)
            );
            CREATE TABLE IF NOT EXISTS routing_configuration (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                settings_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routing_preparation (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                owner TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routing_runtime_identity (
                model_id INTEGER PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
                model_digest TEXT NOT NULL,
                runtime_version TEXT NOT NULL,
                endpoint_url TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routing_predictors (
                model_id INTEGER PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
                model_revision TEXT NOT NULL,
                encoder_revision TEXT NOT NULL,
                rubric TEXT NOT NULL,
                snapshot_revision TEXT NOT NULL,
                artifact_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routing_defaults (
                id INTEGER PRIMARY KEY CHECK(id=1),
                fallback_model_id INTEGER REFERENCES models(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS routing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routing_node_leases (
                id TEXT PRIMARY KEY,
                provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routing_node_leases ON routing_node_leases(provider_id,expires_at);
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "key_value" not in columns:
            db.execute("ALTER TABLE api_keys ADD COLUMN key_value TEXT")
        profile_columns = {row["name"] for row in db.execute("PRAGMA table_info(model_routing_profiles)")}
        if "model_revision" not in profile_columns:
            db.execute("ALTER TABLE model_routing_profiles ADD COLUMN model_revision TEXT")
        evaluation_columns = {row["name"] for row in db.execute("PRAGMA table_info(routing_evaluations)")}
        if "latency_ms" not in evaluation_columns:
            db.execute("ALTER TABLE routing_evaluations ADD COLUMN latency_ms REAL CHECK(latency_ms > 0)")
        if "evaluation_group" not in evaluation_columns:
            db.execute("ALTER TABLE routing_evaluations ADD COLUMN evaluation_group TEXT")


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return [dict_from_row(row) for row in rows]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(query, params).fetchone()
        return dict_from_row(row) if row else None
