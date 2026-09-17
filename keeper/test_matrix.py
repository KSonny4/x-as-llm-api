"""Ported grouping cases (llm-quota/test/matrix.test.js) + probe-state cells.

Design §3: rows = owner emails (email field -> email-in-name fallback,
case-insensitive dedupe); cells carry probe state + optional AA score
(tiebreak among probe-ok only). No quota percents, no packs, no billing.
"""
import unittest

from matrix import (
    build_matrix,
    connection_owner_email,
    extract_owner_email,
    group_connections_by_email,
    is_active_connection,
)


class GroupingTest(unittest.TestCase):
    def test_groups_by_email_case_insensitive_deduped(self):
        res = group_connections_by_email([
            {"id": "a", "provider": "muse-code", "email": "Ksonny4@Gmail.com", "name": "Muse A"},
            {"id": "a2", "provider": "codex", "email": "ksonny4@gmail.com", "name": "Codex"},
            {"id": "b", "provider": "codex", "email": "ksonny@seznam.cz", "name": "Codex"},
            {"id": "c", "provider": "codex", "email": "someone-else@example.com", "name": "Other"},
            {"id": "d", "provider": "claude", "email": None, "name": "no-email"},
        ])
        self.assertEqual(res["emails"], ["ksonny4@gmail.com", "ksonny@seznam.cz", "someone-else@example.com"])
        self.assertEqual(len(res["by_email"]["ksonny4@gmail.com"]), 2)
        self.assertEqual(len(res["by_email"]["ksonny@seznam.cz"]), 1)
        self.assertEqual(len(res["unassigned"]), 1)
        self.assertEqual(res["unassigned"][0]["id"], "d")

    def test_falls_back_to_email_in_name(self):
        res = group_connections_by_email([
            {"id": "k", "provider": "opencode", "email": None, "name": "petr1kubelka@gmail.com"},
            {"id": "z", "provider": "opencode-zen", "email": None, "name": "opencode-zen ksonny@apple.com"},
        ])
        self.assertEqual(len(res["by_email"]["petr1kubelka@gmail.com"]), 1)
        self.assertEqual(len(res["by_email"]["ksonny@apple.com"]), 1)
        self.assertEqual(res["unassigned"], [])

    def test_bare_names_go_unassigned(self):
        res = group_connections_by_email([
            {"id": "g", "provider": "gemini", "email": None, "name": "ksonny4"},
            {"id": "m", "provider": "moonshot", "email": None, "name": "main"},
        ])
        self.assertEqual(res["emails"], [])
        self.assertEqual(res["by_email"], {})
        self.assertEqual(len(res["unassigned"]), 2)

    def test_skips_inactive_and_reports(self):
        self.assertFalse(is_active_connection({"isActive": 0}))
        self.assertFalse(is_active_connection({"is_active": False}))
        self.assertTrue(is_active_connection({}))
        res = group_connections_by_email([
            {"id": "x", "provider": "muse-code", "email": "ksonny4@gmail.com", "isActive": 0},
        ])
        self.assertEqual(res["emails"], [])
        self.assertEqual(len(res["skipped_inactive"]), 1)

    def test_owner_email_trims_and_nulls_blanks(self):
        self.assertEqual(connection_owner_email({"email": "  a@b.cz "}), "a@b.cz")
        self.assertIsNone(connection_owner_email({"email": "  "}))
        self.assertIsNone(connection_owner_email({}))

    def test_extracts_angled_and_decorated_addresses(self):
        self.assertEqual(extract_owner_email("ksonny4@gmail.com"), "ksonny4@gmail.com")
        self.assertEqual(extract_owner_email("  KSonny4@Gmail.Com  "), "ksonny4@gmail.com")
        self.assertEqual(extract_owner_email("Petr <ksonny4@gmail.com>"), "ksonny4@gmail.com")
        self.assertEqual(extract_owner_email("ksonny4@gmail.com (work)"), "ksonny4@gmail.com")
        self.assertIsNone(extract_owner_email("  "))
        self.assertIsNone(extract_owner_email(None))


class MatrixTest(unittest.TestCase):
    def test_cells_carry_probe_state_unknown_by_default(self):
        data = build_matrix([
            {"id": "z", "provider": "claude", "name": "Claude Z", "email": "kubelkatropkova@seznam.cz"},
        ], probe_states={})
        row = next(r for r in data["rows"] if r["email"] == "kubelkatropkova@seznam.cz")
        self.assertEqual(len(row["cells"]["claude"]), 1)
        self.assertEqual(row["cells"]["claude"][0]["state"], "unknown")

    def test_cells_join_probe_state_by_connection_id(self):
        data = build_matrix([
            {"id": "a", "provider": "muse-code", "name": "A", "email": "ksonny4@gmail.com"},
            {"id": "b", "provider": "muse-code", "name": "B", "email": "ksonny4@gmail.com"},
        ], probe_states={"a": "ok", "b": "down"})
        row = data["rows"][0]
        states = {c["connection_id"]: c["state"] for c in row["cells"]["muse-code"]}
        self.assertEqual(states, {"a": "ok", "b": "down"})

    def test_aa_orders_ties_among_probe_ok_only(self):
        conns = [
            {"id": "low", "provider": "zen", "name": "L", "email": "a@b.cz", "model": "m-low"},
            {"id": "high", "provider": "zen", "name": "H", "email": "a@b.cz", "model": "m-high"},
            {"id": "dead", "provider": "zen", "name": "D", "email": "a@b.cz", "model": "m-dead"},
        ]
        states = {"low": "ok", "high": "ok", "dead": "down"}
        scores = {"m-low": 50.0, "m-high": 90.0, "m-dead": 99.0}
        data = build_matrix(conns, probe_states=states, aa_scores=scores)
        ids = [c["connection_id"] for c in data["rows"][0]["cells"]["zen"]]
        # ok first ordered by AA desc; down last despite highest AA
        self.assertEqual(ids, ["high", "low", "dead"])
        self.assertEqual(data["rows"][0]["cells"]["zen"][0]["aa_score"], 90.0)


if __name__ == "__main__":
    unittest.main()
