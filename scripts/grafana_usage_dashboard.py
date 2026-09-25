#!/usr/bin/env python3
"""Generate the Keeper LLM usage & cost dashboard + alert rules (Grafana JSON).

Source of truth for grafana/keeper-usage-dashboard.json and
grafana/keeper-usage-alerts.json. Metrics come from keeper/usage_metrics.py
(computed from SQLite at scrape time); drilldown from Loki `event=llm_usage`
lines and Tempo `keeper.request` spans.

  python3 scripts/grafana_usage_dashboard.py            # write JSON
  python3 scripts/grafana_usage_dashboard.py --check    # validate only
Push: scripts/grafana-push.sh (gcx, service-account token).
"""
import json
import pathlib
import sys

PROM = {'type': 'prometheus', 'uid': 'grafanacloud-prom'}
LOKI = {'type': 'loki', 'uid': 'grafanacloud-logs'}
TEMPO = {'type': 'tempo', 'uid': 'grafanacloud-traces'}
F = 'consumer=~"$consumer",provider=~"$provider",model=~"$model",tier=~"$tier"'
ROOT = pathlib.Path(__file__).resolve().parents[1] / 'grafana'


class Board:
    def __init__(self):
        self.panels, self.y, self.next_id = [], 0, 1

    def row(self, title):
        self.panels.append({'type': 'row', 'title': title, 'id': self._id(), 'collapsed': False,
                            'gridPos': {'x': 0, 'y': self.y, 'w': 24, 'h': 1}, 'panels': []})
        self.y += 1

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    def line(self, specs, h):
        """specs: [(width, panel)] laid out left to right on one line."""
        x = 0
        for w, p in specs:
            p['id'] = self._id()
            p['gridPos'] = {'x': x, 'y': self.y, 'w': w, 'h': h}
            self.panels.append(p)
            x += w
        assert x <= 24, 'row overflow'
        self.y += h


def prom(expr, legend='', instant=False, ref='A', fmt=None):
    t = {'refId': ref, 'datasource': PROM, 'expr': expr, 'legendFormat': legend,
         'range': not instant, 'instant': instant}
    if fmt:
        t['format'] = fmt
    return t


def stat(title, expr, unit='short', decimals=None, desc='', thresholds=None, color_mode='value'):
    p = {'type': 'stat', 'title': title, 'description': desc, 'datasource': PROM,
         'targets': [prom(expr, instant=True)],
         'options': {'reduceOptions': {'calcs': ['lastNotNull'], 'values': False},
                     'colorMode': color_mode, 'graphMode': 'none', 'textMode': 'value'},
         'fieldConfig': {'defaults': {'unit': unit, 'thresholds': thresholds or {
             'mode': 'absolute', 'steps': [{'color': 'text', 'value': None}]}}, 'overrides': []}}
    if decimals is not None:
        p['fieldConfig']['defaults']['decimals'] = decimals
    return p


def ts(title, targets, unit='short', stack=False, desc='', bars=False):
    return {'type': 'timeseries', 'title': title, 'description': desc, 'datasource': PROM,
            'targets': targets,
            'fieldConfig': {'defaults': {'unit': unit, 'custom': {
                'drawStyle': 'bars' if bars else 'line', 'fillOpacity': 60 if bars else 15,
                'stacking': {'mode': 'normal' if stack else 'none'}, 'lineWidth': 1,
                'showPoints': 'never'}}, 'overrides': []},
            'options': {'legend': {'displayMode': 'table', 'placement': 'right',
                                   'calcs': ['sum'] if bars else ['lastNotNull', 'max']},
                        'tooltip': {'mode': 'multi', 'sort': 'desc'}}}


def table(title, queries, rename, desc='', units=None, sort=None):
    """queries: [(ref, expr)] instant tables merged on shared labels."""
    overrides = [{'matcher': {'id': 'byName', 'options': col},
                  'properties': [{'id': 'unit', 'value': unit}]} for col, unit in (units or {}).items()]
    # increase() extrapolates; counts read as whole numbers, money keeps decimals.
    overrides += [{'matcher': {'id': 'byName', 'options': col},
                   'properties': [{'id': 'decimals', 'value': 0}]}
                  for col in rename.values() if col not in (units or {})]
    return {'type': 'table', 'title': title, 'description': desc, 'datasource': PROM,
            'targets': [prom(e, instant=True, ref=r, fmt='table') for r, e in queries],
            'transformations': [
                {'id': 'merge', 'options': {}},
                {'id': 'organize', 'options': {'excludeByName': {'Time': True}, 'renameByName': rename}}],
            'fieldConfig': {'defaults': {}, 'overrides': overrides},
            'options': {'showHeader': True, 'sortBy': [{'displayName': sort, 'desc': True}] if sort else []}}


def bargauge(title, expr, legend, unit='short', desc=''):
    return {'type': 'bargauge', 'title': title, 'description': desc, 'datasource': PROM,
            'targets': [prom(expr, legend=legend, instant=True)],
            'options': {'orientation': 'horizontal', 'displayMode': 'gradient',
                        'reduceOptions': {'calcs': ['lastNotNull'], 'values': False}, 'showUnfilled': True},
            'fieldConfig': {'defaults': {'unit': unit, 'min': 0}, 'overrides': []}}


def inc(metric, extra='', by=''):
    sel = F + (',' + extra if extra else '')
    group = 'sum by (%s) ' % by if by else 'sum '
    return '%s(increase(%s{%s}[$__range]))' % (group, metric, sel)


def build():
    b = Board()
    b.row('Overview — selected range')
    b.line([
        (4, stat('Requests', inc('keeper_llm_requests_total'), decimals=0)),
        (4, stat('Success rate', '%s / %s' % (inc('keeper_llm_requests_total', 'outcome="ok"'),
                                               inc('keeper_llm_requests_total')), unit='percentunit', decimals=1,
                 thresholds={'mode': 'absolute', 'steps': [{'color': 'red', 'value': None},
                                                           {'color': 'orange', 'value': 0.9},
                                                           {'color': 'green', 'value': 0.98}]})),
        (4, stat('Actual spend', inc('keeper_llm_cost_usd_total', 'basis="actual"'), unit='currencyUSD', decimals=4,
                 desc='Real USD: upstream-reported cost, else tokens x list price on paid routes. Free routes cost 0.')),
        (4, stat('Saved by free routes (shadow)', inc('keeper_llm_cost_usd_total', 'basis="shadow",tier="free"'),
                 unit='currencyUSD', decimals=4,
                 desc="What free-served tokens would cost at the paid sibling's list price, else at the escrowed paid fallback's price.")),
        (4, stat('Tokens', inc('keeper_llm_tokens_total'), unit='short', decimals=0)),
        (4, stat('Paid fallback share', '%s / %s' % (inc('keeper_llm_requests_total', 'outcome="ok",tier="paid"'),
                                                      inc('keeper_llm_requests_total', 'outcome="ok"')),
                 unit='percentunit', decimals=1, desc='Share of served requests that needed the paid fallback.')),
    ], 4)

    b.row('By caller (consumer = Keeper service token)')
    b.line([
        (12, ts('Requests by caller', [prom('sum by (consumer) (increase(keeper_llm_requests_total{%s}[$__interval]))' % F,
                                            '{{consumer}}')], stack=True, bars=True)),
        (12, ts('Spend by caller (actual vs shadow)', [
            prom('sum by (consumer) (increase(keeper_llm_cost_usd_total{%s,basis="actual"}[$__interval]))' % F,
                 '{{consumer}} actual'),
            prom('sum by (consumer) (increase(keeper_llm_cost_usd_total{%s,basis="shadow",tier="free"}[$__interval]))' % F,
                 '{{consumer}} shadow', ref='B')], unit='currencyUSD', bars=True)),
    ], 8)
    b.line([(24, table('Callers — selected range', [
        ('A', inc('keeper_llm_requests_total', by='consumer')),
        ('B', inc('keeper_llm_requests_total', 'outcome="ok"', by='consumer')),
        ('C', inc('keeper_llm_tokens_total', by='consumer')),
        ('D', inc('keeper_llm_cost_usd_total', 'basis="actual"', by='consumer')),
        ('E', inc('keeper_llm_cost_usd_total', 'basis="shadow",tier="free"', by='consumer')),
        ('F', inc('keeper_llm_attempts_total', by='consumer')),
    ], {'Value #A': 'requests', 'Value #B': 'served', 'Value #C': 'tokens', 'Value #D': 'actual $',
        'Value #E': 'saved $ (shadow)', 'Value #F': 'attempts'},
        units={'actual $': 'currencyUSD', 'saved $ (shadow)': 'currencyUSD'}, sort='requests'))], 6)

    b.row('By provider & model')
    b.line([(24, table('Models — selected range', [
        ('A', inc('keeper_llm_requests_total', by='provider, model, tier')),
        ('B', inc('keeper_llm_requests_total', 'outcome="ok"', by='provider, model, tier')),
        ('C', inc('keeper_llm_tokens_total', 'direction="prompt"', by='provider, model, tier')),
        ('D', inc('keeper_llm_tokens_total', 'direction="completion"', by='provider, model, tier')),
        ('E', inc('keeper_llm_cost_usd_total', 'basis="actual"', by='provider, model, tier')),
        ('F', inc('keeper_llm_cost_usd_total', 'basis="shadow"', by='provider, model, tier')),
        ('G', inc('keeper_llm_estimated_tokens_total', by='provider, model, tier')),
    ], {'Value #A': 'requests', 'Value #B': 'served', 'Value #C': 'prompt tok', 'Value #D': 'completion tok',
        'Value #E': 'actual $', 'Value #F': 'shadow $', 'Value #G': 'estimated tok'},
        units={'actual $': 'currencyUSD', 'shadow $': 'currencyUSD'}, sort='requests',
        desc='Estimated tokens: upstream reported no usage (zencli CLI routes), chars/4.'))], 8)
    b.line([
        (12, ts('Served requests by model', [prom(
            'sum by (model) (increase(keeper_llm_requests_total{%s,outcome="ok"}[$__interval]))' % F, '{{model}}')],
            stack=True, bars=True)),
        (12, ts('Tokens by tier', [prom(
            'sum by (tier, direction) (increase(keeper_llm_tokens_total{%s}[$__interval]))' % F,
            '{{tier}} {{direction}}')], stack=True, bars=True)),
    ], 8)

    b.row('By provider key (Bao reference names, never owner emails)')
    b.line([
        (12, bargauge('Served requests per key',
                      'sum by (key, provider) (increase(keeper_llm_key_requests_total{consumer=~"$consumer",'
                      'provider=~"$provider",tier=~"$tier",key=~"$key"}[$__range]))', '{{provider}} · {{key}}')),
        (12, table('Checks per key today (verify spends the daily budget; serve is traffic)', [
            ('A', 'sum by (key, provider) (increase(keeper_checks_total{kind="verify",key=~"$key"}[1d]))'),
            ('B', 'sum by (key, provider) (increase(keeper_checks_total{kind="serve",key=~"$key"}[1d]))'),
            ('C', 'sum by (key, provider) (increase(keeper_checks_total{kind="verify",result!="working",key=~"$key"}[1d]))'),
        ], {'Value #A': 'verify (24h)', 'Value #B': 'serve (24h)', 'Value #C': 'verify failures (24h)'},
            sort='serve (24h)')),
    ], 9)

    b.row('Reliability')
    b.line([
        (8, ts('Outcomes (non-ok)', [prom(
            'sum by (outcome) (increase(keeper_llm_requests_total{%s,outcome!="ok"}[$__interval]))' % F,
            '{{outcome}}')], bars=True, stack=True,
            desc='no_working_compatible_free_model = 503 (clients get Retry-After); upstream_rejected_request = every model rejected the request.')),
        (8, ts('Attempts per request (failover)', [prom(
            'sum(rate(keeper_llm_attempts_total{consumer=~"$consumer",provider=~"$provider",model=~"$model"}[$__rate_interval])) / '
            'sum(rate(keeper_llm_requests_total{%s}[$__rate_interval]))' % F, 'attempts/request')])),
        (8, ts('Latency p50 / p95 by tier', [
            prom('histogram_quantile(0.5, sum by (le, tier) (rate(keeper_llm_latency_ms_bucket{consumer=~"$consumer",tier=~"$tier"}[$__rate_interval])))', 'p50 {{tier}}'),
            prom('histogram_quantile(0.95, sum by (le, tier) (rate(keeper_llm_latency_ms_bucket{consumer=~"$consumer",tier=~"$tier"}[$__rate_interval])))', 'p95 {{tier}}', ref='B')],
            unit='ms')),
    ], 8)
    b.line([
        (12, ts('Connections by state (per model)', [prom(
            'sum by (model, state) (keeper_connections{provider=~"$provider",model=~"$model",state!="working"})',
            '{{model}} {{state}}')], stack=True,
            desc='suspect = excluded pending re-verification; cooldown = short backoff after request failures or 429.')),
        (12, bargauge('Working keys per model (now)', 'sum by (provider, model) (keeper_connections{provider=~"$provider",model=~"$model",state="working"})',
                      '{{provider}} · {{model}}')),
    ], 8)

    b.row('Verification')
    b.line([
        (12, ts('Verification checks by result', [prom(
            'sum by (result) (increase(keeper_checks_total{kind="verify",provider=~"$provider",model=~"$model"}[$__interval]))',
            '{{result}}')], bars=True, stack=True)),
        (6, stat('Verify spend on paid routes (est.)', 'sum(increase(keeper_verify_cost_usd_estimate_total[$__range]))',
                 unit='currencyUSD', decimals=4)),
        (6, stat('Unpriced free tokens', inc('keeper_llm_unpriced_tokens_total'), decimals=0,
                 desc='Free-route tokens with no known sibling or fallback price (shadow cost undercounts by these).')),
    ], 8)

    b.row('Drilldown — requests, logs and traces')
    b.line([(24, {
        'type': 'logs', 'title': 'llm_usage events (one line per request)', 'datasource': LOKI,
        'targets': [{'refId': 'A', 'datasource': LOKI,
                     'expr': '{service="keeper-server"} |= "llm_usage" | json | consumer=~"$consumer" | provider=~"$provider" | model=~"$model" | tier=~"$tier"'}],
        'options': {'showTime': True, 'wrapLogMessage': False, 'prettifyLogMessage': False,
                    'enableLogDetails': True, 'sortOrder': 'Descending', 'dedupStrategy': 'none'}})], 9)
    b.line([(24, {
        'type': 'table', 'title': 'Keeper traces (click trace id → Tempo)', 'datasource': TEMPO,
        'targets': [{'refId': 'A', 'datasource': TEMPO, 'queryType': 'traceql', 'limit': 50, 'tableType': 'traces',
                     'query': '{resource.service.name="keeper" && span.http.route="inference" && span.keeper.consumer=~"${consumer:regex}"}'}],
        'fieldConfig': {'defaults': {}, 'overrides': []}, 'options': {'showHeader': True}})], 9)

    def var(name, query, label):
        return {'name': name, 'label': label, 'type': 'query', 'datasource': PROM,
                'query': {'query': query, 'refId': name}, 'definition': query, 'refresh': 2,
                'includeAll': True, 'allValue': '.*', 'multi': True,
                'current': {'text': 'All', 'value': '$__all'}, 'sort': 1}

    return {
        'uid': 'keeper-usage', 'title': 'Keeper — LLM usage & cost', 'tags': ['keeper', 'llm', 'cost'],
        'timezone': 'browser', 'schemaVersion': 39, 'editable': True, 'refresh': '1m',
        'time': {'from': 'now-24h', 'to': 'now'}, 'graphTooltip': 1,
        'description': 'Who uses Keeper, what served them, tokens, actual and shadow cost. Generated by scripts/grafana_usage_dashboard.py.',
        'templating': {'list': [
            var('consumer', 'label_values(keeper_llm_requests_total, consumer)', 'Caller'),
            var('provider', 'label_values(keeper_llm_requests_total, provider)', 'Provider'),
            var('model', 'label_values(keeper_llm_requests_total{provider=~"$provider"}, model)', 'Model'),
            var('tier', 'label_values(keeper_llm_requests_total, tier)', 'Tier'),
            var('key', 'label_values(keeper_checks_total, key)', 'Key'),
        ]},
        'links': [{'title': 'Keeper routes', 'type': 'link', 'url': '/d/keeper-routes'},
                  {'title': 'Keeper matrix', 'type': 'link', 'url': 'https://keeper.pkubelka.cz/', 'targetBlank': True}],
        'panels': b.panels,
    }


def rule(uid, title, expr, threshold, summary, for_='0s', no_data='OK'):
    return {
        'uid': uid, 'title': title, 'folderUID': 'keeper', 'ruleGroup': 'keeper-usage', 'condition': 'C',
        'for': for_, 'noDataState': no_data, 'execErrState': 'Error',
        'labels': {'service': 'keeper', 'severity': 'page'},
        'annotations': {'summary': summary, 'description': 'Dashboard: /d/keeper-usage'},
        'notification_settings': {'receiver': 'HonzaTraderBot'},
        'data': [
            {'refId': 'A', 'queryType': 'instant', 'relativeTimeRange': {'from': 600, 'to': 0},
             'datasourceUid': 'grafanacloud-prom',
             'model': {'expr': expr, 'instant': True, 'intervalMs': 60000, 'maxDataPoints': 43200, 'refId': 'A'}},
            {'refId': 'B', 'queryType': '', 'relativeTimeRange': {'from': 0, 'to': 0}, 'datasourceUid': '__expr__',
             'model': {'expression': 'A', 'reducer': 'last', 'refId': 'B', 'type': 'reduce'}},
            {'refId': 'C', 'queryType': '', 'relativeTimeRange': {'from': 0, 'to': 0}, 'datasourceUid': '__expr__',
             'model': {'expression': 'B', 'refId': 'C', 'type': 'threshold',
                       'conditions': [{'evaluator': {'params': [threshold], 'type': 'gt'}}]}},
        ]}


def alerts():
    return [
        rule('keeper-paid-spend-day', 'Keeper paid spend over $2 in 24h',
             'sum(increase(keeper_llm_cost_usd_total{basis="actual"}[24h]))', 2,
             'Keeper spent ${{ $values.B.Value | printf "%.2f" }} on paid routes in 24h'),
        # Only models that still serve on other keys (the muse 2/10 pattern):
        # keys a provider denies outright stay suspect by design and are noise.
        rule('keeper-suspect-keys', 'Keeper model has suspect keys for 1h',
             'sum by (provider, model) (keeper_connections{state="suspect"}) and on (provider, model) '
             '(sum by (provider, model) (keeper_connections{state="working"}) > 0)', 0,
             '{{ $labels.provider }}/{{ $labels.model }}: {{ $values.B.Value }} suspect keys for 1h', for_='1h'),
    ]


def validate(board, rules):
    ids, cells = set(), set()
    for p in board['panels']:
        assert p['id'] not in ids, 'duplicate panel id'
        ids.add(p['id'])
        g = p['gridPos']
        for x in range(g['x'], g['x'] + g['w']):
            for y in range(g['y'], g['y'] + g['h']):
                assert (x, y) not in cells, 'overlap at %s,%s (%s)' % (x, y, p['title'])
                cells.add((x, y))
        for t in p.get('targets', []):
            assert t['datasource']['uid'] in ('grafanacloud-prom', 'grafanacloud-logs', 'grafanacloud-traces')
    raw = json.dumps([board, rules])
    for bad in ('glc_', 'eyJ', 'Bearer ', '@gmail'):
        assert bad not in raw, 'secret-looking or personal content: ' + bad
    return True


if __name__ == '__main__':
    board, rules = build(), alerts()
    validate(board, rules)
    if '--check' not in sys.argv:
        (ROOT / 'keeper-usage-dashboard.json').write_text(json.dumps(board, indent=1) + '\n')
        (ROOT / 'keeper-usage-alerts.json').write_text(json.dumps(rules, indent=1) + '\n')
    print('ok panels=%d rules=%d' % (len(board['panels']), len(rules)))
