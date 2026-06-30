# woodpecker-mcp

[![CI](https://github.com/sspcodeflix/woodpecker-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sspcodeflix/woodpecker-mcp/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![backend](https://img.shields.io/badge/graph-FalkorDB-ff4438)

A **materialized service dependency graph as an MCP toolset.** It gives an LLM
agent such as [HolmesGPT](https://github.com/robusta-dev/holmesgpt) the one thing
those agents do not keep: a persistent, queryable graph of how services depend on
each other, so root cause is a deterministic graph traversal instead of a
per-investigation guess.

Holmes stays vanilla. It launches woodpecker-mcp as a subprocess (or connects
over HTTP) and discovers its tools. No fork, no custom image.

---

## Why this exists

HolmesGPT markets a "Runtime Dependency Graph", but its source has no graph data
structure, no graph database, and no graph-traversal code. It infers relationships
on the fly from traces, Kubernetes owner-refs, and metric labels during each
investigation, then discards them; root cause is whatever the model concludes via
a "five whys" prompt. That is deliberate (freshness, statelessness, breadth), but
it has costs that a materialized graph removes:

| | Holmes (inferred) | woodpecker-mcp (materialized) |
|---|---|---|
| Where relationships live | model context, one investigation | a graph database (FalkorDB) |
| Root cause | reasoned per run (non-deterministic) | deepest-failing-service, one Cypher query (exact, repeatable) |
| Blast radius | re-derived each time | variable-length path traversal |
| Explore it yourself | no | yes (browser UI + Cypher) |
| Blind-spot detection | no | yes |

---

## How it works

```mermaid
flowchart TD
    H[MCP client / HolmesGPT] -->|stdio or HTTP| S[server.py - FastMCP tools]
    S --> B[build.refresh]
    B -->|reads| C[sources/: Topology + Metrics<br/>docker / k8s / prometheus]
    B -->|ingests| G[(FalkorDB<br/>materialized graph)]
    S --> D[diagnose.py]
    D -->|Cypher: roots, blast radius, paths| G
```

The graph is rebuilt from live sources on each query (or from a static topology
file), then all reasoning runs as Cypher against the store.

---

## Quickstart

```bash
# 1. Run the graph backend (FalkorDB; browser UI on :3000)
docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest

# 2. Install Holmes + woodpecker-mcp (same venv = simplest)
pip install holmesgpt woodpecker-mcp

# 3. Point HolmesGPT at it
holmes ask "find the root cause of the current incident" \
  -t examples/holmesgpt-toolset.yaml
```

---

## Install

```bash
pip install woodpecker-mcp                 # FalkorDB backend (default)
pip install "woodpecker-mcp[kuzu]"         # add the embedded Kuzu backend
```

woodpecker-mcp stores the graph in **FalkorDB**. Run one:

```bash
docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest   # :3000 = graph browser
# or: docker compose up -d        # FalkorDB + woodpecker-mcp together
```

---

## Wire into HolmesGPT

For a `pip install holmesgpt` CLI, integration is **config-only** - HolmesGPT
already ships the MCP client, so there is no Holmes code, fork, or plugin to
build. The whole flow:

```
pip install holmesgpt woodpecker-mcp  ->  run FalkorDB  ->  drop in one YAML  ->  holmes ask -t
```

### Fast path (`woodpecker-mcp setup`)

```bash
pip install holmesgpt woodpecker-mcp
woodpecker-mcp init        # guided Q&A -> writes a filled-in .env
woodpecker-mcp setup       # start FalkorDB, wait until ready, register the toolset
holmes ask "find the root cause of the current incident"
```

- **`init`** asks a few questions (graph backend, topology, metrics) with numbered
  options and defaults, then writes a `.env` containing only the vars your choices
  need - no hand-editing a full template. `--defaults` (or `-y`) skips the prompts
  and writes the commented template instead; `--force` overwrites an existing
  `.env`. When stdin is not a TTY (CI, piped) it falls back to the template
  automatically, so it never hangs.
- **`setup`** starts FalkorDB in Docker, polls it until it answers
  (`FalkorDB is ready`), then merges the `woodpecker-graph` toolset into
  `~/.holmes/config.yaml` (backing up the original; re-running is safe). Flags:
  `--config PATH` to target a different Holmes config, `--no-falkordb` if you run
  FalkorDB yourself. The generated `command:` is an **absolute path**, so it works
  even when Holmes lives in a different virtualenv.

After `setup`, `holmes ask` picks up the toolset automatically - no `-t` needed.

Prefer to wire it by hand (the stdio toolset YAML), or run it in-cluster over HTTP
for the Holmes Operator? Both are covered step by step - with every env var, a
validation command, and troubleshooting - in the integration guide:
**[docs/CONFIGURATION.md](docs/CONFIGURATION.md#step-3---integrate-with-holmesgpt)**
(Method A = stdio, Method B = HTTP). The ready-made toolset file is
[`examples/holmesgpt-toolset.yaml`](examples/holmesgpt-toolset.yaml).

---

## Tools

| Tool | Returns |
|---|---|
| `woodpecker_get_topology` | the materialized graph (services, status, deps) |
| `woodpecker_diagnose_root_cause` | deepest-failing-service + causal chains + blast radius + blind spots + page verdict |
| `woodpecker_get_blast_radius(service, direction)` | transitive upstream/downstream closure |
| `woodpecker_get_service_health(service)` | per-service drill-down |
| `woodpecker_detect_blind_spots` | healthy-but-unmonitored services |

---

## Explore the graph

FalkorDB ships a browser. Open **http://localhost:3000**, pick the `woodpecker`
graph, and run OpenCypher visually, e.g. the blast radius of `db`:

```cypher
MATCH (a:Service)-[:DEPENDS_ON*1..20]->(:Service {name:'db'}) RETURN a
```

Or from Python:

```python
from falkordb import FalkorDB
g = FalkorDB(host="localhost", port=6379).select_graph("woodpecker")
g.query("MATCH (a:Service)-[:DEPENDS_ON*1..20]->(:Service {name:'db'}) "
        "RETURN a.name").result_set
```

---

## CLI (standalone)

```bash
woodpecker-mcp topology      # rebuild + print the service graph
woodpecker-mcp diagnose      # rebuild + print root-cause analysis
woodpecker-mcp refresh       # rebuild the graph only
woodpecker-mcp serve [--http] [--port 8000]   # run the MCP server

# study a topology offline, no live infra:
woodpecker-mcp ingest examples/topology.example.json
WP_AUTO_REFRESH=0 woodpecker-mcp diagnose
```

---

## Configuration

All settings have defaults; override only what points at your infra, in the
`env:` block of the toolset YAML. For local CLI runs, `woodpecker-mcp init`
generates a `.env` from a guided Q&A (or `cp .env.sample .env` to edit the full
template) - the app loads `.env` from the working directory (exported env vars and
the toolset `env:` block take precedence).

The common ones (full table with per-backend deep-dives lives in the guide):

| Var | Default | Meaning |
|---|---|---|
| `WP_GRAPH_BACKEND` | `falkordb` | graph backend: `falkordb` (server) or `kuzu` (embedded) |
| `WP_TOPOLOGY` | `docker` | topology connector: `docker`, `k8s`, or `traces` (Jaeger) |
| `WP_METRICS_BACKEND` | `prometheus` | metrics connector: `prometheus` or `datadog` |
| `WP_PROM_URL` | `http://localhost:9091` | Prometheus URL (or any PromQL-compatible backend) |
| `WP_MONITORED_SERVICES` | `web,orders,db` | services expected to be scraped (blind-spot check) |
| `WP_AUTO_REFRESH` | `1` | `0` queries a static snapshot without rebuilding |

Topology and metrics are independent seams - mix `docker`/`k8s`/`traces` with
`prometheus`/`datadog`, and override the metric queries to match your
instrumentation. **Every variable, with per-backend deep-dives and validation
commands, is in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).**

---

## Graph backends

Default is **FalkorDB**: actively maintained, OpenCypher, with a browser UI for
exploring the graph. **Kuzu** is an embedded fallback
(`pip install "woodpecker-mcp[kuzu]"`, `WP_GRAPH_BACKEND=kuzu`); its upstream was
archived in October 2025 (final release `0.11.3`, pinned). The `GraphStore`
interface keeps either backend, and Neo4j/Memgraph drop in the same way.

---

## Layout

```
woodpecker_mcp/
  server.py      FastMCP tools, stdio + HTTP
  store.py       GraphStore interface; FalkorGraphStore (default), KuzuGraphStore
  build.py       rebuild the graph from sources, or ingest a static topology
  diagnose.py    deterministic root-cause verdict from store queries
  sources/       TopologySource (docker, k8s, traces) + MetricsSource (prometheus, datadog)
  schema.py      status vocabulary
  cli.py         init | setup | serve | topology | diagnose | refresh | ingest
  scaffold.py    init/setup helpers (.env, FalkorDB, Holmes config)
examples/        holmesgpt-toolset.yaml, k8s-deployment.yaml, topology.example.json
docs/            CONFIGURATION.md
tests/           unit tests (test_*.py) + smoke_mcp.py (integration)
```

---

## Development

```bash
pip install -e ".[dev]"                      # pytest + ruff
pre-commit install                           # ruff lint on every commit
pre-commit install --hook-type pre-push      # unit tests before every push

pytest                                       # unit tests - no services needed
ruff check .                                 # lint  (ruff format . to auto-format)
```

Unit tests (`tests/test_*.py`) run offline against fakes. The stdio integration
check needs a live FalkorDB:

```bash
docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest
python tests/smoke_mcp.py
```

---

## License

woodpecker-mcp is licensed under [Apache-2.0](LICENSE). It connects to FalkorDB
as a client and does not redistribute it; FalkorDB itself is SSPL-licensed
(source-available) - fine for self-hosting, relevant only if you offer FalkorDB
as a managed service.
