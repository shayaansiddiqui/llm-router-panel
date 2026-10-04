"""Lifecycle-managed preparation; no runtime pip, no inference on the event loop."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import logging
import os
from pathlib import Path
import sys
import uuid

from .config import get_settings, get_router_settings
from .database import fetch_all, fetch_one, get_db, utc_now

logger = logging.getLogger(__name__)


class AutomaticPreparation:
    def __init__(self):
        self.task = None
        self.process = None
        self.owner = None
        self.wake = asyncio.Event()
        self.failures = 0
        self.loop = None

    def start(self):
        if (get_settings().router_selection_mode == 'learned'
                and get_settings().router_auto_prepare and self.task is None):
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.create_task(self.run(), name='automatic-router-preparation')

    def notify(self):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._notify)

    def _notify(self):
        self.failures = 0
        self.wake.set()

    def report(self, status, message, owner):
        with get_db() as db:
            db.execute('''UPDATE routing_preparation SET status=?,message=?,updated_at=?
                WHERE id=1 AND owner=?''', (status, message, utc_now(), owner))

    async def check(self):
        if not fetch_one('''SELECT m.id FROM models m JOIN providers p ON p.id=m.provider_id
            WHERE m.is_active=1 AND p.is_active=1 LIMIT 1'''):
            return 60
        current = get_router_settings()
        fit_only = bool(current.router_evaluation_rubric
                        and not current.router_evaluation_rubric.startswith('starter-exact-answer-v1-'))
        owner = uuid.uuid4().hex
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with get_db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM routing_preparation WHERE id=1').fetchone()
            if row and row['status'] in {'running', 'checking'} and row['updated_at'] >= cutoff:
                return 60
            db.execute('''INSERT INTO routing_preparation(id,status,message,completed,total,owner,updated_at)
                VALUES(1,'checking','Checking local models automatically',0,0,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,message=excluded.message,
                owner=excluded.owner,updated_at=excluded.updated_at''', (owner, utc_now()))
        self.owner = owner
        if not all(importlib.util.find_spec(package) for package in ('sentence_transformers', 'onnxruntime', 'numpy', 'threadpoolctl')):
            self.report('dependencies_missing', 'The running environment predates the current server requirements. Normal deployment must install requirements.txt; no separate router setup is required.', owner)
            return 300
        script = Path(__file__).resolve().parents[1] / 'scripts' / (
            'fit_router_predictors.py' if fit_only else 'setup_automatic_routing.py')
        arguments = ['--controller-owner', owner] if fit_only else ['--automatic', '--controller-owner', owner]
        environment = {**os.environ, 'DATABASE_PATH': str(Path(get_settings().database_path).resolve())}
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, str(script), *arguments,
                env=environment, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            # Bound a preparation run, including downloads; preserve prior config
            # rather than leaving an unbounded orphan background calibration.
            result = await asyncio.wait_for(self.process.wait(), timeout=60 * 60)
            if result != 0:
                self.failures += 1
                row = fetch_one('SELECT status FROM routing_preparation WHERE id=1 AND owner=?', (owner,))
                if row and row['status'] in {'checking', 'complete', 'prepared'}:
                    self.report('failed', 'Measurement or predictor fitting failed; compatible existing artifacts are retained.', owner)
                return min(900, 30 * 2 ** min(self.failures, 5))
            self.failures = 0
            row = fetch_one('SELECT status FROM routing_preparation WHERE id=1 AND owner=?', (owner,))
            if row and row['status'] == 'checking':
                snapshot = get_router_settings()
                usable = fetch_all('''SELECT e.model_id FROM routing_evaluations e
                    JOIN model_routing_profiles p ON p.model_id=e.model_id
                    JOIN models m ON m.id=e.model_id JOIN providers n ON n.id=m.provider_id
                    WHERE e.model_revision=p.model_revision AND e.rubric=? AND e.encoder_revision=?
                      AND m.is_active=1 AND n.is_active=1
                    GROUP BY e.model_id HAVING COUNT(*) >= 20''',
                    (snapshot.router_evaluation_rubric, snapshot.router_encoder_revision))
                self.report('prepared' if usable else 'waiting_for_local_ollama',
                    'Measured data and background predictor fitting checked; inspect predictor validation and fallback status.' if usable
                    else 'Waiting for an accessible direct local Ollama node with installed models. No remote node was calibrated.', owner)
            return 60
        finally:
            await self.stop_process()

    async def stop_process(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            if self.owner:
                row = fetch_one('SELECT status FROM routing_preparation WHERE id=1 AND owner=?', (self.owner,))
                if row and row['status'] in {'running', 'checking'}:
                    self.report('interrupted', 'Preparation stopped with the server; it will resume on startup.', self.owner)
        self.process = None

    async def run(self):
        while True:
            self.wake.clear()
            try:
                delay = await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning('Automatic router preparation deferred; previous configuration retained.')
                self.failures += 1
                delay = min(900, 30 * 2 ** min(self.failures, 5))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        await self.stop_process()
        self.loop = None


automatic_preparation = AutomaticPreparation()
