#!/usr/bin/env python3
"""Inject or heal a catalog scenario by id (single source of truth = scenarios).

    python fault.py inject crashloop-db
    python fault.py heal   crashloop-db
"""
import subprocess
import sys

from scenarios import catalog

if len(sys.argv) != 3 or sys.argv[1] not in ("inject", "heal"):
    sys.exit("usage: fault.py {inject|heal} <scenario-id>")

action, sid = sys.argv[1], sys.argv[2]
scn = next((s for s in catalog() if s["id"] == sid), None)
if not scn:
    sys.exit(f"unknown scenario id: {sid}")

subprocess.run(scn["inject" if action == "inject" else "heal"], check=True)
print(f"{action} {sid} -> service={scn['service']}, "
      f"expected blast radius = {len(scn['expected_blast'])}")
