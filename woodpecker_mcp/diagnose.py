"""Deterministic root-cause analysis over the materialized graph.

ROOT CAUSE = the DEEPEST failing service: unhealthy, with all its own
dependencies healthy. Everything else unhealthy is cascading fallout. Computed
from the store's Cypher queries.
"""


def diagnose(store):
    roots = store.roots()
    blind = store.blind_spots()

    if not roots:
        if blind:
            return {
                "verdict": "no-incident", "page": False,
                "root_causes": [], "cascading": [], "blind_spots": blind,
                "summary": (f"NO INCIDENT - observability blind spot. {', '.join(blind)} "
                            "is healthy but not being scraped; visibility is lost, the "
                            "service itself is fine. Do NOT page."),
            }
        return {"verdict": "healthy", "page": False, "root_causes": [], "cascading": [],
                "blind_spots": [], "summary": "All services healthy - no incident."}

    root_names = [r["service"] for r in roots]
    root_causes = [{
        "service": r["service"], "status": r["status"], "error_rate": r["error_rate"],
        "why": f"{(r['status'] or '?').upper()} and all of its own dependencies are healthy",
    } for r in roots]

    cascading = []
    for c in store.cascading():
        chain = None
        for rn in root_names:
            p = store.path(c["service"], rn)
            if p:
                chain = " -> ".join(f"{n['name']}[{(n['status'] or '?').upper()}]" for n in p)
                break
        cascading.append({"service": c["service"], "status": c["status"], "chain": chain})

    return {
        "verdict": "incident", "page": True,
        "root_causes": root_causes, "cascading": cascading, "blind_spots": blind,
        "summary": (f"INCIDENT - root cause: {', '.join(root_names)} (deepest failing "
                    f"service in the dependency chain). {len(cascading)} downstream "
                    f"service(s) are cascading symptoms. PAGE."),
    }
