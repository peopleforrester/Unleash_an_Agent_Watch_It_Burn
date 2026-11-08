# ABOUTME: Offline gate for #1149: guard-mcp-on and guard-mcp-off switch Challenge 4's MCP rule on this cluster and the
# ABOUTME: linked KubeCon peer, each through its own control, and guard-mcp-on times how long each took to serve it.
"""#1149, part of #1132. The room plays on the public bot, so guard-mcp-on, run from the private terminal, has to reach
the community cluster too. guard-mcp-on and guard-mcp-off now run _mcp through _both (gitops/ai-layer/web-terminal/
entrypoint.sh): here with kubectl, then on the other KubeCon cluster through the guardrails-peer kubeconfig. _mcp asks
_c7gw which control that cluster uses, agentgateway's rule (kubecon-private, admin) or the Agent's evil-mcp toolNames
(kubecon-community and everything else), and switches that one. guard-mcp-on then waits, bounded, until each cluster
serves the change and prints how long that took.

Checked here, with a kubectl on PATH that plays two clusters, each with its own Argo CD profile label:
  * private here and community the peer, and the reverse: each cluster switched by its own control, the other control
    left as it was, one line per cluster naming the control, the line _both prints, and every printed `$ ` line, run by
    bash, makes the call that ran;
  * the timing line for each cluster: the gateway's reload (agentgateway-c7 logs `loaded config from`) and kagent's roll
    of workshop-agent; when neither comes, the line names the cluster and the bound, and the run fails;
  * a write that changed nothing says there is nothing to reload, and waits for nothing;
  * a cluster with no guardrails-peer Secret (the 2-hour workshop's): switched alone, timed, exit 0;
  * a peer that cannot be reached: this cluster switched and timed, the peer named, exit 1;
  * the grant in gitops/guardrails-switch/mcp-switch.yaml is exactly what those calls ask of the peer, by resourceName
    everywhere but pods and pods/log, whose names RBAC cannot know, and the pod patch is held by an admission policy
    to the one annotation; block-argocd-drift lets that identity UPDATE agentgateway-c7-config and nothing else.

The clock is the test's own (#1180, run 18742). guard-mcp-on's wait reads `date +%s` against each write's t0, so on
the real clock a 2 s bound ran out before the first read whenever the two writes and the peer's calls took 2 s, as on a
loaded gate host, and "it read again, every 2 s" saw 1 read. A fake `date` answers `+%s` from a file and passes every
other form to the real one, and a fake `sleep` moves that file on without waiting, so time passes only when the script
sleeps.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
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
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
MCP_SWITCH = REPO / "gitops/guardrails-switch/mcp-switch.yaml"
SWITCH_DIR = REPO / "gitops/guardrails-switch"
SWITCH_APP = REPO / "gitops/bootstrap/apps/guardrails-switch.yaml"
DRIFT = REPO / "policies/kyverno/block-argocd-drift.yaml"
BOOT = REPO / "gitops/bootstrap"
SA = "system:serviceaccount:guardrails-switch:guardrails-switch"
PRIVATE, COMMUNITY = "watch-it-burn-private", "watch-it-burn-community"
ALL = ["get_weather", "read_internal_config", "apply_optimization"]
ON_RULE = 'mcp.tool.name == "get_weather"'
TOUCH = "wib.agenticburn.com/c7-rule-at"
STEP_SECONDS = 300
REAL_DATE = shutil.which("date")
if not REAL_DATE:
    sys.exit("FAILED: no date on PATH, which the fake clock passes its other forms to")
# date +%s reads the clock file; any other form (the --since-time stamp of a given second) is the real date's.
FAKE_DATE = f'''#!/usr/bin/env bash
if [ "$#" -eq 1 ] && [ "$1" = +%s ]; then cat "$CLOCK"; exit 0; fi
exec {REAL_DATE} "$@"
'''
# sleep N moves the clock N seconds on and returns at once.
FAKE_SLEEP = '''#!/usr/bin/env bash
case "$1" in ''|*[!0-9]*) echo "fake sleep: whole seconds only, got '$1'" >&2; exit 1 ;; esac
echo $(( $(cat "$CLOCK") + $1 )) >"$CLOCK"
'''
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


COMMITTED = next(d for d in docs(GATEWAY) if d.get("kind") == "ConfigMap"
                 and d["metadata"]["name"] == "agentgateway-c7-config")["data"]["config.yaml"]
if "'true' # c7-rule" not in COMMITTED:
    sys.exit(f"FAILED: {GATEWAY.relative_to(REPO)} has no line \"'true' # c7-rule\"; the cases below start from it")
NARROWED = COMMITTED.replace("'true' # c7-rule", f"'{ON_RULE}' # c7-rule")

# A kubectl that plays two clusters. A call with --kubeconfig is the peer, named by its --context; any other is this
# cluster. Each cluster has its Argo CD profile label, its agentgateway-c7-config, its Agent and the workshop-agent
# Deployment kagent rolls. MODE: linked, unlinked (no peer Secret), peer-down (the peer's API cannot be reached),
# stuck (the gateway never logs a reload and kagent never finishes the roll). PEER names the peer the Secret carries.
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
def save():
    json.dump(state, open(os.environ["STATE"], "w"))
def apply(doc, ops):
    for op in ops:
        parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].split("/")[1:]]
        node = doc
        for p in parts[:-1]:
            node = node[int(p)] if isinstance(node, list) else node[p]
        last = int(parts[-1]) if isinstance(node, list) else parts[-1]
        if op["op"] == "test" and node[last] != op["value"]:
            sys.stderr.write("The request is invalid: the server rejected our request\n"); sys.exit(1)
        if op["op"] == "replace":
            node[last] = op["value"]
if "guardrails-peer" in a:
    if mode == "unlinked":
        if "--ignore-not-found" in a:
            sys.exit(0)
        sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
    if "--ignore-not-found" in a:
        print("secret/guardrails-peer"); sys.exit(0)
    val = b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in a[-1] else os.environ["PEER"].encode()
    print(base64.b64encode(val).decode()); sys.exit(0)
if mode == "peer-down" and ctx != "this":
    sys.stderr.write("Unable to connect to the server\n"); sys.exit(1)
c = state[ctx]
if "application" in a:
    sys.stdout.write(c["profile"])
elif "get" in a and "configmap" in a:
    print(json.dumps({"metadata": {"name": "agentgateway-c7-config", "resourceVersion": str(c["rv"])},
                      "data": {"config.yaml": c["config"]}}))
elif "patch" in a and "configmap" in a:
    doc = {"metadata": {"resourceVersion": str(c["rv"])}, "data": {"config.yaml": c["config"]}}
    apply(doc, json.loads(a[a.index("-p") + 1]))
    if doc["data"]["config.yaml"] == c["config"]:
        print("configmap/agentgateway-c7-config patched (no change)")
    else:
        c["config"] = doc["data"]["config.yaml"]; c["rv"] += 1; c["reload"] = True
        print("configmap/agentgateway-c7-config patched")
elif "annotate" in a:
    c["touched"] += 1
    print("pod/agentgateway-6d9f7c8b5-x2x4q annotated")
elif "logs" in a:
    if c.get("reload") and mode != "stuck":
        print('2026-11-08T05:35:31.361287Z\tinfo\tstate_manager\tloaded config from File("/etc/agentgateway-c7/config.yaml")')
elif "get" in a and "deployment" in a:
    g = c["gen"]
    if a[-1] == "jsonpath={.metadata.generation}":
        sys.stdout.write(str(g))
    else:
        sys.stdout.write(f"{g} {g} 2 1 1" if mode == "stuck" else f"{g} {g} 1 1 1")
elif "get" in a and "agent" in a:
    print(json.dumps(c["agent"]))
elif "patch" in a and "agent" in a:
    before = json.dumps(c["agent"])
    apply(c["agent"], json.loads(a[a.index("-p") + 1]))
    if json.dumps(c["agent"]) == before:
        print("agent.kagent.dev/workshop-agent patched (no change)")
    else:
        c["gen"] += 1
        print("agent.kagent.dev/workshop-agent patched")
else:
    sys.stderr.write("fake kubectl: unexpected call\n"); sys.exit(1)
save()
'''

helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT.read_text(encoding="utf-8"), re.S))


def agent(evil: list[str]) -> dict:
    return {"metadata": {"name": "workshop-agent"}, "spec": {"declarative": {"tools": [
        {"type": "McpServer", "mcpServer": {"name": "workshop-mcp", "toolNames": ["run_shell"]}},
        {"type": "McpServer", "mcpServer": {"name": "evil-mcp", "toolNames": list(evil)}}]}}}


def cluster(profile: str, config: str = COMMITTED, evil: list[str] = ALL) -> dict:
    return {"profile": profile, "config": config, "rv": 7, "agent": agent(evil), "gen": 3, "touched": 0}


def switched_on(profile: str) -> dict:
    """A cluster as guard-mcp-on leaves it: the gateway rule narrowed where it is the control, else the short list."""
    if profile in ("admin", "kubecon-private"):
        return cluster(profile, NARROWED)
    return cluster(profile, evil=["get_weather"])


def evil_of(c: dict) -> list[str]:
    return next(t["mcpServer"]["toolNames"] for t in c["agent"]["spec"]["declarative"]["tools"]
                if t["mcpServer"]["name"] == "evil-mcp")


def timed(argv: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=STEP_SECONDS, **kw)
    except subprocess.TimeoutExpired:
        sys.exit(f"FAILED: {' '.join(argv)[:200]} ran past {STEP_SECONDS} seconds")


def run(cmd: str, mode: str, here: dict, peer_name: str, peer: dict, args: tuple[str, ...] = ()) -> dict:
    """One terminal command against the fake. Returns its exit code, output, the calls, the calls its printed `$ ` lines
    make when bash runs them again (against a copy of the starting state), and both clusters' state after."""
    with tempfile.TemporaryDirectory() as tmp:
        home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        home.mkdir(); fakebin.mkdir()  # noqa: E702
        for name, body in helpers.items():
            (home / name).write_text(body + "\n")
        for tool, body in (("kubectl", FAKE), ("date", FAKE_DATE), ("sleep", FAKE_SLEEP)):
            (fakebin / tool).write_text(body)
            (fakebin / tool).chmod(0o755)
        clock = pathlib.Path(tmp, "clock")
        clock.write_text("1762580131\n")
        start = json.dumps({"this": here, peer_name: peer})
        calls, state = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "state")
        state.write_text(start)
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls),
               "STATE": str(state), "MODE": mode, "PEER": peer_name, "CLOCK": str(clock)}
        r = timed(["bash", str(home / cmd), *args], env=env)
        ran = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        shown = [line[2:] for line in (r.stdout + r.stderr).splitlines() if line.startswith("$ ")]
        replay, state2 = pathlib.Path(tmp, "replay"), pathlib.Path(tmp, "state2")
        state2.write_text(start)
        renv = {**env, "CALLS": str(replay), "STATE": str(state2)}
        for line in shown:
            timed(["bash", "-c", line], env=renv)
        replayed = [json.loads(line) for line in replay.read_text().splitlines()] if replay.exists() else []
        h = str(home)
        norm = lambda s: s.replace(h, "$HOME")  # noqa: E731
        # The annotate stamps the time; the replay runs a second later, so the stamp is compared as a stamp.
        unstamp = lambda s: re.sub(rf"^{re.escape(TOUCH)}=[0-9]+$", f"{TOUCH}=<now>", norm(s))  # noqa: E731
        return {"rc": r.returncode, "out": norm(r.stdout + r.stderr), "stdout": norm(r.stdout),
                "calls": [{"cluster": c["cluster"], "args": [unstamp(x) for x in c["args"]]} for c in ran],
                "replayed": [{"cluster": c["cluster"], "args": [unstamp(x) for x in c["args"]]} for c in replayed],
                "state": json.loads(state.read_text())}


def on_cluster(r: dict, name: str, *words: str) -> list[list[str]]:
    return [c["args"] for c in r["calls"] if c["cluster"] == name and all(w in c["args"] for w in words)]


def need(c: dict) -> set[tuple[str, str, str, str]]:
    """The RBAC requests one kubectl call makes: (namespace, resource, name or *, verb). kubectl annotate and kubectl
    logs with -l list the pods, then patch each one or read each one's log."""
    a = c["args"]
    ns = a[a.index("-n") + 1] if "-n" in a else ""
    if "guardrails-peer" in a:
        return set()  # read on this cluster, never on the peer
    if "annotate" in a:
        return {(ns, "pods", "*", "list"), (ns, "pods", "*", "patch")}
    if "logs" in a:
        return {(ns, "pods", "*", "list"), (ns, "pods/log", "*", "get")}
    i = next(i for i, x in enumerate(a) if x in ("get", "patch"))
    res = {"application": "applications", "configmap": "configmaps", "agent": "agents",
           "deployment": "deployments"}[a[i + 1]]
    return {(ns, res, a[i + 2], a[i])}


gw_line = lambda who: re.compile(  # noqa: E731
    rf"^⏱  {re.escape(who)}: the gateway served the new rule [0-9]+ s after the write \(agentgateway-c7 logged", re.M)
roll_line = lambda who: re.compile(  # noqa: E731
    rf"^⏱  {re.escape(who)}: kagent rolled workshop-agent with the new allow-list [0-9]+ s after the write\.$", re.M)

print("== the two commands go through _both and _mcp, and C7's profiles pick the controls the issue names ==")
lib = helpers.get(".guardlib", "")
for cmd, st in (("guard-mcp-on", "on"), ("guard-mcp-off", "off")):
    body = helpers.get(cmd, "")
    check(f"{cmd} runs _mcp {st} through _both, and no kubectl of its own",
          f"_both _mcp {st}" in body and "kubectl" not in body, body[:300])
check("guard-mcp-on waits with _c7wait, bounded by its argument, 180 s unless given",
      '_c7wait "$bound"' in helpers.get("guard-mcp-on", "") and 'bound="${1:-180}"' in helpers.get("guard-mcp-on", ""))
check("guard-mcp-off waits for nothing", "_c7wait" not in helpers.get("guard-mcp-off", ""))
check("_c7gw picks the gateway on the admin and kubecon-private labels only",
      '[ "$r" = admin ] || [ "$r" = kubecon-private ]' in lib)
vals = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in BOOT.glob("values*.yaml")}
check("values-kubecon-private.yaml selects c7Control: gateway",
      vals["values-kubecon-private"].get("c7Control") == "gateway")
check("values-kubecon-community.yaml sets no c7Control, so the community cluster takes values.yaml's toolnames",
      "c7Control" not in vals["values-kubecon-community"] and vals["values"].get("c7Control") == "toolnames")
check("images/web-terminal/entrypoint.sh is kept byte-identical", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

LINKED = (("private here, community the peer", "kubecon-private", COMMUNITY, "kubecon-community"),
          ("community here, private the peer", "kubecon-community", PRIVATE, "kubecon-private"))
for label, here_p, peer_name, peer_p in LINKED:
    gw_who, tn_who = ("This cluster", peer_name) if here_p == "kubecon-private" else (peer_name, "This cluster")
    gw_key, tn_key = ("this", peer_name) if here_p == "kubecon-private" else (peer_name, "this")
    print(f"== guard-mcp-on, {label} ==")
    r = run("guard-mcp-on", "linked", cluster(here_p), peer_name, cluster(peer_p))
    st, out = r["state"], r["stdout"]
    check(f"{label}: exits 0", r["rc"] == 0, r["out"])
    check(f"{label}: the private cluster's gateway rule is narrowed to get_weather, and only that line changed",
          st[gw_key]["config"] == NARROWED, st[gw_key]["config"][-200:])
    check(f"{label}: the private cluster's allow-list is left full, so the gateway is what stops the call",
          evil_of(st[gw_key]) == ALL, str(evil_of(st[gw_key])))
    check(f"{label}: the gateway pod is touched on the private cluster alone", st[gw_key]["touched"] == 1
          and st[tn_key]["touched"] == 0, str((st[gw_key]["touched"], st[tn_key]["touched"])))
    check(f"{label}: the community cluster's allow-list is get_weather alone", evil_of(st[tn_key]) == ["get_weather"],
          str(evil_of(st[tn_key])))
    check(f"{label}: the community cluster's gateway rule is never read or written",
          not [c for c in r["calls"] if c["cluster"] == tn_key and "configmap" in c["args"]]
          and st[tn_key]["config"] == COMMITTED)
    check(f"{label}: one line per cluster names the control it used",
          f"🛡️  {gw_who}: ON, at the gateway." in out and f"🛡️  {tn_who}: ON, in the agent's allow-list." in out, out)
    check(f"{label}: says it switched both clusters, naming {peer_name}",
          f"Switched on both clusters: this one and {peer_name}." in out, out)
    check(f"{label}: times the gateway's reload on the private cluster", gw_line(gw_who).search(out) is not None, out)
    check(f"{label}: times kagent's roll on the community cluster", roll_line(tn_who).search(out) is not None, out)
    check(f"{label}: then explains this cluster's control",
          ("MCP tool authorization ON, at the gateway" if here_p == "kubecon-private"
           else "removed from the agent's allow-list") in out, out)
    check(f"{label}: every line it prints, run by bash, makes the call it made, in order",
          r["replayed"] == r["calls"], f"\n    shown: {r['replayed']}\n    ran:   {r['calls']}")
    check(f"{label}: touches no cluster but these two", {c["cluster"] for c in r["calls"]} == {"this", peer_name})
    wait = on_cluster(r, gw_key, "logs")
    check(f"{label}: the reload is read from agentgateway-c7's log since the write, every line of it",
          len(wait) == 1 and "-c" in wait[0] and wait[0][wait[0].index("-c") + 1] == "agentgateway-c7"
          and any(x.startswith("--since-time=") for x in wait[0]) and "--tail=-1" in wait[0], str(wait))
    check(f"{label}: the toolNames write reads the Deployment's generation before it, to tell kagent's roll",
          on_cluster(r, tn_key, "deployment") and r["calls"].index(
              next(c for c in r["calls"] if c["cluster"] == tn_key and "deployment" in c["args"]))
          < r["calls"].index(next(c for c in r["calls"] if c["cluster"] == tn_key and "patch" in c["args"])))

    print(f"== guard-mcp-off, {label} ==")
    r = run("guard-mcp-off", "linked", switched_on(here_p), peer_name, switched_on(peer_p))
    st, out = r["state"], r["stdout"]
    check(f"{label}: guard-mcp-off exits 0", r["rc"] == 0, r["out"])
    check(f"{label}: the private cluster's rule is 'true' again, the committed file byte for byte",
          st[gw_key]["config"] == COMMITTED)
    check(f"{label}: the community cluster's allow-list is the three tools again", evil_of(st[tn_key]) == ALL)
    check(f"{label}: one line per cluster names the control, and _both names {peer_name}",
          f"🔓 {gw_who}: OFF, at the gateway." in out and f"🔓 {tn_who}: OFF, in the agent's allow-list." in out
          and f"Switched on both clusters: this one and {peer_name}." in out, out)
    check(f"{label}: guard-mcp-off times nothing and reads no log", "⏱" not in out and not on_cluster(r, gw_key, "logs"))
    check(f"{label}: every line guard-mcp-off prints replays the call it made", r["replayed"] == r["calls"])

print("== the waits run out: each cluster named with the bound, and the run fails ==")
r = run("guard-mcp-on", "stuck", cluster("kubecon-private"), COMMUNITY, cluster("kubecon-community"), ("2",))
out = r["stdout"]
check("exits 1", r["rc"] == 1, r["out"])
check("names this cluster and the bound: the gateway logged no reload",
      "⚠️  This cluster: gave up after 2 s: the gateway had not logged a reload of the new rule." in out, out)
check(f"names {COMMUNITY} and the bound: kagent had not rolled workshop-agent",
      f"⚠️  {COMMUNITY}: gave up after 2 s: kagent had not rolled workshop-agent with the new allow-list." in out, out)
check("says the restriction is written but not served within the bound, without the explanation",
      "not every cluster serves it yet: the ones named above had not, within 2 s." in out
      and "Re-ask the weather question" not in out, out)
check("both writes still went through", r["state"]["this"]["config"] == NARROWED
      and evil_of(r["state"][COMMUNITY]) == ["get_weather"])
polls = len(on_cluster(r, "this", "logs"))
check("it read again, every 2 s, before giving up: once at the write and once 2 s on", polls == 2, f"{polls} reads")
r = run("guard-mcp-on", "linked", cluster("kubecon-private"), COMMUNITY, cluster("kubecon-community"), ("soon",))
check("a bound that is not a number of seconds is a usage error that changes nothing",
      r["rc"] == 2 and "Usage: guard-mcp-on [seconds" in r["stdout"] and not r["calls"], r["out"])

print("== a write that changed nothing has nothing to reload ==")
r = run("guard-mcp-on", "linked", cluster("kubecon-private", NARROWED), COMMUNITY,
        cluster("kubecon-community", evil=["get_weather"]))
out = r["stdout"]
check("exits 0, both clusters say it already read that way", r["rc"] == 0
      and "⏱  This cluster: it already read that way, so there is nothing to reload." in out
      and f"⏱  {COMMUNITY}: it already read that way, so there is nothing to reload." in out, r["out"])
check("and it reads no log and no rollout status", not on_cluster(r, "this", "logs")
      and not [c for c in on_cluster(r, COMMUNITY, "deployment") if "jsonpath={.metadata.generation}" not in c])

print("== a cluster with no guardrails-peer Secret, the 2-hour workshop's ==")
for profile, timing in (("admin", gw_line("This cluster")), ("attendee", roll_line("This cluster"))):
    r = run("guard-mcp-on", "unlinked", cluster(profile), COMMUNITY, cluster("kubecon-community"))
    lines = [line for line in r["stdout"].splitlines() if line.startswith("Switched on")]
    check(f"{profile}: switches this cluster alone, says so in one line, and exits 0", r["rc"] == 0 and lines == [
        "Switched on this cluster alone: it has no guardrails-switch/guardrails-peer Secret, so no other cluster is "
        "linked to it."], r["out"])
    check(f"{profile}: still times this cluster", timing.search(r["stdout"]) is not None, r["stdout"])
    check(f"{profile}: touches no other cluster", {c["cluster"] for c in r["calls"]} == {"this"})
    r = run("guard-mcp-off", "unlinked", cluster(profile, NARROWED, ["get_weather"]), COMMUNITY,
            cluster("kubecon-community"))
    check(f"{profile}: guard-mcp-off switches it alone and exits 0", r["rc"] == 0
          and "Switched on this cluster alone" in r["stdout"] and {c["cluster"] for c in r["calls"]} == {"this"},
          r["out"])

print("== the peer Secret is there, its cluster cannot be reached ==")
r = run("guard-mcp-on", "peer-down", cluster("kubecon-private"), COMMUNITY, cluster("kubecon-community"))
out = r["stdout"]
check("this cluster is switched and timed", r["state"]["this"]["config"] == NARROWED
      and gw_line("This cluster").search(out) is not None, out)
check(f"fails, naming {COMMUNITY} as the cluster it could not reach",
      r["rc"] == 1 and f"not on {COMMUNITY}: it could not be reached, or it refused the change." in out
      and f"⚠️  {COMMUNITY}: the MCP tool restriction did not switch on" in out, out)
check("ends saying it did not switch on everywhere, without the explanation",
      "did not switch on everywhere" in out and "Re-ask the weather question" not in out, out)
r = run("guard-mcp-off", "peer-down", cluster("kubecon-private", NARROWED), COMMUNITY, cluster("kubecon-community"))
check(f"guard-mcp-off: switches this cluster, fails naming {COMMUNITY}", r["rc"] == 1
      and r["state"]["this"]["config"] == COMMITTED and f"not on {COMMUNITY}" in r["stdout"], r["out"])

print("== the peer's grant is what those calls ask of it, and no more ==")
asked: set[tuple[str, str, str, str]] = set()
for label, here_p, peer_name, peer_p in LINKED:
    for cmd in ("guard-mcp-on", "guard-mcp-off"):
        start = switched_on if cmd.endswith("off") else cluster
        r = run(cmd, "linked", start(here_p), peer_name, start(peer_p))
        for c in r["calls"]:
            if c["cluster"] == peer_name:
                asked |= need(c)
mcp = docs(MCP_SWITCH)
GRANT: dict[tuple[str, str, str], set[str]] = {}
for d in mcp:
    if d["kind"] == "Role":
        for rule in d["rules"]:
            for res in rule["resources"]:
                for name in rule.get("resourceNames") or ["*"]:
                    GRANT.setdefault((d["metadata"]["namespace"], res, name), set()).update(rule["verbs"])
WANT = {("argocd", "applications", "lab-bootstrap"): {"get"},
        ("agent", "configmaps", "agentgateway-c7-config"): {"get", "patch"},
        ("agent", "agents", "workshop-agent"): {"get", "patch"},
        ("agent", "deployments", "workshop-agent"): {"get"},
        ("agent", "pods", "*"): {"list", "patch"},
        ("agent", "pods/log", "*"): {"get"}}
check("mcp-switch.yaml grants argocd/lab-bootstrap (get), agentgateway-c7-config and the workshop-agent Agent (get, "
      "patch), the workshop-agent Deployment (get), and pods (list, patch) and pods/log (get) in agent",
      GRANT == WANT, str(GRANT))
granted = {(*k, v) for k, vs in GRANT.items() for v in vs}
check("everything guard-mcp-on and guard-mcp-off ask of the peer, both ways round, is inside it",
      asked and asked <= granted, str(sorted(asked - granted)))
check("and every verb it grants is one they ask for", granted <= asked, str(sorted(granted - asked)))
groups = {(d["metadata"]["namespace"], res): rule["apiGroups"] for d in mcp if d["kind"] == "Role"
          for rule in d["rules"] for res in rule["resources"]}
check("each rule names its one API group",
      groups == {("argocd", "applications"): ["argoproj.io"], ("agent", "configmaps"): [""],
                 ("agent", "agents"): ["kagent.dev"], ("agent", "deployments"): ["apps"], ("agent", "pods"): [""],
                 ("agent", "pods/log"): [""]}, str(groups))
unnamed = sorted(k[1] for k in GRANT if k[2] == "*")
check("only pods and pods/log are unnamed, the two whose names RBAC cannot know", unnamed == ["pods", "pods/log"],
      str(unnamed))
binds = [d for d in mcp if d["kind"] == "RoleBinding"]
check("a RoleBinding for each Role, to the guardrails-switch ServiceAccount alone",
      sorted((b["metadata"]["namespace"], b["roleRef"]["name"]) for b in binds)
      == [("agent", "guardrails-switch-mcp"), ("argocd", "guardrails-switch-mcp")]
      and all(b["subjects"] == [{"kind": "ServiceAccount", "name": "guardrails-switch", "namespace": "guardrails-switch"}]
              for b in binds))
check("no ClusterRole: nothing in it reaches past the two namespaces", not [d for d in mcp if d["kind"].startswith("Cluster")])
app_src = yaml.safe_load(SWITCH_APP.read_text(encoding="utf-8"))["spec"]["source"]
check("the guardrails-switch Application syncs the whole directory, so mcp-switch.yaml ships with it",
      app_src["path"] == "gitops/guardrails-switch" and "directory" not in app_src
      and MCP_SWITCH.parent == SWITCH_DIR)

print("== the pod patch is held to the one annotation on the agentgateway pod ==")
vap = next((d for d in mcp if d["kind"] == "ValidatingAdmissionPolicy"), {})
vapb = next((d for d in mcp if d["kind"] == "ValidatingAdmissionPolicyBinding"), {})
spec = vap.get("spec", {})
check("a ValidatingAdmissionPolicy, failing closed, bound with Deny",
      spec.get("failurePolicy") == "Fail" and vapb.get("spec", {}).get("policyName") == vap["metadata"]["name"]
      and vapb["spec"].get("validationActions") == ["Deny"])
check("it matches every pod UPDATE", spec.get("matchConstraints", {}).get("resourceRules") == [
    {"apiGroups": [""], "apiVersions": ["v1"], "operations": ["UPDATE"], "resources": ["pods"]}])
check("by the guardrails-switch ServiceAccount alone",
      [m["expression"] for m in spec.get("matchConditions", [])] == [f"request.userInfo.username == '{SA}'"])
var = {v["name"]: v["expression"] for v in spec.get("variables", [])}
check("the one annotation it lets change is the one _c7rule writes",
      var.get("touch") == f"'{TOUCH}'" and f'"{TOUCH}=$(date +%s)"' in lib, str(var))
rules = " ".join(v["expression"] for v in spec.get("validations", []))
check("it holds the pod to agentgateway's in agent, the label _c7rule selects on",
      "object.metadata.namespace == 'agent'" in rules and "'app.kubernetes.io/name'" in rules
      and "== 'agentgateway'" in rules and "annotate pod -l app.kubernetes.io/name=agentgateway" in lib)
for what, part in (("the spec, images included", "object.spec == oldObject.spec"),
                   ("the labels", "object.metadata.?labels.orValue({}) == oldObject.metadata.?labels.orValue({})"),
                   ("the owners", "object.metadata.?ownerReferences.orValue([]) == oldObject.metadata.?ownerReferences"),
                   ("the finalizers", "object.metadata.?finalizers.orValue([]) == oldObject.metadata.?finalizers"),
                   ("every other annotation, kept with its value",
                    "variables.after.all(k, k == variables.touch || (k in variables.before && "
                    "variables.before[k] == variables.after[k]))"),
                   ("every other annotation, none removed",
                    "variables.before.all(k, k == variables.touch || k in variables.after)")):
    check(f"it holds {what} as they were", part in rules, rules)

print("== block-argocd-drift lets guardrails-switch UPDATE agentgateway-c7-config and nothing else ==")
conds = {c["name"]: c["expression"] for c in yaml.safe_load(DRIFT.read_text(encoding="utf-8"))["spec"]["matchConditions"]}
ex = conds.get("not-guardrails-switch-c7-rule", "")
check("a not-guardrails-switch-c7-rule matchCondition, for that identity",
      f"request.userInfo.username == '{SA}'" in ex, ex)
check("an UPDATE of the one ConfigMap, by kind, namespace and name, read optionally",
      "request.operation == 'UPDATE'" in ex and "object.?kind.orValue('') == 'ConfigMap'" in ex
      and "object.?metadata.?namespace.orValue('') == 'agent'" in ex
      and "object.?metadata.?name.orValue('') == 'agentgateway-c7-config'" in ex, ex)
check("a negated conjunction, never wider than all of those at once",
      ex.strip().startswith("!(") and ex.strip().endswith(")") and "||" not in ex and ex.count("&&") == 4, ex)
check("the web terminal's own exemption is still there", "not-terminal-c7-rule" in conds)

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
print("All two-cluster MCP switch checks passed.")
