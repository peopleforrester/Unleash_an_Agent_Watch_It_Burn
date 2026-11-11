# ABOUTME: Offline gate for #1346: every stage switch is guardrails-<name>-on or -off, switches both KubeCon clusters
# ABOUTME: from the private terminal, prints each kubectl it runs, and ends on both clusters' /controls in the new state.
"""#1346, Michael 2026-11-11: one naming pattern for every stage switch. The terminal (gitops/ai-layer/web-terminal/
entrypoint.sh) writes guardrails-<name>-on and guardrails-<name>-off for kates, agency, input, output, mcp, budget,
topic, ai and all, each a call to _gr in ~/.guardlib.

Checked here, with the entrypoint's own ~/.guardlib, .controls.py, .c7rule.py and .evilpatch.py, its own loop writing
the eighteen scripts, and a kubectl on PATH that plays both KubeCon clusters (a call with --kubeconfig is the peer,
watch-it-burn-community; any other is this one, watch-it-burn-private) and answers guard-proxy's /toggle and
/controls from each cluster's state:

  * each of the eighteen, from the opposite state, exits 0, turns every field its groups own to the new state on both
    clusters and leaves the other groups as they were (ai and all never touch topic), names both clusters as switched,
    and prints a `$ ` line for every kubectl it runs, in the order it runs them;
  * each ends on both clusters' /controls: the last two lines are this cluster's and the peer's, each with its host,
    and the groups it switched read the new state;
  * guardrails-all-off takes least privilege off before the Kubernetes guardrails, so the shipped Role is what stays;
  * a peer that cannot be reached: exit 1, the peer named, and its /controls named as not read;
  * a peer whose /controls still reads the old state: exit 1, naming the group and the cluster;
  * a cluster with no peer Secret (the 2-hour lab's): switched alone and read alone, exit 0;
  * a bad argument exits 2 and switches nothing;
  * the older names are still written, and the images/ twin is byte-identical.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
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
PEER = "watch-it-burn-community"
HOSTS = {"this": "burritobot-private.burritobot.co", PEER: "attackme.burritobot.co"}
PROFILES = {"this": "kubecon-private", PEER: "kubecon-community"}
ALL_TOOLS = ["get_weather", "read_internal_config", "apply_optimization"]
NAMES = ("kates", "agency", "input", "output", "mcp", "budget", "topic", "ai", "all")
OLD = ("guardrails-on", "guardrails-off", "guard-agency-on", "guard-agency-off", "guards-on", "guards-off",
       "guard-input-on", "guard-input-off", "guard-output-on", "guard-output-off", "guard-mcp-on", "guard-mcp-off",
       "guard-budget-on", "guard-budget-off", "guard-topic-on", "guard-topic-off")
# The /controls fields each group owns, as guard-proxy sends them (stage_switch_check.py names the same).
FIELDS = {
    "kates": (("infra", "rbac_scoped"), ("infra", "kyverno"), ("infra", "kubearmor"), ("infra", "networkpolicy")),
    "agency": (("infra", "agency_scoped"),),
    "input": (("ai", "input_blocklist"), ("ai", "input_classifier")),
    "output": (("ai", "output"),),
    "mcp": (("infra", "tool_allowlist"),),
    "budget": (("ai", "budget"),),
    "topic": (("ai", "topic"),),
}
GROUPS = {"ai": ("input", "output", "mcp", "budget"),
          "all": ("kates", "agency", "input", "output", "mcp", "budget")}
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:1500]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


TEXT = ENTRYPOINT.read_text(encoding="utf-8")
HELPERS = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', TEXT, re.S))
for h in (".guardlib", ".controls.py", ".c7rule.py", ".evilpatch.py"):
    if h not in HELPERS:
        sys.exit(f"ANCHOR MISSING: no `cat > \"$HOME/{h}\" <<'EOS'` heredoc in {ENTRYPOINT}")
LOOP = re.search(r"^for g in kates agency input output mcp budget topic ai all; do\n.*?^done\n", TEXT, re.S | re.M)
if not LOOP:
    sys.exit(f"ANCHOR MISSING: the `for g in kates agency ... all; do` loop that writes the switches in {ENTRYPOINT}")
COMMITTED = next(d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d and d.get("kind") == "ConfigMap"
                 and d["metadata"]["name"] == "agentgateway-c7-config")["data"]["config.yaml"]
if "'true' # c7-rule" not in COMMITTED:
    sys.exit(f"ANCHOR MISSING: {GATEWAY.relative_to(REPO)} has no line \"'true' # c7-rule\"")
NARROWED = COMMITTED.replace("'true' # c7-rule", "'mcp.tool.name == \"get_weather\"' # c7-rule")

# A kubectl that plays both clusters. MODE: linked, unlinked (no peer Secret), peer-down (the peer's API cannot be
# reached), stale (the peer's /controls keeps answering what it read at the start).
FAKE = r'''#!/usr/bin/env python3
import base64, json, os, re, sys, urllib.parse
a = sys.argv[1:]
if "--kubeconfig" in a:
    i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]
    j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]
else:
    ctx = "this"
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"cluster": ctx, "args": a}) + "\n")
S = json.load(open(os.environ["STATE"]))
mode = os.environ["MODE"]
def save():
    json.dump(S, open(os.environ["STATE"], "w"))
def jpatch(doc, ops):
    for op in ops:
        parts = [p for p in op["path"].split("/")[1:]]
        node = doc
        for p in parts[:-1]:
            node = node[int(p)] if isinstance(node, list) else node[p]
        last = int(parts[-1]) if isinstance(node, list) else parts[-1]
        if op["op"] == "test" and node[last] != op["value"]:
            sys.stderr.write("the server rejected our request\n"); sys.exit(1)
        if op["op"] == "replace":
            node[last] = op["value"]
def evil(c):
    return next(t["mcpServer"]["toolNames"] for t in c["agent"]["spec"]["declarative"]["tools"]
                if t["mcpServer"]["name"] == "evil-mcp")
def controls(c):
    narrowed = "get_weather" in c["config"].split("# c7-rule")[0].splitlines()[-1]
    return {"host": c["host"], "ai": dict(c["guards"]), "infra": {
        "rbac_scoped": c["role"] in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml"),
        "agency_scoped": c["role"] == "c6-least-privilege-role.yaml",
        "kyverno": c["policies"]["restrict-image-registries"] == "Deny",
        "kubearmor": c["kubearmor"], "networkpolicy": c["netpol"],
        "tool_allowlist": narrowed or evil(c) == ["get_weather"], "falco": True}}
def proxy(c, path):
    u = urllib.parse.urlsplit(path)
    if u.path == "/controls":
        return json.dumps(S["frozen"][ctx] if mode == "stale" and ctx != "this" else controls(c))
    if u.path == "/toggle":
        for k, v in urllib.parse.parse_qsl(u.query):
            if k in c["guards"]:
                c["guards"][k] = v == "on"
        return json.dumps(c["guards"])
    sys.stderr.write("fake guard-proxy: no such path " + path + "\n"); sys.exit(1)
if "guardrails-peer" in a:
    if mode == "unlinked":
        if "--ignore-not-found" in a:
            sys.exit(0)
        sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
    if "--ignore-not-found" in a:
        print("secret/guardrails-peer"); sys.exit(0)
    val = b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in a[-1] else b"watch-it-burn-community"
    print(base64.b64encode(val).decode()); sys.exit(0)
if mode == "peer-down" and ctx != "this":
    sys.stderr.write("Unable to connect to the server\n"); sys.exit(1)
c = S[ctx]
if "exec" in a and "deploy/guard-proxy" in a:
    m = re.search(r"localhost:8080(/[^']*)'", a[-1])
    print(proxy(c, m.group(1)))
elif "--raw" in a:
    raw = a[a.index("--raw") + 1]
    print(proxy(c, raw.split("/services/guard-proxy:8080/proxy", 1)[1]))
elif "apply" in a or "delete" in a:
    f = os.path.basename(a[a.index("-f") + 1])
    on = "apply" in a
    if f in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml"):
        c["role"] = f
    elif f == "c3-kubearmor-policy.yaml":
        c["kubearmor"] = on
    elif f == "c1-network-policy.yaml":
        c["netpol"] = on
    else:
        sys.stderr.write("fake kubectl: no such file " + f + "\n"); sys.exit(1)
    print(f + (" configured" if on else " deleted"))
elif "validatingpolicy" in a:
    p = a[a.index("validatingpolicy") + 1]
    if "patch" in a:
        c["policies"][p] = json.loads(a[a.index("-p") + 1])[0]["value"][0]
    else:
        sys.stdout.write(c["policies"][p])
elif "application" in a:
    sys.stdout.write(c["profile"])
elif "get" in a and "configmap" in a:
    print(json.dumps({"metadata": {"resourceVersion": str(c["rv"])}, "data": {"config.yaml": c["config"]}}))
elif "patch" in a and "configmap" in a:
    doc = {"metadata": {"resourceVersion": str(c["rv"])}, "data": {"config.yaml": c["config"]}}
    jpatch(doc, json.loads(a[a.index("-p") + 1]))
    if doc["data"]["config.yaml"] == c["config"]:
        print("configmap/agentgateway-c7-config patched (no change)")
    else:
        c["config"] = doc["data"]["config.yaml"]; c["rv"] += 1; c["reload"] = True
        print("configmap/agentgateway-c7-config patched")
elif "annotate" in a:
    print("pod/agentgateway-6d9f7c8b5-x2x4q annotated")
elif "logs" in a:
    if c.get("reload"):
        print('info state_manager loaded config from File("/etc/agentgateway-c7/config.yaml")')
elif "get" in a and "deployment" in a:
    g = c["gen"]
    sys.stdout.write(str(g) if a[-1] == "jsonpath={.metadata.generation}" else f"{g} {g} 1 1 1")
elif "get" in a and "agent" in a:
    print(json.dumps(c["agent"]))
elif "patch" in a and "agent" in a:
    before = json.dumps(c["agent"])
    jpatch(c["agent"], json.loads(a[a.index("-p") + 1]))
    if json.dumps(c["agent"]) == before:
        print("agent.kagent.dev/workshop-agent patched (no change)")
    else:
        c["gen"] += 1
        print("agent.kagent.dev/workshop-agent patched")
else:
    sys.stderr.write("fake kubectl: unexpected call " + " ".join(a) + "\n"); sys.exit(1)
save()
'''
FAKE_SLEEP = "#!/usr/bin/env bash\nexit 0\n"


def cluster(ctx: str, on: bool) -> dict:
    """One cluster with every guardrail off (the stage's start), or every one on, the on-topic guard included."""
    return {"host": HOSTS[ctx], "profile": PROFILES[ctx], "rv": 7, "gen": 3,
            "role": "c6-least-privilege-role.yaml" if on else "c8-broad-role.yaml",
            "policies": {p: ("Deny" if on else "Audit") for p in ("restrict-image-registries", "deny-external-registries")},
            "kubearmor": on, "netpol": on,
            "guards": {k: on for k in ("output", "input_blocklist", "input_classifier", "budget", "topic")},
            "config": NARROWED if on and ctx == "this" else COMMITTED,
            "agent": {"spec": {"declarative": {"tools": [
                {"type": "McpServer", "mcpServer": {"name": "workshop-mcp", "toolNames": ["run_shell"]}},
                {"type": "McpServer", "mcpServer": {"name": "evil-mcp", "toolNames":
                                                    ["get_weather"] if on and ctx != "this" else list(ALL_TOOLS)}}]}}}}


def controls_of(c: dict) -> dict:
    """What the fake's /controls answers for a cluster's state (the fake's own controls(), here for the test)."""
    narrowed = "get_weather" in c["config"].split("# c7-rule")[0].splitlines()[-1]
    evil = c["agent"]["spec"]["declarative"]["tools"][1]["mcpServer"]["toolNames"]
    return {"ai": dict(c["guards"]), "infra": {
        "rbac_scoped": c["role"] in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml"),
        "agency_scoped": c["role"] == "c6-least-privilege-role.yaml",
        "kyverno": c["policies"]["restrict-image-registries"] == "Deny",
        "kubearmor": c["kubearmor"], "networkpolicy": c["netpol"],
        "tool_allowlist": narrowed or evil == ["get_weather"]}}


def group_state(c: dict, group: str) -> list:
    ctl = controls_of(c)
    return [ctl[s][k] for s, k in FIELDS[group]]


def run(cmd: str, args: tuple[str, ...] = (), start_on: bool = False, mode: str = "linked"):
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        for h in (".guardlib", ".controls.py", ".c7rule.py", ".evilpatch.py"):
            (home / h).write_text(HELPERS[h] + "\n", encoding="utf-8")
        (home / "challenges").mkdir()
        bindir = home / "bin"
        bindir.mkdir()
        (bindir / "kubectl").write_text(FAKE)
        (bindir / "sleep").write_text(FAKE_SLEEP)
        for b in ("kubectl", "sleep"):
            (bindir / b).chmod(0o755)
        start = {"this": cluster("this", start_on), PEER: cluster(PEER, start_on)}
        start["frozen"] = {PEER: {**controls_of(start[PEER]), "host": HOSTS[PEER]}}
        (home / "state").write_text(json.dumps(start))
        env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}",
               "CALLS": str(home / "calls"), "STATE": str(home / "state"), "MODE": mode}
        w = subprocess.run(["bash", "-c", LOOP.group(0)], env=env, capture_output=True, text=True, timeout=30)
        if w.returncode != 0 or not (home / cmd).exists():
            return 99, f"the loop did not write {cmd}: {w.stderr}", "", [], start, start
        r = subprocess.run(["bash", str(home / cmd), *args], env=env, capture_output=True, text=True, timeout=120)
        calls = [json.loads(x) for x in (home / "calls").read_text().splitlines()] if (home / "calls").exists() else []
        end = json.loads((home / "state").read_text())
        return r.returncode, r.stdout, r.stderr, calls, start, end


def shown(stderr: str) -> list[dict]:
    """Each printed `$ ` line as the call it names, in the fake's terms: the cluster and the arguments."""
    out = []
    for line in stderr.splitlines():
        if not line.startswith("$ "):
            continue
        words = shlex.split(line[2:].split(" | ", 1)[0])
        if words[:2] == ["timeout", "20"]:
            words = words[2:]
        if words[0] != "kubectl":
            continue
        a, ctx = words[1:], "this"
        if "--kubeconfig" in a:
            i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]
            j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]
        out.append({"cluster": ctx, "args": a})
    return out


def groups_of(name: str) -> tuple[str, ...]:
    return GROUPS.get(name, (name,))


# Every switch, from the opposite state, on both clusters.
for name in NAMES:
    for st in ("on", "off"):
        cmd = f"guardrails-{name}-{st}"
        rc, out, err, calls, start, end = run(cmd, start_on=(st == "off"))
        want = st == "on"
        mine = groups_of(name)
        moved = [f"{ctx} {g}" for ctx in ("this", PEER) for g in mine if group_state(end[ctx], g) != [want] * len(FIELDS[g])]
        # kates and agency both write the workshop-agent Role, so either one moves the other's Role-read field.
        shared = {"kates", "agency"} if {"kates", "agency"} & set(mine) else set()
        kept = [f"{ctx} {g}" for ctx in ("this", PEER) for g in FIELDS if g not in mine and g not in shared
                and group_state(end[ctx], g) != group_state(start[ctx], g)]
        check(f"{cmd}: exit 0, and both clusters read {st} for {', '.join(mine)}", rc == 0 and not moved,
              f"exit {rc}, not {st}: {moved}\n{out}{err}")
        check(f"{cmd}: leaves every other group as it was" + (" (topic among them)" if name in ("ai", "all") else ""),
              not kept, f"changed: {kept}")
        check(f"{cmd}: names both clusters as switched",
              f"this one and {PEER}" in out and "⚠️" not in out, out)
        check(f"{cmd}: prints a `$ ` line for every kubectl it runs, in order", shown(err) == calls,
              f"{len(shown(err))} shown, {len(calls)} ran")
        lines = out.strip().splitlines()
        tail = lines[-2:]
        check(f"{cmd}: ends on both clusters' /controls, the groups it switched reading {st}",
              len(tail) == 2 and tail[0].startswith(f"  This cluster ({HOSTS['this']}): kates ")
              and tail[1].startswith(f"  {PEER} ({HOSTS[PEER]}): kates ")
              and all(f"{g} {st}" in t for t in tail for g in mine)
              and calls[-1]["args"][-1].endswith("/proxy/controls") and calls[-1]["cluster"] == PEER, "\n".join(tail))

# all-off takes least privilege off before the Kubernetes guardrails: the shipped Role is the last one applied.
rc, out, err, calls, start, end = run("guardrails-all-off", start_on=True)
roles = [os.path.basename(c["args"][c["args"].index("-f") + 1]) for c in calls if "apply" in c["args"]
         and "role" in c["args"][c["args"].index("-f") + 1] and c["cluster"] == "this"]
check("guardrails-all-off applies the scoped Role, then the shipped one, so the shipped Role stays",
      roles == ["c5-scoped-role.yaml", "c8-broad-role.yaml"] and end["this"]["role"] == "c8-broad-role.yaml", str(roles))
check("guardrails-all-off leaves the on-topic guard on", end["this"]["guards"]["topic"] and end[PEER]["guards"]["topic"])

# The peer cannot be reached: the switch fails, the peer is named, and its /controls is named as not read.
for cmd in ("guardrails-input-on", "guardrails-agency-on", "guardrails-kates-on", "guardrails-ai-on"):
    rc, out, err, calls, start, end = run(cmd, mode="peer-down")
    check(f"{cmd} with the peer down: exit 1, naming the peer and its unread /controls",
          rc == 1 and PEER in out and f"⚠️  {PEER}: /controls could not be read." in out
          and out.strip().splitlines()[-1].startswith(f"  ⚠️  {PEER}"), f"exit {rc}\n{out}")
rc, out, err, calls, start, end = run("guardrails-ai-on", mode="peer-down")
check("guardrails-ai-on with the peer down names every group that did not switch",
      "guardrails-ai-on ran every step; these did not switch on: input, output, mcp, budget." in out, out)

# The peer's /controls still reads the old state: the switch fails, naming the group and the cluster.
rc, out, err, calls, start, end = run("guardrails-input-on", mode="stale")
check("a /controls that still reads the old state fails, naming the cluster and the group",
      rc == 1 and f"⚠️  {PEER}: /controls reads input off, not on." in out, f"exit {rc}\n{out}")

# The 2-hour lab's lone cluster: switched alone, read alone.
rc, out, err, calls, start, end = run("guardrails-input-on", mode="unlinked")
check("an unlinked cluster switches alone, reads its own /controls, and exits 0",
      rc == 0 and "Switched on this cluster alone" in out and "The other KubeCon cluster was not read" in out
      and all(c["cluster"] == "this" for c in calls), f"exit {rc}\n{out}")

# A bad argument switches nothing.
for cmd, args in (("guardrails-input-on", ("now",)), ("guardrails-kates-on", ("x",)), ("guardrails-mcp-on", ("soon",)),
                  ("guardrails-mcp-off", ("5",)), ("guardrails-all-off", ("5",))):
    rc, out, err, calls, start, end = run(cmd, args)
    check(f"{cmd} {' '.join(args)}: exit 2, a usage line, nothing changed",
          rc == 2 and "Usage: " in out and not any("apply" in c["args"] or "patch" in c["args"] or "--raw" in c["args"]
                                                   or "exec" in c["args"] for c in calls), f"exit {rc}\n{out}")

# guardrails-kates-on takes the seconds between guardrails, and guardrails-mcp-on the bound it waits for each cluster.
rc, out, err, calls, start, end = run("guardrails-kates-on", ("3",))
check("guardrails-kates-on 3 switches as guardrails-kates-on does", rc == 0, f"exit {rc}\n{out}")
rc, out, err, calls, start, end = run("guardrails-mcp-on", ("60",))
check("guardrails-mcp-on 60 switches and times each cluster", rc == 0 and out.count("⏱") == 2, f"exit {rc}\n{out}")

# The older names are still written (decisions.md, #1346), and the twin matches.
missing = [n for n in OLD if f'cat > "$HOME/{n}" <<' not in TEXT]
check("the older names are still written, for the 2-hour lab and a presenter's old habit", not missing, str(missing))
check("images/web-terminal/entrypoint.sh is kept byte-identical", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

# Self-check: a .controls.py that never names a wrong group lets a stale /controls through, and the check above sees it.
real = HELPERS[".controls.py"]
HELPERS[".controls.py"] = real.replace("if wrong:", "if False:", 1)
if HELPERS[".controls.py"] == real:
    sys.exit(f"ANCHOR MISSING: `if wrong:` in .controls.py in {ENTRYPOINT}")
rc, out, err, calls, start, end = run("guardrails-input-on", mode="stale")
check("self-check: a /controls read that is not held to the new state is caught", rc == 0, f"exit {rc}")
HELPERS[".controls.py"] = real

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nevery stage switch is guardrails-<name>-on or -off, reaches both KubeCon clusters and ends on /controls (#1346)")
