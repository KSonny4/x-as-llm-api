"""Process RSS/CPU metrics exist in /metrics (stdlib resource only)."""
from server import metrics_view, process_metrics_lines


def test_process_metrics_present_and_sane():
    out = metrics_view({})
    assert "keeper_process_rss_bytes" in out
    assert "keeper_process_cpu_seconds_total" in out


def test_process_metrics_values_positive():
    lines = dict(l.split(" ", 1) for l in process_metrics_lines())
    assert int(lines["keeper_process_rss_bytes"]) > 0
    assert float(lines["keeper_process_cpu_seconds_total"]) >= 0
