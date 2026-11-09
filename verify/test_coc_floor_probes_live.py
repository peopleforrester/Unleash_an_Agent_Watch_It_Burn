# ABOUTME: Live check of #1267's probe criterion (#1293): with the code-of-conduct floor on and every guardrail off on
# ABOUTME: both KubeCon clusters, verify/kubecon_probe.py's admin and community runs are green, every challenge beat passing.
# SUITE: e2e
"""Needs kubectl, PRIVATE_CONTEXT and COMMUNITY_CONTEXT naming the kube-contexts of the private admin cluster
(watch-it-burn-private) and the community cluster (watch-it-burn-community), both in one kubeconfig, and the public
internet. Every missing prerequisite is a failure, never a skip.

#1267 put a code-of-conduct floor under the talk: checks no toggle turns off. Its criterion on the probe is that every
challenge still lands with that floor on and every guardrail off: the KubeCon probe's community and admin runs green.
This test holds that, in three steps.

1. The start, on both clusters, read before any model call:
   - the floor is on, each of its four layers read where it runs: guard-proxy's `/controls` reports
     `always_on.code_of_conduct` true (the /chat refusal and the reply mask), the `code-of-conduct-names`
     ValidatingAdmissionPolicyBinding exists (the admission policy), the running workshop-mcp's /app/server.py calls
     `_refuse_coc` (deploy_app's check, #1269), and a collector ConfigMap in `monitoring` runs `transform/coc_mask` in a
     pipeline (#1277);
   - every guardrail is off: `/controls` reports every AI guard off and every infrastructure guardrail the stage
     switches off (networkpolicy, kyverno, kubearmor, tool_allowlist, rbac_scoped, agency_scoped), and the probe's own
     judge_at_start finds the cluster at the stage's start state (AI guards off, the rogue tools offered, the C7
     gateway rule open, the four Kubernetes guardrails present and off). Falco's badge is not one of them: it reads
     whether the Falco DaemonSet is ready, which no switch changes, and the private cluster runs it.
   When either does not hold, no probe runs and no model call is spent: a green probe then would say nothing about
   the floor.
2. The probes, admin first, then community, each as `python3 verify/kubecon_probe.py ... --json`: each exits 0 and
   prints KUBECON PROBE GREEN, and every beat of its run (kubecon_probe.ADMIN with guards-off, kubecon_probe.COMMUNITY
   with guardrails-off) is reported and PASS, every challenge beat (a Beat with a stage) among them. The lists are read
   off the probe, so a challenge beat added there is required here.
3. The end, on both clusters: the floor is still on, and every guardrail is off again.

When a probe is red, the guard-proxy events of the floor (`conduct_refused`, `conduct_masked`) logged on both clusters
since the probes started are printed under it, to show whether the floor touched a turn. They are printed, not
checked: a room turn the floor refused in that window would read the same.

The guard lock. The test holds verify/guard_lease.py's lock on both clusters (run_held with the private cluster's
guardrails peer) from before the start read until after the end read, so no other run switches a guard or a guardrail
between them. Each probe it runs finds the hold in WIB_GUARD_LEASE and joins it rather than waiting on it. When another
run keeps the lock for the whole wait (30 minutes by default), the test fails naming the holder, having read nothing.

What it spends: both probe runs, about $0.25 to $0.45 of Bedrock over 24 model calls (run 19724 on #1267), which counts
on /cost until the counter is reset. Each probe holds the guard lock on both clusters (verify/guard_lease.py) and leaves
them at the start state. About 15 minutes, longer when another run holds a lock.

verify/test_coc_floor_probes_live_checks.py runs run_checks against fake clusters and fake probe runs, one healthy and
one per way the criterion can stop holding, and holds that each of those ways fails here.

Usage: PRIVATE_CONTEXT=<ctx> COMMUNITY_CONTEXT=<ctx> [KUBECONFIG=<isolated file>] python3 verify/test_coc_floor_probes_live.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Callable, Protocol

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import kubecon_probe as kp  # noqa: E402

PROBE = HERE / "kubecon_probe.py"
# The infrastructure badges of /controls that a stage switch turns on: guardrails-on (networkpolicy, kyverno, kubearmor,
# rbac_scoped), guard-agency-on (agency_scoped) and guard-mcp-on (tool_allowlist). Falco's badge is left out on purpose.
INFRA_SWITCHED = ("networkpolicy", "kyverno", "kubearmor", "tool_allowlist", "rbac_scoped", "agency_scoped")
FLOOR_LAYERS = ("admission", "deploy_check", "collector_mask")
FLOOR_EVENTS = ("conduct_refused", "conduct_masked")
PROBE_TIMEOUT_S = 3600


def expected_beats(role: str) -> list[kp.Beat]:
    """Every beat a run of this role reports, in order, its final beat included."""
    return [*kp.ADMIN, kp.GUARDS_OFF_BEAT] if role == "admin" else [*kp.COMMUNITY, kp.GUARDRAILS_OFF_BEAT]


def judge_floor_on(name: str, controls: dict | None, layers: dict[str, bool]) -> list[str]:
    """What keeps the floor from reading on, on one cluster, each problem naming the cluster."""
    bad = []
    if controls is None:
        bad.append("/controls could not be read")
    elif (controls.get("always_on") or {}).get("code_of_conduct") is not True:
        bad.append(f"/controls always_on reads {controls.get('always_on')!r}: guard-proxy's /chat check is off")
    why = {"admission": "the code-of-conduct-names ValidatingAdmissionPolicyBinding is missing",
           "deploy_check": "the running workshop-mcp's deploy_app does not call _refuse_coc",
           "collector_mask": "no collector ConfigMap in monitoring runs transform/coc_mask in a pipeline"}
    bad += [why[k] for k in FLOOR_LAYERS if layers.get(k) is not True]
    return [f"{name}: {b}" for b in bad]


def judge_guardrails_off(name: str, controls: dict | None, m: dict) -> list[str]:
    """What keeps every guardrail from reading off, on one cluster: the badges, then the probe's own start-state read."""
    bad = []
    if controls is None:
        bad.append("/controls could not be read")
    else:
        ai = controls.get("ai") or {}
        if not ai:
            bad.append("/controls reports no AI guards at all")
        bad += [f"/controls AI guard {k} on" for k, v in ai.items() if v]
        infra = controls.get("infra") or {}
        bad += [f"/controls {k} on" for k in INFRA_SWITCHED if infra.get(k)]
        bad += [f"/controls reports no {k} badge" for k in INFRA_SWITCHED if k not in infra]
    return [f"{name}: {b}" for b in bad] + kp.judge_at_start(name, m)


def parse_probe(out: str) -> list[dict] | None:
    """The beat results the probe printed with --json, or None when it printed none (KUBECON PROBE NOT RUN)."""
    start = next((i for i, line in enumerate(out.splitlines(keepends=True)) if line.startswith("[")), None)
    if start is None:
        return None
    text = "".join(out.splitlines(keepends=True)[start:])
    try:
        results, _ = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    return results if isinstance(results, list) else None


def judge_probe(role: str, rc: int, out: str) -> list[str]:
    """What keeps one probe run from green with every beat, every challenge beat among them, reported and PASS."""
    bad = []
    if rc != 0:
        bad.append(f"exited {rc}")
    if "KUBECON PROBE GREEN" not in out.splitlines():
        last = [ln for ln in out.splitlines() if ln.startswith("KUBECON PROBE")]
        bad.append(f"printed {last[-1] if last else 'no KUBECON PROBE verdict'}, not KUBECON PROBE GREEN")
    results = parse_probe(out)
    if results is None:
        return [f"{role}: {b}" for b in bad + ["printed no beat results"]]
    by_key = {r.get("key"): r for r in results}
    for beat in expected_beats(role):
        r = by_key.get(beat.key)
        kind = "challenge beat" if beat.stage else "beat"
        if r is None:
            bad.append(f"{kind} {beat.key} was not reported")
        elif r.get("verdict") != kp.PASS:
            bad.append(f"{kind} {beat.key} {r.get('verdict')}: {r.get('note')}")
    bad += [f"beat {r.get('key')} {r.get('verdict')}: {r.get('note')}" for r in results
            if r.get("key") not in {b.key for b in expected_beats(role)} and r.get("verdict") != kp.PASS]
    return [f"{role}: {b}" for b in bad]


def floor_events(lines: list[str]) -> list[str]:
    """guard-proxy's JSON log lines for the floor's own events."""
    out = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("event") in FLOOR_EVENTS:
            out.append(f"{d.get('timestamp')} {d.get('event')}")
    return out


def collector_masks(configmaps: list[dict]) -> bool:
    """A collector config among these ConfigMaps lists transform/coc_mask in a pipeline's processors."""
    for cm in configmaps:
        for text in (cm.get("data") or {}).values():
            if "transform/coc_mask" not in (text or ""):
                continue
            try:
                cfg = yaml.safe_load(text)
            except yaml.YAMLError:
                continue
            pipelines = ((cfg or {}).get("service") or {}).get("pipelines") or {} if isinstance(cfg, dict) else {}
            if any("transform/coc_mask" in (p or {}).get("processors", []) for p in pipelines.values()):
                return True
    return False


def deploy_checks(server_py: str) -> bool:
    """workshop-mcp's server.py defines _refuse_coc and calls it."""
    return "def _refuse_coc(" in server_py and server_py.count("_refuse_coc(") >= 2


class Cluster(Protocol):
    name: str

    def host(self) -> str | None: ...
    def controls(self) -> dict | None: ...
    def floor_layers(self) -> dict[str, bool]: ...
    def measure(self) -> dict: ...
    def floor_log(self, since: dt.datetime) -> list[str]: ...


class LiveCluster:
    """One KubeCon cluster, read with kubectl on its named context and over https at its cluster-identity host."""

    def __init__(self, context: str, kubeconfig: str | None) -> None:
        self.name = context
        self.kubeconfig = kubeconfig
        self.k = kp.KubeconCluster("", context, None, kubeconfig, timeout=120.0)

    def host(self) -> str | None:
        h = self.k.identity_host()
        if h:
            self.k.host = h
        return h or None

    def controls(self) -> dict | None:
        return self.k.get_json("/controls")

    def floor_layers(self) -> dict[str, bool]:
        rc, _ = self.k._stdout_rc("get", "validatingadmissionpolicybinding", "code-of-conduct-names", "-o", "name")
        rc_src, src = self.k._stdout_rc("-n", "agent", "exec", "deploy/workshop-mcp", "-c", "shim", "--",
                                        "cat", "/app/server.py")
        rc_cm, cms = self.k._stdout_rc("-n", "monitoring", "get", "configmap", "-o", "json")
        try:
            items = json.loads(cms).get("items", []) if rc_cm == 0 else []
        except ValueError:
            items = []
        return {"admission": rc == 0, "deploy_check": rc_src == 0 and deploy_checks(src),
                "collector_mask": collector_masks(items)}

    def measure(self) -> dict:
        return self.k.measure()

    def floor_log(self, since: dt.datetime) -> list[str]:
        rc, out = self.k._stdout_rc("-n", "agent", "logs", "deploy/guard-proxy", "--all-containers",
                                    f"--since-time={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        return out.splitlines() if rc == 0 else [f"(guard-proxy's log could not be read: {out.strip()[:200]})"]


def run_probe(role: str, host: str, context: str, switch_context: str | None, kubeconfig: str | None) -> tuple[int, str]:
    """One probe run, its results as JSON on stdout; its log goes to stderr as it runs, so progress shows."""
    cmd = [sys.executable, str(PROBE), role, host, "--context", context, "--json"]
    if switch_context:
        cmd += ["--switch-context", switch_context]
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, timeout=PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") if isinstance(e.stdout, str) else ""
    return r.returncode, r.stdout


ProbeRunner = Callable[[str, str, str, "str | None"], tuple[int, str]]


def state_checks(when: str, clusters: list[Cluster], check: Callable[[str, bool, str], None]) -> bool:
    """The floor on and every guardrail off on each cluster; True when both hold on all of them."""
    ok = True
    for c in clusters:
        controls = c.controls()
        floor = judge_floor_on(c.name, controls, c.floor_layers())
        check(f"{when}: the code-of-conduct floor is on on {c.name}", not floor, "; ".join(floor))
        try:
            m = c.measure()
        except Exception as e:  # noqa: BLE001 - an unreadable cluster is a failed state, not a crash
            m = {}
            off = [f"{c.name}: could not be read: {e}"]
        else:
            off = judge_guardrails_off(c.name, controls, m)
        check(f"{when}: every guardrail is off on {c.name}", not off, "; ".join(off))
        ok = ok and not floor and not off
    return ok


def run_checks(private: Cluster, community: Cluster, probe: ProbeRunner,
               check: Callable[[str, bool, str], None]) -> None:
    """Every check after the prerequisites: the start state, both probes, the end state."""
    hosts, named = {}, True
    for c, want in ((private, False), (community, True)):
        h = c.host()
        is_community = kp.identity_name(h) in {kp.identity_name(x) for x in kp.COMMUNITY_HOSTS}
        ok = bool(h) and is_community == want
        check(f"{c.name} is the {'community' if want else 'private admin'} cluster", ok,
              f"its cluster-identity public-host is {h!r}")
        hosts[c.name], named = h, named and ok
    if not named or private.name == community.name:
        check("the probes ran", False, "not run: the two contexts are not the private and community clusters")
        return

    if not state_checks("at the start", [private, community], check):
        check("the probes ran", False, "not run, so no model call is spent: the start is not the floor on with "
                                       "every guardrail off, so a green probe would say nothing about the criterion")
        return

    since = dt.datetime.now(dt.timezone.utc)
    red = False
    for role, c, switch in (("admin", private, None), ("community", community, private.name)):
        print(f"-- the {role} probe on {c.name} ({hosts[c.name]}) --", flush=True)
        rc, out = probe(role, hosts[c.name], c.name, switch)
        bad = judge_probe(role, rc, out)
        n = len(parse_probe(out) or [])
        check(f"the {role} probe is green with the floor on: every one of its {len(expected_beats(role))} beats, "
              f"every challenge beat among them, PASS ({n} reported)", not bad, "; ".join(bad))
        red = red or bool(bad)

    if red:
        for c in (private, community):
            events = floor_events(c.floor_log(since))
            print(f"  (diagnostic) the floor's guard-proxy events on {c.name} since the probes started: "
                  f"{', '.join(events) if events else 'none'}")
    state_checks("at the end", [private, community], check)


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""),
              flush=True)
        if not cond:
            failures.append(name)

    private_ctx = os.environ.get("PRIVATE_CONTEXT", "")
    community_ctx = os.environ.get("COMMUNITY_CONTEXT", "")
    kubeconfig = os.environ.get("KUBECONFIG") or None
    missing = []
    if not private_ctx:
        missing.append("PRIVATE_CONTEXT is not set: name the kube-context of the private admin cluster")
    if not community_ctx:
        missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if not missing:
        for ctx in (private_ctx, community_ctx):
            r = subprocess.run(["kubectl", "--context", ctx, "--request-timeout=15s", "get", "--raw", "/readyz"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                missing.append(f"cluster for context {ctx!r} is not reachable: {(r.stderr or r.stdout).strip()[:200]}")
    if missing:
        print("FAILED: the floor-on probe check cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== #1267's criterion: the KubeCon probes green with the floor on and every guardrail off "
          f"({private_ctx}, {community_ctx}) ==", flush=True)
    # The whole check holds the guard lock on both clusters (#1016): the private cluster's and the one its
    # guardrails-peer Secret names, as the probe does. The start and end reads then see no other run's switch, and each
    # probe, which inherits WIB_GUARD_LEASE, joins this hold instead of waiting on it, so no run gets in between.
    body = lambda: run_checks(LiveCluster(private_ctx, kubeconfig), LiveCluster(community_ctx, kubeconfig),  # noqa: E731
                              lambda role, host, ctx, switch: run_probe(role, host, ctx, switch, kubeconfig), check)
    if not guard_lease.run_held(private_ctx, body, check, "verify/test_coc_floor_probes_live.py", with_peer=True,
                                kubeconfig=kubeconfig):
        return guard_lease.BUSY_EXIT

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All floor-on probe checks passed: every challenge lands with the floor on and every guardrail off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
