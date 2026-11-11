# ABOUTME: Offline gate for #1271: finale-cap-on, finale-cap-off and cost-watch, run in the KubeCon private terminal,
# ABOUTME: act on watch-it-burn-community's guard-proxy through guardrails-peer, and on this cluster anywhere else.
"""#1271. The break-it finale capped the room's bot, on watch-it-burn-community, whose terminal no presenter can open. The
three commands now pick the room's cluster with _room in ~/.guardlib (gitops/ai-layer/web-terminal/entrypoint.sh): on
the cluster whose lab-bootstrap Application is labelled lab-platform/profile=kubecon-private it is the peer, reached
with the guardrails-peer kubeconfig through the API server's Service proxy on guard-proxy:8080; anywhere else it is
this cluster, by the kubectl exec into deploy/guard-proxy the finale always used.

Two real guard-proxy instances (the pinned proxy.py, loaded twice, so each keeps its own tally and cap) serve on
localhost: one is this cluster, one is the peer. A kubectl on PATH plays both: an exec runs its python3 -c snippet here
against this cluster's proxy, and a `--kubeconfig ... get --raw <service proxy path>` is a GET on the peer's.

Checked:
  * private and linked: finale-cap-on sets the peer's cap to its spend plus the headroom, leaves this cluster's at $25,
    names watch-it-burn-community and says the private cluster is unchanged; cost-watch draws the peer's spend and
    cap; finale-cap-off restores the peer's $25; every printed `$ ` line, run by bash, makes the call it made;
  * every call to the peer is a get --raw on guard-proxy's Service proxy, which guardrails-switch's Role already
    grants (get on services/proxy guard-proxy:8080), so the finale adds no grant;
  * on the community cluster (a peer Secret there names the private one) and on a cluster with no KubeCon profile,
    the three act on this cluster by exec and never read guardrails-peer;
  * private with an unreadable peer Secret, Argo CD that cannot be asked, or a peer that cannot be reached: the
    command fails saying so, and neither cluster's cap moves;
  * the run-of-show and /kubecon say the three stay in the private terminal. Since Michael cut the finale at the
    rehearsal of 2026-11-11 (rounds-agenticburn#172, #1348) no step of the close runs them; verify/test_finale_cap.py
    holds that.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
TWIN = REPO / "images/web-terminal/entrypoint.sh"
SWITCH = REPO / "gitops/guardrails-switch/guardrails-switch.yaml"
ROS = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
KUBECON = REPO / "gitops/ai-layer/web/kubecon.html"
PEER = "watch-it-burn-community"
PROXY = "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy"
STEP_SECONDS = 120
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


os.environ["COST_CAP_USD"] = "25"
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
sys.path.insert(0, str(REPO / "gitops/ai-layer/guard-proxy"))


def serve(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "gitops/ai-layer/guard-proxy/proxy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.Handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return mod, srv


here, here_srv = serve("guard_proxy_finale_here")
peer, peer_srv = serve("guard_proxy_finale_peer")
PORTS = {"this": here_srv.server_address[1], PEER: peer_srv.server_address[1]}
check("the two guard-proxy instances keep separate tallies", here is not peer and here._cost_cap is not peer._cost_cap)


def cost(cluster: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORTS[cluster]}/cost", timeout=5) as r:
        return json.load(r)


def spend(mod, input_tokens: int, output_tokens: int = 0) -> None:
    mod.record_usage({"result": {"metadata": {"kagent_usage_metadata": {
        "promptTokenCount": input_tokens, "candidatesTokenCount": output_tokens,
        "totalTokenCount": input_tokens + output_tokens}}}})


def reset_caps() -> None:
    for c in PORTS:
        urllib.request.urlopen(f"http://127.0.0.1:{PORTS[c]}/toggle?cost_cap=default", timeout=5).read()


# A kubectl that plays two clusters. A call with --kubeconfig is the peer, named by its --context; any other is this
# cluster. PROFILE is this cluster's lab-bootstrap label; MODE picks a failure.
FAKE = r'''#!/usr/bin/env python3
import base64, json, os, subprocess, sys, urllib.request
a = sys.argv[1:]
if "--kubeconfig" in a:
    i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]
    j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]
else:
    ctx = "this"
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"cluster": ctx, "args": a}) + "\n")
mode, ports = os.environ["MODE"], json.loads(os.environ["PORTS"])
if "application" in a and "lab-bootstrap" in a:
    if mode == "argocd-down":
        sys.stderr.write("Unable to connect to the server: i/o timeout\n"); sys.exit(1)
    sys.stdout.write(os.environ["PROFILE"]); sys.exit(0)
if "guardrails-peer" in a:
    if mode == "secret-unreadable":
        sys.stderr.write("Unable to connect to the server: i/o timeout\n"); sys.exit(1)
    named = b"watch-it-burn-community" if os.environ["PROFILE"] == "kubecon-private" else b"watch-it-burn-private"
    print(base64.b64encode(b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in a[-1] else named).decode())
    sys.exit(0)
if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"] and ctx == "this":
    code = a[a.index("-c") + 1].replace("localhost:8080", "127.0.0.1:%d" % ports["this"])
    sys.exit(subprocess.run([sys.executable, "-c", code]).returncode)
PREFIX = "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy"
if a[:2] == ["get", "--raw"] and a[2].startswith(PREFIX + "/") and ctx in ports and ctx != "this":
    if mode == "peer-down":
        sys.stderr.write("Unable to connect to the server: net/http: request canceled\n"); sys.exit(1)
    path = a[2][len(PREFIX):]
    # As the real kubectl does, --request-timeout=N goes on the URL as timeout=N, which the Service proxy hands on
    # to guard-proxy: /cost then reads /cost?timeout=20s, which guard-proxy does not match (#1271's live run).
    for x in a:
        if x.startswith("--request-timeout="):
            path += ("&" if "?" in path else "?") + "timeout=" + x.split("=", 1)[1]
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (ports[ctx], path), timeout=10) as r:
        sys.stdout.write(r.read().decode())
    sys.exit(0)
sys.stderr.write("fake kubectl: no such call on %s: %s\n" % (ctx, a)); sys.exit(1)
'''

helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT.read_text(encoding="utf-8"), re.S))


class Box:
    """A HOME with the terminal's helpers and the fake kubectl on PATH."""

    def __init__(self, tmp: str, profile: str, mode: str = "ok"):
        self.home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        self.home.mkdir(); fakebin.mkdir()  # noqa: E702
        for name, body in helpers.items():
            (self.home / name).write_text(body + "\n")
        (fakebin / "kubectl").write_text(FAKE)
        (fakebin / "kubectl").chmod(0o755)
        self.calls, self.replay = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "replay")
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{fakebin}:{os.environ['PATH']}",
                    "CALLS": str(self.calls), "PROFILE": profile, "MODE": mode, "PORTS": json.dumps(PORTS)}

    def run(self, *cmd: str) -> dict:
        start = len(self.calls.read_text().splitlines()) if self.calls.exists() else 0
        try:
            r = subprocess.run(["bash", str(self.home / cmd[0]), *cmd[1:]], env=self.env, capture_output=True,
                               text=True, timeout=STEP_SECONDS)
        except subprocess.TimeoutExpired:
            sys.exit(f"FAILED: {cmd} ran past {STEP_SECONDS} seconds")
        ran = [json.loads(x) for x in self.calls.read_text().splitlines()[start:]] if self.calls.exists() else []
        shown = [x[2:] for x in (r.stdout + r.stderr).splitlines() if x.startswith("$ ")]
        if self.replay.exists():
            self.replay.unlink()
        for line in shown:
            subprocess.run(["bash", "-c", line], env={**self.env, "CALLS": str(self.replay)}, capture_output=True,
                           timeout=STEP_SECONDS)
        replayed = [json.loads(x) for x in self.replay.read_text().splitlines()] if self.replay.exists() else []
        h = str(self.home)
        norm = lambda c: {"cluster": c["cluster"], "args": [x.replace(h, "$HOME") for x in c["args"]]}  # noqa: E731
        return {"rc": r.returncode, "stdout": r.stdout.replace(h, "$HOME"), "stderr": r.stderr.replace(h, "$HOME"),
                "calls": [norm(c) for c in ran], "replayed": [norm(c) for c in replayed]}

    def frame(self) -> str:
        """cost-watch's first whole frame; it loops until Ctrl-C, so it is read until "(Ctrl-C to stop)" and killed."""
        w = subprocess.Popen(["bash", str(self.home / "cost-watch")], env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        lines: list[str] = []
        framed = threading.Event()

        def read() -> None:
            for ln in iter(w.stdout.readline, ""):
                lines.append(ln)
                if "(Ctrl-C to stop)" in ln:
                    framed.set()
                    return

        threading.Thread(target=read, daemon=True).start()
        framed.wait(90)
        w.kill()
        w.wait()
        return "".join(lines)


def peer_calls(r: dict) -> list[list[str]]:
    return [c["args"] for c in r["calls"] if c["cluster"] == PEER]


def guard_proxy_calls(r: dict) -> list[tuple[str, str]]:
    out = []
    for c in r["calls"]:
        a = c["args"]
        if a[:4] == ["-n", "agent", "exec", "deploy/guard-proxy"]:
            out.append((c["cluster"], "exec"))
        elif a[:2] == ["get", "--raw"] and a[2].startswith(PROXY + "/"):
            out.append((c["cluster"], "proxy " + a[2][len(PROXY):].split("=")[0]))
    return out


print("== the terminal ships the finale through _room ==")
lib = helpers.get(".guardlib", "")
check(".guardlib defines _room, _gpc, _gp and _room_after beside _peer",
      all(re.search(rf"^{f}\(\) \{{", lib, re.M) for f in ("_room", "_gpc", "_gp", "_room_after", "_peer")))
for cmd in ("finale-cap-on", "finale-cap-off", "cost-watch"):
    body = helpers.get(cmd, "")
    check(f"{cmd} picks the room's cluster with _room and runs no kubectl of its own",
          "_room || exit 1" in body and "kubectl" not in body, body)
check("images/web-terminal/entrypoint.sh is kept byte-identical to it", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

print("== the private terminal, linked: the finale caps watch-it-burn-community and leaves this cluster alone ==")
reset_caps()
spend(here, 100_000)
spend(peer, 300_000, 4_000)
with tempfile.TemporaryDirectory() as tmp:
    box = Box(tmp, "kubecon-private")
    before_here, before_peer = cost("this"), cost(PEER)
    r = box.run("finale-cap-on", "0.50")
    out = r["stdout"] + r["stderr"]
    check("finale-cap-on exits 0", r["rc"] == 0, out)
    check("the community cluster's cap is its spend plus $0.50",
          abs(cost(PEER)["cap_usd"] - (before_peer["usd"] + 0.50)) < 1e-3, str(cost(PEER)))
    check("the private cluster's cap is still $25 and its tally untouched",
          cost("this")["cap_usd"] == 25.0 and cost("this")["usd"] == before_here["usd"], str(cost("this")))
    check("the community cluster's tally is kept", abs(cost(PEER)["usd"] - before_peer["usd"]) < 1e-9)
    check(f"it names {PEER}, its spend and its new cap",
          f"Finale cap ON on {PEER}. It has spent ${before_peer['usd']:.2f}; the cap is now "
          f"${before_peer['usd'] + 0.50:.2f}" in r["stdout"], r["stdout"])
    check("it says which cluster changed and that the private one did not",
          f"Changed: {PEER} only. This cluster, the private one, is unchanged." in r["stdout"], r["stdout"])
    check("guard-proxy is reached only on the peer, /cost then /toggle?cost_cap, through its Service proxy",
          guard_proxy_calls(r) == [(PEER, "proxy /cost"), (PEER, "proxy /toggle?cost_cap")], str(guard_proxy_calls(r)))
    check("every printed line, run by bash, makes the call it made, in order",
          r["replayed"] == r["calls"] and len(r["calls"]) == 5, f"\n    shown: {r['replayed']}\n    ran:   {r['calls']}")
    pc = peer_calls(r)
    check("each call to the peer is a get --raw on guard-proxy's Service proxy, with no --request-timeout, which "
          "would put ?timeout= on guard-proxy's path",
          bool(pc) and all(a[:2] == ["get", "--raw"] and a[2].startswith(PROXY + "/") and len(a) == 3 for a in pc),
          str(pc))
    raw_lines = [x for x in r["stderr"].splitlines() if f"get --raw {PROXY}" in x or f"get --raw '{PROXY}" in x]
    check("and each is bounded at 20 seconds by timeout(1), as its printed line shows",
          len(raw_lines) == 2 and all(x.startswith("$ timeout 20 kubectl --kubeconfig") for x in raw_lines),
          str(raw_lines))

    shown = box.frame()
    check("cost-watch draws a whole frame", "(Ctrl-C to stop)" in shown, shown[-400:])
    check(f"cost-watch shows {PEER}'s spend and cap, by name",
          f"BurritoBot, {PEER}" in shown and f"SPENT  ${cost(PEER)['usd']:.4f}" in shown
          and f"CAP    ${cost(PEER)['cap_usd']:.2f}" in shown, shown[-400:])
    check("cost-watch shows the command it runs, the get --raw on the peer's /cost",
          f"$ timeout 20 kubectl --kubeconfig $HOME/.kube/peer --context {PEER} get --raw {PROXY}/cost   ("
          in shown.replace(str(box.home), "$HOME"), shown[:600])

    # the room spends past the headroom on the community cluster, at the MODEL_TIER row, and the cap trips there only
    prices = peer.TIER_PRICES_PER_1K.get(peer.MODEL_TIER, peer.TIER_PRICES_PER_1K["haiku"])
    spend(peer, int(0.6 / prices["in"] * 1000))
    check("past it, the community cluster's guard-proxy refuses for everyone", peer.cost_capped() == "cost_cap")
    check("and the private bot still answers", not here.cost_capped())
    check("cost-watch then shows the cap hit on the community cluster", "CAP HIT" in box.frame())

    r = box.run("finale-cap-off")
    check("finale-cap-off exits 0", r["rc"] == 0, r["stdout"] + r["stderr"])
    check("the community cluster's cap is $25 again, and the private one's still $25",
          cost(PEER)["cap_usd"] == 25.0 and cost("this")["cap_usd"] == 25.0, f"{cost(PEER)} {cost('this')}")
    check(f"it names {PEER} and says the private cluster is unchanged",
          f"Finale cap OFF on {PEER}." in r["stdout"]
          and f"Changed: {PEER} only. This cluster, the private one, is unchanged." in r["stdout"], r["stdout"])
    check("finale-cap-off reaches guard-proxy on the peer alone, once",
          guard_proxy_calls(r) == [(PEER, "proxy /toggle?cost_cap")], str(guard_proxy_calls(r)))
    check("and its printed lines replay its calls", r["replayed"] == r["calls"], str(r["calls"]))

print("== the peer's grant already covers the finale; nothing is added ==")
GRANT: dict[tuple[str, str, str], set[str]] = {}
for d in (d for d in yaml.safe_load_all(SWITCH.read_text(encoding="utf-8")) if d):
    if d["kind"] in ("Role", "ClusterRole"):
        for rule in d["rules"]:
            for res in rule["resources"]:
                for name in rule.get("resourceNames") or ["*"]:
                    GRANT.setdefault((d["metadata"].get("namespace", ""), res, name), set()).update(rule["verbs"])
check("guardrails-switch holds get on services/proxy guard-proxy:8080 in agent, the one verb a get --raw needs",
      GRANT.get(("agent", "services/proxy", "guard-proxy:8080")) == {"get"}, str(GRANT))
check("and no other guard-proxy or pod route: no pods/exec, pods/proxy or pods/portforward",
      not [k for k in GRANT if k[1] in ("pods/exec", "pods/proxy", "pods/portforward")]
      and [k for k in GRANT if k[1] == "services/proxy"] == [("agent", "services/proxy", "guard-proxy:8080")],
      str(sorted(GRANT)))

print("== anywhere but the private cluster, the finale acts on this cluster ==")
for profile in ("kubecon-community", "admin", ""):
    reset_caps()
    with tempfile.TemporaryDirectory() as tmp:
        box = Box(tmp, profile)
        before = cost("this")["usd"]
        r = box.run("finale-cap-on", "1.00")
        label = profile or "no profile"
        check(f"{label}: finale-cap-on caps this cluster at its spend plus $1.00 and leaves the peer's at $25",
              r["rc"] == 0 and abs(cost("this")["cap_usd"] - (before + 1.0)) < 1e-3 and cost(PEER)["cap_usd"] == 25.0,
              r["stdout"] + r["stderr"])
        check(f"{label}: by exec into deploy/guard-proxy, never reading guardrails-peer or calling the peer",
              guard_proxy_calls(r) == [("this", "exec"), ("this", "exec")] and not peer_calls(r)
              and not any("guardrails-peer" in c["args"] for c in r["calls"]), str(r["calls"]))
        check(f"{label}: it says this cluster changed",
              "Finale cap ON on this cluster." in r["stdout"] and "Changed: this cluster only." in r["stdout"],
              r["stdout"])
        check(f"{label}: and prints the exec it ran, which replays it",
              "$ kubectl -n agent exec deploy/guard-proxy -- python3 -c" in r["stderr"] and r["replayed"] == r["calls"],
              r["stderr"])
        shown = box.frame()
        check(f"{label}: cost-watch shows this cluster", "BurritoBot, this cluster" in shown
              and f"CAP    ${cost('this')['cap_usd']:.2f}" in shown, shown[-400:])
        r = box.run("finale-cap-off")
        check(f"{label}: finale-cap-off puts this cluster back on $25", r["rc"] == 0 and cost("this")["cap_usd"] == 25.0
              and "Finale cap OFF on this cluster." in r["stdout"] and not peer_calls(r), r["stdout"] + r["stderr"])

print("== a failure changes neither cluster ==")
FAILS = {
    ("kubecon-private", "secret-unreadable"): "guardrails-switch/guardrails-peer could not be read",
    ("kubecon-private", "argocd-down"): "Argo CD could not be asked which cluster this is",
    ("kubecon-community", "argocd-down"): "Argo CD could not be asked which cluster this is",
}
for (profile, mode), says in FAILS.items():
    for cmd in ("finale-cap-on", "finale-cap-off", "cost-watch"):
        reset_caps()
        urllib.request.urlopen(f"http://127.0.0.1:{PORTS[PEER]}/toggle?cost_cap=3", timeout=5).read()
        urllib.request.urlopen(f"http://127.0.0.1:{PORTS['this']}/toggle?cost_cap=4", timeout=5).read()
        with tempfile.TemporaryDirectory() as tmp:
            r = Box(tmp, profile, mode).run(cmd)
        check(f"{profile}, {mode}: {cmd} exits 1 saying why, and no guard-proxy is called",
              r["rc"] == 1 and says in r["stderr"] and not guard_proxy_calls(r), r["stdout"] + r["stderr"])
        check(f"{profile}, {mode}: {cmd} leaves both caps where they were",
              cost(PEER)["cap_usd"] == 3.0 and cost("this")["cap_usd"] == 4.0, f"{cost(PEER)} {cost('this')}")
reset_caps()
with tempfile.TemporaryDirectory() as tmp:
    box = Box(tmp, "kubecon-private", "peer-down")
    for cmd in ("finale-cap-on", "finale-cap-off"):
        r = box.run(cmd)
        check(f"private, the peer unreachable: {cmd} exits 1 naming {PEER}, and the private cap stays $25",
              r["rc"] == 1 and f"{PEER}'s guard-proxy" in r["stdout"] and cost("this")["cap_usd"] == 25.0
              and not [g for g in guard_proxy_calls(r) if g[0] == "this"], r["stdout"] + r["stderr"])
    check("private, the peer unreachable: cost-watch says it is waiting rather than showing this cluster",
          "waiting for guard-proxy" in box.frame())
with tempfile.TemporaryDirectory() as tmp:
    box = Box(tmp, "kubecon-private")
    for bad in ("lots", ".", "1.2.3", "-1"):
        r = box.run("finale-cap-on", bad)
        check(f"a headroom of {bad!r} is a usage error and runs nothing", r["rc"] == 2 and not r["calls"], r["stdout"])

print("== the run-of-show and /kubecon say the three stay in the private terminal (#1348) ==")
ros = " ".join(ROS.read_text(encoding="utf-8").split())
kc = " ".join(KUBECON.read_text(encoding="utf-8").split())
ROS_STAY = "Those three stay in the private terminal"
PAGE_STAY = "They stay in the private terminal"
check("the run-of-show says the finale's three commands stay in the private terminal", ROS_STAY in ros)
check("/kubecon says the same, and neither names the public terminal for them",
      PAGE_STAY in kc and "public cluster's terminal" not in ros and "public terminal" not in kc)

here_srv.shutdown()
peer_srv.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("From the private terminal the finale commands cap, show and restore the room's cluster, and only that one.")
