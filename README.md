# woodpecker-mcp

A **materialized service dependency graph as an MCP toolset.** It gives an LLM
agent (e.g. [HolmesGPT](https://github.com/robusta-dev/holmesgpt)) the one thing
those agents don't keep: a persistent, **queryable** graph of how your services
depend on each other — so root cause is a *deterministic graph traversal*, not a
per-investigation guess.

## Why this exists

HolmesGPT markets a *"Runtime Dependency Graph"*, but — verified against its
source — it has **no graph data structure, no graph database, and no
graph-traversal code**. It *infers* relationships on the fly from traces / k8s
owner-refs / metric labels during each investigation and throws them away. Root
cause is whatever the LLM concludes via a *"five whys"* prompt.

That inference approach is deliberate (freshness, statelessness, breadth across
60+ integrations), but it costs you:

| | Holmes (inferred) | woodpecker-mcp (materialized) |
|---|---|---|
| Where relationships live | LLM context, one investigation | A graph database (Kùzu) |
| Root cause | LLM reasons per-run (non-deterministic) | **Deepest-failing-service**, one Cypher query (exact, repeatable) |
| Blast radius | re-derived each time | variable-length path traversal |
| Explore it yourself | ❌ can't | ✅ open the DB, run Cypher |
| Blind-spot detection | ❌ | ✅ |

woodpecker-mcp plugs into Holmes (or any MCP client) and adds exactly that
materialized layer. Holmes stays vanilla — it just launches this as a subprocess.

## Install

```bash
pip install woodpecker-mcp          # (from this repo: pip install -e .)
```

Dependencies: `mcp`, `kuzu` (embedded — no server to run).

## Use it

**As a CLI** (points at live infra; defaults match the Woodpecker demo_env):

```bash
woodpecker-mcp topology      # materialize the graph + print services & deps
woodpecker-mcp diagnose      # deterministic root-cause analysis
woodpecker-mcp refresh       # just rebuild the graph in the DB
```

**Study relationships offline** — ingest a static topology and query it:

```bash
woodpecker-mcp ingest examples/topology.example.json
WP_AUTO_REFRESH=0 woodpecker-mcp diagnose
# -> root cause: db (deepest failing); web & orders cascade; reporting = blind spot
```

**As an MCP server** (stdio for local, HTTP for in-cluster):

```bash
woodpecker-mcp serve                 # stdio (how Holmes launches it)
woodpecker-mcp serve --http --port 8000
```

### Tools exposed

- `woodpecker_get_topology` — the materialized graph (services, status, deps)
- `woodpecker_diagnose_root_cause` — deepest-failing-service + causal chains + blast radius + blind spots + page verdict
- `woodpecker_get_blast_radius(service, direction)` — transitive upstream/downstream closure
- `woodpecker_get_service_health(service)` — per-service drill-down
- `woodpecker_detect_blind_spots` — healthy-but-unmonitored services

## Study the relationships directly (the point of using a graph DB)

The graph lives in a real database at `WP_KUZU_PATH`. Open it and run Cypher —
something Holmes' ephemeral inference can never let you do:

```python
import kuzu
con = kuzu.Connection(kuzu.Database("./woodpecker.kuzu"))

# Deepest failing service = the root cause (unhealthy, nothing bad beneath it):
con.execute("""
  MATCH (s:Service) WHERE s.status IN ['down','hung','unhealthy','restarting','erroring']
  AND NOT EXISTS { MATCH (s)-[:DEPENDS_ON*1..20]->(d:Service)
                   WHERE d.status IN ['down','hung','unhealthy','restarting','erroring'] }
  RETURN s.name, s.status
""").get_as_df()

# Blast radius: everything that (transitively) depends on db
con.execute("MATCH (a:Service)-[:DEPENDS_ON*1..20]->(:Service {name:'db'}) "
            "RETURN DISTINCT a.name").get_as_df()
```

Point Kùzu Explorer at the same directory for a visual of the graph.

## Wire into HolmesGPT

See [`examples/holmesgpt-toolset.yaml`](examples/holmesgpt-toolset.yaml):

```bash
holmes ask "why is web returning 503s? find the root cause" \
  -t examples/holmesgpt-toolset.yaml
```

For the in-cluster Operator, run `woodpecker-mcp serve --http` as its own
Deployment and point Holmes at it with `mode: streamable-http` (no Holmes image
change — the same way Robusta ships its own MCP servers).

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `WP_KUZU_PATH` | `./woodpecker.kuzu` | where the graph DB lives |
| `WP_TOPOLOGY` | `docker` | topology connector (`docker`; `k8s` is a drop-in addition) |
| `WP_PROM_URL` | `http://localhost:9091` | Prometheus base URL |
| `WP_COMPOSE_PROJECT` | `demo_env` | docker compose project to inspect |
| `WP_AUTO_REFRESH` | `1` | `0` = query a static snapshot without rebuilding |
| `WP_MONITORED_SERVICES` | `web,orders,db` | services expected to be scraped (blind-spot check) |

## Architecture

```
MCP client (HolmesGPT)
   │  stdio / http  (server.py — FastMCP tools)
   ▼
build.refresh ──reads──> sources/  (TopologySource + MetricsSource: docker, prometheus)
   │ ingests
   ▼
store.py  GraphStore (abstract) ──> KuzuGraphStore  (Cypher: roots, blast radius, paths)
   ▲
diagnose.py  composes the deterministic verdict from store queries
```

`GraphStore` is backend-agnostic — swap Kùzu for Neo4j/Memgraph by implementing
the same interface. The connector seam (`sources/`) means swapping Docker for
Kubernetes is a new `TopologySource`, not a rewrite.

## Status

Spike. Working: Kùzu graph store, Docker + Prometheus connectors, deterministic
diagnosis, MCP server (stdio/http), CLI, static ingest, smoke test
([`tests/smoke_mcp.py`](tests/smoke_mcp.py)). Not yet: k8s `TopologySource`
(interface ready), packaging to PyPI, auth on the HTTP transport.
