# ABOUTME: Offline gate for #1148: guard-input-on and guard-input-off set the input block-list and classifier on this
# ABOUTME: cluster's guard-proxy and the KubeCon peer's, the peer through a Service proxy grant held to that one Service.
"""#1148, the second piece of #1132. guard-input-on and guard-input-off used to call /toggle only on the guard-proxy of
the cluster whose terminal ran them, while the room plays on the public bot. They now run `_both _toggle <query>` from
~/.guardlib (gitops/ai-layer/web-terminal/entrypoint.sh): on this cluster the kubectl exec into deploy/guard-proxy it
always was (_px), and on the other KubeCon cluster a GET through the API server's Service proxy,
/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/toggle?<query>, as its guardrails-switch ServiceAccount.

Checked here, with a kubectl on PATH that plays two clusters, each with a guard-proxy that keeps its guard state:
  * linked: both set input_blocklist and input_classifier on both clusters, say so naming the peer, and every
    printed `$ ` line, run by bash, makes the call it made;
  * the peer's API cannot be reached, or it refuses: this cluster switches, the run fails and names the peer;
  * no guardrails-peer Secret (the 2-hour workshop's): this cluster switches alone, one line says so, exit 0;
  * a peer Secret that cannot be read: this cluster switches and the run fails, never passing as unlinked;
  * this cluster refuses: the peer still switches, the run fails;
  * what the two ask of the peer, read as the API server's authorizer reads a request, is inside guardrails-switch's
    grant, and the grant's guard-proxy part is get on services/proxy for guard-proxy:8080 and nothing more: no
    pods/exec, pods/portforward or pods/proxy, and that name is the guard-proxy Service's port in ai-layer.
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
PROXY_PATH = "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/toggle"
STEP_SECONDS = 300
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


# A kubectl that plays two clusters, each with a guard-proxy. A call with --kubeconfig is the peer, named by its
# --context; any other is this cluster. A /toggle, by exec on deploy/guard-proxy or by get --raw on its Service proxy,
# sets that cluster's guards the way proxy.py's do_GET does and prints its answer. MODE picks the case.
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
    sys.stderr.write("Unable to connect to the server: net/http: request canceled (Client.Timeout exceeded)\n"); sys.exit(1)
if mode == "peer-forbidden" and ctx != "this":
    sys.stderr.write('Error from server (Forbidden): services "guard-proxy:8080" is forbidden\n'); sys.exit(1)
if mode == "here-down" and ctx == "this":
    sys.stderr.write("Error from server (Forbidden)\n"); sys.exit(1)
query = None
if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"]:
    code = a[a.index("-c") + 1]
    query = code.split("http://localhost:8080/toggle?", 1)[1].split("'", 1)[0]
elif a[:2] == ["get", "--raw"] and a[2].startswith("/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/toggle?"):
    query = urlparse(a[2]).query
if query is not None:
    g = state.setdefault(ctx, {"input_blocklist": False, "input_classifier": False, "output": False})
    q = parse_qs(query)
    for k in ("input_blocklist", "input_classifier", "output", "budget", "topic"):
        if k in q:
            g[k] = q[k][0].lower() == "on"
    print(json.dumps(g))
json.dump(state, open(os.environ["STATE"], "w"))
'''

helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT.read_text(encoding="utf-8"), re.S))


def timed(argv: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=STEP_SECONDS, **kw)
    except subprocess.TimeoutExpired:
        sys.exit(f"FAILED: {' '.join(argv)[:200]} ran past {STEP_SECONDS} seconds")


def run(cmd: str, mode: str) -> dict:
    """Run one terminal command against the fake: its exit code, output, the calls it made, the calls its printed `$ `
    lines make when bash runs them again, and each cluster's guard state afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        home.mkdir(); fakebin.mkdir()  # noqa: E702
        for name, body in helpers.items():
            (home / name).write_text(body + "\n")
        (fakebin / "kubectl").write_text(FAKE)
        (fakebin / "kubectl").chmod(0o755)
        calls, state = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "state")
        state.write_text("{}")
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls),
               "STATE": str(state), "MODE": mode}
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
                "state": json.loads(state.read_text())}


def toggles(r: dict) -> list[tuple[str, str]]:
    """(cluster, how) for each /toggle call: "exec" for the kubectl exec into deploy/guard-proxy, "proxy" for the GET
    on guard-proxy's Service proxy."""
    out = []
    for c in r["calls"]:
        a = c["args"]
        if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"]:
            out.append((c["cluster"], "exec"))
        elif a[:2] == ["get", "--raw"] and a[2].startswith(PROXY_PATH + "?"):
            out.append((c["cluster"], "proxy"))
    return out


QUERY = {"guard-input-on": "input_blocklist=on&input_classifier=on",
         "guard-input-off": "input_blocklist=off&input_classifier=off"}
ON = {"guard-input-on": True, "guard-input-off": False}
EXPLAINS = {"guard-input-on": "INPUT guards ON", "guard-input-off": "INPUT guards OFF"}


def inputs(r: dict, cluster: str) -> tuple:
    g = r["state"].get(cluster, {})
    return g.get("input_blocklist"), g.get("input_classifier")


print("== guard-input-on and guard-input-off run _both _toggle, from the entrypoint the KubeCon terminals run ==")
lib = helpers.get(".guardlib", "")
check("the terminal ships .guardlib, guard-input-on and guard-input-off",
      {".guardlib", "guard-input-on", "guard-input-off"} <= set(helpers))
check(".guardlib defines _toggle beside _both and _px", all(re.search(rf"^{f}\(\) \{{", lib, re.M)
                                                           for f in ("_toggle", "_both", "_px")))
for cmd, q in QUERY.items():
    body = helpers.get(cmd, "")
    check(f"{cmd} sets both input stages through _both _toggle, and runs no kubectl or _px of its own",
          f'_both _toggle "{q}"' in body and "kubectl" not in body and "_px" not in body, body)
check("images/web-terminal/entrypoint.sh is kept byte-identical to it", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

print("== on two linked clusters ==")
for cmd, q in QUERY.items():
    r = run(cmd, "linked")
    out = r["stdout"] + r["stderr"]
    check(f"{cmd}: exits 0", r["rc"] == 0, out)
    check(f"{cmd}: calls /toggle on this cluster by exec, then on {PEER} through its Service proxy, once each",
          toggles(r) == [("this", "exec"), (PEER, "proxy")], str(toggles(r)))
    peer_call = next((c["args"] for c in r["calls"] if c["cluster"] == PEER and c["args"][:2] == ["get", "--raw"]), [])
    check(f"{cmd}: the peer's call is get --raw {PROXY_PATH}?{q}, bounded at 20 seconds",
          peer_call == ["get", "--raw", f"{PROXY_PATH}?{q}", "--request-timeout=20s"], str(peer_call))
    check(f"{cmd}: input_blocklist and input_classifier are {'on' if ON[cmd] else 'off'} on both clusters afterwards",
          inputs(r, "this") == (ON[cmd], ON[cmd]) and inputs(r, PEER) == (ON[cmd], ON[cmd]), str(r["state"]))
    check(f"{cmd}: no other guard is touched on either cluster",
          all(r["state"].get(c, {}).get("output") is False and set(r["state"].get(c, {})) ==
              {"input_blocklist", "input_classifier", "output"} for c in ("this", PEER)), str(r["state"]))
    check(f"{cmd}: says it switched both clusters, naming {PEER}",
          f"Switched on both clusters: this one and {PEER}." in r["stdout"], r["stdout"])
    check(f"{cmd}: still explains what the input guards do", EXPLAINS[cmd] in r["stdout"], r["stdout"])
    check(f"{cmd}: every line it prints, run by bash, makes the call it made, in order",
          r["replayed"] == r["calls"] and len(r["calls"]) == 4, f"\n    shown: {r['replayed']}\n    ran:   {r['calls']}")
    others = [c for c in r["calls"] if c["cluster"] not in ("this", PEER)]
    check(f"{cmd}: touches no cluster but these two", not others, str(others))

print("== the peer cannot be reached, or refuses ==")
for mode in ("peer-down", "peer-forbidden"):
    for cmd in QUERY:
        r = run(cmd, mode)
        check(f"{cmd} ({mode}): still sets both stages on this cluster", inputs(r, "this") == (ON[cmd], ON[cmd]),
              str(r["state"]))
        check(f"{cmd} ({mode}): fails, naming {PEER} as the cluster it could not reach",
              r["rc"] == 1 and f"not on {PEER}: it could not be reached, or it refused the change." in r["stdout"],
              r["stdout"])
        check(f"{cmd} ({mode}): leaves out the explanation, which would read as done, and says to try again",
              EXPLAINS[cmd] not in r["stdout"] and f"try '{cmd}' again" in r["stdout"], r["stdout"])

print("== a cluster with no guardrails-peer Secret, the 2-hour workshop's ==")
for cmd in QUERY:
    r = run(cmd, "unlinked")
    lines = [line for line in r["stdout"].splitlines() if line.strip()]
    alone = [line for line in lines if "alone" in line]
    check(f"{cmd}: sets both stages here by exec and exits 0",
          r["rc"] == 0 and inputs(r, "this") == (ON[cmd], ON[cmd]) and toggles(r) == [("this", "exec")],
          r["stdout"] + r["stderr"])
    check(f"{cmd}: says in one line that this cluster was switched alone",
          alone == ["Switched on this cluster alone: it has no guardrails-switch/guardrails-peer Secret, so no other "
                    "cluster is linked to it."], str(lines))
    check(f"{cmd}: and still explains what the input guards do", EXPLAINS[cmd] in r["stdout"], r["stdout"])
    check(f"{cmd}: touches no other cluster, and every printed line replays its call",
          {c["cluster"] for c in r["calls"]} == {"this"} and r["replayed"] == r["calls"], str(r["calls"]))

print("== a peer Secret this cluster cannot read is a failure, not the 2-hour workshop ==")
for cmd in QUERY:
    r = run(cmd, "secret-unreadable")
    check(f"{cmd}: sets both stages here, then fails saying the other cluster was not switched",
          r["rc"] == 1 and inputs(r, "this") == (ON[cmd], ON[cmd])
          and "guardrails-switch/guardrails-peer could not be read" in r["stdout"] and "alone" not in r["stdout"],
          r["stdout"])

print("== this cluster refuses ==")
for cmd in QUERY:
    r = run(cmd, "here-down")
    check(f"{cmd}: fails, says this cluster did not switch, and still switches {PEER}",
          r["rc"] == 1 and "not on this cluster" in r["stdout"] and inputs(r, PEER) == (ON[cmd], ON[cmd]),
          r["stdout"])

print("== the peer's grant: get on guard-proxy's Service proxy by name, nothing more ==")
sw = docs(SWITCH.read_text(encoding="utf-8"))
GRANT: dict[tuple[str, str, str], set[str]] = {}
for d in sw:
    if d["kind"] in ("Role", "ClusterRole"):
        scope = d["metadata"].get("namespace", "")
        for rule in d["rules"]:
            for res in rule["resources"]:
                for name in rule.get("resourceNames") or ["*"]:
                    GRANT.setdefault((scope, res, name), set()).update(rule["verbs"])
proxy_grants = {k: v for k, v in GRANT.items() if k[1] == "services/proxy"}
check("services/proxy is granted for guard-proxy:8080 alone, in agent, with get alone",
      proxy_grants == {("agent", "services/proxy", "guard-proxy:8080"): {"get"}}, str(proxy_grants))
pod_reach = sorted(k for k in GRANT if k[1].startswith("pods") or k[1] in ("services", "nodes/proxy", "*"))
check("no pods, pods/exec, pods/portforward, pods/proxy, services or nodes/proxy grant, so no other way into a pod",
      not pod_reach, str(pod_reach))
svc = next(d for d in docs(RESOURCES.read_text(encoding="utf-8")) if d.get("kind") == "Service"
           and d["metadata"]["name"] == "guard-proxy")
check("guard-proxy:8080 names a port the guard-proxy Service serves",
      any(p.get("port") == 8080 for p in svc["spec"]["ports"]), str(svc["spec"]["ports"]))


def authz(args: list[str]) -> tuple[str, str, str, str]:
    """The (namespace, resource, name, verb) the API server's authorizer sees for one kubectl call made through
    the peer kubeconfig. get --raw is a GET on its path; an exec is create on pods/exec, whose pod name the caller
    cannot know in advance."""
    if args[:2] == ["get", "--raw"]:
        parts = urlparse(args[2]).path.strip("/").split("/")
        assert parts[:3] == ["api", "v1", "namespaces"], args
        ns, res, name, *rest = parts[3:]
        return ns, f"{res}/{rest[0]}" if rest else res, name, "get"
    if "exec" in args:
        return "agent", "pods/exec", "*", "create"
    return "?", " ".join(args[:3]), "?", "?"


for cmd in QUERY:
    r = run(cmd, "linked")
    need = {authz(c["args"]) for c in r["calls"] if c["cluster"] == PEER}
    missing = sorted(n for n in need if n[3] not in GRANT.get(n[:3], set()))
    check(f"{cmd}: everything it asks of {PEER} is inside the guardrails-switch grant", bool(need) and not missing,
          f"asks {sorted(need)}, missing {missing}")
    q = parse_qs(urlparse(next((c["args"][2] for c in r["calls"] if c["cluster"] == PEER
                                and c["args"][:2] == ["get", "--raw"]), "")).query)
    check(f"{cmd}: the peer's /toggle sets input_blocklist and input_classifier and no other guard",
          sorted(q) == ["input_blocklist", "input_classifier"], str(q))

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
print("All guard-input two-cluster checks passed.")
