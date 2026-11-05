# ABOUTME: Offline round trip of the #480 live-check.sh against a stateful kubectl stand-in: it changes what the check
# ABOUTME: needs, puts every object back exactly as found on success and on failure, and refuses to start when it should not.
"""live-check.sh runs on watch-it-burn-community, the public cluster the room attacks, and the coordinator's go on #480
says it must leave that cluster as it found it (attackme answering 200 after). It has never run on a cluster, so this
runs it, every phase, against verify/tool_pin_kubectl_shim.py, which holds the objects the script touches in one JSON
file. What is held here:

- `run` reaches every phase: the pinned bind is in the gateway config and evil-mcp points at it before any question is
  asked, the rug pull and deny mode happen, and the agent is restarted when kagent does not roll it;
- after `run`, every object is as it was before, the rug-pulled server.py is no longer what evil-mcp runs, and the
  public host was checked for 200;
- a failure in the middle of `run`, or a gateway that refuses the pinned config, still ends with everything as found;
- a gateway whose last reload failed before the check (it runs an older config than its ConfigMap, as on
  watch-it-burn-community on 2026-11-05) is restarted onto the pinned config, and restarted again by restore;
- `restore` exits 1 and keeps its snapshot when the cluster does not match it;
- `setup` changes nothing when the public host is not answering 200 or the context is unknown, and will not take a
  second snapshot over the first.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "docs/research/2026-10-24-tool-pin-spike"
SCRIPT = SPIKE / "live-check.sh"
SHIM = REPO / "verify/tool_pin_kubectl_shim.py"
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
CONTEXT = "watch-it-burn-community-test"
PINNED = "http://agentgateway.agent:3004/mcp"
ORIGINAL_URL = "http://agentgateway.agent:3003/mcp"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def cluster() -> dict:
    docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
    gw_cm = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "agentgateway-config")
    gw_svc = next(d for d in docs if d["kind"] == "Service" and d["metadata"]["name"] == "agentgateway")
    ingress = next(d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/chat-path-ingress.yaml").read_text(encoding="utf-8"))
                   if d and d["metadata"]["name"] == "agentgateway-ingress")
    server = (REPO / "gitops/ai-layer/server.py").read_text(encoding="utf-8")
    automated = {"prune": True, "selfHeal": True}

    def obj(ns, kind, name, **body):
        return f"{ns}/{kind}/{name}", {"kind": kind, "metadata": {"name": name, "namespace": ns}, **body}

    def deploy(name, **spec):
        return obj("agent", "Deployment", name, spec={"selector": {"matchLabels": {"app": name}}, **spec})

    def pod(ns, name, app, ip):
        return f"{ns}/Pod/{name}", {"kind": "Pod", "metadata": {"name": name, "namespace": ns, "labels": {"app": app}},
                                    "status": {"podIP": ip}}

    objects = dict([
        obj("agent", "ConfigMap", "agentgateway-config", data={"config.yaml": gw_cm["data"]["config.yaml"]}),
        obj("agent", "Service", "agentgateway", spec={"ports": copy.deepcopy(gw_svc["spec"]["ports"])}),
        obj("agent", "NetworkPolicy", "agentgateway-ingress", spec=copy.deepcopy(ingress["spec"])),
        obj("agent", "ConfigMap", "evil-mcp-src", data={"server.py": server}),
        obj("agent", "ConfigMap", "cluster-identity", data={"public-host": "attackme.agenticburn.com"}),
        obj("agent", "RemoteMCPServer", "evil-mcp", spec={"url": ORIGINAL_URL, "protocol": "STREAMABLE_HTTP"},
            status={"conditions": [{"type": "Accepted", "status": "True"}]}),
        deploy("evil-mcp-shim", template={"spec": {
            "volumes": [{"name": "src", "configMap": {"name": "evil-mcp-src"}}],
            "containers": [{"name": "shim", "image": "ghcr.io/peopleforrester/watch-it-burn:workshop-mcp-mcp-1.29.1@sha256:9a26"}]}}),
        deploy("workshop-agent", template={"spec": {"containers": [{"name": "kagent", "image": "kagent-adk"}]}}),
        deploy("agentgateway", template={"spec": {"containers": [{"name": "agentgateway", "image": "agw"}]}}),
        pod("agent", "workshop-agent-0", "workshop-agent", "10.1.0.1"),
        pod("agent", "evil-mcp-shim-0", "evil-mcp-shim", "10.1.0.2"),
        pod("kagent", "kagent-controller-0", "kagent-controller", "10.1.0.3"),
        *(obj("argocd", "Application", name,
              spec={"syncPolicy": {"automated": dict(automated), "syncOptions": ["ServerSideApply=true"]}},
              status={"sync": {"status": "Synced"}, "health": {"status": "Healthy"}})
          for name in ("lab-bootstrap", "ai-layer")),
    ])
    return {"objects": objects, "logs": ['info state_manager loaded config from File("/etc/agentgateway/config.yaml")'],
            "events": [], "running_src": server}


def as_found(st: dict) -> dict:
    """What 'as found' compares: every object but the Pods (a restart renames them), with the restart annotation a
    rollout restart leaves on a Deployment's template, plus the source evil-mcp is running."""
    objs = {}
    for k, o in st["objects"].items():
        if o["kind"] == "Pod":
            continue
        o = copy.deepcopy(o)
        if o["kind"] == "Deployment":
            o["spec"].get("template", {}).get("metadata", {}).get("annotations", {}).pop("kubectl.kubernetes.io/restartedAt", None)
            if not o["spec"].get("template", {}).get("metadata", {}).get("annotations", True):
                del o["spec"]["template"]["metadata"]["annotations"]
            if not o["spec"].get("template", {}).get("metadata", True):
                del o["spec"]["template"]["metadata"]
        objs[k] = o
    return {"objects": objs, "running_src": st["running_src"]}


class Bed:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir(parents=True)
        for name in ("kubectl", "curl"):
            shutil.copy(SHIM, self.bin / name)
            (self.bin / name).chmod((self.bin / name).stat().st_mode | stat.S_IXUSR)
        self.state_file = root / "cluster.json"
        self.before = cluster()
        self.state_file.write_text(json.dumps(self.before))
        self.snap = root / "snap"

    def live(self, phase: str, **env) -> subprocess.CompletedProcess:
        e = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "CONTEXT": env.pop("CONTEXT", CONTEXT),
             "TP_CONTEXT": CONTEXT, "TP_STATE": str(self.state_file), "STATE": str(self.snap), "SETTLE": "0",
             "TMPDIR": str(self.root)}
        e.pop("TP_FAIL", None)
        e.update(env)
        return subprocess.run(["bash", str(SCRIPT), phase], env=e, capture_output=True, text=True, timeout=600)

    def st(self) -> dict:
        return json.loads(self.state_file.read_text())


def events_matching(st: dict, needle: str) -> list[int]:
    return [i for i, ev in enumerate(st["events"]) if needle in ev]


with tempfile.TemporaryDirectory() as d:
    print("== run: every phase, then everything as found ==")
    bed = Bed(pathlib.Path(d) / "a")
    # A tools/list from a pod that is gone by the time observe runs, as a probe pod is (--rm): seen on the cluster.
    st0 = bed.st()
    st0["logs"].append("info request route=default/evil-mcp-pinned src.addr=10.9.9.9 mcp.method=tools/list")
    bed.state_file.write_text(json.dumps(st0))
    r = bed.live("run")
    out = r.stdout + r.stderr
    st = bed.st()
    # On a failure, the script's own "live-check: failed at line N" says where; the tail alone shows only the restore.
    why = [line for line in out.splitlines() if line.startswith("live-check:")]
    check("run exits 0" + ("" if r.returncode == 0 else f" (exit {r.returncode}; {why}; tail: {out[-300:]!r})"), r.returncode == 0)
    pinned_cfg = events_matching(st, 'patch ConfigMap/agentgateway-config {"data": {"config.yaml": ')
    to_pinned = events_matching(st, f'patch RemoteMCPServer/evil-mcp {{"spec": {{"url": "{PINNED}"}}}}')
    check("the pinned bind goes into the gateway config before evil-mcp is pointed at it",
          bool(pinned_cfg) and bool(to_pinned) and pinned_cfg[0] < to_pinned[0])
    restored = next(bed.snap.parent.glob("snap.restored-*"), None)
    pinned_cm = json.loads((restored / "gateway-pinned.json").read_text()) if restored else {"data": {"config.yaml": "{}"}}
    binds = yaml.safe_load(pinned_cm["data"]["config.yaml"]).get("binds", [])
    live_binds = yaml.safe_load(bed.before["objects"]["agent/ConfigMap/agentgateway-config"]["data"]["config.yaml"])["binds"]
    check("the pinned bind is added to the live config: its binds are all still there, then :3004",
          binds[:-1] == live_binds and binds[-1]["port"] == 3004)
    opened = events_matching(st, "patch NetworkPolicy/agentgateway-ingress")
    check("3004 is opened in agentgateway-ingress (#552) before the bind is probed, and closed again by restore",
          len(opened) == 2 and opened[0] < to_pinned[0] and '{"port": 3004, "protocol": "TCP"}' in st["events"][opened[0]]
          and '"port": 3004' not in st["events"][opened[1]])
    check("both Argo CD apps are paused before the first change and resumed at the end",
          events_matching(st, 'patch Application/lab-bootstrap {"spec": {"syncPolicy": {"automated": null}}}')[0] < pinned_cfg[0]
          and events_matching(st, 'patch Application/ai-layer {"spec": {"syncPolicy": {"automated": {"prune": true')[-1]
          < events_matching(st, 'patch Application/lab-bootstrap {"spec": {"syncPolicy": {"automated": {"prune": true')[-1])
    check("tool-pin is deployed from the spike's bundle and its source ConfigMap",
          bool(events_matching(st, "apply Deployment/tool-pin")) and bool(events_matching(st, "apply ConfigMap/tool-pin-src"))
          and bool(events_matching(st, "apply ConfigMap/tool-pin-baseline")))
    check("the rug pull and deny mode both happen, in that order",
          events_matching(st, "patch ConfigMap/evil-mcp-src")[0] < events_matching(st, "set env deploy/tool-pin PIN_MODE=deny")[0])
    check("a gateway that reloads is never restarted", not events_matching(st, "restart agentgateway"))
    check("kagent did not roll the agent here, so run restarts it, and restore restarts it again",
          "kagent did not roll workshop-agent" in out and len(events_matching(st, "restart workshop-agent")) == 2)
    check("each of the three phases asks, observes, and the rug-pulled ones call get_weather",
          all(p in out for p in ("1. strip mode", "2. rug pull", "3. deny mode"))
          and out.count("tools the agent touched") == 3 and out.count("-- get_weather called by name") == 2
          and '"isError": true' in out)
    check("observe names the pod behind each tools/list on the pinned bind",
          "10.1.0.3 kagent/kagent-controller-0" in out)
    check("a caller with no pod now reads as a probe, and does not trip the ERR trap",
          "10.9.9.9 (no pod now: a probe)" in out and "live-check: failed at line" not in out)
    check("everything is as found afterwards, the rug-pulled server.py included", as_found(st) == as_found(bed.before))
    check("restore checked the public host for 200 and every object, evil-mcp's Accepted condition included",
          "ok    https://attackme.agenticburn.com/ status" in out and "ok    evil-mcp's Accepted condition" in out
          and "FAIL" not in out)
    check("deny mode ran before restore, so that check had a False condition to wait out (the stand-in sets it)",
          bool(events_matching(st, "set env deploy/tool-pin PIN_MODE=deny")))
    check("the snapshot is moved aside and the record kept beside it",
          not bed.snap.exists() and any(p.name.startswith("snap.restored-") for p in bed.snap.parent.iterdir())
          and (bed.snap.parent / "snap.record.txt").exists())

    print("== a failure in the middle of run still puts everything back ==")
    bed = Bed(pathlib.Path(d) / "b")
    r = bed.live("run", TP_FAIL="set-env")
    out = r.stdout + r.stderr
    st = bed.st()
    check(f"run exits non-zero (exit {r.returncode})", r.returncode != 0)
    check("restore ran on the way out", "restore (exit 1)" in out and "ok    https://attackme.agenticburn.com/ status" in out)
    check("everything is as found, after a rug pull that had already happened",
          bool(events_matching(st, "patch ConfigMap/evil-mcp-src")) and as_found(st) == as_found(bed.before))

    print("== a gateway that refuses the pinned config ==")
    bed = Bed(pathlib.Path(d) / "c")
    r = bed.live("run", TP_FAIL="reload")
    out = r.stdout + r.stderr
    st = bed.st()
    check(f"run stops at once, naming the refusal (exit {r.returncode})",
          r.returncode != 0 and "the gateway refused the pinned config" in out)
    check("evil-mcp is never pointed at the refused bind", not events_matching(st, PINNED))
    check("everything is as found", as_found(st) == as_found(bed.before))

    print("== a gateway whose last reload failed before the check ==")
    bed = Bed(pathlib.Path(d) / "g")
    st0 = bed.st()
    st0["logs"].append("error state_manager Failed to reload config: cannot use deprecated config.tracing together "
                       "with frontendPolicies.tracing")
    st0["gateway_stale"] = True
    bed.state_file.write_text(json.dumps(st0))
    r = bed.live("run")
    out = r.stdout + r.stderr
    st = bed.st()
    why = [line for line in out.splitlines() if line.startswith("live-check:")]
    check("run exits 0" + ("" if r.returncode == 0 else f" (exit {r.returncode}; {why}; tail: {out[-300:]!r})"), r.returncode == 0)
    restarts = events_matching(st, "restart agentgateway")
    pinned_cfg = events_matching(st, 'patch ConfigMap/agentgateway-config {"data": {"config.yaml": ')
    to_pinned = events_matching(st, f'patch RemoteMCPServer/evil-mcp {{"spec": {{"url": "{PINNED}"}}}}')
    check("setup says the gateway refuses reloads and restarts it after the pinned config and before evil-mcp moves",
          "refuses reloads" in out and len(restarts) == 2 and len(pinned_cfg) == 2
          and pinned_cfg[0] < restarts[0] < to_pinned[0])
    check("restore restarts it again after putting its config back, and checks it loaded",
          pinned_cfg[1] < restarts[1] and "ok    the restarted gateway's config load" in out and "FAIL" not in out)
    check("everything is as found, the gateway now on its own ConfigMap",
          as_found(st) == as_found(bed.before) and st["gateway_stale"] is False)

    print("== restore that cannot put a thing back says so and keeps the snapshot ==")
    bed = Bed(pathlib.Path(d) / "d")
    r = bed.live("setup")
    check("setup alone exits 0" + ("" if r.returncode == 0 else f" (exit {r.returncode}; {r.stderr[-300:]!r})"), r.returncode == 0)
    check("after setup evil-mcp dials the pinned bind", bed.st()["objects"]["agent/RemoteMCPServer/evil-mcp"]["spec"]["url"] == PINNED)
    r2 = bed.live("setup")
    check("a second setup refuses to snapshot over the first", r2.returncode == 1 and "run restore first" in r2.stderr)
    r = bed.live("restore", TP_FAIL="restore-url")
    check("restore exits 1 when evil-mcp's url cannot be put back", r.returncode == 1 and "FAIL  evil-mcp's url" in r.stdout)
    check("and keeps the snapshot for another try", (bed.snap / "snapshot.done").exists())
    r = bed.live("restore")
    check(f"the second restore exits 0 and everything is as found (exit {r.returncode})",
          r.returncode == 0 and as_found(bed.st()) == as_found(bed.before))

    print("== setup refuses to start, changing nothing ==")
    bed = Bed(pathlib.Path(d) / "e")
    r = bed.live("setup", TP_PUBLIC_CODE="503")
    check("when the public host is not answering 200 first", r.returncode == 1 and "does not answer 200 before" in r.stderr
          and bed.st()["events"] == [])
    r = bed.live("run", CONTEXT="some-other-cluster")
    check("when the context is not in the kubeconfig", r.returncode == 1 and "no context some-other-cluster" in r.stderr
          and bed.st()["events"] == [])

    print("== when kagent rolls the agent itself ==")
    bed = Bed(pathlib.Path(d) / "f")
    r = bed.live("run", TP_KAGENT_ROLLS="1")
    out = r.stdout + r.stderr
    st = bed.st()
    check("run says so and does not restart the agent itself",
          r.returncode == 0 and "kagent rolled workshop-agent" in out and not events_matching(st, "restart workshop-agent"))
    check("everything is as found", as_found(st) == as_found(bed.before))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll live-check round-trip checks passed.")
