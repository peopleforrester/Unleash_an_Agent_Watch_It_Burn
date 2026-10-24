# ABOUTME: Static gate for the drift floor (#205): every Argo CD app self-heals and prunes, every exemption from that
# ABOUTME: is in docs/floor.md's register, the documented windows still hold, and the AWS record covers what it claims.
"""Offline: python3, PyYAML and the repo. What it guards is the agreement between docs/floor.md and the manifests,
because the doc is only useful while it is true:

- an Application that stops self-healing silently turns "deleted objects come back" into a lie;
- an `ignoreDifferences` or `ignore_changes` nobody registered is drift that no check will ever report;
- the 30 s / 180 s windows rest on Argo CD defaults and on the controller source read for one chart version, so
  overriding a default, or moving the chart, has to come with a re-read and a doc change;
- the drill target has to exist on every profile, and be a kind no admission policy stops you deleting;
- the Config recorder has to record what the drift report demands of it.
"""
from __future__ import annotations

import ast
import fnmatch
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FLOOR = (REPO / "docs/floor.md").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def section(title: str) -> str:
    start = FLOOR.find(title)
    if start < 0:
        return ""
    level = "\n" + title.split(" ", 1)[0] + " "
    nxt = FLOOR.find(level, start + len(title))
    return FLOOR[start: nxt if nxt > 0 else len(FLOOR)]


def braces(glob: str) -> list[str]:
    """Expand one {a,b} group, which is all the roots use."""
    m = re.search(r"\{([^}]*)\}", glob)
    return [glob[:m.start()] + alt + glob[m.end():] for alt in m.group(1).split(",")] if m else [glob]


APPS = {}  # file name -> [Application docs]
for p in sorted((REPO / "gitops/apps").glob("*.yaml")):
    APPS[p.name] = [d for d in docs(p) if d.get("kind") == "Application"]
ROOTS = {p.parent.name: docs(p)[0] for p in sorted((REPO / "gitops/bootstrap").glob("*/*.yaml"))}


def root_selects(root: dict, filename: str) -> bool:
    d = next(s for s in root["spec"]["sources"] if s.get("path") == "gitops/apps").get("directory") or {}
    if d.get("include") and not any(fnmatch.fnmatch(filename, g) for g in braces(d["include"])):
        return False
    return not (d.get("exclude") and any(fnmatch.fnmatch(filename, g) for g in braces(d["exclude"])))


print("== every Application and every root syncs itself, prunes and self-heals ==")
not_healing = [f"{f}/{a['metadata']['name']}" for f, apps in APPS.items() for a in apps
               if (a["spec"].get("syncPolicy", {}).get("automated") or {}).get("selfHeal") is not True
               or (a["spec"].get("syncPolicy", {}).get("automated") or {}).get("prune") is not True]
check(f"all {sum(map(len, APPS.values()))} Applications in gitops/apps have automated prune + selfHeal"
      + (f" (not: {not_healing})" if not_healing else ""), not not_healing)
for name, root in ROOTS.items():
    auto = root["spec"].get("syncPolicy", {}).get("automated") or {}
    check(f"root {name}: automated prune + selfHeal", auto.get("prune") is True and auto.get("selfHeal") is True)

print("== every ignoreDifferences is in the register (docs/floor.md) ==")
table = section("### What Argo CD deliberately does not put back")
rows = [ln for ln in table.splitlines() if ln.startswith("|")]
check("the register table is there", len(rows) > 2)
for f, apps in APPS.items():
    for a in apps:
        for ig in a["spec"].get("ignoreDifferences", []):
            want = [f"`{a['metadata']['name']}`", ig["kind"]] + ([f"`{ig['name']}`"] if ig.get("name") else [])
            want += ig.get("jsonPointers", [])
            label = f"{a['metadata']['name']}: {ig['kind']} {ig.get('name', '(all)')}"
            check(f"{label} has a row", any(all(w in r for w in want) for r in rows))
            for expr in ig.get("jqPathExpressions", []):
                # The guard-proxy entry selects env vars by a regex of names; every name is a field that drifts.
                m = re.search(r'test\("\^\(([^)]*)\)\$"\)', expr)
                for env in (m.group(1).split("|") if m else []):
                    check(f"{label}: env {env} is named in its row",
                          any(all(w in r for w in want) and f"`{env}`" in r for r in rows))
for name, root in ROOTS.items():
    for ig in root["spec"].get("ignoreDifferences", []):
        want = ["every root", ig["kind"]] + ig.get("jsonPointers", [])
        check(f"root {name}: {ig['kind']} {ig.get('jsonPointers')} has a row", any(all(w in r for w in want) for r in rows))

print("== every Terraform ignore_changes is in the register ==")
ic_section = section("### `ignore_changes`")
check("the register has an ignore_changes section", bool(ic_section))
ignored = []
for tf in sorted((REPO / "infra/terraform").rglob("*.tf")):
    if ".terraform" in tf.parts:
        continue
    resource = None
    for ln in tf.read_text().splitlines():
        m = re.match(r'\s*resource\s+"([^"]+)"\s+"([^"]+)"', ln)
        if m:
            resource = f"{m.group(1)}.{m.group(2)}"
        if re.search(r"\bignore_changes\b", ln) and not ln.lstrip().startswith("#"):
            ignored.append((tf.relative_to(REPO).as_posix(), resource or "?"))
for path, res in ignored:
    check(f"{path} {res}: ignore_changes is registered", f"`{res}`" in ic_section)
if not ignored:
    check("no root has ignore_changes, and the register says so", "no root has an `ignore_changes` block" in ic_section)

print("== the documented windows rest on settings that are still the defaults ==")
values = (REPO / "infra/argocd-values.yaml").read_text()
deploy = (REPO / "infra/deploy-full-idp.sh").read_text()
for knob in ("timeout.reconciliation", "self-heal", "SELF_HEAL", "app-resync", "RECONCILIATION_TIMEOUT",
             "RECONCILIATION_JITTER", "webhook"):
    check(f"argocd-values.yaml and deploy-full-idp.sh leave {knob} at the default",
          knob not in values and knob not in deploy)
chart = re.search(r"helm upgrade --install argocd argo/argo-cd --version (\S+)", deploy)
check("deploy-full-idp.sh pins the Argo CD chart", chart is not None)
check(f"floor.md names the chart whose controller source the backoff was read from ({chart and chart.group(1)})",
      chart is not None and f"chart {chart.group(1)}" in FLOOR)
live = (REPO / "verify/test_drift_selfheal_live.py").read_text()
window = re.search(r"^WINDOW_S = (\d+)\b", live, re.M)
quiet = re.search(r"^QUIET_S = (\d+)\b", live, re.M)
check("the live drill declares its window", window is not None and quiet is not None)
if window and quiet:
    check(f"floor.md documents the drill's window ({window.group(1)} s)", f"Within {window.group(1)} seconds" in FLOOR)
    check(f"and the quiet period it needs ({int(quiet.group(1)) // 60} minutes)",
          f"has not self-healed in the previous {int(quiet.group(1)) // 60} minutes" in FLOOR)
    check("the quiet period covers the 300 s backoff cap", int(quiet.group(1)) >= 300)
check("floor.md documents the git-side window (120 s + 60 s jitter)", "Up to 180 seconds" in FLOOR and "120 s" in FLOOR)

print("== the drill target is managed on every profile and deletable ==")
target = re.search(r'^TARGET = \("([^"]+)", "([^"]+)", "([^"]+)"\)', live, re.M)
check("the live drill names its target (namespace, name, owning app)", target is not None)
if target:
    ns, name, app = target.groups()
    check(f"floor.md names the target {ns}/{name}", f"`{ns}/{name}`" in FLOOR)
    owner = next(((f, a) for f, apps in APPS.items() for a in apps if a["metadata"]["name"] == app), None)
    check(f"{app} is an Application in gitops/apps", owner is not None)
    if owner:
        f, a = owner
        path = REPO / a["spec"]["source"]["path"]
        found = [d for m in sorted(path.glob("*.yaml")) for d in docs(m)
                 if d.get("kind") == "NetworkPolicy" and d["metadata"].get("name") == name
                 and d["metadata"].get("namespace") == ns]
        check(f"{ns}/{name} is a top-level NetworkPolicy in {a['spec']['source']['path']}", len(found) == 1)
        for rname, root in ROOTS.items():
            check(f"root {rname} deploys {f}", root_selects(root, f))
    blocked = []
    for pol in list((REPO / "policies/kyverno").glob("*.yaml")) + list((REPO / "policies/floor").glob("*.yaml")):
        for d in docs(pol):
            for rule in (d.get("spec") or {}).get("rules", []):
                for m in (rule.get("match") or {}).get("any", []) + (rule.get("match") or {}).get("all", []):
                    res = m.get("resources") or {}
                    if "NetworkPolicy" in res.get("kinds", []) and "DELETE" in res.get("operations", ["DELETE"]):
                        blocked.append(f"{pol.name}/{rule['name']}")
    check(f"no Kyverno rule refuses deleting a NetworkPolicy (so the drill measures Argo CD, not admission)"
          + (f" (found {blocked})" if blocked else ""), not blocked)

print("== the AWS record covers what the drift report demands of it ==")
audit = (REPO / "infra/terraform/aws/audit/main.tf").read_text()
types_block = re.search(r'variable "recorded_resource_types" \{.*?default = \[(.*?)\]', audit, re.S)
recorded = set(re.findall(r'"(AWS::[^"]+)"', types_block.group(1))) if types_block else set()
report_src = (REPO / "infra/terraform/drift/drift-report.py").read_text()
required = ast.literal_eval(re.search(r"^REQUIRED_CONFIG_TYPES = (\(.*\))$", report_src, re.M).group(1))
check(f"the recorder records every type the report requires {required}", set(required) <= recorded)
eks = {"AWS::EKS::Cluster", "AWS::EKS::Nodegroup", "AWS::EKS::Addon", "AWS::EKS::FargateProfile",
       "AWS::EKS::IdentityProviderConfig", "AWS::EKS::PodIdentityAssociation"}
check("the recorder records all six EKS types", eks <= recorded)
check("the recorder records IAM users (the attendee keys)", "AWS::IAM::User" in recorded)
check("recording is by inclusion and continuous",
      'use_only = "INCLUSION_BY_RESOURCE_TYPES"' in audit and 'recording_frequency = "CONTINUOUS"' in audit)
check("the trail is multi-region with log file validation",
      re.search(r"is_multi_region_trail\s*=\s*true", audit) and re.search(r"enable_log_file_validation\s*=\s*true", audit))
check("the audit root's profile has no default",
      re.search(r'variable "profile" \{\s*type = string\s*#', audit) is not None and
      "default" not in re.search(r'variable "profile" \{(.*?)\n\}', audit, re.S).group(1))
check("the recorder is turned on, not only defined", "aws_config_configuration_recorder_status" in audit
      and re.search(r"is_enabled\s*=\s*true", audit))

print("== the AWS register is explained, and in floor.md ==")
reg = yaml.safe_load((REPO / "infra/terraform/drift/known-unmanaged.yaml").read_text())["entries"]
for e in reg:
    label = e.get("name") or e.get("tag")
    check(f"register entry {label}: has made_by and why", bool(e.get("made_by")) and bool(e.get("why")))
    key = f"`{e['name']}`" if e.get("name") else "".join(f"`{k}={v}`" for k, v in e["tag"].items())
    check(f"register entry {label}: is in floor.md's register", key in section("## The unmanaged register"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All drift-floor checks passed.")
