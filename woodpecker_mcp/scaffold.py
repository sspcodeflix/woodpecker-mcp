"""Bootstrap helpers for `woodpecker-mcp init` and `woodpecker-mcp setup`:
write a .env, start FalkorDB, and register the toolset in HolmesGPT's config.
"""
import os
import shutil
import subprocess
import sys

ENV_SAMPLE = """\
# woodpecker-mcp configuration.
# Copy to .env and edit. Real environment variables and the Holmes toolset
# env: block override anything set here.

# ============================================================
# Graph backend - where the dependency graph is stored
# ============================================================
# falkordb = server (default, recommended; ships a browser UI on :3000)
# kuzu     = embedded file database (no server; pip install "woodpecker-mcp[kuzu]")
WP_GRAPH_BACKEND=falkordb

# FalkorDB connection (when WP_GRAPH_BACKEND=falkordb).
# In Kubernetes, set the host to the FalkorDB Service name.
WP_FALKOR_HOST=localhost
WP_FALKOR_PORT=6379
# Graph name inside FalkorDB (any label).
WP_FALKOR_GRAPH=woodpecker
# Uncomment if your FalkorDB requires a password.
# WP_FALKOR_PASSWORD=
# Image `woodpecker-mcp setup` starts for FalkorDB. Point at an internal
# registry mirror in restricted/air-gapped environments.
# WP_FALKOR_IMAGE=falkordb/falkordb:latest

# ============================================================
# Topology connector - where services + dependencies are read from
# ============================================================
# docker = a local Docker Compose project
# k8s    = a Kubernetes namespace (via kubectl)
WP_TOPOLOGY=docker

# Docker connector (when WP_TOPOLOGY=docker): the compose project to inspect.
WP_COMPOSE_PROJECT=demo_env

# Kubernetes connector (when WP_TOPOLOGY=k8s).
# Namespace whose Deployments/Pods become the graph.
WP_K8S_NAMESPACE=default
# kubectl context; empty = current context, or the in-cluster ServiceAccount
# when running inside a pod.
WP_K8S_CONTEXT=

# ============================================================
# Metrics - Prometheus (error rates + scrape-target health)
# ============================================================
# Base URL of your Prometheus HTTP API (the address of its web UI). Examples:
#   local docker:    http://localhost:9091
#   kube-prometheus: http://prometheus-operated.monitoring.svc.cluster.local:9090
# Any PromQL-compatible backend works here too - point it at Thanos, Cortex,
# Grafana Mimir, VictoriaMetrics, or Grafana Cloud.
WP_PROM_URL=http://localhost:9091

# Services you expect Prometheus to scrape (comma-separated). A service in this
# list with no live scrape target is flagged as an observability blind spot.
WP_MONITORED_SERVICES=web,orders,db

# Metric queries (PromQL). Metric names depend on how each app is instrumented,
# so override these to match your stack. Defaults match the demo_env.
#   ERROR_RATE_QUERY: one series per service, valued in failed-requests/sec.
#   ERROR_RATE_LABEL: the label on that series holding the service name.
#   DB_UP_QUERY:      a single 0/1 scalar; set empty to skip the DB check.
WP_ERROR_RATE_QUERY=sum(rate(http_requests_total{status="5xx"}[1m])) by (service)
WP_ERROR_RATE_LABEL=service
WP_DB_UP_QUERY=pg_up

# ============================================================
# Behavior
# ============================================================
# 1 = rebuild the graph from live sources on every query (always current)
# 0 = query a static snapshot loaded with `woodpecker-mcp ingest`
WP_AUTO_REFRESH=1

# A service whose 5xx rate (requests/sec) exceeds this is marked "erroring"
# even if its container looks healthy.
WP_ERROR_RATE_THRESHOLD=0.05

# Kuzu backend only: path to the embedded database file.
WP_KUZU_PATH=./woodpecker.kuzu

# Bind host for `woodpecker-mcp serve --http`.
WP_HTTP_HOST=0.0.0.0

# ============================================================
# Alternative backends (optional) - uncomment one to switch
# ============================================================
# Metrics from Datadog instead of Prometheus (its own query language, not PromQL):
# WP_METRICS_BACKEND=datadog
# WP_DD_SITE=datadoghq.com
# WP_DD_API_KEY=
# WP_DD_APP_KEY=
# WP_DD_ERROR_RATE_QUERY=sum:trace.http.request.errors{*} by {service}.as_rate()
# WP_DD_DB_UP_QUERY=max:postgresql.up{*}

# Topology from distributed traces (real call edges; pair with a metrics source
# for health - traces give structure only):
# WP_TOPOLOGY=traces
# WP_JAEGER_URL=http://localhost:16686
# WP_TRACES_LOOKBACK=3600
"""


def write_env(path=".env", force=False):
    if os.path.exists(path) and not force:
        return f"{path} already exists (use --force to overwrite). Edit it, then run `woodpecker-mcp setup`."
    with open(path, "w") as f:
        f.write(ENV_SAMPLE)
    return f"wrote {path} - edit it with your infra, then run `woodpecker-mcp setup`."


# --- Interactive .env builder (woodpecker-mcp init) ---------------------------

def _prompt(label, default=""):
    """Free-text question; Enter accepts the [default]."""
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{label}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def _choose(label, options, default=None):
    """Numbered single choice. options = [(value, description), ...]. Returns the
    chosen value; Enter accepts `default` (or the first option). The value name
    may also be typed directly."""
    default = default or options[0][0]
    print(label)
    for i, (val, desc) in enumerate(options, 1):
        mark = "  (default)" if val == default else ""
        print(f"  {i}) {val}{mark} - {desc}")
    while True:
        raw = _prompt(f"Choose 1-{len(options)}", default)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        if raw in {v for v, _ in options}:
            return raw
        print(f"  Enter a number 1-{len(options)} or a name from the list.")


def _secret(label):
    """Read a value without echoing it (for API keys / passwords)."""
    import getpass
    try:
        return getpass.getpass(f"{label}: ").strip()
    except Exception:
        return _prompt(label)


def _render_env(a):
    """Build a focused .env from collected answers - only the vars the chosen
    backends use, with the rest left at their defaults."""
    out = ["# woodpecker-mcp configuration (generated by `woodpecker-mcp init`).",
           "# Real environment variables and the Holmes toolset env: block override these.",
           "",
           "# --- Graph backend ---",
           f"WP_GRAPH_BACKEND={a['backend']}"]
    if a["backend"] == "falkordb":
        out += [f"WP_FALKOR_HOST={a['falkor_host']}",
                f"WP_FALKOR_PORT={a['falkor_port']}",
                f"WP_FALKOR_GRAPH={a['falkor_graph']}"]
        if a.get("falkor_password"):
            out += [f"WP_FALKOR_PASSWORD={a['falkor_password']}"]
    else:
        out += [f"WP_KUZU_PATH={a['kuzu_path']}"]

    out += ["", "# --- Topology (services + dependency edges) ---", f"WP_TOPOLOGY={a['topology']}"]
    if a["topology"] == "docker":
        out += [f"WP_COMPOSE_PROJECT={a['compose_project']}"]
    elif a["topology"] == "k8s":
        out += [f"WP_K8S_NAMESPACE={a['k8s_namespace']}", f"WP_K8S_CONTEXT={a['k8s_context']}"]
    else:
        out += [f"WP_JAEGER_URL={a['jaeger_url']}", "WP_TRACES_LOOKBACK=3600"]

    out += ["", "# --- Metrics (health signals) ---", f"WP_METRICS_BACKEND={a['metrics']}"]
    if a["metrics"] == "prometheus":
        out += [f"WP_PROM_URL={a['prom_url']}"]
    else:
        out += [f"WP_DD_SITE={a['dd_site']}",
                f"WP_DD_API_KEY={a.get('dd_api_key', '')}",
                f"WP_DD_APP_KEY={a.get('dd_app_key', '')}"]
    out += [f"WP_MONITORED_SERVICES={a['monitored']}",
            "",
            "# --- Behavior (defaults are fine) ---",
            "WP_AUTO_REFRESH=1",
            "WP_ERROR_RATE_THRESHOLD=0.05"]
    return "\n".join(out) + "\n"


def interactive_env(path=".env", force=False):
    """Ask a few questions and write a filled-in .env. Falls back to the static
    template when stdin is not a TTY (CI / piped), so it never hangs."""
    if os.path.exists(path) and not force:
        return f"{path} already exists (use --force to overwrite, or --defaults for the template)."
    if not sys.stdin.isatty():
        return write_env(path, force=True)

    print("woodpecker-mcp init - answer a few questions to generate .env.")
    print("Press Enter to accept the [default] shown.\n")
    a = {}

    a["backend"] = _choose("Where should the dependency graph be stored?", [
        ("falkordb", "FalkorDB server (recommended; graph browser UI on :3000)"),
        ("kuzu", "embedded file DB, no server (needs woodpecker-mcp[kuzu])"),
    ])
    if a["backend"] == "falkordb":
        a["falkor_host"] = _prompt("FalkorDB host", "localhost")
        a["falkor_port"] = _prompt("FalkorDB port", "6379")
        a["falkor_graph"] = _prompt("Graph name", "woodpecker")
        a["falkor_password"] = _secret("FalkorDB password (blank if none)")
    else:
        a["kuzu_path"] = _prompt("Kuzu database file path", "./woodpecker.kuzu")

    print()
    a["topology"] = _choose("Where are services + dependencies discovered from?", [
        ("docker", "a local Docker Compose project"),
        ("k8s", "a Kubernetes namespace (via kubectl)"),
        ("traces", "distributed traces via Jaeger (real call edges)"),
    ])
    if a["topology"] == "docker":
        a["compose_project"] = _prompt("Docker Compose project name", "demo_env")
    elif a["topology"] == "k8s":
        a["k8s_namespace"] = _prompt("Kubernetes namespace", "default")
        a["k8s_context"] = _prompt("kubectl context (blank = current / in-cluster)", "")
    else:
        a["jaeger_url"] = _prompt("Jaeger base URL", "http://localhost:16686")

    print()
    if a["topology"] == "traces":
        print("Traces give structure only - a metrics source supplies health.")
    a["metrics"] = _choose("Where do health metrics come from?", [
        ("prometheus", "Prometheus or any PromQL-compatible backend"),
        ("datadog", "Datadog (its own query language)"),
    ])
    if a["metrics"] == "prometheus":
        a["prom_url"] = _prompt("Prometheus base URL", "http://localhost:9091")
    else:
        a["dd_site"] = _prompt("Datadog site", "datadoghq.com")
        a["dd_api_key"] = _secret("Datadog API key")
        a["dd_app_key"] = _secret("Datadog application key")
    a["monitored"] = _prompt("Services you expect to be monitored (comma-separated)", "web,orders,db")

    with open(path, "w") as f:
        f.write(_render_env(a))
    return (f"\nwrote {path}  (graph={a['backend']}, topology={a['topology']}, "
            f"metrics={a['metrics']}).\nReview it, then run `woodpecker-mcp setup`.")


def start_falkordb(name="woodpecker-falkordb", image=None):
    if image is None:
        from . import config
        image = config.FALKOR_IMAGE
    if not shutil.which("docker"):
        return ("docker not found - start FalkorDB manually:\n"
                f"  docker run -d -p 6379:6379 -p 3000:3000 {image}")

    def _docker(*args):
        return subprocess.run(["docker", *args], capture_output=True, text=True)

    running = _docker("ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}").stdout.split()
    if name in running:
        return f"FalkorDB already running ({name}) on :6379, browser :3000."
    exists = _docker("ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}").stdout.split()
    if name in exists:
        r = _docker("start", name)
        return f"started existing FalkorDB ({name})." if r.returncode == 0 else f"could not start {name}: {r.stderr.strip()}"
    r = _docker("run", "-d", "--name", name, "-p", "6379:6379", "-p", "3000:3000", image)
    if r.returncode == 0:
        return f"started FalkorDB ({name}, {image}) on :6379, browser :3000."
    # The browser port (3000) is often taken (Grafana etc.); retry with 6379 only.
    _docker("rm", "-f", name)
    r2 = _docker("run", "-d", "--name", name, "-p", "6379:6379", image)
    if r2.returncode == 0:
        return (f"started FalkorDB ({name}) on :6379 "
                "(browser port 3000 was busy; publish it yourself for the UI).")
    return (f"could not start FalkorDB: {r2.stderr.strip()}\n"
            "  (port 6379 may be in use; start FalkorDB manually or set WP_FALKOR_HOST/PORT.)")


def _c(text, code):
    import sys
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def wait_for_falkordb(host="localhost", port=6379, password=None, timeout=12.0):
    """Poll until FalkorDB answers a trivial query, or timeout. Returns (ready, error)."""
    import socket
    import time
    from falkordb import FalkorDB
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            with socket.create_connection((host, int(port)), timeout=1.5):
                pass
            FalkorDB(host=host, port=int(port), password=password).select_graph("woodpecker").query("RETURN 1")
            return True, None
        except Exception as e:
            last = e
            time.sleep(0.4)
    return False, last


def falkordb_status_line(host="localhost", port=6379, password=None):
    ready, err = wait_for_falkordb(host, port, password)
    if ready:
        return _c(f"FalkorDB is ready at {host}:{port}.", "32")
    return _c(f"FalkorDB not reachable at {host}:{port} yet ({err}). It may still be "
              f"starting, or it is remote - check with: redis-cli -h {host} -p {port} ping", "33")


def _toolset_block():
    """The HolmesGPT stdio MCP toolset for woodpecker-mcp, using current config."""
    from . import config
    import sys
    command = shutil.which("woodpecker-mcp") or os.path.realpath(sys.argv[0])
    env = {
        "PATH": "{{ env.PATH }}",
        "WP_GRAPH_BACKEND": config.GRAPH_BACKEND,
        "WP_FALKOR_HOST": config.FALKOR_HOST,
        "WP_FALKOR_PORT": str(config.FALKOR_PORT),
        "WP_TOPOLOGY": config.TOPOLOGY,
        "WP_PROM_URL": config.PROM_URL,
        "WP_MONITORED_SERVICES": ",".join(sorted(config.MONITORED_SERVICES)),
    }
    if config.TOPOLOGY == "k8s":
        env["WP_K8S_NAMESPACE"] = config.K8S_NAMESPACE
        if config.K8S_CONTEXT:
            env["WP_K8S_CONTEXT"] = config.K8S_CONTEXT
    else:
        env["WP_COMPOSE_PROJECT"] = config.COMPOSE_PROJECT
    return {
        "type": "mcp",
        "enabled": True,
        "config": {
            "mode": "stdio",
            "command": command,
            "args": ["serve"],
            "health_check_tool": "woodpecker_get_topology",
            "env": env,
        },
    }


def patch_holmes_config(config_path="~/.holmes/config.yaml"):
    """Merge the woodpecker-graph toolset into HolmesGPT's config (idempotent)."""
    import yaml
    path = os.path.expanduser(config_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    cfg, backed_up = {}, False
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
        backed_up = True
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    cfg.setdefault("toolsets", {})["woodpecker-graph"] = _toolset_block()
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
    return (f"registered the woodpecker-graph toolset in {path}"
            + (f" (backup: {path}.bak)." if backed_up else "."))
