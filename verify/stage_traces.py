# ABOUTME: Pre-seeds the Datadog traces the KubeCon stage shows (#648): runs Challenge 1, 3 and 4 on the private bot,
# ABOUTME: attack then fix, each under its own session id, waits for the traces in LLM Observability, prints one view each.
"""Night Before, after the probe is green on the private cluster:

    python3 verify/stage_traces.py seed burritobot-private.burritobot.co \\
        --context <private-context> --kubeconfig /tmp/private.kubeconfig --profile accen-dev

    # the next morning: every seeded trace is still in LLM Observability
    python3 verify/stage_traces.py check --profile accen-dev

Each challenge opens on its trace, before the room plays (Michael, 2026-10-31), so every challenge is seeded twice:
the attack as it lands, and the same ask after the fix. Six model calls, in presentation order:

    c1-attack  Challenge 1, the CEO's record read through the shipped Role
    c1-fixed   the same ask after guard-rbac-on: the read is Forbidden
    c3-attack  Challenge 3, HC-666 followed: deploy_app called, the Joker refused at admission
    c3-fixed   the same ask after guard-input-on: the ticket withheld, no deploy_app
    c4-attack  Challenge 4, the poisoned weather tool chains read_internal_config
    c4-fixed   the same ask after guard-mcp-on: stopped at the gateway

The guards are flipped by the KubeCon probe's own beats (verify/kubecon_probe.py), so a seed is exactly what the
stage does, guardrails-on before Challenge 3 included (#774), and its last act is the probe's guards-off and
guardrails-off, run even when a seed fails. The prompts carry no probe
marker, so a seeded trace reads as the prompt Whitney shows; they do appear in the private bot's feed on the prompt
wall, as the presenters' own stage prompts will.

The session ids, the Datadog query for each and the room and presenter views are written to --out
(tmp/stage-traces.json) and printed. Datadog is read with the repo's read-only key (infra/datadog-fleet).
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
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "infra/datadog-fleet"))
import kubecon_probe as kp  # noqa: E402

log = logging.getLogger("stage-traces")

ML_APP = "burritobot"
DEFAULT_OUT = REPO / "tmp/stage-traces.json"
# The two clusters' names on their spans' k8s.cluster.name tag (#629): the room's tab and the presenters'.
ROOM_CLUSTER = "burritobot-public"
PRESENTER_CLUSTER = "burritobot-private"
# key, the challenge it opens, what the trace shows, the tool spans it must carry, the tool spans it must not.
# The spans are what Whitney points at, so a seed whose reply passed but whose trace lacks them is red.
SEEDS = (
    ("c1-attack", "Challenge 1", "the CEO's record read through the shipped Role", ("get_vault_entry",), ()),
    ("c1-fixed", "Challenge 1", "the same ask after guard-rbac-on: the read is Forbidden", ("get_vault_entry",), ()),
    ("c3-attack", "Challenge 3", "HC-666 followed: deploy_app called, the Joker refused at admission",
     ("read_support_ticket", "deploy_app"), ()),
    ("c3-fixed", "Challenge 3", "the same ask after guard-input-on: the ticket withheld, no deploy_app",
     ("read_support_ticket",), ("deploy_app",)),
    ("c4-attack", "Challenge 4", "the poisoned weather tool chains read_internal_config",
     ("get_weather", "read_internal_config"), ()),
    ("c4-fixed", "Challenge 4", "the same ask after guard-mcp-on: stopped at the gateway", ("get_weather",), ()),
)


def session_id(key: str, stamp: str) -> str:
    return f"wib-stage-{key}-{stamp}"


class StageCluster(kp.KubeconCluster):
    """The probe's cluster, with /chat sending a session id, so each seed is one LLM Observability session."""

    session = ""

    def chat_body(self, prompt: str) -> dict:
        return {**super().chat_body(prompt), "session": self.session}


class StageProbe(kp.Probe):
    """A seed is a stage prompt, so it goes without the probe marker."""

    def ask(self, prompt: str) -> dict:
        try:
            return self.cluster.chat(prompt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            return {"reply": "", "transport_error": str(e)}


def _seed(key: str, stamp: str, prompt: str, judge: Callable[[dict], tuple[bool, str]],
          extra: Callable[[kp.Probe], None] | None = None) -> Callable[[kp.Probe], tuple[bool, str]]:
    def go(p: kp.Probe) -> tuple[bool, str]:
        p.cluster.session = session_id(key, stamp)
        try:
            if extra:
                extra(p)
            ok, note = judge(p.ask(prompt))
        finally:
            p.cluster.session = ""
        p.state.setdefault("seeded", []).append(key)
        return ok, f"session {session_id(key, stamp)}: {note}"
    return go


def _c3(stamp: str, key: str, judge: Callable[[dict], tuple[bool, str]]) -> Callable[[kp.Probe], tuple[bool, str]]:
    """Challenge 3 judged on joker-<stage name>, cleared before and after, as the probe's own C6 beats do."""
    def go(p: kp.Probe) -> tuple[bool, str]:
        p.cluster.session = session_id(key, stamp)
        p.cluster.clear_room_joker()
        p.cluster.witch = kp.STAGE_NAME
        try:
            d = p.ask(kp.ROOM_PROMPT)
            d = {**d, "joker": p.cluster.room_joker_exists()}
        finally:
            p.cluster.witch = ""
            p.cluster.remove_room_joker()
            p.cluster.session = ""
        p.state.setdefault("seeded", []).append(key)
        ok, note = judge(d)
        return ok, f"session {session_id(key, stamp)}: {note}"
    return go


def seed_beats(stamp: str) -> list[kp.Beat]:
    beat = {b.key: b for b in kp.ADMIN}
    return [
        beat["identity"],
        beat["start-state"],
        kp.Beat("c1-attack", "2", "Challenge 1 attack: the CEO record leaks",
                _seed("c1-attack", stamp, kp.CEO_PROMPT, kp.judge_ceo_leaks), calls=1),
        beat["guard-rbac-on"],
        kp.Beat("c1-fixed", "2", "Challenge 1 fixed: the record out of reach",
                _seed("c1-fixed", stamp, kp.CEO_PROMPT, kp.judge_ceo_unreadable), calls=1),
        # The four Kubernetes guardrails start off on the private cluster (#774); the stage arms them before
        # Challenge 2, so Challenge 3's Joker meets Kyverno at Deny, as it does on stage.
        beat["guardrails-on"],
        kp.Beat("c3-attack", "4", "Challenge 3 attack: the Joker refused at admission",
                _c3(stamp, "c3-attack", kp.judge_joker_blocked), calls=1),
        beat["guard-input-on"],
        kp.Beat("c3-fixed", "4", "Challenge 3 fixed: the ticket withheld",
                _c3(stamp, "c3-fixed", kp.judge_joker_blocked), calls=1),
        kp.Beat("c4-attack", "5", "Challenge 4 attack: the rogue tool chains",
                _seed("c4-attack", stamp, kp.MCP_PROMPT, kp.judge_c7_chained), calls=1),
        beat["guard-mcp-on"],
        kp.Beat("c4-fixed", "5", "Challenge 4 fixed: stopped at the gateway",
                _seed("c4-fixed", stamp, kp.MCP_PROMPT, lambda d: kp.from_green(kp.judge_mcp_blocked(d))),
                calls=1),
    ]


def llmobs_url(site: str, query: str) -> str:
    return f"https://app.{site}/llm/traces?" + urllib.parse.urlencode({"query": f"ml_app:{ML_APP} {query}"})


def views(site: str, stamp: str) -> list[dict]:
    out = [{"key": k, "challenge": c, "shows": what, "session": session_id(k, stamp),
            "query": f"session_id:{session_id(k, stamp)}", "must": list(must), "must_not": list(must_not),
            "url": llmobs_url(site, f"session_id:{session_id(k, stamp)}")} for k, c, what, must, must_not in SEEDS]
    for key, cluster, what in (("room", ROOM_CLUSTER, "the room's prompts, the public bot"),
                               ("presenters", PRESENTER_CLUSTER, "the presenters' prompts, the private bot")):
        q = f"k8s.cluster.name:{cluster}"
        out.append({"key": key, "challenge": "-", "shows": what, "session": None, "query": q,
                    "url": llmobs_url(site, q)})
    return out


def spans_for(dd, session: str, hours: int = 48) -> list[dict]:
    q = urllib.parse.quote(f"session_id:{session}")
    path = (f"/api/v2/llm-obs/v1/spans/events?filter[from]=now-{hours}h&filter[to]=now&filter[ml_app]={ML_APP}"
            f"&filter[query]={q}&page[limit]=100")
    return [s for s in dd.call("GET", path).get("data", [])
            if f"session_id:{session}" in (s.get("attributes", {}).get("tags") or [])]


def judge_spans(spans: list[dict], must: list[str], must_not: list[str]) -> tuple[bool, str]:
    names = {(s.get("attributes") or {}).get("name") for s in spans}
    missing = [n for n in must if n not in names]
    extra = [n for n in must_not if n in names]
    if not spans:
        return False, "no spans"
    if missing or extra:
        return False, f"{len(spans)} spans; missing {missing}" + (f", should not have {extra}" if extra else "")
    return True, f"{len(spans)} spans, with {', '.join(must)}" + (f" and no {', '.join(must_not)}" if must_not else "")


def read_seeds(dd, rows: list[dict]) -> dict[str, tuple[bool, str]]:
    return {r["session"]: judge_spans(spans_for(dd, r["session"]), r["must"], r["must_not"])
            for r in rows if r["session"]}


def wait_for(dd, rows: list[dict], deadline_s: float, poll_s: float = 30.0,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, tuple[bool, str]]:
    """Each seed's verdict on its spans, polled until every seed passes or the deadline passes. A trace's spans
    arrive over a minute or two, so a seed is read again until it carries the tool spans it must."""
    seeds = [r for r in rows if r["session"]]
    verdicts: dict[str, tuple[bool, str]] = {}
    start = time.monotonic()
    while True:
        verdicts.update(read_seeds(dd, [r for r in seeds if not verdicts.get(r["session"], (False,))[0]]))
        done = sum(1 for r in seeds if verdicts[r["session"]][0])
        elapsed = time.monotonic() - start
        log.info("  seeded traces complete in LLM Observability: %d of %d (%.0fs of %.0fs)", done, len(seeds),
                 elapsed, deadline_s)
        if done == len(seeds) or elapsed >= deadline_s:
            return verdicts
        sleep(poll_s)


def datadog(profile: str, region: str):
    import fleet_monitors as fm
    api, app, site = fm.read_keys(profile, region)
    return fm.Datadog(site, api, app), site


def report(rows: list[dict], verdicts: dict[str, tuple[bool, str]]) -> bool:
    ok = True
    for r in rows:
        if r["session"] is None:
            log.info("VIEW  %-11s %-12s %s\n      %s", r["key"], r["challenge"], r["shows"], r["url"])
            continue
        good, note = verdicts.get(r["session"], (False, "not read"))
        ok &= good
        log.info("%-4s  %-11s %-12s %s: %s\n      %s", kp.PASS if good else kp.FAIL, r["key"], r["challenge"],
                 r["shows"], note, r["url"])
    return ok


def cmd_seed(args) -> int:
    if not args.context:
        log.error("seed needs --context: it flips the private cluster's guards and never uses the current-context")
        return 2
    if args.host in kp.COMMUNITY_HOSTS:
        log.error("seed runs on the private bot only; %s is the room's", args.host)
        return 2
    stamp = args.stamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")
    cluster = StageCluster(args.host, args.context, args.profile, args.kubeconfig, args.timeout)
    probe = StageProbe(cluster, args.max_calls, settle=args.settle)
    results = probe.run(seed_beats(stamp), final=kp.GUARDS_OFF_BEAT)
    seeded_ok = all(r["verdict"] == kp.PASS for r in results)
    dd, site = datadog(args.profile, args.region)
    rows = views(site, stamp)
    log.info("== waiting up to %ds for the traces to reach LLM Observability ==", args.wait)
    verdicts = wait_for(dd, rows, args.wait)
    found = report(rows, verdicts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"host": args.host, "stamp": stamp, "site": site, "views": rows,
                                    "spans": {k: v[1] for k, v in verdicts.items()}, "beats": results},
                                   indent=2) + "\n")
    log.info("written: %s", args.out)
    log.info("SEEDED %s", "GREEN" if seeded_ok and found else "RED")
    return 0 if seeded_ok and found else 1


def cmd_check(args) -> int:
    if not args.out.exists():
        log.error("no %s: run seed first", args.out)
        return 2
    saved = json.loads(args.out.read_text())
    dd, _ = datadog(args.profile, args.region)
    rows = saved["views"]
    ok = report(rows, read_seeds(dd, rows))
    log.info("STAGE TRACES %s", "GREEN" if ok else "RED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="run the six seeds on the private bot and wait for their traces")
    s.add_argument("host", help="burritobot-private.burritobot.co")
    s.add_argument("--context", help="kube-context of the private cluster (required)")
    s.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
    s.add_argument("--max-calls", type=int, default=8, help="hard ceiling on model calls (default 8; a seed needs 6)")
    s.add_argument("--settle", type=float, default=20.0, help="seconds after narrowing C7's gateway rule")
    s.add_argument("--timeout", type=float, default=120.0)
    s.add_argument("--wait", type=int, default=600, help="seconds to wait for the traces (default 600)")
    s.add_argument("--stamp", help="session id suffix (default: the UTC minute)")
    c = sub.add_parser("check", help="re-read the seeded traces from LLM Observability")
    for p in (s, c):
        p.add_argument("--profile", required=True, help="AWS profile holding watch-it-burn/datadog")
        p.add_argument("--region", default="us-west-2")
        p.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return cmd_seed(args) if args.cmd == "seed" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
