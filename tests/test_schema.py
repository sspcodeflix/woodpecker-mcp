from woodpecker_mcp.schema import BAD_STATUSES, STATUS_ORDER, derive_container_status, worse


def test_derive_container_status():
    assert derive_container_status("running", "healthy") == "healthy"
    assert derive_container_status("running", None) == "healthy"
    assert derive_container_status("running", "unhealthy") == "unhealthy"
    assert derive_container_status("exited", None) == "down"
    assert derive_container_status(None, None) == "down"
    assert derive_container_status("missing", None) == "down"
    assert derive_container_status("paused", None) == "hung"
    assert derive_container_status("restarting", None) == "restarting"
    assert derive_container_status("weird", None) == "unknown"


def test_worse_picks_more_severe():
    assert worse("down", "healthy") == "down"
    assert worse("healthy", "down") == "down"
    assert worse("erroring", "healthy") == "erroring"
    assert worse("healthy", "healthy") == "healthy"
    assert worse("unknown", "down") == "down"  # down sorts worst


def test_bad_statuses():
    assert set(BAD_STATUSES) < set(STATUS_ORDER)
    assert "healthy" not in BAD_STATUSES
