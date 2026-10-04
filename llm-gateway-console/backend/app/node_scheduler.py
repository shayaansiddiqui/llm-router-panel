"""Atomic gateway-observed load, shared by workers using the same SQLite DB.

Not GPU telemetry, native queue depth, or a promise of upstream cancellation.
Expired leases recover after worker crashes; no capacity figures are invented.
"""
import time
import uuid

from .database import get_db

LEASE_SECONDS = 1200


def reserve_provider(providers):
    now = time.time()
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM routing_node_leases WHERE expires_at<=?', (now,))
        counts = {row['provider_id']: row['active'] for row in db.execute(
            'SELECT provider_id,COUNT(*) AS active FROM routing_node_leases GROUP BY provider_id')}
        # Preserve administrative failover tiers; balance peers atomically.
        provider = min(providers, key=lambda item: (item['priority'], counts.get(item['id'], 0), item['id']))
        lease = uuid.uuid4().hex
        db.execute('INSERT INTO routing_node_leases(id,provider_id,expires_at) VALUES(?,?,?)',
                   (lease, provider['id'], now + LEASE_SECONDS))
    return provider, lease


def renew(lease):
    with get_db() as db:
        db.execute('UPDATE routing_node_leases SET expires_at=? WHERE id=?', (time.time() + LEASE_SECONDS, lease))


def release(lease):
    with get_db() as db:
        db.execute('DELETE FROM routing_node_leases WHERE id=?', (lease,))
