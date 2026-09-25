"""Prometheus lines for LLM usage, cost, verification and connection health.

Computed from SQLite (av_usage, av_checks, connections) at scrape time:
restart-safe counters, no in-process high-cardinality state. Labels are
bounded names only: consumer (configured), provider/model (catalog), tier,
outcome codes, Bao key reference names. Never owner emails or secrets.
"""
import re

from availability import spendable
from usage import LATENCY_BUCKETS_MS, VERIFY_TOKENS, model_prices


def esc(value):
    return str(value if value is not None else '').replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')[:120]


def key_label(reference):
    """'OPENCODE_ZEN_RETIRED_2@bao:2' -> 'OPENCODE_ZEN_RETIRED_2' (stable across rotations)."""
    return re.sub(r'@bao:\d+$', '', reference or '')


def labels(**kv):
    return ','.join('%s="%s"' % (k, esc(v)) for k, v in kv.items())


def _family(out, name, kind, help_text):
    out.append('# HELP %s %s' % (name, help_text))
    out.append('# TYPE %s %s' % (name, kind))


def lines(state):
    s = state.get('availability')
    if s is None:
        return []
    out = []
    rows = s.store.rows('''SELECT consumer, provider, model, tier, outcome,
        COUNT(*) AS n, SUM(prompt_tokens) AS pin, SUM(completion_tokens) AS pout,
        SUM(CASE WHEN tokens_estimated=1 THEN prompt_tokens+completion_tokens ELSE 0 END) AS est,
        SUM(cost_usd) AS cost, SUM(COALESCE(shadow_cost_usd,0)) AS shadow,
        SUM(CASE WHEN shadow_cost_usd IS NULL AND outcome='ok' AND tier='free'
            THEN prompt_tokens+completion_tokens ELSE 0 END) AS unpriced,
        SUM(attempts) AS attempts
        FROM av_usage GROUP BY consumer, provider, model, tier, outcome''')
    _family(out, 'keeper_llm_requests_total', 'counter', 'Inference requests by caller, serving route and outcome.')
    for r in rows:
        out.append('keeper_llm_requests_total{%s} %d' % (labels(
            consumer=r['consumer'], provider=r['provider'], model=r['model'], tier=r['tier'],
            outcome=r['outcome']), r['n']))
    _family(out, 'keeper_llm_attempts_total', 'counter', 'Connection attempts spent (failover visibility).')
    for r in rows:
        out.append('keeper_llm_attempts_total{%s} %d' % (labels(
            consumer=r['consumer'], provider=r['provider'], model=r['model'], outcome=r['outcome']),
            r['attempts'] or 0))
    ok = [r for r in rows if r['outcome'] in ('ok', 'client_disconnect', 'upstream_failed')]
    _family(out, 'keeper_llm_tokens_total', 'counter', 'Tokens by caller and route (direction=prompt|completion).')
    _family(out, 'keeper_llm_estimated_tokens_total', 'counter', 'Tokens estimated (chars/4) because upstream reported none.')
    _family(out, 'keeper_llm_cost_usd_total', 'counter', 'USD by caller and route; basis=actual (spent) or shadow (list price without free tier).')
    _family(out, 'keeper_llm_unpriced_tokens_total', 'counter', 'Free-route tokens with no known shadow price.')
    for r in ok:
        base = dict(consumer=r['consumer'], provider=r['provider'], model=r['model'], tier=r['tier'])
        out.append('keeper_llm_tokens_total{%s} %d' % (labels(**base, direction='prompt'), r['pin'] or 0))
        out.append('keeper_llm_tokens_total{%s} %d' % (labels(**base, direction='completion'), r['pout'] or 0))
        out.append('keeper_llm_estimated_tokens_total{%s} %d' % (labels(**base), r['est'] or 0))
        out.append('keeper_llm_cost_usd_total{%s} %.8f' % (labels(**base, basis='actual'), r['cost'] or 0))
        out.append('keeper_llm_cost_usd_total{%s} %.8f' % (labels(**base, basis='shadow'), r['shadow'] or 0))
        out.append('keeper_llm_unpriced_tokens_total{%s} %d' % (labels(**base), r['unpriced'] or 0))

    _family(out, 'keeper_llm_key_requests_total', 'counter', 'Served requests per provider key (Bao reference name).')
    for r in s.store.rows('''SELECT credential_ref, provider, tier, consumer, COUNT(*) AS n,
            SUM(cost_usd) AS cost FROM av_usage WHERE credential_ref!='' AND outcome='ok'
            GROUP BY credential_ref, provider, tier, consumer'''):
        out.append('keeper_llm_key_requests_total{%s} %d' % (labels(
            key=key_label(r['credential_ref']), provider=r['provider'], tier=r['tier'],
            consumer=r['consumer']), r['n']))

    _family(out, 'keeper_llm_latency_ms', 'histogram', 'End-to-end inference latency (ms) by caller and tier.')
    select = ', '.join('SUM(CASE WHEN latency_ms<=%d THEN 1 ELSE 0 END) AS b%d' % (b, b) for b in LATENCY_BUCKETS_MS)
    for r in s.store.rows('SELECT consumer, tier, COUNT(*) AS n, SUM(latency_ms) AS total, %s '
                          'FROM av_usage GROUP BY consumer, tier' % select):
        base = dict(consumer=r['consumer'], tier=r['tier'])
        for b in LATENCY_BUCKETS_MS:
            out.append('keeper_llm_latency_ms_bucket{%s} %d' % (labels(**base, le=b), r['b%d' % b]))
        out.append('keeper_llm_latency_ms_bucket{%s} %d' % (labels(**base, le='+Inf'), r['n']))
        out.append('keeper_llm_latency_ms_sum{%s} %d' % (labels(**base), r['total'] or 0))
        out.append('keeper_llm_latency_ms_count{%s} %d' % (labels(**base), r['n']))

    _family(out, 'keeper_checks_total', 'counter', 'Finished checks by kind (verify spends the daily budget; serve is traffic).')
    _family(out, 'keeper_verify_cost_usd_estimate_total', 'counter', 'Estimated USD spent verifying paid routes.')
    for r in s.store.rows('''SELECT h.kind, h.state, m.provider, m.model, m.id AS model_id, m.eligibility,
            k.reference, COUNT(*) AS n FROM av_checks h JOIN av_connections c ON c.id=h.connection_id
            JOIN av_models m ON m.id=c.model_id JOIN av_credentials k ON k.id=c.credential_id
            WHERE h.finished_at IS NOT NULL GROUP BY h.kind, h.state, m.id, k.reference'''):
        tier = 'paid' if r['eligibility'] == 'paid' else 'free'
        out.append('keeper_checks_total{%s} %d' % (labels(
            kind=r['kind'], result=r['state'] or '', provider=r['provider'], model=r['model'],
            tier=tier, key=key_label(r['reference'])), r['n']))
        if r['kind'] == 'verify' and tier == 'paid':
            price_in, price_out, _, _ = model_prices(s.store, r['model_id'])
            if price_in is not None and price_out is not None:
                out.append('keeper_verify_cost_usd_estimate_total{%s} %.8f' % (labels(
                    provider=r['provider'], model=r['model'], key=key_label(r['reference'])),
                    r['n'] * (VERIFY_TOKENS[0] * price_in + VERIFY_TOKENS[1] * price_out)))

    _family(out, 'keeper_connections', 'gauge', 'Selectable connections by display state (working/suspect/cooldown/stale/...).')
    counts = {}
    for c in s.connections():
        if c['blocked_reason'] and not (c['blocked_reason'] == 'paid' and spendable(c)):
            continue
        key = (c['provider'], c['model'], c['protocol'], c['state'])
        counts[key] = counts.get(key, 0) + 1
    for (provider, model, protocol, st), n in sorted(counts.items()):
        out.append('keeper_connections{%s} %d' % (labels(
            provider=provider, model=model, protocol=protocol, state=st), n))
    return out
