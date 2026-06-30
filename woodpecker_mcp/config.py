"""Configuration seam - env-var overridable defaults.

The graph is populated from a topology source (dependencies + health) and a
metrics source (Prometheus). Defaults match the Woodpecker demo_env.
"""
import os


def _load_dotenv(path=".env"):
    """Populate os.environ from a .env file in the working directory. Values
    already set in the environment (e.g. the Holmes toolset env: block) win."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

# --- Graph store backend: "falkordb" (server, default) or "kuzu" (embedded) ---
GRAPH_BACKEND = os.environ.get("WP_GRAPH_BACKEND", "falkordb")

# FalkorDB connection (used when WP_GRAPH_BACKEND=falkordb).
FALKOR_HOST = os.environ.get("WP_FALKOR_HOST", "localhost")
FALKOR_PORT = int(os.environ.get("WP_FALKOR_PORT", "6379"))
FALKOR_GRAPH = os.environ.get("WP_FALKOR_GRAPH", "woodpecker")
FALKOR_PASSWORD = os.environ.get("WP_FALKOR_PASSWORD") or None

# Kuzu embedded DB path (used when WP_GRAPH_BACKEND=kuzu).
KUZU_PATH = os.environ.get("WP_KUZU_PATH", "./woodpecker.kuzu")

# Topology backend (the connector seam): "docker", "k8s", or "traces".
TOPOLOGY = os.environ.get("WP_TOPOLOGY", "docker")

# Docker connector (used when WP_TOPOLOGY=docker).
COMPOSE_PROJECT = os.environ.get("WP_COMPOSE_PROJECT", "demo_env")

# Kubernetes connector (used when WP_TOPOLOGY=k8s). Empty context = the current
# kubeconfig context, or the in-cluster ServiceAccount when running in a pod.
K8S_NAMESPACE = os.environ.get("WP_K8S_NAMESPACE", "default")
K8S_CONTEXT = os.environ.get("WP_K8S_CONTEXT", "")

# Trace connector (used when WP_TOPOLOGY=traces). Edges come from real call
# spans. Pair it with a metrics source for health - traces give structure only.
TRACES_BACKEND = os.environ.get("WP_TRACES_BACKEND", "jaeger")  # jaeger
JAEGER_URL = os.environ.get("WP_JAEGER_URL", "http://localhost:16686")
TRACES_LOOKBACK = int(os.environ.get("WP_TRACES_LOOKBACK", "3600"))  # seconds

PROM_URL = os.environ.get("WP_PROM_URL", "http://localhost:9091")

# Metric queries (PromQL). Metric names depend on how each app is instrumented,
# so override these to match your deployment. Defaults match the Woodpecker
# demo_env. These are the only Prometheus-specific strings in the system - a
# non-Prometheus backend ignores them and implements MetricsSource directly.
#   ERROR_RATE_QUERY: one series per service, valued in failed-requests/sec.
#   ERROR_RATE_LABEL: the label on that series that holds the service name.
#   DB_UP_QUERY:      a single 0/1 scalar; set empty to skip the DB check.
ERROR_RATE_QUERY = os.environ.get(
    "WP_ERROR_RATE_QUERY",
    'sum(rate(http_requests_total{status="5xx"}[1m])) by (service)',
)
ERROR_RATE_LABEL = os.environ.get("WP_ERROR_RATE_LABEL", "service")
DB_UP_QUERY = os.environ.get("WP_DB_UP_QUERY", "pg_up")

# --- Metrics backend: "prometheus" (default) or "datadog" ---
METRICS_BACKEND = os.environ.get("WP_METRICS_BACKEND", "prometheus")

# Datadog metrics source (used when WP_METRICS_BACKEND=datadog). The queries are
# Datadog's language, not PromQL. DD_SITE is the region host (datadoghq.com,
# datadoghq.eu, us3.datadoghq.com...). Keys fall back to the standard DD_* names.
DD_SITE = os.environ.get("WP_DD_SITE", "datadoghq.com")
DD_API_KEY = os.environ.get("WP_DD_API_KEY") or os.environ.get("DD_API_KEY")
DD_APP_KEY = os.environ.get("WP_DD_APP_KEY") or os.environ.get("DD_APP_KEY")
DD_ERROR_RATE_QUERY = os.environ.get(
    "WP_DD_ERROR_RATE_QUERY",
    "sum:trace.http.request.errors{*} by {service}.as_rate()",
)
DD_SERVICE_TAG = os.environ.get("WP_DD_SERVICE_TAG", "service")
DD_DB_UP_QUERY = os.environ.get("WP_DD_DB_UP_QUERY", "")  # e.g. max:postgresql.up{*}
DD_WINDOW = int(os.environ.get("WP_DD_WINDOW", "300"))  # query lookback, seconds

# When true (default), query commands/tools rebuild the graph from live sources
# first. Set WP_AUTO_REFRESH=0 to query a snapshot you ingested separately (e.g.
# a static topology you're studying offline).
AUTO_REFRESH = os.environ.get("WP_AUTO_REFRESH", "1") != "0"

# Services we expect Prometheus to scrape - a monitored service with no live
# scrape target is flagged as an observability blind spot (lost visibility, not
# an outage).
MONITORED_SERVICES = set(
    filter(None, os.environ.get("WP_MONITORED_SERVICES", "web,orders,db").split(","))
)

# A service whose 5xx rate (req/s) exceeds this is "erroring" even if its
# container reports healthy - catches functional failure container health misses.
ERROR_RATE_THRESHOLD = float(os.environ.get("WP_ERROR_RATE_THRESHOLD", "0.05"))
