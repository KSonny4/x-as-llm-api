"""Availability SQLite storage; deliberately separate from legacy probe evidence.

All writes are serialized transactions. Tables are namespaced; opening an old
probe database neither imports its observations nor removes its tables. Callers
must put the file on durable storage and keep errors visible.
"""
import sqlite3
import threading
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS av_schema (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS av_credentials (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, reference TEXT NOT NULL,
 owner TEXT, active INTEGER NOT NULL, supported INTEGER NOT NULL,
 has_secret INTEGER NOT NULL, free_tier INTEGER NOT NULL DEFAULT 0,
 revoked INTEGER NOT NULL DEFAULT 0, cooldown REAL NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(provider, reference));
CREATE TABLE IF NOT EXISTS av_models (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
 base_url TEXT NOT NULL, protocol TEXT NOT NULL, eligibility TEXT NOT NULL,
 provenance TEXT NOT NULL, checked_at REAL NOT NULL,
 requires_free_tier INTEGER NOT NULL DEFAULT 0,
 present INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS av_connections (
 id TEXT PRIMARY KEY, credential_id TEXT NOT NULL REFERENCES av_credentials(id),
 model_id TEXT NOT NULL REFERENCES av_models(id), revision INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'unknown', checked_at REAL, retry_at REAL NOT NULL DEFAULT 0,
 excluded INTEGER NOT NULL DEFAULT 0,
 UNIQUE(credential_id, model_id));
CREATE TABLE IF NOT EXISTS av_checks (
 id INTEGER PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES av_connections(id),
 revision INTEGER NOT NULL, key_revision INTEGER NOT NULL, started_at REAL NOT NULL,
 finished_at REAL, state TEXT, applied INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS av_feedback (
 id INTEGER PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES av_connections(id),
 created_at REAL NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS av_selections (
 id INTEGER PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES av_connections(id),
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS av_discovery (
 credential_id TEXT PRIMARY KEY REFERENCES av_credentials(id),
 checked_at REAL NOT NULL, succeeded_at REAL, error TEXT);
CREATE TABLE IF NOT EXISTS av_sweeps (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS av_jobs (
 id INTEGER PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES av_connections(id),
 state TEXT NOT NULL DEFAULT 'queued', due_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 lease_until REAL, check_id INTEGER REFERENCES av_checks(id));
CREATE UNIQUE INDEX IF NOT EXISTS av_job_live ON av_jobs(connection_id)
 WHERE state IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS av_sweep_jobs (
 sweep_id INTEGER NOT NULL REFERENCES av_sweeps(id), job_id INTEGER NOT NULL REFERENCES av_jobs(id),
 PRIMARY KEY(sweep_id, job_id));
CREATE TABLE IF NOT EXISTS av_provider_pacing (
 provider TEXT PRIMARY KEY, next_at REAL NOT NULL);
"""


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None,
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        # executescript commits implicitly; include the initialization lock in SQL.
        try:
            self.db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
            versions = self.db.execute('SELECT version FROM av_schema').fetchall()
            if not versions:
                self.db.execute('INSERT INTO av_schema VALUES (1)')
            elif len(versions) != 1 or versions[0][0] != 1:
                raise ValueError('unsupported availability schema')
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def rows(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params)]

    def close(self):
        with self.lock:
            self.db.close()
