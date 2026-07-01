# Benchmark: does woodpecker capture a reliable 360 view?

This measures the thing that matters in production: on a live incident, does
woodpecker **reliably and completely** capture the operational picture - root
cause, the full blast radius, and the same answer every time - scored against a
**known ground-truth topology**, not by eyeballing.

It is not a "fewer tool calls" benchmark. Tool count is fault-dependent and
misleading; completeness and determinism of the impact picture are not.

## What it checks

For a faulted service, `verify.py` compares woodpecker's output to the ground
truth in [`topology.py`](topology.py):

1. **Topology coverage** - did woodpecker discover the full dependency graph?
2. **Blast radius** - does that graph yield the complete set of affected services?
3. **Root cause** - does `diagnose` name the faulted service as root?
4. **Determinism** - is the diagnose output identical across N runs?

## Prerequisites

- The [ecommerce-demo](https://github.com/sspcodeflix/ecommerce-demo) app deployed
  on a cluster (kind, 14 services + Postgres + Prometheus).
- `woodpecker-mcp` installed and reachable to a graph backend.
- `kubectl` pointed at that cluster; Prometheus port-forwarded (`WP_PROM_URL`).
- `cp .env.sample .env` and fill it in.

## Run it

```bash
python topology.py            # sanity: prints the ground-truth summary

./inject.sh db                # crashloop Postgres (cascade, root = db)
sleep 45                      # let the cascade + metrics settle
python verify.py --fault db --runs 5
./inject.sh heal
```

Expected on a healthy setup: 100% topology coverage, 100% blast-radius coverage
(all 11 db-dependents), root = db on every run, identical output across runs.

Sweep the fault depth to show the picture holds regardless of where the fault is:

```bash
for f in orders payments db; do
  ./inject.sh "$f"; sleep 45
  python verify.py --fault "$f" --runs 5
  ./inject.sh heal; sleep 20
done
```

## Fault catalog (25+ scenarios)

[`scenarios.py`](scenarios.py) defines a matrix of failure modes x graph
positions - crashloop, bad image, readiness failure, OOM kill, blind spot, and
the honest "scale-to-0" limit - across the topology (leaf to entry point). List
them:

```bash
python scenarios.py        # 25 scenarios: id, service, mechanism, blast size
```

[`sweep.py`](sweep.py) drives the catalog: for each scenario it injects the
fault, waits, scores whether woodpecker names the right root, covers the full
blast radius, and is deterministic - then heals - and writes `results.csv`:

```bash
python sweep.py --id crashloop-db      # one scenario
python sweep.py                        # whole catalog (~1 min each)
```

The two `scalezero-*` rows are expected to under-detect (0 pods reads as
"unknown") - they document a real limit, not a pass.

## HolmesGPT comparison (optional)

To contrast with an LLM-only agent, run HolmesGPT with the woodpecker toolset
disabled vs enabled on the *same live fault* and compare how much of the
ground-truth blast radius each recovers, and whether it is the same across runs.
`run.sh` / `score_holmes.py` drive that arm (see the project blog for the writeup).
