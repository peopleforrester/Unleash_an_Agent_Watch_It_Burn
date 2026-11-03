# ABOUTME: Fails loudly when Agent Observability stops receiving BurritoBot spans (#783): one chat per KubeCon bot read
# ABOUTME: back through the LLM Observability API, or, with no model call, APM's newest BurritoBot span matched there.
"""Is Agent Observability still receiving BurritoBot's traces?

    # one model call per bot: send a chat, wait for its spans in Agent Observability
    python3 verify/agent_obs_flow.py chat --profile accen-dev

    # no model call: APM's newest BurritoBot span must have reached Agent Observability too
    python3 verify/agent_obs_flow.py watch --profile accen-dev

#783: from 2026-11-01 ~15:55 UTC Agent Observability received no BurritoBot span while APM kept receiving them, and
nobody saw it for six hours. The presenters open these traces on stage for every challenge, so the run-through and
the talk need a check that goes red when the flow stops, not a look at the page.

chat sends "What are your hours?" to each bot's /chat (default both KubeCon bots: attackme.burritobot.co, the room's,
on burritobot-public, and burritobot-private.burritobot.co, the presenters', on burritobot-private), with guard-proxy's
probe marker so it never reaches the room's feed, and a session id of its own. It then polls the LLM Observability
spans API for ml_app:burritobot spans on that cluster from the moment the chat was sent, until --wait (default 600 s;
Datadog documents a 3 to 5 minute delay). Any span counts: the question is whether anything arrives. It prints the
trace ids it found, which is the read-back a fix is judged on.

chat --own-session (#813) asks the harder question: did this chat itself show up? It looks only for spans tagged with
the chat's own session_id on that cluster, so a room busy with other chats cannot make it GREEN. When spans from the
cluster arrive but none carry the session, the RED says so: the flow runs and the session tag is what is missing.
verify/test_agent_obs_flow_live.py runs it on both bots in the live E2E suite.

watch spends nothing. It reads APM's newest BurritoBot span at least --lag minutes old (default 10, past the ingestion
delay) and asks Agent Observability for any ml_app:burritobot span from two minutes before it. APM with a span and
Agent Observability with none is #783's symptom, and is RED. No APM span in the window is RED too: there is nothing to
judge, so send a chat with `chat`.

Datadog is read with the repo's read-only key (Secrets Manager watch-it-burn/datadog, infra/datadog-fleet), as
verify/stage_traces.py reads it. Exit 0 GREEN, 1 RED, 2 a usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "infra/datadog-fleet"))
import kubecon_probe as kp  # noqa: E402

log = logging.getLogger("agent-obs-flow")

ML_APP = "burritobot"
APM_SERVICE = "burritobot"
APM_ENV = "burritobot-kubecon-na-26"
PRESENTER_HOST = "burritobot-private.burritobot.co"
DEFAULT_HOSTS = ("attackme.burritobot.co", PRESENTER_HOST)
PROMPT = "What are your hours?"
# Clock skew between this machine and the bot: a span is looked for from this long before the chat was sent.
SKEW_S = 60
RED_HINT = ("APM still receiving while Agent Observability gets nothing is #783: read the collector's traces/llmobs "
            "export (kubectl --context <ctx> -n monitoring logs ds/otel-collector-opentelemetry-collector-agent "
            "-c opentelemetry-collector | grep -i llmobs) and the decisions.md #783 entry.")


def cluster_for(host: str) -> str:
    """The k8s.cluster.name a bot's spans carry (#629): the room's bot is burritobot-public, the presenters' private."""
    if host in kp.COMMUNITY_HOSTS:
        return "burritobot-public"
    if host.startswith("burritobot-private."):
        return "burritobot-private"
    raise ValueError(f"{host} is not a KubeCon bot: use {' or '.join(DEFAULT_HOSTS)}")


def ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def llmobs_path(start: dt.datetime, cluster: str | None, limit: int = 100, session: str = "") -> str:
    params = {"filter[from]": str(ms(start)), "filter[to]": "now", "filter[ml_app]": ML_APP, "page[limit]": str(limit)}
    query = " ".join(([f"k8s.cluster.name:{cluster}"] if cluster else []) + ([f"session_id:{session}"] if session else []))
    if query:
        params["filter[query]"] = query
    return "/api/v2/llm-obs/v1/spans/events?" + urllib.parse.urlencode(params)


def llmobs_spans(dd, start: dt.datetime, cluster: str | None, session: str = "") -> list[dict]:
    return dd.call("GET", llmobs_path(start, cluster, session=session)).get("data") or []


def carries(span: dict, session: str) -> bool:
    return f"session_id:{session}" in ((span.get("attributes") or {}).get("tags") or [])


def trace_ids(spans: list[dict]) -> list[str]:
    return sorted({str((s.get("attributes") or {}).get("trace_id")) for s in spans
                   if (s.get("attributes") or {}).get("trace_id")})


def send_chat(host: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"https://{host}/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def datadog(profile: str, region: str):
    import fleet_monitors as fm
    api, app, site = fm.read_keys(profile, region)
    return fm.Datadog(site, api, app)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def check_chat(dd, host: str, stamp: str, wait_s: float, poll_s: float, timeout: float,
               chat: Callable[[str, dict, float], dict] = send_chat, now: Callable[[], dt.datetime] = utcnow,
               sleep: Callable[[float], None] = time.sleep, *, own_session: bool = False) -> tuple[bool, str]:
    """GREEN when ml_app:burritobot spans from the bot's cluster arrive after the chat; with own_session, only when
    spans carrying the chat's own session arrive (#813), so another visitor's chat cannot stand in for this one."""
    cluster = cluster_for(host)
    session = f"wib-aoflow-{cluster}-{stamp}"
    sent = now()
    try:
        reply = chat(host, {"prompt": f"{PROMPT} {kp.PROBE_MARKER}", "session": session}, timeout)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return False, f"{host}: the chat did not complete ({e}), so nothing was sent to trace"
    if not str(reply.get("reply") or "").strip():
        return False, f"{host}: the chat answered with no reply ({json.dumps(reply)[:200]})"
    log.info("  %s: chat sent at %s, session %s; waiting up to %ds for %s in Agent Observability",
             host, sent.strftime("%H:%M:%SZ"), session, wait_s, cluster)
    deadline = time.monotonic() + wait_s
    since = sent - dt.timedelta(seconds=SKEW_S)
    while True:
        if own_session:
            # The query asks for the session, and the tag is checked again here, so a query Datadog widened can
            # never pass another chat's spans off as this one's.
            mine = [s for s in llmobs_spans(dd, since, cluster, session) if carries(s, session)]
            if mine:
                return True, (f"{host}: the chat's own session {session} is in Agent Observability: {len(mine)} "
                              f"ml_app:{ML_APP} span(s) on {cluster}, traces "
                              f"{', '.join(trace_ids(mine)) or '(no trace_id in the response)'}")
        else:
            spans = llmobs_spans(dd, since, cluster)
            if spans:
                mine = [s for s in spans if carries(s, session)]
                return True, (f"{host}: {len(spans)} ml_app:{ML_APP} span(s) on {cluster} since the chat, traces "
                              f"{', '.join(trace_ids(spans)) or '(no trace_id in the response)'}"
                              + (f"; {len(mine)} carry its session {session}" if mine else ""))
        if time.monotonic() >= deadline:
            break
        sleep(poll_s)
    if own_session:
        others = llmobs_spans(dd, since, cluster)
        if others:
            return False, (f"{host}: THE CHAT'S OWN SPANS NEVER ARRIVED from {cluster}. One chat at "
                           f"{sent.strftime('%Y-%m-%d %H:%M:%SZ')} under session {session} was answered, and in "
                           f"{wait_s:.0f}s Agent Observability got {len(others)} ml_app:{ML_APP} span(s) from "
                           f"{cluster} (traces {', '.join(trace_ids(others)[:5]) or '?'}) but none tagged "
                           f"session_id:{session}. The flow runs; the chat's session.id is not reaching its spans.")
    return False, (f"{host}: AGENT OBSERVABILITY RECEIVED NOTHING from {cluster}. One chat at "
                   f"{sent.strftime('%Y-%m-%d %H:%M:%SZ')} was answered, and no ml_app:{ML_APP} span on "
                   f"{cluster} arrived in {wait_s:.0f}s. {RED_HINT}")


def apm_newest(dd, hours: int, lag_min: int, env: str) -> dt.datetime | None:
    body = {"data": {"type": "search_request", "attributes": {
        "filter": {"query": f"service:{APM_SERVICE} env:{env}", "from": f"now-{hours}h", "to": f"now-{lag_min}m"},
        "sort": "-timestamp", "page": {"limit": 1}}}}
    data = dd.call("POST", "/api/v2/spans/events/search", body).get("data") or []
    if not data:
        return None
    a = data[0].get("attributes") or {}
    raw = a.get("start_timestamp") or a.get("timestamp")
    if not raw:
        raise RuntimeError(f"APM's span has no start_timestamp: {sorted(a)}")
    return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def check_watch(dd, hours: int, lag_min: int, env: str) -> tuple[bool, str]:
    newest = apm_newest(dd, hours, lag_min, env)
    if newest is None:
        return False, (f"nothing to judge: APM has no {APM_SERVICE} span in env:{env} between now-{hours}h and "
                       f"now-{lag_min}m. Send a chat with `python3 verify/agent_obs_flow.py chat`.")
    spans = llmobs_spans(dd, newest - dt.timedelta(minutes=2), None)
    if not spans:
        return False, (f"AGENT OBSERVABILITY RECEIVED NOTHING since {newest.strftime('%Y-%m-%d %H:%M:%SZ')}, APM's "
                       f"newest {APM_SERVICE} span: no ml_app:{ML_APP} span from two minutes before it to now. "
                       f"{RED_HINT}")
    return True, (f"APM's newest {APM_SERVICE} span is from {newest.strftime('%Y-%m-%d %H:%M:%SZ')}, and Agent "
                  f"Observability has {len(spans)} ml_app:{ML_APP} span(s) since, traces "
                  f"{', '.join(trace_ids(spans)[:5]) or '(no trace_id in the response)'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat", help="one chat per bot, read back from Agent Observability (one model call each)")
    c.add_argument("--host", action="append", help=f"a KubeCon bot (repeatable; default {' and '.join(DEFAULT_HOSTS)})")
    c.add_argument("--wait", type=int, default=600, help="seconds to wait for the spans (default 600)")
    c.add_argument("--poll", type=float, default=30.0)
    c.add_argument("--timeout", type=float, default=120.0, help="the /chat call's timeout")
    c.add_argument("--own-session", action="store_true",
                   help="GREEN only when spans tagged with the chat's own session arrive, not any span (#813)")
    w = sub.add_parser("watch", help="APM's newest BurritoBot span must be in Agent Observability too (no model call)")
    w.add_argument("--hours", type=int, default=12, help="how far back APM is read (default 12)")
    w.add_argument("--lag", type=int, default=10, help="minutes APM's span must be old, past ingestion (default 10)")
    w.add_argument("--env", default=APM_ENV)
    for p in (c, w):
        p.add_argument("--profile", required=True, help="AWS profile holding watch-it-burn/datadog")
        p.add_argument("--region", default="us-west-2")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.cmd == "chat":
        hosts = args.host or list(DEFAULT_HOSTS)
        try:
            for h in hosts:
                cluster_for(h)
        except ValueError as e:
            log.error("%s", e)
            return 2
    dd = datadog(args.profile, args.region)
    if args.cmd == "chat":
        stamp = utcnow().strftime("%Y%m%d%H%M%S")
        results = [check_chat(dd, h, stamp, args.wait, args.poll, args.timeout, own_session=args.own_session)
                   for h in hosts]
    else:
        results = [check_watch(dd, args.hours, args.lag, args.env)]
    for good, note in results:
        log.info("%s  %s", kp.PASS if good else kp.FAIL, note)
    ok = all(good for good, _ in results)
    log.info("AGENT OBSERVABILITY %s", "GREEN" if ok else "RED: the stage's traces are not arriving")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
