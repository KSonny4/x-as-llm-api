"""Availability SQLite storage; deliberately separate from legacy probe evidence.

All writes are serialized transactions. Tables are namespaced; opening an old
probe database neither imports its observations nor removes its tables. Callers
must put the file on durable storage and keep errors visible.
"""
import sqlite3
import threading
import time
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
CREATE TABLE IF NOT EXISTS av_transport_limits (
 credential_id TEXT NOT NULL REFERENCES av_credentials(id),
 base_url TEXT NOT NULL, protocol TEXT NOT NULL,
 cooldown REAL NOT NULL DEFAULT 0, auth_invalid INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(credential_id, base_url, protocol));
CREATE TABLE IF NOT EXISTS av_transport_inheritance (
 credential_id TEXT NOT NULL REFERENCES av_credentials(id),
 base_url TEXT NOT NULL, protocol TEXT NOT NULL, source_base_url TEXT NOT NULL,
 cooldown REAL NOT NULL DEFAULT 0, auth_invalid INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(credential_id, base_url, protocol));
CREATE TABLE IF NOT EXISTS av_transport_provider_pacing (
 scope TEXT PRIMARY KEY, next_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS av_transport_key_pacing (
 credential_id TEXT NOT NULL REFERENCES av_credentials(id), scope TEXT NOT NULL,
 next_at REAL NOT NULL, PRIMARY KEY(credential_id, scope));
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
CREATE TABLE IF NOT EXISTS av_key_pacing (
 credential_id TEXT PRIMARY KEY REFERENCES av_credentials(id), next_at REAL NOT NULL);
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
                self.db.execute('INSERT INTO av_schema VALUES (3)')
            elif len(versions) != 1 or versions[0][0] not in (1, 2, 3):
                raise ValueError('unsupported availability schema')
            check_cols = {r[1] for r in self.db.execute('PRAGMA table_info(av_checks)')}
            if 'feedback_id' not in check_cols:
                self.db.execute('ALTER TABLE av_checks ADD COLUMN feedback_id INTEGER NOT NULL DEFAULT 0')
            # 'verify' checks spend the daily verification budget; 'serve'
            # checks are real traffic and must not starve verification.
            if 'kind' not in check_cols:
                self.db.execute("ALTER TABLE av_checks ADD COLUMN kind TEXT NOT NULL DEFAULT 'verify'")
            if 'fail_streak' not in {r[1] for r in self.db.execute('PRAGMA table_info(av_connections)')}:
                self.db.execute('ALTER TABLE av_connections ADD COLUMN fail_streak INTEGER NOT NULL DEFAULT 0')
            self.db.execute('CREATE INDEX IF NOT EXISTS av_checks_conn_started ON av_checks(connection_id, started_at)')
            # Operator-scoped manual checks skip the daily verification budget.
            if 'bypass' not in {r[1] for r in self.db.execute('PRAGMA table_info(av_jobs)')}:
                self.db.execute('ALTER TABLE av_jobs ADD COLUMN bypass INTEGER NOT NULL DEFAULT 0')
            if versions and versions[0][0] == 1:
                self._migrate_transport_limits()
            if versions and versions[0][0] < 3:
                self._migrate_cli_ipc_policy()
                self.db.execute('UPDATE av_schema SET version=3')
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    def _migrate_transport_limits(self):
        # V1 did not store retry durations on checks. Conservatively carry its
        # maximum deadline to every transport with applied rate evidence. Never
        # infer a CLI limit from direct evidence. Without evidence retain the
        # legacy global value, explicitly projected as unknown scope. Historical
        # revoked is ambiguous (manual vs upstream); never auto-unrevoke it.
        for key in self.db.execute('SELECT id,cooldown FROM av_credentials WHERE cooldown>0').fetchall():
            scopes = self.db.execute('''SELECT DISTINCT m.base_url,m.protocol
                FROM av_checks h JOIN av_connections c ON c.id=h.connection_id
                JOIN av_models m ON m.id=c.model_id WHERE c.credential_id=?
                AND h.state='rate_limited' AND h.applied=1 AND h.finished_at IS NOT NULL''',
                (key['id'],)).fetchall()
            for scope in scopes:
                self.db.execute('''INSERT INTO av_transport_limits
                    (credential_id,base_url,protocol,cooldown) VALUES (?,?,?,?)
                    ON CONFLICT(credential_id,base_url,protocol) DO UPDATE SET
                    cooldown=MAX(cooldown,excluded.cooldown)''',
                    (key['id'], scope['base_url'], scope['protocol'], key['cooldown']))
            if scopes:
                self.db.execute('UPDATE av_credentials SET cooldown=0 WHERE id=?', (key['id'],))

    def _migrate_cli_ipc_policy(self):
        # IPC is a new identity requiring fresh checks. Preserve only evidenced
        # active prior CLI policy, separately attributed, never success/direct
        # limits. Copy absolute deadlines once; restarting cannot renew them.
        from availability import BRIDGE_BASE
        old_base = 'http://127.0.0.1:8099/v1'
        for limit in self.db.execute('''SELECT t.* FROM av_transport_limits t
            JOIN av_credentials k ON k.id=t.credential_id
            WHERE k.provider='opencode-zen' AND t.protocol='zencli' AND t.base_url=?''', (old_base,)).fetchall():
            states = {row[0] for row in self.db.execute('''SELECT DISTINCT h.state
                FROM av_checks h JOIN av_connections c ON c.id=h.connection_id
                JOIN av_models m ON m.id=c.model_id WHERE c.credential_id=?
                AND m.base_url=? AND m.protocol='zencli' AND h.applied=1
                AND h.finished_at IS NOT NULL''', (limit['credential_id'], old_base))}
            cooldown = limit['cooldown'] if limit['cooldown'] > time.time() and 'rate_limited' in states else 0
            auth_invalid = int(bool(limit['auth_invalid'] and 'auth_invalid' in states))
            if cooldown or auth_invalid:
                self.db.execute('''INSERT OR IGNORE INTO av_transport_inheritance
                    (credential_id,base_url,protocol,source_base_url,cooldown,auth_invalid)
                    VALUES (?,?,'zencli',?,?,?)''',
                    (limit['credential_id'], BRIDGE_BASE, old_base, cooldown, auth_invalid))

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
