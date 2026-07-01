#!/usr/bin/env python3
"""Score HolmesGPT run logs for blast-radius recall and consistency.

Holmes is prompted to end each answer with `ROOT: <svc>` and
`AFFECTED: <svc, ...>`. This parses those, compares the affected set to the
ground-truth blast radius, and reports recall per run + consistency across runs.

    python score_holmes.py --fault db logs/db-alone-*.log
"""
import argparse
import re

from topology import all_services, blast_radius


def parse(text):
    known = all_services()
    root, affected = None, set()
    for line in text.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        m = re.search(r"\bROOT:\s*([a-z0-9-]+)", line, re.I)
        if m:
            root = m.group(1).strip().lower()
        m = re.search(r"\bAFFECTED:\s*(.+)", line, re.I)
        if m:
            affected = {t.strip().lower() for t in re.split(r"[,\s]+", m.group(1)) if t.strip()}
    return root, (affected & known)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault", required=True)
    ap.add_argument("logs", nargs="+")
    args = ap.parse_args()

    truth = blast_radius(args.fault)
    print(f"ground-truth blast radius of {args.fault} ({len(truth)}): {', '.join(sorted(truth))}\n")
    print(f"{'log':34} {'root ok':8} {'recall':8} captured")
    print("-" * 70)

    recalls, sets = [], []
    for path in args.logs:
        with open(path) as f:
            root, affected = parse(f.read())
        hit = truth & affected
        recall = 100.0 if not truth else 100.0 * len(hit) / len(truth)
        recalls.append(recall)
        sets.append(frozenset(hit))
        name = path.rsplit("/", 1)[-1]
        print(f"{name[:34]:34} {str(root == args.fault):8} {recall:5.0f}%   {len(hit)}/{len(truth)}")

    mean = sum(recalls) / len(recalls)
    consistent = len(set(sets)) == 1
    print(f"\nmean recall: {mean:.0f}%   |   consistency across {len(args.logs)} runs: "
          f"{'IDENTICAL affected set' if consistent else f'{len(set(sets))} different sets'}")


if __name__ == "__main__":
    main()
