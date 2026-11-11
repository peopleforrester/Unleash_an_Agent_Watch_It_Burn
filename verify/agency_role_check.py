# ABOUTME: Read-only check (#1151): reads the agent/workshop-agent Role with kubectl on each kube-context named, and
# ABOUTME: prints per cluster whether it is one of the two least-privilege Roles guard-agency-on applies.
"""Is guard-agency-on's least-privilege Role applied on each cluster?

    python3 verify/agency_role_check.py watch-it-burn-community watch-it-burn-private

Each argument is a kube-context, and every kubectl call names it with --context; with none, the check fails and reads
nothing, never falling back to the current-context. It runs one `kubectl get` per cluster and changes nothing.

guard-agency-on applies, from the challenge-fixes ConfigMap in gitops/ai-layer/resources.yaml,
c6-least-privilege-role.yaml where the RBAC guardrail is on and c6-broad-secrets-role.yaml where it is off (#1362), and
guard-agency-off puts c5-scoped-role.yaml or c8-broad-role.yaml back (#1358). The workshop-agent Roles there differ
like this:

  * c8-broad-role.yaml (the Role the cluster ships with): create and patch on Deployments and Pods, get and list on
    every Secret.
  * c8-scoped-role.yaml and c5-scoped-role.yaml: the same workload verbs, get on one Secret by name.
  * c6-least-privilege-role.yaml: c5's one Secret, and get and list only on Deployments and Pods.
  * c6-broad-secrets-role.yaml: c6's workload rules with c8-broad-role.yaml's get and list on every Secret.
  The two c6 Roles are the only ones that grant no create or patch on Deployments or Pods.

So a Role is "applied" when its permissions, each rule expanded to (API group, resource, verb, resource name), are the
same set as one c6 Role's, which no order or split of the rules changes. Otherwise it is "not applied", and the line names the
ConfigMap Role it matches, or says it matches none, and whether it grants create or patch on Deployments or Pods. That
last reading is guard-proxy's `infra.agency_scoped` on /controls (guard-proxy-agenticburn#76, proxy.py
_role_grants_workload_writes), which this check stands in for until the pinned proxy runs on both clusters.

Exit 0 when every cluster's Role was read, whatever it reads as; 1 when one could not be read; 2 with no context.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
FIX = "c6-least-privilege-role.yaml"
# guard-agency-on's Role where the RBAC guardrail is off (#1362): FIX's workload rules, every Secret.
FIX_BROAD = "c6-broad-secrets-role.yaml"
FIXES = (FIX, FIX_BROAD)
NS = "agent"
ROLE = "workshop-agent"
# What guard-proxy's agency_scoped looks for: create or patch on apps Deployments or core Pods.
WORKLOAD_WRITES = (("apps", "deployments"), ("", "pods"))


def role_files(path: pathlib.Path = RESOURCES) -> dict[str, dict]:
    """Every workshop-agent Role in the challenge-fixes ConfigMap, by its key there, parsed."""
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"] == "challenge-fixes":
            out = {}
            for key, text in doc["data"].items():
                for d in yaml.safe_load_all(text):
                    if isinstance(d, dict) and d.get("kind") == "Role" and d["metadata"].get("name") == ROLE:
                        out[key] = d
            for key in FIXES:
                if key not in out:
                    raise RuntimeError(f"{path}: the challenge-fixes ConfigMap has no workshop-agent Role under {key}")
            return out
    raise RuntimeError(f"{path} has no challenge-fixes ConfigMap")


def permissions(role: dict) -> frozenset[tuple[str, str, str, str | None]]:
    """The Role's rules as (API group, resource, verb, resource name or None) tuples."""
    out = set()
    for r in role.get("rules") or []:
        names = r.get("resourceNames") or [None]
        for g in r.get("apiGroups") or []:
            for res in r.get("resources") or []:
                for v in r.get("verbs") or []:
                    for n in names:
                        out.add((g, res, v, n))
    return frozenset(out)


def grants_workload_writes(role: dict) -> bool:
    """True when a rule grants create or patch (or *) on Deployments or Pods, a wildcard group or resource included."""
    for r in role.get("rules") or []:
        if not {"create", "patch", "*"} & set(r.get("verbs") or []):
            continue
        groups, res = r.get("apiGroups") or [], r.get("resources") or []
        if any((g in groups or "*" in groups) and (k in res or "*" in res) for g, k in WORKLOAD_WRITES):
            return True
    return False


def verdict(role: dict, files: dict[str, dict]) -> tuple[bool, str]:
    """(applied, the line's reading) for one live Role."""
    have = permissions(role)
    for key in FIXES:
        if have == permissions(files[key]):
            return True, f"applied: the workshop-agent Role is {key}"
    match = next((k for k, d in sorted(files.items()) if permissions(d) == have), None)
    what = f"is {match}" if match else "matches no workshop-agent Role in the challenge-fixes ConfigMap"
    writes = "granted" if grants_workload_writes(role) else "not granted"
    return False, f"not applied: the workshop-agent Role {what} (create or patch on Deployments or Pods: {writes})"


def read_role(context: str) -> tuple[dict | None, str]:
    p = subprocess.run(["kubectl", "--context", context, "-n", NS, "get", "role", ROLE, "-o", "json"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        lines = (p.stderr or p.stdout).strip().splitlines()
        return None, lines[-1] if lines else f"kubectl exited {p.returncode}"
    try:
        return json.loads(p.stdout), ""
    except ValueError as e:
        return None, f"kubectl printed no Role JSON ({e})"


def main(argv: list[str]) -> int:
    contexts = argv[1:]
    if not contexts or any(not c.strip() for c in contexts):
        print("FAIL: name each cluster's kube-context, e.g. python3 verify/agency_role_check.py "
              "watch-it-burn-community watch-it-burn-private; this check never reads the current-context",
              file=sys.stderr)
        return 2
    files = role_files()
    unreadable = 0
    for ctx in contexts:
        role, err = read_role(ctx)
        if role is None:
            unreadable += 1
            print(f"{ctx}: unreadable: {err}")
            continue
        print(f"{ctx}: {verdict(role, files)[1]}")
    return 1 if unreadable else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
