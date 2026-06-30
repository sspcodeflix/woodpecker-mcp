import threading

import woodpecker_mcp.build as build
from woodpecker_mcp.build import _collapse, ingest_static, refresh


class CaptureStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.services, self.deps = {}, []

    def reset(self):
        self.services, self.deps = {}, []

    def upsert_service(self, s):
        self.services[s["name"]] = s

    def add_dependency(self, a, b):
        self.deps.append((a, b))


def test_collapse_worst_wins():
    services = [{"name": "web", "role": "app"}]
    containers = [
        {"name": "web-1", "service": "web", "state": "running", "health": "healthy", "restarts": 0},
        {"name": "web-2", "service": "web", "state": "exited", "health": None, "restarts": 3},
    ]
    assert _collapse(services, containers)["web"]["status"] == "down"


def test_ingest_static_skips_unknown_dep_targets():
    store = CaptureStore()
    ingest_static(store, {
        "services": [{"name": "web", "status": "erroring"}, {"name": "db", "status": "down"}],
        "dependencies": [["web", "db"], ["web", "ghost"]],
    })
    assert set(store.services) == {"web", "db"}
    assert ("web", "db") in store.deps
    assert ("web", "ghost") not in store.deps


class FakeTopology:
    def discover(self):
        services = [{"name": "web", "role": "app"}, {"name": "db", "role": "database"}]
        containers = [
            {"name": "web-1", "service": "web", "state": "running", "health": "healthy", "restarts": 0},
            {"name": "db-1", "service": "db", "state": "exited", "health": None, "restarts": 1},
        ]
        return services, containers, [("web", "db")]


class FakeMetrics:
    def targets(self):
        return [{"job": "web", "service": "web", "health": "up", "endpoint": "x"}]

    def error_rates(self):
        return {}

    def db_up(self):
        return None


def test_refresh_status_and_blind_spot(monkeypatch):
    monkeypatch.setattr(build.config, "MONITORED_SERVICES", {"web", "db"})
    store = CaptureStore()
    refresh(store, FakeTopology(), FakeMetrics())
    assert store.services["db"]["status"] == "down"          # from the exited container
    assert store.services["db"]["monitoring"] == "MISSING"    # monitored but no scrape target
    assert store.services["web"].get("monitoring") != "MISSING"
    assert ("web", "db") in store.deps
