"""Private admin API. Authentication/session checks live at the routing seam."""
import hashlib
import hmac
import json

NO_STORE = [('Cache-Control', 'no-store, private'), ('X-Content-Type-Options', 'nosniff')]
MUTATIONS = {'/api/v2/checks', '/api/v2/credentials', '/api/v2/feedback',
             '/api/v2/discovery/refresh'}


def csrf_token(state, raw_session):
    return hmac.new(state['token'].encode(), ('csrf:' + raw_session).encode(), hashlib.sha256).hexdigest()


def browser_mutation_ok(state, headers, raw_session):
    h = {k.lower(): v for k, v in headers.items()}
    origin = state.get('public_origin', '')
    return bool(origin and h.get('origin') == origin and raw_session
                and hmac.compare_digest(h.get('x-keeper-csrf', ''), csrf_token(state, raw_session))
                and h.get('sec-fetch-site', 'same-origin') == 'same-origin')


def response(code, doc):
    return code, json.dumps(doc).encode(), [('Content-Type', 'application/json')] + NO_STORE


def catalog(state):
    s = state['availability']
    doc = s.catalog()
    import aa
    doc['models'] = aa.rank_models(doc['models'], state.get('aa_scores', {}))
    doc.update(s.accounts())
    sweeps = s.store.rows('SELECT * FROM av_sweeps ORDER BY id DESC LIMIT 1')
    doc['sweep'] = ({**sweeps[0], **state['sweeps'].progress(sweeps[0]['id'])} if sweeps else None)
    doc['jobs'] = s.store.rows('SELECT state,COUNT(*) AS count FROM av_jobs GROUP BY state')
    doc['aa'] = {'source': 'Artificial Analysis Coding Index', 'checked_at': state.get('aa_checked_at'),
                 'succeeded_at': state.get('aa_succeeded_at'), 'stale': state.get('aa_stale', True),
                 # Per-row provenance: models[].coding_index_match (alias|exact|normalized|ai).
                 'match_decided_at': aa.aa_match.table()['decided_at'],
                 'match_error': state.get('aa_match_error')}
    doc['now'] = s.clock()
    doc['build'] = state.get('build', 'development')
    doc['worker_error'] = state.get('worker_error')
    doc['bridge_error'] = state.get('bridge_error')
    return doc


def handle(state, method, path, body, raw_session):
    if method == 'GET' and path == '/api/v2/session':
        return response(200, {'csrf': csrf_token(state, raw_session) if raw_session else None})
    if 'availability' not in state:
        return response(503, {'error': 'availability_not_initialized'})
    if method == 'GET' and path == '/api/v2/catalog':
        return response(200, catalog(state))
    if method != 'POST' or path not in MUTATIONS:
        return response(404, {'error': 'not_found'})
    try:
        doc = json.loads(body or b'{}')
        fields = {'/api/v2/checks': {'credential_id', 'model_id'},
                  '/api/v2/credentials': {'model_id'},
                  '/api/v2/feedback': {'connection_id', 'reason'},
                  '/api/v2/discovery/refresh': set()}[path]
        if not isinstance(doc, dict) or set(doc) - fields or any(not isinstance(v, str) for v in doc.values()):
            raise ValueError()
        s = state['availability']
        if path == '/api/v2/discovery/refresh':
            try:
                sid = state['sweeps'].schedule('forced')
            except ValueError:
                return response(409, {'error': 'forced_refresh_too_soon'})
            return response(202, state['sweeps'].progress(sid))
        if path == '/api/v2/checks':
            for name, table in [('credential_id', 'av_credentials'), ('model_id', 'av_models')]:
                if name in doc and not s.store.rows('SELECT id FROM ' + table + ' WHERE id=?', (doc[name],)):
                    raise KeyError()
            sid = state['sweeps'].schedule(**doc)
            return response(202, state['sweeps'].progress(sid))
        if path == '/api/v2/credentials':
            if not doc.get('model_id'):
                raise ValueError()
            if not s.store.rows('SELECT id FROM av_models WHERE id=?', (doc['model_id'],)):
                raise KeyError()
            result = state['selector'].select(doc['model_id'])
        else:
            if not doc.get('connection_id'):
                raise ValueError()
            result = state['selector'].replace(doc['connection_id'], doc.get('reason', 'client_failure'))
        return response(409 if 'error' in result else 200, result)
    except KeyError:
        return response(404, {'error': 'unknown_identity'})
    except (ValueError, TypeError):
        return response(422, {'error': 'invalid_request'})
