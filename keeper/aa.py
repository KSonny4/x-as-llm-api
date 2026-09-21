"""AA snapshot fetch: scores index models for tiebreak input only.

Refreshed daily by the caller; this module fetches + caches. Failure serves
the last-good cache with stale=True; no cache means empty + stale=True.
Values (the API key) never touch disk — only parsed scores are cached.
"""
import json
import math
import time
import os
import urllib.request as _request

urlopen = _request.urlopen

AA_MODELS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"


def parse_scores(payload):
    """Exact AA slugs and Coding Index only; never Intelligence Index."""
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


def fetch_snapshot(api_key, cache_path, url=AA_MODELS_URL, timeout=20):
    """Returns (scores, stale). Writes cache on success only."""
    try:
        req = _request.Request(url, headers={"x-api-key": api_key})
        with urlopen(req, timeout=timeout) as res:
            scores = parse_scores(json.loads(res.read().decode("utf-8")))
        if not scores or any(api_key and api_key in k for k in scores):
            raise ValueError("unusable coding snapshot")
        try:
            parent = os.path.dirname(cache_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(cache_path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump({"format": "coding-v1", "scores": scores, "succeeded_at": time.time()}, fh)
            os.replace(cache_path + ".tmp", cache_path)
        except OSError:
            pass
        return scores, False
    except Exception:
        cached = _read_cache(cache_path)
        return (cached if cached is not None else {}), True


# No implicit suffix stripping, fuzzy joins, or invented model aliases.
# An explicit (provider, model) -> AA slug entry requires reviewed provenance.
# Primary-name equivalences reviewed 2026-09-20: docs/keeper-aa-aliases.md.
# Scores still come exclusively from the dated AA cache, never this mapping.
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


def score_for(scores, provider, model):
    value = scores.get(ALIASES.get((provider, model), model))
    return float(value) if valid_score(value) else None


def rank_models(models, scores):
    rows = [{**m, 'coding_index': score_for(scores, m['provider'], m['model'])} for m in models]
    return sorted(rows, key=lambda m: (not bool(m['working_keys']), m['coding_index'] is None,
                                      -(m['coding_index'] or 0), m['provider'], m['model'], m['id']))


def refresh_state(state, now=None):
    """Background only. Daily attempt cadence, including failures and restarts."""
    now = time.time() if now is None else now
    if state.get('aa_checked_at') is None:
        cached = _read_cache(state['aa_cache'])
        if cached is not None:
            try:
                with open(state['aa_cache'], encoding='utf-8') as fh:
                    stamp = json.load(fh).get('succeeded_at')
                if isinstance(stamp, (int, float)) and stamp <= now:
                    state.update(aa_scores=cached, aa_succeeded_at=stamp, aa_checked_at=stamp,
                                 aa_stale=now - stamp >= 86400)
            except (OSError, ValueError, TypeError):
                pass
    last = state.get('aa_checked_at')
    if last is not None and 0 <= now - last < 86400:
        return
    state['aa_checked_at'] = now
    if not state.get('aa_api_key'):
        state['aa_stale'] = True
        return
    scores, stale = fetch_snapshot(state['aa_api_key'], state['aa_cache'])
    state['aa_scores'] = scores or state.get('aa_scores', {})
    state['aa_stale'] = stale
    if not stale:
        state['aa_succeeded_at'] = now
