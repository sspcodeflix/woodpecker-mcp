#!/usr/bin/env python3
"""Verify woodpecker captures a reliable 360 view of a live incident.

For a given faulted service it checks, against the ecommerce-demo ground truth:
  1. topology  - did woodpecker discover the full dependency graph?
  2. blast radius - does the discovered graph yield the complete affected set?
  3. root cause - does diagnose name the faulted service as root?
  4. determinism - is the diagnose output identical across N runs?

Requires `woodpecker-mcp` on PATH and configured for the cluster (WP_TOPOLOGY=k8s
etc., via env or a .env in the working directory), with the fault already live.

    python verify.py --fault db --runs 5
"""
import argparse
import json
import subprocess
import sys

from topology import INFRA, blast_radius, ground_edges


def _wp(*args):
    out = subprocess.check_output(["woodpecker-mcp", *args], text=True)
    return json.loads(out)


def _app_edges(topology_json):
    """Discovered (dependent, dependency) edges between app services only."""
    edges = set()
    for svc in topology_json.get("services", []):
        a = svc["service"]
        if a in INFRA:
            continue
        for b in svc.get("depends_on", []):
            if b not in INFRA:
                edges.add((a, b))
    return edges


def _pct(part, whole):
    return 100.0 if not whole else 100.0 * len(part) / len(whole)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault", required=True, help="faulted service (expected root)")
    ap.add_argument("--runs", type=int, default=5, help="diagnose repetitions for determinism")
    args = ap.parse_args()

    try:
        topo = _wp("topology")
    except Exception as e:
        sys.exit(f"could not run `woodpecker-mcp topology` - is it configured and the cluster up?\n{e}")

    # 1. topology coverage
    truth_edges = ground_edges()
    disc_edges = _app_edges(topo)
    missing = truth_edges - disc_edges
    extra = disc_edges - truth_edges

    print("== 1. topology coverage ==")
    print(f"   ground-truth app edges : {len(truth_edges)}")
    print(f"   discovered             : {len(disc_edges)}   ({_pct(truth_edges & disc_edges, truth_edges):.0f}% of truth)")
    print(f"   missing edges          : {sorted(missing) or 'none'}")
    if extra:
        print(f"   unexpected edges       : {sorted(extra)}")

    # 2. blast radius (from the discovered graph vs ground truth)
    expected = blast_radius(args.fault)
    discovered = blast_radius(args.fault, edges=disc_edges)
    print(f"\n== 2. blast radius (fault = {args.fault}) ==")
    print(f"   expected affected ({len(expected)}) : {', '.join(sorted(expected))}")
    print(f"   woodpecker captured      : {len(expected & discovered)}/{len(expected)}  "
          f"({_pct(expected & discovered, expected):.0f}% coverage)")
    print(f"   missed                   : {sorted(expected - discovered) or 'none'}")

    # 3 + 4. root cause correctness and determinism
    diags = []
    for _ in range(args.runs):
        try:
            diags.append(_wp("diagnose"))
        except Exception as e:
            sys.exit(f"`woodpecker-mcp diagnose` failed: {e}")

    roots_ok = sum(args.fault in [r["service"] for r in d.get("root_causes", [])] for d in diags)
    canonical = {json.dumps(d, sort_keys=True) for d in diags}
    print(f"\n== 3. root cause ({args.runs} runs) ==")
    print(f"   named '{args.fault}' as root : {roots_ok}/{args.runs}")
    print(f"   verdict                  : {diags[0].get('verdict')} (page={diags[0].get('page')})")
    print(f"\n== 4. determinism ({args.runs} runs) ==")
    print(f"   identical diagnose output : {'YES' if len(canonical) == 1 else f'NO - {len(canonical)} variants'}")

    ok = not missing and expected <= discovered and roots_ok == args.runs and len(canonical) == 1
    print(f"\n{'PASS' if ok else 'CHECK'}: woodpecker "
          f"{'reliably captured the full 360 view' if ok else 'did not fully match ground truth (see above)'}.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
