"""Guard the benchmark ground truth (topology + fault catalog) in CI, so code
changes can't silently break the numbers the benchmark scores against.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

import scenarios  # noqa: E402
import topology  # noqa: E402


def test_blast_radius_db():
    assert topology.blast_radius("db") == {
        "catalog", "orders", "users", "inventory", "ledger", "web",
        "cart", "mobilebff", "recommendations", "payments", "gateway",
    }


def test_leaf_and_entry_blast_radius():
    assert topology.blast_radius("gateway") == set()   # nothing depends on the entry point
    assert "gateway" in topology.blast_radius("web")   # gateway transitively depends on web


def test_catalog_has_at_least_25_scenarios():
    assert len(scenarios.catalog()) >= 25


def test_scenario_blast_matches_topology_and_kubectl_shape():
    for s in scenarios.catalog():
        assert s["expected_blast"] == sorted(topology.blast_radius(s["service"]))
        assert s["inject"][0] == "kubectl" and s["heal"][0] == "kubectl"
