# ABOUTME: Offline gate for _both in the terminal's .guardlib (#1147): guardrails-agency-on and guardrails-agency-off switch this
# ABOUTME: cluster and the linked KubeCon peer, name a peer they could not reach, and guardrails-k8s-on/off stay as they were.
"""#1147, the first piece of #1132. guardrails-agency-on and guardrails-agency-off used to change only the cluster whose terminal
ran them, while the room plays on the public bot. _both in ~/.guardlib (gitops/ai-layer/web-terminal/entrypoint.sh)
runs one switch step here, then on the other KubeCon cluster through the kubeconfig in the
guardrails-switch/guardrails-peer Secret, the way _guardrails reaches it.

Checked here, with a kubectl on PATH that plays two clusters:
  * guardrails-agency-on and guardrails-agency-off apply their Role on both clusters, say which clusters changed, and print every
    kubectl they run; each printed line, run by bash, makes the same call;
  * a peer Secret whose cluster cannot be reached: this cluster switches, the run fails and names the peer;
  * a cluster with no peer Secret (the 2-hour workshop's): this cluster switches alone, one line says so, exit 0;
  * a peer Secret that is there but cannot be read: this cluster switches and the run fails, never passing as unlinked;
  * guardrails-agency-off reads each cluster's Role first and keeps its Secret rule (#1358): c8-broad-role.yaml where RBAC is
    off, c5-scoped-role.yaml where it is on, so guardrails-ai-off, guardrails-k8s-off, guardrails-agency-off (the 2026-11-11 16:14Z
    reset) ends broad on both, and a Role it cannot read is not written;
  * guardrails-agency-on keeps each cluster's Secret rule too (#1362): c6-least-privilege-role.yaml where RBAC is on,
    c6-broad-secrets-role.yaml where it is off, so guardrails-agency-on then guardrails-agency-off from the start state (after
    guardrails-k8s-off) ends with the shipped broad Role and RBAC scope off on both clusters;
  * what the two commands ask of the peer is inside its guardrails-switch grant, and that grant is #774's plus
    #1148's one guard-proxy Service proxy rule;
  * guardrails-k8s-on and guardrails-k8s-off make the same kubectl calls and print the same output as before #1147, held to
    verify/fixtures/guardrails-switch-golden.json, recorded from staging e4354c50 and recorded again for #1349, whose
    closing /controls read (_controls) both now end on: the switch's calls and lines are #774's, then the read.

`python3 verify/test_guard_switch_both.py --write-golden` rewrites that file from the current entrypoint. Run it only
when guardrails-k8s-on or guardrails-k8s-off is meant to change, and say why in decisions.md.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import no_cloud  # noqa: E402
no_cloud.setup()

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
TWIN = REPO / "images/web-terminal/entrypoint.sh"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
SWITCH = REPO / "gitops/guardrails-switch/guardrails-switch.yaml"
GOLDEN = REPO / "verify/fixtures/guardrails-switch-golden.json"
PEER = "watch-it-burn-community"
STEP_SECONDS = 300
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


FIXES = next(d for d in docs(RESOURCES.read_text(encoding="utf-8")) if d.get("kind") == "ConfigMap"
             and d["metadata"]["name"] == "challenge-fixes")["data"]

# A kubectl that plays two clusters. A call with --kubeconfig is the peer, named by its --context; any other is this
# cluster. MODE picks the case: linked, unlinked (no peer Secret), peer-down (the peer's API cannot be reached),
# secret-unreadable (this cluster's API refuses the Secret read) and here-down (this cluster refuses the change).
FAKE = r'''#!/usr/bin/env python3
import base64, json, os, sys
a = sys.argv[1:]
if "--kubeconfig" in a:
    i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]
    j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]
else:
    ctx = "this"
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"cluster": ctx, "args": a}) + "\n")
state = json.load(open(os.environ["STATE"]))
mode = os.environ["MODE"]
if "guardrails-peer" in a:
    if mode == "secret-unreadable":
        sys.stderr.write("Unable to connect to the server: i/o timeout\n"); sys.exit(1)
    if mode == "unlinked":
        if "--ignore-not-found" in a:
            sys.exit(0)
        sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
    if "--ignore-not-found" in a:
        print("secret/guardrails-peer"); sys.exit(0)
    key = a[-1]
    print(base64.b64encode(b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in key else b"watch-it-burn-community").decode())
    sys.exit(0)
if mode == "peer-down" and ctx != "this":
    sys.stderr.write("Unable to connect to the server\n"); sys.exit(1)
if mode == "here-down" and ctx == "this":
    sys.stderr.write("Error from server (Forbidden)\n"); sys.exit(1)
if "patch" in a and "validatingpolicy" in a:
    state.setdefault(ctx, {})[a[a.index("validatingpolicy") + 1]] = json.loads(a[a.index("-p") + 1])[0]["value"][0]
elif "get" in a and "validatingpolicy" in a:
    sys.stdout.write(state.get(ctx, {}).get(a[a.index("validatingpolicy") + 1], "Audit"))
elif "apply" in a:
    state.setdefault(ctx, {})["applied"] = state.get(ctx, {}).get("applied", []) + [os.path.basename(a[-1])]
elif "get" in a and "role" in a and "workshop-agent" in a:
    # _agency_off's read of the live Role (#1358): the rules of the last Role applied there, else the one it started
    # with (START_ROLE, or START_ROLE_PEER on the peer). ROLE_UNREADABLE names a cluster whose read fails.
    if os.environ.get("ROLE_UNREADABLE") == ctx:
        sys.stderr.write("Error from server (Forbidden)\n"); sys.exit(1)
    s = state.get(ctx, {})
    start = os.environ.get("START_ROLE_PEER" if ctx != "this" else "START_ROLE") or os.environ.get("START_ROLE")
    role = next((f for f in reversed(s.get("applied", [])) if f.endswith("-role.yaml")), start or "c8-broad-role.yaml")
    print(json.dumps({"kind": "Role", "metadata": {"name": "workshop-agent", "namespace": "agent"},
                      "rules": json.load(open(os.environ["ROLES"]))[role]}))
elif "/controls" in " ".join(a):
    # The closing /controls read every stage switch ends on (#1349), measured from what this fake holds.
    s = state.get(ctx, {})
    start = os.environ.get("START_ROLE_PEER" if ctx != "this" else "START_ROLE") or os.environ.get("START_ROLE")
    role = next((f for f in reversed(s.get("applied", [])) if f.endswith("-role.yaml")), start or "c8-broad-role.yaml")
    print(json.dumps({"ai": {"output": False}, "infra": {
        "kyverno": s.get("restrict-image-registries") == "Deny",
        "rbac_scoped": role in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml"),
        "agency_scoped": role in ("c6-least-privilege-role.yaml", "c6-broad-secrets-role.yaml")}, "host": ctx + ".example"}))
json.dump(state, open(os.environ["STATE"], "w"))
'''

# The rules of each Role in challenge-fixes, which the fake answers _agency_off's read with.
ROLE_RULES = {name: d["rules"] for name, body in FIXES.items() if name.endswith("-role.yaml")
              for d in docs(body) if d.get("kind") == "Role"}

FAKE_DATE = "#!/usr/bin/env bash\necho 1762300800\n"
FAKE_SLEEP = "#!/usr/bin/env bash\nexit 0\n"

helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT.read_text(encoding="utf-8"), re.S))


def timed(argv: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=STEP_SECONDS, **kw)
    except subprocess.TimeoutExpired:
        sys.exit(f"FAILED: {' '.join(argv)[:200]} ran past {STEP_SECONDS} seconds")


def run(cmd: str, mode: str, args: tuple[str, ...] = (), start: str = "", start_peer: str = "",
        before: tuple[str, ...] = (), unreadable: str = "") -> dict:
    """Run one terminal command against the fake. Returns its exit code, output, calls, and the calls its printed
    `$ ` lines make when bash runs them again, with the temp HOME written as $HOME so a run reads the same twice.
    start and start_peer name the Role each cluster holds before (the shipped c8-broad-role.yaml when unset); each
    command in before runs first against the same clusters, and only cmd's calls and output are returned; unreadable
    names a cluster ("this" or the peer) whose Role cannot be read."""
    with tempfile.TemporaryDirectory() as tmp:
        home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        home.mkdir(); fakebin.mkdir(); (home / "challenges").mkdir()  # noqa: E702
        for name, body in FIXES.items():
            (home / "challenges" / name).write_text(body)
        for name, body in helpers.items():
            (home / name).write_text(body + "\n")
        # A clock that stands still and a sleep that returns at once (#1349): _controls waits out guard-proxy's 5 s
        # cache after a Kubernetes write, and with the clock pinned it always says so, so the record reads the same.
        for tool, body in (("kubectl", FAKE), ("date", FAKE_DATE), ("sleep", FAKE_SLEEP)):
            (fakebin / tool).write_text(body)
            (fakebin / tool).chmod(0o755)
        calls, state = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "state")
        state.write_text("{}")
        roles = pathlib.Path(tmp, "roles.json")
        roles.write_text(json.dumps(ROLE_RULES))
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls),
               "STATE": str(state), "MODE": mode, "ROLES": str(roles), "START_ROLE": start,
               "START_ROLE_PEER": start_peer, "ROLE_UNREADABLE": unreadable}
        for b in before:
            timed(["bash", str(home / b)], env=env)
        calls.unlink(missing_ok=True)
        state0 = state.read_text()
        r = timed(["bash", str(home / cmd), *args], env=env)
        ran = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        shown = [line[2:] for line in (r.stdout + r.stderr).splitlines() if line.startswith("$ ")]
        replay = pathlib.Path(tmp, "replay")
        pathlib.Path(tmp, "state2").write_text("{}")
        pathlib.Path(tmp, "state2").write_text(state0)
        renv = {**env, "CALLS": str(replay), "STATE": str(pathlib.Path(tmp, "state2"))}
        for line in shown:
            timed(["bash", "-c", line], env=renv)
        replayed = [json.loads(line) for line in replay.read_text().splitlines()] if replay.exists() else []
        h = str(home)
        norm = lambda s: s.replace(h, "$HOME")  # noqa: E731
        return {"rc": r.returncode, "stdout": norm(r.stdout), "stderr": norm(r.stderr),
                "calls": [{"cluster": c["cluster"], "args": [norm(x) for x in c["args"]]} for c in ran],
                "replayed": [{"cluster": c["cluster"], "args": [norm(x) for x in c["args"]]} for c in replayed],
                "state": json.loads(state.read_text())}


GOLDEN_CASES = [("guardrails-k8s-on", "linked"), ("guardrails-k8s-off", "linked"), ("guardrails-k8s-on", "unlinked"),
                ("guardrails-k8s-off", "unlinked"), ("guardrails-k8s-on", "peer-down"), ("guardrails-k8s-off", "peer-down")]


def golden_now() -> dict:
    return {f"{cmd} {mode}": {k: v for k, v in run(cmd, mode).items() if k in ("rc", "stdout", "stderr", "calls")}
            for cmd, mode in GOLDEN_CASES}


if "--write-golden" in sys.argv[1:]:
    GOLDEN.write_text(json.dumps(golden_now(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN.relative_to(REPO)}")
    sys.exit(0)

ROLE = {"guardrails-agency-on": "c6-least-privilege-role.yaml", "guardrails-agency-off": "c5-scoped-role.yaml"}
# The Role each cluster holds before the command, in talk order: guardrails-agency-on after guardrails-k8s-on's c5, guardrails-agency-off
# after guardrails-agency-on's c6. The checks below run each command from there.
TALK_START = {"guardrails-agency-on": "c5-scoped-role.yaml", "guardrails-agency-off": "c6-least-privilege-role.yaml"}
# The calls each makes on two linked clusters: two reads of the peer Secret, then per cluster the read of the Role
# (#1358, #1362) and the apply, then the closing /controls read on each (#1349).
LINKED_CALLS = {"guardrails-agency-on": 8, "guardrails-agency-off": 8}
STEP = {"guardrails-agency-on": "_both _agency_on", "guardrails-agency-off": "_both _agency_off"}

print("== _both is in .guardlib, and the two commands use it ==")
lib = helpers.get(".guardlib", "")
check("the terminal ships .guardlib, guardrails-agency-on and guardrails-agency-off",
      {".guardlib", "guardrails-agency-on", "guardrails-agency-off"} <= set(helpers))
check(".guardlib defines _both, beside _peer", re.search(r"^_both\(\) \{", lib, re.M) is not None and "_peer()" in lib)
for cmd, f in ROLE.items():
    body = helpers.get(cmd, "")
    check(f"{cmd} switches through {STEP[cmd]}, and runs no kubectl of its own",
          STEP[cmd] in body and "kubectl" not in body, body)
check(".guardlib defines _keep_secrets, which applies through _apply, and _agency_on and _agency_off on it",
      re.search(r"^_keep_secrets\(\) \{", lib, re.M) is not None and '_apply "$f" "$@"' in lib
      and "_agency_on() { _keep_secrets c6-broad-secrets-role.yaml c6-least-privilege-role.yaml \"$@\"; }" in lib
      and "_agency_off() { _keep_secrets c8-broad-role.yaml c5-scoped-role.yaml \"$@\"; }" in lib)
check("the KubeCon terminals run gitops/ai-layer/web-terminal/entrypoint.sh: ai-layer mounts it over the image's copy",
      "entrypoint.sh=web-terminal/entrypoint.sh" in (REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8")
      and "{ name: entrypoint, mountPath: /entrypoint.sh, subPath: entrypoint.sh, readOnly: true }"
      in RESOURCES.read_text(encoding="utf-8"))
check("images/web-terminal/entrypoint.sh is kept byte-identical to it", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

print("== guardrails-agency-on and guardrails-agency-off on two linked clusters ==")
for cmd, f in ROLE.items():
    r = run(cmd, "linked", start=TALK_START[cmd])
    out = r["stdout"] + r["stderr"]
    applies = [(c["cluster"], c["args"]) for c in r["calls"] if c["args"][:1] == ["apply"]]
    check(f"{cmd}: exits 0", r["rc"] == 0, out)
    check(f"{cmd}: applies ~/challenges/{f} on this cluster, then on {PEER}, and nothing else",
          applies == [("this", ["apply", "-f", f"$HOME/challenges/{f}"]), (PEER, ["apply", "-f", f"$HOME/challenges/{f}"])],
          str(applies))
    check(f"{cmd}: both clusters hold the Role afterwards", r["state"].get("this", {}).get("applied") == [f]
          and r["state"].get(PEER, {}).get("applied") == [f], str(r["state"]))
    check(f"{cmd}: says it switched both clusters, naming {PEER}",
          f"Switched on both clusters: this one and {PEER}." in r["stdout"], r["stdout"])
    check(f"{cmd}: still explains what the Role does", "Least privilege " + ("ON" if cmd.endswith("on") else "OFF")
          in r["stdout"], r["stdout"])
    # Two reads of the peer Secret, the apply on each cluster, then the closing /controls read on each (#1349).
    check(f"{cmd}: every line it prints, run by bash, makes the call it made, in order",
          r["replayed"] == r["calls"] and len(r["calls"]) == LINKED_CALLS[cmd],
          f"\n    shown: {r['replayed']}\n    ran:   {r['calls']}")
    others = [c for c in r["calls"] if c["cluster"] not in ("this", PEER)]
    check(f"{cmd}: touches no cluster but these two", not others, str(others))

print("== guardrails-agency-off keeps each cluster's Secret rule: least privilege off never turns RBAC on (#1358) ==")
c5, c6, c8 = "c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml"
for this0, peer0, want_this, want_peer, why in (
        (c8, c8, c8, c8, "from the start state, the shipped broad Role on both"),
        (c6, c6, c5, c5, "after guardrails-agency-on, in talk order: RBAC was on"),
        (c5, c5, c5, c5, "after guardrails-k8s-on alone"),
        (c8, c6, c8, c5, "this cluster broad, the peer least-privileged: each keeps its own")):
    r = run("guardrails-agency-off", "linked", start=this0, start_peer=peer0)
    applies = [(c["cluster"], c["args"][-1].rsplit("/", 1)[-1]) for c in r["calls"] if c["args"][:1] == ["apply"]]
    check(f"guardrails-agency-off {why}: applies {want_this} here and {want_peer} on {PEER}, exit 0",
          r["rc"] == 0 and applies == [("this", want_this), (PEER, want_peer)], f"{r['rc']} {applies}")
    reads = [c for c in r["calls"] if c["args"] == ["-n", "agent", "get", "role", "workshop-agent", "-o", "json"]]
    check(f"guardrails-agency-off {why}: reads the Role on each cluster before it applies, and prints the read",
          [c["cluster"] for c in reads] == ["this", PEER] and r["replayed"] == r["calls"], str(r["calls"]))
    for ctx, want in (("this", want_this), (PEER, want_peer)):
        rules = ROLE_RULES[want]
        check(f"guardrails-agency-off {why}: {ctx} ends with create on Deployments and Pods (least privilege off)",
              any("apps" in x.get("apiGroups", []) and "deployments" in x.get("resources", [])
                  and "create" in x.get("verbs", []) for x in rules)
              and any("" in x.get("apiGroups", []) and "pods" in x.get("resources", [])
                      and "create" in x.get("verbs", []) for x in rules), str(rules))
r = run("guardrails-agency-off", "linked", before=("guardrails-ai-off", "guardrails-k8s-off"), start=c5, start_peer=c5)
applies = [(c["cluster"], c["args"][-1].rsplit("/", 1)[-1]) for c in r["calls"] if c["args"][:1] == ["apply"]]
check("the 2026-11-11 16:14Z reset, guardrails-ai-off then guardrails-k8s-off then guardrails-agency-off, ends broad on both clusters",
      r["rc"] == 0 and applies == [("this", c8), (PEER, c8)], f"{r['rc']} {applies}")
check("and its closing read shows RBAC scope off on both, the start state",
      "RBAC scope" in r["stdout"] and all("RBAC scope" in (ln.split("off:", 1)[-1] if "off:" in ln else "")
                                          for ln in r["stdout"].splitlines() if ln.strip().startswith("Kubernetes")),
      r["stdout"])
for who in ("this", PEER):
    r = run("guardrails-agency-off", "linked", start=c6, start_peer=c6, unreadable=who)
    applied = [c["cluster"] for c in r["calls"] if c["args"][:1] == ["apply"]]
    check(f"guardrails-agency-off: a Role it cannot read on {who} is not written there, and the run fails",
          r["rc"] == 1 and who not in applied and len(applied) == 1, f"{r['rc']} {applied}\n{r['stdout']}")

def creates_workloads(rules: list[dict]) -> bool:
    return any(("apps" in x.get("apiGroups", []) and "deployments" in x.get("resources", []))
               or ("" in x.get("apiGroups", []) and "pods" in x.get("resources", []))
               for x in rules if {"create", "patch", "*"} & set(x.get("verbs", [])))


def secrets_broad(rules: list[dict]) -> bool:
    return any("" in x.get("apiGroups", []) and "secrets" in x.get("resources", []) and not x.get("resourceNames")
               for x in rules)


def badges(stdout: str) -> dict[str, tuple[str, str]]:
    """Each cluster's closing /controls line, split into what it reads as on and as off."""
    out = {}
    for ln in stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("Kubernetes") and ":" in ln:
            on, _, off = ln.partition("off:")
            out[len(out)] = (on, off)
    return out


print("== guardrails-agency-on keeps each cluster's Secret rule: least privilege on never turns RBAC on (#1362) ==")
c6b = "c6-broad-secrets-role.yaml"
check(f"challenge-fixes holds {c6b}", c6b in ROLE_RULES, str(sorted(ROLE_RULES)))
check(f"{c6b} is c6-least-privilege-role.yaml's workload rules with c8-broad-role.yaml's Secret rule",
      [x for x in ROLE_RULES.get(c6b, []) if "secrets" not in x.get("resources", [])]
      == [x for x in ROLE_RULES[c6] if "secrets" not in x.get("resources", [])]
      and [x for x in ROLE_RULES.get(c6b, []) if "secrets" in x.get("resources", [])]
      == [x for x in ROLE_RULES[c8] if "secrets" in x.get("resources", [])], str(ROLE_RULES.get(c6b)))
for this0, peer0, want_this, want_peer, why in (
        (c8, c8, c6b, c6b, "from the start state, the shipped broad Role on both"),
        (c5, c5, c6, c6, "after guardrails-k8s-on, in talk order: RBAC is on"),
        (c8, c5, c6b, c6, "this cluster broad, the peer scoped: each keeps its own")):
    r = run("guardrails-agency-on", "linked", start=this0, start_peer=peer0)
    applies = [(c["cluster"], c["args"][-1].rsplit("/", 1)[-1]) for c in r["calls"] if c["args"][:1] == ["apply"]]
    check(f"guardrails-agency-on {why}: applies {want_this} here and {want_peer} on {PEER}, exit 0",
          r["rc"] == 0 and applies == [("this", want_this), (PEER, want_peer)], f"{r['rc']} {applies}")
    reads = [c for c in r["calls"] if c["args"] == ["-n", "agent", "get", "role", "workshop-agent", "-o", "json"]]
    check(f"guardrails-agency-on {why}: reads the Role on each cluster before it applies, and prints the read",
          [c["cluster"] for c in reads] == ["this", PEER] and r["replayed"] == r["calls"], str(r["calls"]))
    for ctx, start0, want in (("this", this0, want_this), (PEER, peer0, want_peer)):
        rules = ROLE_RULES[want]
        check(f"guardrails-agency-on {why}: {ctx} ends with no create or patch on Deployments or Pods, and its Secret rule "
              f"as it was", not creates_workloads(rules) and secrets_broad(rules) == secrets_broad(ROLE_RULES[start0]),
              str(rules))
for who in ("this", PEER):
    r = run("guardrails-agency-on", "linked", start=c8, start_peer=c8, unreadable=who)
    applied = [c["cluster"] for c in r["calls"] if c["args"][:1] == ["apply"]]
    check(f"guardrails-agency-on: a Role it cannot read on {who} is not written there, and the run fails",
          r["rc"] == 1 and who not in applied and len(applied) == 1, f"{r['rc']} {applied}\n{r['stdout']}")

# The rehearsal #1362 reported: from the start state (guardrails-k8s-off after a talk that had scoped both Roles),
# guardrails-agency-on, then guardrails-agency-off.
r = run("guardrails-agency-on", "linked", before=("guardrails-k8s-off",), start=c5, start_peer=c5)
applies = [(c["cluster"], c["args"][-1].rsplit("/", 1)[-1]) for c in r["calls"] if c["args"][:1] == ["apply"]]
read = badges(r["stdout"])
check("guardrails-agency-on after guardrails-k8s-off applies the broad-Secret least-privilege Role on both clusters",
      r["rc"] == 0 and applies == [("this", c6b), (PEER, c6b)], f"{r['rc']} {applies}")
check("and its closing read shows least privilege on and RBAC scope off on both clusters",
      len(read) == 2 and all("least privilege" in on and "RBAC scope" in off for on, off in read.values()),
      r["stdout"])
r = run("guardrails-agency-off", "linked", before=("guardrails-k8s-off", "guardrails-agency-on"), start=c5, start_peer=c5)
applies = [(c["cluster"], c["args"][-1].rsplit("/", 1)[-1]) for c in r["calls"] if c["args"][:1] == ["apply"]]
read = badges(r["stdout"])
check("guardrails-k8s-off, guardrails-agency-on, guardrails-agency-off ends with the shipped broad Role on both clusters",
      r["rc"] == 0 and applies == [("this", c8), (PEER, c8)], f"{r['rc']} {applies}")
check("and its closing read shows RBAC scope and least privilege off on both, the start state",
      len(read) == 2 and all("RBAC scope" in off and "least privilege" in off for _on, off in read.values()),
      r["stdout"])

print("== the peer Secret is there, its cluster cannot be reached ==")
for cmd, f in ROLE.items():
    r = run(cmd, "peer-down", start=TALK_START[cmd])
    check(f"{cmd}: still applies {f} on this cluster", r["state"].get("this", {}).get("applied") == [f], str(r["state"]))
    check(f"{cmd}: fails, naming {PEER} as the cluster it could not reach",
          r["rc"] == 1 and f"not on {PEER}: it could not be reached, or it refused the change." in r["stdout"],
          r["stdout"])
    check(f"{cmd}: does not print the explanation, which would read as done",
          "Least privilege" not in r["stdout"] and f"try '{cmd}' again" in r["stdout"], r["stdout"])

print("== a cluster with no guardrails-peer Secret, the 2-hour workshop's ==")
for cmd, f in ROLE.items():
    r = run(cmd, "unlinked", start=TALK_START[cmd])
    lines = [line for line in r["stdout"].splitlines() if line.strip()]
    alone = [line for line in lines if "alone" in line]
    check(f"{cmd}: applies {f} here and exits 0", r["rc"] == 0 and r["state"].get("this", {}).get("applied") == [f],
          r["stdout"] + r["stderr"])
    check(f"{cmd}: says in one line that this cluster was switched alone",
          alone == ["Switched on this cluster alone: it has no guardrails-switch/guardrails-peer Secret, so no other "
                    "cluster is linked to it."], str(lines))
    check(f"{cmd}: and still explains what the Role does", any(line.startswith(("🛡️", "🔓")) for line in lines), str(lines))
    check(f"{cmd}: touches no other cluster", {c["cluster"] for c in r["calls"]} == {"this"}, str(r["calls"]))
    check(f"{cmd}: tells an absent Secret from an unreadable one with --ignore-not-found, a call it prints",
          ["-n", "guardrails-switch", "get", "secret", "guardrails-peer", "--ignore-not-found", "-o", "name"]
          in [c["args"] for c in r["calls"]] and r["replayed"] == r["calls"], str(r["calls"]))

print("== a peer Secret this cluster cannot read is a failure, not the 2-hour workshop ==")
for cmd, f in ROLE.items():
    r = run(cmd, "secret-unreadable", start=TALK_START[cmd])
    check(f"{cmd}: applies {f} here, then fails saying the other cluster was not switched",
          r["rc"] == 1 and r["state"].get("this", {}).get("applied") == [f]
          and "guardrails-switch/guardrails-peer could not be read" in r["stdout"] and "alone" not in r["stdout"],
          r["stdout"])

print("== this cluster refuses the change ==")
for cmd, f in ROLE.items():
    r = run(cmd, "here-down", start=TALK_START[cmd])
    check(f"{cmd}: fails, says this cluster did not switch, and still switches {PEER}",
          r["rc"] == 1 and "not on this cluster" in r["stdout"] and r["state"].get(PEER, {}).get("applied") == [f],
          r["stdout"])

print("== what the peer is asked for is inside its guardrails-switch grant, #774's plus one guard-proxy rule ==")
sw = docs(SWITCH.read_text(encoding="utf-8"))
GRANT: dict[tuple[str, str, str], set[str]] = {}
for d in sw:
    if d["kind"] in ("Role", "ClusterRole"):
        scope = d["metadata"].get("namespace", "")
        for rule in d["rules"]:
            for res in rule["resources"]:
                for name in rule.get("resourceNames") or ["*"]:
                    GRANT.setdefault((scope, res, name), set()).update(rule["verbs"])
check("the grant is #774's, with #1148's get on guard-proxy's Service proxy alone added: the workshop-agent Role by "
      "name (get, patch, escalate), the two registry policies, KubeArmor policies and NetworkPolicies in agent",
      GRANT == {("agent", "roles", "workshop-agent"): {"get", "patch", "escalate"},
                ("agent", "services/proxy", "guard-proxy:8080"): {"get"},
                ("agent", "kubearmorpolicies", "*"): {"get", "list", "watch", "create", "patch", "delete"},
                ("agent", "networkpolicies", "*"): {"get", "list", "watch", "create", "patch", "delete"},
                ("", "validatingpolicies", "restrict-image-registries"): {"get", "patch"},
                ("", "validatingpolicies", "deny-external-registries"): {"get", "patch"}}, str(GRANT))
for f in (c5, c6, c6b, c8):
    ds = docs(FIXES[f])
    check(f"~/challenges/{f} is the workshop-agent Role in agent alone, the one Role the peer may write",
          [(d["kind"], d["metadata"]["namespace"], d["metadata"]["name"]) for d in ds] == [("Role", "agent", "workshop-agent")])
for cmd, start0 in [(c, TALK_START[c]) for c in ROLE] + [("guardrails-agency-on", c8), ("guardrails-agency-off", c6b)]:
    r = run(cmd, "linked", start=start0)
    # kubectl apply on an existing Role reads it and patches it; writing rules the switch identity does not hold
    # needs escalate on that Role. The Role exists from git, so no create. guardrails-agency-off's read is a get (#1358).
    need = {("agent", "roles", "workshop-agent", v) for c in r["calls"] if c["cluster"] == PEER
            and c["args"][:1] == ["apply"] for v in ("get", "patch", "escalate")}
    need |= {("agent", "roles", "workshop-agent", "get") for c in r["calls"] if c["cluster"] == PEER
             and c["args"][:5] == ["-n", "agent", "get", "role", "workshop-agent"]}
    missing = sorted(n for n in need if n[3] not in GRANT.get(n[:3], set()))
    check(f"{cmd}: everything it asks of {PEER} is inside the guardrails-switch grant", bool(need) and not missing,
          str(missing))

print("== guardrails-k8s-on and guardrails-k8s-off are as they were ==")
if not GOLDEN.exists():
    sys.exit(f"FAILED: {GOLDEN.relative_to(REPO)} is missing; it holds guardrails-k8s-on and guardrails-k8s-off to #774's calls")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
check("the record covers guardrails-k8s-on and guardrails-k8s-off linked, unlinked and with the peer down",
      sorted(want) == sorted(f"{c} {m}" for c, m in GOLDEN_CASES), str(sorted(want)))
got = golden_now()
for key in sorted(want):
    w, g = want[key], got.get(key, {})
    for part in ("rc", "calls", "stdout", "stderr"):
        detail = ""
        if w.get(part) != g.get(part):
            wl = w.get(part) if isinstance(w.get(part), list) else str(w.get(part)).splitlines()
            gl = g.get(part) if isinstance(g.get(part), list) else str(g.get(part)).splitlines()
            n = next((i for i, (a, b) in enumerate(zip(wl, gl)) if a != b), min(len(wl), len(gl)))
            detail = f"first difference at item {n}:\n          was {wl[n] if n < len(wl) else '<end>'}\n" \
                     f"          now {gl[n] if n < len(gl) else '<end>'}"
        check(f"{key}: the same {part} as before #1147", w.get(part) == g.get(part), detail)

print()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls)
if _calls:
    print("".join(f"        {line}\n" for line in _calls.splitlines()), end="")

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All two-cluster switch checks passed.")
