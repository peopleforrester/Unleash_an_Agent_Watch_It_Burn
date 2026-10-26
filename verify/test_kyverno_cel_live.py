# ABOUTME: Live half of the Kyverno CEL migration (#206, #467): the policies Argo CD installs, the Beat-1/C2
# ABOUTME: toggle holding against selfHeal, the C2 refusal and report text, and signed images behind the C1 seal.
# SUITE: e2e
"""Needs kubectl, jq and CONTEXT naming a fresh full-profile or attendee cluster. Every missing prerequisite
is a failure with the reason, never a skip.

Why (#467). test_kyverno_cel_policies.py proves each CEL expression with the Kyverno CLI on fixture requests.
What it cannot show is the cluster: that Argo CD pruned the old ClusterPolicy objects, that the engine took
every new policy (READY), that the Applications settle Synced with no drift on the defaults the API server
fills in, that a live flip to Deny survives selfHeal (ignoreDifferences on /spec/validationActions), and that
the words the room sees, the refusal and the lab's PolicyReport line, are the words the lab prints.

In order, against CONTEXT:
  1. no kyverno.io ClusterPolicy is left;
  2. the ValidatingPolicies and ImageValidatingPolicies on the cluster are exactly the ones in
     policies/kyverno/ and policies/floor/, each READY;
  3. the kyverno-policies and minimal-floor Applications are Synced and Healthy;
  4. with restrict-image-registries in Audit, the lab's villain Deployment is admitted, and the lab's own
     policyreport jq (read from challenges/LAB-TEXT.md) prints the line the lab shows;
  5. toggle-kyverno-enforce.sh flips both policies to Deny, and they stay Deny through a hard refresh of
     kyverno-policies while the Application stays Synced;
  6. the C2 villain Deployment, as agent-sa, is refused with 'Policy restrict-image-registries failed: ...';
  7. with the Challenge 1 NetworkPolicies on the agent namespace, a Deployment of our signed image admits
     and its Pod runs.
The cluster is put back as found: both policies' validationActions, and the C1 policies if this applied
them. Everything it creates is labelled wib.test/run=<id> and deleted on the way out.

beat-01.sh and the C2 badge are not repeated here: run-e2e.sh runs run-all.sh (beat-01) and
test_kubecon_probe's live probe.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/test_kyverno_cel_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import uuid

import yaml

from kubecon_probe import C2_CHECK, C2_MANIFEST

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_FILES = sorted((REPO / "policies/kyverno").glob("*.yaml")) + sorted((REPO / "policies/floor").glob("*.yaml"))
REG_FILE = REPO / "policies/kyverno/restrict-image-registries.yaml"
LAB = REPO / "challenges/LAB-TEXT.md"
TOGGLE = REPO / "challenges/01-cncf-wall/toggle-kyverno-enforce.sh"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
TOGGLED = ("require-resource-limits", "restrict-image-registries")
APPS = ("kyverno-policies", "minimal-floor")
CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")
# The reports controller rescans every 30s (gitops/bootstrap/apps/kyverno.yaml); four rescans covers a busy controller.
REPORT_TIMEOUT_S = 150
# How long the flip must hold after the hard refresh: long enough for a refresh, a diff and a selfHeal sync.
HOLD_S = 90
SIGNED = ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
          "@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live Kyverno CEL migration checks passed.")


KUBECTL = shutil.which("kubectl")
JQ = shutil.which("jq")


def kubectl(*args: str, stdin: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run([KUBECTL, "--context", CONTEXT, *args], input=stdin, capture_output=True, text=True,
                          timeout=timeout)


def kjson(*args: str) -> dict | None:
    r = kubectl(*args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else None


def out(r: subprocess.CompletedProcess) -> str:
    return " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())


def actions(policy: str) -> list[str] | None:
    live = kjson("get", f"validatingpolicies.policies.kyverno.io/{policy}")
    return (live.get("spec") or {}).get("validationActions") if live else None


def set_actions(policy: str, value: list[str]) -> subprocess.CompletedProcess:
    return kubectl("patch", f"validatingpolicies.policies.kyverno.io/{policy}", "--type=json",
                   "-p", json.dumps([{"op": "replace", "path": "/spec/validationActions", "value": value}]))


def app_state(name: str) -> tuple[str, str]:
    app = kjson("-n", "argocd", "get", f"applications.argoproj.io/{name}") or {}
    st = app.get("status") or {}
    return (st.get("sync") or {}).get("status", "<none>"), (st.get("health") or {}).get("status", "<none>")


print("== prerequisites ==")
check("kubectl is on PATH", KUBECTL is not None)
check("jq is on PATH (the lab's policyreport command is a jq filter)", JQ is not None)
check("CONTEXT names the cluster to run against", bool(CONTEXT))
if failures:
    finish()
r = kubectl("--request-timeout=15s", "get", "--raw", "/readyz")
check(f"cluster for context {CONTEXT!r} is reachable", r.returncode == 0, r.stderr.strip())
if failures:
    finish()
check(f"namespace {NS} exists", kjson("get", "namespace", NS) is not None)

# The repo's side, read once: what the cluster must hold, and what the lab tells the room it will see.
want: dict[str, set[str]] = {"ValidatingPolicy": set(), "ImageValidatingPolicy": set()}
for f in POLICY_FILES:
    for d in yaml.safe_load_all(f.read_text()):
        if d and d.get("kind") in want:
            want[d["kind"]].add(d["metadata"]["name"])
reg_msg = " ".join(next(v["message"] for v in yaml.safe_load(REG_FILE.read_text())["spec"]["validations"]).split())
lab = LAB.read_text()
m = re.search(r"kubectl -n agent get policyreport -o json \| jq -r '([^']+)' \| sort -u", lab)
check("LAB-TEXT.md carries the policyreport jq command", m is not None)
lab_filter = m.group(1) if m else ""
m = re.search(r"The entry that matters here:\n>\n> ```\n(.*?)\n> ```", lab, re.S)
lab_line = " ".join(re.sub(r"^\s*>", "", m.group(1), flags=re.M).split()) if m else ""
check("the lab's printed entry is restrict-image-registries' own message",
      lab_line == f"restrict-image-registries: {reg_msg}", f"lab shows {lab_line!r}")
if failures:
    finish()

print("== 1. the ClusterPolicies are gone ==")
r = kubectl("get", "clusterpolicies.kyverno.io", "-o", "json")
if r.returncode == 0:
    names = [i["metadata"]["name"] for i in json.loads(r.stdout)["items"]]
    check("no kyverno.io ClusterPolicy is left (Argo CD pruned them)", not names, f"still present: {names}")
else:
    check("no kyverno.io ClusterPolicy is left (the CRD itself is not served)",
          "doesn't have a resource type" in r.stderr, r.stderr.strip())

print("== 2. the CEL policies are the repo's set, each READY ==")
for kind, plural in (("ValidatingPolicy", "validatingpolicies"), ("ImageValidatingPolicy", "imagevalidatingpolicies")):
    live = kjson("get", f"{plural}.policies.kyverno.io") or {"items": []}
    have = {i["metadata"]["name"]: i for i in live["items"]}
    check(f"the {kind} names on the cluster are the repo's {sorted(want[kind])}",
          set(have) == want[kind], f"cluster has {sorted(have)}")
    for name in sorted(want[kind] & set(have)):
        status = (have[name].get("status") or {}).get("conditionStatus") or {}
        check(f"{kind} {name} is READY", status.get("ready") is True, json.dumps(status.get("conditions")))
check("eleven policies in all", sum(len(v) for v in want.values()) == 11,
      f"the repo holds {sum(len(v) for v in want.values())}; update this check with the reason if that changed")

print("== 3. the Applications settle with no drift ==")
for name in APPS:
    sync, health = app_state(name)
    check(f"Application {name} is Synced and Healthy", (sync, health) == ("Synced", "Healthy"),
          f"sync={sync} health={health}")
if failures:
    finish()

RUN = uuid.uuid4().hex[:6]
RUN_LABEL = f"wib.test/run={RUN}"
LABELS = {"wib.test/run": RUN}
original = {p: actions(p) for p in TOGGLED}
applied_c1 = ""


def villain_deployment() -> dict:
    """The lab's villain, as C2's deploy_app makes it, under a name of this run's that still matches the jq."""
    d = json.loads(json.dumps(C2_MANIFEST))
    d["metadata"]["name"] = f"promo-mascot-{RUN}"
    d["metadata"]["labels"] = {**d["metadata"]["labels"], **LABELS}
    return d


def signed_deployment() -> dict:
    sel = {**LABELS, "wib.test/case": "signed"}
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": f"signed-{RUN}", "namespace": NS, "labels": sel},
            "spec": {"replicas": 1, "selector": {"matchLabels": sel},
                     "template": {"metadata": {"labels": sel}, "spec": {
                         "automountServiceAccountToken": False, "terminationGracePeriodSeconds": 0,
                         "containers": [{
                             "name": "c", "image": SIGNED, "command": ["sleep", "600"],
                             "resources": {"limits": {"cpu": "20m", "memory": "16Mi"},
                                           "requests": {"cpu": "5m", "memory": "8Mi"}},
                             "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
                                                 "runAsUser": 65534, "capabilities": {"drop": ["ALL"]}}}]}}}}


try:
    print(f"== 4. Audit admits the villain, and the lab's jq names the rule (run {RUN}) ==")
    r = set_actions("restrict-image-registries", ["Audit"])
    check("restrict-image-registries set to Audit (the lab's starting state)", r.returncode == 0, out(r))
    time.sleep(5)  # the webhook picks up a policy change within a few seconds
    r = kubectl("--as=system:serviceaccount:agent:agent-sa", "-n", "agent", "create", "-f", "-",
                stdin=json.dumps(villain_deployment()))
    check("the villain Deployment is admitted as agent-sa while the wall is Audit", r.returncode == 0, out(r))
    line = f"restrict-image-registries: {reg_msg}"
    printed: list[str] = []
    deadline = time.monotonic() + REPORT_TIMEOUT_S
    while r.returncode == 0:
        reports = kubectl("-n", "agent", "get", "policyreport", "-o", "json")
        jq = subprocess.run([JQ, "-r", lab_filter], input=reports.stdout, capture_output=True, text=True)
        printed = sorted(set(jq.stdout.splitlines()))
        if line in printed or time.monotonic() > deadline:
            break
        time.sleep(5)
    check(f"the lab's policyreport jq prints {line[:70]!r}...", line in printed, f"it printed {printed}")
    kubectl("-n", "agent", "delete", "deployment", f"promo-mascot-{RUN}", "--ignore-not-found", "--wait=false")

    print("== 5. toggle-kyverno-enforce.sh flips to Deny, and selfHeal leaves it there ==")
    t = subprocess.run(["bash", str(TOGGLE)], env={**os.environ, "CONTEXT": CONTEXT}, capture_output=True,
                       text=True, timeout=120)
    check("toggle-kyverno-enforce.sh exits 0", t.returncode == 0, out(t))
    for p in TOGGLED:
        check(f"{p} is [Deny] after the toggle", actions(p) == ["Deny"], f"got {actions(p)}")
    r = kubectl("-n", "argocd", "annotate", "applications.argoproj.io/kyverno-policies",
                "argocd.argoproj.io/refresh=hard", "--overwrite")
    check("kyverno-policies hard refresh requested", r.returncode == 0, out(r))
    seen: dict[str, set[str]] = {p: set() for p in TOGGLED}
    deadline = time.monotonic() + HOLD_S
    while time.monotonic() < deadline:
        for p in TOGGLED:
            seen[p].add(json.dumps(actions(p)))
        time.sleep(10)
    for p in TOGGLED:
        check(f"{p} stayed [Deny] for {HOLD_S}s after the refresh (ignoreDifferences holds)",
              seen[p] == {json.dumps(["Deny"])}, f"saw {sorted(seen[p])}")
    sync, health = app_state("kyverno-policies")
    check("kyverno-policies is still Synced with the flip live", sync == "Synced", f"sync={sync} health={health}")

    print("== 6. C2: the villain is refused, by name ==")
    r = kubectl(*C2_CHECK, stdin=json.dumps(C2_MANIFEST))
    want_refusal = "Policy restrict-image-registries failed: Images must come from allowed registries"
    check(f"deploy_app's villain Deployment is refused with {want_refusal!r}",
          r.returncode != 0 and want_refusal in out(r), f"rc={r.returncode}: {out(r)[:300]}")

    print("== 7. our signed image still admits behind the Challenge 1 egress seal ==")
    if kjson("-n", "agent", "get", "networkpolicy", "agent-egress-allowlist") is None:
        # The attendee profile ships without it; apply what the student applies in Challenge 1.
        cm = next(d for d in yaml.safe_load_all(RESOURCES.read_text())
                  if d and d.get("kind") == "ConfigMap" and "c1-network-policy.yaml" in (d.get("data") or {}))
        applied_c1 = cm["data"]["c1-network-policy.yaml"]
        r = kubectl("apply", "-f", "-", stdin=applied_c1)
        check("the Challenge 1 NetworkPolicies are applied (this run put them on)", r.returncode == 0, out(r))
    else:
        print("  (the agent namespace is already sealed: full profile, or Challenge 1 already done)")
    r = kubectl("apply", "-f", "-", stdin=json.dumps(signed_deployment()))
    check(f"a Deployment of the signed {SIGNED.split('@')[0]} is admitted", r.returncode == 0, out(r))
    r = kubectl("-n", NS, "wait", "pod", "-l", f"{RUN_LABEL},wib.test/case=signed", "--for=condition=Ready",
                "--timeout=120s", timeout=150)
    check("its Pod passes admission (verify-image-signatures) and runs", r.returncode == 0, out(r))
finally:
    print("\n== restoring the cluster ==")
    for p, value in original.items():
        if value is not None:
            r = set_actions(p, value)
            print(f"  {p} validationActions -> {value}: {'done' if r.returncode == 0 else 'FAILED: ' + out(r)}")
    if applied_c1:
        r = kubectl("delete", "-f", "-", "--ignore-not-found", stdin=applied_c1)
        print(f"  Challenge 1 NetworkPolicies removed: {'done' if r.returncode == 0 else 'FAILED: ' + out(r)}")
    r = kubectl("delete", "deployments", "-n", NS, "-l", RUN_LABEL, "--ignore-not-found", "--wait=false")
    if NS != "agent":
        kubectl("delete", "deployments", "-n", "agent", "-l", RUN_LABEL, "--ignore-not-found", "--wait=false")
    print(f"  cleanup ({RUN_LABEL}): {'done' if r.returncode == 0 else 'FAILED: ' + out(r)}")

finish()
