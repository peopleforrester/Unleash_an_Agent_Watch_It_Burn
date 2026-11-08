# ABOUTME: Live check for #885's last criterion (#1056): with the turn guard synced on attackme, the 150-user load
# ABOUTME: replay of the recorded prompts ends with 0 PROXY_TIMEOUT 502s, read from the replay and guard-proxy's log.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of the community cluster (attackme, the live public bot),
the public internet, and the recorded prompts. Every missing prerequisite is a failure, never a skip.

On 2026-11-05 #644's 150-user replay on attackme ended with 5 turns cut at guard-proxy's 120 s PROXY_TIMEOUT, each one
an agent tool loop, and the phone read "BurritoBot's kitchen isn't answering" after two minutes. #885 put a per-turn
cap on repeated tool calls in workshop-mcp, keyed on guard-proxy's trace id, which the Agent forwards to workshop-mcp
as traceparent. Its last criterion: once the change is synced on attackme,

    python3 verify/load_replay.py attackme.burritobot.co --yes --users 150 --harvest <harvest prompts dir>

ends with 0 PROXY_TIMEOUT 502s. This runs that command, with --json-out added so the verdict is read from the replay's
own report, and fails when the criterion stops holding:

1. the context is attackme: its cluster-identity public-host is attackme's;
2. the change is what attackme runs: the Agent's workshop-mcp entry forwards traceparent, workshop-mcp mounts git's
   tool_audit.py (the guard) and has rolled out, and guard-proxy runs git's PROXY_TIMEOUT and has rolled out. When any
   of these fails the replay is not sent and nothing is spent;
3. the replay sent every planned turn (150 users x 3) and each came back, and the turns reached the model: at least
   one served and none refused by the cluster's cost cap, so a capped counter cannot pass it on refusals alone;
4. no turn came back 502 after PROXY_TIMEOUT or longer. guard-proxy answers a forward that ran past PROXY_TIMEOUT with
   a 502 whose body is its /chat JSON, never sooner (proxy.py's _forward), so a 502 that took that long is one. Every
   other 502 is printed too, and counted by load_replay.py's own LOAD REPLAY verdict, which this does not judge;
5. guard-proxy logged no "forward deadline (PROXY_TIMEOUT) passed" line while the replay ran, and its pod neither
   restarted nor changed in that time, so the log it read covers the whole replay.

The prompts. The criterion's harvest is the DevOpsDays Portland 2026 one, gitignored because it holds attendee-typed
text. LOAD_REPLAY_HARVEST names its prompts/ directory; unset, it is load_replay.py's own default,
.harvest/devopsdays-portland/prompts in this checkout. A directory with no *.json is a failure. On hecaton's host the
harvest is read from the operator's checkout through the sources route (decisions.md, #1056).

What it changes, and puts back. The replay spends at most 450 model calls on the public bot, each marked [[wib-probe]]
so the room's feed skips it: about $3 of Bedrock in run 18561, which stays on /cost until `./fleet.sh reset-bot
watch-it-burn-community` before the room opens. The harvest holds the room's attacks, so the bot deploys what they ask
for. Afterwards every object in namespace agent that workshop-mcp created during the replay and Argo CD does not manage
is deleted, by the rule fleet.sh's clear_bot_workloads uses, limited to objects that were not there before it, and
their rows, with the rows of any older object workshop-mcp applied over, are removed from the one deployments page
(/desk-forget, #1215). An older object workshop-mcp applied over is named, not reverted. The cleanup runs whatever the
replay's verdict.

verify/test_load_replay_live_checks.py runs these checks offline on the readings of 2026-11-05 (5 PROXY_TIMEOUT 502s,
which fail) and of run 18561 on 2026-11-08 (none, which pass), and on each way the criterion can stop holding.

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] [LOAD_REPLAY_HARVEST=<prompts dir>] \\
           python3 verify/test_load_replay_live.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402
import load_replay  # noqa: E402

TARGET = "attackme.burritobot.co"
USERS = 150
LOAD_REPLAY = HERE / "load_replay.py"
TOOL_AUDIT = REPO / "gitops" / "ai-layer" / "tool_audit.py"
HARVEST_ENV = "LOAD_REPLAY_HARVEST"
# guard-proxy's log line for a forward PROXY_TIMEOUT ended (proxy.py _forward's TimeoutError, logged as forward_error).
TIMEOUT_LOG = "forward deadline (PROXY_TIMEOUT) passed"
# The header the Agent forwards to workshop-mcp alone, which the guard keys each turn on (#885).
TURN_HEADER = "traceparent"
# The kinds deploy_app can create (workshop-mcp-server.py _API_VERSIONS), read back to find what the replay made.
BOT_KINDS = "deployments,statefulsets,daemonsets,replicasets,pods,services,configmaps,jobs,cronjobs"
BOT_MANAGER = "workshop-mcp"
# --since-time and managedFields times are the cluster's clock, so each window opens this far before the replay.
SKEW_S = 10
# load_replay.py's --deadline (900 s) stops new turns; a turn already sent then has nginx's 285 s to end.
REPLAY_TIMEOUT_S = 1800
# guard-proxy's pods, by the selector its Deployment uses.
PROXY_SELECTOR = "app.kubernetes.io/name=guard-proxy"


def replay_argv(harvest: pathlib.Path, json_out: pathlib.Path) -> list[str]:
    """The criterion's command, word for word, with --json-out added so the verdict is read from its report."""
    return [sys.executable, str(LOAD_REPLAY), TARGET, "--yes", "--users", str(USERS), "--harvest", str(harvest),
            "--json-out", str(json_out)]


def git_proxy_timeout() -> float:
    """guard-proxy's PROXY_TIMEOUT as git ships it (gitops/ai-layer/resources.yaml)."""
    return float(kp._proxy_env()["PROXY_TIMEOUT"])


def harvest_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get(HARVEST_ENV) or load_replay.DEFAULT_HARVEST).expanduser()


# --- the judges, run offline by test_load_replay_live_checks.py ------------------------------------------------------
def rolled_out(dep: dict | None) -> tuple[bool, str]:
    """Every replica of the Deployment is updated and available at its current generation."""
    if not dep:
        return False, "no such Deployment"
    st, replicas = dep.get("status") or {}, dep["spec"].get("replicas", 1)
    if (st.get("observedGeneration") != dep["metadata"].get("generation")
            or st.get("updatedReplicas") != replicas or st.get("availableReplicas") != replicas):
        return False, (f"not rolled out: {st.get('updatedReplicas')} of {replicas} updated, "
                       f"{st.get('availableReplicas')} available")
    return True, f"{replicas} replica(s) rolled out"


def mcp_src_configmap(mcp_dep: dict | None) -> str | None:
    """The ConfigMap workshop-mcp mounts at /app (workshop-mcp-src, its name suffixed with a hash by kustomize)."""
    spec = ((mcp_dep or {}).get("spec") or {}).get("template", {}).get("spec", {})
    for v in spec.get("volumes") or []:
        name = (v.get("configMap") or {}).get("name") or ""
        if name.startswith("workshop-mcp-src"):
            return name
    return None


def judge_synced(agent: dict | None, mcp_dep: dict | None, mcp_tool_audit: str | None, git_tool_audit: str,
                 proxy_dep: dict | None, git_timeout: float) -> list[tuple[bool, str, str]]:
    """Is #885's change what attackme runs? (ok, check, detail) each."""
    out = []
    tools = (((agent or {}).get("spec") or {}).get("declarative") or {}).get("tools") or []
    entry = next((t.get("mcpServer") or {} for t in tools if (t.get("mcpServer") or {}).get("name") == "workshop-mcp"),
                 None)
    headers = (entry or {}).get("allowedHeaders") or []
    out.append((TURN_HEADER in headers, f"the Agent forwards {TURN_HEADER} to workshop-mcp, the turn the guard counts",
                "no workshop-mcp tool on the workshop-agent Agent" if entry is None
                else f"its allowedHeaders are {headers}"))
    ok, note = rolled_out(mcp_dep)
    same = mcp_tool_audit is not None and mcp_tool_audit == git_tool_audit
    out.append((same and ok, "workshop-mcp runs git's tool_audit.py, the turn guard, and has rolled out",
                note if same else ("its ConfigMap holds no tool_audit.py" if mcp_tool_audit is None
                                   else "its tool_audit.py differs from git's: Argo CD has not synced it")))
    env = {}
    for c in (((proxy_dep or {}).get("spec") or {}).get("template", {}).get("spec", {}).get("containers") or []):
        if c.get("name") == "proxy":
            env = {e.get("name"): e.get("value") for e in c.get("env") or []}
    ok, note = rolled_out(proxy_dep)
    got = env.get("PROXY_TIMEOUT")
    try:
        same = got is not None and float(got) == git_timeout
    except ValueError:
        same = False
    out.append((same and ok, f"guard-proxy runs git's PROXY_TIMEOUT {git_timeout:g} and has rolled out",
                note if same else f"its PROXY_TIMEOUT is {got!r}"))
    return out


def proxy_timeout_502s(report: dict, timeout: float) -> list[dict]:
    """The turns that came back 502 after PROXY_TIMEOUT or longer: guard-proxy's answer to a forward it cut off."""
    return [u for u in report.get("unreadable") or []
            if u.get("status") == 502 and float(u.get("latency_s") or 0) >= timeout]


def log_timeouts(log_text: str) -> list[str]:
    """guard-proxy's log lines for a forward PROXY_TIMEOUT ended."""
    return [ln.strip() for ln in log_text.splitlines() if TIMEOUT_LOG in ln]


def judge_replay(report: dict | None, timeout: float, log_lines: list[str] | None,
                 pods_before: dict, pods_after: dict) -> list[tuple[bool, str, str]]:
    """Did the replay end with 0 PROXY_TIMEOUT 502s, and did it run enough to say so? (ok, check, detail) each."""
    if report is None:
        return [(False, "the replay wrote its report", "load_replay.py wrote no --json-out report (output above)")]
    o = report.get("outcomes") or {}
    planned = USERS * 3
    sent, answered = report.get("sent"), report.get("answered")
    out = [(report.get("users") == USERS and report.get("planned") == planned and sent == planned
            and answered == sent,
            f"the replay sent every planned turn ({USERS} users x 3) and each came back",
            f"users {report.get('users')}, planned {report.get('planned')}, sent {sent}, answered {answered}"
            + (f", stopped: {report['stop_reason']}" if report.get("stop_reason") else ""))]
    out.append((int(o.get("served") or 0) > 0 and int(o.get("cost_cap") or 0) == 0,
                "the turns reached the model: some served and none refused by the cluster's cost cap",
                f"served {o.get('served')}, cost cap {o.get('cost_cap')}"))
    cut = proxy_timeout_502s(report, timeout)
    others = [u for u in report.get("unreadable") or [] if u.get("status") == 502 and u not in cut]
    out.append((not cut, f"0 PROXY_TIMEOUT 502s: no turn came back 502 after {timeout:g} s or longer",
                f"{len(cut)}: " + "; ".join(f"{u.get('at')} after {u.get('latency_s')} s, session {u.get('session')}"
                                            for u in cut)))
    if others:
        print(f"  note  {len(others)} other 502(s), under {timeout:g} s, which load_replay.py's own verdict counts: "
              + "; ".join(f"{u.get('at')} after {u.get('latency_s')} s, {u.get('answered_by')}" for u in others))
    if log_lines is None:
        out.append((False, "guard-proxy's log during the replay was read", "kubectl could not read it"))
    else:
        out.append((not log_lines, f"guard-proxy logged no '{TIMEOUT_LOG}' during the replay",
                    f"{len(log_lines)}: " + " | ".join(ln[:240] for ln in log_lines[:10])))
    out.append((bool(pods_before) and pods_before == pods_after,
                "guard-proxy's pod neither restarted nor changed during the replay, so its log covers it",
                f"before {pods_before}, after {pods_after}"))
    return out


def stamp(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rfc3339(text: str | None) -> float:
    try:
        return dt.datetime.strptime(text or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return 0.0


def bot_writes(items: list[dict], before_uids: set[str], since: float) -> tuple[list[str], list[str]]:
    """What workshop-mcp applied at or after `since` and Argo CD does not manage, as kind/name: (made, applied over).
    Made is what was not there before the replay; applied over is an older object it wrote to during it."""
    made, over = [], []
    for o in items:
        md = o.get("metadata") or {}
        fields = md.get("managedFields") or []
        managers = {f.get("manager") for f in fields}
        if BOT_MANAGER not in managers or any(str(m).startswith("argocd") for m in managers if m):
            continue
        if not any(f.get("manager") == BOT_MANAGER and _rfc3339(f.get("time")) >= since - SKEW_S for f in fields):
            continue
        ref = f"{o.get('kind', '').lower()}/{md.get('name')}"
        (over if md.get("uid") in before_uids else made).append(ref)
    return made, over


# --- the cluster -----------------------------------------------------------------------------------------------------
class LiveCluster(kp.KubeconCluster):
    """The probe's cluster, plus the reads and deletes this check needs."""

    def get_json(self, *args: str) -> dict | None:
        rc, out = self._stdout_rc(*args, "-o", "json")
        try:
            return json.loads(out) if rc == 0 and out.strip() else None
        except json.JSONDecodeError:
            return None

    def configmap_key(self, name: str, key: str) -> str | None:
        cm = self.get_json("-n", "agent", "get", "configmap", name)
        return ((cm or {}).get("data") or {}).get(key)

    def proxy_pods(self) -> dict:
        """guard-proxy's pods: name to restart count, so a restart or a new pod during the replay shows."""
        d = self.get_json("-n", "agent", "get", "pods", "-l", PROXY_SELECTOR) or {}
        return {p["metadata"]["name"]: sum(int(s.get("restartCount") or 0)
                                           for s in (p.get("status") or {}).get("containerStatuses") or [])
                for p in d.get("items") or []}

    def proxy_log_since(self, since: float) -> str | None:
        rc, out = self._stdout_rc("-n", "agent", "logs", "-l", PROXY_SELECTOR, "-c", "proxy", "--tail=-1",
                                  "--max-log-requests=10", f"--since-time={stamp(since - SKEW_S)}")
        return out if rc == 0 else None

    def bot_objects(self) -> list[dict]:
        d = self.get_json("-n", "agent", "get", BOT_KINDS, "--show-managed-fields")
        if d is None:
            raise RuntimeError(f"kubectl could not list {BOT_KINDS} in namespace agent")
        return d.get("items") or []

    def delete(self, ref: str) -> tuple[bool, str]:
        rc, out = self.kubectl_rc("-n", "agent", "delete", ref, "--ignore-not-found", "--wait=true", "--timeout=120s",
                                  timeout=150)
        return rc == 0, out.strip()[-200:]


def run_checks(cluster, replay: Callable[[], dict | None], check: Callable[[str, bool, str], None],
               git_tool_audit: str, git_timeout: float, now: Callable[[], float] = time.time) -> dict | None:
    """Every check after the prerequisites, against one cluster. Returns the replay's report (None when not sent)."""
    host = cluster.identity_host()
    check(f"the context is attackme ({TARGET})", kp.identity_name(host) == kp.identity_name(TARGET),
          f"its cluster-identity public-host is {host!r}")
    if kp.identity_name(host) != kp.identity_name(TARGET):
        return None
    mcp_dep = cluster.get_json("-n", "agent", "get", "deployment", "workshop-mcp")
    cm = mcp_src_configmap(mcp_dep)
    synced = judge_synced(cluster.get_json("-n", "agent", "get", "agent", "workshop-agent"), mcp_dep,
                          cluster.configmap_key(cm, "tool_audit.py") if cm else None, git_tool_audit,
                          cluster.get_json("-n", "agent", "get", "deployment", "guard-proxy"), git_timeout)
    for ok, name, detail in synced:
        check(name, ok, detail)
    if not all(ok for ok, _, _ in synced):
        check("the 150-user load replay ran", False, "not sent, so nothing is spent: #885's change is not synced")
        return None

    before_uids = {(o.get("metadata") or {}).get("uid") for o in cluster.bot_objects()}
    pods_before = cluster.proxy_pods()
    start = now()
    report = None
    try:
        report = replay()
    finally:
        log_text = cluster.proxy_log_since(start)
        pods_after = cluster.proxy_pods()
        cleanup(cluster, before_uids, start, check)
    for ok, name, detail in judge_replay(report, git_timeout, None if log_text is None else log_timeouts(log_text),
                                         pods_before, pods_after):
        check(name, ok, detail)
    return report


def cleanup(cluster, before_uids: set[str], start: float, check: Callable[[str, bool, str], None]) -> None:
    """Delete what the replayed attacks had the bot create, and take its rows off the one deployments page."""
    try:
        made, over = bot_writes(cluster.bot_objects(), before_uids, start)
    except Exception as exc:  # noqa: BLE001 - the verdict still stands; the failure is named
        check("the objects the replay had the bot create were listed", False, f"{type(exc).__name__}: {exc}")
        return
    failed = []
    for ref in made:
        ok, out = cluster.delete(ref)
        if not ok:
            failed.append(f"{ref}: {out}")
    check(f"every object the replay had the bot create was deleted ({len(made)}: {', '.join(made) or 'none'})",
          not failed, "; ".join(failed))
    if over:
        print(f"  note  workshop-mcp applied over {len(over)} older object(s) during the replay, left as they now are: "
              + ", ".join(over))
    names = sorted({ref.split("/", 1)[1] for ref in made + over})
    if names:
        why = None
        for i in range(0, len(names), 50):  # /desk-forget takes at most 50 names a call (ticket_site.MAX_FORGET)
            why = cluster.forget_on_desk(names[i:i + 50], start) or why
        check("their rows were removed from the one deployments page", why is None, why or "")


def subprocess_replay(harvest: pathlib.Path) -> Callable[[], dict | None]:
    def run() -> dict | None:
        with tempfile.TemporaryDirectory(prefix="wib-load-replay-") as tmp:
            out = pathlib.Path(tmp) / "report.json"
            argv = replay_argv(harvest, out)
            print("$ " + " ".join(argv[1:]), flush=True)
            try:
                rc = subprocess.run(argv, timeout=REPLAY_TIMEOUT_S).returncode
            except subprocess.TimeoutExpired:
                print(f"load_replay.py ran past {REPLAY_TIMEOUT_S} s and was stopped", flush=True)
                return None
            print(f"load_replay.py exit {rc}", flush=True)
            return json.loads(out.read_text()) if out.is_file() else None
    return run


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""),
              flush=True)
        if not cond:
            failures.append(name)

    context = os.environ.get("COMMUNITY_CONTEXT", "")
    kubeconfig = os.environ.get("KUBECONFIG") or None
    harvest = harvest_dir()
    missing = []
    if not context:
        missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if not sorted(harvest.glob("*.json")):
        missing.append(f"no recorded prompts: {harvest} has no *.json files. Set {HARVEST_ENV} to the DevOpsDays "
                       "Portland harvest's prompts/ directory (gitignored; it holds attendee-typed text)")
    if not missing:
        cluster = LiveCluster(TARGET, context, None, kubeconfig, timeout=60.0)
        rc, out = cluster.kubectl_rc("--request-timeout=15s", "get", "--raw", "/readyz", timeout=30)
        if rc != 0:
            missing.append(f"cluster for context {context!r} is not reachable: {out.strip()[:200]}")
    if missing:
        print("FAILED: the live load replay check cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== #885: the 150-user load replay on attackme ends with 0 PROXY_TIMEOUT 502s ({context}) ==", flush=True)
    run_checks(cluster, subprocess_replay(harvest), check, TOOL_AUDIT.read_text(), git_proxy_timeout())
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("The 150-user load replay on attackme ended with 0 PROXY_TIMEOUT 502s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
