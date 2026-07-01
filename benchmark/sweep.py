#!/usr/bin/env python3
"""Drive the fault catalog and score woodpecker against ground truth.

For each scenario: inject the fault, wait for it to settle, then check whether
woodpecker names the right root, covers the full blast radius, and is
deterministic - then heal. Writes results.csv and prints a table.

    python sweep.py                    # whole catalog (slow; ~1 min/scenario)
    python sweep.py --id crashloop-db  # one scenario
    python sweep.py --settle 45 --runs 3

Requires a live ecommerce-demo cluster and woodpecker-mcp configured (see README).
"""
import argparse
import csv
import json
import subprocess
import time

from scenarios import catalog
from topology import blast_radius
from verify import _app_edges, _wp


def _run(argv):
    subprocess.run(argv, check=True, capture_output=True, text=True)


def score(scn, settle, runs):
    _run(scn["inject"])
    time.sleep(settle)
    try:
        topo = _wp("topology")
        diags = [_wp("diagnose") for _ in range(runs)]
    finally:
        _run(scn["heal"])

    svc = scn["service"]
    roots = {r["service"] for r in diags[0].get("root_causes", [])}
    blinds = set(diags[0].get("blind_spots", []))
    disc_edges = _app_edges(topo)
    expected = set(scn["expected_blast"])
    got = blast_radius(svc, edges=disc_edges)
    coverage = 100.0 if not expected else 100.0 * len(expected & got) / len(expected)
    deterministic = len({json.dumps(d, sort_keys=True) for d in diags}) == 1

    if scn["mechanism"] == "blind_spot":
        detected = svc in blinds
        facet = "blind-spot"
    else:
        detected = svc in roots
        facet = "root"

    return {
        "id": scn["id"], "service": svc, "mechanism": scn["mechanism"], "facet": facet,
        "expected_detect": scn["expected_detect"], "detected": detected,
        "blast_expected": len(expected), "blast_coverage_pct": round(coverage),
        "deterministic": deterministic, "verdict": diags[0].get("verdict"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="run a single scenario by id")
    ap.add_argument("--settle", type=int, default=45, help="seconds to wait after inject")
    ap.add_argument("--recover", type=int, default=20, help="seconds to wait after heal")
    ap.add_argument("--runs", type=int, default=3, help="diagnose repeats for determinism")
    ap.add_argument("--out", default="results.csv")
    args = ap.parse_args()

    scenarios = [s for s in catalog() if not args.id or s["id"] == args.id]
    if not scenarios:
        raise SystemExit(f"no scenario with id={args.id!r}")

    rows = []
    for s in scenarios:
        print(f"-> {s['id']} (inject, wait {args.settle}s, score) ...", flush=True)
        try:
            rows.append(score(s, args.settle, args.runs))
        except Exception as e:
            rows.append({"id": s["id"], "service": s["service"], "mechanism": s["mechanism"],
                         "facet": "-", "expected_detect": s["expected_detect"], "detected": False,
                         "blast_expected": len(s["expected_blast"]), "blast_coverage_pct": 0,
                         "deterministic": False, "verdict": f"ERROR: {str(e)[:40]}"})
        time.sleep(args.recover)  # let the heal recover before the next inject

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'id':30} {'facet':10} {'detected':9} {'blast%':7} {'determ':7}")
    print("-" * 70)
    for r in rows:
        flag = "" if r["detected"] == r["expected_detect"] else "  <-- unexpected"
        print(f"{r['id']:30} {r['facet']:10} {str(r['detected']):9} "
              f"{str(r['blast_coverage_pct']):7} {str(r['deterministic']):7}{flag}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
