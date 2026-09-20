"""Pricing-aware discovery, separate from legacy inventory's ID-only display.

Sources: OpenRouter/Kilo priced catalogs; Zen's official endpoint + pricing
MDX tables (joined by exact display name, not a '-free' guess); Gemini's
standard free-tier pricing tables + generateContent inventory. Account-tier
proof is independently required before recurring-allowance inference.
"""
from decimal import Decimal, InvalidOperation
import html
import re
from urllib.parse import urlencode

from availability import Model, identity, safe_base, seed_model, CATALOG_TTL
from inference import request, USER_AGENT

ZEN_DOC = 'https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx'
GEMINI_PRICING = 'https://ai.google.dev/gemini-api/docs/pricing'
PRICED_BASES = {'openrouter': 'https://openrouter.ai/api/v1',
                'kilocode': 'https://api.kilo.ai/api/gateway'}


def pricing_eligibility(pricing):
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= pricing.keys():
        return 'unknown'
    try:
        values = [Decimal(str(value)) for value in pricing.values()]
        if any(not x.is_finite() or x < 0 for x in values):
            return 'unknown'
        return 'free' if all(x == 0 for x in values) else 'paid'
    except (InvalidOperation, ValueError):
        return 'unknown'


def priced_text_eligibility(row):
    """Zero text-token prices do not cover audio/image generation charges.

    Lyria catalogs, for example, expose text+audio outputs with zero text rates
    but per-song pricing outside those rates. Require authoritative text-only
    output and text input; missing/mixed modality evidence stays unknown.
    Keep the same API identity so new uncertainty supersedes old free metadata
    even during an incomplete provider refresh.
    """
    architecture = row.get('architecture')
    if not isinstance(architecture, dict):
        return 'unknown'
    outputs, inputs = architecture.get('output_modalities'), architecture.get('input_modalities')
    if outputs != ['text'] or not isinstance(inputs, list) or 'text' not in inputs:
        return 'unknown'
    return pricing_eligibility(row.get('pricing'))


def parse_zen(text):
    endpoints, prices = {}, {}
    section = ''
    for line in text.splitlines():
        if line.startswith('## '):
            section = line[3:].strip()
        if not line.startswith('|'):
            continue
        cols = [x.strip().strip('`') for x in line.strip('|').split('|')]
        if section == 'Endpoints' and len(cols) >= 3 and cols[2].startswith('https://opencode.ai/zen/v1/'):
            endpoints[cols[0]] = (cols[1], cols[2])
        if section == 'Pricing' and len(cols) >= 3:
            if cols[1:3] == ['Free', 'Free']:
                prices[cols[0]] = 'free'
            elif any('$' in v for v in cols[1:3]):
                prices[cols[0]] = 'paid'
    models = []
    for name, (model, endpoint) in endpoints.items():
        suffix = endpoint.removeprefix('https://opencode.ai/zen/v1')
        protocol = {'/chat/completions': 'openai', '/responses': 'responses',
                    '/messages': 'anthropic'}.get(suffix, 'unsupported')
        if suffix == '/models/' + model:
            protocol = 'gemini'
        models.append(Model('opencode-zen', model, 'https://opencode.ai/zen/v1', protocol,
                            prices.get(name, 'unknown'), ZEN_DOC))
    if not models or not prices:
        raise ValueError('unrecognized Zen pricing document')
    return models


def _plain(text):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', text)).split())


def parse_gemini_pricing(text):
    free = set()
    for block in re.split(r'<h2\b', text, flags=re.I)[1:]:
        # Only exact code model IDs; no display-name alias expansion.
        code = re.search(r'<code\b[^>]*>([^<]+)</code>', block, flags=re.I)
        table = re.search(r'<table\b[^>]*>(.*?)</table>', block, flags=re.I | re.S)
        if not code or not table:
            continue
        rows = re.findall(r'<tr\b[^>]*>(.*?)</tr>', table[1], flags=re.I | re.S)
        cells = [[_plain(c) for c in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', row, flags=re.I | re.S)] for row in rows]
        if not cells or len(cells[0]) < 2 or cells[0][1] != 'Free Tier':
            continue
        inputs = [c for c in cells if len(c) >= 2 and c[0].startswith('Input price')]
        outputs = [c for c in cells if len(c) >= 2 and c[0].startswith('Output price')]
        if inputs and outputs and all(c[1] == 'Free of charge' for c in inputs + outputs):
            free.add(html.unescape(code[1]).strip())
    return free


class CatalogDiscovery:
    def __init__(self, service, transport=request, bridge_enabled=False):
        self.service = service
        self.transport = transport
        self.bridge_enabled = bridge_enabled

    def _get(self, url, headers=None, text=False):
        res = self.transport('GET', url, {'User-Agent': USER_AGENT, **(headers or {})})
        if res.status != 200:
            raise ValueError('catalog unavailable')
        return res.body.decode('utf-8') if text else res.json()

    def _pages(self, url, headers, gemini=False):
        token, seen = '', set()
        while True:
            target = url + ('?' + urlencode({'pageToken' if gemini else 'page_token': token}) if token else '')
            doc = self._get(target, headers)
            rows = doc.get('models' if gemini else 'data')
            if not isinstance(rows, list):
                raise ValueError('invalid model catalog')
            yield from rows
            token = doc.get('nextPageToken' if gemini else 'next_page_token')
            if not token and doc.get('has_more'):
                # Standard OpenAI cursor pagination uses the last model ID.
                token = doc.get('last_id')
                if not token:
                    raise ValueError('incomplete model catalog')
                # Handled explicitly rather than following arbitrary next URLs.
                yield from self._cursor_pages(url, headers, token)
                return
            if not token:
                return
            if not isinstance(token, str) or token in seen:
                raise ValueError('invalid pagination')
            seen.add(token)

    def _cursor_pages(self, url, headers, cursor):
        seen = set()
        while cursor:
            if cursor in seen:
                raise ValueError('invalid pagination')
            seen.add(cursor)
            doc = self._get(url + '?' + urlencode({'after': cursor}), headers)
            if not isinstance(doc.get('data'), list):
                raise ValueError('invalid model catalog')
            yield from doc['data']
            cursor = doc.get('last_id') if doc.get('has_more') else None
            if doc.get('has_more') and not cursor:
                raise ValueError('incomplete model catalog')

    def discover(self, route, public):
        provider = route['provider']
        secret = route.get('api_key', '')
        if provider in PRICED_BASES:
            base = PRICED_BASES[provider]
            return [Model(provider, r['id'], base, 'openai', priced_text_eligibility(r), base + '/models')
                    for r in self._pages(base + '/models', {'Authorization': 'Bearer ' + secret})
                    if isinstance(r, dict) and isinstance(r.get('id'), str) and r['id']]
        if provider == 'opencode-zen':
            if provider not in public:
                public[provider] = parse_zen(self._get(ZEN_DOC, text=True))
            base = 'https://opencode.ai/zen/v1'
            ids = {r['id'] for r in self._pages(base + '/models', {'Authorization': 'Bearer ' + secret}) if isinstance(r, dict) and r.get('id')}
            known = {m.model: m for m in public[provider]}
            return [known.get(mid, Model(provider, mid, base, 'unsupported')) for mid in sorted(ids)]
        if provider == 'gemini':
            if provider not in public:
                public[provider] = parse_gemini_pricing(self._get(GEMINI_PRICING, text=True))
                if not public[provider]:
                    raise ValueError('unrecognized Gemini pricing document')
            base = 'https://generativelanguage.googleapis.com/v1beta'
            result = []
            for r in self._pages(base + '/models', {'x-goog-api-key': secret}, gemini=True):
                mid = r.get('name', '').removeprefix('models/')
                if mid:
                    supported = 'generateContent' in r.get('supportedGenerationMethods', [])
                    result.append(Model(provider, mid, base, 'gemini' if supported else 'unsupported',
                                        'free' if mid in public[provider] else 'unknown', GEMINI_PRICING, True))
            return result
        # ID-only inventories are useful for accounting but never prove price.
        base = safe_base(route.get('base_url', ''))
        if base and route.get('wire') == 'openai':
            return [Model(provider, r['id'], base, 'openai') for r in
                    self._pages(base + '/models', {'Authorization': 'Bearer ' + secret})
                    if isinstance(r, dict) and r.get('id')]
        raise ValueError('unsupported discovery')

    def refresh(self, routes):
        """All active API keys, provider unions, sanitized per-key diagnostics.

        Does not call sync_seeds: startup/config reload does that once. Public
        document fetches are shared only within this refresh, not page reads.
        """
        by_key = {}
        for r in routes:
            ref = r.get('credential_ref') or r.get('env_var')
            if ref:
                by_key.setdefault(identity(r['provider'], ref), []).append(r)
        explicit = {}
        for route in routes:
            if route.get('model'):
                m = seed_model(route)
                if m.eligibility == 'free' and 0 <= self.service.clock() - m.verified_at < CATALOG_TTL:
                    explicit[m.id] = m
        secrets = {r['api_key'] for r in routes if isinstance(r.get('api_key'), str) and r['api_key']}
        public, unions, complete = {}, {}, {}
        for k in self.service.store.rows('SELECT * FROM av_credentials'):
            if not k['active'] or not k['supported'] or not k['has_secret'] or k['revoked']:
                continue
            provider = k['provider']
            complete.setdefault(provider, True)
            error = None
            seen_routes = set()
            for route in by_key.get(k['id'], [{}]):
                signature = provider if provider in PRICED_BASES or provider in ('gemini', 'opencode-zen') else (route.get('base_url'), route.get('wire'))
                if signature in seen_routes:
                    continue
                seen_routes.add(signature)
                try:
                    models = self.discover(route, public)
                    if any(secret in value for m in models for value in
                           (m.model, m.provider, m.base_url, m.protocol, m.provenance) for secret in secrets):
                        raise ValueError('unsafe catalog metadata')
                    union = unions.setdefault(provider, {})
                    for m in models:
                        if m.eligibility == 'unknown' and m.id in explicit and provider not in PRICED_BASES:
                            m = explicit[m.id]
                        old = union.get(m.id)
                        # Conflicting per-key prices fail closed for the provider union.
                        priority = {'free': 0, 'unknown': 1, 'paid': 2}
                        if not old or priority[m.eligibility] >= priority[old.eligibility]:
                            union[m.id] = m
                except Exception:
                    error = 'discovery_failed'
                    complete[provider] = False
            with self.service.store.transaction() as db:
                db.execute('''INSERT INTO av_discovery(credential_id,checked_at,succeeded_at,error)
                    VALUES (?,?,?,?) ON CONFLICT(credential_id) DO UPDATE SET
                    checked_at=excluded.checked_at,
                    succeeded_at=COALESCE(excluded.succeeded_at,av_discovery.succeeded_at), error=excluded.error''',
                    (k['id'], self.service.clock(), None if error else self.service.clock(), error))
        for provider, models in unions.items():
            published = list(models.values())
            if self.bridge_enabled and provider == 'opencode-zen':
                from zencli_bridge import bridge_models
                published += bridge_models(published)
            self.service.update_catalog(provider, published, complete=complete[provider])
        return self.service.store.rows('SELECT * FROM av_discovery')
