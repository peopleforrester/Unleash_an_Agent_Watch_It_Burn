# ABOUTME: Static gate for the drift floor (#205): every Argo CD app self-heals and prunes, every exemption from that
# ABOUTME: is in docs/floor.md's register, the documented windows still hold, and the AWS record covers what it claims.
"""Offline: python3, PyYAML and the repo. What it guards is the agreement between docs/floor.md and the manifests,
because the doc is only useful while it is true:

- an Application that stops self-healing silently turns "deleted objects come back" into a lie;
- an `ignoreDifferences` or `ignore_changes` nobody registered is drift that no check will ever report;
- the 30 s / 180 s windows rest on Argo CD defaults and on the controller source read for one chart version, so
  overriding a default, or moving the chart, has to come with a re-read and a doc change;
- the drill target has to be managed on every profile, and be a kind no admission policy stops you deleting;
- the Config recorder has to record what the drift report demands of it, and the AWS register has to be in the doc.

The apps are read from the gitops/bootstrap chart (#609) through verify/bootstrap_chart.py. Their template guards sit
in YAML comments, so an app file read as YAML holds every ignoreDifferences entry any profile can render.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, all_profiles, deploy_root, deploys  # noqa: E402

FLOOR = (REPO / "docs/floor.md").read_text(encoding="utf-8")
LIVE = (REPO / "verify/test_drift_selfheal_live.py").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def section(title: str) -> str:
    start = FLOOR.find(title)
    if start < 0:
        return ""
    level = "\n" + title.split(" ", 1)[0] + " "
    nxt = FLOOR.find(level, start + len(title))
    return FLOOR[start: nxt if nxt > 0 else len(FLOOR)]


def auto(app: dict) -> dict:
    return ((app.get("spec") or {}).get("syncPolicy") or {}).get("automated") or {}


def jq_fields(expr: str) -> list[str]:
    """The field names a jqPathExpression ignores, as the register's row has to name them: the env vars an
    env selector picks by name, else the last field the path ends on."""
    m = re.search(r'test\("\^\(([^)]*)\)\$"\)', expr)
    if m:
        return m.group(1).split("|")
    m = re.search(r'select\(\.name == "([^"]+)"\)\s*$', expr)
    if m:
        return [m.group(1)]
    m = re.search(r'\["([^"]+)"\]\s*$', expr) or re.search(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*$", expr)
    return [m.group(1)] if m else [expr]


APP_FILES = {p.name: [d for d in docs(p) if d.get("kind") == "Application"] for p in sorted(APPS.glob("*.yaml"))}
ROOTS = {prof: deploy_root(prof) for prof in all_profiles()}

print("== every Application and the root syncs itself, prunes and self-heals ==")
check("the chart has app files to read", len(APP_FILES) > 0 and all(APP_FILES.values()))
not_healing = [f"{f}/{a['metadata']['name']}" for f, apps in APP_FILES.items() for a in apps
               if auto(a).get("selfHeal") is not True or auto(a).get("prune") is not True]
check(f"all {sum(map(len, APP_FILES.values()))} Applications in gitops/bootstrap/apps have automated prune + selfHeal"
      + (f" (not: {not_healing})" if not_healing else ""), not not_healing)
for prof, root in ROOTS.items():
    check(f"deploy-full-idp.sh's lab-bootstrap root for {prof}: automated prune + selfHeal",
          root.get("metadata", {}).get("name") == "lab-bootstrap"
          and auto(root).get("prune") is True and auto(root).get("selfHeal") is True)

print("== every ignoreDifferences is in the register (docs/floor.md) ==")
table = section("### What Argo CD deliberately does not put back")
rows = [ln for ln in table.splitlines() if ln.startswith("|")]
check("the register table is there", len(rows) > 2)
for f, apps in APP_FILES.items():
    for a in apps:
        for ig in a["spec"].get("ignoreDifferences", []):
            name = a["metadata"]["name"]
            want = [f"`{name}`", ig["kind"]] + ([f"`{ig['name']}`"] if ig.get("name") else [])
            want += [f"`{ptr}`" for ptr in ig.get("jsonPointers", [])]
            label = f"{name}: {ig['kind']} {ig.get('name', '(every one)')}"
            mine = [r for r in rows if all(w in r for w in want)]
            check(f"{label} has a row naming {want}", bool(mine))
            for expr in ig.get("jqPathExpressions", []):
                for field in jq_fields(expr):
                    check(f"{label}: its row names the ignored field `{field}`", any(f"`{field}`" in r for r in mine))
root_ignores = {(ig["kind"], ptr) for root in ROOTS.values() for ig in root["spec"].get("ignoreDifferences", [])
                for ptr in ig.get("jsonPointers", [])}
check("the lab-bootstrap root ignores only Application finalizers", root_ignores == {("Application", "/metadata/finalizers")})
check("and that is in the register", any("`lab-bootstrap`" in r and "Application" in r and "`/metadata/finalizers`" in r
                                         for r in rows))

print("== every Terraform ignore_changes is in the register ==")
ic_section = section("### `ignore_changes`")
check("the register has an ignore_changes section", bool(ic_section))
ignored = []
for tf in sorted(list((REPO / "infra/terraform").rglob("*.tf")) + list((REPO / "infra/org").rglob("*.tf"))):
    if ".terraform" in tf.parts:
        continue
    resource = None
    for ln in tf.read_text(encoding="utf-8").splitlines():
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
values = (REPO / "infra/argocd-values.yaml").read_text(encoding="utf-8")
deploy = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
for knob in ("timeout.reconciliation", "self-heal", "SELF_HEAL", "selfHealBackoff", "app-resync", "RECONCILIATION_",
             "webhook.github", "webhook.gitlab", "webhook.bitbucket", "githubSecret"):
    check(f"argocd-values.yaml and deploy-full-idp.sh leave {knob} at the default",
          knob not in values and knob not in deploy)
chart = re.search(r"helm upgrade --install argocd argo/argo-cd --version (\S+)", deploy)
check("deploy-full-idp.sh pins the Argo CD chart", chart is not None)
check(f"floor.md names the chart whose controller source the backoff was read from ({chart and chart.group(1)})",
      chart is not None and f"chart {chart.group(1)}" in FLOOR)
app_version = re.search(r'tags\.datadoghq\.com/version: "(v[0-9.]+)"', values)
check(f"and the Argo CD version that chart installs ({app_version and app_version.group(1)})",
      app_version is not None and f"Argo CD {app_version.group(1)}" in FLOOR)
window = re.search(r"^WINDOW_S = (\d+)\b", LIVE, re.M)
quiet = re.search(r"^QUIET_S = (\d+)\b", LIVE, re.M)
check("the live drill declares its window", window is not None and quiet is not None)
if window and quiet:
    check(f"floor.md documents the drill's window ({window.group(1)} s)", f"Within {window.group(1)} seconds" in FLOOR)
    check(f"and the quiet period it needs ({int(quiet.group(1)) // 60} minutes)",
          f"has not self-healed in the previous {int(quiet.group(1)) // 60} minutes" in FLOOR)
    check("the quiet period covers the 300 s backoff cap", int(quiet.group(1)) >= 300)
check("floor.md documents the git-side window (120 s + 60 s jitter)", "Up to 180 seconds" in FLOOR and "120 s" in FLOOR)
check("floor.md says no Git webhook is configured", "No Git webhook is configured" in FLOOR)

print("== the drill target is managed on every profile and deletable ==")
target = re.search(r'^TARGET = \("([^"]+)", "([^"]+)", "([^"]+)"\)', LIVE, re.M)
check("the live drill names its target (namespace, name, owning app)", target is not None)
if target:
    ns, name, app = target.groups()
    check(f"floor.md names the target {ns}/{name}", f"`{ns}/{name}`" in FLOOR)
    owner = next((a for apps in APP_FILES.values() for a in apps if a["metadata"]["name"] == app), None)
    check(f"{app} is an Application in gitops/bootstrap/apps", owner is not None)
    if owner:
        path = REPO / owner["spec"]["source"]["path"]
        kust = yaml.safe_load((path / "kustomization.yaml").read_text(encoding="utf-8"))
        found = [d for res in kust.get("resources", []) if (path / res).is_file() for d in docs(path / res)
                 if d.get("kind") == "NetworkPolicy" and d["metadata"].get("name") == name]
        check(f"{name} is a NetworkPolicy in {owner['spec']['source']['path']}'s kustomization, in namespace {ns}",
              len(found) == 1 and (found[0]["metadata"].get("namespace") or kust.get("namespace")) == ns)
        for prof in all_profiles():
            check(f"profile {prof} deploys {app}", deploys(prof, app))
    blocked = []
    for pol in sorted((REPO / "policies").rglob("*.yaml")):
        for d in docs(pol):
            spec = d.get("spec") or {}
            for rr in (spec.get("matchConstraints") or {}).get("resourceRules", []) or []:
                if {"networkpolicies", "*"} & set(rr.get("resources", [])) and {"DELETE", "*"} & set(rr.get("operations", [])):
                    blocked.append(f"{pol.relative_to(REPO)}:{d['metadata']['name']}")
            for rule in spec.get("rules", []) or []:
                if "NetworkPolicy" in str(rule.get("match")):
                    blocked.append(f"{pol.relative_to(REPO)}:{d['metadata']['name']}/{rule.get('name')}")
    check("no Kyverno policy refuses deleting a NetworkPolicy (so the drill measures Argo CD, not admission)"
          + (f" (found {blocked})" if blocked else ""), not blocked)

print("== the AWS record covers what the drift report demands of it ==")
audit = (REPO / "infra/terraform/aws/audit/main.tf").read_text(encoding="utf-8")
types_block = re.search(r'variable "recorded_resource_types" \{.*?default = \[(.*?)\]', audit, re.S)
recorded = set(re.findall(r'"(AWS::[^"]+)"', types_block.group(1))) if types_block else set()
report_src = (REPO / "infra/terraform/drift/drift-report.py").read_text(encoding="utf-8")
required = ast.literal_eval(re.search(r"^REQUIRED_CONFIG_TYPES = (\(.*\))$", report_src, re.M).group(1))
check(f"the recorder records every type the report requires {required}", set(required) <= recorded)
eks = {"AWS::EKS::Cluster", "AWS::EKS::Nodegroup", "AWS::EKS::Addon", "AWS::EKS::FargateProfile",
       "AWS::EKS::IdentityProviderConfig", "AWS::EKS::PodIdentityAssociation"}
check("the recorder records all six EKS types", eks <= recorded)
check("the recorder records the attendee users and their grants", {"AWS::IAM::User", "AWS::IAM::UserPolicy"} <= recorded)
check("recording is by inclusion and continuous",
      'use_only = "INCLUSION_BY_RESOURCE_TYPES"' in audit and 'recording_frequency = "CONTINUOUS"' in audit)
check("the trail is multi-region with log file validation",
      re.search(r"is_multi_region_trail\s*=\s*true", audit) is not None
      and re.search(r"enable_log_file_validation\s*=\s*true", audit) is not None)
for var in ("profile", "event"):
    body = re.search(rf'variable "{var}" \{{(.*?)\n\}}', audit, re.S)
    check(f"the audit root's {var} has no default", body is not None and not re.search(r"^\s*default\s*=", body.group(1), re.M))
check("the recorder is turned on, not only defined", "aws_config_configuration_recorder_status" in audit
      and re.search(r"is_enabled\s*=\s*true", audit) is not None)
check("floor.md gives the audit apply with its profile and event",
      "terraform -chdir=infra/terraform/aws/audit apply -state=states/<profile>.tfstate -var profile=<profile> "
      '-var event="${WIB_EVENT}"' in FLOOR)

print("== the AWS register is explained, and in floor.md ==")
reg = yaml.safe_load((REPO / "infra/terraform/drift/known-unmanaged.yaml").read_text(encoding="utf-8"))["entries"]
register_doc = section("## The unmanaged register")
for e in reg:
    label = e.get("name") or e.get("tag")
    check(f"register entry {e['kind']} {label}: has made_by and why", bool(e.get("made_by")) and bool(e.get("why")))
    key = f"`{e['name']}`" if e.get("name") else "".join(f"`{k}={v}`" for k, v in e["tag"].items())
    check(f"register entry {e['kind']} {label}: is in floor.md's register", key in register_doc)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All drift-floor checks passed.")
