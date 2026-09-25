"""Per-request usage, cost and caller attribution for the inference alias.

One av_usage row (and one `event=llm_usage` stderr JSON line for Loki) per
chat request: who asked (consumer), what served it (provider/model/tier/key
reference), tokens, actual cost and shadow cost. Metrics are computed from
these rows at scrape time, so they survive restarts and hold no in-memory
high-cardinality state.

Cost basis:
- actual: upstream-reported `usage.cost` when numeric, else tokens x list
  price for paid routes; free routes cost 0.
- shadow: what the same tokens would cost on the model's paid sibling
  (':free' -> base id, 'X Free' -> 'X'), else on the escrowed paid fallback
  (what Keeper would otherwise have spent); None when nothing is priced.
Tokens are estimated (chars/4, flagged) when the upstream reports none
(zencli, translated streams).

Never records prompts, outputs, keys or error bodies: only counts and ids.
"""
import json
import math
import sys
import time

from availability import OPERATOR_PAID

VERIFY_TOKENS = (16, 64)  # inference.verify prompt/max output, for estimates
LATENCY_BUCKETS_MS = (250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, 180000)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _chars(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(len(p.get('text', '')) for p in value if isinstance(p, dict) and isinstance(p.get('text'), str))
    return 0


def estimate_prompt(req):
    chars = sum(_chars(m.get('content')) for m in req.get('messages', []) if isinstance(m, dict))
    for field in ('tools', 'response_format'):
        if req.get(field):
            chars += len(json.dumps(req[field]))
    return math.ceil(chars / 4)


def doc_text_chars(doc):
    chars = 0
    for choice in (doc or {}).get('choices', []):
        msg = choice.get('message') or choice.get('delta') or {}
        chars += _chars(msg.get('content'))
        for call in msg.get('tool_calls') or []:
            chars += len((call.get('function') or {}).get('arguments') or '')
    return chars


def upstream_tokens(usage):
    """(prompt, completion, upstream_cost) from an OpenAI-shaped usage object."""
    if not isinstance(usage, dict):
        return None, None, None
    cost = usage.get('cost')
    cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0 else None
    return _count(usage.get('prompt_tokens')), _count(usage.get('completion_tokens')), cost


def _cross_price(store, provider, model):
    """A direct paid route priced only in an aggregator catalog (openai/gpt-x)."""
    rows = store.rows('''SELECT price_in,price_out FROM av_models WHERE model=? AND price_in IS NOT NULL
        AND price_out IS NOT NULL ORDER BY checked_at DESC LIMIT 1''', (provider + '/' + model,))
    return (rows[0]['price_in'], rows[0]['price_out']) if rows else (None, None)


def model_prices(store, model_id):
    """(price_in, price_out, shadow_in, shadow_out) USD per token."""
    rows = store.rows('SELECT * FROM av_models WHERE id=?', (model_id,))
    if not rows:
        return None, None, None, None
    m = rows[0]
    price_in, price_out = m['price_in'], m['price_out']
    if price_in is None and m['eligibility'] == 'paid':
        price_in, price_out = _cross_price(store, m['provider'], m['model'])
    return price_in, price_out, m['shadow_in'], m['shadow_out']


def fallback_prices(store):
    for m in store.rows("SELECT * FROM av_models WHERE provenance=? AND present=1", (OPERATOR_PAID,)):
        price_in, price_out = m['price_in'], m['price_out']
        if price_in is None:
            price_in, price_out = _cross_price(store, m['provider'], m['model'])
        if price_in is not None and price_out is not None:
            return price_in, price_out
    return None, None


def costs(store, model_id, tier, prompt, completion, upstream_cost=None):
    """(actual_usd, shadow_usd or None)."""
    price_in, price_out, shadow_in, shadow_out = model_prices(store, model_id)
    if tier == 'paid':
        if upstream_cost is not None:
            actual = upstream_cost
        elif price_in is not None and price_out is not None:
            actual = prompt * price_in + completion * price_out
        else:
            actual = 0.0
        return actual, actual
    actual = upstream_cost or 0.0
    if shadow_in is None or shadow_out is None:
        shadow_in, shadow_out = fallback_prices(store)
    shadow = (prompt * shadow_in + completion * shadow_out
              if shadow_in is not None and shadow_out is not None else None)
    return actual, shadow


def credential_ref(store, connection_id):
    rows = store.rows('''SELECT k.reference FROM av_connections c JOIN av_credentials k ON k.id=c.credential_id
        WHERE c.id=?''', (connection_id,))
    return rows[0]['reference'] if rows else ''


def error_code(raw):
    try:
        err = json.loads(raw).get('error') or {}
        return str(err.get('code') or 'error')[:64]
    except (ValueError, TypeError, AttributeError):
        return 'error'


def record(state, ctx, outcome, prompt=0, completion=0, estimated=0, upstream_cost=None):
    """Persist one request row and emit its Loki line. Never raises."""
    try:
        s = state['availability']
        model, config = ctx.get('model') or {}, ctx.get('config') or {}
        tier = ('paid' if model.get('eligibility') == 'paid' else 'free') if model else ''
        actual, shadow = (costs(s.store, model['id'], tier, prompt, completion, upstream_cost)
                          if model and outcome == 'ok' else (0.0, None))
        now = s.clock()
        row = {
            'req_id': ctx.get('req_id', ''), 'ts': now, 'consumer': ctx.get('consumer', 'unknown'),
            'model_id': model.get('id'), 'provider': model.get('provider', ''),
            'model': model.get('model', ''), 'protocol': model.get('protocol', ''), 'tier': tier,
            'credential_ref': credential_ref(s.store, config['connection_id']) if config.get('connection_id') else '',
            'attempts': ctx.get('attempts', 0), 'outcome': outcome,
            'prompt_tokens': int(prompt or 0), 'completion_tokens': int(completion or 0),
            'tokens_estimated': int(bool(estimated)), 'cost_usd': float(actual),
            'shadow_cost_usd': shadow, 'stream': int(bool(ctx.get('stream'))),
            'latency_ms': _elapsed_ms(ctx),
        }
        with s.store.transaction() as db:
            cols = ','.join(row)
            db.execute('INSERT INTO av_usage(%s) VALUES (%s)' % (cols, ','.join('?' * len(row))), tuple(row.values()))
        line = {'event': 'llm_usage', **{k: v for k, v in row.items() if k not in ('ts', 'model_id')},
                'trace': ctx.get('trace_id', '')}
        (ctx.get('log') or sys.stderr.write)(json.dumps(line, sort_keys=True) + '\n')
        ctx['recorded'] = row
    except Exception:
        pass


def _elapsed_ms(ctx):
    t0 = ctx.get('t0')
    return max(0, int((time.time() - t0) * 1000)) if isinstance(t0, (int, float)) else 0


def record_response(state, ctx, code, raw):
    """Non-streaming exit of chat(): success with tokens, or the error code."""
    if code == 200 and ctx.get('doc') is not None:
        doc = ctx['doc']
        prompt, completion, cost = upstream_tokens(doc.get('usage'))
        estimated = 0
        if not prompt and not completion:
            prompt = estimate_prompt(ctx.get('req') or {})
            completion = math.ceil(doc_text_chars(doc) / 4)
            estimated = 1
        record(state, ctx, 'ok', prompt or 0, completion or 0, estimated, cost)
    else:
        record(state, ctx, error_code(raw))


class StreamMeter:
    """Accumulates a streamed response's usage (or an estimate)."""

    def __init__(self, ctx):
        self.ctx, self.chars, self.usage = ctx, 0, None

    def see(self, chunk):
        if isinstance(chunk, dict):
            self.chars += doc_text_chars(chunk)
            if isinstance(chunk.get('usage'), dict):
                self.usage = chunk['usage']

    def finish(self, state, outcome):
        prompt, completion, cost = upstream_tokens(self.usage)
        estimated = 0
        if not prompt and not completion:
            prompt = estimate_prompt(self.ctx.get('req') or {})
            completion = math.ceil(self.chars / 4)
            estimated = 1
        record(state, self.ctx, outcome, prompt or 0, completion or 0, estimated, cost)
