"""Exact direct-API availability domain. No legacy success imports or secrets.

Model metadata comes only from trusted discovery/seed configuration, never HTTP
clients. Runtime secret resolution belongs to the service's caller. Public
snapshots are local SQLite reads and never trigger discovery or inference.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import time
from urllib.parse import urlsplit
from typing import Optional

STALE_AFTER = 30 * 3600
CATALOG_TTL = 24 * 3600
PROTOCOLS = {'openai', 'responses', 'anthropic', 'gemini'}
RESULT_STATES = {'working', 'access_denied', 'auth_invalid', 'rate_limited',
                 'transient_error', 'invalid_response', 'model_mismatch', 'unsupported'}


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


def safe_base(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        return ''
    return value.rstrip('/')


@dataclass(frozen=True)
class Model:
    provider: str
    model: str
    base_url: str
    protocol: str
    eligibility: str = 'unknown'
    provenance: str = ''
    requires_free_tier: bool = False
    verified_at: Optional[float] = None

    @property
    def id(self):
        return identity(self.provider, self.model, self.base_url, self.protocol)


def seed_model(route):
    """Only exact, timestamped pricing evidence is usable from trusted seeds."""
    evidence = route.get('free_eligibility') or {}
    stamp = evidence.get('verified_at') if isinstance(evidence, dict) else None
    known = (isinstance(evidence, dict) and evidence.get('kind') in ('zero_price', 'recurring_allowance')
             and bool(evidence.get('provenance')) and isinstance(stamp, (int, float)) and math.isfinite(stamp))
    return Model(route['provider'], route['model'], safe_base(route.get('base_url', '')),
                 route.get('wire', 'openai'), 'free' if known else 'unknown',
                 str(evidence['provenance']) if known else '',
                 bool(known and evidence['kind'] == 'recurring_allowance'), stamp if known else None)


@dataclass(frozen=True)
class Result:
    # Deliberately no provider body, generated text, exception text or headers.
    state: str
    retry_after: float = 0

    def __post_init__(self):
        if self.state not in RESULT_STATES:
            raise ValueError('invalid observation state')
        if not math.isfinite(self.retry_after) or self.retry_after < 0:
            raise ValueError('invalid retry delay')


CONNECTION_SQL = """SELECT c.*, k.provider, k.reference, k.owner, k.active,
 k.supported, k.has_secret, k.free_tier, k.revoked, k.cooldown,
 k.revision AS key_revision, m.model, m.base_url, m.protocol,
 m.eligibility, m.provenance, m.requires_free_tier, m.present,
 m.checked_at AS catalog_checked_at
 FROM av_connections c JOIN av_credentials k ON k.id=c.credential_id
 JOIN av_models m ON m.id=c.model_id"""


def evidence_age(stamp, now):
    if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        return -1
    return now - stamp


def blocked_reason(c, now):
    if not c['active']:
        return 'disabled'
    if c['revoked']:
        return 'revoked'
    if not c['supported'] or c['protocol'] not in PROTOCOLS or not safe_base(c['base_url']):
        return 'unsupported'
    if not c['has_secret']:
        return 'signin_required'
    if not c['present']:
        return 'catalog_removed'
    if c['eligibility'] != 'free':
        return 'paid' if c['eligibility'] == 'paid' else 'eligibility_unknown'
    if not c['provenance']:
        return 'eligibility_unknown'
    if not 0 <= evidence_age(c['catalog_checked_at'], now) < CATALOG_TTL:
        return 'catalog_stale'
    if c['requires_free_tier'] and not c['free_tier']:
        return 'free_tier_unverified'
    return None


def aggregate_health(states):
    states = list(states)
    for health in ('working', 'stale', 'suspect', 'cooldown'):
        if health in states:
            return health
    failed = RESULT_STATES - {'working', 'unsupported'} | {'failed', 'revoked'}
    if states and all(state in failed for state in states):
        return 'failed'
    return 'unknown'


class Availability:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock

    def sync_seeds(self, routes):
        """Account for ALL configured keys; env_var/credential_ref dedups routes.

        Missing ownership stays NULL. Missing metadata never means free. Seed
        refresh does not un-revoke keys; removed keys remain visible/disabled.
        A rotated key must use a new credential_ref (not a reused route ID).
        """
        grouped = {}
        for r in routes:
            provider = str(r.get('provider') or 'unknown')
            ref = str(r.get('credential_ref') or r.get('env_var') or '')
            if not ref:
                ref = 'unreferenced:' + identity(provider, r.get('connection_id'), r.get('model'))
            grouped.setdefault((provider, ref), []).append(r)
        with self.store.transaction() as db:
            existing = {r['id']: dict(r) for r in db.execute('SELECT * FROM av_credentials')}
            db.execute('UPDATE av_credentials SET active=0')
            for (provider, ref), rs in grouped.items():
                kid = identity(provider, ref)
                owners = {str(r.get('owner') or '').strip().lower() for r in rs} - {''}
                owner = next(iter(owners)) if len(owners) == 1 else None
                inactive_status = {'disabled', 'retired', 'inactive', 'revoked', 'banned'}
                active = all(r.get('active', True) and str(r.get('bao_status', '')).lower()
                             not in inactive_status for r in rs)
                supported = not ref.startswith('unreferenced:') and any(
                    r.get('wire', 'openai') in PROTOCOLS and safe_base(r.get('base_url', '')) for r in rs)
                has_secret = any(bool(r.get('api_key')) for r in rs)
                tier = all(r.get('free_tier') is True and r.get('no_paid_fallback') is True
                           and r.get('tier_provenance') for r in rs)
                values = (provider, ref, owner, int(active), int(supported), int(has_secret), int(tier))
                old = existing.get(kid)
                changed = old and tuple(old[x] for x in
                    ('provider', 'reference', 'owner', 'active', 'supported', 'has_secret', 'free_tier')) != values
                db.execute('''INSERT INTO av_credentials
                    (id,provider,reference,owner,active,supported,has_secret,free_tier)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    owner=excluded.owner, active=excluded.active, supported=excluded.supported,
                    has_secret=excluded.has_secret, free_tier=excluded.free_tier,
                    revision=av_credentials.revision+?''', (kid,) + values + (int(bool(changed)),))
                for r in rs:
                    if r.get('model'):
                        model = seed_model(r)
                        self._put_model(db, model, replace=model.eligibility == 'free')
            removed = set(existing) - {identity(*pair) for pair in grouped}
            for kid in removed:
                if existing[kid]['active']:
                    db.execute('UPDATE av_credentials SET revision=revision+1 WHERE id=?', (kid,))
            self._expand(db)

    def _put_model(self, db, m, replace=True):
        if m.eligibility not in {'free', 'paid', 'unknown'}:
            raise ValueError('invalid eligibility')
        if m.eligibility == 'free' and (not m.provenance or not safe_base(m.base_url)):
            raise ValueError('free model requires pricing provenance and safe endpoint')
        checked_at = self.clock() if m.verified_at is None else m.verified_at
        if not math.isfinite(checked_at):
            raise ValueError('invalid catalog time')
        old = db.execute('SELECT * FROM av_models WHERE id=?', (m.id,)).fetchone()
        if old and replace:
            if isinstance(old['checked_at'], (int, float)) and checked_at < old['checked_at']:
                return
            if (old['eligibility'], old['requires_free_tier'], old['present']) != (m.eligibility, int(m.requires_free_tier), 1):
                db.execute('UPDATE av_connections SET revision=revision+1 WHERE model_id=?', (m.id,))
        values = (m.id, m.provider, m.model, m.base_url, m.protocol, m.eligibility,
                  m.provenance, checked_at, int(m.requires_free_tier))
        suffix = ''' ON CONFLICT(id) DO UPDATE SET eligibility=excluded.eligibility,
            provenance=excluded.provenance, checked_at=excluded.checked_at,
            requires_free_tier=excluded.requires_free_tier, present=1''' if replace else ' ON CONFLICT(id) DO NOTHING'
        db.execute('''INSERT INTO av_models
            (id,provider,model,base_url,protocol,eligibility,provenance,checked_at,requires_free_tier)
            VALUES (?,?,?,?,?,?,?,?,?)''' + suffix, values)

    def _expand(self, db):
        for k in db.execute('SELECT id,provider FROM av_credentials').fetchall():
            for m in db.execute('SELECT id FROM av_models WHERE provider=?', (k['provider'],)).fetchall():
                db.execute('INSERT OR IGNORE INTO av_connections(id,credential_id,model_id) VALUES (?,?,?)',
                           (identity(k['id'], m['id']), k['id'], m['id']))

    def update_catalog(self, provider, models, complete=True):
        """Publish a provider union after discovering EVERY key (not first-key only).

        A failed key discovery should set complete=False, preserving missing rows
        and their original freshness, not renewing unobserved free eligibility.
        """
        models = list(models)
        if any(m.provider != provider for m in models):
            raise ValueError('catalog provider mismatch')
        with self.store.transaction() as db:
            if complete:
                current_ids = {m.id for m in models}
                for old in db.execute('SELECT id FROM av_models WHERE provider=? AND present=1', (provider,)).fetchall():
                    if old['id'] not in current_ids:
                        db.execute('UPDATE av_models SET present=0 WHERE id=?', (old['id'],))
                        db.execute('UPDATE av_connections SET revision=revision+1 WHERE model_id=?', (old['id'],))
            for m in models:
                self._put_model(db, m)
            self._expand(db)

    def connections(self):
        now = self.clock()
        rows = self.store.rows(CONNECTION_SQL + ' ORDER BY k.provider,k.reference,m.model,m.protocol')
        for c in rows:
            c['observation_state'] = c['state']
            c['blocked_reason'] = blocked_reason(c, now)
            c['retry_at'] = max(c['retry_at'], c['cooldown'])
            age = evidence_age(c['checked_at'], now)
            if c['blocked_reason'] and c['blocked_reason'] != 'catalog_stale':
                c['state'] = c['blocked_reason']
            elif c['excluded']:
                c['state'] = 'suspect'
            elif c['retry_at'] > now:
                c['state'] = 'cooldown'
            elif c['state'] == 'working':
                c['state'] = ('unknown' if age < 0 else 'stale' if age >= STALE_AFTER
                              else 'working')
            elif c['blocked_reason']:
                c['state'] = c['blocked_reason']
        return rows

    def catalog(self):
        """Secret-free, local-only route catalog; consumers must not collapse IDs."""
        rows = self.connections()
        models = self.store.rows('SELECT * FROM av_models ORDER BY provider,model,protocol,base_url')
        for model in models:
            cells = [c for c in rows if c['model_id'] == model['id']]
            model['connections'] = cells
            model['working_keys'] = sum(c['state'] == 'working' for c in cells)
            model['total_keys'] = len(cells)
            model['checked'] = sum(c['checked_at'] is not None for c in cells)
            model['blocked'] = sum(bool(c['blocked_reason']) for c in cells)
            model['state'] = aggregate_health(c['state'] for c in cells)
        return {'models': models, 'discovery': self.store.rows('SELECT * FROM av_discovery ORDER BY credential_id')}

    def accounts(self):
        keys = self.store.rows('SELECT * FROM av_credentials ORDER BY provider,reference')
        rows = self.connections()
        owners = {}
        for k in keys:
            cells = [c for c in rows if c['credential_id'] == k['id']]
            k['connections'] = cells
            k['working'] = sum(c['state'] == 'working' for c in cells)
            k['total'] = len(cells)
            k['checked'] = sum(c['checked_at'] is not None for c in cells)
            k['blocked'] = sum(bool(c['blocked_reason']) for c in cells)
            k['state'] = ('disabled' if not k['active'] else 'revoked' if k['revoked']
                          else aggregate_health(c['state'] for c in cells
                                                if c['blocked_reason'] in (None, 'catalog_stale')))
            owners.setdefault(k['owner'], []).append(k)
        return {'keys': keys, 'owners': [
            {'owner': owner, 'state': aggregate_health(k['state'] for k in ks if k['active']),
             'working_keys': sum(k['working'] > 0 for k in ks), 'total_keys': len(ks)}
            for owner, ks in owners.items()]}

    def _begin(self, db, cid):
        row = db.execute(CONNECTION_SQL + ' WHERE c.id=?', (cid,)).fetchone()
        if row is None:
            raise KeyError('unknown connection')
        if blocked_reason(row, self.clock()) or max(row['cooldown'], row['retry_at']) > self.clock():
            return None
        revision = row['revision'] + 1
        db.execute('UPDATE av_connections SET revision=? WHERE id=?', (revision, cid))
        cur = db.execute('''INSERT INTO av_checks
            (connection_id,revision,key_revision,started_at,feedback_id) VALUES (?,?,?,?,?)''',
            (cid, revision, row['key_revision'], self.clock(),
             db.execute('SELECT COALESCE(MAX(id),0) FROM av_feedback WHERE connection_id=?', (cid,)).fetchone()[0]))
        return cur.lastrowid

    def begin_check(self, cid):
        with self.store.transaction() as db:
            return self._begin(db, cid)

    def _finish(self, db, ticket, result):
        check = db.execute('SELECT * FROM av_checks WHERE id=?', (ticket,)).fetchone()
        if check is None:
            raise KeyError('unknown check')
        if check['finished_at'] is not None:
            return False
        c = db.execute(CONNECTION_SQL + ' WHERE c.id=?', (check['connection_id'],)).fetchone()
        applied = (check['revision'] == c['revision'] and check['key_revision'] == c['key_revision']
                   and check['started_at'] <= self.clock() and not blocked_reason(c, self.clock()))
        db.execute('UPDATE av_checks SET finished_at=?,state=?,applied=? WHERE id=?',
                   (self.clock(), result.state, int(applied), ticket))
        if applied:
            retry = self.clock() + result.retry_after if result.retry_after else 0
            db.execute('''UPDATE av_connections SET state=?,checked_at=?,retry_at=?,
                excluded=CASE WHEN ?='working' THEN 0 ELSE excluded END WHERE id=?''',
                (result.state, self.clock(), retry, result.state, c['id']))
            if result.state == 'auth_invalid':
                db.execute('UPDATE av_credentials SET revoked=1,revision=revision+1 WHERE id=?',
                           (c['credential_id'],))
            elif result.state == 'rate_limited':
                db.execute('UPDATE av_credentials SET cooldown=MAX(cooldown,?) WHERE id=?',
                           (max(retry, self.clock() + 60), c['credential_id']))
        return bool(applied)

    def finish_check(self, ticket, result):
        with self.store.transaction() as db:
            return self._finish(db, ticket, result)

    def report_failure(self, cid, reason='client_failure'):
        # Never persist arbitrary client text; it can contain a provider key.
        if reason not in RESULT_STATES | {'client_failure'}:
            reason = 'client_failure'
        with self.store.transaction() as db:
            cur = db.execute('UPDATE av_connections SET excluded=1,revision=revision+1 WHERE id=?', (cid,))
            if not cur.rowcount:
                raise KeyError('unknown connection')
            db.execute('INSERT INTO av_feedback(connection_id,created_at,reason) VALUES (?,?,?)',
                       (cid, self.clock(), reason))
            self._enqueue(db, cid)

    def _enqueue(self, db, cid):
        row = db.execute("SELECT id FROM av_jobs WHERE connection_id=? AND state IN ('queued','running')", (cid,)).fetchone()
        if row:
            return row['id']
        return db.execute('INSERT INTO av_jobs(connection_id,due_at) VALUES (?,?)',
                          (cid, self.clock())).lastrowid

    def history(self, cid):
        return self.store.rows('SELECT * FROM av_checks WHERE connection_id=? ORDER BY id', (cid,))

    def feedback(self, cid):
        return self.store.rows('SELECT * FROM av_feedback WHERE connection_id=? ORDER BY id', (cid,))

    def record_selection(self, cid):
        with self.store.transaction() as db:
            db.execute('INSERT INTO av_selections(connection_id,created_at) VALUES (?,?)', (cid, self.clock()))
