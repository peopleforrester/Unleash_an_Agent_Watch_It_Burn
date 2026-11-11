# ABOUTME: Offline gate for #1358: ai-layer's sync options and its ignore on the workshop-agent Role's rules, as live-checked
# ABOUTME: on both KubeCon clusters, so a staging sync leaves a guard switch's live Role as the presenters left it.
"""#1358. On 2026-11-11 both KubeCon clusters' workshop-agent Role was found scoped minutes after guardrails-off had
opened it, and the first suspect was ai-layer's sync of 1b0d0974 at 16:16:45Z (private) and 16:19:07Z (community).
The EKS audit log cleared it: the terminal applied c8-broad-role.yaml at 16:14:13Z and c5-scoped-role.yaml at
16:14:16Z on both (guardrails-off, then guard-agency-off), and each Argo CD sync then applied the live c5 rules back
unchanged. The scoped Role came from guard-agency-off, which #1358 fixed in the terminal (_agency_off, held by
verify/test_guard_switch_both.py).

What a sync does to the Role, on Argo CD v3.5.7 with these options, measured on 2026-11-11 (decisions.md, #1358):
  * ServerSideApply=true first moves kubectl's client-side apply ownership of the Role to argocd-controller (its
    client-side apply migration, a managedFields patch that also drops the last-applied annotation);
  * RespectIgnoreDifferences=true with the `.rules` ignore copies the live rules into what it applies, so the apply
    writes the rules the cluster already has;
  * the Role stays Synced through any rules a switch writes, so selfHeal has nothing to do.
A scratch Application on watch-it-burn-private with these four options and this ignore kept a client-side applied
Role's rules through three switch-and-promote cycles, and a sync of ai-layer itself on both KubeCon clusters left the
broad start-state Role broad, with agent-sa still able to list Secrets.

Held here, so a change to any of it has to be measured again on a cluster first:
  * ai-layer's syncOptions are the four the live check ran with, in that order;
  * its one ignore on the Role is workshop-agent's `.rules`, by group, kind and name;
  * no other Application source under gitops/ declares a Role named workshop-agent, which would write git's rules;
  * the committed Role carries no sync-options annotation of its own, and its rules are c8-broad-role.yaml's, the
    start state, so a Role Argo CD creates fresh starts with RBAC off;
  * VERSIONS.lock pins the Argo CD the check ran on, v3.5.7.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
APP = REPO / "gitops/bootstrap/apps/ai-layer.yaml"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
GITOPS = REPO / "gitops"
LOCK = REPO / "VERSIONS.lock"
LIVE_CHECKED_OPTIONS = ["CreateNamespace=true", "ServerSideApply=true", "Force=true", "RespectIgnoreDifferences=true"]
LIVE_CHECKED_ARGOCD = "v3.5.7"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


app = yaml.safe_load(APP.read_text(encoding="utf-8"))
spec = app["spec"]

print("== ai-layer syncs the Role with the options #1358's live check ran with ==")
opts = (spec.get("syncPolicy") or {}).get("syncOptions") or []
check("syncOptions are CreateNamespace, ServerSideApply, Force and RespectIgnoreDifferences, in that order",
      opts == LIVE_CHECKED_OPTIONS, str(opts))
check("RespectIgnoreDifferences=true is among them: without it a sync applies git's rules over a switch's",
      "RespectIgnoreDifferences=true" in opts, str(opts))
check("no Replace=true and no ApplyOutOfSyncOnly or ClientSideApplyMigration setting, none of them measured",
      not any(o.split("=")[0] in ("Replace", "ApplyOutOfSyncOnly", "ClientSideApplyMigration") for o in opts), str(opts))
auto = (spec.get("syncPolicy") or {}).get("automated") or {}
check("automated sync with selfHeal, as the live check had: a promotion syncs ai-layer on its own",
      auto.get("selfHeal") is True and auto.get("prune") is True, str(auto))

print("== the ignore on the Role ==")
role_ignores = [i for i in spec.get("ignoreDifferences") or [] if i.get("kind") == "Role"]
check("one Role ignore: rbac.authorization.k8s.io Role workshop-agent, jqPathExpressions ['.rules'] alone",
      role_ignores == [{"group": "rbac.authorization.k8s.io", "kind": "Role", "name": "workshop-agent",
                        "jqPathExpressions": [".rules"]}], str(role_ignores))
check("ai-layer's destination namespace is agent, the Role's",
      spec["destination"].get("namespace") == "agent", str(spec["destination"]))

print("== ai-layer is the one writer of the Role in git ==")
decl = re.compile(r"^kind: Role[ \t]*\n(?:(?![-]{3}).*\n)*?metadata:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+name: workshop-agent[ \t]*$",
                  re.M)
owners = sorted(str(p.relative_to(REPO)) for p in GITOPS.rglob("*.y*ml")
                if p.is_file() and decl.search(p.read_text(encoding="utf-8", errors="replace")))
check("only gitops/ai-layer/resources.yaml declares a top-level Role named workshop-agent",
      owners == ["gitops/ai-layer/resources.yaml"], str(owners))
docs = [d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8")) if d]
roles = [d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "workshop-agent"]
check("resources.yaml declares it once", len(roles) == 1, str(len(roles)))
role = roles[0] if roles else {"metadata": {}, "rules": []}
anns = role["metadata"].get("annotations") or {}
check("the Role carries no argocd.argoproj.io/sync-options or compare-options annotation of its own",
      not any(k.startswith("argocd.argoproj.io/") for k in anns), str(anns))
fixes = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")["data"]
broad = next(d for d in yaml.safe_load_all(fixes["c8-broad-role.yaml"]) if d)
check("the committed rules are c8-broad-role.yaml's, guardrails-off's: a fresh Role starts with RBAC off",
      role.get("rules") == broad.get("rules"), f"\n        git:   {role.get('rules')}\n        c8:    {broad.get('rules')}")

print("== the Argo CD the check ran on ==")
line = next((ln for ln in LOCK.read_text(encoding="utf-8").splitlines() if re.match(r"argocd\s+chart ", ln)), "")
check(f"VERSIONS.lock pins Argo CD {LIVE_CHECKED_ARGOCD}: a bump fails here until #1358's live check runs on the new "
      "version (switch the Role off, sync ai-layer, the Role stays broad)", f"app {LIVE_CHECKED_ARGOCD}" in line, line)

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ai-layer's Role sync checks passed.")
