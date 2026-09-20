"""Inference-only service principal: ranked free alias, no Keeper usage quotas.

Provider failures are precise observations + feedback. At most three connection attempts per request; same-model keys precede lower-ranked
model routes; never fail over after the first streaming byte.
HTTP response/error bodies never become diagnostics, logs or feedback text.
"""
import json
import urllib.error
import urllib.request

import aa
from api_v2 import response
from availability import Result
from inference import NoRedirect, request, retry_after
import service_wire as wire

ALIAS = 'keeper-coder'


class UpstreamFailure(Exception):
    def __init__(self, state='transient_error', delay=0):
        self.result = Result(state, delay)


def error(code, name):
    return response(code, {'error': {'message': name, 'type': 'keeper_error', 'code': name}})


def models():
    return response(200, {'object':'list','data':[{'id':ALIAS,'object':'model','owned_by':'keeper',
        'description':'Highest Coding Index verified working compatible free route; unscored fallback when unmatched.'}]})


def classify(status, headers, now):
    if status == 429: return UpstreamFailure('rate_limited', retry_after(headers, now))
    if status in (401, 402, 403): return UpstreamFailure('access_denied')
    return UpstreamFailure('transient_error' if status >= 500 else 'invalid_response')


def stream_request(config, payload):
    """Yield actual provider SSE events, bounded event size and socket timeout."""
    url = config['endpoint']
    if config['protocol'] == 'gemini':
        url = url.replace(':generateContent', ':streamGenerateContent') + '?alt=sse'
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=config['headers'], method='POST')
    try:
        res = urllib.request.build_opener(NoRedirect()).open(req, timeout=25)
    except urllib.error.HTTPError as exc:
        import time
        failure = classify(exc.code, dict(exc.headers), time.time())
        exc.close()
        raise failure
    with res:
        data = []
        size = 0
        while True:
            raw = res.readline(1024 * 1024 + 1)
            if not raw: break
            size += len(raw)
            if size > 1024 * 1024: raise UpstreamFailure('invalid_response')
            line = raw.decode('utf-8').rstrip('\r\n')
            if line.startswith('data:'): data.append(line[5:].lstrip())
            elif not line:
                if data:
                    text = '\n'.join(data)
                    if text == '[DONE]': return
                    yield json.loads(text)
                data, size = [], 0
        if data: raise UpstreamFailure('invalid_response')


def _safe_doc(doc, config):
    # Keep response content/semantics, not provider diagnostics. Do not leak a
    # credential if a malicious upstream reflects its Authorization header.
    raw = json.dumps(doc)
    if config['api_key'] and config['api_key'] in raw:
        raise UpstreamFailure('invalid_response')
    return raw.encode()


def _usable(doc):
    for choice in doc.get('choices', []):
        msg = choice.get('message', {})
        if isinstance(msg.get('content'), str) and msg['content'].strip(): return True
        for tc in msg.get('tool_calls', []):
            if tc.get('type') == 'function' and tc.get('id') and tc.get('function', {}).get('name') and isinstance(tc['function'].get('arguments'), str):
                try:
                    if isinstance(json.loads(tc['function']['arguments']), dict): return True
                except ValueError:
                    pass
    return False


def _failed(state, config, ticket, failure):
    result = failure.result if isinstance(failure, UpstreamFailure) else Result('transient_error')
    state['availability'].finish_check(ticket, result)
    state['availability'].report_failure(config['connection_id'], result.state)


def _validated_chunks(events, config):
    """Hold metadata until usable text/tool output; empty streams prove nothing."""
    prefix, tools, meaningful = [], {}, False
    try:
        for part in wire.stream_chunks(events, config):
            _safe_doc(part, config)
            for choice in part.get('choices', []):
                delta = choice.get('delta', {})
                if isinstance(delta.get('content'), str) and delta['content'].strip():
                    meaningful = True
                for call in delta.get('tool_calls', []):
                    key = (choice.get('index', 0), call.get('index', 0))
                    tool = tools.setdefault(key, {'id':'', 'name':'', 'arguments':''})
                    tool['id'] += call.get('id', '')
                    tool['name'] += call.get('function', {}).get('name', '')
                    tool['arguments'] += call.get('function', {}).get('arguments', '')
                    if tool['id'] and tool['name']:
                        meaningful = True
            if not meaningful:
                prefix.append(part)
                if len(prefix) > 64: raise UpstreamFailure('invalid_response')
                continue
            yield from prefix
            prefix.clear()
            yield part
        if not meaningful: raise UpstreamFailure('invalid_response')
        for tool in tools.values():
            if not tool['id'] or not tool['name'] or not isinstance(json.loads(tool['arguments']), dict):
                raise UpstreamFailure('invalid_response')
    except (ValueError, KeyError, TypeError):
        raise UpstreamFailure('invalid_response')
    finally:
        close = getattr(events, 'close', None)
        if close: close()


def _stream_body(first, chunks, state, config, ticket):
    try:
        yield b'data: ' + _safe_doc(first, config) + b'\n\n'
        for chunk in chunks:
            yield b'data: ' + _safe_doc(chunk, config) + b'\n\n'
        state['availability'].finish_check(ticket, Result('working'))
    except GeneratorExit:
        # Client disconnect is not evidence of a broken provider.
        state['availability'].finish_check(ticket, Result('transient_error'))
        raise
    except Exception as exc:
        _failed(state, config, ticket, exc)
        yield b'data: {"error":{"message":"upstream_failed","type":"keeper_error","code":"upstream_failed"}}\n\n'
    finally:
        chunks.close()
    yield b'data: [DONE]\n\n'


def chat(state, body):
    try:
        req = json.loads(body or b'{}')
        if not isinstance(req, dict) or req.get('model') != ALIAS:
            return error(400, 'use_keeper_coder_model')
        if (not isinstance(req.get('messages'), list) or not req['messages']
                or any(not isinstance(m, dict) for m in req['messages'])
                or not isinstance(req.get('stream', False), bool)):
            return error(400, 'invalid_request')
    except (ValueError, TypeError):
        return error(400, 'invalid_json')
    try:
        if not wire.safe_request(req): return error(400, 'unsupported_request_features')
    except (TypeError, KeyError, ValueError):
        return error(400, 'invalid_request')
    if 'availability' not in state: return error(503, 'availability_not_initialized')
    s = state['availability']
    try:
        candidates = aa.rank_models(s.catalog()['models'], state.get('aa_scores', {}))
        candidates = [m for m in candidates if m['working_keys'] and wire.compatible(m['protocol'], req)
                      and any(c['state']=='working' and not c['blocked_reason'] and not c['excluded']
                              and c['retry_at'] <= s.clock() for c in m['connections'])]
    except (TypeError, KeyError, ValueError):
        return error(400, 'invalid_request')
    if not candidates: return error(503, 'no_working_compatible_free_model')
    attempts, excluded = 0, set()
    for model in candidates:
        while attempts < 3:
            if not any(c['model_id'] == model['id'] and c['id'] not in excluded
                       and c['state'] == 'working' and not c['excluded']
                       and not c['blocked_reason'] and c['retry_at'] <= s.clock()
                       for c in s.connections()):
                break
            attempts += 1
            config = state['selector'].select(model['id'], exclude=excluded, max_attempts=1)
            if 'error' in config: break
            excluded.add(config['connection_id'])
            try:
                payload = wire.prepare(config, req)
            except (TypeError, KeyError, ValueError):
                return error(400, 'unsupported_request_features')
            ticket = s.begin_check(config['connection_id'])
            if ticket is None: continue
            try:
                if req.get('stream'):
                    events = state.get('stream_transport', stream_request)(config, payload)
                    chunks = _validated_chunks(events, config)
                    try:
                        first = next(chunks)
                        _safe_doc(first, config)
                    except BaseException:
                        chunks.close()
                        raise
                    return 200, _stream_body(first, chunks, state, config, ticket), [
                        ('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-store, private'),
                        ('X-Accel-Buffering', 'no')]
                res = state.get('inference_transport', request)('POST', config['endpoint'], config['headers'], payload)
                if res.status != 200: raise classify(res.status, res.headers, s.clock())
                doc = wire.normalize(res.json(), config)
                if not _usable(doc): raise UpstreamFailure('invalid_response')
                raw = _safe_doc(doc, config)
                s.finish_check(ticket, Result('working'))
                return 200, raw, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store, private')]
            except Exception as exc:
                _failed(state, config, ticket, exc)
    return error(503, 'no_working_compatible_free_model')
