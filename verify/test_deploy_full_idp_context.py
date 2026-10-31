# ABOUTME: infra/deploy-full-idp.sh and infra/datadog-cluster-identity.sh require CONTEXT and pass it on every kubectl
# ABOUTME: and helm call, never reading the kubeconfig's current-context; run offline against recording fakes (#732).
"""CLAUDE.md's kube-context rule 5: a script that cannot determine its target context fails loudly. Before #732
deploy-full-idp.sh never read CONTEXT, its kubectl and helm calls carried no context, and both scripts took the cluster
name from `kubectl config current-context`, so a manual run built whatever cluster ~/.kube/config pointed at.

This runs both scripts with kubectl, helm and aws on PATH as fakes that record every call and refuse one without the
context, then checks the callers (fleet.sh's bootstrap_one and repair_datadog, setup-instructor-cluster.sh) pass it.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = REPO / "infra/deploy-full-idp.sh"
IDENT = REPO / "infra/datadog-cluster-identity.sh"
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
SETUP = (REPO / "infra/setup-instructor-cluster.sh").read_text(encoding="utf-8")
CTX = "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-001"
failures: list[str] = []

# One recorder for all three tools: it logs its own name and argv, and refuses a cluster call without the context.
FAKE = r"""#!/usr/bin/env python3
import json, os, sys
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps([tool, *args]) + "\n")
if tool == "aws":
    if "describe-cluster" in args:
        print("vpc-0abc"); sys.exit(0)
    sys.exit(1)
ctx = os.environ.get("FAKE_CONTEXT", "")
flag = "--context" if tool == "kubectl" else "--kube-context"
if args[:2] != [flag, ctx] or not ctx:
    sys.stderr.write(f"fake {tool}: refused, no {flag} first\n"); sys.exit(97)
if args[-2:] == ["-f", "-"] or "-f" in args and args[args.index("-f") + 1] == "-":
    sys.stdin.read()
if tool == "kubectl" and "--dry-run=client" in args:
    print("kind: Namespace"); sys.exit(0)
sys.exit(0)
"""


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def code(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def body(src: str, fn: str) -> str:
    m = re.search(rf"^{fn}\(\) \{{\n(.*?)^\}}", src, re.M | re.S)
    return m.group(1) if m else ""


print("== the source ==")
for path in (DEPLOY, IDENT):
    src = code(path.read_text(encoding="utf-8"))
    rel = path.relative_to(REPO)
    check(f"{rel} never reads the current-context", "current-context" not in src and "use-context" not in src)
    check(f"{rel} requires CONTEXT", re.search(r'\$\{CONTEXT:\?', src) is not None)

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    fakebin = tmp / "bin"
    fakebin.mkdir()
    for tool in ("kubectl", "helm", "aws"):
        (fakebin / tool).write_text(FAKE)
        (fakebin / tool).chmod(0o755)
    runs = 0

    def run(cmd: list[str], **extra: str) -> tuple[int, str, list[list[str]]]:
        global runs
        runs += 1
        calls = tmp / f"calls-{runs}"
        calls.write_text("")
        env = {k: v for k, v in os.environ.items() if k not in ("CONTEXT", "KUBECONFIG", "CLUSTER_NAME")}
        env.update({"PATH": f"{fakebin}:{os.environ['PATH']}", "HOME": str(tmp), "FAKE_CALLS": str(calls),
                    "FAKE_CONTEXT": CTX, "AWS_PROFILE": "fake", "WITB_DD_API_KEY": "own-api",
                    "WITB_DD_APP_KEY": "own-app", **extra})
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr, [json.loads(l) for l in calls.read_text().splitlines()]

    print("== without CONTEXT ==")
    for path, args in ((DEPLOY, ["attendee"]), (IDENT, [])):
        rc, out, calls = run(["bash", str(path), *args])
        cluster = [c for c in calls if c[0] in ("kubectl", "helm")]
        check(f"{path.name}: exits non-zero and says CONTEXT", rc != 0 and "CONTEXT" in out, out[-300:])
        check(f"{path.name}: makes no kubectl or helm call", not cluster, json.dumps(cluster[:3]))

    print("== with CONTEXT ==")
    for profile in ("attendee", "full"):
        rc, out, calls = run(["bash", str(DEPLOY), profile], CONTEXT=CTX)
        kube = [c for c in calls if c[0] == "kubectl"]
        helm = [c for c in calls if c[0] == "helm"]
        aws = [c for c in calls if c[0] == "aws" and "describe-cluster" in c]
        check(f"{profile}: deploy-full-idp.sh completes", rc == 0, out[-400:])
        check(f"{profile}: it made kubectl calls, the identity script's included",
              len(kube) > 10 and any("cluster-identity" in c for c in kube), str(len(kube)))
        check(f"{profile}: every kubectl call starts with --context <CONTEXT>",
              all(c[1:3] == ["--context", CTX] for c in kube), json.dumps([c for c in kube if c[1:3] != ["--context", CTX]][:2]))
        check(f"{profile}: every helm call starts with --kube-context <CONTEXT>",
              bool(helm) and all(c[1:3] == ["--kube-context", CTX] for c in helm))
        check(f"{profile}: no call reads the current-context", not any("current-context" in c for c in calls))
        check(f"{profile}: the cluster name comes from CONTEXT",
              bool(aws) and aws[0][aws[0].index("--name") + 1] == "watch-it-burn-attendee-001", json.dumps(aws))
    rc, out, calls = run(["bash", str(IDENT)], CONTEXT=CTX)
    kube = [c for c in calls if c[0] == "kubectl"]
    check("datadog-cluster-identity.sh alone: completes, every kubectl call carries --context <CONTEXT>",
          rc == 0 and bool(kube) and all(c[1:3] == ["--context", CTX] for c in kube), out[-300:])

print("== the callers pass CONTEXT ==")
boot, repair = body(FLEET, "bootstrap_one"), body(FLEET, "repair_datadog")
check("fleet.sh bootstrap_one reads the context of its isolated kubeconfig and passes it to deploy-full-idp.sh",
      re.search(r'KUBECONFIG="\$\{kcfg\}" kubectl config current-context', boot) is not None
      and re.search(r'CONTEXT="\$\{ctx\}"[^\n]*\\\n(?:[^\n]*\\\n)*\s*run_idp_script', boot) is not None)
check("fleet.sh repair_datadog passes CONTEXT to datadog-cluster-identity.sh",
      re.search(r'CONTEXT="\$\{ctx\}"[^\n]*\\\n(?:[^\n]*\\\n)*[^\n]*run_identity_script', repair) is not None)
check("setup-instructor-cluster.sh passes CONTEXT to deploy-full-idp.sh",
      re.search(r'CONTEXT="\$\{CONTEXT\}"[^\n]*deploy-full-idp\.sh', SETUP) is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    raise SystemExit(1)
print("deploy-full-idp.sh and datadog-cluster-identity.sh run only against the CONTEXT they are given.")
