"""TopologySource backed by Kubernetes (via `kubectl`, mirroring the Docker
connector's shell-out style - zero extra deps).

Maps k8s objects onto the same graph vocabulary as the Docker connector:
  Deployment -> service node
  Pod        -> container node (a service can have many: replicas)
  env refs   -> depends_on edges (e.g. ORDERS_URL=http://orders:8001)

Pod status is normalized to the docker-like (state, health) the graph builder
understands: CrashLoopBackOff -> restarting, Running+ready -> healthy, etc.

`kubectl` must be on PATH with a readable kubeconfig (or, in a pod, an in-cluster
ServiceAccount with read access to deployments/pods in the namespace). Set the
namespace/context via WP_K8S_NAMESPACE / WP_K8S_CONTEXT.
"""
import json
import re
import subprocess

from .base import TopologySource

_ROLES = {"db": "database", "prometheus": "observability", "grafana": "observability"}


def _role(name):
    return _ROLES.get(name, "app")


def _references_host(value, host):
    """True if `value` references `host` as a network host (no false-substring match)."""
    return re.search(rf"[/@]{re.escape(host)}(?=[:/]|$)", value) is not None


def _pod_status(pod):
    """Normalize a Pod's status to (state, health, restarts) in docker terms."""
    status = pod.get("status", {})
    phase = status.get("phase")
    cs = status.get("containerStatuses") or []
    main = cs[0] if cs else {}
    restarts = main.get("restartCount", 0)
    ready = main.get("ready", False)
    waiting = (main.get("state") or {}).get("waiting") or {}
    reason = waiting.get("reason", "")

    if reason in ("CrashLoopBackOff", "Error", "ImagePullBackOff", "ErrImagePull", "RunContainerError"):
        return "restarting", "unhealthy", restarts
    if phase == "Running":
        return "running", ("healthy" if ready else "unhealthy"), restarts
    # Failed / Succeeded / Pending / Unknown -> treat as down
    return "exited", "unhealthy", restarts


class KubernetesTopology(TopologySource):
    def __init__(self, namespace="default", context=""):
        self.namespace = namespace
        self.context = context

    def _kubectl_json(self, kind):
        cmd = ["kubectl", "-n", self.namespace, "get", kind, "-o", "json"]
        if self.context:
            cmd[1:1] = ["--context", self.context]
        out = subprocess.check_output(cmd, text=True, timeout=15)
        return json.loads(out)

    def discover(self):
        deploys = self._kubectl_json("deployments")
        pods = self._kubectl_json("pods")

        svc_names = {d["metadata"]["name"] for d in deploys["items"]}
        services = [{"name": d["metadata"]["name"], "role": _role(d["metadata"]["name"])}
                    for d in deploys["items"]]

        containers, deps = [], set()
        for p in pods["items"]:
            labels = p["metadata"].get("labels", {})
            svc = labels.get("app", p["metadata"]["name"])
            if svc not in svc_names:
                continue  # skip stray pods not owned by a known deployment
            state, health, restarts = _pod_status(p)
            spec_containers = p["spec"].get("containers", [])
            image = spec_containers[0].get("image", "") if spec_containers else ""
            containers.append({"name": p["metadata"]["name"], "service": svc, "state": state,
                               "health": health, "restarts": restarts, "image": image})
            for c in spec_containers:
                for e in (c.get("env") or []):
                    val = e.get("value", "") or ""
                    for other in svc_names:
                        if other != svc and _references_host(val, other):
                            deps.add((svc, other))

        return services, containers, sorted(deps)
