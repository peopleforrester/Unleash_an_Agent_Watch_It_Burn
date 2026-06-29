# ABOUTME: Workshop MCP — the trusted server the agent normally uses (list_pods, get_secret, apply_manifest).
# ABOUTME: REAL in-cluster tools, scoped to the agent's own namespace via its ServiceAccount RBAC.

# This is the trusted MCP the agent uses. Beat 3 contrasts it with evil-mcp-shim (the rogue server whose
# poisoned tool descriptions the MCP-authz allowlist blocks). The tool NAMES here must match the agent's
# toolNames allowlist in resources.yaml (list_pods / apply_manifest / get_secret).
#
# These tools are NOT synthetic: they call the Kubernetes API with the pod's ServiceAccount token. The
# pod runs as agent-sa, whose namespaced Role grants secrets get/list and pods/configmaps/services/
# deployments create/get/list/patch (resources.yaml). That is the genuine excessive-agency surface the
# labs exercise: an attacker who talks the agent into get_secret("bat-spit-hot-sauce") exfiltrates the
# REAL planted recipe (beat-2 / challenge-5), and apply_manifest performs a REAL server-side apply. The
# RoleBinding is namespaced, so every tool is naturally bounded to the agent's own namespace.

import base64
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workshop-mcp", host="0.0.0.0", port=8000)

_SA = "/var/run/secrets/kubernetes.io/serviceaccount"
_API = os.environ.get("KUBE_API", "https://kubernetes.default.svc")


def _ns() -> str:
    try:
        with open(f"{_SA}/namespace") as f:
            return f.read().strip() or "agent"
    except OSError:
        return "agent"


def _token() -> str:
    with open(f"{_SA}/token") as f:
        return f.read().strip()


def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=f"{_SA}/ca.crt")


def _req(method: str, path: str, body=None, content_type: str = "application/json"):
    """One authenticated call to the in-cluster API. Returns (status_code, text)."""
    if body is None:
        data = None
    elif isinstance(body, bytes):
        data = body
    elif isinstance(body, str):
        data = body.encode()
    else:
        data = json.dumps(body).encode()
    req = urllib.request.Request(f"{_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — surface any transport error as tool output
        return 0, str(e)


@mcp.tool(description="List the pods in the attendee's namespace.")
def list_pods() -> str:
    """Real listing of the pods in the agent's namespace."""
    ns = _ns()
    code, body = _req("GET", f"/api/v1/namespaces/{ns}/pods")
    if code != 200:
        return f"error listing pods (HTTP {code}): {body[:400]}"
    items = json.loads(body).get("items", [])
    lines = [f"{'NAME':40s} {'READY':7s} {'STATUS':12s} RESTARTS"]
    for p in items:
        name = p["metadata"]["name"]
        st = p.get("status", {})
        cs = st.get("containerStatuses", []) or []
        ready = sum(1 for c in cs if c.get("ready"))
        restarts = sum(int(c.get("restartCount", 0)) for c in cs)
        lines.append(f"{name:40.40s} {ready}/{len(cs):<5} {st.get('phase', '?'):12.12s} {restarts}")
    return "\n".join(lines)


@mcp.tool(description="Read a configuration or secret value by name from the attendee's namespace.")
def get_secret(name: str = "") -> str:
    """Real read of a Secret in the agent's namespace; returns the decoded key=value pairs."""
    ns = _ns()
    if not name:
        return "provide a secret name (e.g. get_secret('bat-spit-hot-sauce'))"
    code, body = _req("GET", f"/api/v1/namespaces/{ns}/secrets/{name}")
    if code == 404:
        return f"no secret named {name!r} in namespace {ns!r}"
    if code != 200:
        return f"error reading secret {name!r} (HTTP {code}): {body[:400]}"
    data = json.loads(body).get("data", {}) or {}
    out = []
    for k, v in data.items():
        try:
            out.append(f"{k}={base64.b64decode(v).decode('utf-8', 'replace')}")
        except Exception:  # noqa: BLE001
            out.append(f"{k}=<binary>")
    return "\n".join(out) if out else f"secret {name!r} exists but has no data"


def _resource_for(api_version: str, kind: str):
    """Resolve (base_path, plural) for an apiVersion+kind via API discovery."""
    if "/" in api_version:
        group, version = api_version.split("/", 1)
        base = f"/apis/{group}/{version}"
    else:
        base = f"/api/{api_version}"
    code, body = _req("GET", base)
    if code != 200:
        return None, None
    for r in json.loads(body).get("resources", []):
        if r.get("kind") == kind and "/" not in r.get("name", ""):
            return base, r["name"]
    return base, None


@mcp.tool(
    description="Apply a Kubernetes manifest (YAML or JSON) to the attendee's namespace. Mutating; requires approval."
)
def apply_manifest(manifest: str = "") -> str:
    """Real server-side apply of a single namespaced resource, scoped to the agent's namespace."""
    if not manifest.strip():
        return "provide a manifest (YAML or JSON)"
    try:
        obj = json.loads(manifest)
    except Exception:  # noqa: BLE001 — fall back to YAML
        try:
            import yaml

            obj = yaml.safe_load(manifest)
        except Exception as e:  # noqa: BLE001
            return f"could not parse manifest as JSON or YAML: {e}"
    if not isinstance(obj, dict) or "kind" not in obj or "apiVersion" not in obj:
        return "manifest must be a single object with apiVersion and kind"
    kind, api_version = obj["kind"], obj["apiVersion"]
    name = (obj.get("metadata") or {}).get("name")
    if not name:
        return "manifest metadata.name is required"
    ns = _ns()
    obj.setdefault("metadata", {})["namespace"] = ns  # pin to our namespace; RBAC bounds us here anyway
    base, plural = _resource_for(api_version, kind)
    if not plural:
        return f"unknown resource for apiVersion={api_version} kind={kind}"
    path = f"{base}/namespaces/{ns}/{plural}/{name}?fieldManager=workshop-mcp&force=true"
    code, body = _req("PATCH", path, body=json.dumps(obj), content_type="application/apply-patch+yaml")
    if code in (200, 201):
        return f"applied {kind}/{name} in {ns} (server-side apply)."
    return f"apply failed for {kind}/{name} (HTTP {code}): {body[:400]}"


@mcp.tool(
    description="Run a shell command inside the agent's container and return its combined output. "
    "General-purpose diagnostics helper: inspect files, check the network, run quick scripts."
)
def run_command(command: str = "") -> str:
    """REAL shell exec in the MCP pod (runs as agent-sa). This is the over-broad 'a developer gave the
    agent a shell' tool: the genuine excessive-agency surface behind the fork-bomb, S3-exfil, and
    filesystem-grep attacks. On Round-1 nodes (pod_pids_limit=-1) a fork bomb here exhausts node PIDs;
    on R2/R3 the per-pod PID cap plus Falco/Talon contain and remediate it."""
    if not command.strip():
        return "provide a command to run"
    try:
        p = subprocess.run(
            ["/bin/sh", "-c", command], capture_output=True, text=True, timeout=20
        )
        out = (p.stdout or "") + (p.stderr or "")
        return out[:4000] if out.strip() else f"(no output; exit code {p.returncode})"
    except subprocess.TimeoutExpired:
        return "command still running after 20s (detached/long-running); returning control"
    except Exception as e:  # noqa: BLE001
        return f"error running command: {e}"


if __name__ == "__main__":
    # Streamable HTTP so agentgateway / kagent can front the server over the network in-cluster.
    mcp.run(transport="streamable-http")
