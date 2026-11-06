# ABOUTME: Offline: ai-layer's two ordering gates (kubearmor-gate, otel-gate) are plain wave -1 resources, not hooks,
# ABOUTME: so a full-sync self-heal does not delete, re-create and re-run them (#898), and they still run before wave 0.
"""Offline: python3, PyYAML and the repo.

Why. As PreSync hooks the gates ran on every full sync of ai-layer, and the first self-heal after any commit on
staging is a full sync: 20.1, 25.2 and 27.2 s on 2026-11-05 to put back a deleted NetworkPolicy, against the 30 s
window docs/floor.md documents, and 29 s on watch-it-burn-private on 2026-11-06 at 03:47Z, of which 24 s went to the
hooks. As Sync-phase resources at wave -1 they run once, when the Job is first created; a later full sync re-applies
the Complete Job as a no-op. Argo CD (gitops-engine's sync_context.go, v3.5.7) holds a later wave until every
plain resource of the wave before it reads Healthy, and a Job reads Healthy only once Complete. So on a fresh
cluster workshop-mcp is still admitted after the KubeArmor webhook, and guard-proxy after the OTel webhook,
provided nothing the gates hold back sits at wave -1 or lower. That is what this checks, with the shape a plain Job
needs to stay Synced: a name that changes with its spec (the pod template is immutable) and no TTL.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI_LAYER = REPO / "gitops/ai-layer"
GATES = {"kubearmor-gate": "kubearmor-ordering-gate.yaml", "otel-gate": "otel-ordering-gate.yaml"}
WAVE = "argocd.argoproj.io/sync-wave"
HOOK_KEYS = ("argocd.argoproj.io/hook", "argocd.argoproj.io/hook-delete-policy", "helm.sh/hook")
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def gate_hash(job: dict, script: dict) -> str:
    """The suffix a gate Job's name carries: its spec and its script's data, so any edit to either renames it."""
    body = json.dumps({"spec": job.get("spec"), "script": script.get("data")}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:8]


def docs_of(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def annotations(doc: dict) -> dict:
    return (doc.get("metadata") or {}).get("annotations") or {}


print("== the hash names an edit ==")
probe_job, probe_cm = {"spec": {"backoffLimit": 3}}, {"data": {"gate.py": "print(1)"}}
check("the suffix is eight hex characters", re.fullmatch(r"[0-9a-f]{8}", gate_hash(probe_job, probe_cm)) is not None)
check("editing the Job spec changes the suffix",
      gate_hash(probe_job, probe_cm) != gate_hash({"spec": {"backoffLimit": 4}}, probe_cm))
check("editing the script changes the suffix",
      gate_hash(probe_job, probe_cm) != gate_hash(probe_job, {"data": {"gate.py": "print(2)"}}))

kust = yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text(encoding="utf-8"))
resources = kust.get("resources") or []

for base, fname in GATES.items():
    print(f"== {fname} ({base}) ==")
    check(f"{fname} is in ai-layer's kustomization resources", fname in resources)
    path = AI_LAYER / fname
    check(f"{fname} exists", path.is_file())
    if not path.is_file():
        continue
    docs = docs_of(path)
    hooked = [f"{d['kind']}/{d['metadata']['name']}" for d in docs if any(k in annotations(d) for k in HOOK_KEYS)]
    check(f"no object in {fname} is a hook ({', '.join(hooked) or 'none'}), so a full sync does not re-run it",
          not hooked)
    waves = sorted({str(annotations(d).get(WAVE)) for d in docs})
    check(f"every object in {fname} is at sync-wave -1 (found {', '.join(waves)})", waves == ["-1"])
    jobs = [d for d in docs if d["kind"] == "Job"]
    scripts = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == f"{base}-script"]
    check(f"{fname} holds one Job and its ConfigMap {base}-script", len(jobs) == 1 and len(scripts) == 1)
    if len(jobs) != 1 or len(scripts) != 1:
        continue
    job, script = jobs[0], scripts[0]
    want = f"{base}-{gate_hash(job, script)}"
    check(f"the Job is named {want}, the hash of its spec and script (it is {job['metadata']['name']}); "
          "rename it to that after any edit, since a Job's pod template is immutable",
          job["metadata"]["name"] == want)
    check(f"the Job is labelled app.kubernetes.io/name={base}, which the recovery delete in its comment selects on",
          ((job["metadata"].get("labels") or {}).get("app.kubernetes.io/name")) == base)
    spec = job.get("spec") or {}
    check("the Job has no ttlSecondsAfterFinished (a deleted Job reads as missing and self-heal would re-run it)",
          "ttlSecondsAfterFinished" not in spec)
    pod = (spec.get("template") or {}).get("spec") or {}
    check("the Job's pod mounts the gate's own script", any(
        (v.get("configMap") or {}).get("name") == f"{base}-script" for v in pod.get("volumes") or []))
    check("the Job's pod runs as the gate's ServiceAccount, which this file creates in the same wave",
          pod.get("serviceAccountName") == base
          and any(d["kind"] == "ServiceAccount" and d["metadata"]["name"] == base for d in docs))
    code = (script.get("data") or {}).get("gate.py", "")
    exits = re.findall(r"sys\.exit\((\d+)\)", code)
    check(f"the gate script exits 0 on every path it names (exits: {', '.join(exits) or 'none'}), so the Job fails "
          "only when its pod cannot run", bool(exits) and set(exits) == {"0"})
    # `time.time() + 420` (a deadline) and `time.time() - t0 > 90` (a bounded look) are the script's waits.
    waits = [int(n) for n in re.findall(r"time\.time\(\)\s*[-+]\s*(?:t0\s*>\s*)?(\d+)", code)]
    check(f"the script's waits are bounded and found ({waits})", bool(waits))
    budget = sum(waits) + 60
    deadline = spec.get("activeDeadlineSeconds")
    check(f"activeDeadlineSeconds ({deadline}) outlasts the script's own waits plus a minute ({budget} s), so the "
          "script degrades and exits 0 before Kubernetes fails the Job", isinstance(deadline, int) and deadline >= budget)

print("== everything the gates hold back is at a later wave ==")
later: list[str] = []
for res in resources:
    if res in GATES.values():
        continue
    path = AI_LAYER / res
    check(f"{res} exists", path.is_file())
    if not path.is_file():
        continue
    for d in docs_of(path):
        wave = annotations(d).get(WAVE, "0")
        hooks = [k for k in HOOK_KEYS if k in annotations(d)]
        where = f"{res}: {d.get('kind')}/{(d.get('metadata') or {}).get('name')}"
        if int(wave) <= -1:
            later.append(f"{where} at wave {wave}")
        if hooks:
            later.append(f"{where} is a hook ({', '.join(hooks)})")
check(f"no other ai-layer object is at wave -1 or lower, or is a hook ({'; '.join(later) or 'none'})", not later)
for name in ("workshop-mcp", "guard-proxy"):
    found = any(d.get("kind") == "Deployment" and d["metadata"]["name"] == name
                for res in resources if res not in GATES.values() and (AI_LAYER / res).is_file()
                for d in docs_of(AI_LAYER / res))
    check(f"the gated Deployment {name} is in this bundle, so the wave order above covers it", found)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ai-layer gate checks passed.")
