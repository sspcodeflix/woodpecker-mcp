"""Fault-injection catalog for the ecommerce-demo benchmark.

25+ scenarios spanning failure modes x graph positions. Each names how to inject
and heal the fault via kubectl, the expected root cause, whether woodpecker is
expected to detect it, and (computed from the ground-truth topology) the blast
radius. `sweep.py` drives the catalog and scores woodpecker against it.
"""
from topology import blast_radius

NS = "ecommerce"


# --- mechanism templates: return (inject_argv, heal_argv) for kubectl ---

def _patch(svc, op):
    return ["kubectl", "-n", NS, "patch", "deployment", svc, "--type=json", "-p=" + op]


def crashloop(svc):
    if svc == "db":  # postgres: feed an invalid config directive
        add = '[{"op":"add","path":"/spec/template/spec/containers/0/args","value":["-c","bogus_setting=on"]}]'
        rem = '[{"op":"remove","path":"/spec/template/spec/containers/0/args"}]'
    else:            # app: replace the command with one that exits immediately
        add = '[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","exit 1"]}]'
        rem = '[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
    return _patch(svc, add), _patch(svc, rem)


def bad_image(svc):
    inj = ["kubectl", "-n", NS, "set", "image", f"deployment/{svc}", f"{svc}=ecommerce-demo-svc:nope"]
    heal = ["kubectl", "-n", NS, "set", "image", f"deployment/{svc}", f"{svc}=ecommerce-demo-svc:latest"]
    return inj, heal


def readiness_fail(svc):
    to = '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"%s"}]'
    return _patch(svc, to % "/nope"), _patch(svc, to % "/healthz")


def oomkill(svc):
    to = '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"%s"}]'
    return _patch(svc, to % "8Mi"), _patch(svc, to % "64Mi")


def scale_zero(svc):
    return (["kubectl", "-n", NS, "scale", "deployment", svc, "--replicas=0"],
            ["kubectl", "-n", NS, "scale", "deployment", svc, "--replicas=1"])


def blind_spot(svc):
    to = '[{"op":"replace","path":"/spec/template/metadata/annotations/prometheus.io~1scrape","value":"%s"}]'
    return _patch(svc, to % "false"), _patch(svc, to % "true")


# --- the catalog: (id, service, mechanism, expected_detect) -----------------
# expected_detect=False marks honest limits woodpecker's current signals miss.
_MATRIX = [
    # crashloop across the whole topology (leaf -> entry), to prove blast radius
    # is captured at every depth
    ("crashloop-db",            "db",              crashloop,       True),
    ("crashloop-email",         "email",           crashloop,       True),
    ("crashloop-ledger",        "ledger",          crashloop,       True),
    ("crashloop-notifications", "notifications",   crashloop,       True),
    ("crashloop-catalog",       "catalog",         crashloop,       True),
    ("crashloop-inventory",     "inventory",       crashloop,       True),
    ("crashloop-payments",      "payments",        crashloop,       True),
    ("crashloop-shipping",      "shipping",        crashloop,       True),
    ("crashloop-users",         "users",           crashloop,       True),
    ("crashloop-recommendations", "recommendations", crashloop,     True),
    ("crashloop-orders",        "orders",          crashloop,       True),
    ("crashloop-cart",          "cart",            crashloop,       True),
    ("crashloop-mobilebff",     "mobilebff",       crashloop,       True),
    ("crashloop-web",           "web",             crashloop,       True),
    ("crashloop-gateway",       "gateway",         crashloop,       True),
    # failure-mode variety on the same targets
    ("badimage-catalog",        "catalog",         bad_image,       True),
    ("badimage-orders",         "orders",          bad_image,       True),
    ("readiness-web",           "web",             readiness_fail,  True),
    ("readiness-mobilebff",     "mobilebff",       readiness_fail,  True),
    ("oomkill-payments",        "payments",        oomkill,         True),
    ("oomkill-inventory",       "inventory",       oomkill,         True),
    # observability facet
    ("blindspot-recommendations", "recommendations", blind_spot,    True),
    ("blindspot-users",         "users",           blind_spot,      True),
    # honest limits: 0 pods reads as "unknown", not "down"
    ("scalezero-orders",        "orders",          scale_zero,      False),
    ("scalezero-db",            "db",              scale_zero,      False),
]


def catalog():
    out = []
    for sid, svc, mech, detect in _MATRIX:
        inj, heal = mech(svc)
        out.append({
            "id": sid,
            "service": svc,
            "mechanism": mech.__name__,
            "expected_root": svc,
            "expected_blast": sorted(blast_radius(svc)),
            "expected_detect": detect,
            "inject": inj,
            "heal": heal,
        })
    return out


if __name__ == "__main__":
    rows = catalog()
    print(f"{len(rows)} fault scenarios\n")
    print(f"{'id':30} {'service':15} {'mechanism':16} {'detect':7} blast")
    print("-" * 78)
    for r in rows:
        print(f"{r['id']:30} {r['service']:15} {r['mechanism']:16} "
              f"{'yes' if r['expected_detect'] else 'LIMIT':7} {len(r['expected_blast'])}")
