"""Inference-only service principal: ranked free alias, no Keeper usage quotas.

Provider failures are precise observations + feedback. Up to FREE_ATTEMPTS
free and then PAID_ATTEMPTS escrowed-paid connection attempts per request
(so free failures never starve the paid fallback), bounded by a wall-clock
deadline. Same-model keys precede lower-ranked model routes; an upstream
request rejection (400/422) moves on to the next model; never fail over
after the first streaming byte. On the text-only CLI (zencli) route,
structured output/tools are emulated (zencli_structured); a model that cannot
produce the requested structure after one repair turn is skipped without
key penalty.
HTTP response/error bodies never become diagnostics, logs or feedback text.
"""
import json
import math
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

import aa
from api_v2 import response
from availability import Result, spendable
from inference import NoRedirect, request, retry_after
import service_wire as wire
from zencli_bridge import BridgeUnavailable
import zencli_structured as structured
import usage

ALIAS = 'keeper-coder'
FREE_ATTEMPTS = 3
PAID_ATTEMPTS = 2
# Loopback callers (Cognee) are not behind Cloudflare's ~100s cap.
REQUEST_DEADLINE = float(os.environ.get('KEEPER_REQUEST_DEADLINE', '180'))
UPSTREAM_TIMEOUT = 90
# A structured-emulation repair turn is only worth it if a slow CLI answer
# (bridge timeout 110s) still leaves the paid fallback room in the deadline.
REPAIR_MIN_REMAINING = 60
# Harmless client bookkeeping (litellm/OpenAI SDK). Dropped, never forwarded:
# `store` would persist completions upstream; `service_tier` can change price.
DROPPED_EXTRAS = ('metadata', 'store', 'service_tier')


class UpstreamFailure(Exception):
    def __init__(self, state='transient_error', delay=0):
        self.result = Result(state, delay)


class UpstreamRequestError(Exception):
    """A rejected request is not evidence against a provider credential."""


def error(code, name, headers=()):
    code, raw, base = response(code, {'error': {'message': name, 'type': 'keeper_error', 'code': name}})
    return code, raw, base + list(headers)


def models():
    return response(200, {'object':'list','data':[{'id':ALIAS,'object':'model','owned_by':'keeper',
        'description':'Highest Coding Index verified working compatible free route; unscored fallback when unmatched.'}]})


def classify(status, headers, now):
    if status in (400, 422): return UpstreamRequestError()
    if status == 429: return UpstreamFailure('rate_limited', retry_after(headers, now))
    if status in (401, 402, 403): return UpstreamFailure('access_denied')
    # Same classes as inference.verify: timeouts are transient, not bad output.
    return UpstreamFailure('transient_error' if status >= 500 or status in (408, 425) else 'invalid_response')


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
    if any(secret and secret in raw for secret in config.get('secret_values', [config['api_key']])):
        raise UpstreamFailure('invalid_response')
    return raw.encode()


def _string_fragments(value, path=()):
    """Stable logical channels, including interleaved choice/tool indexes."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _string_fragments(child, path + (key,))
    elif isinstance(value, list):
        for position, child in enumerate(value):
            index = child.get('index', position) if isinstance(child, dict) else position
            if type(index) is not int: index = position
            yield from _string_fragments(child, path + (index,))


def _secret_guard(parts, config):
    """Hold incomplete credential prefixes BEFORE releasing their SSE events.

    Keep only suffixes that could complete a secret in a later logical fragment.
    Other events stream immediately. Ambiguous interleaved streams have a bounded
    pending window and fail closed rather than grow memory or expose prefixes.
    """
    secrets = [s for s in config.get('secret_values', [config['api_key']]) if s]
    longest = max((len(s) for s in secrets), default=1)
    tails, pending, size, closed = {}, [], 0, set()
    for part in parts:
        encoded = _safe_doc(part, config)
        fragments = []
        for choice in part.get('choices', []):
            index = choice.get('index', 0)
            delta = choice.get('delta', {})
            if index in closed and delta:
                raise UpstreamFailure('invalid_response')
            # Role, IDs and function names are atomic metadata, not text
            # deltas. Treating repeated model names as text can buffer every
            # ':free' stream when a JWT happens to start with 'e'.
            for field, value in delta.items():
                if field not in ('role', 'tool_calls'):
                    fragments.extend(_string_fragments(value, (index, field)))
            for call in delta.get('tool_calls', []):
                arguments = call.get('function', {}).get('arguments')
                if isinstance(arguments, str):
                    fragments.append(((index, 'tool', call.get('index', 0)), arguments))
        for channel, text in fragments:
            combined = tails.get(channel, '') + text
            if any(secret in combined for secret in secrets):
                raise UpstreamFailure('invalid_response')
            suffix = next((combined[-n:] for n in range(min(len(combined), longest - 1), 0, -1)
                           if any(secret.startswith(combined[-n:]) for secret in secrets)), '')
            if suffix: tails[channel] = suffix
            else: tails.pop(channel, None)
        for choice in part.get('choices', []):
            if choice.get('finish_reason') is not None:
                index = choice.get('index', 0)
                closed.add(index)
                # The choice is complete; later deltas are rejected above.
                tails = {channel: value for channel, value in tails.items() if channel[0] != index}
        pending.append(part)
        size += len(encoded)
        if len(pending) > 256 or size > 1024 * 1024:
            raise UpstreamFailure('invalid_response')
        if not tails:
            yield from pending
            pending.clear()
            size = 0
    # Only a successful upstream terminal permits incomplete prefixes to flush.
    yield from pending


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


def _inference_request(state, model, url, headers, payload, timeout=UPSTREAM_TIMEOUT):
    transport = state.get('inference_transport')
    if transport is not None:
        return transport('POST', url, headers, payload)
    # Verification probes stay short (25s). Real inference is large
    # structured extraction (Cognee); the observed 26s Keeper 503s were a 25s
    # read deadline, not provider failures. Bounded by the request deadline.
    return request('POST', url, headers, payload, timeout=timeout)


def _token_field_fallback(config, payload, send):
    """Newer OpenAI models (o-series, gpt-6) reject legacy max_tokens with a
    400. Retry once on the same connection with max_completion_tokens, like
    inference.verify does; a rejected field is not credential evidence."""
    try:
        return send(payload)
    except UpstreamRequestError:
        if config['protocol'] != 'openai' or 'max_tokens' not in payload:
            raise
        alt = {k: v for k, v in payload.items() if k != 'max_tokens'}
        alt['max_completion_tokens'] = payload['max_tokens']
        return send(alt)


def _zencli_answer(s, ctx, config, req, payload, send, deadline):
    """CLI text -> OpenAI doc; structured requests are emulated (plan ->
    infer -> finish), with one repair turn on the same connection.

    An empty CLI answer stays provider evidence (UpstreamFailure). A reply
    that is not the requested structure after repair raises Unsatisfied.
    """
    raw = wire.normalize(send(payload).json(), config)
    sp = structured.spec(req)
    if sp is None:
        return raw
    for stage in ('first', 'repair'):
        text = structured.reply_text(raw)
        if not text or not text.strip():
            raise UpstreamFailure('invalid_response')
        try:
            doc = structured.finish(text, sp, config['model'], raw.get('usage'))
            doc.update({k: raw[k] for k in ('id', 'created') if k in raw})
            return doc
        except structured.Invalid as exc:
            retry = (structured.repair(payload, text, str(exc))
                     if stage == 'first' and deadline - s.clock() >= REPAIR_MIN_REMAINING else None)
            _emulation_log(ctx, config, stage, 'repair' if retry else 'unsatisfied')
            if retry is None:
                raise structured.Unsatisfied() from None
        raw = wire.normalize(send(retry).json(), config)
    raise structured.Unsatisfied()


def _emulation_log(ctx, config, stage, action):
    """Counts/ids only: never prompt, answer or validation text."""
    line = {'event': 'zencli_structured', 'stage': stage, 'action': action,
            'model': config.get('model', ''), 'req_id': ctx.get('req_id', ''),
            'trace': ctx.get('trace_id', '')}
    try:
        (ctx.get('log') or sys.stderr.write)(json.dumps(line, sort_keys=True) + '\n')
    except Exception:
        pass


def _retry_after(s):
    """Seconds until the soonest cooled-down connection is eligible (15-300)."""
    now = s.clock()
    soon = min((c['retry_at'] for c in s.connections() if c['retry_at'] > now), default=now + 15)
    return str(max(15, min(300, math.ceil(soon - now))))


def _served_headers(config, model):
    return [('X-Keeper-Model', str(config.get('model', ''))),
            ('X-Keeper-Provider', str(config.get('provider', model.get('provider', '')))),
            ('X-Keeper-Tier', 'paid' if model.get('eligibility') == 'paid' else 'free')]


def _failed(state, config, ticket, failure):
    result = failure.result if isinstance(failure, UpstreamFailure) else Result('transient_error')
    state['availability'].finish_request_failure(ticket, result)


def _validated_chunks(events, config):
    """Hold metadata until usable text/tool output; empty streams prove nothing."""
    prefix, tools, meaningful = [], {}, False
    try:
        for part in _secret_guard(wire.stream_chunks(events, config), config):
            _safe_doc(part, config)
            for choice in part.get('choices', []):
                delta = choice.get('delta', {})
                if isinstance(delta.get('content'), str) and delta['content'].strip():
                    meaningful = True
                for call in delta.get('tool_calls', []):
                    key = (choice.get('index', 0), call.get('index', 0))
                    tool = tools.setdefault(key, {'id':'', 'name':'', 'arguments':''})
                    for field, value in (('id', call.get('id', '')),
                                         ('name', call.get('function', {}).get('name', ''))):
                        if value:
                            if tool[field] and tool[field] != value:
                                raise UpstreamFailure('invalid_response')
                            tool[field] = value
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


def _stream_body(first, chunks, state, config, ticket, ctx=None):
    meter = usage.StreamMeter(ctx if ctx is not None else {})
    try:
        meter.see(first)
        yield b'data: ' + _safe_doc(first, config) + b'\n\n'
        for chunk in chunks:
            meter.see(chunk)
            yield b'data: ' + _safe_doc(chunk, config) + b'\n\n'
        state['availability'].finish_check(ticket, Result('working'))
        meter.finish(state, 'ok')
    except GeneratorExit:
        # Client disconnect is not evidence of a broken provider.
        state['availability'].discard_request_check(ticket)
        meter.finish(state, 'client_disconnect')
        raise
    except Exception as exc:
        _failed(state, config, ticket, exc)
        meter.finish(state, 'upstream_failed')
        yield b'data: {"error":{"message":"upstream_failed","type":"keeper_error","code":"upstream_failed"}}\n\n'
    finally:
        chunks.close()
    yield b'data: [DONE]\n\n'


def chat(state, body, allow_exact=False, ctx=None):
    """OpenAI chat for the alias; ctx carries caller attribution (consumer,
    req_id, trace_id, t0) and receives what served the request."""
    ctx = dict(ctx or {})
    ctx.setdefault('consumer', 'admin' if allow_exact else 'legacy')
    ctx.setdefault('req_id', secrets.token_hex(8))
    ctx.setdefault('t0', time.time())
    code, raw, headers = _chat(state, body, allow_exact, ctx)
    if not ctx.get('streaming') and 'availability' in state:
        usage.record_response(state, ctx, code, raw)
    return code, raw, headers


def _chat(state, body, allow_exact, ctx):
    try:
        req = json.loads(body or b'{}')
        if isinstance(req, dict):
            for field in DROPPED_EXTRAS:
                req.pop(field, None)
        if (not isinstance(req, dict) or not isinstance(req.get('model'), str)
                or (req['model'] != ALIAS and not allow_exact)):
            return error(400, 'use_keeper_coder_model')
        if (not isinstance(req.get('messages'), list) or not req['messages']
                or any(not isinstance(m, dict) for m in req['messages'])
                or not isinstance(req.get('stream', False), bool)):
            return error(400, 'invalid_request')
    except (ValueError, TypeError):
        return error(400, 'invalid_json')
    try:
        if not wire.valid_values(req): return error(400, 'invalid_request')
        if not wire.safe_request(req): return error(400, 'unsupported_request_features')
    except (TypeError, KeyError, ValueError):
        return error(400, 'invalid_request')
    if 'availability' not in state: return error(503, 'availability_not_initialized')
    s = state['availability']
    ctx['req'], ctx['stream'] = req, bool(req.get('stream'))
    try:
        candidates = aa.rank_models(s.catalog()['models'], state.get('aa_scores', {}))
        if req['model'] != ALIAS:
            candidates = [m for m in candidates if req['model'] in (m['id'], m['model'])]
            if len(candidates) > 1:
                return error(400, 'ambiguous_model_use_catalog_id')
        candidates = [m for m in candidates if m['working_keys'] and wire.compatible(m['protocol'], req)
                      and any(c['state']=='working' and (not c['blocked_reason'] or (
                          c['blocked_reason'] == 'paid' and spendable(c))) and not c['excluded']
                          and c['retry_at'] <= s.clock() for c in m['connections'])]
        # Spend order: free first, unknown next, escrowed-paid last (fallback).
        # Stable sort keeps AA rank order within each tier.
        candidates = sorted(candidates, key=lambda m: (
            0 if m.get('eligibility') == 'free' else 2 if m.get('eligibility') == 'paid' else 1))
    except (TypeError, KeyError, ValueError):
        return error(400, 'invalid_request')
    if not candidates:
        return error(503, 'no_working_compatible_free_model', [('Retry-After', _retry_after(s))])
    deadline = s.clock() + REQUEST_DEADLINE
    used = {'free': 0, 'paid': 0}
    excluded, bridge_down, failures = set(), False, 0
    rejected_free, rejected = set(), set()
    for model in candidates:
        tier = 'paid' if model.get('eligibility') == 'paid' else 'free'
        if bridge_down and model['protocol'] == 'zencli':
            continue
        # Two distinct free models rejecting the request means the request
        # is the problem: don't pay the fallback to confirm it.
        if tier == 'paid' and len(rejected_free) >= 2:
            continue
        limit = PAID_ATTEMPTS if tier == 'paid' else FREE_ATTEMPTS
        while used[tier] < limit and s.clock() < deadline:
            if not any(c['model_id'] == model['id'] and c['id'] not in excluded
                       and c['state'] == 'working' and not c['excluded']
                       and (not c['blocked_reason'] or (
                           c['blocked_reason'] == 'paid' and spendable(c)))
                       and c['retry_at'] <= s.clock()
                       for c in s.connections()):
                break
            used[tier] += 1
            ctx['attempts'], ctx['model'] = used['free'] + used['paid'], model
            config = state['selector'].select(model['id'], exclude=excluded, max_attempts=1, export=False)
            if 'error' in config:
                if config['error'] == 'verification_pending':
                    break
                # A failed revalidation superseded that key's old success.
                # Re-read remaining working keys for this same ranked model.
                continue
            excluded.add(config['connection_id'])
            ctx['config'] = config
            try:
                payload = wire.prepare(config, req)
            except (TypeError, KeyError, ValueError):
                return error(400, 'unsupported_request_features')
            ticket = s.begin_check(config['connection_id'], kind='serve')
            if ticket is None: continue
            served = _served_headers(config, model)
            try:
                if req.get('stream'):
                    def open_stream(body):
                        events = state.get('stream_transport', stream_request)(config, body)
                        chunks = _validated_chunks(events, config)
                        try:
                            first = next(chunks)
                            _safe_doc(first, config)
                        except BaseException:
                            chunks.close()
                            raise
                        return first, chunks
                    first, chunks = _token_field_fallback(config, payload, open_stream)
                    ctx['streaming'] = True
                    return 200, _stream_body(first, chunks, state, config, ticket, ctx), [
                        ('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-store, private'),
                        ('X-Accel-Buffering', 'no')] + served
                timeout = max(5, min(UPSTREAM_TIMEOUT, deadline - s.clock()))

                def send(body):
                    res = (state['zencli'].infer(config, body) if config['protocol'] == 'zencli' else
                           _inference_request(state, model, config['endpoint'], config['headers'], body, timeout))
                    if res.status != 200: raise classify(res.status, res.headers, s.clock())
                    return res
                if config['protocol'] == 'zencli':
                    doc = _zencli_answer(s, ctx, config, req, payload, send, deadline)
                else:
                    res = _token_field_fallback(config, payload, send)
                    doc = wire.normalize(res.json(), config)
                if not _usable(doc): raise UpstreamFailure('invalid_response')
                raw = _safe_doc(doc, config)
                s.finish_check(ticket, Result('working'))
                ctx['doc'] = doc
                return 200, raw, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store, private')] + served
            except UpstreamRequestError:
                # Not credential evidence. Another model may accept it.
                s.discard_request_check(ticket)
                rejected.add(model['id'])
                if tier == 'free':
                    rejected_free.add(model['id'])
                break
            except structured.Unsatisfied:
                # This model cannot produce the requested structure: neither
                # credential evidence nor a malformed client request. Next
                # model; the paid fallback stays available.
                s.discard_request_check(ticket)
                break
            except BridgeUnavailable:
                # The shared CLI sidecar is down: not evidence about this key
                # or model, and every other zencli candidate would fail too.
                s.discard_request_check(ticket)
                bridge_down = True
                break
            except Exception as exc:
                failures += 1
                _failed(state, config, ticket, exc)
    if rejected and not failures:
        return error(400, 'upstream_rejected_request')
    return error(503, 'no_working_compatible_free_model', [('Retry-After', _retry_after(s))])
