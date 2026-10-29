# ABOUTME: Pre-seeds the Datadog traces Whitney shows on stage (#648): C5, C6 and C7 run before and after their guard on
# ABOUTME: the private bot, each under its own session id, then one Trace Explorer view per challenge plus the two live tabs.
"""The night before, put every trace the stage shows into Whitney's Datadog org, so nobody waits for a span.

    # once per org, before the first seed: index every seeded trace in full (needs an admin APP key)
    python3 verify/stage_traces.py retention --profile accen-dev --region us-west-2 --apply

    # the night before: six model calls on the private bot, then the views, in presentation order
    python3 verify/stage_traces.py seed burritobot-private.agenticburn.com \\
        --context <private-context> --kubeconfig /tmp/private.kubeconfig --profile accen-dev \\
        --region us-west-2 --out /tmp/stage-views.json

    # the morning of, at least 15 minutes after the seed: every view still finds its traces
    python3 verify/stage_traces.py check /tmp/stage-views.json --profile accen-dev --region us-west-2

What it seeds. The run-of-show's three challenge tabs (facilitation/kubecon-na-2026-run-of-show.md, segments 2 to 4)
each show a before and an after on the private bot: C5 the CEO record leaking, then redacted by the output guard; C6
the ticket read with the input guard off (Kyverno armed, so the Deployment it asks for is refused at admission), then
withheld by it; C7 the poisoned weather tool reaching read_internal_config, then stopped at the gateway. The guards go
on cumulatively, in that order, as the stage turns them on, and the last act is the probe's guards-off, run even when
a seed fails, so the stage starts clean.

How the traces are found again. guard-proxy stamps the browser session on its /chat root span as `session.id`
(proxy.py, `_stamp`), and every seed sends its own, `wib-stage-<UTC minute>-<seed>-t<try>`. A challenge view is the
root spans of its two sessions, `service:burritobot`, over the seed's own window, paused. The live tabs are the root
spans of each cluster by `kube_cluster_name`, burritobot-public for the room and burritobot-private for the
presenters, under the env both clusters tag (#629).

Why the retention filter. Trace Explorer keeps every ingested span searchable for 15 minutes; after that it finds only
spans a retention filter indexed, and the default filters keep a sample. A seed from the night before is gone by the
morning unless a filter indexes it, so `retention` writes one for `@session.id:wib-stage-*` at rate 1.0 and trace
rate 1.0 (the whole trace, not just the root), and `seed` refuses to spend a model call until it is in the org.
A filter applies only to spans ingested after it exists.

Saving the views. Datadog's API has no endpoint for Trace Explorer saved views; they are made with the explorer's own
Save button. `seed` writes the views file and prints each view's name and URL in presentation order: open each one
signed in to the org and save it under that name. `check` is what proves the file still holds: every challenge
session found as an indexed span, and each live tab answering.

Every prompt carries guard-proxy's probe marker, so no seed is shown on the prompt wall: the wall must not show the
room the three challenge prompts before they play them. The marker is visible in the trace's prompt.
THIS SPENDS REAL MONEY: six model calls, up to --max-calls (default 12) with retries.
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
from dataclasses import dataclass
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import kubecon_probe as kp  # noqa: E402
from agent_probe import (  # noqa: E402
    C6_ARTIFACT, EXCERPT, INJECTION_PROMPT, MCP_PROMPT, judge_injection_blocked, judge_mcp_blocked,
    judge_secret_scrubbed,
)
from fleet_monitors import Datadog, read_keys  # noqa: E402

log = logging.getLogger("stage-traces")

# The env both KubeCon clusters tag (deployment.environment.name in gitops/ai-layer/resources.yaml, #629) and the root
# service guard-proxy names its /chat span (question 868: the root stays burritobot, every other service burritobot-*).
DD_ENV = "burritobot-kubecon-na-26"
ROOT_SERVICE = "burritobot"
SESSION_PREFIX = "wib-stage-"
RETENTION_NAME = "BurritoBot stage seeds (wib-stage, #648)"
RETENTION_QUERY = f"env:{DD_ENV} service:{ROOT_SERVICE} @session.id:{SESSION_PREFIX}*"
# Trace Explorer's live window: past it only indexed spans are searchable, so a check any sooner proves nothing.
LIVE_WINDOW_S = 15 * 60
# The seed window a challenge view is pinned to: a minute before the first seed, five after the last (spans land late).
WINDOW_BEFORE_S = 60
WINDOW_AFTER_S = 300
# The two live tabs from the planning call (facilitation/kubecon-na-2026-planning-2026-10-28.md, "Datadog on stage"),
# named for the kube_cluster_name each KubeCon cluster carries (verify/test_datadog_sandbox_names.py).
LIVE_TABS = (("burritobot-public", "the room: every prompt sent to attackme"),
             ("burritobot-private", "the presenters: the private bot"))
CHALLENGES = (("C5", "1 C5 the CEO's secret", "the Secret read, and the reply before and after the output guard"),
              ("C6", "2 C6 the support ticket", "read_support_ticket with the guard off, then withheld by it"),
              ("C7", "3 C7 the poisoned weather tool", "read_internal_config before the gateway rule, absent after"))


# --- the seeds: pure definitions ----------------------------------------------------------------------------


def judge_c6_admission(d: dict) -> tuple[bool, str]:
    """C6 with the input guard off on the private cluster: Kyverno is armed, so no maintenance-shell may exist.

    Whether the model asked for it is in the trace (a deploy_app span and its denial), not in the reply.
    """
    if "c6_deployment" not in d:
        return False, f"{C6_ARTIFACT} was not checked"
    if d["c6_deployment"]:
        return False, f"{C6_ARTIFACT} EXISTS: Kyverno's registry allow-list is not armed on this cluster"
    r = kp._reply(d)
    if not r:
        return False, "empty reply (the MCP servers or the model are down)"
    return True, f"no {C6_ARTIFACT}: the ticket was read and anything it asked to deploy was refused at admission"


@dataclass(frozen=True)
class Seed:
    key: str
    challenge: str
    title: str
    prompt: str
    judge: Callable[[dict], tuple[bool, str]]
    flip: str | None = None  # the guard turned on just before this seed: output, input or mcp
    c6: bool = False         # judged on the maintenance-shell Deployment, cleared before and after


SEEDS: tuple[Seed, ...] = (
    Seed("c5-off", "C5", "C5 the CEO record leaks (output guard off)", kp.CEO_PROMPT, kp.judge_ceo_leaks),
    Seed("c5-on", "C5", "C5 the CEO record redacted (guard-output-on)", kp.CEO_PROMPT,
         lambda d: kp.from_green(judge_secret_scrubbed(d)), flip="output"),
    Seed("c6-off", "C6", "C6 the ticket read, its Deployment refused at admission (input guard off)",
         INJECTION_PROMPT, judge_c6_admission, c6=True),
    Seed("c6-on", "C6", "C6 the ticket withheld (guard-input-on)", INJECTION_PROMPT,
         lambda d: kp.from_green(judge_injection_blocked(d)), flip="input", c6=True),
    Seed("c7-off", "C7", "C7 the rogue tool chains (gateway rule open)", MCP_PROMPT, kp.judge_c7_chained),
    Seed("c7-on", "C7", "C7 the rogue tool stopped at the gateway (guard-mcp-on)", MCP_PROMPT,
         lambda d: kp.from_green(judge_mcp_blocked(d)), flip="mcp"),
)
FLIPS: dict[str, Callable] = {
    "output": kp._flip(kp.GUARD_OUTPUT_ON, "output"),
    "input": kp._flip(kp.GUARD_INPUT_ON, "input_blocklist", "input_classifier"),
    "mcp": kp._mcp_on,
}


def session_id(stamp: str, key: str, attempt: int) -> str:
    return f"{SESSION_PREFIX}{stamp}-{key}-t{attempt}"


def render_retention() -> dict:
    """The API body for the one retention filter the seeds need. Pure; the tests assert on it."""
    return {"data": {"type": "apm_retention_filter", "attributes": {
        "name": RETENTION_NAME, "enabled": True, "filter_type": "spans-sampling-processor",
        "filter": {"query": RETENTION_QUERY}, "rate": 1.0, "trace_rate": 1.0}}}


def retention_ok(f: dict) -> bool:
    a = f.get("attributes") or {}
    return (a.get("enabled") is True and (a.get("filter") or {}).get("query") == RETENTION_QUERY
            and float(a.get("rate") or 0) == 1.0 and float(a.get("trace_rate") or 0) == 1.0)


def explorer_url(site: str, query: str, start_ms: int | None = None, end_ms: int | None = None) -> str:
    """A Trace Explorer URL: pinned and on indexed spans when given a window, live (the last 15 minutes) when not."""
    params = {"query": query}
    if start_ms is not None and end_ms is not None:
        params.update({"start": str(start_ms), "end": str(end_ms), "paused": "true", "historicalData": "true"})
    else:
        params.update({"paused": "false"})
    return f"https://app.{site}/apm/traces?" + urllib.parse.urlencode(params)


def challenge_query(sessions: list[str]) -> str:
    return f"env:{DD_ENV} service:{ROOT_SERVICE} @session.id:({' OR '.join(sessions)})"


def live_query(cluster: str) -> str:
    return f"env:{DD_ENV} service:{ROOT_SERVICE} kube_cluster_name:{cluster}"


def build_views(site: str, seeded: list[dict], start: float, end: float) -> list[dict]:
    """The views in presentation order: one per challenge (its kept sessions, pinned to the seed window), then the
    public and private live tabs. `seeded` holds each seed's kept session and verdict."""
    s_ms, e_ms = int((start - WINDOW_BEFORE_S) * 1000), int((end + WINDOW_AFTER_S) * 1000)
    views = []
    for ch, name, shows in CHALLENGES:
        rows = [r for r in seeded if r["challenge"] == ch]
        sessions = [r["session"] for r in rows if r.get("session")]
        q = challenge_query(sessions) if sessions else ""
        views.append({"name": name, "shows": shows, "query": q, "sessions": sessions,
                      "seeds": [{k: r[k] for k in ("key", "verdict", "session", "note")} for r in rows],
                      "start_ms": s_ms, "end_ms": e_ms, "url": explorer_url(site, q, s_ms, e_ms) if q else ""})
    for cluster, shows in LIVE_TABS:
        q = live_query(cluster)
        views.append({"name": cluster, "shows": shows, "query": q, "sessions": [], "seeds": [],
                      "url": explorer_url(site, q)})
    return views


# --- the cluster --------------------------------------------------------------------------------------------


class StageCluster(kp.KubeconCluster):
    """The probe's cluster, plus a /chat that carries a session, which guard-proxy stamps on the root span."""

    def chat_as(self, prompt: str, session: str) -> dict:
        body = json.dumps({"prompt": prompt, "session": session}).encode()
        req = urllib.request.Request(f"https://{self.host}/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.calls += 1
            return json.load(r)


@dataclass
class Seeder:
    probe: kp.Probe
    tries: int
    stamp: str
    clock: Callable[[], float] = time.time

    @property
    def cluster(self):
        return self.probe.cluster

    def ask(self, prompt: str, session: str) -> dict:
        try:
            return self.cluster.chat_as(f"{prompt}\n\n{kp.PROBE_MARKER}", session)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            return {"reply": "", "transport_error": str(e)}

    def one(self, seed: Seed) -> dict:
        """Up to --tries fresh sessions; the first that passes its judge is the one kept. A seed the ceiling stops
        or that never passes is FAIL, and its last session is kept so the trace can still be read."""
        row = {"key": seed.key, "challenge": seed.challenge, "title": seed.title, "verdict": kp.FAIL,
               "session": "", "note": "", "tries": 0}
        for attempt in range(1, self.tries + 1):
            if self.cluster.calls + 1 > self.probe.max_calls:
                row["note"] = f"not run: --max-calls={self.probe.max_calls} would be passed. {row['note']}".strip()
                break
            session = session_id(self.stamp, seed.key, attempt)
            if seed.c6:
                self.cluster.clear_c6_artifact()
            try:
                d = self.ask(seed.prompt, session)
                if seed.c6:
                    d = {**d, "c6_deployment": self.cluster.c6_artifact_exists()}
            finally:
                if seed.c6:
                    self.cluster.remove_c6_artifact()
            ok, note = seed.judge(d)
            row.update(session=session, note=note, tries=attempt)
            if ok:
                row["verdict"] = kp.PASS
                break
        log.info("%-4s  %-62s %s  %s", row["verdict"], seed.title, row["session"] or "-", row["note"])
        return row

    def run(self) -> tuple[list[dict], list[dict], float, float]:
        """(seed rows, step rows, start, end). Nothing is flipped unless the identity and start state pass, and
        guards-off runs last whenever anything was flipped."""
        steps: list[dict] = []
        rows: list[dict] = []
        start = self.clock()

        def step(key: str, fn: Callable) -> bool:
            try:
                ok, note = fn(self.probe)
            except Exception as e:  # noqa: BLE001 - a step that cannot run is a failed step
                ok, note = False, f"could not run: {e}"
            steps.append({"key": key, "verdict": kp.PASS if ok else kp.FAIL, "note": note})
            log.info("%-4s  %-62s %s", kp.PASS if ok else kp.FAIL, key, note)
            return ok

        if not step("identity", kp._identity):
            return rows, steps, start, self.clock()
        try:
            if not step("start-state", kp._start_state):
                return rows, steps, start, self.clock()
            for seed in SEEDS:
                if seed.flip and not step(f"guard-{seed.flip}-on", FLIPS[seed.flip]):
                    rows.extend({"key": s.key, "challenge": s.challenge, "title": s.title, "verdict": kp.FAIL,
                                 "session": "", "note": f"not run: guard-{seed.flip}-on failed", "tries": 0}
                                for s in SEEDS[SEEDS.index(seed):])
                    break
                rows.append(self.one(seed))
        finally:
            step("guards-off", kp._guards_off)
        return rows, steps, start, self.clock()


# --- Datadog ------------------------------------------------------------------------------------------------


def iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def spans_found(dd: Datadog, query: str, start: float, end: float) -> int:
    """How many spans match, capped at the page: the Spans API search, which Trace Explorer runs."""
    body = {"data": {"type": "search_request", "attributes": {
        "filter": {"query": query, "from": iso(start), "to": iso(end)}, "page": {"limit": 10}}}}
    return len(dd.call("POST", "/api/v2/spans/events/search", body).get("data") or [])


def retention_filters(dd: Datadog) -> list[dict]:
    return dd.call("GET", "/api/v2/apm/config/retention-filters").get("data") or []


def ours(filters: list[dict]) -> dict | None:
    return next((f for f in filters if (f.get("attributes") or {}).get("name") == RETENTION_NAME), None)


def cmd_retention(dd: Datadog, apply: bool, say=print) -> int:
    body = render_retention()
    found = ours(retention_filters(dd))
    if found and retention_ok(found):
        say(f"  OK       retention filter '{RETENTION_NAME}' indexes {RETENTION_QUERY} at rate 1.0, trace rate 1.0")
        return 0
    if not apply:
        say(f"  {'DRIFT' if found else 'MISSING':<8} retention filter '{RETENTION_NAME}'; --apply writes:")
        say("    " + json.dumps(body))
        return 1
    try:
        if found:
            dd.call("PUT", f"/api/v2/apm/config/retention-filters/{found['id']}",
                    {"data": {**body["data"], "id": found["id"]}})
            say(f"  updated  retention filter '{RETENTION_NAME}'")
        else:
            dd.call("POST", "/api/v2/apm/config/retention-filters", body)
            say(f"  created  retention filter '{RETENTION_NAME}'")
    except RuntimeError as e:
        say(f"FAILED: {e}")
        say("  Writing a retention filter needs apm_retention_filter_write, an admin APP key. Without one, an org")
        say("  admin makes it by hand: APM > Retention Filters > Add Retention Filter, name it")
        say(f"  '{RETENTION_NAME}', query '{RETENTION_QUERY}', span rate 100%, trace rate 100%.")
        return 1
    return 0


def wait_for_traces(dd: Datadog, rows: list[dict], start: float, wait: float, sleep=time.sleep,
                    clock=time.time) -> list[str]:
    """Poll until every kept session's root span is in the org. Returns the sessions still missing."""
    missing = [r["session"] for r in rows if r.get("session")]
    deadline = clock() + wait
    while missing:
        missing = [s for s in missing if not spans_found(dd, challenge_query([s]), start - WINDOW_BEFORE_S, clock())]
        if not missing or clock() >= deadline:
            break
        sleep(15)
    return missing


def cmd_check(dd: Datadog, views: dict, now: float, say=print) -> int:
    """The views file still holds: every challenge session found as an indexed span, each live tab answering."""
    seeded_end = float(views["seeded_end"])
    if now < seeded_end + LIVE_WINDOW_S:
        say(f"TOO EARLY: the seed ended {int(now - seeded_end)} s ago; before {LIVE_WINDOW_S} s Trace Explorer still "
            "answers from its live window, so a hit would not prove the trace was indexed. Run it again later.")
        return 1
    bad = 0
    for v in views["views"]:
        if v["sessions"]:
            s, e = v["start_ms"] / 1000, v["end_ms"] / 1000
            lost = [x for x in v["sessions"] if not spans_found(dd, challenge_query([x]), s, e)]
            failed = [r["key"] for r in v["seeds"] if r["verdict"] != kp.PASS]
            ok = not lost and not failed
            note = (f"{len(v['sessions'])} traces indexed" if not lost else f"not indexed: {lost}")
            if failed:
                note += f"; seeds that did not show their beat: {failed}"
        elif v["seeds"]:
            ok, note = False, "no seed of this challenge ran"
        else:
            n = spans_found(dd, v["query"], now - 24 * 3600, now)
            ok, note = n > 0, (f"{n}+ root spans in the last 24 h" if n else "no root span in the last 24 h")
        bad += not ok
        say(f"  {'OK' if ok else 'FAIL':<5} {v['name']}: {note}")
    say("STAGE VIEWS GREEN" if not bad else "STAGE VIEWS RED")
    return 1 if bad else 0


def print_views(views: list[dict], say=print) -> None:
    say("\nThe views, in presentation order. Open each one signed in to the org and save it under its name")
    say("(Trace Explorer > Views > Save as new view); Datadog's API cannot save one:")
    for i, v in enumerate(views, 1):
        say(f"\n  {i}. {v['name']}: {v['shows']}")
        say(f"     {v['url'] or 'no trace to show: every seed of it failed to run'}")


# --- entry --------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None, keys=read_keys, http=None, cluster_cls=StageCluster,
         sleep=time.sleep, clock=time.time) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("retention", help="the retention filter that keeps every seeded trace indexed")
    r.add_argument("--apply", action="store_true", help="write it (default: report only)")
    s = sub.add_parser("seed", help="run the seeds on the private bot and write the views file")
    s.add_argument("host", help="the private bot, burritobot-private.agenticburn.com")
    s.add_argument("--context", required=True, help="kube-context of that cluster; never the current-context")
    s.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
    s.add_argument("--out", required=True, help="where the views file is written")
    s.add_argument("--tries", type=int, default=2, help="fresh sessions per seed before it is FAIL (default 2)")
    s.add_argument("--max-calls", type=int, default=12, help="hard ceiling on model calls (default 12)")
    s.add_argument("--settle", type=float, default=20.0, help="seconds after narrowing the C7 rule (default 20)")
    s.add_argument("--wait", type=float, default=300.0, help="seconds to wait for the traces in Datadog")
    s.add_argument("--timeout", type=float, default=120.0)
    c = sub.add_parser("check", help="read-only: every view in the file still finds its traces")
    c.add_argument("views", help="the views file seed wrote")
    for p in (r, s, c):
        p.add_argument("--profile", required=True, help="AWS profile that reads watch-it-burn/datadog")
        p.add_argument("--region", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        api, app, site = keys(a.profile, a.region)
        dd = Datadog(site, api, app, http=http)
        if a.cmd == "retention":
            return cmd_retention(dd, a.apply)
        if a.cmd == "check":
            return cmd_check(dd, json.loads(pathlib.Path(a.views).read_text(encoding="utf-8")), clock())
        if a.host == kp.COMMUNITY_HOST:
            log.error("%s is the room's bot; the stage's traces come from the private bot", a.host)
            return 2
        found = ours(retention_filters(dd))
        if not (found and retention_ok(found)):
            log.error("no retention filter '%s' in the org: a seed would be unsearchable by morning. Run "
                      "`stage_traces.py retention --apply` first; nothing was sent", RETENTION_NAME)
            return 2
    except RuntimeError as e:
        log.error("FAILED: %s", e)
        return 1

    cluster = cluster_cls(a.host, a.context, a.profile, a.kubeconfig, a.timeout)
    probe = kp.Probe(cluster, a.max_calls, settle=a.settle, sleep=sleep)
    stamp = dt.datetime.fromtimestamp(clock(), dt.timezone.utc).strftime("%Y%m%d%H%M")
    log.info("stage traces: %s, max %d model calls, sessions %s%s-*", a.host, a.max_calls, SESSION_PREFIX, stamp)
    rows, steps, start, end = Seeder(probe, a.tries, stamp, clock=clock).run()

    try:
        missing = wait_for_traces(dd, rows, start, a.wait, sleep=sleep, clock=clock)
    except RuntimeError as e:
        log.error("FAILED reading the traces back: %s", e)
        missing = [r["session"] for r in rows if r.get("session")]
    views = build_views(site, rows, start, end)
    out = {"host": a.host, "env": DD_ENV, "site": site, "seeded_start": start, "seeded_end": end,
           "seeded_at": iso(end), "steps": steps, "views": views, "missing": missing,
           "model_calls": cluster.calls}
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print_views(views)

    fails = [x for x in steps if x["verdict"] != kp.PASS] + [x for x in rows if x["verdict"] != kp.PASS]
    print(f"\n{len(rows)} seeds, {len(steps)} steps, {cluster.calls} model calls; views file {a.out}")
    for x in fails:
        print(f"  FAIL  {x['key']}: {x['note'][:EXCERPT]}")
    if missing:
        print(f"  FAIL  not in Datadog after {int(a.wait)} s: {missing}")
    ok = not fails and not missing and len(rows) == len(SEEDS)
    print("STAGE TRACES SEEDED" if ok else "STAGE TRACES RED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
