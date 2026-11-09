# ABOUTME: A console rollout must not 502 a chat turn (#1258): the console drains past the NLB's deregistration
# ABOUTME: delay before nginx stops, and a new console pod is Ready only once the NLB has it registered and healthy.
"""Holds the three settings that keep a console rollout from dropping a chat turn (#1258).

Run 19462 (#1232) saw POST /chat return 502 on burritobot-private.burritobot.co while Argo CD rolled the console
Deployment. The console had no preStop, so nginx stopped the moment its pod was deleted, while the NLB, whose ip
targets the AWS load balancer controller deregisters only after the pod leaves the endpoints, still sent it new
connections. And the agent namespace had no readiness-gate label, so a new pod counted as Ready, and the old one
was deleted, before the NLB had the new one registered.

What this holds, in git, for every profile that ships the ai-layer and namespaces Applications, both KubeCon
clusters among them:

  1. the console's nginx container has a preStop sleep longer than the deregistration delay its Service sets on
     the NLB's target groups (the NLB default, 300s, when the Service sets none);
  2. its terminationGracePeriodSeconds covers that sleep plus the longest /chat turn console.conf allows, so a
     turn in flight when the rollout starts is answered;
  3. the agent namespace carries elbv2.k8s.aws/pod-readiness-gate-inject=enabled.

It then removes each setting from a copy of the parsed manifests and checks that the same rules fail, so the test
cannot pass on a rule that no longer reads what it names. The live half is verify/test_console_rollout_drain_live.py.

Usage: python3 verify/test_console_rollout_drain.py
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
NAMESPACES = REPO / "gitops/namespaces/namespaces.yaml"
CONSOLE_CONF = REPO / "gitops/ai-layer/console.conf"
PROFILES = sorted((REPO / "gitops/bootstrap").glob("values-kubecon-*.yaml"))
TG_ATTRS = "service.beta.kubernetes.io/aws-load-balancer-target-group-attributes"
GATE_LABEL = "elbv2.k8s.aws/pod-readiness-gate-inject"
NLB_DEFAULT_DELAY = 300

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(d, dict)]


def find(ds: list[dict], kind: str, name: str) -> dict | None:
    return next((d for d in ds if d.get("kind") == kind and d.get("metadata", {}).get("name") == name), None)


def chat_read_timeout(conf: str) -> int:
    m = re.search(r"location = /chat \{(.*?)\n  \}", conf, re.S)
    t = re.search(r"proxy_read_timeout (\d+)s;", m.group(1)) if m else None
    return int(t.group(1)) if t else 0


def deregistration_delay(svc: dict) -> int:
    attrs = (svc.get("metadata", {}).get("annotations") or {}).get(TG_ATTRS, "")
    pairs = dict(p.strip().split("=", 1) for p in attrs.split(",") if "=" in p)
    v = pairs.get("deregistration_delay.timeout_seconds")
    return int(v) if v and v.isdigit() else NLB_DEFAULT_DELAY


def problems(resources: list[dict], namespaces: list[dict], chat_timeout: int) -> list[str]:
    """Every way the manifests fall short of a drained, registered rollout. Empty means they hold."""
    out = []
    dep, svc, ns = find(resources, "Deployment", "console"), find(resources, "Service", "console"), \
        find(namespaces, "Namespace", "agent")
    if not (dep and svc and ns):
        return [f"a manifest is missing: Deployment console {bool(dep)}, Service console {bool(svc)}, "
                f"Namespace agent {bool(ns)}"]
    pod = dep["spec"]["template"]["spec"]
    nginx = next((c for c in pod.get("containers", []) if c.get("name") == "nginx"), {})
    sleep = (((nginx.get("lifecycle") or {}).get("preStop") or {}).get("sleep") or {}).get("seconds")
    delay = deregistration_delay(svc)
    if not isinstance(sleep, int):
        out.append("the console's nginx container has no lifecycle.preStop.sleep.seconds")
    elif sleep <= delay:
        out.append(f"the preStop sleep ({sleep}s) is not longer than the target groups' deregistration delay "
                   f"({delay}s)")
    grace = pod.get("terminationGracePeriodSeconds", 30)
    if isinstance(sleep, int) and grace < sleep + chat_timeout:
        out.append(f"terminationGracePeriodSeconds {grace} is under the preStop sleep plus the /chat "
                   f"proxy_read_timeout ({sleep} + {chat_timeout})")
    if (ns.get("metadata", {}).get("labels") or {}).get(GATE_LABEL) != "enabled":
        out.append(f"the agent namespace does not carry {GATE_LABEL}=enabled")
    return out


resources, namespaces = docs(RESOURCES), docs(NAMESPACES)
chat_timeout = chat_read_timeout(CONSOLE_CONF.read_text(encoding="utf-8"))

print("== git holds a drained, registered console rollout ==")
check(f"console.conf gives /chat a proxy_read_timeout (got {chat_timeout}s)", chat_timeout > 0)
found = problems(resources, namespaces, chat_timeout)
check("the console Deployment, its Service and the agent namespace hold all three settings", not found,
      "; ".join(found))
svc = find(resources, "Service", "console") or {}
check(f"the Service sets the deregistration delay itself (got {deregistration_delay(svc)}s, NLB default "
      f"{NLB_DEFAULT_DELAY}s)", TG_ATTRS in (svc.get("metadata", {}).get("annotations") or {}))

print("== both KubeCon clusters ship it ==")
check(f"there are two KubeCon profiles (got {[p.name for p in PROFILES]})", len(PROFILES) == 2)
for p in PROFILES:
    apps = yaml.safe_load(p.read_text(encoding="utf-8")).get("apps") or []
    check(f"{p.name} lists the ai-layer and namespaces Applications", "ai-layer" in apps and "namespaces" in apps,
          f"apps: {apps}")
# The front door patch (#638) is the one place a profile edits the console Service: it must not replace the
# annotations map, or the deregistration delay would be dropped on exactly the clusters that set a certificate.
app = (REPO / "gitops/bootstrap/apps/ai-layer.yaml").read_text(encoding="utf-8")
check("the ai-layer Application's console Service patch adds annotations one by one, never the whole map",
      "path: /metadata/annotations\n" not in app and TG_ATTRS.replace("/", "~1") not in app)
components = sorted((REPO / "gitops/ai-layer/components").glob("*/kustomization.yaml"))
patched = [c.parent.name for c in components
           if re.search(r"kind: Deployment\s+name: console\b", c.read_text(encoding="utf-8"))]
check("no ai-layer component patches the console Deployment", not patched, f"patched by: {patched}")

print("== each setting removed is caught ==")


def without(mutate) -> list[str]:
    r, n = copy.deepcopy(resources), copy.deepcopy(namespaces)
    mutate(r, n)
    return problems(r, n, chat_timeout)


def nginx_of(r: list[dict]) -> dict:
    return next(c for c in find(r, "Deployment", "console")["spec"]["template"]["spec"]["containers"]
                if c["name"] == "nginx")


cases = {
    "the preStop sleep removed": lambda r, n: nginx_of(r).pop("lifecycle", None),
    "the preStop sleep cut to the deregistration delay":
        lambda r, n: nginx_of(r)["lifecycle"]["preStop"]["sleep"].update(
            seconds=deregistration_delay(find(r, "Service", "console"))),
    "the Service's deregistration delay removed (the NLB's 300s default)":
        lambda r, n: find(r, "Service", "console")["metadata"]["annotations"].pop(TG_ATTRS, None),
    "the grace period removed (Kubernetes' 30s default)":
        lambda r, n: find(r, "Deployment", "console")["spec"]["template"]["spec"].pop(
            "terminationGracePeriodSeconds", None),
    "the readiness-gate label removed": lambda r, n: find(n, "Namespace", "agent")["metadata"]["labels"].pop(
        GATE_LABEL, None),
}
for name, mutate in cases.items():
    try:
        caught = without(mutate)
    except (KeyError, TypeError, StopIteration) as e:
        check(f"{name}: the case could be built from git", False, f"{type(e).__name__}: {e}")
        continue
    check(f"{name}: the rules fail", bool(caught))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The console drains past the NLB's deregistration delay and registers before it takes traffic.")
