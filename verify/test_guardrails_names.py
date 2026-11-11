# ABOUTME: Offline gate for #1350: every stage switch is guardrails-<name>-on or -off, switches both KubeCon clusters
# ABOUTME: from the private terminal, prints each kubectl and ends on both /controls; each old name is an alias of one.
"""#1350, the rename Michael asked for in #1346: one pattern, guardrails-<name>-on and guardrails-<name>-off, for k8s,
agency, input, output, mcp, budget, topic, ai and all (and rbac and admission, the 2-hour lab's cluster fixes, whose
old names Michael kept as aliases too), each a heredoc in gitops/ai-layer/web-terminal/entrypoint.sh. Every old name
(guardrails-on/off, guards-on/off/status, guard-<name>-on/off) is an alias the entrypoint writes from its ALIASES table:
it says its new name, then execs it.

Checked here, with the entrypoint's own ~/.guardlib, .c7rule.py, .evilpatch.py, every heredoc and the alias loop, and
a kubectl on PATH that plays both KubeCon clusters (a call with --kubeconfig is the peer, watch-it-burn-community; any
other is this one, watch-it-burn-private, the private terminal's) and keeps each cluster's state:

  * each of the eighteen switches (and rbac and admission), from the opposite state, exits 0, turns every /controls
    field its groups own to the new state on both clusters and leaves every other field as it was (ai and all never
    touch topic), says once per step that it switched this cluster and the peer, prints a `$ ` line for every
    kubectl it runs, in order, and ends with /controls read on this cluster, then on the peer, both printed by name
    with the switched controls ON or off;
  * guardrails-all-on runs k8s before agency and guardrails-all-off agency off before k8s off, so the Role left is c6
    and c8; each runs every step when the peer is down, names what failed, and exits 1;
  * a lone cluster (the 2-hour lab's) is switched and read alone; guardrails-k8s-on keeps its seconds argument;
  * every old name runs exactly what its new name runs, with the same exit code and output after its one line naming
    the new name; guards-off's line says it leaves the on-topic guard; a mis-paired alias is caught;
  * guardrails-status names every new switch and ends on both clusters' /controls;
  * the images/ twin is byte-identical.
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
HERE = "watch-it-burn-private"
PEER = "watch-it-burn-community"
HOSTS = {"this": "burritobot-private.example", PEER: "attackme.example"}
PROFILES = {"this": "kubecon-private", PEER: "kubecon-community"}
ALL_TOOLS = ["get_weather", "read_internal_config", "apply_optimization"]
NAMES = ("k8s", "agency", "input", "output", "mcp", "budget", "topic", "ai", "all")
EXTRA = ("rbac", "admission")
# The /controls fields each group owns, as guard-proxy reports them, and the label _controls prints for each.
FIELDS = {
    "k8s": (("infra", "rbac_scoped"), ("infra", "kyverno"), ("infra", "kubearmor"), ("infra", "networkpolicy")),
    "agency": (("infra", "agency_scoped"),),
    "rbac": (("infra", "rbac_scoped"),),
    "admission": (("infra", "kyverno"),),
    "input": (("ai", "input_blocklist"), ("ai", "input_classifier")),
    "output": (("ai", "output"),),
    "mcp": (("infra", "tool_allowlist"),),
    "budget": (("ai", "budget"),),
    "topic": (("ai", "topic"),),
}
LABEL = {"rbac_scoped": "RBAC scope", "kyverno": "Kyverno", "kubearmor": "KubeArmor", "networkpolicy": "NetworkPolicy",
         "agency_scoped": "least privilege", "input_blocklist": "input block-list",
         "input_classifier": "injection classifier", "output": "output", "tool_allowlist": "tool allow-list",
         "budget": "budget cap", "topic": "on-topic"}
GROUPS = {"ai": ("input", "output", "mcp", "budget"), "all": ("k8s", "agency", "input", "output", "mcp", "budget")}
# How many steps each switch runs, each one saying which clusters it changed.
STEPS = {"ai": 2, "all": 4}
ROLE_GROUPS = {"k8s", "agency", "rbac"}  # each writes the workshop-agent Role, so each can move the other's field
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:2000]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


TEXT = ENTRYPOINT.read_text(encoding="utf-8")
HELPERS = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', TEXT, re.S))
for h in (".guardlib", ".c7rule.py", ".evilpatch.py", "guardrails-status"):
    if h not in HELPERS:
        sys.exit(f"ANCHOR MISSING: no `cat > \"$HOME/{h}\" <<'EOS'` heredoc in {ENTRYPOINT}")
ALIAS_LOOP = re.search(r"^while read -r old new; do\n.*?^ALIASES\n", TEXT, re.S | re.M)
if not ALIAS_LOOP:
    sys.exit(f"ANCHOR MISSING: the `while read -r old new; do ... ALIASES` loop that writes the old names in {ENTRYPOINT}")
ALIASES = [tuple(line.split()) for line in ALIAS_LOOP.group(0).split("<<'ALIASES'\n", 1)[1].splitlines()[:-1]]
COMMITTED = next(d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d and d.get("kind") == "ConfigMap"
                 and d["metadata"]["name"] == "agentgateway-c7-config")["data"]["config.yaml"]
if "'true' # c7-rule" not in COMMITTED:
    sys.exit(f"ANCHOR MISSING: {GATEWAY.relative_to(REPO)} has no line \"'true' # c7-rule\"")
NARROWED = COMMITTED.replace("'true' # c7-rule", "'mcp.tool.name == \"get_weather\"' # c7-rule")

# A kubectl that plays both clusters. MODE: linked, unlinked (no peer Secret), peer-down (the peer cannot be reached).
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
        parts = op["path"].split("/")[1:]
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
        "networkpolicy": c["netpol"], "kyverno": c["policies"]["restrict-image-registries"] == "Deny",
        "kubearmor": c["kubearmor"], "falco": True, "tool_allowlist": narrowed or evil(c) == ["get_weather"],
        "rbac_scoped": c["role"] in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml"),
        "agency_scoped": c["role"] == "c6-least-privilege-role.yaml"}}
def proxy(c, path, key=None):
    u = urllib.parse.urlsplit(path)
    if u.path == "/controls":
        return json.dumps(controls(c))
    if u.path == "/toggle":
        for k, v in urllib.parse.parse_qsl(u.query):
            if k in c["guards"]:
                c["guards"][k] = v == "on"
        return str(c["guards"].get(key, "missing")) if key else json.dumps(c["guards"])
    if u.path == "/guards":
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
    code = a[a.index("-c") + 1]
    key = code.split(".get('", 1)[1].split("'", 1)[0] if ".get('" in code else None
    print(proxy(c, re.search(r"localhost:8080(/[^']*)'", code).group(1), key))
elif "--raw" in a:
    print(proxy(c, a[a.index("--raw") + 1].split("/services/guard-proxy:8080/proxy", 1)[1]))
elif "apply" in a or "delete" in a:
    f = os.path.basename(a[a.index("-f") + 1])
    on = "apply" in a
    if f in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml"):
        c["role"] = f; c.setdefault("roles", []).append(f)
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
# A sleep that records what it was asked and returns at once, and a clock that stands still at NOW (date +%s), so two
# runs make the same calls to the second (_c7rule's annotation and _c7poll's --since-time carry the time).
NOW = 1762300800
FAKE_SLEEP = '#!/usr/bin/env bash\necho "$1" >> "$SLEPT"\n'
FAKE_DATE = f'#!/usr/bin/env bash\n[ "$*" = +%s ] && {{ echo {NOW}; exit 0; }}\nexec "{__import__("shutil").which("date")}" "$@"\n'


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
    """The /controls fields of a cluster's state, as the fake answers them."""
    narrowed = "get_weather" in c["config"].split("# c7-rule")[0].splitlines()[-1]
    evil = c["agent"]["spec"]["declarative"]["tools"][1]["mcpServer"]["toolNames"]
    return {"ai": dict(c["guards"]), "infra": {
        "rbac_scoped": c["role"] in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml"),
        "agency_scoped": c["role"] == "c6-least-privilege-role.yaml",
        "kyverno": c["policies"]["restrict-image-registries"] == "Deny",
        "kubearmor": c["kubearmor"], "networkpolicy": c["netpol"],
        "tool_allowlist": narrowed or evil == ["get_weather"]}}


def flat(c: dict) -> dict:
    ctl = controls_of(c)
    return {(s, k): v for s in ("ai", "infra") for k, v in ctl[s].items()}


def run(cmd: str, args: tuple[str, ...] = (), start_on: bool = False, mode: str = "linked",
        aliases: str | None = None) -> dict:
    """Run one terminal command in a home the entrypoint's heredocs and alias loop wrote, against the fake."""
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp, "home")
        bindir = pathlib.Path(tmp, "bin")
        home.mkdir(); bindir.mkdir(); (home / "challenges").mkdir()  # noqa: E702
        for name, body in HELPERS.items():
            (home / name).write_text(body + "\n", encoding="utf-8")
            if not name.startswith("."):
                (home / name).chmod(0o755)
        (bindir / "kubectl").write_text(FAKE)
        (bindir / "sleep").write_text(FAKE_SLEEP)
        (bindir / "date").write_text(FAKE_DATE)
        for b in ("kubectl", "sleep", "date"):
            (bindir / b).chmod(0o755)
        start = {"this": cluster("this", start_on), PEER: cluster(PEER, start_on)}
        state = pathlib.Path(tmp, "state")
        state.write_text(json.dumps(start))
        env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}", "WIB_CLUSTER_NAME": HERE,
               "CALLS": str(pathlib.Path(tmp, "calls")), "STATE": str(state), "MODE": mode,
               "SLEPT": str(pathlib.Path(tmp, "slept"))}
        w = subprocess.run(["bash", "-c", aliases or ALIAS_LOOP.group(0)], env=env, capture_output=True, text=True,
                           timeout=30)
        if w.returncode != 0:
            sys.exit(f"FAILED: the alias loop did not run: {w.stderr}")
        if not (home / cmd).exists():
            return {"rc": 99, "out": f"no {cmd} in the terminal's home", "err": "", "calls": [], "start": start,
                    "end": start}
        r = subprocess.run(["bash", str(home / cmd), *args], env=env, capture_output=True, text=True, timeout=180)
        calls_f = pathlib.Path(tmp, "calls")
        calls = [json.loads(x) for x in calls_f.read_text().splitlines()] if calls_f.exists() else []
        h = str(home)
        return {"rc": r.returncode, "out": r.stdout.replace(h, "$HOME"), "err": r.stderr.replace(h, "$HOME"),
                "calls": [{"cluster": c["cluster"], "args": [x.replace(h, "$HOME") for x in c["args"]]} for c in calls],
                "start": start, "end": json.loads(state.read_text())}


def shown(stderr: str) -> list[dict]:
    """Each printed `$ ` line as the call it names, in the fake's terms: the cluster and the arguments."""
    out = []
    for line in stderr.splitlines():
        if not line.startswith("$ "):
            continue
        words = shlex.split(line[2:].split(" | python3 ", 1)[0])
        if words[:2] == ["timeout", "20"]:
            words = words[2:]
        if not words or words[0] != "kubectl":
            continue
        a, ctx = words[1:], "this"
        if "--kubeconfig" in a:
            i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]  # noqa: E702
            j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]  # noqa: E702
        out.append({"cluster": ctx, "args": a})
    return out


def is_controls(c: dict) -> bool:
    a = c["args"]
    return ("--raw" in a and a[a.index("--raw") + 1].endswith("/proxy/controls")) or (
        "exec" in a and "localhost:8080/controls'" in a[-1])


def read_block(out: str, header: str) -> dict[str, list[str]]:
    """What _controls printed for one cluster: each label listed ON, and each listed off."""
    lines = out.splitlines()
    got: dict[str, list[str]] = {"ON": [], "off": []}
    for i, line in enumerate(lines):
        if line.startswith("  " + header):
            for nxt in lines[i + 1:]:
                if not nxt.startswith("    "):
                    break
                on = nxt.split("ON: ", 1)[1].split("   off: ", 1)
                got["ON"] += [x.strip() for x in on[0].split(",")]
                got["off"] += [x.strip() for x in on[1].split("   not measured:", 1)[0].split(",")]
            return got
    return {}


def groups_of(name: str) -> tuple[str, ...]:
    return GROUPS.get(name, (name,))


print("== the switches are written, and the twin matches ==")
for name in NAMES + EXTRA:
    for st in ("on", "off"):
        check(f"guardrails-{name}-{st} is a heredoc the terminal writes", f"guardrails-{name}-{st}" in HELPERS)
check("images/web-terminal/entrypoint.sh is kept byte-identical", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

print("== each switch, from the opposite state, on both linked clusters ==")
for name in NAMES + EXTRA:
    for st in ("on", "off"):
        cmd = f"guardrails-{name}-{st}"
        want = st == "on"
        r = run(cmd, start_on=not want)
        out, calls = r["out"], r["calls"]
        mine = groups_of(name)
        owned = {f for g in mine for f in FIELDS[g]}
        if ROLE_GROUPS & set(mine):
            owned |= {("infra", "rbac_scoped"), ("infra", "agency_scoped")}
        not_moved = [f"{ctx} {k}" for ctx in ("this", PEER) for g in mine for k in FIELDS[g]
                     if flat(r["end"][ctx])[k] is not want]
        moved = [f"{ctx} {k}" for ctx in ("this", PEER) for k, v in flat(r["end"][ctx]).items()
                 if k not in owned and v != flat(r["start"][ctx])[k]]
        check(f"{cmd}: exits 0, and {', '.join(mine)} read {st} on both clusters", r["rc"] == 0 and not not_moved,
              f"exit {r['rc']}, not {st}: {not_moved}\n{out}{r['err']}")
        check(f"{cmd}: leaves every other control as it was" + (", the on-topic guard among them"
                                                               if name in ("ai", "all") else ""),
              not moved, f"moved: {moved}")
        if name in ("ai", "all"):
            topic = [c for c in calls if "topic" in " ".join(c["args"])]
            check(f"{cmd}: sends nothing to the on-topic guard", not topic, str(topic))
        said = [ln for ln in out.splitlines() if f"this one and {PEER}" in ln]
        check(f"{cmd}: says for each of its {STEPS.get(name, 1)} step(s) that it switched this cluster and {PEER}",
              len(said) == STEPS.get(name, 1) and "⚠️" not in out, out)
        check(f"{cmd}: prints a `$ ` line for every kubectl it runs, in the order it runs them",
              shown(r["err"]) == calls and len(calls) > 2, f"{len(shown(r['err']))} shown, {len(calls)} ran")
        check(f"{cmd}: touches no cluster but {HERE} and {PEER}", {c["cluster"] for c in calls} == {"this", PEER},
              str({c["cluster"] for c in calls}))
        check(f"{cmd}: its last two calls read /controls, on this cluster, then on {PEER}",
              len(calls) >= 2 and all(is_controls(c) for c in calls[-2:])
              and [c["cluster"] for c in calls[-2:]] == ["this", PEER], json.dumps(calls[-2:])[:400])
        word = "ON" if want else "off"
        blocks = {HERE: read_block(out, f"{HERE} (this cluster), {HOSTS['this']}"),
                  PEER: read_block(out, f"{PEER}, {HOSTS[PEER]}")}
        labels = {LABEL[k] for g in mine for _, k in FIELDS[g]}
        check(f"{cmd}: ends on both clusters' /controls by name, {', '.join(sorted(labels))} {word} on each",
              all(b and labels <= set(b[word]) for b in blocks.values())
              and out.index("Read back from guard-proxy's /controls") > max(out.rfind(s) for s in said),
              out[-1500:])

print("== guardrails-all orders agency against k8s ==")
for st, roles, left in (("on", ["c5-scoped-role.yaml", "c6-least-privilege-role.yaml"], "c6-least-privilege-role.yaml"),
                        ("off", ["c5-scoped-role.yaml", "c8-broad-role.yaml"], "c8-broad-role.yaml")):
    r = run(f"guardrails-all-{st}", start_on=st == "off")
    check(f"guardrails-all-{st} applies {' then '.join(roles)} on each cluster, leaving {left}",
          all(r["end"][c].get("roles") == roles and r["end"][c]["role"] == left for c in ("this", PEER)),
          str({c: r["end"][c].get("roles") for c in ("this", PEER)}))

print("== a peer that cannot be reached: every step still runs, what failed is named, exit 1 ==")
for cmd, steps in (("guardrails-all-on", "k8s, agency, the guard-proxy guards, mcp"),
                   ("guardrails-all-off", "mcp, the guard-proxy guards, agency, k8s"),
                   ("guardrails-ai-on", "the guard-proxy guards, the MCP tool restriction"),
                   ("guardrails-input-on", None), ("guardrails-admission-on", None), ("guardrails-rbac-off", None)):
    r = run(cmd, start_on=cmd.endswith("-off"), mode="peer-down")
    want = cmd.endswith("-on")
    here_ok = all(flat(r["end"]["this"])[k] is want for g in groups_of(cmd.split("-")[1]) for k in FIELDS[g])
    check(f"{cmd}: exits 1, still switches this cluster", r["rc"] == 1 and here_ok, f"exit {r['rc']}\n{r['out']}")
    if steps:
        check(f"{cmd}: names every step that did not switch", f"these did not switch {cmd.rsplit('-', 1)[1]}: {steps}."
              in r["out"], r["out"])
    check(f"{cmd}: the read still runs and says {PEER}'s /controls could not be read",
          f"⚠️  {PEER}: /controls could not be read, so its state is not shown." in r["out"], r["out"][-800:])

print("== a lone cluster, the 2-hour lab's ==")
for cmd in ("guardrails-input-on", "guardrails-rbac-on", "guardrails-admission-on", "guardrails-agency-on"):
    r = run(cmd, mode="unlinked")
    check(f"{cmd}: switches and reads this cluster alone, exit 0",
          r["rc"] == 0 and "Switched on this cluster alone" in r["out"] and all(c["cluster"] == "this" for c in r["calls"])
          and is_controls(r["calls"][-1]), f"exit {r['rc']}\n{r['out']}")

print("== arguments ==")
r = run("guardrails-k8s-on", ("3",))
check("guardrails-k8s-on 3 switches and waits 3 s between guardrails", r["rc"] == 0, f"exit {r['rc']}\n{r['out']}")
r = run("guardrails-k8s-on", ("soon",))
check("guardrails-k8s-on soon: the usage code 2, its usage line names guardrails-k8s-on, nothing switched",
      r["rc"] == 2 and "Usage: guardrails-k8s-on [seconds" in r["out"]
      and not any("apply" in c["args"] or "patch" in c["args"] for c in r["calls"]), r["out"])
r = run("guardrails-mcp-on", ("60",))
check("guardrails-mcp-on 60 switches and times each cluster", r["rc"] == 0 and r["out"].count("⏱") == 2, r["out"])

print("== every old name is an alias of its new one ==")
WANT = {"guardrails-on": "guardrails-k8s-on", "guardrails-off": "guardrails-k8s-off", "guards-on": "guardrails-ai-on",
        "guards-off": "guardrails-ai-off", "guards-status": "guardrails-status"}
for g in ("agency", "input", "output", "mcp", "budget", "topic", "rbac", "admission"):
    for st in ("on", "off"):
        WANT[f"guard-{g}-{st}"] = f"guardrails-{g}-{st}"
check("the ALIASES table names every old switch, each with its guardrails- form", dict(ALIASES) == WANT,
      f"{sorted(set(dict(ALIASES).items()) ^ set(WANT.items()))}")
for old, new in ALIASES:
    for start_on in (False, True):
        args = ("0",) if new.startswith("guardrails-k8s") else ()
        a, b = run(old, args, start_on=start_on), run(new, args, start_on=start_on)
        first, _, rest = a["out"].partition("\n")
        note = " It leaves the on-topic guard as it is: guardrails-topic-off turns that off." if old == "guards-off" else ""
        check(f"{old} (from {'on' if start_on else 'off'}): says it is {new}, then runs exactly what {new} runs",
              first == f"({old} is now {new}; running that.{note})" and rest == b["out"] and a["err"] == b["err"]
              and a["calls"] == b["calls"] and a["rc"] == b["rc"] == 0 and a["end"] == b["end"],
              f"first line {first!r}; exit {a['rc']} vs {b['rc']}; same calls {a['calls'] == b['calls']}")
r = run("guardrails-on", ("x",))
check("an alias passes its arguments on: guardrails-on x is guardrails-k8s-on's usage error", r["rc"] == 2
      and "Usage: guardrails-k8s-on" in r["out"], r["out"])

# Self-check: an alias paired with the wrong switch is caught by the comparison above.
wrong = ALIAS_LOOP.group(0).replace("guard-output-on guardrails-output-on\n", "guard-output-on guardrails-input-on\n", 1)
if wrong == ALIAS_LOOP.group(0):
    sys.exit(f"ANCHOR MISSING: `guard-output-on guardrails-output-on` in the ALIASES table in {ENTRYPOINT}")
a, b = run("guard-output-on", aliases=wrong), run("guardrails-output-on")
check("self-check: guard-output-on paired with guardrails-input-on runs other calls than guardrails-output-on",
      a["calls"] != b["calls"])

print("== guardrails-status ==")
r = run("guardrails-status")
status = HELPERS["guardrails-status"]
missing = [n for n in NAMES + EXTRA if not re.search(rf"^echo \"  [^\"]*\b{n}\b", status, re.M)]
check("its help says guardrails-<name>-on and -off and names every switch", "guardrails-<name>-on and guardrails-<name>-off"
      in status and not missing, str(missing))
check("it says the old names still run", "The old names" in r["out"], r["out"])
check("it lists the AI guards, then ends on both clusters' /controls", r["rc"] == 0 and "Your AI guardrails right now:"
      in r["out"] and [c["cluster"] for c in r["calls"][-2:]] == ["this", PEER]
      and all(is_controls(c) for c in r["calls"][-2:]), r["out"])

print()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls)

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nevery stage switch is guardrails-<name>-on or -off on both KubeCon clusters, and every old name an alias (#1350)")
