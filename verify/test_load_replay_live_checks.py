# ABOUTME: Offline checks for verify/test_load_replay_live.py (#1056): its judges fail 2026-11-05's 150-user replay with
# ABOUTME: 5 PROXY_TIMEOUT 502s, pass run 18561's with none, and fail each other way #885's last criterion can break.
"""verify/test_load_replay_live.py runs #885's last criterion on attackme: the 150-user load replay of the recorded
prompts ends with 0 PROXY_TIMEOUT 502s. It needs the live cluster. This runs its judges and its whole flow with no
cluster and no network:

1. the replay it runs is the criterion's command word for word, with only --json-out added;
2. the reports are built by load_replay.py's own summarize, so the judge reads the shape the tool writes. 2026-11-05's
   run B (decisions.md, #644: 450 turns, served 307, cluster cap 138, five 502s answered after 120.3 to 122.9 s) fails
   on its five; run 18561's of 2026-11-08 (#885: served 311, cluster cap 139, no error) passes;
3. a 502 under PROXY_TIMEOUT is not counted as one; a replay cut short, one the cost cap refused, a guard-proxy log
   line naming the deadline, an unread log and a guard-proxy restart each fail;
4. the sync judge fails when the Agent does not forward traceparent, workshop-mcp mounts another tool_audit.py or has
   not rolled out, or guard-proxy runs another PROXY_TIMEOUT;
5. the flow against a fake cluster: unsynced, nothing is sent; synced, the replay runs and what the bot made during it
   is deleted and taken off the deployments page, also when the replay raises, and an older object is never deleted;
6. the literals it reads are where it says: guard-proxy's deadline log line and its 502 in the pinned proxy.py, the
   kinds deploy_app can create in workshop-mcp-server.py, and PROXY_TIMEOUT in git.
"""
from __future__ import annotations

import ast
import datetime
import importlib.util
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
HERE = REPO / "verify"
LIVE = HERE / "test_load_replay_live.py"
PROXY_PY = REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py"
MCP_SERVER = REPO / "gitops" / "ai-layer" / "workshop-mcp-server.py"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if not PROXY_PY.is_file():
    print(f"FAILED: {PROXY_PY} is missing; run bash verify/ensure-submodules.sh")
    sys.exit(1)

sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("load_replay_live", LIVE)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
lr = live.load_replay
TIMEOUT = live.git_proxy_timeout()


def ok_all(checks) -> bool:
    return all(ok for ok, _, _ in checks)


def failed(checks) -> list[str]:
    return [name for ok, name, _ in checks if not ok]


# --- 1. the command --------------------------------------------------------------------------------------------------
print("== the replay is the criterion's command ==")
argv = live.replay_argv(pathlib.Path("/h/prompts"), pathlib.Path("/t/report.json"))
criterion = "verify/load_replay.py attackme.burritobot.co --yes --users 150 --harvest /h/prompts".split()
check("it runs load_replay.py on attackme with --yes --users 150 --harvest <dir>, adding only --json-out",
      [pathlib.Path(argv[1]).relative_to(REPO).as_posix(), *argv[2:-2]] == criterion
      and argv[-2:] == ["--json-out", "/t/report.json"], " ".join(argv))
check("it runs under this interpreter", argv[0] == sys.executable, argv[0])


# --- 2. the recorded readings, built by load_replay.py's own summarize -----------------------------------------------
def report(served: int, limited: int, errors: list[tuple[str, int, float, str]] = (), cost_cap: int = 0,
           users: int = 150, sent: int | None = None, answered: int | None = None) -> dict:
    """A report as load_replay.py writes it, from per-turn results: served and cluster-limited turns, then each error
    as (outcome, status, latency, answered_by), then cost-cap refusals."""
    results = [lr.Result("served", 200, 4.1) for _ in range(served)]
    results += [lr.Result("cluster_limit", 200, 0.2) for _ in range(limited)]
    results += [lr.Result("cost_cap", 200, 0.2) for _ in range(cost_cap)]
    results += [lr.Result(o, s, lat, at=f"2026-11-05T06:4{i}:00.000+00:00", session=f"wib-load-x-{i:04d}", source=src)
                for i, (o, s, lat, src) in enumerate(errors)]
    plan = lr.Plan(users, 3, 1500, 60, 15, 45, 0.005)
    run = lr.Run("https://attackme.burritobot.co", plan, [["hi"]], 320, 10, 900, 644, "test")
    run.results = results
    run.sent = len(results) if sent is None else sent
    s = lr.summarize(run, 400.0, {"usd": 0.5}, {"usd": 3.5})
    if answered is not None:
        s["answered"] = answered
    return s


PODS = {"guard-proxy-7d9f-abcde": 0}
CHAT = "chat json, with a reply"
# 2026-11-05 run B: the five 502s were answered after 120.3 to 122.9 s (decisions.md, #644); the middle three are
# placed inside that recorded range.
NOV5 = report(307, 138, [("http_502", 502, lat, CHAT) for lat in (120.3, 120.8, 121.6, 122.2, 122.9)])
NOV8 = report(311, 139)

print("== the recorded readings ==")
check("load_replay.py's report holds what the judge reads", all(k in NOV5 for k in ("unreadable", "outcomes", "sent",
                                                                                     "answered", "planned", "users")))
check("2026-11-05's run B counts 5 PROXY_TIMEOUT 502s", len(live.proxy_timeout_502s(NOV5, TIMEOUT)) == 5,
      str(live.proxy_timeout_502s(NOV5, TIMEOUT)))
nov5 = live.judge_replay(NOV5, TIMEOUT, [], PODS, PODS)
check("2026-11-05's run B fails, on the 0 PROXY_TIMEOUT 502s check alone",
      len(failed(nov5)) == 1 and "0 PROXY_TIMEOUT 502s" in failed(nov5)[0], str(failed(nov5)))
nov8 = live.judge_replay(NOV8, TIMEOUT, [], PODS, PODS)
check("run 18561's replay of 2026-11-08 passes", ok_all(nov8), str(failed(nov8)))

# --- 3. each other way it can break ----------------------------------------------------------------------------------
print("== each other way the criterion can stop holding ==")
GATEWAY = "not chat json (server Caddy, via 1.1 Caddy)"
short_502 = report(311, 138, [("http_502", 502, 3.1, GATEWAY)])
check("a 502 well under PROXY_TIMEOUT is not a PROXY_TIMEOUT 502",
      not live.proxy_timeout_502s(short_502, TIMEOUT) and ok_all(live.judge_replay(short_502, TIMEOUT, [], PODS, PODS)))
edge = report(311, 138, [("http_502", 502, TIMEOUT, CHAT)])
check("a 502 at exactly PROXY_TIMEOUT is one", len(live.proxy_timeout_502s(edge, TIMEOUT)) == 1)
one = report(311, 138, [("http_502", 502, 120.4, CHAT)])
check("one PROXY_TIMEOUT 502 fails", not ok_all(live.judge_replay(one, TIMEOUT, [], PODS, PODS)))
cut = report(200, 100, sent=300)
check("a replay that sent fewer than 450 turns fails", not ok_all(live.judge_replay(cut, TIMEOUT, [], PODS, PODS)))
lost = report(311, 139, answered=449)
check("a replay where a sent turn never came back fails",
      not ok_all(live.judge_replay(lost, TIMEOUT, [], PODS, PODS)))
small = report(100, 50, users=50)
check("a replay of fewer than 150 users fails", not ok_all(live.judge_replay(small, TIMEOUT, [], PODS, PODS)))
capped = report(0, 0, cost_cap=450)
check("a replay the cost cap refused whole fails: it never reached the model",
      not ok_all(live.judge_replay(capped, TIMEOUT, [], PODS, PODS)))
some_capped = report(300, 140, cost_cap=10)
check("a replay with any cost-cap refusal fails", not ok_all(live.judge_replay(some_capped, TIMEOUT, [], PODS, PODS)))
check("no report fails", not ok_all(live.judge_replay(None, TIMEOUT, [], PODS, PODS)))
LOG_LINE = json.dumps({"timestamp": "2026-11-05 06:47:05,065", "level": "ERROR", "logger": "guard-proxy",
                       "message": "chat forward failed: the 120s forward deadline (PROXY_TIMEOUT) passed",
                       "event": "forward_error"})
LOG = "\n".join(['{"message": "pricing at nova", "event": "price_tier"}', LOG_LINE,
                 '{"message": "chat forward failed: HTTP Error 503", "event": "forward_error"}'])
check("guard-proxy's deadline line is found in its log, and no other forward_error",
      live.log_timeouts(LOG) == [LOG_LINE], str(live.log_timeouts(LOG)))
check("a deadline line in guard-proxy's log fails a clean report",
      not ok_all(live.judge_replay(NOV8, TIMEOUT, live.log_timeouts(LOG), PODS, PODS)))
check("an unread guard-proxy log fails", not ok_all(live.judge_replay(NOV8, TIMEOUT, None, PODS, PODS)))
check("a guard-proxy restart during the replay fails",
      not ok_all(live.judge_replay(NOV8, TIMEOUT, [], PODS, {"guard-proxy-7d9f-abcde": 1})))
check("a new guard-proxy pod during the replay fails",
      not ok_all(live.judge_replay(NOV8, TIMEOUT, [], PODS, {"guard-proxy-7d9f-zzzzz": 0})))
check("no guard-proxy pod fails", not ok_all(live.judge_replay(NOV8, TIMEOUT, [], {}, {})))


# --- 4. the sync judge -----------------------------------------------------------------------------------------------
def dep(name: str, env: dict | None = None, cm: str | None = None, updated: int = 1) -> dict:
    tpl = {"containers": [{"name": "proxy" if name == "guard-proxy" else "shim",
                           "env": [{"name": k, "value": v} for k, v in (env or {}).items()]}]}
    if cm:
        tpl["volumes"] = [{"name": "src", "configMap": {"name": cm}}]
    return {"metadata": {"name": name, "generation": 4}, "spec": {"replicas": 1, "template": {"spec": tpl}},
            "status": {"observedGeneration": 4, "updatedReplicas": updated, "availableReplicas": 1}}


def agent(headers) -> dict:
    return {"spec": {"declarative": {"tools": [
        {"type": "McpServer", "mcpServer": {"name": "workshop-mcp", "allowedHeaders": headers}},
        {"type": "McpServer", "mcpServer": {"name": "evil-mcp"}}]}}}


GIT_AUDIT = (REPO / "gitops" / "ai-layer" / "tool_audit.py").read_text()
AGENT = agent(["X-Witch-Name", "X-Pantry-Shut", "traceparent"])
MCP = dep("workshop-mcp", cm="workshop-mcp-src-5h7k2")
PROXY = dep("guard-proxy", {"PROXY_TIMEOUT": f"{TIMEOUT:g}"})

print("== is #885's change what attackme runs ==")
check("workshop-mcp's ConfigMap is found by its kustomize prefix", live.mcp_src_configmap(MCP) == "workshop-mcp-src-5h7k2")
synced = live.judge_synced(AGENT, MCP, GIT_AUDIT, GIT_AUDIT, PROXY, TIMEOUT)
check("the synced cluster passes", ok_all(synced), str(failed(synced)))
for label, args in [
    ("an Agent that forwards no traceparent", (agent(["X-Witch-Name", "X-Pantry-Shut"]), MCP, GIT_AUDIT, PROXY)),
    ("an Agent with no workshop-mcp tool", ({"spec": {"declarative": {"tools": []}}}, MCP, GIT_AUDIT, PROXY)),
    ("workshop-mcp mounting an older tool_audit.py", (AGENT, MCP, GIT_AUDIT.replace("MAX_TURN_CALLS = 20",
                                                                                    "MAX_TURN_CALLS = 200"), PROXY)),
    ("workshop-mcp mounting no tool_audit.py", (AGENT, MCP, None, PROXY)),
    ("workshop-mcp not rolled out", (AGENT, dep("workshop-mcp", cm="workshop-mcp-src-5h7k2", updated=0), GIT_AUDIT,
                                     PROXY)),
    ("guard-proxy on another PROXY_TIMEOUT", (AGENT, MCP, GIT_AUDIT, dep("guard-proxy", {"PROXY_TIMEOUT": "300"}))),
    ("guard-proxy on no PROXY_TIMEOUT", (AGENT, MCP, GIT_AUDIT, dep("guard-proxy", {}))),
    ("guard-proxy not rolled out", (AGENT, MCP, GIT_AUDIT, dep("guard-proxy", {"PROXY_TIMEOUT": f"{TIMEOUT:g}"},
                                                              updated=0))),
    ("no guard-proxy Deployment", (AGENT, MCP, GIT_AUDIT, None)),
]:
    a, m, audit, p = args
    got = live.judge_synced(a, m, audit, GIT_AUDIT, p, TIMEOUT)
    check(f"{label} fails", not ok_all(got))
check("the older-tool_audit anchor is in git's tool_audit.py", "MAX_TURN_CALLS = 20" in GIT_AUDIT,
      "tool_audit.py no longer reads 'MAX_TURN_CALLS = 20'; change the case above")


# --- 5. the flow, against a fake cluster -----------------------------------------------------------------------------
def obj(kind: str, name: str, uid: str, managers: list[tuple[str, str]]) -> dict:
    return {"kind": kind, "metadata": {"name": name, "uid": uid,
                                       "managedFields": [{"manager": m, "time": t} for m, t in managers]}}


START = datetime.datetime(2026, 11, 5, 6, 40, tzinfo=datetime.timezone.utc).timestamp()
BEFORE_T, DURING_T = "2026-11-05T06:00:00Z", "2026-11-05T06:43:10Z"
OLD = [obj("Deployment", "tron", "u-tron", [("workshop-mcp", BEFORE_T)]),
       obj("Deployment", "guard-proxy", "u-gp", [("argocd-controller", BEFORE_T)]),
       obj("Service", "maintenance-shell", "u-ms", [("workshop-mcp", BEFORE_T)])]
NEW = [obj("Deployment", "promo-mascot", "u-pm", [("workshop-mcp", DURING_T)]),
       obj("Pod", "debug-shell", "u-ds", [("workshop-mcp", DURING_T)]),
       obj("ReplicaSet", "promo-mascot-6f7", "u-rs", [("kube-controller-manager", DURING_T)]),
       obj("ConfigMap", "argo-owned", "u-ao", [("workshop-mcp", DURING_T), ("argocd-controller", DURING_T)])]
OVER = obj("Service", "maintenance-shell", "u-ms", [("workshop-mcp", DURING_T)])

print("== what the replay had the bot write ==")
made, over = live.bot_writes(OLD + NEW, {"u-tron", "u-gp", "u-ms"}, START)
check("it finds what workshop-mcp created during the replay, and nothing Argo CD or a controller manages",
      made == ["deployment/promo-mascot", "pod/debug-shell"] and over == [], f"{made} {over}")
made, over = live.bot_writes([OLD[0], OVER], {"u-tron", "u-ms"}, START)
check("an older object workshop-mcp applied over during the replay is named, never made",
      made == [] and over == ["service/maintenance-shell"], f"{made} {over}")


class FakeCluster:
    def __init__(self, host="attackme.agenticburn.com", agent_obj=AGENT, log="", pods_after=None, audit=GIT_AUDIT):
        self.host_, self.agent_obj, self.log, self.audit = host, agent_obj, log, audit
        self.pods_after = PODS if pods_after is None else pods_after
        self.items, self.deleted, self.forgot, self.pod_reads = list(OLD), [], [], 0

    def identity_host(self):
        return self.host_

    def get_json(self, *args):
        kind, name = args[-2], args[-1]
        return {("agent", "workshop-agent"): self.agent_obj, ("deployment", "workshop-mcp"): MCP,
                ("deployment", "guard-proxy"): PROXY}.get((kind, name))

    def configmap_key(self, name, key):
        return self.audit if (name, key) == ("workshop-mcp-src-5h7k2", "tool_audit.py") else None

    def proxy_pods(self):
        self.pod_reads += 1
        return PODS if self.pod_reads == 1 else self.pods_after

    def proxy_log_since(self, since):
        return self.log

    def bot_objects(self):
        return [o for o in self.items if f"{o['kind'].lower()}/{o['metadata']['name']}" not in self.deleted]

    def delete(self, ref):
        self.deleted.append(ref)
        return True, ""

    def forget_on_desk(self, names, since):
        self.forgot.append((list(names), since))
        return None


def flow(cluster, replay):
    results = []
    report_ = live.run_checks(cluster, replay, lambda n, c, d="": results.append((c, n, d)), GIT_AUDIT, TIMEOUT,
                              now=lambda: START)
    return report_, results


def replay_that_lands(cluster, rep):
    def run():
        cluster.items += NEW
        return rep
    run.calls = 0
    return run


print("== the flow against a fake attackme ==")
c = FakeCluster()
rep, res = flow(c, replay_that_lands(c, NOV8))
check("synced, clean: every check passes", rep is NOV8 and all(ok for ok, _, _ in res),
      str([n for ok, n, _ in res if not ok]))
check("what the bot made is deleted, and nothing older", c.deleted == ["deployment/promo-mascot", "pod/debug-shell"],
      str(c.deleted))
check("their rows are taken off the deployments page from the replay's start",
      c.forgot == [(["debug-shell", "promo-mascot"], START)], str(c.forgot))

c = FakeCluster()
rep, res = flow(c, replay_that_lands(c, NOV5))
check("2026-11-05's reading fails the flow, and the cleanup still runs",
      not all(ok for ok, _, _ in res) and c.deleted == ["deployment/promo-mascot", "pod/debug-shell"])

c = FakeCluster(log=LOG)
rep, res = flow(c, replay_that_lands(c, NOV8))
check("a deadline line in guard-proxy's log fails the flow", not all(ok for ok, _, _ in res))

sent = []
for label, cl in [("another cluster", FakeCluster(host="deathstar.agenticburn.com")),
                  ("an Agent without traceparent", FakeCluster(agent_obj=agent(["X-Witch-Name"]))),
                  ("an older guard", FakeCluster(audit="MAX_TURN_CALLS = 200\n"))]:
    rep, res = flow(cl, lambda: sent.append(label) or NOV8)
    check(f"{label}: nothing is sent, and the check fails", rep is None and label not in sent
          and not all(ok for ok, _, _ in res) and not cl.deleted)

c = FakeCluster()


def raises():
    c.items += NEW
    raise RuntimeError("the replay broke")


try:
    flow(c, raises)
    raised = False
except RuntimeError:
    raised = True
check("a replay that raises still has what the bot made deleted, and the error is not swallowed",
      raised and c.deleted == ["deployment/promo-mascot", "pod/debug-shell"], str(c.deleted))

# --- 6. the literals it reads ----------------------------------------------------------------------------------------
print("== the literals it reads are where it says ==")
proxy = PROXY_PY.read_text()
check(f"the pinned proxy.py raises '{live.TIMEOUT_LOG}' at PROXY_TIMEOUT", live.TIMEOUT_LOG in proxy,
      f"{PROXY_PY} no longer reads '{live.TIMEOUT_LOG}'")
check("it logs that as a forward_error and answers the /chat turn 502",
      re.search(r'log\.error\("chat forward failed: %s", exc, extra=\{"event": "forward_error"\}\)\s*\n'
                r'(?:.*\n){0,8}?\s*self\._send\(502,', proxy) is not None,
      "proxy.py's chat forward no longer logs forward_error then sends 502")
tree = ast.parse(MCP_SERVER.read_text())
kinds = next((ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "_API_VERSIONS" for t in n.targets)), None)
plural = {k.lower() + "s" for k in kinds or {}}
check("the kinds it lists are every kind deploy_app can create (workshop-mcp-server.py _API_VERSIONS)",
      kinds is not None and plural == set(live.BOT_KINDS.split(",")), f"{sorted(plural)} vs {live.BOT_KINDS}")
check("git's PROXY_TIMEOUT is read from guard-proxy's env (120 s since #694)", TIMEOUT == 120.0, str(TIMEOUT))
check("the selector is the one guard-proxy's Deployment uses",
      re.search(r"app\.kubernetes\.io/name: guard-proxy", (REPO / "gitops/ai-layer/resources.yaml").read_text())
      is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All load replay live-check judges hold.")
