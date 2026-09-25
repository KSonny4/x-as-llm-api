"""Keeper model id -> Artificial Analysis slug matching (Coding Index input).

Precedence (docs/keeper-aa-aliases.md, owner-authorized AI matching 2026-09-25):
  1. reviewed aa.ALIASES          method 'alias'  (taken verbatim)
  2. exact AA slug                method 'exact'
  3. deterministic normalization  method 'normalized'
  4. persisted AI adjudication    method 'ai'     (confidence >= 0.8, shortlist-only)

Matching (which AA model) is separate from scoring (does AA publish a Coding
Index for it): an exact/normalized hit ends resolution even when AA has no
Coding Index yet, so e.g. gpt-6-luna is never handed to the LLM and confused
with gpt-5-6-luna. Unless the Keeper id names an effort level, a match takes
the lowest scored member of its AA family (same creator + name without the
trailing "(max)"/"(xhigh)"/"(Non-reasoning)" label) so a rank never
over-promises.

The AI step runs only from the daily AA refresh, never on the request path.
Its decisions persist in aa-matches.json next to the AA cache; a model is
re-asked only when its candidate shortlist changes. LLM failure keeps prior
decisions and leaves new models unscored.
"""
import difflib
import hashlib
import json
import math
import os
import re
import threading
import time

AI_MIN_CONFIDENCE = 0.8
AI_MAX_PER_REFRESH = 10
SHORTLIST_SIZE = 8
MATCHES_FORMAT = 'aa-matches-v1'
EFFORT_LABELS = ('max', 'xhigh', 'high', 'medium', 'low', 'minimal', 'non-reasoning', 'reasoning')

_LOCK = threading.Lock()
# Swapped atomically (one assignment) by install(); request threads read it.
_TABLE = {'index': {}, 'family': {}, 'ai': {}, 'decided_at': None, 'memo': {}}


def normalize(model):
    """Lowercase; drop provider/vendor/stealth namespaces and free-tier
    suffixes; every other separator (dots, underscores, spaces) -> dash."""
    m = str(model).strip().lower().rsplit('/', 1)[-1]
    m = re.sub(r'(:free|[-_ ]free|\s*\(free\))$', '', m)
    return re.sub(r'[^a-z0-9]+', '-', m).strip('-')


def tokens(text):
    """Alphanumeric runs split at letter/digit boundaries: v2.6 -> v, 2, 6."""
    return re.findall(r'[a-z]+|[0-9]+', str(text).lower())


def family_name(name):
    return re.sub(r'\s*\([^)]*\)\s*$', '', str(name or '')).strip().lower()


def explicit_effort(model):
    norm = normalize(model)
    return any(norm.endswith('-' + label) for label in EFFORT_LABELS)


def install(index, ai, decided_at=None):
    """index: slug -> {name, creator, coding}; ai: (provider, model) -> decision."""
    global _TABLE
    groups = {}
    for slug, entry in index.items():
        groups.setdefault((entry.get('creator'), family_name(entry.get('name') or slug)), []).append(slug)
    family = {slug: tuple(members) for members in groups.values() for slug in members}
    ai = {k: v for k, v in ai.items() if not v.get('slug') or v['slug'] in index}
    _TABLE = {'index': dict(index), 'family': family, 'ai': ai, 'decided_at': decided_at, 'memo': {}}


def table():
    return _TABLE


def _valid(score):
    return (isinstance(score, (int, float)) and not isinstance(score, bool)
            and math.isfinite(score) and score >= 0)


def conservative(slug, scores, model, family):
    if explicit_effort(model):
        return slug
    scored = [(float(scores[s]), s) for s in family.get(slug, (slug,)) if _valid(scores.get(s))]
    return min(scored)[1] if scored else slug


def resolve(scores, provider, model, aliases):
    """-> {slug, method, confidence, picked?, reason?} or None. Pure lookups,
    memoized per (installed table, scores object): aa_scores is replaced,
    never mutated, so the request path pays one dict lookup per model."""
    t = _TABLE
    memo = t['memo']
    if memo.get('scores') is not scores:
        memo = t['memo'] = {'scores': scores, 'rows': {}}
    key = (provider, model)
    if key not in memo['rows']:
        memo['rows'][key] = _resolve(t, scores, provider, model, aliases)
    found = memo['rows'][key]
    return dict(found) if found else None


def _resolve(t, scores, provider, model, aliases):
    index, key = t['index'], (provider, model)
    if key in aliases:
        return {'slug': aliases[key], 'method': 'alias', 'confidence': 1.0}
    norm = normalize(model)
    if model in scores or model in index:
        picked, method, extra = model, 'exact', {}
    elif norm and (norm in scores or norm in index):
        picked, method, extra = norm, 'normalized', {}
    elif (t['ai'].get(key) or {}).get('slug'):
        d = t['ai'][key]
        picked, method = d['slug'], 'ai'
        extra = {'confidence': d.get('confidence'), 'reason': d.get('reason'), 'decided_at': d.get('decided_at')}
    else:
        return None
    # An exact slug already names the precise AA variant; only inferred
    # matches (normalized/ai) take the family's most conservative score.
    slug = picked if method == 'exact' else conservative(picked, scores, model, t['family'])
    out = {'slug': slug, 'method': method, 'confidence': 1.0, **extra}
    if slug != picked:
        out['picked'] = picked
    return out


# ---------------------------------------------------------------- AI step --

def shortlist(provider, model, index, size=SHORTLIST_SIZE):
    """Plausible AA entries sharing at least one word token with the id."""
    norm = normalize(model)
    words = {w for w in tokens(norm) if not w.isdigit() and len(w) > 1}
    vendor = re.sub(r'[^a-z0-9]', '', (model.split('/')[0] if '/' in model else provider).lower())
    ranked = []
    for slug, entry in index.items():
        cand = set(tokens(slug)) | set(tokens(entry.get('name') or ''))
        overlap = words & cand
        if not overlap:
            continue
        creator = re.sub(r'[^a-z0-9]', '', str(entry.get('creator') or '').lower())
        sim = (difflib.SequenceMatcher(None, norm, slug).ratio() + len(overlap) / len(words | cand)
               + (0.2 if creator and vendor and (creator.startswith(vendor) or vendor.startswith(creator)) else 0))
        ranked.append((-sim, slug))
    return [{'slug': s, 'name': index[s].get('name'), 'creator': index[s].get('creator'),
             'coding_index': index[s].get('coding')} for _, s in sorted(ranked)[:size]]


def shortlist_hash(cands):
    return hashlib.sha256(json.dumps(sorted(c['slug'] for c in cands)).encode()).hexdigest()[:16]


PROMPT = """You map one LLM endpoint id to an entry of the Artificial Analysis (AA) model catalog.
Endpoint: provider={provider!r} id={model!r}
AA candidates (JSON): {cands}

Rules:
- Pick a candidate only if it is the SAME model: same family, same version numbers, same size/variant words (pro, flash, mini, lite, small, vl, coder, ultra, ...).
- A different version number is a different model (2.6 vs 2.5, 6 vs 5.6, 3 vs 3.5) -> null.
- Ignore provider/namespace prefixes (openai/, stealth/, vendor/), free-tier suffixes (free, :free), and 'contributor'.
- Candidates differing only by a parenthesised reasoning effort are the same model; pick any of them.
- If unsure, or the endpoint is a codename/stealth model not in the list, answer null. Never guess from a similar name.
Reply with ONLY one JSON object: {{"slug": "<candidate slug>" or null, "confidence": <0..1>, "reason": "<short>"}}"""


def parse_reply(text):
    """First JSON object in the reply -> (slug|None, confidence, reason). Raises on garbage."""
    text = str(text)
    start = text.find('{')
    while start != -1:
        try:
            doc, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            start = text.find('{', start + 1)
            continue
        if isinstance(doc, dict) and 'slug' in doc:
            slug, conf = doc.get('slug'), doc.get('confidence')
            if (slug is None or isinstance(slug, str)) and _valid(conf) and conf <= 1:
                return slug or None, float(conf), str(doc.get('reason') or '')[:300]
        break
    raise ValueError('unparseable matcher reply')


def adjudicate(provider, model, cands, ask, now):
    """One LLM decision; raises when the LLM call or reply fails."""
    slug, conf, reason = parse_reply(ask([{'role': 'user', 'content': PROMPT.format(
        provider=provider, model=model, cands=json.dumps(cands, separators=(',', ':')))}]))
    base = {'provider': provider, 'model': model, 'method': 'ai', 'confidence': conf, 'reason': reason,
            'decided_at': now, 'shortlist_hash': shortlist_hash(cands),
            'candidates': [c['slug'] for c in cands]}
    by_slug = {c['slug']: c for c in cands}
    rejected = None
    if slug is not None and slug not in by_slug:
        rejected = 'out_of_shortlist'
    elif slug is not None and conf < AI_MIN_CONFIDENCE:
        rejected = 'low_confidence'
    elif slug is not None:
        # Version numbers in the id must all appear in the chosen entry.
        have = set(tokens(slug)) | set(tokens(by_slug[slug].get('name') or ''))
        if not {n for n in tokens(normalize(model)) if n.isdigit()} <= have:
            rejected = 'version_mismatch'
    if rejected:
        return {**base, 'slug': None, 'picked': slug, 'rejected': rejected}
    return {**base, 'slug': slug}


def matches_path(state):
    return state.get('aa_matches_path') or os.path.join(
        os.path.dirname(state['aa_cache']) or '.', 'aa-matches.json')


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
        if doc.get('format') != MATCHES_FORMAT:
            return {}, None
        return ({(d['provider'], d['model']): d for d in doc.get('ai', [])
                 if isinstance(d, dict) and isinstance(d.get('provider'), str) and isinstance(d.get('model'), str)},
                doc.get('decided_at'))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}, None


def save(path, ai, served, now):
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path + '.tmp', 'w', encoding='utf-8') as fh:
            json.dump({'format': MATCHES_FORMAT, 'decided_at': now, 'ai': list(ai.values()),
                       'served': served}, fh, indent=1, sort_keys=True)
        os.replace(path + '.tmp', path)
    except OSError:
        pass


def run(state, scores, aliases, now, ask, served_models):
    """Adjudicate unresolved served models; persist; install. Never raises."""
    t = _TABLE
    ai, new = dict(t['ai']), {}
    asked = 0
    for m in served_models:
        provider, model = m['provider'], m['model']
        if asked >= AI_MAX_PER_REFRESH:
            break
        current = resolve(scores, provider, model, aliases)
        if current and current['method'] != 'ai':
            continue
        cands = shortlist(provider, model, t['index'])
        prior = ai.get((provider, model))
        if prior and prior.get('shortlist_hash') == shortlist_hash(cands):
            continue
        if not cands:
            new[(provider, model)] = {'provider': provider, 'model': model, 'method': 'ai', 'slug': None,
                                     'confidence': None, 'reason': 'no AA entry shares a name token',
                                     'rejected': 'no_candidate', 'decided_at': now,
                                     'shortlist_hash': shortlist_hash(cands), 'candidates': []}
            continue
        asked += 1
        try:
            new[(provider, model)] = adjudicate(provider, model, cands, ask, now)
        except Exception:
            continue  # keep prior decision (if any); retried next refresh
    # Merge onto whatever is installed now (a daily refresh may have swapped the index).
    install(_TABLE['index'], {**_TABLE['ai'], **new}, now)
    served = []
    for m in served_models:
        r = resolve(scores, m['provider'], m['model'], aliases)
        served.append({'provider': m['provider'], 'model': m['model'],
                       'slug': r and r['slug'], 'method': r and r['method'],
                       'coding_index': float(scores[r['slug']]) if r and _valid(scores.get(r['slug'])) else None})
    save(matches_path(state), _TABLE['ai'], served, now)


def refresh(state, scores, aliases, now, background=True):
    """Kick AI adjudication for served, still-unresolved models (daily path)."""
    ask = state.get('aa_matcher')
    if not ask or 'availability' not in state or not _TABLE['index']:
        return None
    if not _LOCK.acquire(blocking=False):
        return None

    def work():
        try:
            served = [m for m in state['availability'].catalog()['models'] if m.get('working_keys')]
            run(state, scores, aliases, now, ask, served)
            state['aa_match_error'] = None
        except Exception:
            state['aa_match_error'] = 'matcher_failed'
        finally:
            _LOCK.release()
    if not background:
        work()
        return None
    thread = threading.Thread(target=work, name='keeper-aa-matcher', daemon=True)
    try:
        thread.start()
    except Exception:
        _LOCK.release()  # never leave the matcher disabled until restart
        state['aa_match_error'] = 'matcher_failed'
        return None
    return thread


def keeper_chat(state):
    """In-process keeper-coder call: free-first, attributed to keeper-aa-matcher.
    Plain text (no response_format) so genuine-CLI free routes stay eligible."""
    def ask(messages):
        import service_api
        body = json.dumps({'model': service_api.ALIAS, 'messages': messages}).encode()
        code, raw, _ = service_api.chat(state, body, allow_exact=False,
                                        ctx={'consumer': 'keeper-aa-matcher'})
        if code != 200:
            raise RuntimeError('matcher_chat_failed')
        return json.loads(raw)['choices'][0]['message']['content']
    return ask
