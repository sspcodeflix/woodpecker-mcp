"""MCP server: graph-backed tools over stdio or HTTP.

Each query tool rebuilds the graph from live sources first (WP_AUTO_REFRESH=1,
default), then answers from Cypher. Set WP_AUTO_REFRESH=0 to query a snapshot
ingested separately.
"""
from mcp.server.fastmcp import FastMCP

from . import build, config
from .diagnose import diagnose as _diagnose
from .store import open_store

mcp = FastMCP("woodpecker-graph")

_store = None


def store():
    global _store
    if _store is None:
        _store = open_store()
    return _store


def _ready():
    """Rebuild from live sources if enabled. Return an error dict on connector failure, else None."""
    if not config.AUTO_REFRESH:
        return None
    try:
        build.refresh(store())
        return None
    except Exception as e:
        return {"error": f"could not refresh graph from sources: {e}"}


@mcp.tool()
def woodpecker_get_topology() -> dict:
    """Return the materialized service dependency graph: every service, its
    current status, and the services it depends on. Call first to establish the
    causal structure before diagnosing. status in {healthy, erroring, unhealthy,
    restarting, hung, down}; monitoring='MISSING' flags a possible blind spot."""
    return _ready() or {"services": store().topology()}


@mcp.tool()
def woodpecker_diagnose_root_cause() -> dict:
    """Localize the ROOT CAUSE deterministically: the DEEPEST failing service,
    the unhealthy one whose own dependencies are all healthy. Everything
    unhealthy above it is cascading fallout. Returns root cause(s), the causal
    chain per cascading symptom, blast radius, blind spots, and a page/no-page
    verdict, distinguishing a real outage from an observability blind spot
    (metrics missing but the service responds). Exact and repeatable, unlike
    per-investigation inference."""
    err = _ready()
    return err or _diagnose(store())


@mcp.tool()
def woodpecker_get_blast_radius(service: str, direction: str = "upstream") -> dict:
    """Transitive dependency closure of a service over DEPENDS_ON edges.
    direction='upstream': services that transitively depend on this one (its
    blast radius if it fails). direction='downstream': everything it relies on
    (trace toward a deeper root cause)."""
    if direction not in ("upstream", "downstream"):
        return {"error": "direction must be 'upstream' or 'downstream'"}
    err = _ready()
    if err:
        return err
    if not store().has_service(service):
        return {"error": f"unknown service: {service}"}
    return {"service": service, "direction": direction,
            "related": store().blast_radius(service, direction)}


@mcp.tool()
def woodpecker_get_service_health(service: str) -> dict:
    """Detailed health snapshot for one service: status, container state/health,
    restarts, 5xx error rate, db pg_up, scrape health, and blind-spot flag."""
    err = _ready()
    if err:
        return err
    h = store().service_health(service)
    return h or {"error": f"unknown service: {service}"}


@mcp.tool()
def woodpecker_detect_blind_spots() -> dict:
    """List observability blind spots: services that are healthy but have no live
    Prometheus scrape target (lost visibility, NOT an outage - do not page)."""
    return _ready() or {
        "blind_spots": store().blind_spots(),
        "note": "blind spots = lost monitoring, not outages; do not page on these",
    }


def run(transport="stdio", host="0.0.0.0", port=8000):
    if transport in ("http", "streamable-http"):
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
