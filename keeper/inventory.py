#!/usr/bin/env python3
"""Provider model inventory: live-enumerated, cached, degrading.

Each seed route carries a credential; adapters use it to ask the provider
for its model list. Results are cached (TTL) so page views never fan out
to provider APIs, and a failing provider degrades to its seed-declared
models instead of breaking the matrix.

Hermetic: HTTP goes through module-level ``urlopen`` (tests stub it);
time through ``now()`` (tests pin it). No live calls in the suite.
"""
import json
import time
import urllib.error
import urllib.request

# Assignable in tests to stub provider APIs (no live calls in suite).
urlopen = urllib.request.urlopen

CACHE_TTL = 3600  # 1h: model lists change slowly; ?refresh=1 bypasses

_cache = {}  # provider -> (expires_epoch, [model, ...])


def now():
    return time.time()


def _get_json(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def openai_compatible_models(base_url, api_key):
    """GET {base}/models with a bearer; returns [model id]."""
    doc = _get_json(base_url.rstrip("/") + "/models",
                    {"Authorization": "Bearer " + api_key})
    data = doc.get("data", [])
    return sorted({str(m.get("id", "")) for m in data if isinstance(m, dict)
                   and m.get("id")})


def gemini_models(api_key):
    """GET generativelanguage models; returns [model id]."""
    doc = _get_json(
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": api_key})
    out = []
    for m in doc.get("models", []):
        name = str(m.get("name", ""))
        if name.startswith("models/"):
            name = name[len("models/"):]
        if name:
            out.append(name)
    return sorted(set(out))


def provider_credential(routes):
    """First route per provider: {provider: route} (seed decides the key)."""
    seen = {}
    for route in routes:
        provider = route.get("provider", "")
        if provider and provider not in seen:
            seen[provider] = route
    return seen


def seed_models(routes):
    """Seed-declared models per provider (always listed, even on API fail)."""
    out = {}
    for route in routes:
        provider = route.get("provider", "")
        model = route.get("model", "")
        if provider and model:
            out.setdefault(provider, [])
            if model not in out[provider]:
                out[provider].append(model)
    return out


def enumerate_provider(route):
    """Live model list for one seed route's provider ([] on any failure)."""
    try:
        wire = route.get("wire", "openai")
        if wire in ("openai", "opencode", "zen"):
            return openai_compatible_models(route.get("base_url", ""),
                                            route.get("api_key", ""))
        if wire == "gemini":
            return gemini_models(route.get("api_key", ""))
        return []
    except Exception:
        return []


def get_inventory(routes, refresh=False):
    """{provider: [model, ...]} = union(live API, seed-declared).

    Cache hit skips HTTP; refresh=True or expiry re-enumerates per
    provider; a failing provider keeps its seed models only.
    """
    seeds = seed_models(routes)
    creds = provider_credential(routes)
    current = now()
    out = {}
    for provider, route in creds.items():
        entry = _cache.get(provider)
        if not refresh and entry and entry[0] > current:
            out[provider] = sorted(set(entry[1]) | set(seeds.get(provider, [])))
            continue
        live = enumerate_provider(route)
        merged = sorted(set(live) | set(seeds.get(provider, [])))
        _cache[provider] = (current + CACHE_TTL, merged)
        out[provider] = merged
    return out


def clear_cache():
    _cache.clear()
