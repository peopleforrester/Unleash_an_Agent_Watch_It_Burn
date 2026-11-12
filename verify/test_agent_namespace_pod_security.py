# ABOUTME: Holds Pod Security Admission baseline on namespace agent (#1410), so a privileged, hostPath, hostNetwork or
# ABOUTME: hostPID pod from the agent is refused, and checks every pod template the repo ships into agent meets it.
"""Why this exists (#1410, rounds-agenticburn#152).

The agent's Role creates pods and Deployments in namespace `agent`, and `deploy_app` applies whatever YAML the model
writes. Until #1410 that namespace carried no Pod Security Admission label, and `disallow-privileged` matches only
`apps`, so a server dry-run of a privileged, hostPath, hostPID pod as agent-sa was admitted on both KubeCon clusters
on 2026-11-04 (docs/research/2026-11-02-privileged-pod-hostpath-escape.md). PSA runs inside the API server, so a
label refuses that pod on the community cluster too, which runs no Kyverno.

These checks hold:

* namespace `agent` enforces baseline (or stricter) on the latest version, and warns at least at baseline;
* the checker below, which reads the baseline fields, flags each escape shape: privileged, hostPath, hostNetwork,
  hostPID, hostIPC, a hostPort and an added capability outside baseline's list;
* every pod template the repo ships into `agent` (each Argo CD Application whose destination is `agent`, and any
  manifest under gitops/ that names namespace agent) meets baseline, so the label refuses nothing the platform runs
  and a later manifest that would be refused fails here, not in an Argo CD sync.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
NAMESPACES = "gitops/namespaces/namespaces.yaml"
APPS_DIR = "gitops/bootstrap/apps"
NS = "agent"
LEVELS = {"privileged": 0, "baseline": 1, "restricted": 2}
# The Pod Security Standards baseline profile's allowed added capabilities.
BASELINE_CAPS = {"AUDIT_WRITE", "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL", "MKNOD", "NET_BIND_SERVICE",
                 "SETFCAP", "SETGID", "SETPCAP", "SETUID", "SYS_CHROOT"}
# Pod-template kinds and the path from the object to its pod spec.
POD_PATHS = {
    "Pod": ("spec",),
    "Deployment": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "ReplicaSet": ("spec", "template", "spec"),
    "Job": ("spec", "template", "spec"),
    "CronJob": ("spec", "jobTemplate", "spec", "template", "spec"),
}
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(d, dict)]


def pod_spec(obj: dict) -> dict | None:
    node: object = obj
    for key in POD_PATHS.get(obj.get("kind", ""), ()):
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) and obj.get("kind") in POD_PATHS else None


def baseline_violations(spec: dict) -> list[str]:
    """What in a pod spec the Pod Security Standards baseline profile forbids (the fields an escape uses)."""
    found = [f"spec.{f}" for f in ("hostNetwork", "hostPID", "hostIPC") if spec.get(f) is True]
    found += [f"hostPath volume {v.get('name')}" for v in spec.get("volumes") or [] if "hostPath" in v]
    pod_sc = spec.get("securityContext") or {}
    if (pod_sc.get("seccompProfile") or {}).get("type") == "Unconfined":
        found.append("pod seccompProfile Unconfined")
    if (pod_sc.get("windowsOptions") or {}).get("hostProcess") is True:
        found.append("pod windowsOptions.hostProcess")
    containers = [c for key in ("initContainers", "containers", "ephemeralContainers") for c in spec.get(key) or []]
    for c in containers:
        name, sc = c.get("name"), c.get("securityContext") or {}
        if sc.get("privileged") is True:
            found.append(f"container {name} privileged")
        extra = set((sc.get("capabilities") or {}).get("add") or []) - BASELINE_CAPS
        if extra:
            found.append(f"container {name} adds {sorted(extra)}")
        if sc.get("procMount") not in (None, "Default"):
            found.append(f"container {name} procMount {sc.get('procMount')}")
        if (sc.get("seccompProfile") or {}).get("type") == "Unconfined":
            found.append(f"container {name} seccompProfile Unconfined")
        if (sc.get("windowsOptions") or {}).get("hostProcess") is True:
            found.append(f"container {name} windowsOptions.hostProcess")
        found += [f"container {name} hostPort {p['hostPort']}" for p in c.get("ports") or [] if p.get("hostPort")]
    return found


print(f"== namespace {NS} enforces Pod Security baseline ==")
ns_doc = next((d for d in docs(REPO / NAMESPACES) if d.get("kind") == "Namespace" and d["metadata"]["name"] == NS),
              None)
check(f"{NAMESPACES} declares namespace {NS}", ns_doc is not None)
labels = (ns_doc or {}).get("metadata", {}).get("labels") or {}
enforce = labels.get("pod-security.kubernetes.io/enforce")
check(f"{NS} enforces baseline or stricter", LEVELS.get(enforce, -1) >= LEVELS["baseline"], f"enforce: {enforce!r}")
check(f"{NS} enforces the latest version of the standard",
      labels.get("pod-security.kubernetes.io/enforce-version") == "latest",
      f"enforce-version: {labels.get('pod-security.kubernetes.io/enforce-version')!r}")
warn = labels.get("pod-security.kubernetes.io/warn")
check(f"{NS} warns at baseline or stricter, so an applied Deployment names the refusal",
      LEVELS.get(warn, -1) >= LEVELS["baseline"], f"warn: {warn!r}")

print("== the checker flags each escape shape ==")
# The pod from the research note's attack, then each field alone.
escape = yaml.safe_load("""
hostPID: true
containers:
  - name: shell
    image: busybox
    securityContext: { privileged: true }
    volumeMounts: [{ name: host, mountPath: /host }]
volumes:
  - { name: host, hostPath: { path: / } }
""")
check("the research note's escape pod is flagged three ways", len(baseline_violations(escape)) == 3,
      f"{baseline_violations(escape)}")
plain = {"containers": [{"name": "c", "image": "busybox"}]}
check("a plain pod is not flagged", baseline_violations(plain) == [], f"{baseline_violations(plain)}")
SHAPES = {
    "privileged": {"containers": [{"name": "c", "securityContext": {"privileged": True}}]},
    "privileged initContainer": {"containers": [{"name": "c"}],
                                 "initContainers": [{"name": "i", "securityContext": {"privileged": True}}]},
    "hostPath": {"containers": [{"name": "c"}], "volumes": [{"name": "h", "hostPath": {"path": "/"}}]},
    "hostNetwork": {"hostNetwork": True, "containers": [{"name": "c"}]},
    "hostPID": {"hostPID": True, "containers": [{"name": "c"}]},
    "hostIPC": {"hostIPC": True, "containers": [{"name": "c"}]},
    "hostPort": {"containers": [{"name": "c", "ports": [{"containerPort": 80, "hostPort": 80}]}]},
    "SYS_ADMIN": {"containers": [{"name": "c", "securityContext": {"capabilities": {"add": ["SYS_ADMIN"]}}}]},
}
for shape, spec in SHAPES.items():
    check(f"{shape} is flagged", len(baseline_violations(spec)) == 1, f"{baseline_violations(spec)}")

print(f"== every pod template the repo ships into {NS} meets baseline ==")
sources: set[str] = set()
for app_file in sorted((REPO / APPS_DIR).glob("*.yaml")):
    for app in docs(app_file):
        spec = app.get("spec") or {}
        if (spec.get("destination") or {}).get("namespace") != NS:
            continue
        for src in [spec["source"]] if spec.get("source") else spec.get("sources") or []:
            if src.get("path") and "Unleash_an_Agent_Watch_It_Burn" in src.get("repoURL", ""):
                sources.add(src["path"])
check(f"the Applications that deploy into {NS} include gitops/ai-layer", "gitops/ai-layer" in sources,
      f"sources: {sorted(sources)}")
# Every source path sits under gitops/ or policies/, so the manifests are read from those two trees.
manifests = {p.relative_to(REPO).as_posix(): p for root in (REPO / "gitops", REPO / "policies")
             for p in root.rglob("*.y*ml") if p.is_file()}
files: set[pathlib.Path] = set()
for rel in sorted(sources):
    under = {p for name, p in manifests.items() if name.startswith(rel.rstrip("/") + "/")}
    check(f"{rel} holds manifests under gitops/ or policies/", bool(under))
    files.update(under)
# A manifest elsewhere under gitops/ that names namespace agent also lands there.
named_elsewhere = {p for name, p in manifests.items()
                   if name.startswith("gitops/") and "namespace: agent" in p.read_text(encoding="utf-8")}
templates: list[tuple[str, dict]] = []
for path in sorted(files | named_elsewhere):
    in_source = path in files
    for obj in docs(path):
        ns = (obj.get("metadata") or {}).get("namespace")
        if not (ns == NS or (ns is None and in_source)):
            continue
        spec = pod_spec(obj)
        if spec is not None:
            templates.append((f"{path.relative_to(REPO)} {obj['kind']}/{obj['metadata'].get('name')}", spec))
names = " ".join(t for t, _ in templates)
check(f"the pod templates found include the platform's own (workshop-mcp, guard-proxy, console); {len(templates)} found",
      all(f"Deployment/{n} " in names + " " for n in ("workshop-mcp", "guard-proxy", "console")), names)
for where, spec in templates:
    check(f"{where} meets baseline", not baseline_violations(spec), f"{baseline_violations(spec)}")

print()
if failures:
    print(f"FAIL: {len(failures)} check(s) failed")
    sys.exit(1)
print("PASS: namespace agent enforces Pod Security baseline, and every pod template shipped into it meets baseline")
