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
    """{model_id: score}; prefers coding, falls back to intelligence."""
    scores = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        score = entry.get("coding")
        if not isinstance(score, (int, float)):
            score = entry.get("intelligence")
        if isinstance(score, (int, float)):
            scores[model_id] = float(score)
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
