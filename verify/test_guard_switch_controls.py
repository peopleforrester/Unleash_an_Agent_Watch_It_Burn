# ABOUTME: Offline gate for #1349: guard-output, guard-budget and guard-topic switch both KubeCon clusters through _both,
# ABOUTME: and every stage switch ends with _controls, guard-proxy's /controls read back on each cluster by name.
"""#1349, the first piece of #1346. guard-output-on/off, guard-budget-on/off and guard-topic-on/off used to call _px,
which reaches this cluster only, while the room plays on the public bot. They now run `_both _toggle <query>` (output,
budget) and `_both _topic on|off` (topic) from ~/.guardlib (gitops/ai-layer/web-terminal/entrypoint.sh), as
guard-input-on does: here the kubectl exec into deploy/guard-proxy, on the other KubeCon cluster a GET through the API
server's Service proxy on guard-proxy:8080. And every stage switch now ends with _controls: guard-proxy's /controls on
this cluster and on the peer, printed one cluster to a block by name.

Checked here, with a kubectl on PATH that plays two clusters, each with a guard-proxy that keeps its guard state:
  * linked: each of the six switches sets its guard on both clusters, says so naming the peer, then reads /controls on
    this cluster and the peer, last, and prints each by name with that guard ON or off; every printed `$ ` line, run
    by bash, makes the call it made;
  * WIB_CLUSTER_NAME names this cluster in the read, and the web-terminal Deployment takes it from cluster-identity;
  * no guardrails-peer Secret (the 2-hour lab's): the switch acts here alone and reads this cluster alone, exit 0;
  * the peer cannot be reached: this cluster switches, the run fails naming the peer, and the read says the peer's
    /controls could not be read rather than guessing it;
  * a guard-proxy without the topic stage: guard-topic-on fails naming that cluster, guard-topic-off passes saying it
    already chats about anything;
  * a control guard-proxy could not measure (null) reads "not measured", never off;
  * after a Kubernetes write the read waits out guard-proxy's 5 s cache of those controls; after a guard-proxy toggle
    alone it does not wait;
  * every stage switch the issue lists ends with _controls and then exits with its own code;
  * what the read asks of the peer is inside guardrails-switch's grant;
  * images/web-terminal/entrypoint.sh is byte-identical.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import no_cloud  # noqa: E402
no_cloud.setup()

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
TWIN = REPO / "images/web-terminal/entrypoint.sh"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
SWITCH = REPO / "gitops/guardrails-switch/guardrails-switch.yaml"
PEER = "watch-it-burn-community"
HERE = "watch-it-burn-private"
TOGGLE_PATH = "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/toggle"
CONTROLS_PATH = "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/controls"
STEP_SECONDS = 300
NOW = 1762300800
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


# A kubectl that plays two clusters. A call with --kubeconfig is the peer, named by its --context; any other is this
# cluster. Each cluster's guard-proxy keeps its guards in STATE: a /toggle sets them as proxy.py's do_GET does and
# answers them, a /controls answers {ai, infra, host}. MODE picks the case; in no-topic, neither guard-proxy has the
# topic stage, so it ignores the key and never reports it.
FAKE = r'''#!/usr/bin/env python3
import base64, json, os, sys
from urllib.parse import parse_qs, urlparse
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
    if mode == "unlinked":
        if "--ignore-not-found" in a:
            sys.exit(0)
        sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
    if "--ignore-not-found" in a:
        print("secret/guardrails-peer"); sys.exit(0)
    print(base64.b64encode(b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in a[-1] else b"watch-it-burn-community").decode())
    sys.exit(0)
if mode == "peer-down" and ctx != "this":
    sys.stderr.write("Unable to connect to the server: net/http: request canceled (Client.Timeout exceeded)\n"); sys.exit(1)
g = state.setdefault(ctx, {"output": False, "input_blocklist": False, "input_classifier": False, "budget": False})
if mode != "no-topic":
    g.setdefault("topic", False)
if "apply" in a:
    state.setdefault("applied", []).append([ctx, os.path.basename(a[-1])])
    print("role.rbac.authorization.k8s.io/workshop-agent configured")
else:
    path = None
    if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"]:
        code = a[a.index("-c") + 1]
        path = code.split("http://localhost:8080", 1)[1].split("'", 1)[0]
    elif a[:2] == ["get", "--raw"] and a[2].startswith("/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/"):
        path = "/" + a[2].split("/proxy/", 1)[1]
    if path is None:
        sys.stderr.write("fake kubectl: unexpected call " + json.dumps(a) + "\n"); sys.exit(1)
    u = urlparse(path)
    if u.path == "/toggle":
        q = parse_qs(u.query)
        for k in ("output", "input_blocklist", "input_classifier", "budget", "topic"):
            if k in q and k in g:
                g[k] = q[k][0].lower() == "on"
        answer = {**g, "cost_cap_usd": 25.0}
        if "-c" in a and ".get('" in a[a.index("-c") + 1]:
            key = a[a.index("-c") + 1].split(".get('", 1)[1].split("'", 1)[0]
            print(answer.get(key, "missing"))
        else:
            print(json.dumps(answer))
    elif u.path == "/controls":
        print(json.dumps({"ai": g, "infra": {"networkpolicy": True, "kyverno": False, "kubearmor": None},
                          "always_on": {"code_of_conduct": True},
                          "host": "attackme.example" if ctx != "this" else "burritobot-private.example"}))
    else:
        sys.stderr.write("fake kubectl: unexpected path " + path + "\n"); sys.exit(1)
json.dump(state, open(os.environ["STATE"], "w"))
'''
# A clock that stands still, and a sleep that records how long it was asked to wait and returns at once.
FAKE_DATE = f"#!/usr/bin/env bash\necho {NOW}\n"
FAKE_SLEEP = '#!/usr/bin/env bash\necho "$1" >> "$SLEPT"\n'

text = ENTRYPOINT.read_text(encoding="utf-8")
helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', text, re.S))
CHALLENGES = next(d for d in docs(RESOURCES.read_text(encoding="utf-8")) if d.get("kind") == "ConfigMap"
                  and d["metadata"]["name"] == "challenge-fixes")["data"]


def timed(argv: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=STEP_SECONDS, **kw)
    except subprocess.TimeoutExpired:
        sys.exit(f"FAILED: {' '.join(argv)[:200]} ran past {STEP_SECONDS} seconds")


def run(cmd: str, mode: str, cluster_name: str | None = HERE) -> dict:
    """Run one terminal command against the fake: its exit code, output, the calls it made, the calls its printed `$ `
    lines make when bash runs them again, each cluster's guards afterwards, and each sleep it asked for."""
    with tempfile.TemporaryDirectory() as tmp:
        home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        home.mkdir(); fakebin.mkdir(); (home / "challenges").mkdir()  # noqa: E702
        for name, body in CHALLENGES.items():
            (home / "challenges" / name).write_text(body)
        for name, body in helpers.items():
            (home / name).write_text(body + "\n")
        for tool, body in (("kubectl", FAKE), ("date", FAKE_DATE), ("sleep", FAKE_SLEEP)):
            (fakebin / tool).write_text(body)
            (fakebin / tool).chmod(0o755)
        calls, state, slept = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "state"), pathlib.Path(tmp, "slept")
        state.write_text("{}")
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls),
               "STATE": str(state), "MODE": mode, "SLEPT": str(slept)}
        env.pop("WIB_CLUSTER_NAME", None)
        if cluster_name is not None:
            env["WIB_CLUSTER_NAME"] = cluster_name
        r = timed(["bash", str(home / cmd)], env=env)
        ran = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        shown = [line[2:] for line in (r.stdout + r.stderr).splitlines() if line.startswith("$ ")]
        replay = pathlib.Path(tmp, "replay")
        pathlib.Path(tmp, "state2").write_text("{}")
        renv = {**env, "CALLS": str(replay), "STATE": str(pathlib.Path(tmp, "state2"))}
        for line in shown:
            timed(["bash", "-c", line], env=renv)
        replayed = [json.loads(line) for line in replay.read_text().splitlines()] if replay.exists() else []
        h = str(home)
        norm = lambda s: s.replace(h, "$HOME")  # noqa: E731
        return {"rc": r.returncode, "stdout": norm(r.stdout), "stderr": norm(r.stderr),
                "calls": [{"cluster": c["cluster"], "args": [norm(x) for x in c["args"]]} for c in ran],
                "replayed": [{"cluster": c["cluster"], "args": [norm(x) for x in c["args"]]} for c in replayed],
                "state": json.loads(state.read_text()),
                "slept": slept.read_text().split() if slept.exists() else []}


def kind(c: dict) -> str:
    """What one call is: toggle or controls (by exec here, by the Service proxy on the peer), or other."""
    a = c["args"]
    if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"]:
        code = a[a.index("-c") + 1]
        return "toggle" if "/toggle?" in code else "controls" if "/controls'" in code else "other"
    if a[:2] == ["get", "--raw"]:
        return "toggle" if a[2].startswith(TOGGLE_PATH + "?") else "controls" if a[2] == CONTROLS_PATH else "other"
    return "other"


def block(out: str, header: str) -> str:
    """The lines _controls printed for one cluster: its header line and the indented lines after it."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("  " + header):
            rest = [line]
            for nxt in lines[i + 1:]:
                if not nxt.startswith("    "):
                    break
                rest.append(nxt)
            return "\n".join(rest)
    return ""


# The three switches, the query each sends, the guard key it sets, the value it leaves, and its explanation.
SWITCHES = {
    "guard-output-on": ("output=on", "output", True, "OUTPUT guard ON"),
    "guard-output-off": ("output=off", "output", False, "OUTPUT guard OFF"),
    "guard-budget-on": ("budget=on", "budget", True, "BUDGET guard ON"),
    "guard-budget-off": ("budget=off", "budget", False, "Budget limits are now removed"),
    "guard-topic-on": ("topic=on", "topic", True, "On-topic guard ON"),
    "guard-topic-off": ("topic=off", "topic", False, "On-topic guard OFF"),
}
LABEL = {"output": "output", "budget": "budget cap", "topic": "on-topic"}

print("== the three switches go through _both, from the entrypoint the KubeCon terminals run ==")
lib = helpers.get(".guardlib", "")
check(".guardlib defines _both, _toggle, _topic and _controls",
      all(re.search(rf"^{f}\(\) \{{", lib, re.M) for f in ("_both", "_toggle", "_topic", "_controls")))
for cmd, (q, key, _, _) in SWITCHES.items():
    body = helpers.get(cmd, "")
    step = f'_both _topic {q.split("=")[1]}' if key == "topic" else f'_both _toggle "{q}"'
    check(f"{cmd} switches through {step}, and runs no kubectl, _px or _pxkey of its own",
          step in body and not re.search(r"\bkubectl\b|\b_px\b|\b_pxkey\b", body), body)
check("images/web-terminal/entrypoint.sh is kept byte-identical to it", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

print("== every stage switch ends with the /controls read, then exits with its own code ==")
STAGES = ("guardrails-on", "guardrails-off", "guard-agency-on", "guard-agency-off", "guard-input-on", "guard-input-off",
          "guard-mcp-on", "guard-mcp-off", "guard-output-on", "guard-output-off", "guard-budget-on", "guard-budget-off",
          "guard-topic-on", "guard-topic-off", "guards-on", "guards-off")
for cmd in STAGES:
    lines = [ln.strip() for ln in helpers.get(cmd, "").splitlines() if ln.strip()]
    check(f"{cmd} ends with _controls, then exit \"$rc\"",
          len(lines) >= 2 and lines[-1] == 'exit "$rc"' and lines[-2].endswith("_controls"), str(lines[-3:]))
    early = [ln for ln in lines[:-1] if re.search(r"\bexit [0-9]", ln) and "Usage:" not in ln]
    check(f"{cmd} has no exit before it other than a usage error, so the read always runs", not early, str(early))

print("== on two linked clusters ==")
for cmd, (q, key, val, explains) in SWITCHES.items():
    r = run(cmd, "linked")
    out = r["stdout"] + r["stderr"]
    kinds = [(c["cluster"], kind(c)) for c in r["calls"] if kind(c) != "other"]
    check(f"{cmd}: exits 0", r["rc"] == 0, out)
    check(f"{cmd}: toggles this cluster, then {PEER}, then reads /controls on this cluster, then on {PEER}, last",
          kinds == [("this", "toggle"), (PEER, "toggle"), ("this", "controls"), (PEER, "controls")]
          and [kind(c) for c in r["calls"][-2:]] == ["controls", "controls"], str(kinds))
    peer_toggle = next((c["args"] for c in r["calls"] if c["cluster"] == PEER and kind(c) == "toggle"), [])
    check(f"{cmd}: the peer's call is get --raw {TOGGLE_PATH}?{q}, bounded at 20 seconds",
          peer_toggle == ["get", "--raw", f"{TOGGLE_PATH}?{q}", "--request-timeout=20s"], str(peer_toggle))
    check(f"{cmd}: {key} is {'on' if val else 'off'} on both clusters, and no other guard moved",
          all(r["state"].get(c, {}).get(key) is val and all(v is False for k, v in r["state"][c].items() if k != key)
              for c in ("this", PEER)), str(r["state"]))
    check(f"{cmd}: says it switched both clusters, naming {PEER}",
          f"Switched on both clusters: this one and {PEER}." in r["stdout"], r["stdout"])
    check(f"{cmd}: still explains what it did", explains in r["stdout"], r["stdout"])
    here_b, peer_b = block(r["stdout"], f"{HERE} (this cluster)"), block(r["stdout"], PEER)
    word = "ON" if val else "off"
    for name, b in ((f"{HERE} (this cluster)", here_b), (PEER, peer_b)):
        ai = next((ln for ln in b.splitlines() if "AI guards" in ln), "")
        part = ai.split("ON: ", 1)[-1].split("   off: ", 1)
        has = part[0] if val else (part[1] if len(part) > 1 else "")
        check(f"{cmd}: the read names {name} and shows {LABEL[key]} {word} there",
              bool(b) and LABEL[key] in [x.strip() for x in has.split(",")], b or r["stdout"])
    so = r["stdout"]
    check(f"{cmd}: the read follows the switch's own lines", "Read back from guard-proxy's /controls" in so
          and so.index("Read back from guard-proxy's /controls") > so.index(explains), so)
    check(f"{cmd}: a guard-proxy toggle alone does not wait out the Kubernetes cache", not r["slept"]
          and "Waiting out" not in r["stdout"], str(r["slept"]))
    check(f"{cmd}: every line it prints, run by bash, makes the call it made, in order",
          r["replayed"] == r["calls"] and len(r["calls"]) == 6, f"\n    shown: {r['replayed']}\n    ran:   {r['calls']}")
    others = [c for c in r["calls"] if c["cluster"] not in ("this", PEER)]
    check(f"{cmd}: touches no cluster but these two", not others, str(others))

print("== the read names each cluster ==")
r = run("guard-output-on", "linked", cluster_name=None)
check("without WIB_CLUSTER_NAME this cluster reads as This cluster, beside its host",
      block(r["stdout"], "This cluster, burritobot-private.example") != "", r["stdout"])
r = run("guard-output-on", "linked")
check(f"with it, {HERE} (this cluster) and {PEER}, each beside the host its guard-proxy reports",
      block(r["stdout"], f"{HERE} (this cluster), burritobot-private.example") != ""
      and block(r["stdout"], f"{PEER}, attackme.example") != "", r["stdout"])
check("a control guard-proxy could not measure reads not measured, never off",
      "off: Kyverno   not measured: KubeArmor" in r["stdout"], r["stdout"])
term = next(d for d in docs(RESOURCES.read_text(encoding="utf-8")) if d.get("kind") == "Deployment"
            and d["metadata"]["name"] == "web-terminal")
env = {e["name"]: e for c in term["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
check("the web-terminal Deployment takes WIB_CLUSTER_NAME from cluster-identity's cluster-name, optional",
      env.get("WIB_CLUSTER_NAME", {}).get("valueFrom") == {"configMapKeyRef": {"name": "cluster-identity",
                                                                               "key": "cluster-name",
                                                                               "optional": True}},
      str(env.get("WIB_CLUSTER_NAME")))
check("infra/datadog-cluster-identity.sh writes cluster-name into cluster-identity",
      "--from-literal=cluster-name=" in (REPO / "infra/datadog-cluster-identity.sh").read_text(encoding="utf-8"))

print("== a cluster with no guardrails-peer Secret, the 2-hour lab's ==")
for cmd, (q, key, val, explains) in SWITCHES.items():
    r = run(cmd, "unlinked")
    kinds = [(c["cluster"], kind(c)) for c in r["calls"] if kind(c) != "other"]
    check(f"{cmd}: switches here alone, reads here alone, and exits 0",
          r["rc"] == 0 and kinds == [("this", "toggle"), ("this", "controls")]
          and r["state"].get("this", {}).get(key) is val and PEER not in r["state"], f"{kinds} {r['stdout']}")
    check(f"{cmd}: says in one line that this cluster was switched alone, and still explains",
          "Switched on this cluster alone" in r["stdout"] and explains in r["stdout"], r["stdout"])
    check(f"{cmd}: the read shows this cluster and no other", block(r["stdout"], f"{HERE} (this cluster)") != ""
          and PEER not in r["stdout"], r["stdout"])

print("== the peer cannot be reached ==")
for cmd, (q, key, val, explains) in SWITCHES.items():
    r = run(cmd, "peer-down")
    check(f"{cmd}: still switches this cluster", r["state"].get("this", {}).get(key) is val, str(r["state"]))
    check(f"{cmd}: fails, naming {PEER}, without the explanation, saying to try again",
          r["rc"] == 1 and f"not on {PEER}: it could not be reached, or it refused the change." in r["stdout"]
          and explains not in r["stdout"] and f"try '{cmd}' again" in r["stdout"], r["stdout"])
    check(f"{cmd}: the read shows this cluster and says {PEER}'s /controls could not be read, guessing nothing",
          block(r["stdout"], f"{HERE} (this cluster)") != ""
          and f"⚠️  {PEER}: /controls could not be read, so its state is not shown." in r["stdout"], r["stdout"])

print("== a guard-proxy without the topic stage ==")
r = run("guard-topic-on", "no-topic")
check("guard-topic-on fails, naming each cluster whose guard-proxy has no on-topic guard, never a confident ON",
      r["rc"] == 1 and "This cluster: its guard-proxy has no on-topic guard, so nothing changed there." in r["stdout"]
      and f"{PEER}: its guard-proxy has no on-topic guard, so nothing changed there." in r["stdout"]
      and "On-topic guard ON" not in r["stdout"], r["stdout"])
r = run("guard-topic-off", "no-topic")
check("guard-topic-off passes, saying each cluster already chats about anything",
      r["rc"] == 0 and "This cluster: its guard-proxy has no on-topic guard, so BurritoBot there already chats" in r["stdout"]
      and f"{PEER}: its guard-proxy has no on-topic guard" in r["stdout"], r["stdout"])

print("== after a Kubernetes write, the read waits out guard-proxy's 5 s cache ==")
r = run("guard-agency-on", "linked")
kinds = [(c["cluster"], kind(c)) for c in r["calls"] if kind(c) != "other"]
check("guard-agency-on applies on both clusters, then reads /controls on both, and exits 0",
      r["rc"] == 0 and kinds == [("this", "controls"), (PEER, "controls")]
      and [x[0] for x in r["state"].get("applied", [])] == ["this", PEER], f"{kinds} {r['stdout']}")
check("it waits 6 s from its write before the read, and says why", r["slept"] == ["6"]
      and r["stdout"].index("Waiting out guard-proxy's 5-second cache") < r["stdout"].index("Read back"),
      f"{r['slept']} {r['stdout']}")

print("== what the read asks of the peer is inside its guardrails-switch grant ==")
GRANT: dict[tuple[str, str, str], set[str]] = {}
for d in docs(SWITCH.read_text(encoding="utf-8")):
    if d["kind"] in ("Role", "ClusterRole"):
        scope = d["metadata"].get("namespace", "")
        for rule in d["rules"]:
            for res in rule["resources"]:
                for name in rule.get("resourceNames") or ["*"]:
                    GRANT.setdefault((scope, res, name), set()).update(rule["verbs"])
for cmd in SWITCHES:
    r = run(cmd, "linked")
    asked = set()
    for c in r["calls"]:
        if c["cluster"] != PEER:
            continue
        a = c["args"]
        if a[:2] != ["get", "--raw"]:
            asked.add(("?", " ".join(a[:3]), "?", "?"))
            continue
        ns, res, name, sub, *_ = urlparse(a[2]).path.strip("/").split("/")[3:]
        asked.add((ns, f"{res}/{sub}", name, "get"))
    missing = sorted(n for n in asked if n[3] not in GRANT.get(n[:3], set()))
    check(f"{cmd}: everything it asks of {PEER}, the toggle and the read, is get on services/proxy guard-proxy:8080",
          asked == {("agent", "services/proxy", "guard-proxy:8080", "get")} and not missing, f"{asked} {missing}")
    q = parse_qs(urlparse(next(c["args"][2] for c in r["calls"] if c["cluster"] == PEER and kind(c) == "toggle")).query)
    check(f"{cmd}: the peer's /toggle sets {SWITCHES[cmd][1]} and no other guard", sorted(q) == [SWITCHES[cmd][1]],
          str(q))

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
print("All guard-switch /controls checks passed.")
