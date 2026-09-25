"""AA snapshot fetch: scores index models for tiebreak input only.

Refreshed daily by the caller; this module fetches + caches. Failure serves
the last-good cache with stale=True; no cache means empty + stale=True.
Values (the API key) never touch disk — only parsed scores and the public
slug index (slug -> name, creator, coding) are cached. Model-id matching
lives in aa_match (alias > exact > normalized > persisted AI decision).
"""
import json
import math
import time
import os
import urllib.request as _request

import aa_match

urlopen = _request.urlopen

AA_MODELS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"


def parse_scores(payload):
    """Exact AA slugs -> Coding Index (the ranking score). The Intelligence
    Index lives only in parse_index, as a secondary sort key."""
    scores = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("slug") or entry.get("id")
        if not key:
            continue
        evals = entry.get("evaluations")
        evals = evals if isinstance(evals, dict) else {}
        score = evals.get("artificial_analysis_coding_index")
        if not isinstance(score, (int, float)):
            score = entry.get("coding")
        if valid_score(score) and isinstance(key, str):
            scores[key] = float(score)
    return scores


def parse_index(payload):
    """Every AA slug (scored or not) -> {name, creator, coding}: identity for
    matching. A slug AA lists without a Coding Index still matches, unscored."""
    index = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("slug"), str):
            continue
        creator = entry.get("model_creator")
        evals = entry.get("evaluations") if isinstance(entry.get("evaluations"), dict) else {}
        score = evals.get("artificial_analysis_coding_index")
        intel = evals.get("artificial_analysis_intelligence_index")
        index[entry["slug"]] = {
            "name": entry.get("name") if isinstance(entry.get("name"), str) else None,
            "creator": creator.get("slug") if isinstance(creator, dict) else None,
            "coding": float(score) if valid_score(score) else None,
            # Secondary ranking key only (never a Coding Index substitute).
            "intelligence": float(intel) if valid_score(intel) else None}
    return index


def _read_cache(cache_path):
    try:
        with open(cache_path, encoding="utf-8") as fh:
            body = json.load(fh)
        scores = body.get("scores")
        if body.get("format") == "coding-v1" and isinstance(scores, dict):
            return {k: v for k, v in scores.items() if valid_score(v)}
    except (OSError, ValueError):
        pass
    return None


def _read_index(cache_path):
    try:
        with open(cache_path, encoding="utf-8") as fh:
            index = json.load(fh).get("index")
        if isinstance(index, dict):
            return {k: v for k, v in index.items() if isinstance(k, str) and isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        pass
    return None


def fetch_snapshot(api_key, cache_path, url=AA_MODELS_URL, timeout=20, index_out=None):
    """Returns (scores, stale). Writes cache on success only. A dict passed as
    index_out receives the fresh slug index on success."""
    try:
        req = _request.Request(url, headers={"x-api-key": api_key})
        with urlopen(req, timeout=timeout) as res:
            payload = json.loads(res.read().decode("utf-8"))
        scores, index = parse_scores(payload), parse_index(payload)
        if not scores or any(api_key and api_key in k for k in list(scores) + list(index)):
            raise ValueError("unusable coding snapshot")
        if index_out is not None:
            index_out.update(index)
        try:
            parent = os.path.dirname(cache_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(cache_path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump({"format": "coding-v1", "scores": scores, "index": index,
                           "succeeded_at": time.time()}, fh)
            os.replace(cache_path + ".tmp", cache_path)
        except OSError:
            pass
        return scores, False
    except Exception:
        cached = _read_cache(cache_path)
        return (cached if cached is not None else {}), True


# Reviewed (provider, model) -> AA slug entries; they win over every other
# matching method (aa_match: exact, normalized, AI-adjudicated) and are taken
# verbatim. Primary-name equivalences reviewed 2026-09-20/21:
# docs/keeper-aa-aliases.md. Scores come only from the dated AA cache.
ALIASES = {
    ('opencode-zen', 'ling-3.0-flash-fin-free'): 'ling-3-0-flash-fin',
    ('opencode-zen', 'nemotron-3.5-lightning-free'): 'nemotron-3-5-lightning',
    ('openrouter', 'inclusionai/ling-3.0-flash-fin:free'): 'ling-3-0-flash-fin',
    ('kilocode', 'inclusionai/ling-3.0-flash-fin:free'): 'ling-3-0-flash-fin',
    ('openrouter', 'nvidia/nemotron-3.5-lightning:free'): 'nemotron-3-5-lightning',
    ('kilocode', 'nvidia/nemotron-3.5-lightning:free'): 'nemotron-3-5-lightning',
    ('openrouter', 'inclusionai/ling-3.0-flash-vl:free'): 'ling-3-0-flash-vl',
    ('openrouter', 'thinkingmachines/inkling-small:free'): 'inkling-small',
    ('openrouter', 'cohere/north-mini-code:free'): 'north-mini-code',
    ('openrouter', 'liquid/lfm-2.5-2.6b:free'): 'lfm2-5-2-6b',
    ('kilocode', 'inclusionai/ling-3.0-flash-vl:free'): 'ling-3-0-flash-vl',
    ('kilocode', 'thinkingmachines/inkling-small:free'): 'inkling-small',
    ('kilocode', 'cohere/north-mini-code:free'): 'north-mini-code',
    ('kilocode', 'liquid/lfm-2.5-2.6b:free'): 'lfm2-5-2-6b',
    ('kilocode', 'stepfun/step-3.7-flash:free'): 'step-3-7-flash',
    # Muse Spark 1.3 contributor-free has no effort label; map to the lower
    # (max, 75.8) rather than xhigh (76.5) so the rank never over-promises.
    ('opencode-zen', 'muse-spark-1.3-contributor-free'): 'muse-spark-1-3',
}


def valid_score(score):
    return isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) and score >= 0


def match_for(scores, provider, model):
    """Provenance {slug, method, confidence, ...} or None (see aa_match)."""
    return aa_match.resolve(scores, provider, model, ALIASES)


def _scored(scores, match):
    value = scores.get(match['slug']) if match else None
    return float(value) if valid_score(value) else None


def intelligence_for(match):
    """AA Intelligence Index of the matched slug: a secondary sort key for
    models AA has not given a Coding Index yet (e.g. a week-old release)."""
    entry = aa_match._TABLE['index'].get(match['slug']) if match else None
    value = (entry or {}).get('intelligence')
    return float(value) if valid_score(value) else None


def score_for(scores, provider, model):
    return _scored(scores, match_for(scores, provider, model))


def rank_models(models, scores):
    rows = []
    for m in models:
        match = match_for(scores, m['provider'], m['model'])
        rows.append({**m, 'coding_index': _scored(scores, match), 'coding_index_match': match,
                     'intelligence_index': intelligence_for(match)})
    # Coding Index first; models without one are ordered by Intelligence
    # Index (still after every Coding-scored model), then unscored ones.
    return sorted(rows, key=lambda m: (not bool(m['working_keys']), m['coding_index'] is None,
                                      -(m['coding_index'] or 0), m['intelligence_index'] is None,
                                      -(m['intelligence_index'] or 0), m['provider'], m['model'], m['id']))


def _install(state):
    """Publish this state's AA index + persisted AI decisions to aa_match once
    per index object (startup load, each successful fetch)."""
    index = state.get('aa_index') or {}
    if state.get('aa_index_installed') is index:
        return
    ai, decided = aa_match.load(aa_match.matches_path(state)) if index else ({}, None)
    aa_match.install(index, ai, decided)
    state['aa_index_installed'] = index


def refresh_state(state, now=None):
    """Background only. Daily attempt cadence, including failures and restarts."""
    now = time.time() if now is None else now
    if state.get('aa_checked_at') is None:
        cached = _read_cache(state['aa_cache'])
        if cached is not None:
            try:
                with open(state['aa_cache'], encoding='utf-8') as fh:
                    stamp = json.load(fh).get('succeeded_at')
                index = _read_index(state['aa_cache'])
                if isinstance(stamp, (int, float)) and stamp <= now:
                    state.update(aa_scores=cached, aa_succeeded_at=stamp, aa_stale=now - stamp >= 86400,
                                 aa_index=index or {})
                    # A pre-index cache refetches now so matching has names/families.
                    if index is not None or not state.get('aa_api_key'):
                        state['aa_checked_at'] = stamp
            except (OSError, ValueError, TypeError):
                pass
    last = state.get('aa_checked_at')
    if last is not None and 0 <= now - last < 86400:
        _install(state)
        return
    state['aa_checked_at'] = now
    if not state.get('aa_api_key'):
        state['aa_stale'] = True
        _install(state)
        return
    index = {}
    scores, stale = fetch_snapshot(state['aa_api_key'], state['aa_cache'], index_out=index)
    state['aa_scores'] = scores or state.get('aa_scores', {})
    state['aa_stale'] = stale
    if not stale:
        state['aa_succeeded_at'] = now
        state['aa_index'] = index
    _install(state)
    try:
        aa_match.refresh(state, state['aa_scores'], ALIASES, now,
                         background=state.get('aa_match_background', True))
    except Exception:
        state['aa_match_error'] = 'matcher_failed'
