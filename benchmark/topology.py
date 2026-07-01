"""Ground-truth dependency graph of the ecommerce-demo platform.

This mirrors the topology defined in ecommerce-demo/scripts/gen_k8s.py. The
benchmark scores woodpecker's discovered graph and blast radius against this
known truth, so "did it capture the full 360 view" is measured, not asserted.
"""

# service -> the services it depends on (HTTP downstreams + database)
TOPOLOGY = {
    "gateway":         ["web", "mobilebff"],
    "web":             ["catalog", "cart", "orders", "users", "recommendations"],
    "mobilebff":       ["catalog", "orders"],
    "catalog":         ["db"],
    "cart":            ["catalog", "inventory"],
    "orders":          ["payments", "inventory", "shipping", "notifications", "db"],
    "users":           ["db"],
    "recommendations": ["catalog"],
    "payments":        ["ledger"],
    "inventory":       ["db"],
    "shipping":        ["notifications"],
    "notifications":   ["email"],
    "ledger":          ["db"],
    "email":           [],
    "db":              [],
}

# Non-app services woodpecker also discovers in the namespace; edges touching
# these are infrastructure, not part of the app graph we score.
INFRA = {"db-exporter", "prometheus", "loadgen"}


def all_services():
    return set(TOPOLOGY)


def ground_edges():
    """The set of (dependent, dependency) app edges."""
    return {(s, d) for s, deps in TOPOLOGY.items() for d in deps}


def blast_radius(service, edges=None):
    """Services transitively affected if `service` fails = everything that
    depends on it (directly or through the chain). Uses the ground-truth graph
    unless `edges` is supplied (e.g. woodpecker's discovered edges)."""
    edges = ground_edges() if edges is None else edges
    dependents = {}
    for dep, dependency in edges:
        dependents.setdefault(dependency, set()).add(dep)
    affected, stack = set(), [service]
    while stack:
        cur = stack.pop()
        for d in dependents.get(cur, ()):
            if d not in affected:
                affected.add(d)
                stack.append(d)
    return affected


if __name__ == "__main__":
    # self-check: db should transitively affect 11 services (all but email,
    # notifications, shipping, which never touch the database).
    br = blast_radius("db")
    expected = {"catalog", "orders", "users", "inventory", "ledger", "web",
                "cart", "mobilebff", "recommendations", "payments", "gateway"}
    assert br == expected, f"blast_radius(db) wrong: {br ^ expected}"
    print(f"ground truth OK: {len(all_services())} services, "
          f"{len(ground_edges())} edges, blast_radius(db) = {len(br)} affected")
