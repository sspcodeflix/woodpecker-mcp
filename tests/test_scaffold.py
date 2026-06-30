import yaml

import woodpecker_mcp.scaffold as scaffold
from woodpecker_mcp.scaffold import (ENV_SAMPLE, _choose, _prompt, _render_env, _toolset_block,
                                     interactive_env, patch_holmes_config, write_env)


def test_write_env(tmp_path):
    p = tmp_path / ".env"
    assert "wrote" in write_env(str(p))
    assert p.read_text() == ENV_SAMPLE
    # does not overwrite without --force
    p.write_text("CHANGED")
    write_env(str(p))
    assert p.read_text() == "CHANGED"
    # force overwrites
    write_env(str(p), force=True)
    assert p.read_text() == ENV_SAMPLE


def test_toolset_block_shape():
    b = _toolset_block()
    assert b["type"] == "mcp"
    assert b["config"]["mode"] == "stdio"
    assert b["config"]["args"] == ["serve"]
    assert b["config"]["health_check_tool"] == "woodpecker_get_topology"
    env = b["config"]["env"]
    assert env["PATH"] == "{{ env.PATH }}"
    assert "WP_GRAPH_BACKEND" in env and "WP_TOPOLOGY" in env


def test_patch_creates_and_backs_up(tmp_path):
    cfg = tmp_path / "config.yaml"
    patch_holmes_config(str(cfg))
    data = yaml.safe_load(cfg.read_text())
    assert data["toolsets"]["woodpecker-graph"]["type"] == "mcp"
    assert not (tmp_path / "config.yaml.bak").exists()   # first run: nothing to back up
    # idempotent re-run backs up and keeps a single entry
    patch_holmes_config(str(cfg))
    assert (tmp_path / "config.yaml.bak").exists()
    assert list(yaml.safe_load(cfg.read_text())["toolsets"]) == ["woodpecker-graph"]


def test_patch_preserves_existing_toolsets(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("toolsets:\n  kubernetes/core:\n    enabled: true\n")
    patch_holmes_config(str(cfg))
    toolsets = yaml.safe_load(cfg.read_text())["toolsets"]
    assert "kubernetes/core" in toolsets
    assert "woodpecker-graph" in toolsets


# --- interactive `init` -------------------------------------------------------

def test_prompt_default_and_value(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    assert _prompt("q", "def") == "def"
    monkeypatch.setattr("builtins.input", lambda *a, **k: "  x  ")
    assert _prompt("q", "def") == "x"


def test_choose_number_name_and_default(monkeypatch):
    opts = [("falkordb", "x"), ("kuzu", "y")]
    monkeypatch.setattr("builtins.input", lambda *a, **k: "2")
    assert _choose("q", opts) == "kuzu"
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    assert _choose("q", opts) == "falkordb"      # Enter -> first option
    monkeypatch.setattr("builtins.input", lambda *a, **k: "kuzu")
    assert _choose("q", opts) == "kuzu"          # typed name


def test_choose_rejects_invalid_then_accepts(monkeypatch):
    seq = iter(["9", "zzz", "1"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    assert _choose("q", [("a", "x"), ("b", "y")]) == "a"


def test_render_env_k8s_prometheus_omits_other_backends():
    body = _render_env({
        "backend": "falkordb", "falkor_host": "localhost", "falkor_port": "6379",
        "falkor_graph": "woodpecker", "falkor_password": "",
        "topology": "k8s", "k8s_namespace": "demo", "k8s_context": "",
        "metrics": "prometheus", "prom_url": "http://prom:9090", "monitored": "web,db",
    })
    assert "WP_TOPOLOGY=k8s" in body and "WP_K8S_NAMESPACE=demo" in body
    assert "WP_METRICS_BACKEND=prometheus" in body and "WP_PROM_URL=http://prom:9090" in body
    assert "WP_COMPOSE_PROJECT" not in body and "WP_JAEGER_URL" not in body
    assert "WP_FALKOR_PASSWORD" not in body       # blank -> omitted


def test_render_env_traces_datadog():
    body = _render_env({
        "backend": "kuzu", "kuzu_path": "./w.kuzu",
        "topology": "traces", "jaeger_url": "http://j:16686",
        "metrics": "datadog", "dd_site": "datadoghq.eu", "dd_api_key": "K", "dd_app_key": "A",
        "monitored": "web",
    })
    assert "WP_GRAPH_BACKEND=kuzu" in body and "WP_KUZU_PATH=./w.kuzu" in body
    assert "WP_TOPOLOGY=traces" in body and "WP_JAEGER_URL=http://j:16686" in body
    assert "WP_DD_API_KEY=K" in body and "WP_DD_APP_KEY=A" in body
    assert "WP_FALKOR_HOST" not in body and "WP_PROM_URL" not in body


def test_interactive_env_non_tty_falls_back_to_template(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold.sys, "stdin", type("S", (), {"isatty": lambda self: False})())
    p = tmp_path / ".env"
    interactive_env(str(p))
    assert p.read_text() == ENV_SAMPLE


def test_start_falkordb_uses_explicit_image(monkeypatch):
    monkeypatch.setattr(scaffold.shutil, "which", lambda _: None)   # no docker -> manual hint
    msg = scaffold.start_falkordb(image="registry.corp/falkordb/falkordb:1.2")
    assert "registry.corp/falkordb/falkordb:1.2" in msg


def test_start_falkordb_defaults_to_config_image(monkeypatch):
    import woodpecker_mcp.config as cfg
    monkeypatch.setattr(scaffold.shutil, "which", lambda _: None)
    monkeypatch.setattr(cfg, "FALKOR_IMAGE", "registry.corp/mirror/falkordb:9")
    msg = scaffold.start_falkordb()                                 # no image arg -> config default
    assert "registry.corp/mirror/falkordb:9" in msg


def test_interactive_env_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold.sys, "stdin", type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(scaffold, "_secret", lambda label: "")
    # graph(default falkordb), host, port, graph-name, topo=2(k8s), ns, ctx,
    # metrics(default prometheus), prom-url, monitored(default)
    seq = iter(["", "", "", "", "2", "demo", "", "", "http://prom:9090", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(seq))
    p = tmp_path / ".env"
    msg = interactive_env(str(p))
    body = p.read_text()
    assert "WP_GRAPH_BACKEND=falkordb" in body
    assert "WP_TOPOLOGY=k8s" in body and "WP_K8S_NAMESPACE=demo" in body
    assert "WP_METRICS_BACKEND=prometheus" in body and "WP_PROM_URL=http://prom:9090" in body
    assert "WP_COMPOSE_PROJECT" not in body
    assert "topology=k8s" in msg
