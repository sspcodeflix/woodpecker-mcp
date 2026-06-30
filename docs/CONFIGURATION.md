# Integration & Configuration Guide

How to connect woodpecker-mcp to your infrastructure and HolmesGPT. Every step
below is copy-paste with a verification command and the output you should see.

---

## Supported environments

| Environment | Service + dependency discovery | Live health source | Status |
|---|---|---|---|
| Kubernetes | Automatic (`kubectl`) | Prometheus / PromQL-compatible / Datadog | **Supported** |
| Docker Compose host | Automatic (`docker inspect`) | Prometheus / PromQL-compatible / Datadog | **Supported** |
| Distributed traces (Jaeger) | Real call edges (`/api/dependencies`) | Pair with a metrics source | **Supported** |
| Any (declarative) | You provide a JSON topology file | From the file (snapshot) | **Supported** |

Pick the row that matches you, then follow the matching steps below.

Topology (the dependency edges) and metrics (the health signals) are independent
seams - mix and match:

- **Topology** (`WP_TOPOLOGY`): `docker`, `k8s`, or `traces` (Jaeger). The trace
  source gives real call edges but no health, so pair it with a metrics source.
- **Metrics** (`WP_METRICS_BACKEND`): `prometheus` (default) or `datadog`.
  "PromQL-compatible" means `prometheus` also works against Thanos, Cortex,
  Grafana Mimir, VictoriaMetrics, or Grafana Cloud - just set `WP_PROM_URL`.

Backends not yet built in (New Relic, CloudWatch) are added as new `MetricsSource`
implementations behind the same interface - see
[Other backends](#other-backends-datadog-traces).

---

## Requirements

- Python **3.10+** on the host/image where the server runs
- A reachable **FalkorDB** server (the graph backend) - `docker run -p 6379:6379 -p 3000:3000 falkordb/falkordb`, or `docker compose up -d`
- For the Docker Compose row: the `docker` CLI on `PATH`, with access to the Docker socket
- For the Kubernetes row: `kubectl` on `PATH` + a kubeconfig (local) or, in a pod, an in-cluster ServiceAccount with read access to deployments + pods
- Network access from that host to your Prometheus
- HolmesGPT installed (`pip install holmesgpt`) - for the integration in step 3

---

## Step 1 - Install and verify

```bash
pip install woodpecker-mcp           # from this repo: pip install -e .
```

Verify:

```bash
woodpecker-mcp --help
```

Expected output (the command list):

```
woodpecker-mcp CLI.

  woodpecker-mcp serve [--http] [--host 0.0.0.0] [--port 8000]   # MCP server (stdio default)
  woodpecker-mcp refresh                          # rebuild the graph from live sources
  woodpecker-mcp ingest <file.json>               # load a static topology (offline study)
  woodpecker-mcp diagnose                          # refresh + print root-cause analysis
  woodpecker-mcp topology                          # refresh + print the service graph
```

---

## Step 2 - Set the configuration values

Set these as environment variables. In the HolmesGPT integration (step 3) they
go in the toolset's `env:` block. **Set only the ones marked "set this"; the rest
have working defaults.**

> Tip: `woodpecker-mcp init` asks these as a guided Q&A (numbered options +
> defaults) and writes a filled-in `.env` with only the vars your choices need.
> Use `woodpecker-mcp init --defaults` for the full commented template instead.

| Variable | Default | Action | Example value |
|---|---|---|---|
| `WP_GRAPH_BACKEND` | `falkordb` | Optional | `falkordb` or `kuzu` |
| `WP_FALKOR_HOST` | `localhost` | Set this (in-cluster) | `falkordb` (the Service name) |
| `WP_FALKOR_PORT` | `6379` | Optional | `6379` |
| `WP_PROM_URL` | `http://localhost:9091` | **Set this** | `http://prometheus-operated.monitoring.svc.cluster.local:9090` |
| `WP_MONITORED_SERVICES` | `web,orders,db` | **Set this** | `web,orders,checkout,payments,db` |
| `WP_TOPOLOGY` | `docker` | Set if not Docker | `docker`, `k8s`, or `traces` |
| `WP_METRICS_BACKEND` | `prometheus` | Set for Datadog | `prometheus` or `datadog` |
| `WP_COMPOSE_PROJECT` | `demo_env` | Set this (Docker row) | `my-app` |
| `WP_K8S_NAMESPACE` | `default` | Set this (k8s row) | `demo` |
| `WP_K8S_CONTEXT` | (empty) | Optional (k8s) | `kind-woodpecker`; empty = in-cluster ServiceAccount |
| `WP_KUZU_PATH` | `./woodpecker.kuzu` | Optional | `/data/woodpecker.kuzu` |
| `WP_AUTO_REFRESH` | `1` | Set `0` for declarative row | `0` |
| `WP_ERROR_RATE_THRESHOLD` | `0.05` | Optional (tuning) | `0.1` |
| `WP_ERROR_RATE_QUERY` | demo 5xx query | Set if metric names differ | `sum(rate(http_server_requests_seconds_count{outcome="SERVER_ERROR"}[1m])) by (app)` |
| `WP_ERROR_RATE_LABEL` | `service` | Set if grouped by another label | `app` |
| `WP_DB_UP_QUERY` | `pg_up` | Set per DB exporter; empty disables | `mysql_up` |
| `WP_HTTP_HOST` | `0.0.0.0` | Optional (HTTP mode) | `0.0.0.0` |

### `WP_PROM_URL` - exactly what to put

The base URL of your Prometheus HTTP API: scheme + host + port, no trailing path.
It is the same address you open in a browser to reach the Prometheus UI.

| Where your Prometheus runs | Value to use |
|---|---|
| Local Docker Compose (this demo) | `http://localhost:9091` |
| Prometheus on a VM / bare metal | `http://<HOST_IP>:9090` |
| Kubernetes, kube-prometheus-stack (Prometheus Operator) | `http://prometheus-operated.<ns>.svc.cluster.local:9090` |
| Kubernetes, `prometheus-community/prometheus` Helm chart | `http://prometheus-server.<ns>.svc.cluster.local:80` |
| Thanos / Mimir / Grafana Cloud | the Query Frontend / `prometheus`-API endpoint URL |

**Validate it before going further** (run from where the server will run):

```bash
curl -s "$WP_PROM_URL/api/v1/query?query=up" | head -c 80
```

Expected - a JSON body that starts with success:

```
{"status":"success","data":{"resultType":"vector","result":[{"metric":{...
```

If you get a connection error or HTML, fix the URL/network before continuing.

### `WP_MONITORED_SERVICES` - exactly what to put

A comma-separated list of the service names you expect Prometheus to scrape. A
service in this list that has **no** active scrape target is reported as an
observability blind spot. Use the values of the `service` (or `job`) label in
your metrics:

```bash
curl -s "$WP_PROM_URL/api/v1/label/service/values"
# -> {"status":"success","data":["web","orders","db", ...]}
```

Set `WP_MONITORED_SERVICES` to those names.

### Metric queries - match your instrumentation

The graph reads two signals from metrics: a per-service **error rate** and an
optional **database-up** flag. The defaults are the demo's metric names
(`http_requests_total{status="5xx"}`, `pg_up`); real apps differ, so override
the queries to match yours.

- `WP_ERROR_RATE_QUERY` - PromQL returning **one series per service**, valued in
  failed-requests/sec. A service over `WP_ERROR_RATE_THRESHOLD` is marked
  `erroring` even when its container looks healthy.
- `WP_ERROR_RATE_LABEL` - the label on those series that holds the service name
  (e.g. `service`, `app`, `job`). Must match the `by (...)` clause in the query.
- `WP_DB_UP_QUERY` - PromQL returning a single `0`/`1` scalar (e.g. `pg_up`,
  `mysql_up`, `redis_up`). Set it empty to skip the DB check entirely.

Spring Boot / Micrometer example:

```bash
WP_ERROR_RATE_QUERY='sum(rate(http_server_requests_seconds_count{outcome="SERVER_ERROR"}[1m])) by (app)'
WP_ERROR_RATE_LABEL=app
```

These are the only PromQL strings in the system. Pointing `WP_PROM_URL` at a
PromQL-compatible backend (Thanos, Cortex, Grafana Mimir, VictoriaMetrics,
Grafana Cloud) needs no other change.

### Other backends (Datadog, traces)

**Datadog metrics** (`WP_METRICS_BACKEND=datadog`). Reads the Datadog v1 query
API in Datadog's own query language - no PromQL. Set the keys and the error-rate
query:

```bash
WP_METRICS_BACKEND=datadog
WP_DD_API_KEY=...                       # or the standard DD_API_KEY
WP_DD_APP_KEY=...                       # or the standard DD_APP_KEY
WP_DD_SITE=datadoghq.com               # datadoghq.eu, us3.datadoghq.com, ...
WP_DD_ERROR_RATE_QUERY='sum:trace.http.request.errors{*} by {service}.as_rate()'
WP_DD_SERVICE_TAG=service              # tag holding the service name
WP_DD_DB_UP_QUERY='max:postgresql.up{*}'   # optional; empty disables the DB check
```

A service that emits the error-rate metric counts as "reporting" for blind-spot
detection (Datadog has no scrape-target list). Verify the credentials reach the
API:

```bash
curl -s -G "https://api.$WP_DD_SITE/api/v1/query" \
  -H "DD-API-KEY: $WP_DD_API_KEY" -H "DD-APPLICATION-KEY: $WP_DD_APP_KEY" \
  --data-urlencode "from=$(($(date +%s)-300))" --data-urlencode "to=$(date +%s)" \
  --data-urlencode "query=$WP_DD_ERROR_RATE_QUERY" | head -c 80
# Expected: {"status":"ok","series":[...
```

**Trace topology** (`WP_TOPOLOGY=traces`). Dependency edges come from real call
spans via Jaeger's `/api/dependencies` (parent calls child). Traces carry no
container health, so discovered services are marked up and **a metrics source
supplies the failure status** - run traces + Prometheus/Datadog together:

```bash
WP_TOPOLOGY=traces
WP_JAEGER_URL=http://localhost:16686
WP_TRACES_LOOKBACK=3600                 # seconds of trace history to fold in
# plus a metrics source (default Prometheus) for health
```

Tempo instead of Jaeger: Tempo's metrics-generator exposes the service graph as
Prometheus metrics (`traces_service_graph_request_total{client,server}`), so a
Tempo topology is a PromQL query against `WP_PROM_URL`, not this connector.

Backends still on the seam (New Relic, CloudWatch, service-mesh topology) are
added as new `MetricsSource` / `TopologySource` classes the same way.

### Graph backend - FalkorDB (default)

The graph is stored in FalkorDB. Point woodpecker-mcp at it with `WP_FALKOR_HOST`
/ `WP_FALKOR_PORT` (default `localhost:6379`); in Kubernetes set `WP_FALKOR_HOST`
to the FalkorDB Service name (`falkordb`). Run FalkorDB with `docker run -p
6379:6379 -p 3000:3000 falkordb/falkordb` (graph browser on :3000) or the bundled
`docker-compose.yml`. Validate it's reachable:

```bash
redis-cli -h "$WP_FALKOR_HOST" -p 6379 PING        # -> PONG
```

Prefer no server? Use the embedded Kuzu fallback: `pip install
"woodpecker-mcp[kuzu]"` and set `WP_GRAPH_BACKEND=kuzu`.

---

## Step 3 - Integrate with HolmesGPT

HolmesGPT launches/contacts the server and discovers its tools. **Holmes is not
modified, forked, or rebuilt.**

### Method A - local / CLI (stdio transport)

For `holmes` running on a machine that has `woodpecker-mcp` installed.

**1.** Create `woodpecker-toolset.yaml` (start from
[`examples/holmesgpt-toolset.yaml`](../examples/holmesgpt-toolset.yaml)) and put
your step-2 values in `env:`:

```yaml
toolsets:
  woodpecker-graph:
    type: mcp
    enabled: true
    config:
      mode: stdio
      command: "woodpecker-mcp"
      args: ["serve"]
      health_check_tool: "woodpecker_get_topology"
      env:
        PATH: "{{ env.PATH }}"
        WP_GRAPH_BACKEND: "falkordb"
        WP_FALKOR_HOST: "localhost"
        WP_TOPOLOGY: "docker"
        WP_COMPOSE_PROJECT: "my-app"
        WP_PROM_URL: "http://localhost:9091"
        WP_MONITORED_SERVICES: "web,orders,db"
```

**2.** Run an investigation with the toolset attached:

```bash
holmes ask "find the root cause of the current incident" \
  -t woodpecker-toolset.yaml -v
```

**3.** Verify Holmes loaded and called the tools - with `-v` the output shows
tool calls; confirm lines naming `woodpecker_get_topology` /
`woodpecker_diagnose_root_cause` appear.

To make it permanent, paste the `toolsets:` block into `~/.holmes/config.yaml`.

> **PATH gotcha (the usual snag):** Holmes runs `woodpecker-mcp` as a subprocess,
> so `command:` must resolve from Holmes's environment. Same venv -> the bare name
> works; pipx or a separate venv -> use the absolute path
> (`/path/to/venv/bin/woodpecker-mcp`). The subprocess also needs `docker` or
> `kubectl` on `PATH` (hence `PATH: "{{ env.PATH }}"`) and FalkorDB reachable.

### Method B - in-cluster (HTTP transport, for the Holmes Operator)

**1.** Build and push the image:

```bash
docker build -t <REGISTRY>/woodpecker-mcp:0.1.0 .
docker push <REGISTRY>/woodpecker-mcp:0.1.0
```

**2.** Edit [`examples/k8s-deployment.yaml`](../examples/k8s-deployment.yaml):
set `<IMAGE>`, `WP_PROM_URL`, `WP_MONITORED_SERVICES`, and the namespace. Apply:

```bash
kubectl apply -f examples/k8s-deployment.yaml
kubectl -n monitoring rollout status deploy/woodpecker-mcp
```

**3.** Point Holmes at it (in Holmes' config/values):

```yaml
toolsets:
  woodpecker-graph:
    type: mcp
    enabled: true
    config:
      mode: streamable-http
      url: "http://woodpecker-mcp.monitoring.svc.cluster.local:8000/mcp"
```

**4.** Verify the server is serving MCP (from inside the cluster):

```bash
kubectl -n monitoring port-forward deploy/woodpecker-mcp 8000:8000 &
curl -s -i http://localhost:8000/mcp -H 'Accept: text/event-stream' | head -n 1
# Expected: HTTP/1.1 200 OK  (an MCP endpoint is responding)
```

---

## Step 4 - Tell it your topology

The graph needs to know which services depend on which. Two ways:

**Docker Compose (automatic).** With `WP_TOPOLOGY=docker`, dependencies are read
from compose `depends_on` labels **and** env-var host references (e.g.
`ORDERS_URL=http://orders:8001` -> `web depends on orders`). Nothing to author.

**Declarative (any environment).** Provide a JSON file and load it:

```bash
woodpecker-mcp ingest my-topology.json     # see examples/topology.example.json
WP_AUTO_REFRESH=0 woodpecker-mcp diagnose   # query the loaded snapshot
```

```json
{
  "services": [
    {"name": "web",    "status": "erroring", "error_rate": 4.2},
    {"name": "orders", "status": "erroring"},
    {"name": "db",     "status": "down"}
  ],
  "dependencies": [["web", "orders"], ["orders", "db"]]
}
```

Set `WP_AUTO_REFRESH=0` so queries read your snapshot instead of rebuilding from
a (non-existent) live connector.

**Kubernetes (automatic).** With `WP_TOPOLOGY=k8s`, services come from
Deployments, instances from Pods, and dependencies from env-var host references -
read via `kubectl`. Locally it uses your kubeconfig (`WP_K8S_CONTEXT` picks a
context); in a pod it uses the in-cluster ServiceAccount (leave `WP_K8S_CONTEXT`
empty). The ServiceAccount needs read access to deployments + pods - see the RBAC
in [`examples/k8s-deployment.yaml`](../examples/k8s-deployment.yaml).

---

## Step 5 - Production checklist

- **Persistence**: mount a volume at `WP_KUZU_PATH` (`/data` in the image) so the
  graph DB survives restarts.
- **Health checks**: a TCP check on the HTTP port (port 8000) - see the
  liveness/readiness probes in the k8s manifest.
- **Resources**: small - one service graph at a time; 128-256Mi is plenty.
- **Security**: all tools are read-only. The HTTP transport has **no built-in
  auth** - keep it cluster-internal and restrict ingress (the manifest's
  NetworkPolicy allows only Holmes pods). Do not expose it publicly.
- **Refresh cost**: with `WP_AUTO_REFRESH=1` the graph is rebuilt on every tool
  call. Fine at tens of services; for larger graphs, refresh on a schedule and
  set `WP_AUTO_REFRESH=0`.

---

## Troubleshooting

| Symptom | Command to check | Fix |
|---|---|---|
| Tool error names FalkorDB / connection refused | `redis-cli -h $WP_FALKOR_HOST -p 6379 PING` (expect `PONG`) | FalkorDB isn't running/reachable - start it (`docker run ... falkordb/falkordb`) or fix `WP_FALKOR_HOST`/`WP_FALKOR_PORT`. |
| Tool returns `could not refresh graph from sources` | `curl -s "$WP_PROM_URL/api/v1/query?query=up"` ; `docker ps` | Wrong `WP_PROM_URL`, or `docker` not on `PATH` (add `PATH: "{{ env.PATH }}"`), or wrong `WP_COMPOSE_PROJECT`. |
| `diagnose` always says `healthy` after `ingest` | `echo $WP_AUTO_REFRESH` | Set `WP_AUTO_REFRESH=0` (a live refresh overwrote your snapshot). |
| Blind spots never reported | `curl -s "$WP_PROM_URL/api/v1/label/service/values"` | Set `WP_MONITORED_SERVICES` to those exact names. |
| `WP_TOPOLOGY=k8s` returns nothing or `forbidden` | `kubectl -n <ns> get deploy,pods` | `kubectl` not on `PATH`, wrong `WP_K8S_NAMESPACE`/`WP_K8S_CONTEXT`, or the ServiceAccount lacks `get,list` on deployments+pods (apply the RBAC). |
| Holmes doesn't list the tools | run `holmes ask ... -v` | Check `enabled: true`, `command`/`url` reachable; a failing `health_check_tool` disables the toolset. |
| HTTP server unreachable in a container | `kubectl logs deploy/woodpecker-mcp` | Ensure it binds `0.0.0.0` (default) and the Service/port match 8000. |
