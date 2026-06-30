"""TopologySource backed by a local Docker Compose project.

Discovers services/containers from `docker inspect`, and dependency edges from
two signals merged: (1) compose's `com.docker.compose.depends_on` label, and
(2) env-var host references (e.g. ORDERS_URL=http://orders:8001) - the real
"who talks to whom".
"""
import json
import re
import subprocess

from .base import TopologySource

_ROLES = {
    "db": "database", "prometheus": "observability", "grafana": "observability",
    "db_exporter": "observability", "loadgen": "load-generator",
}


def _role(name):
    return _ROLES.get(name, "app")


def _references_host(value, host):
    """True if `value` references `host` as a network host without false-matching
    substrings (host 'db' must not match 'db_exporter')."""
    return re.search(rf"[/@]{re.escape(host)}(?=[:/]|$)", value) is not None


class DockerComposeTopology(TopologySource):
    def __init__(self, project="demo_env"):
        self.project = project

    def _inspect_all(self):
        names = subprocess.check_output(
            ["docker", "ps", "-a", "--filter",
             f"label=com.docker.compose.project={self.project}", "--format", "{{.Names}}"],
            text=True,
        ).split()
        if not names:
            return []
        return json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))

    def discover(self):
        infos = self._inspect_all()

        svc_names = set()
        for c in infos:
            labels = c["Config"].get("Labels") or {}
            svc_names.add(labels.get("com.docker.compose.service", c["Name"].lstrip("/")))

        services, containers, deps = {}, [], set()
        for c in infos:
            name = c["Name"].lstrip("/")
            labels = c["Config"].get("Labels") or {}
            svc = labels.get("com.docker.compose.service", name)
            state = c["State"]["Status"]
            health = (c["State"].get("Health") or {}).get("Status")
            restarts = c.get("RestartCount", 0)
            image = c["Config"].get("Image", "")

            services.setdefault(svc, {"name": svc, "role": _role(svc)})
            containers.append({"name": name, "service": svc, "state": state,
                               "health": health, "restarts": restarts, "image": image})

            for part in filter(None, labels.get("com.docker.compose.depends_on", "").split(",")):
                dep = part.split(":")[0]
                if dep and dep != svc:
                    deps.add((svc, dep))

            for env in (c["Config"].get("Env") or []):
                val = env.split("=", 1)[1] if "=" in env else ""
                for other in svc_names:
                    if other != svc and _references_host(val, other):
                        deps.add((svc, other))

        return list(services.values()), containers, sorted(deps)
