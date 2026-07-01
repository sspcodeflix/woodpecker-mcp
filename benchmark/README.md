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

## HolmesGPT comparison

Contrast an LLM-only agent with the graph. On the *same live fault*, run
HolmesGPT with the woodpecker toolset disabled vs enabled and score how much of
the ground-truth blast radius each recovers - and whether it names the same set
each run.

Holmes is prompted to end its answer with `ROOT: <svc>` and `AFFECTED: <svc,...>`
so recall is scored precisely and fairly - same model and prompt in both arms,
only the toolset differs.

Setup: put your key in `benchmark/.env` (`DEEPSEEK_API_KEY=...`), and make sure
`woodpecker-mcp setup` has added the `woodpecker-graph` toolset to
`~/.holmes/config.yaml` (the runner flips its `enabled` flag per arm).

```bash
./compare.sh db          # crashloop-db, 3 runs per arm; prints recall + consistency
./compare.sh catalog     # blast radius 5
./compare.sh orders      # blast radius 3
```

Because it costs LLM calls, keep it to a few scenarios across blast sizes (db=11,
catalog=5, orders=3) rather than the full catalog. Individual pieces:

```bash
./run.sh alone "<prompt>" out.log      # one arm, one run
python score_holmes.py --fault db logs/db-alone-*.log
```
