# ABOUTME: Offline gate for verify/agency_role_check.py (#1151): run against the c5, c6 and c8 workshop-agent Roles of
# ABOUTME: resources.yaml through a kubectl on PATH, only c6 reads as applied, and with no context it fails, reading nothing.
"""The check reads the workshop-agent Role on each named cluster and prints applied or not applied. Here a kubectl on
PATH plays one cluster per context, each holding one Role from the challenge-fixes ConfigMap in
gitops/ai-layer/resources.yaml (or the Role the file ships at its top), returned as the API server would return it.

Held here:
  * c6-least-privilege-role.yaml reads as applied, and so does the same Role with its rules split and reordered;
  * c5-scoped-role.yaml, c8-broad-role.yaml, c8-scoped-role.yaml and the shipped Role read as not applied, each named,
    with create or patch on Deployments or Pods granted;
  * c6 with one more rule reads as not applied and matches no ConfigMap Role;
  * a cluster whose Role cannot be read prints unreadable and the check exits 1;
  * with no context, or an empty one, the check exits 2, says so, and runs no kubectl;
  * every kubectl call names its --context and is a `get` in the agent namespace: the check changes nothing.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import no_cloud  # noqa: E402
no_cloud.setup()

REPO = pathlib.Path(__file__).resolve().parent.parent
CHECK = REPO / "verify/agency_role_check.py"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
KEYS = ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml", "c8-scoped-role.yaml")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        failures.append(name)


def load_roles() -> tuple[dict[str, dict], dict]:
    """The four ConfigMap Roles by key, and the shipped workshop-agent Role at the top of resources.yaml."""
    docs = [d for d in yaml.safe_load_all(RESOURCES.read_text()) if d]
    cm = next((d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes"), None)
    if cm is None:
        sys.exit(f"FAIL {RESOURCES} has no challenge-fixes ConfigMap, which this test reads its Roles from")
    for k in KEYS:
        if k not in cm["data"]:
            sys.exit(f"FAIL {RESOURCES}: the challenge-fixes ConfigMap has no key {k!r}")
    shipped = next((d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "workshop-agent"), None)
    if shipped is None:
        sys.exit(f"FAIL {RESOURCES} ships no workshop-agent Role")
    return {k: yaml.safe_load(cm["data"][k]) for k in KEYS}, shipped


def as_served(role: dict) -> dict:
    """The Role as `kubectl get -o json` prints it: namespaced, with server fields added."""
    r = copy.deepcopy(role)
    r["metadata"] = {**r["metadata"], "namespace": "agent", "uid": "0", "resourceVersion": "1",
                     "creationTimestamp": "2026-11-09T00:00:00Z"}
    return r


FAKE = """#!{py}
import json, os, pathlib, sys
a = sys.argv[1:]
with open(os.environ["FAKE_KUBECTL_LOG"], "a") as f:
    f.write(json.dumps(a) + "\\n")
ctx = a[a.index("--context") + 1] if "--context" in a else None
p = pathlib.Path(os.environ["FAKE_KUBECTL_ROLES"]) / f"{{ctx}}.json"
if ctx is None or not p.exists():
    sys.stderr.write('Error from server (NotFound): roles.rbac.authorization.k8s.io "workshop-agent" not found\\n')
    sys.exit(1)
sys.stdout.write(p.read_text())
"""


def run(tmp: pathlib.Path, *contexts: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
               FAKE_KUBECTL_LOG=str(tmp / "calls"), FAKE_KUBECTL_ROLES=str(tmp / "roles"))
    return subprocess.run([sys.executable, str(CHECK), *contexts], capture_output=True, text=True, env=env)


def calls(tmp: pathlib.Path) -> list[list[str]]:
    log = tmp / "calls"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def main() -> int:
    roles, shipped = load_roles()
    c6 = roles["c6-least-privilege-role.yaml"]
    # c6 again, each rule split into one rule per resource and per verb, in reverse order: the same permissions.
    split = copy.deepcopy(c6)
    split["rules"] = [{**r, "resources": [res], "verbs": [v]}
                      for r in reversed(c6["rules"]) for res in r["resources"] for v in r["verbs"]]
    # c6 with one rule more: no workload writes, but not the Role guard-agency-on applies.
    extra = copy.deepcopy(c6)
    extra["rules"].append({"apiGroups": [""], "resources": ["events"], "verbs": ["list"]})
    cases = {"ctx-c6": c6, "ctx-c6-split": split, "ctx-c5": roles["c5-scoped-role.yaml"],
             "ctx-c8-broad": roles["c8-broad-role.yaml"], "ctx-c8-scoped": roles["c8-scoped-role.yaml"],
             "ctx-shipped": shipped, "ctx-c6-extra": extra}

    with tempfile.TemporaryDirectory(prefix="agency-role-") as d:
        tmp = pathlib.Path(d)
        (tmp / "bin").mkdir()
        (tmp / "roles").mkdir()
        fake = tmp / "bin" / "kubectl"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(0o755)
        for ctx, role in cases.items():
            (tmp / "roles" / f"{ctx}.json").write_text(json.dumps(as_served(role)))

        p = run(tmp, *cases)
        lines = dict(line.split(": ", 1) for line in p.stdout.splitlines() if ": " in line)
        check("every cluster's Role read: exit 0", p.returncode == 0, f"exit {p.returncode}, stderr {p.stderr!r}")
        check("one line per context, in the order given", [line.split(": ", 1)[0] for line in p.stdout.splitlines()]
              == list(cases), p.stdout)
        want = {
            "ctx-c6": "applied: the workshop-agent Role is c6-least-privilege-role.yaml",
            "ctx-c6-split": "applied: the workshop-agent Role is c6-least-privilege-role.yaml",
            "ctx-c5": "not applied: the workshop-agent Role is c5-scoped-role.yaml "
                      "(create or patch on Deployments or Pods: granted)",
            "ctx-c8-broad": "not applied: the workshop-agent Role is c8-broad-role.yaml "
                            "(create or patch on Deployments or Pods: granted)",
            "ctx-c8-scoped": "not applied: the workshop-agent Role is c8-scoped-role.yaml "
                             "(create or patch on Deployments or Pods: granted)",
            # The shipped Role is c8-broad-role.yaml's rules, which c8-broad-role.yaml's comment says it must be.
            "ctx-shipped": "not applied: the workshop-agent Role is c8-broad-role.yaml "
                           "(create or patch on Deployments or Pods: granted)",
            "ctx-c6-extra": "not applied: the workshop-agent Role matches no workshop-agent Role in the "
                            "challenge-fixes ConfigMap (create or patch on Deployments or Pods: not granted)",
        }
        for ctx, line in want.items():
            check(f"{ctx} reads: {line}", lines.get(ctx) == line, f"got {lines.get(ctx)!r}")
        log = calls(tmp)
        check("one kubectl call per context", len(log) == len(cases), f"{len(log)} calls")
        check("every call names its --context, one per context in order",
              [a[a.index("--context") + 1] if "--context" in a else None for a in log] == list(cases), str(log))
        check("every call is a read: kubectl get role workshop-agent in agent, as JSON",
              all(a[2:] == ["-n", "agent", "get", "role", "workshop-agent", "-o", "json"] for a in log), str(log))

        (tmp / "calls").unlink(missing_ok=True)
        p = run(tmp, "ctx-c6", "ctx-gone")
        check("a Role that cannot be read: exit 1", p.returncode == 1, f"exit {p.returncode}")
        check("it prints unreadable with kubectl's error, and still reads the other cluster",
              p.stdout.splitlines() == ["ctx-c6: applied: the workshop-agent Role is c6-least-privilege-role.yaml",
                                        'ctx-gone: unreadable: Error from server (NotFound): '
                                        'roles.rbac.authorization.k8s.io "workshop-agent" not found'], p.stdout)

        for args, label in (((), "no context"), (("",), "an empty context"), (("ctx-c6", " "), "a blank second context")):
            (tmp / "calls").unlink(missing_ok=True)
            p = run(tmp, *args)
            check(f"{label}: exit 2, a FAIL line naming the kube-context, nothing on stdout",
                  p.returncode == 2 and "FAIL" in p.stderr and "kube-context" in p.stderr and not p.stdout,
                  f"exit {p.returncode}, stdout {p.stdout!r}, stderr {p.stderr!r}")
            check(f"{label}: no kubectl ran", not calls(tmp), str(calls(tmp)))

    check("no call reached the no-cloud stubs", not no_cloud.calls(), str(no_cloud.calls()))
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("All agency Role checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
