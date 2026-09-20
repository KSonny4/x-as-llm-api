"""Shared exact-model verified selection; only select/replace return secrets.

Verification uses the durable paced queue, including on-demand requests. No
network call holds the SQLite lock. Final eligibility and selection history
are committed together, fencing feedback received during verification.
"""
from availability import Result, evidence_age
from inference import connection_config, request, verify


class Selector:
    def __init__(self, service, sweeps, resolve_secret, transport=request, verifier=verify, config_builder=connection_config):
        self.service = service
        self.sweeps = sweeps
        self.resolve_secret = resolve_secret
        self.transport = transport
        self.verifier = verifier
        self.config_builder = config_builder

    def select(self, model_id, exclude=(), force_verify=False, max_attempts=3, export=True):
        s = self.service
        if export and s.store.rows("SELECT 1 FROM av_models WHERE id=? AND protocol='zencli'", (model_id,)):
            return {'error':'not_exportable', 'model_id':model_id}
        rows = [c for c in s.connections() if c['model_id'] == model_id
                and c['id'] not in exclude and not c['excluded'] and not c['blocked_reason']
                and c['retry_at'] <= s.clock()]
        rows.sort(key=lambda c: (c['state'] != 'working', -(c['checked_at'] or 0), c['id']))
        pending = False
        for c in rows[:max_attempts]:
            if force_verify or c['state'] != 'working' or not 0 <= evidence_age(c['checked_at'], s.clock()) <= 300:
                with s.store.transaction() as db:
                    s._enqueue(db, c['id'])
                job = self.sweeps.claim(c['id'])
                if not job:
                    pending = True
                    continue
                try:
                    result = self.verifier(job, self.resolve_secret(c['provider'], c['reference']),
                                    self.transport, s.clock)
                except Exception:
                    result = Result('transient_error')
                if not self.sweeps.complete(job, result) or result.state != 'working':
                    continue
            # RLock allows a local snapshot inside the transaction, never network.
            with s.store.transaction() as db:
                current = next(row for row in s.connections() if row['id'] == c['id'])
                if (current['state'] != 'working' or current['blocked_reason'] or current['excluded']
                        or current['retry_at'] > s.clock()
                        or not 0 <= evidence_age(current['checked_at'], s.clock()) <= 300):
                    continue
                secret = self.resolve_secret(current['provider'], current['reference'])
                if not secret:
                    continue
                config = self.config_builder(current, secret)
                db.execute('INSERT INTO av_selections(connection_id,created_at) VALUES (?,?)',
                           (c['id'], s.clock()))
                return {**config, 'connection_id': c['id'], 'model_id': model_id,
                        'provider': c['provider'], 'verified_at': current['checked_at']}
        return {'error': 'verification_pending' if pending else 'no_working_connection', 'model_id': model_id}

    def replace(self, connection_id, reason='client_failure'):
        cells = [c for c in self.service.connections() if c['id'] == connection_id]
        if not cells:
            raise KeyError('unknown connection')
        self.service.report_failure(connection_id, reason)
        return self.select(cells[0]['model_id'], exclude=(connection_id,), force_verify=True)
