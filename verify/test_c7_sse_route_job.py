# ABOUTME: Offline: the c7-sse-route Job (#1323) adds the no-standalone-sse route to a live agentgateway-c7-config built
# ABOUTME: before #1303, as both KubeCon clusters carry it, and keeps the `# c7-rule` line and every other line as they were.
"""Offline: python3, PyYAML and the repo.

Why (#1323). ai-layer ignores agentgateway-c7-config's content, so #1303's 405 route for GET /mcp on the 3003 bind never
reached watch-it-burn-private or watch-it-burn-community, and the agent's evil-mcp session there failed when its
standalone stream was cut at 12 hours. Kyverno's block-argocd-drift refuses a hand edit, so gitops/ai-layer/c7-sse-route.yaml
carries a one-shot Job that makes the edit from Git. This runs the Job's own script:

  * on the two clusters' live config.yaml, as read on 2026-11-11 (private carries #864's frontendPolicies tracing,
    community the older config.tracing), and on each with the rule switched on: the parsed result is the input with
    the committed no-standalone-sse route appended to the 3003 bind's routes, every input line is kept in order, and
    the `# c7-rule` line reads the same;
  * on the committed ConfigMap, which already has the route: nothing to write;
  * on shapes it does not know (no rule line, two of them, no routes list, a key after the list): an error, never a
    guess;
  * its main loop against a fake API server: a write tests the resourceVersion it read, a rule flip between the read
    and the write is read again and kept, and every path exits 0.

And the Job's shape: a plain Sync-phase Job whose name carries the hash of its spec and script, no TTL, run as the
web-terminal ServiceAccount, which already holds the RBAC and block-argocd-drift's exemption for this one ConfigMap and
which the agent may not run a pod as.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import pathlib
import re
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI_LAYER = REPO / "gitops/ai-layer"
JOB_FILE = AI_LAYER / "c7-sse-route.yaml"
GATEWAY = AI_LAYER / "agentgateway.yaml"
RESOURCES = AI_LAYER / "resources.yaml"
DRIFT = REPO / "policies/kyverno/block-argocd-drift.yaml"
SPAWN = REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml"
OTEL_GATE = AI_LAYER / "otel-ordering-gate.yaml"
BASE = "c7-sse-route"
ROUTE_NAME = "no-standalone-sse"
MARK = "# c7-rule"
ON = "'mcp.tool.name == \"get_weather\"'"
HOOK_KEYS = ("argocd.argoproj.io/hook", "argocd.argoproj.io/hook-delete-policy", "helm.sh/hook")
WAVE = "argocd.argoproj.io/sync-wave"

# agentgateway-c7-config's config.yaml as each cluster serves it, read with
# `kubectl --context <ctx> -n agent get cm agentgateway-c7-config -o jsonpath='{.data.config\.yaml}'` on 2026-11-11.
PRIVATE = """\
config:
  adminAddr: "off"
  statsAddr: "off"
  readinessAddr: 0.0.0.0:15022
  session:
    key: disabled # as agentgateway-config: v1.7.0 cannot write a generated key into a ConfigMap (#698)
frontendPolicies:
  tracing: # as agentgateway-config (#864)
    host: otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4318
    protocol: http
    randomSampling: true
binds:
- port: 3003
  listeners:
  - protocol: HTTP
    routes:
    - policies:
        mcpAuthorization:
          rules:
          - 'true' # c7-rule
      backends:
      - mcp:
          targets:
          - name: evil-mcp
            mcp:
              host: http://evil-mcp-shim.agent.svc.cluster.local:8000/mcp
"""
COMMUNITY = """\
config:
  adminAddr: "off"
  statsAddr: "off"
  readinessAddr: 0.0.0.0:15022
  session:
    key: disabled # as agentgateway-config: v1.7.0 cannot write a generated key into a ConfigMap (#698)
  tracing:
    otlpEndpoint: http://otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4318
    otlpProtocol: http
    randomSampling: true
binds:
- port: 3003
  listeners:
  - protocol: HTTP
    routes:
    - policies:
        mcpAuthorization:
          rules:
          - 'true' # c7-rule
      backends:
      - mcp:
          targets:
          - name: evil-mcp
            mcp:
              host: http://evil-mcp-shim.agent.svc.cluster.local:8000/mcp
"""

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs_of(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def find(docs: list[dict], kind: str, name: str) -> dict:
    return next((d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name), {})


def job_hash(job: dict, script: dict) -> str:
    """As test_ai_layer_gates.py's gate_hash: the Job's spec and its script's data, so any edit renames the Job."""
    body = json.dumps({"spec": job.get("spec"), "script": script.get("data")}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:8]


def routes_of(cfg: dict) -> list[dict]:
    return [r for b in cfg.get("binds", []) for li in b.get("listeners", []) for r in li.get("routes", [])]


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("c7-sse-route Job checks passed.")
    sys.exit(0)


docs = docs_of(JOB_FILE) if JOB_FILE.is_file() else []
check(f"{JOB_FILE.relative_to(REPO)} exists", bool(docs))
jobs = [d for d in docs if d["kind"] == "Job"]
script_cm = find(docs, "ConfigMap", f"{BASE}-script")
check(f"it holds one Job and its ConfigMap {BASE}-script", len(jobs) == 1 and bool(script_cm))
if failures:
    finish()
job = jobs[0]
CODE = (script_cm.get("data") or {}).get("route.py", "")
gw_docs = docs_of(GATEWAY)
committed_text = find(gw_docs, "ConfigMap", "agentgateway-c7-config")["data"]["config.yaml"]
committed_route = next((r for r in routes_of(yaml.safe_load(committed_text)) if r.get("name") == ROUTE_NAME), None)
check(f"the committed agentgateway-c7-config has the {ROUTE_NAME} route the Job copies", committed_route is not None)
if failures:
    finish()

print("== the Job's shape ==")
kust = yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text(encoding="utf-8"))
check("c7-sse-route.yaml is in ai-layer's kustomization resources", "c7-sse-route.yaml" in (kust.get("resources") or []))
want = f"{BASE}-{job_hash(job, script_cm)}"
check(f"the Job is named {want}, the hash of its spec and script (it is {job['metadata']['name']}); rename it to that "
      "after any edit, since a Job's pod template is immutable", job["metadata"]["name"] == want)
check(f"the Job is labelled app.kubernetes.io/name={BASE}, which the recovery delete in the file's header selects on",
      (job["metadata"].get("labels") or {}).get("app.kubernetes.io/name") == BASE)
hooked = [f"{d['kind']}/{d['metadata']['name']}" for d in docs
          if any(k in ((d.get("metadata") or {}).get("annotations") or {}) for k in HOOK_KEYS)]
check(f"no object is a hook ({hooked or 'none'}), so a self-heal does not re-run the Job", not hooked)
waves = [((d.get("metadata") or {}).get("annotations") or {}).get(WAVE, "0") for d in docs]
check(f"no object is at a wave before 0 ({waves}), where the ordering gates alone sit", all(int(w) >= 0 for w in waves))
spec = job.get("spec") or {}
check("the Job has no ttlSecondsAfterFinished (a deleted Job reads as missing and self-heal would re-run it)",
      "ttlSecondsAfterFinished" not in spec)
pod = (spec.get("template") or {}).get("spec") or {}
check("the pod mounts the Job's own script and runs it",
      any((v.get("configMap") or {}).get("name") == f"{BASE}-script" for v in pod.get("volumes") or [])
      and any("/job/route.py" in " ".join(c.get("command") or []) for c in pod.get("containers") or []))
gate_image = next(c["image"] for c in find(docs_of(OTEL_GATE), "Job", next(
    d["metadata"]["name"] for d in docs_of(OTEL_GATE) if d["kind"] == "Job"))["spec"]["template"]["spec"]["containers"])
images = [c.get("image") for c in pod.get("containers") or []]
check(f"it runs the otel gate's pinned python image, which both clusters already admit ({images})", images == [gate_image])
check("it runs as the web-terminal ServiceAccount", pod.get("serviceAccountName") == "web-terminal")
exits = re.findall(r"sys\.exit\((\d+)\)", CODE)
check(f"the script exits 0 on every path it names (exits: {exits}), so the Job fails only when its pod cannot run",
      bool(exits) and set(exits) == {"0"})
budget = re.search(r"def main\(deadline_s=(\d+), pause=(\d+)\)", CODE)
deadline = spec.get("activeDeadlineSeconds")
check(f"activeDeadlineSeconds ({deadline}) outlasts the script's own deadline plus a minute",
      bool(budget) and isinstance(deadline, int) and deadline >= int(budget.group(1)) + int(budget.group(2)) + 60)

print("== web-terminal already may write this ConfigMap, and the agent may not run as it ==")
res_docs = docs_of(RESOURCES)
check("ai-layer creates the web-terminal ServiceAccount", bool(find(res_docs, "ServiceAccount", "web-terminal")))
binding = find(res_docs, "ClusterRoleBinding", "console-terminal")
check("console-terminal is bound to agent/web-terminal",
      {"kind": "ServiceAccount", "name": "web-terminal", "namespace": "agent"} in binding.get("subjects", []))
rules = find(res_docs, "ClusterRole", "console-terminal").get("rules", [])
cm_verbs = {v for r in rules
            if {"", "*"} & set(r.get("apiGroups", [])) and {"configmaps", "*"} & set(r.get("resources", []))
            and (not r.get("resourceNames") or "agentgateway-c7-config" in r["resourceNames"])
            for v in r.get("verbs", [])}
check(f"console-terminal gets and patches agentgateway-c7-config, as RBAC reads its rules ({sorted(cm_verbs)})",
      {"get", "patch"} <= cm_verbs or "*" in cm_verbs)
conds = {c["name"]: c["expression"] for c in yaml.safe_load(DRIFT.read_text())["spec"]["matchConditions"]}
exempt = conds.get("not-terminal-c7-rule", "")
check("block-argocd-drift's not-terminal-c7-rule exempts web-terminal's UPDATE of agentgateway-c7-config",
      "system:serviceaccount:agent:web-terminal" in exempt and "'UPDATE'" in exempt
      and "'agentgateway-c7-config'" in exempt, exempt)
spawn = yaml.safe_load(SPAWN.read_text())
idents = next((v["expression"] for v in spawn["spec"]["variables"] if v["name"] == "modelIdentities"), "")
check(f"restrict-agent-spawned-workloads keeps the agent from running a pod as web-terminal ({idents})",
      "'web-terminal'" in idents)

print("== the script's route is the committed one ==")
ns: dict = {"__name__": "c7_sse_route"}
exec(compile(CODE, "route.py", "exec"), ns)  # noqa: S102 - the repo's own script, run offline
script_route = yaml.safe_load(ns["ROUTE"])
check(f"ROUTE parses as one route equal to the committed {ROUTE_NAME} route ({script_route})",
      script_route == [committed_route])
add_route, rule_line = ns["add_route"], ns["rule_line"]

print("== on each cluster's live config, and with the rule on ==")
cases = {"watch-it-burn-private": PRIVATE, "watch-it-burn-community": COMMUNITY}
for label, text in list(cases.items()):
    cases[f"{label}, rule on"] = text.replace("- 'true' # c7-rule", f"- {ON} # c7-rule")
for label, text in cases.items():
    check(f"{label}: the fixture has one rule line and no 405 route",
          sum(ln.rstrip().endswith(MARK) for ln in text.split("\n")) == 1 and ROUTE_NAME not in text)
    out = add_route(text)
    if out is None:
        check(f"{label}: the script writes a config", False)
        continue
    before, after = yaml.safe_load(text), yaml.safe_load(out)
    want_cfg = copy.deepcopy(before)
    want_cfg["binds"][0]["listeners"][0]["routes"].append(committed_route)
    check(f"{label}: parsed, the result is the input with the committed route appended to the 3003 bind",
          after == want_cfg, out)
    check(f"{label}: the 405 route sits after the MCP route, so routes[0] is still the MCP route",
          [r.get("name") for r in routes_of(after)] == [None, ROUTE_NAME])
    check(f"{label}: every input line is kept, in order, and only lines are added after them",
          out.split("\n")[:len(text.rstrip("\n").split("\n"))] == text.rstrip("\n").split("\n"))
    check(f"{label}: the `# c7-rule` line reads the same ({rule_line(out).strip()})", rule_line(out) == rule_line(text))
    check(f"{label}: the result ends in a newline, as the block scalar it replaces", out.endswith("\n"))
    check(f"{label}: run again on its own output, it writes nothing", add_route(out) is None)
check("on the committed ConfigMap, which has the route, it writes nothing", add_route(committed_text) is None)

print("== shapes it does not know are an error, never a guess ==")
bad = {
    "no rule line": PRIVATE.replace(" # c7-rule", ""),
    "two rule lines": PRIVATE.replace("- 'true' # c7-rule", "- 'true' # c7-rule\n          - 'true' # c7-rule"),
    "no routes list": PRIVATE.replace("    routes:\n", "    rules:\n"),
    "a listener after the routes list": PRIVATE + "  - protocol: HTTP\n    routes: []\n",
    "a key after the routes list": PRIVATE + "    policies: {}\n",
}
for label, text in bad.items():
    try:
        add_route(text)
        check(f"{label}: refused", False, "add_route returned a config")
    except ValueError as e:
        check(f"{label}: refused ({e})", True)


class FakeApi:
    """agentgateway-c7-config on an API server: GET returns it, a JSON patch whose resourceVersion test fails is a
    422, and `flip_on_first_patch` switches the rule on just before the first patch lands, as guard-mcp-on would."""

    def __init__(self, text: str, flip_on_first_patch: bool = False) -> None:
        self.text, self.rv, self.flip = text, 1, flip_on_first_patch
        self.patches: list[list[dict]] = []

    def __call__(self, method: str, body=None) -> dict:
        if method == "GET":
            return {"metadata": {"resourceVersion": str(self.rv)}, "data": {"config.yaml": self.text}}
        self.patches.append(body)
        if self.flip:
            self.flip = False
            self.text, self.rv = self.text.replace("- 'true' # c7-rule", f"- {ON} # c7-rule"), self.rv + 1
        test, replace = body
        if test != {"op": "test", "path": "/metadata/resourceVersion", "value": str(self.rv)}:
            raise urllib.error.HTTPError("https://api/x", 422, "Unprocessable", {}, io.BytesIO(b"test failed"))
        self.text, self.rv = replace["value"], self.rv + 1
        return {}


def drive(fake: FakeApi, deadline_s: float = 5, pause: float = 0) -> tuple[int | None, str]:
    ns["api"] = fake
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            ns["main"](deadline_s=deadline_s, pause=pause)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


print("== the main loop, against a fake API server ==")
fake = FakeApi(PRIVATE)
code, out = drive(fake)
check(f"a config without the route: one patch, exit 0 ({code}, {len(fake.patches)} patch(es))",
      code == 0 and len(fake.patches) == 1, out)
check("the patch tests the resourceVersion it read first, then replaces config.yaml",
      bool(fake.patches) and fake.patches[0][0]["op"] == "test"
      and fake.patches[0][0]["path"] == "/metadata/resourceVersion"
      and fake.patches[0][1]["op"] == "replace" and fake.patches[0][1]["path"] == "/data/config.yaml")
check("the server now holds the route and the same rule line, and the log says so",
      ROUTE_NAME in fake.text and rule_line(fake.text) == rule_line(PRIVATE) and "added the no-standalone-sse" in out, out)

fake = FakeApi(COMMUNITY, flip_on_first_patch=True)
code, out = drive(fake)
check(f"a rule flip between the read and the write: the 422 is read again, exit 0 ({code}, {len(fake.patches)} patches)",
      code == 0 and len(fake.patches) == 2 and "HTTP 422" in out, out)
check("and the flip is kept: the rule reads on, with the route added",
      ROUTE_NAME in fake.text and rule_line(fake.text).strip() == f"- {ON} {MARK}", fake.text)

fake = FakeApi(committed_text)
code, out = drive(fake)
check(f"a config with the route: no patch, exit 0 ({code})", code == 0 and not fake.patches and "nothing to do" in out, out)

fake = FakeApi(bad["two rule lines"])
code, out = drive(fake)
check(f"an unknown shape: no patch, exit 0, and the log names it ({code})",
      code == 0 and not fake.patches and "NOT ADDED" in out, out)


class DownApi(FakeApi):
    def __call__(self, method: str, body=None) -> dict:
        raise OSError("connection refused")


code, out = drive(DownApi(PRIVATE), deadline_s=0.2, pause=0.05)
check(f"an API server it cannot reach: it gives up at its deadline, exit 0, naming the cause ({code})",
      code == 0 and "NOT ADDED after" in out and "connection refused" in out, out[-500:])

finish()
