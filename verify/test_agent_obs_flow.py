# ABOUTME: Drives verify/agent_obs_flow.py against a fake bot and a fake Datadog (#783): GREEN when a chat's spans reach
# ABOUTME: Agent Observability, RED and loud when they do not, and RED when APM has spans Agent Observability lacks.
"""#783: Agent Observability received no BurritoBot span for six hours while APM kept receiving them, and nothing went
red. agent_obs_flow.py is the check that does: these cases hold what it sends, what it asks Datadog, and that every way
the flow can stop ends RED with exit 1."""
from __future__ import annotations

import datetime as dt
import io
import logging
import pathlib
import sys
import urllib.error
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_obs_flow as af  # noqa: E402
import kubecon_probe as kp  # noqa: E402

failures: list[str] = []
T0 = dt.datetime(2026, 11, 1, 16, 42, tzinfo=dt.timezone.utc)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def span(cluster: str, trace: str, session: str = "") -> dict:
    tags = [f"k8s.cluster.name:{cluster}", f"ml_app:{af.ML_APP}"] + ([f"session_id:{session}"] if session else [])
    return {"attributes": {"name": "invoke_agent", "trace_id": trace, "tags": tags}}


class FakeDatadog:
    """The LLM Observability spans API and APM's span search. `arrives` maps a cluster to the spans it returns."""

    def __init__(self, arrives: dict[str, list[dict]] | None = None, apm: list[dict] | None = None) -> None:
        self.arrives, self.apm, self.gets, self.posts = arrives or {}, apm or [], [], []

    def call(self, method, path, body=None):
        if method == "POST":
            self.posts.append((path, body))
            assert path == "/api/v2/spans/events/search", path
            return {"data": self.apm}
        assert method == "GET" and path.startswith("/api/v2/llm-obs/v1/spans/events?"), path
        q = dict(urllib.parse.parse_qsl(path.split("?", 1)[1]))
        self.gets.append(q)
        cluster = q.get("filter[query]", "").removeprefix("k8s.cluster.name:")
        if cluster:
            return {"data": self.arrives.get(cluster, [])}
        return {"data": [s for spans in self.arrives.values() for s in spans]}


class FakeBot:
    def __init__(self, fail: str = "", empty: bool = False) -> None:
        self.fail, self.empty, self.sent = fail, empty, []

    def __call__(self, host, body, timeout):
        self.sent.append((host, body))
        if host == self.fail:
            raise urllib.error.URLError("connection refused")
        return {"reply": "" if self.empty else "We open at 11."}


def run_chat(dd, bot, hosts=af.DEFAULT_HOSTS):
    return [af.check_chat(dd, h, "20261101164200", wait_s=0, poll_s=0, timeout=5, chat=bot, now=lambda: T0,
                          sleep=lambda s: None) for h in hosts]


def run_main(argv, dd, bot=None) -> tuple[int, str]:
    real_dd, real_chat = af.datadog, af.send_chat
    af.datadog = lambda profile, region: dd  # noqa: E731
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)  # main's basicConfig is a no-op once a handler is attached
    try:
        if bot:
            af.check_chat.__defaults__ = (bot, lambda: T0, lambda s: None)
        return af.main(argv), buf.getvalue()
    finally:
        af.datadog, af.send_chat = real_dd, real_chat
        af.check_chat.__defaults__ = (real_chat, af.utcnow, af.time.sleep)
        logging.getLogger().removeHandler(handler)


print("== chat: both bots' spans arrive ==")
dd = FakeDatadog({"burritobot-public": [span("burritobot-public", "111", "wib-aoflow-burritobot-public-20261101164200")],
                  "burritobot-private": [span("burritobot-private", "222")]})
bot = FakeBot()
res = run_chat(dd, bot)
check("both bots are GREEN", all(ok for ok, _ in res), str(res))
check("the default bots are the room's and the presenters'",
      [h for h, _ in bot.sent] == ["attackme.burritobot.co", "burritobot-private.burritobot.co"], str(bot.sent))
check("each chat carries the probe marker, so it never reaches the room's feed",
      all(kp.PROBE_MARKER in b["prompt"] for _, b in bot.sent))
check("each chat has a session of its own, named for its cluster",
      [b["session"] for _, b in bot.sent] == ["wib-aoflow-burritobot-public-20261101164200",
                                               "wib-aoflow-burritobot-private-20261101164200"])
check("Agent Observability is asked for ml_app:burritobot on each bot's own cluster",
      [(q["filter[ml_app]"], q["filter[query]"]) for q in dd.gets]
      == [("burritobot", "k8s.cluster.name:burritobot-public"), ("burritobot", "k8s.cluster.name:burritobot-private")],
      str(dd.gets))
since = {int(q["filter[from]"]) for q in dd.gets}
check("from the moment of the chat, less the clock-skew minute",
      since == {af.ms(T0 - dt.timedelta(seconds=af.SKEW_S))}, str(since))
check("the read-back names the trace ids found", "111" in res[0][1] and "222" in res[1][1], str(res))
check("and says when its own session was among them", "carry its session" in res[0][1]
      and "carry its session" not in res[1][1], str(res))

print("== chat: one cluster's spans never arrive ==")
dd = FakeDatadog({"burritobot-private": [span("burritobot-private", "222")]})
res = run_chat(dd, FakeBot())
check("the room's bot is RED and the presenters' GREEN", [ok for ok, _ in res] == [False, True], str(res))
check("the RED says it loudly and names the cluster and #783",
      "AGENT OBSERVABILITY RECEIVED NOTHING from burritobot-public" in res[0][1] and "#783" in res[0][1], res[0][1])

print("== chat: the bot does not answer ==")
res = run_chat(FakeDatadog({"burritobot-public": [span("burritobot-public", "1")],
                            "burritobot-private": [span("burritobot-private", "2")]}),
               FakeBot(fail="attackme.burritobot.co"))
check("a chat that never completed is RED, whatever Datadog holds", [ok for ok, _ in res] == [False, True], str(res))
res = run_chat(FakeDatadog({"burritobot-public": [span("burritobot-public", "1")]}), FakeBot(empty=True),
               hosts=("attackme.burritobot.co",))
check("an empty reply is RED", not res[0][0], str(res))

print("== chat: a host that is not a KubeCon bot ==")
rc, out = run_main(["chat", "--profile", "p", "--host", "example.com"], FakeDatadog(), FakeBot())
check("exits 2 before reading Datadog or sending anything", rc == 2 and "not a KubeCon bot" in out, out)

print("== chat through main: exit code and verdict line ==")
rc, out = run_main(["chat", "--profile", "p", "--wait", "0", "--poll", "0"],
                   FakeDatadog({"burritobot-private": [span("burritobot-private", "2")]}), FakeBot())
check("exit 1 and AGENT OBSERVABILITY RED when one bot's spans are missing",
      rc == 1 and "AGENT OBSERVABILITY RED" in out, out)
rc, out = run_main(["chat", "--profile", "p", "--wait", "0", "--poll", "0"],
                   FakeDatadog({"burritobot-public": [span("burritobot-public", "1")],
                                "burritobot-private": [span("burritobot-private", "2")]}), FakeBot())
check("exit 0 and AGENT OBSERVABILITY GREEN when both arrive", rc == 0 and "AGENT OBSERVABILITY GREEN" in out, out)

print("== watch: APM against Agent Observability, no model call ==")
apm = [{"attributes": {"service": "burritobot", "start_timestamp": "2026-11-01T16:42:07.123Z"}}]
dd = FakeDatadog({"burritobot-public": [span("burritobot-public", "9")]}, apm)
ok, note = af.check_watch(dd, 12, 10, af.APM_ENV)
check("GREEN when Agent Observability has a span since APM's newest", ok, note)
path, body = dd.posts[0]
f = body["data"]["attributes"]["filter"]
check("APM is read for BurritoBot in the KubeCon env, past the ingestion lag, newest first",
      f == {"query": "service:burritobot env:burritobot-kubecon-na-26", "from": "now-12h", "to": "now-10m"}
      and body["data"]["attributes"]["sort"] == "-timestamp", str(body))
newest = dt.datetime(2026, 11, 1, 16, 42, 7, 123000, tzinfo=dt.timezone.utc)
check("Agent Observability is read from two minutes before APM's newest span, every cluster",
      int(dd.gets[0]["filter[from]"]) == af.ms(newest - dt.timedelta(minutes=2)) and "filter[query]" not in dd.gets[0],
      str(dd.gets))
ok, note = af.check_watch(FakeDatadog({}, apm), 12, 10, af.APM_ENV)
check("RED, loudly, when APM has a span and Agent Observability nothing: #783's symptom",
      not ok and "AGENT OBSERVABILITY RECEIVED NOTHING since 2026-11-01 16:42:07Z" in note and "#783" in note, note)
ok, note = af.check_watch(FakeDatadog({"burritobot-public": [span("burritobot-public", "9")]}, []), 12, 10, af.APM_ENV)
check("RED when APM has nothing to judge by, and it says to send a chat", not ok and "nothing to judge" in note
      and "agent_obs_flow.py chat" in note, note)
rc, out = run_main(["watch", "--profile", "p"], FakeDatadog({}, apm))
check("watch through main exits 1 with AGENT OBSERVABILITY RED", rc == 1 and "AGENT OBSERVABILITY RED" in out, out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("All agent_obs_flow checks passed.")
