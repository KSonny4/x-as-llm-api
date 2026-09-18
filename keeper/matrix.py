"""Quota-matrix builder (stdlib only). Ported grouping semantics from
llm-quota (src/omni.js); probe-state cells per design §3.

Cells carry probe state keyed by connection id (default "unknown") plus an
optional AA score used ONLY to order ties among probe-ok entries. No quota
percents, no packs, no billing.
"""
import re

_ANGLED_RE = re.compile(r"<([^<>\s]+@[^<>\s]+)>")
_BARE_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

_OK_STATES = ("ok",)

# Display bound for inventory-only columns per provider: firehose
# providers stay complete in packs; the matrix shows at most this many
# unprobed columns each and reports the overflow in
# diagnostics.inventory_more.
MAX_INVENTORY_COLUMNS = 20


def extract_owner_email(value):
    """Canonical lowercase owner address from any typed format, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    angled = _ANGLED_RE.search(text)
    if angled:
        return angled.group(1).lower()
    bare = _BARE_RE.search(text)
    if bare:
        return bare.group(0).lower()
    return None


def connection_owner_email(connection):
    if not isinstance(connection, dict):
        return None
    return extract_owner_email(connection.get("email"))


def connection_display_name(connection):
    if not isinstance(connection, dict):
        return "unknown"
    for key in ("name", "email", "displayName", "id"):
        value = connection.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def is_active_connection(connection):
    if not isinstance(connection, dict):
        return True
    for key in ("isActive", "is_active"):
        if key in connection:
            return bool(connection[key])
    return True


def group_connections_by_email(connections):
    """Rows keyed by canonical owner email; leftovers reported, never dropped."""
    by_email = {}
    unassigned = []
    skipped_inactive = []
    for conn in connections or []:
        if not is_active_connection(conn):
            skipped_inactive.append({"id": str(conn.get("id") or "unknown"), "provider": conn.get("provider")})
            continue
        owner = connection_owner_email(conn)
        embedded = extract_owner_email(conn.get("name") if isinstance(conn, dict) else None)
        candidate = owner or embedded
        if not candidate:
            unassigned.append({
                "id": str(conn.get("id")) if isinstance(conn, dict) else "unknown",
                "provider": conn.get("provider") if isinstance(conn, dict) else None,
                "name": connection_display_name(conn),
            })
            continue
        key = candidate.lower()
        by_email.setdefault(key, []).append(conn)
    emails = sorted(by_email, key=str.lower)
    return {
        "by_email": by_email,
        "emails": emails,
        "unassigned": unassigned,
        "skipped_inactive": skipped_inactive,
    }


L1_OK = ("ok", "limited", "misconfigured")


def dual_verdict(res):
    """Compare L1 (curl) vs L2 (opencode CLI) for one probe_route result.
    divergent ⟺ L1-fail + L2-pass on the same route+run (the 'weird'
    case). L2 runs only on L1 non-ok, so l2 == 'not-run' whenever L1
    passed; report-path results never carry l2 and never diverge."""
    res = res or {}
    state = res.get("state", "unknown")
    detail = res.get("detail") or {}
    l1 = detail.get("l1", state if state in L1_OK else "unknown")
    if state == "degraded":
        l2 = "pass"
    elif state == "down":
        l2 = "fail"
    else:
        l2 = "not-run"
    return {
        "state": state,
        "l1": l1,
        "l2": l2,
        "divergent": l1 not in L1_OK and l2 == "pass",
        "checked_at": res.get("checked_at", ""),
    }


def _cell_sort_key(cell):
    ok_first = 0 if cell["state"] in _OK_STATES else 1
    return (ok_first, -(cell.get("aa_score") or 0.0))


def aa_lookup(aa_scores, model):
    """AA score for a model string: full string first, then the last
    path segment (provider/model ids like openrouter's match AA slugs
    on the bare name). Misses (internal/placeholder ids) stay None and
    sort last in the open-provider view."""
    if not model or not aa_scores:
        return None
    if model in aa_scores:
        return aa_scores[model]
    base = model.rsplit("/", 1)[-1]
    return aa_scores.get(base)


def column_id(provider, model):
    """Matrix column key: the model string when present, else provider id.
    Seed-only fallbacks (no model yet) keep the old provider column."""
    model = model.strip() if isinstance(model, str) else ""
    if model:
        return model
    return provider or "unknown"


def build_matrix(connections, probe_states=None, aa_scores=None,
                 probe_detail=None, inventory=None):
    """Email x model rows; cells ordered ok-first then AA desc.
    probe_states maps connection id -> state string (legacy) while
    probe_detail optionally maps the same id -> full probe_route result;
    cells then also carry l1/l2/divergent and diagnostics lists the
    divergent ids.
    inventory optionally maps provider -> [model, ...] (live-enumerated);
    inventory-only models become unprobed columns so new models are
    visible before any probe runs."""
    probe_states = probe_states or {}
    probe_detail = probe_detail or {}
    aa_scores = aa_scores or {}
    grouped = group_connections_by_email(connections)
    rows = []
    providers = []
    seen_columns = set()

    def ensure_column(col_id, provider, model):
        if col_id not in seen_columns:
            seen_columns.add(col_id)
            providers.append({"id": col_id, "provider": provider,
                              "model": model, "probed": False})
    inventory_more = {}
    divergent = []
    for email in grouped["emails"]:
        cells = {}
        for conn in grouped["by_email"][email]:
            provider = conn.get("provider") or "unknown"
            model = conn.get("model") or ""
            col = column_id(provider, model)
            ensure_column(col, provider, model)
            cid = str(conn.get("id"))
            det = probe_detail.get(cid)
            if det is None:
                raw = probe_states.get(cid, "unknown")
                verdict = {"state": raw, "l1": raw, "l2": "not-run",
                           "divergent": False}
            else:
                verdict = dual_verdict(det)
            if verdict["divergent"] and cid not in divergent:
                divergent.append(cid)
            cells.setdefault(col, []).append({
                "connection_id": cid,
                "name": connection_display_name(conn),
                "model": model,
                "state": verdict["state"],
                "l1": verdict["l1"],
                "l2": verdict["l2"],
                "divergent": verdict["divergent"],
                "checked_at": (det.get("checked_at", "")
                                if isinstance(det, dict) else ""),
                "aa_score": aa_lookup(aa_scores, model),
            })
        for plist in cells.values():
            plist.sort(key=_cell_sort_key)
        rows.append({"email": email, "cells": cells})
    # Unassigned connections have no row cells — scan their dual verdicts
    # too so divergence is visible regardless of email grouping.
    for cid, det in probe_detail.items():
        if cid not in divergent and dual_verdict(det)["divergent"]:
            divergent.append(cid)
    for provider, models in (inventory or {}).items():
        added = 0
        skipped = 0
        for model in models or []:
            col = column_id(provider, model)
            if col in seen_columns:
                continue
            # Display bound: firehose providers (openrouter: 400+) stay in
            # packs; the matrix keeps at most N unprobed columns each and
            # reports the overflow so nothing is silently hidden.
            if added >= MAX_INVENTORY_COLUMNS:
                skipped += 1
                continue
            ensure_column(col, provider, model if isinstance(model, str)
                          else "")
            added += 1
        if skipped:
            inventory_more[provider] = skipped
    probed = set()
    for row in rows:
        for col, entries in row["cells"].items():
            if entries:
                probed.add(col)
    for entry in providers:
        entry["probed"] = entry["id"] in probed
    return {
        "emails": grouped["emails"],
        "rows": rows,
        "providers": providers,
        "diagnostics": {
            "unassigned": grouped["unassigned"],
            "skipped_inactive": grouped["skipped_inactive"],
            "divergent": sorted(divergent),
            "inventory_more": inventory_more,
        },
    }
