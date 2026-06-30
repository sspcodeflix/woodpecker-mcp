from woodpecker_mcp.diagnose import diagnose


class FakeStore:
    def __init__(self, roots=(), cascading=(), blind=(), paths=None):
        self._roots, self._cascading = list(roots), list(cascading)
        self._blind, self._paths = list(blind), paths or {}

    def roots(self): return self._roots
    def cascading(self): return self._cascading
    def blind_spots(self): return self._blind
    def path(self, src, dst): return self._paths.get((src, dst), [])


def test_healthy():
    d = diagnose(FakeStore())
    assert d["verdict"] == "healthy"
    assert d["page"] is False
    assert d["root_causes"] == [] and d["cascading"] == []


def test_blind_spot_is_no_incident():
    d = diagnose(FakeStore(blind=["db"]))
    assert d["verdict"] == "no-incident"
    assert d["page"] is False
    assert d["blind_spots"] == ["db"]
    assert "Do NOT page" in d["summary"]


def test_incident_root_cause_and_chain():
    store = FakeStore(
        roots=[{"service": "db", "status": "down", "error_rate": None}],
        cascading=[{"service": "web", "status": "erroring"}],
        paths={("web", "db"): [{"name": "web", "status": "erroring"},
                               {"name": "db", "status": "down"}]},
    )
    d = diagnose(store)
    assert d["verdict"] == "incident" and d["page"] is True
    assert [r["service"] for r in d["root_causes"]] == ["db"]
    assert d["cascading"][0]["service"] == "web"
    assert d["cascading"][0]["chain"] == "web[ERRORING] -> db[DOWN]"
    assert "root cause: db" in d["summary"]
