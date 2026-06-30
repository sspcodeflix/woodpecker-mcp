"""Populate the graph store - from live connectors (refresh) or a static file
(ingest_static, for offline relationship study / tests).
"""
from . import config
from .schema import derive_container_status, worse
from .sources import metrics_source, topology_source


def _collapse(services, containers):
    """Fold container-level state into one logical health per service."""
    svc = {s["name"]: {"name": s["name"], "role": s.get("role", "app"), "status": "unknown"}
           for s in services}
    for c in containers:
        s = svc.get(c["service"])
        if not s:
            continue
        st = derive_container_status(c["state"], c["health"])
        s["status"] = st if s["status"] == "unknown" else worse(s["status"], st)
        s["container_state"] = c["state"]
        s["container_health"] = c["health"]
        s["restarts"] = c["restarts"]
    return svc


def refresh(store, topology=None, metrics=None):
    """Rebuild the graph from live sources. Always-current (cheap at this scale)."""
    topology = topology or topology_source()
    metrics = metrics or metrics_source()
    services, containers, dep_edges = topology.discover()
    svc = _collapse(services, containers)

    # scrape targets -> monitoring health + blind-spot flag
    monitored = set()
    try:
        targets = metrics.targets()
    except Exception:
        targets = []
    for t in targets:
        if t["service"] in svc:
            svc[t["service"]]["scrape_health"] = t["health"]
            monitored.add(t["service"])
    for name in config.MONITORED_SERVICES:
        if name in svc and name not in monitored:
            svc[name]["monitoring"] = "MISSING"

    # database liveness (the exporter target may be up while the DB itself is down)
    try:
        up = metrics.db_up()
        if up is not None and "db" in svc:
            svc["db"]["pg_up"] = up
            if not up and svc["db"]["status"] == "healthy":
                svc["db"]["status"] = "unhealthy"
    except Exception:
        pass

    # per-service error rate -> "erroring" (functional failure container health misses)
    try:
        for name, rate in metrics.error_rates().items():
            if name in svc:
                svc[name]["error_rate"] = rate
                if rate > config.ERROR_RATE_THRESHOLD and svc[name]["status"] == "healthy":
                    svc[name]["status"] = "erroring"
    except Exception:
        pass

    _ingest(store, svc.values(), dep_edges)
    return store


def ingest_static(store, data):
    """Populate from a plain dict (e.g. parsed JSON) - for studying relationships
    without live infra. Shape: {"services": [{name, role, status, error_rate,
    monitoring, ...}], "dependencies": [[src, dst], ...]}."""
    services = data.get("services", [])
    edges = [tuple(e) for e in data.get("dependencies", [])]
    _ingest(store, services, edges)
    return store


def _ingest(store, services, dep_edges):
    services = list(services)
    names = {s["name"] for s in services}
    with store.lock:
        store.reset()
        for s in services:
            store.upsert_service(s)
        for src, dst in dep_edges:
            if src in names and dst in names:
                store.add_dependency(src, dst)
