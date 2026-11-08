# ABOUTME: Holds #1050's grant on what Argo CD applies: in the pinned kubectl's kustomize render of gitops/ai-layer, workshop-mcp
# ABOUTME: holds a token and runs the reader, and under every swapped workshop-agent Role it lists each kind the reader reports.
# SUITE: e2e (needs the pinned kubectl v1.36.2 and helm v4.2.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Tools-tier checks for #1050's RBAC, on the rendered manifests.

verify/test_room_reader_rbac.py checks resources.yaml as written. This checks what the clusters are handed:
  1. the lab-bootstrap root, rendered with the pinned helm, gives an ai-layer Application whose source is
     gitops/ai-layer and whose ignoreDifferences leaves the reader's Role and binding to selfHeal;
  2. gitops/ai-layer, built with the pinned kubectl's kustomize as Argo CD builds it, puts the workshop-mcp pod on the
     workshop-mcp ServiceAccount with its token mounted, and its generated workshop-mcp-src ConfigMap's server.py is
     the one that starts the reader;
  3. the kinds the reader reports are read from that rendered server.py, and under the shipped workshop-agent Role and
     every workshop-agent Role in the rendered challenge-fixes ConfigMap, with the rendered reader Role beside it, the
     account lists each of them (verify/room_reader_rbac.py, shared with the offline test).
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import room_reader_rbac as rr  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def pinned(tool: str) -> str:
    for line in (REPO / "verify/e2e-tools.lock").read_text().splitlines():
        parts = line.split()
        if parts and not line.startswith("#") and parts[0] == tool:
            return parts[1]
    print(f"FAILED: verify/e2e-tools.lock pins no {tool}")
    sys.exit(1)


KUBECTL, HELM = shutil.which("kubectl"), shutil.which("helm")
if not KUBECTL or not HELM:
    print("FAILED: kubectl and helm must be on PATH; run this through bash verify/run-e2e-tools.sh, which puts the "
          "pinned ones from verify/fetch-e2e-tools.sh there")
    sys.exit(1)
kv = subprocess.run([KUBECTL, "version", "--client", "-o", "yaml"], capture_output=True, text=True).stdout
hv = subprocess.run([HELM, "version", "--short"], capture_output=True, text=True).stdout.strip()
check(f"kubectl is the pinned {pinned('kubectl')}", f"gitVersion: {pinned('kubectl')}\n" in kv, kv[:200])
check(f"helm is the pinned {pinned('helm')}", hv.startswith(pinned("helm")), hv)

print("== the root's ai-layer Application ==")
r = subprocess.run([HELM, "template", "lab-bootstrap", str(REPO / "gitops/bootstrap"), "--set", "revision=0123456789abcdef0123456789abcdef01234567",
                    "--set", "apps={ai-layer}"], capture_output=True, text=True)
check("helm renders the root with ai-layer alone", r.returncode == 0, r.stderr.strip()[:300])
apps = [d for d in yaml.safe_load_all(r.stdout or "") if d and d.get("kind") == "Application"]
app = apps[0] if len(apps) == 1 else {}
src = (app.get("spec") or {}).get("source") or {}
check("it is one Application whose source is gitops/ai-layer", src.get("path") == "gitops/ai-layer", str(src)[:200])
ignored = [d for d in (app.get("spec") or {}).get("ignoreDifferences") or [] if d.get("kind") in ("Role", "RoleBinding")]
check("its ignoreDifferences names no Role or RoleBinding but workshop-agent's Role",
      all(d.get("kind") == "Role" and d.get("name") == rr.SWAPPED for d in ignored), str(ignored))
check("and it self-heals, so a reader Role or binding changed by hand goes back",
      ((app.get("spec") or {}).get("syncPolicy") or {}).get("automated", {}).get("selfHeal") is True)

print("== the kustomize render of gitops/ai-layer ==")
r = subprocess.run([KUBECTL, "kustomize", str(REPO / "gitops/ai-layer")], capture_output=True, text=True)
check("kubectl kustomize builds gitops/ai-layer", r.returncode == 0, r.stderr.strip()[:300])
docs = [d for d in yaml.safe_load_all(r.stdout or "") if isinstance(d, dict)]
deploy = next((d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp"), {})
pod = ((deploy.get("spec") or {}).get("template") or {}).get("spec") or {}
sa = next((d for d in docs if d.get("kind") == "ServiceAccount" and d["metadata"]["name"] == rr.SA), {})
check("the workshop-mcp pod runs as the workshop-mcp ServiceAccount, in agent",
      pod.get("serviceAccountName") == rr.SA and deploy["metadata"].get("namespace") == rr.NS
      and sa.get("metadata", {}).get("namespace") == rr.NS)
check("and holds its token: neither the pod nor the account turns automount off",
      pod.get("automountServiceAccountToken") is not False and sa.get("automountServiceAccountToken") is not False)
src_cm = next((v.get("configMap", {}).get("name") for v in pod.get("volumes") or [] if v.get("name") == "src"), "")
cm = next((d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == src_cm), {})
server_py = (cm.get("data") or {}).get("server.py", "")
check("its src volume is the generated workshop-mcp-src ConfigMap, whose server.py starts the reader",
      src_cm.startswith("workshop-mcp-src-") and "\n    start_cluster_reader()\n" in server_py, src_cm)
check("the rendered server.py is gitops/ai-layer/workshop-mcp-server.py",
      server_py == (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text())


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


if "ROOM_READ_KINDS" not in server_py:
    print(f"FAILED: the render holds no workshop-mcp server.py with the reader in it ({len(failures)} check(s) failed)")
    sys.exit(1)
sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
with tempfile.TemporaryDirectory() as tmp:
    f = pathlib.Path(tmp) / "server.py"
    f.write_text(server_py)
    spec = importlib.util.spec_from_file_location("workshop_mcp_rendered", f)
    mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp)
READ = rr.read_kinds(mcp.ROOM_READ_KINDS)
check("the rendered reader reads seven kinds", len(READ) == 7, str(READ))

terminal = (REPO / "images/web-terminal/entrypoint.sh").read_text()
lab = (REPO / "challenges/LAB-TEXT.md").read_text()
rr.check_all(check, docs, READ, applied_files=rr.applied_role_files(terminal, lab))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all rendered room reader RBAC checks passed")
