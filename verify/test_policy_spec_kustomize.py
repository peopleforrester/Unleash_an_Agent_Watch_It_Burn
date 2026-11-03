# ABOUTME: Renders policies/kyverno with kustomize, as the kyverno-policies Application does since #638, and holds that
# ABOUTME: every ValidatingPolicy's expressions in that render equal its file's, by policy_spec's comparison (#608).
# SUITE: e2e (needs kubectl: every check reads the `kubectl kustomize` render of policies/kyverno)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#608). Escalation 755 stopped verify/test_llm_bypass_live.py at "live restrict-agent-spawned-workloads
validation expressions are the repo's" on watch-it-burn-private, synced to the checkout's own revision. Since #638
(ea699ed) policies/kyverno has a Kustomization, so Argo CD builds it with kustomize, and kustomize writes a `>-`
expression whose second line is more indented with one more empty line than the file has. The live test reads the
file with PyYAML, so the two strings differed by that line alone. The last live run before #638 (hecaton run 12431's
draft, staging 0d73c8d) passed that prerequisite.

This renders the directory with the pinned kubectl's kustomize and compares every ValidatingPolicy in the render
with its own file, through the same verify/policy_spec.py the live test uses. It fails if a render ever differs
from the repo by more than whitespace, or if the comparison stops absorbing the line kustomize adds. No cluster.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from policy_spec import expressions, first_difference, normalized  # noqa: E402

POLICIES = REPO / "policies/kyverno"
# The two policies verify/test_llm_bypass_live.py compares with the cluster.
LIVE_COMPARED = ("deny-llm-endpoint-bypass", "restrict-agent-spawned-workloads")

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
    print("The kustomize render of policies/kyverno matches the repo files modulo whitespace in expressions.")


print("== the kustomize render ==")
check("kubectl is on PATH", shutil.which("kubectl") is not None)
if failures:
    finish()
r = subprocess.run(["kubectl", "kustomize", str(POLICIES)], capture_output=True, text=True, timeout=120)
check("kubectl kustomize policies/kyverno renders", r.returncode == 0, r.stderr.strip())
if failures:
    finish()

rendered = {d["metadata"]["name"]: d for d in yaml.safe_load_all(r.stdout)
            if d and d.get("kind") == "ValidatingPolicy"}
files = {}
for path in sorted(POLICIES.glob("*.yaml")):
    for d in yaml.safe_load_all(path.read_text()):
        if d and d.get("kind") == "ValidatingPolicy":
            files[d["metadata"]["name"]] = d
check("the render holds every ValidatingPolicy in the directory's files, and no other",
      sorted(rendered) == sorted(files), f"render {sorted(rendered)}, files {sorted(files)}")
check("both policies the live test compares are in the render", all(n in rendered for n in LIVE_COMPARED),
      str(sorted(rendered)))

print("== each rendered policy is its file's ==")
for name in sorted(set(rendered) & set(files)):
    have, want = rendered[name]["spec"], files[name]["spec"]
    for field in ("validationActions", "matchConditions", "variables"):
        check(f"{name} spec.{field}", normalized(have.get(field)) == normalized(want.get(field)))
    hx, wx = expressions(have.get("validations")), expressions(want.get("validations"))
    check(f"{name} validation expressions", hx == wx, first_difference(hx, wx))
    check(f"{name} validation messages", [v.get("message") for v in have.get("validations") or []]
          == [v.get("message") for v in want.get("validations") or []])

print("== what escalation 755 saw ==")
spawn_raw = [v["expression"] for v in rendered["restrict-agent-spawned-workloads"]["spec"]["validations"]]
file_raw = [v["expression"] for v in files["restrict-agent-spawned-workloads"]["spec"]["validations"]]
added = [i for i, (h, w) in enumerate(zip(spawn_raw, file_raw)) if h != w]
# Not a check: a kustomize that stops adding the line is no failure. It says whether the comparison is doing work.
print(f"  note: compared exactly, restrict-agent-spawned-workloads expressions {added or 'none'} differ between "
      f"the render and the file")
finish()
