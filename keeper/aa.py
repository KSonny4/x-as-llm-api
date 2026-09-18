"""AA snapshot fetch: scores index models for tiebreak input only.

Refreshed daily by the caller; this module fetches + caches. Failure serves
the last-good cache with stale=True; no cache means empty + stale=True.
Values (the API key) never touch disk — only parsed scores are cached.
"""
import json
import os
import urllib.request as _request

urlopen = _request.urlopen

AA_MODELS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"


def parse_scores(payload):
    """{model key: score}; AA coding index first, intelligence fallback.
    V2 shape nests scores in entry.evaluations
    (artificial_analysis_coding_index / _intelligence_index); bare
    top-level coding/intelligence still accepted (legacy/fixtures).
    Keyed by AA slug (url-style model id) falling back to raw id: v2 ids
    are UUIDs that never match a model string, so the slug is the
    joinable key. Matrix lookup tries the full model string then its
    last path segment (see matrix.aa_lookup)."""
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
            score = evals.get("artificial_analysis_intelligence_index")
        if not isinstance(score, (int, float)):
            score = entry.get("coding")
        if not isinstance(score, (int, float)):
            score = entry.get("intelligence")
        if isinstance(score, (int, float)):
            scores[key] = float(score)
    return scores


def _read_cache(cache_path):
    try:
        with open(cache_path, encoding="utf-8") as fh:
            body = json.load(fh)
        scores = body.get("scores")
        if isinstance(scores, dict):
            return scores
    except (OSError, ValueError):
        pass
    return None


def fetch_snapshot(api_key, cache_path, url=AA_MODELS_URL, timeout=20):
    """Returns (scores, stale). Writes cache on success only."""
    try:
        req = _request.Request(url, headers={"x-api-key": api_key})
        with urlopen(req, timeout=timeout) as res:
            scores = parse_scores(json.loads(res.read().decode("utf-8")))
        try:
            parent = os.path.dirname(cache_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump({"scores": scores}, fh)
        except OSError:
            pass
        return scores, False
    except Exception:
        cached = _read_cache(cache_path)
        return (cached if cached is not None else {}), True
