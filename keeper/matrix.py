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


def _cell_sort_key(cell):
    ok_first = 0 if cell["state"] in _OK_STATES else 1
    return (ok_first, -(cell.get("aa_score") or 0.0))


def build_matrix(connections, probe_states=None, aa_scores=None):
    """Email x provider rows; cells ordered ok-first then AA desc."""
    probe_states = probe_states or {}
    aa_scores = aa_scores or {}
    grouped = group_connections_by_email(connections)
    rows = []
    providers = []
    seen_providers = set()
    for email in grouped["emails"]:
        cells = {}
        for conn in grouped["by_email"][email]:
            provider = conn.get("provider") or "unknown"
            if provider not in seen_providers:
                seen_providers.add(provider)
                providers.append({"id": provider})
            model = conn.get("model")
            cells.setdefault(provider, []).append({
                "connection_id": str(conn.get("id")),
                "name": connection_display_name(conn),
                "model": model,
                "state": probe_states.get(str(conn.get("id")), "unknown"),
                "aa_score": aa_scores.get(model) if model else None,
            })
        for plist in cells.values():
            plist.sort(key=_cell_sort_key)
        rows.append({"email": email, "cells": cells})
    return {
        "emails": grouped["emails"],
        "rows": rows,
        "providers": providers,
        "diagnostics": {
            "unassigned": grouped["unassigned"],
            "skipped_inactive": grouped["skipped_inactive"],
        },
    }
