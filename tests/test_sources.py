from woodpecker_mcp.sources.datadog import DatadogMetricsSource
from woodpecker_mcp.sources.docker_compose import _references_host
from woodpecker_mcp.sources.kubernetes import _pod_status
from woodpecker_mcp.sources.prometheus import PrometheusSource
from woodpecker_mcp.sources.traces import JaegerTopology


def test_references_host_no_false_substring():
    assert _references_host("http://orders:8001", "orders") is True
    assert _references_host("postgres://db:5432/x", "db") is True
    assert _references_host("http://db_exporter:9187", "db") is False  # db != db_exporter
    assert _references_host("SOMETHING=other", "orders") is False


def test_pod_status_crashloop():
    pod = {"status": {"phase": "Running", "containerStatuses": [
        {"restartCount": 5, "ready": False, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}
    assert _pod_status(pod) == ("restarting", "unhealthy", 5)


def test_pod_status_running_ready():
    pod = {"status": {"phase": "Running", "containerStatuses": [
        {"restartCount": 0, "ready": True, "state": {"running": {}}}]}}
    assert _pod_status(pod) == ("running", "healthy", 0)


def test_pod_status_failed():
    pod = {"status": {"phase": "Failed", "containerStatuses": [
        {"restartCount": 0, "ready": False, "state": {}}]}}
    assert _pod_status(pod) == ("exited", "unhealthy", 0)


def test_error_rates_parses_and_rounds(monkeypatch):
    src = PrometheusSource("http://x")
    monkeypatch.setattr(src, "_query", lambda expr: [
        {"metric": {"service": "web"}, "value": [0, "0.12345"]},
        {"metric": {"service": "db"}, "value": [0, "0"]},
    ])
    assert src.error_rates() == {"web": 0.123, "db": 0.0}


def test_error_rates_honors_custom_label(monkeypatch):
    src = PrometheusSource("http://x", error_rate_label="app")
    monkeypatch.setattr(src, "_query", lambda expr: [
        {"metric": {"app": "checkout"}, "value": [0, "2"]},
        {"metric": {"service": "web"}, "value": [0, "9"]},  # different label -> skipped
    ])
    assert src.error_rates() == {"checkout": 2.0}


def test_db_up_true_false_unknown(monkeypatch):
    src = PrometheusSource("http://x")
    monkeypatch.setattr(src, "_query", lambda expr: [{"metric": {}, "value": [0, "1"]}])
    assert src.db_up() is True
    monkeypatch.setattr(src, "_query", lambda expr: [{"metric": {}, "value": [0, "0"]}])
    assert src.db_up() is False
    monkeypatch.setattr(src, "_query", lambda expr: [])
    assert src.db_up() is None


def test_db_up_disabled_issues_no_query(monkeypatch):
    src = PrometheusSource("http://x", db_up_query="")
    called = []
    monkeypatch.setattr(src, "_query", lambda expr: called.append(expr) or [])
    assert src.db_up() is None
    assert called == []


# --- Datadog metrics source (non-PromQL backend) -------------------------------

def test_datadog_error_rates_parses_tag_set_and_scope(monkeypatch):
    src = DatadogMetricsSource(site="datadoghq.com", api_key="k", app_key="a")
    monkeypatch.setattr(src, "_query", lambda q: [
        {"tag_set": ["service:web", "env:prod"], "pointlist": [[0, 1.0], [1, 2.5]]},
        {"tag_set": ["service:db"], "pointlist": [[0, None]]},          # all-null -> skipped
        {"scope": "service:orders,env:prod", "tag_set": [], "pointlist": [[0, 0.0]]},
    ])
    assert src.error_rates() == {"web": 2.5, "orders": 0.0}


def test_datadog_targets_from_emitting_services(monkeypatch):
    src = DatadogMetricsSource(api_key="k", app_key="a")
    monkeypatch.setattr(src, "_query", lambda q: [
        {"tag_set": ["service:web"], "pointlist": [[0, 0.0]]},
    ])
    assert src.targets() == [
        {"job": "web", "service": "web", "health": "up", "endpoint": "datadog"},
    ]


def test_datadog_db_up(monkeypatch):
    src = DatadogMetricsSource(db_up_query="max:postgresql.up{*}")
    monkeypatch.setattr(src, "_query", lambda q: [{"tag_set": [], "pointlist": [[0, 1]]}])
    assert src.db_up() is True
    monkeypatch.setattr(src, "_query", lambda q: [{"tag_set": [], "pointlist": [[0, 0]]}])
    assert src.db_up() is False
    monkeypatch.setattr(src, "_query", lambda q: [])
    assert src.db_up() is None


def test_datadog_db_up_disabled_issues_no_query(monkeypatch):
    src = DatadogMetricsSource(db_up_query="")
    called = []
    monkeypatch.setattr(src, "_query", lambda q: called.append(q) or [])
    assert src.db_up() is None
    assert called == []


# --- Jaeger trace topology source ----------------------------------------------

def test_jaeger_topology_builds_edges_and_healthy_services(monkeypatch):
    src = JaegerTopology(url="http://j")
    monkeypatch.setattr(src, "_dependencies", lambda: [
        {"parent": "web", "child": "orders", "callCount": 10},
        {"parent": "orders", "child": "db", "callCount": 5},
        {"parent": "web", "child": "web", "callCount": 1},      # self-call dropped
        {"parent": "", "child": "db"},                           # malformed -> skipped
    ])
    services, containers, edges = src.discover()
    assert {s["name"] for s in services} == {"web", "orders", "db"}
    assert edges == [("orders", "db"), ("web", "orders")]
    # traces give no health; services are up so the metrics source can set status
    assert all(c["state"] == "running" and c["health"] == "healthy" for c in containers)
