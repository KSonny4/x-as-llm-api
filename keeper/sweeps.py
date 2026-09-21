"""Durable full-coverage queue and paced worker. No network in page reads.

Multiple process claims serialize in SQLite. Lease expiry fences abandoned
checks, provider/key pacing persists, and manual checks cannot clear cooldowns.
run() belongs on one background thread, never in the HTTP request handler.
"""
from availability import (CONNECTION_SQL, DAILY_CHECK_BUDGET, Result,
                           blocked_reason, checks_started_since, identity,
                           utc_day_start)
from inference import verify


class Sweeps:
    def __init__(self, service, provider_interval=2, key_interval=5,
                 lease_seconds=90, max_attempts=3, verifier=verify,
                 daily_budget=DAILY_CHECK_BUDGET):
        self.service = service
        self.store = service.store
        self.clock = service.clock
        if min(provider_interval, key_interval) < 0 or lease_seconds <= 25 or max_attempts < 1:
            raise ValueError('invalid worker limits')
        if daily_budget < 1:
            raise ValueError('daily check budget must cover at least one verification')
        self.provider_interval = provider_interval
        self.key_interval = key_interval
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.verifier = verifier
        self.daily_budget = daily_budget

    def schedule(self, kind='manual', credential_id=None, model_id=None):
        """Schedule EVERY eligible pair; active jobs are shared across sweeps.

        Optional IDs filter exact stored identities (never a model substring).
        Daily dedup is durable. Pricing must be refreshed before a daily sweep.
        """
        if kind not in ('manual', 'daily', 'verification'):
            raise ValueError('invalid sweep kind')
        now = self.clock()
        with self.store.transaction() as db:
            if kind == 'daily' and db.execute(
                    "SELECT 1 FROM av_sweeps WHERE kind='daily' AND created_at>?", (now - 86400,)).fetchone():
                return None
            sid = db.execute('INSERT INTO av_sweeps(kind,created_at) VALUES (?,?)', (kind, now)).lastrowid
            for c in db.execute(CONNECTION_SQL).fetchall():
                if credential_id and c['credential_id'] != credential_id:
                    continue
                if model_id and c['model_id'] != model_id:
                    continue
                if blocked_reason(c, now):
                    continue
                jid = self.service._enqueue(db, c['id'])
                db.execute('INSERT INTO av_sweep_jobs VALUES (?,?)', (sid, jid))
            return sid

    def _new_feedback(self, db, check):
        return bool(check and db.execute(
            'SELECT 1 FROM av_feedback WHERE connection_id=? AND id>?',
            (check['connection_id'], check['feedback_id'])).fetchone())

    def _recover(self, db):
        for job in db.execute("SELECT * FROM av_jobs WHERE state='running' AND lease_until<=?", (self.clock(),)).fetchall():
            check = db.execute('SELECT * FROM av_checks WHERE id=?', (job['check_id'],)).fetchone()
            if check and check['finished_at'] is None:
                db.execute('UPDATE av_connections SET revision=revision+1 WHERE id=? AND revision=?',
                           (job['connection_id'], check['revision']))
                db.execute("UPDATE av_checks SET finished_at=?,state='transient_error',applied=0 WHERE id=?",
                           (self.clock(), check['id']))
            newer = self._new_feedback(db, check)
            db.execute('''UPDATE av_jobs SET state=?,lease_until=NULL,check_id=NULL,
                attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE id=?''',
                ('done' if job['attempts'] >= self.max_attempts and not newer else 'queued',
                 int(newer), job['id']))

    def claim(self, connection_id=None):
        now = self.clock()
        day = utc_day_start(now)
        with self.store.transaction() as db:
            self._recover(db)
            jobs = db.execute("SELECT j.* FROM av_jobs j JOIN av_connections c ON c.id=j.connection_id WHERE j.state='queued' AND j.due_at<=? ORDER BY CASE WHEN j.attempts>0 THEN 0 ELSE 1 END, CASE WHEN c.checked_at IS NULL THEN 0 ELSE 1 END, c.checked_at, j.id", (now,)).fetchall()
            for job in jobs:
                if connection_id and job['connection_id'] != connection_id:
                    continue
                c = db.execute(CONNECTION_SQL + ' WHERE c.id=?', (job['connection_id'],)).fetchone()
                if connection_id is None and checks_started_since(db, c['credential_id'], day) >= self.daily_budget:
                    continue
                if blocked_reason(c, now):
                    db.execute("UPDATE av_jobs SET state='blocked' WHERE id=?", (job['id'],))
                    continue
                if max(c['cooldown'], c['retry_at']) > now:
                    continue
                scope = identity(c['provider'], c['base_url'], c['protocol'])
                pacing = db.execute('SELECT next_at FROM av_transport_provider_pacing WHERE scope=?', (scope,)).fetchone()
                key_pacing = db.execute('SELECT next_at FROM av_transport_key_pacing WHERE credential_id=? AND scope=?', (c['credential_id'], scope)).fetchone()
                if (pacing and pacing[0] > now) or (key_pacing and key_pacing[0] > now):
                    continue
                if db.execute('''SELECT 1 FROM av_jobs j JOIN av_connections c ON c.id=j.connection_id
                    JOIN av_credentials k ON k.id=c.credential_id JOIN av_models m ON m.id=c.model_id
                    WHERE j.state='running' AND k.provider=? AND m.base_url=? AND m.protocol=?''',
                    (c['provider'], c['base_url'], c['protocol'])).fetchone():
                    continue
                ticket = self.service._begin(db, c['id'])
                if not ticket:
                    continue
                db.execute("UPDATE av_jobs SET state='running',attempts=attempts+1,lease_until=?,check_id=? WHERE id=?",
                           (now + self.lease_seconds, ticket, job['id']))
                db.execute('INSERT INTO av_transport_provider_pacing VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET next_at=excluded.next_at',
                           (scope, now + self.provider_interval))
                db.execute('INSERT INTO av_transport_key_pacing VALUES (?,?,?) ON CONFLICT(credential_id,scope) DO UPDATE SET next_at=excluded.next_at',
                           (c['credential_id'], scope, now + self.key_interval))
                return {**dict(c), 'job_id': job['id'], 'check_id': ticket}
        return None

    def complete(self, job, result):
        with self.store.transaction() as db:
            current = db.execute('SELECT * FROM av_jobs WHERE id=?', (job['job_id'],)).fetchone()
            if (not current or current['state'] != 'running' or current['check_id'] != job['check_id']):
                return False
            if current['lease_until'] <= self.clock():
                self._recover(db)
                return False
            applied = self.service._finish(db, job['check_id'], result)
            check = db.execute('SELECT * FROM av_checks WHERE id=?', (job['check_id'],)).fetchone()
            feedback_race = not applied and self._new_feedback(db, check)
            retry = applied and result.state in ('rate_limited', 'transient_error') and current['attempts'] < self.max_attempts
            delay = max(result.retry_after, 60 * 2 ** (current['attempts'] - 1)) if retry else 0
            db.execute('''UPDATE av_jobs SET state=?,due_at=?,lease_until=NULL,check_id=NULL,
                attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE id=?''',
                ('queued' if retry or feedback_race else 'done', self.clock() + delay,
                 int(bool(feedback_race)), job['job_id']))
            return applied

    def progress(self, sweep_id):
        counts = self.store.rows('''SELECT j.state,COUNT(*) AS n FROM av_jobs j
            JOIN av_sweep_jobs s ON s.job_id=j.id WHERE s.sweep_id=? GROUP BY j.state''', (sweep_id,))
        result = {'id': sweep_id, 'total': sum(r['n'] for r in counts),
                  'done': 0, 'queued': 0, 'running': 0, 'blocked': 0}
        result.update({r['state']: r['n'] for r in counts})
        result['pending'] = result['queued'] + result['running']
        return result

    def run_once(self, resolve_secret, transport=None):
        """resolve_secret(provider, reference) reads runtime seeds, NEVER SQLite."""
        job = self.claim()
        if not job:
            return False
        try:
            secret = resolve_secret(job['provider'], job['reference'])
            kwargs = {'clock': self.clock}
            if transport is not None:
                kwargs['transport'] = transport
            result = self.verifier(job, secret, **kwargs)
        except Exception:
            result = Result('transient_error')
        self.complete(job, result)
        return True

    def run(self, stop_event, resolve_secret, refresh_catalog, transport=None):
        """Blocking background loop; stop_event.wait supplies interruptible sleep.

        A failed persistence operation propagates to the supervisor instead of
        pretending the sweep completed. refresh_catalog itself records sanitized
        provider failures. Persisted daily sweep time determines restart cadence.
        """
        while not stop_event.is_set():
            latest = self.store.rows("SELECT MAX(created_at) AS at FROM av_sweeps WHERE kind='daily'")
            if latest[0]['at'] is None or self.clock() - latest[0]['at'] >= 86400:
                refresh_catalog()
                self.schedule('daily')
            self.run_once(resolve_secret, transport)
            stop_event.wait(1)
