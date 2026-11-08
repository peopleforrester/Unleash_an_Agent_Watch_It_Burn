# ABOUTME: The post-talk purge #647 owes (#647): deletes every burritobot-public Agent Observability span from
# ABOUTME: Whitney's sandbox org by trace id, and counts the APM spans no API can delete. Dry run unless --apply.
"""Purge the room's data from Whitney's Datadog sandbox org after the KubeCon NA 2026 talk.

#647 promised, on the 2026-10-28 planning call, that the community cluster's data (`burritobot-public` in Datadog:
the room's bot and the scrub check's own `wib-pii-scrub-check` spans) is purged from her org after the talk. This is
that purge, so a run can do it with no sign-in to her org.

What it does:

- Lists every Agent Observability span tagged `k8s.cluster.name:burritobot-public` between --from and --to, of any
  ml_app, with the secret's read pair (GETs only), and groups them by trace id.
- With --apply, sends one deletion request per batch of trace ids to POST /api/v2/llm-obs/deletion/data/llmobs, with
  the secret's `write-app-key`. Datadog requires an `@trace_id` filter there, so each request names its traces
  (`@trace_id:(a OR b ...)`) and a window from the batch's first span start to its last, padded by PAD_MS. Nothing is
  asked by tag or wildcard, so a request can delete no span outside the traces it names.
- Counts the APM spans under `kube_cluster_name:burritobot-public` in the same window. APM has no delete API (the
  data deletion API takes `logs` only), so those are left to retention or to Datadog support, and the count is what
  to post on #647.
- --verify lists again and exits 1 while any Agent Observability span is left. Deletion takes a few minutes, and a
  second --apply sends only what is left, since a deleted trace is no longer listed.
- --service narrows all of it to one service: `--service wib-pii-scrub-check` clears the fake-data spans
  verify/test_collector_pii_scrub_live.py leaves, and touches no span of the room's bot.

The endpoint left Datadog's published API spec after datadog-api-client-python 2.59.0 (2026-08-12) but still
answers. On 2026-11-08 run 18508 deleted the scrub check's three stored fake-data spans with it, one id per request
and as an OR pair, and the other spans in each request's window stayed. It then sent one new fake span and purged it
with this script: the first request, sent 4 minutes after the span arrived, missed it for 16 minutes, and a second
--apply deleted it within 2. So run --verify after an --apply, and --apply again while it exits 1.

Both keys must reach the org the secret names: the uuid in its `org` field is the org's public_id, read from
/api/v2/current_user with each key before anything else, so a key that reaches another org does nothing.

Usage (after `. "$HECATON_CLUSTER_ENV"` in a dispatched run):
    python3 verify/dd_purge_public.py --profile accen-dev --from 2026-10-28            # dry run: what would go
    python3 verify/dd_purge_public.py --profile accen-dev --from 2026-10-28 --apply    # send the deletions
    python3 verify/dd_purge_public.py --profile accen-dev --from 2026-10-28 --verify   # exit 1 while any is left
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

CLUSTER = "burritobot-public"
LLMOBS_QUERY = f"k8s.cluster.name:{CLUSTER}"
APM_QUERY = f"kube_cluster_name:{CLUSTER}"
LLMOBS_SPANS = "/api/v2/llm-obs/v1/spans/events"
DELETE_PATH = "/api/v2/llm-obs/deletion/data/llmobs"
APM_AGGREGATE = "/api/v2/spans/analytics/aggregate"
ME_PATH = "/api/v2/current_user"
BATCH = 50
PAD_MS = 60_000
RETRIES = 10
BACKOFF_S = 60
WAIT_ON = (412, 429)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TRACE_ID = re.compile(r"[0-9a-f]{16,32}")


def read_secret(profile: str, region: str, run=subprocess.run) -> dict:
    out = run(["aws", "secretsmanager", "get-secret-value", "--secret-id", fm.SECRET_ID, "--profile", profile,
               "--region", region, "--query", "SecretString", "--output", "text"],
              capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"cannot read {fm.SECRET_ID} as profile {profile} in {region}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def org_id(secret: dict) -> str:
    m = UUID.search(str(secret.get("org") or ""))
    if not m:
        raise RuntimeError(f"{fm.SECRET_ID}'s org field names no org uuid, so the org cannot be checked")
    return m.group(0)


def reached_org(dd: fm.Datadog) -> str:
    me = dd.call("GET", ME_PATH)
    return next((i["attributes"].get("public_id", "?") for i in me.get("included", []) if i.get("type") == "orgs"),
                "?")


def ms(text: str) -> int:
    """An ISO date or time (a bare date is midnight UTC; a time needs a zone) as ms since the epoch."""
    t = dt.datetime.fromisoformat(text)
    if t.tzinfo is None:
        if "T" in text or " " in text:
            raise ValueError(f"{text!r} has no zone; write it with Z or an offset")
        t = t.replace(tzinfo=dt.UTC)
    return int(t.timestamp() * 1000)


def inventory(dd: fm.Datadog, frm: int, to: int, service: str | None = None) -> dict[str, list[int]]:
    """trace id -> [first span start ms, last span start ms, spans], for every span on the cluster in the window."""
    traces: dict[str, list[int]] = {}
    cursor = None
    while True:
        p = {"filter[query]": scoped(LLMOBS_QUERY, service), "filter[from]": str(frm), "filter[to]": str(to),
             "page[limit]": "1000"}
        if cursor:
            p["page[cursor]"] = cursor
        r = dd.call("GET", LLMOBS_SPANS + "?" + urllib.parse.urlencode(p))
        for s in r.get("data") or []:
            a = s.get("attributes") or {}
            tid, start = str(a.get("trace_id") or ""), (a.get("start_ns") or 0) // 1_000_000
            if not TRACE_ID.fullmatch(tid):
                raise RuntimeError(f"span {s.get('id')} has trace id {tid!r}, which no deletion query can name")
            t = traces.setdefault(tid, [start, start, 0])
            t[0], t[1], t[2] = min(t[0], start), max(t[1], start), t[2] + 1
        cursor = ((r.get("meta") or {}).get("page") or {}).get("after")
        if not cursor:
            return traces


def batches(traces: dict[str, list[int]], size: int) -> list[tuple[list[str], int, int]]:
    """Trace ids in start order, size to a batch, each with its padded window."""
    order = sorted(traces, key=lambda t: (traces[t][0], t))
    out = []
    for i in range(0, len(order), size):
        ids = order[i:i + size]
        out.append((ids, min(traces[t][0] for t in ids) - PAD_MS, max(traces[t][1] for t in ids) + PAD_MS))
    return out


def query_for(ids: list[str]) -> str:
    return f"@trace_id:{ids[0]}" if len(ids) == 1 else "@trace_id:(" + " OR ".join(ids) + ")"


def deletion_body(ids: list[str], frm: int, to: int) -> dict:
    return {"data": {"type": "create_deletion_req",
                     "attributes": {"from": frm, "to": to, "query": {"query": query_for(ids)}}}}


def scoped(query: str, service: str | None) -> str:
    return f"{query} service:{service}" if service else query


def apm_count(dd: fm.Datadog, frm: int, to: int, service: str | None = None) -> int:
    r = dd.call("POST", APM_AGGREGATE, {"data": {"type": "aggregate_request", "attributes": {
        "compute": [{"aggregation": "count"}],
        "filter": {"query": scoped(APM_QUERY, service), "from": str(frm), "to": str(to)}}}})
    buckets = r.get("data") or []
    return int(((buckets[0].get("attributes") or {}).get("compute") or {}).get("c0") or 0) if buckets else 0


def send(dd: fm.Datadog, body: dict, sleep=time.sleep, say=print) -> str:
    """Post one deletion request. Returns the request id. A 429 (rate limit) or 412 (Datadog's data deletion API
    answers that while too many requests are open) is waited out and retried; any other refusal raises."""
    for attempt in range(RETRIES):
        status, data = dd.http("POST", dd.base + DELETE_PATH, dd.headers, json.dumps(body).encode())
        if status in (200, 202):
            rid = (data.get("data") or {}).get("id")
            if not rid:
                raise RuntimeError(f"POST {DELETE_PATH} -> {status} with no deletion request id: {str(data)[:200]}")
            return str(rid)
        if status not in WAIT_ON:
            raise RuntimeError(f"POST {DELETE_PATH} -> {status}: {json.dumps(data.get('errors', data))[:300]}")
        say(f"  {status} from Datadog; waiting {BACKOFF_S}s (try {attempt + 1} of {RETRIES})")
        sleep(BACKOFF_S)
    raise RuntimeError(f"POST {DELETE_PATH} still refused after {RETRIES} tries; run --apply again later, "
                       "it sends only what is left")


def when(m: int) -> str:
    return dt.datetime.fromtimestamp(m / 1000, dt.UTC).isoformat(timespec="seconds")


def main(argv=None, keys=read_secret, http=None, say=print, sleep=time.sleep, now=time.time) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", required=True, help="AWS profile that reads watch-it-burn/datadog (accen-dev)")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--from", dest="frm", required=True,
                    help="start of the window, ISO (2026-10-28: the first build day)")
    ap.add_argument("--to", help="end of the window, ISO (default now)")
    ap.add_argument("--service", help="only this service's spans, as wib-pii-scrub-check after a live scrub check")
    ap.add_argument("--batch", type=int, default=BATCH, help=f"trace ids per deletion request (default {BATCH})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="send the deletion requests (default: a dry run)")
    mode.add_argument("--verify", action="store_true", help="exit 1 while any Agent Observability span is left")
    a = ap.parse_args(argv)
    try:
        frm, to = ms(a.frm), (ms(a.to) if a.to else int(now() * 1000))
        if not (frm < to and a.batch >= 1):
            raise ValueError("--from must be before --to and --batch at least 1")
    except ValueError as e:
        say(f"dd_purge_public: {e}")
        return 2
    try:
        secret = keys(a.profile, a.region)
        want = org_id(secret)
        if not (secret.get("api-key") and secret.get("app-key")):
            raise RuntimeError(f"{fm.SECRET_ID} has no api-key/app-key pair")
        site = secret.get("site") or "datadoghq.com"
        read = fm.Datadog(site, secret["api-key"], secret["app-key"], http=http)
        got = reached_org(read)
        if got != want:
            say(f"dd_purge_public: the read pair reaches org {got}, not {want}, which {fm.SECRET_ID} names; "
                "nothing read")
            return 1
        say(f"Window {when(frm)} to {when(to)}, org {want}.")
        traces = inventory(read, frm, to, a.service)
        spans = sum(t[2] for t in traces.values())
        apm = apm_count(read, frm, to, a.service)
        say(f"Agent Observability: {spans} spans in {len(traces)} traces under {scoped(LLMOBS_QUERY, a.service)}.")
        say(f"APM: {apm} spans under {scoped(APM_QUERY, a.service)}; no API deletes them, so they are left to "
            "retention or support.")
        if a.verify:
            if traces:
                say(f"Not purged yet: {spans} Agent Observability spans are left (deletion takes minutes).")
                return 1
            say("Purged: no Agent Observability span is left for the cluster in the window.")
            return 0
        plan = batches(traces, a.batch)
        if not a.apply:
            for ids, b0, b1 in plan:
                say(f"  would delete {len(ids)} traces, {when(b0)} to {when(b1)}")
            say(f"Dry run: {len(plan)} deletion requests. Pass --apply to send them.")
            return 0
        if not secret.get("write-app-key"):
            raise RuntimeError(f"{fm.SECRET_ID} has no write-app-key, which the deletion needs")
        write = fm.Datadog(site, secret["api-key"], secret["write-app-key"], http=http)
        got = reached_org(write)
        if got != want:
            say(f"dd_purge_public: the write key reaches org {got}, not {want}; nothing deleted")
            return 1
        for n, (ids, b0, b1) in enumerate(plan, 1):
            rid = send(write, deletion_body(ids, b0, b1), sleep, say)
            say(f"  request {n} of {len(plan)}: {len(ids)} traces, {when(b0)} to {when(b1)}, id {rid}")
        say(f"Sent {len(plan)} deletion requests for {len(traces)} traces. Run --verify in a few minutes.")
        return 0
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        say(f"dd_purge_public: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
