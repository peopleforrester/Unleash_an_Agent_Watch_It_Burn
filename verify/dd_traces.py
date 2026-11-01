# ABOUTME: Reads BurritoBot's latest traces from Whitney's Datadog sandbox org (#759): ml_app:burritobot from LLM
# ABOUTME: Observability, and with --apm the env's APM spans. GET only, on a new read-only key, never watch-it-burn/datadog's.
"""The latest BurritoBot traces in Whitney's sandbox org, for a dispatched run or a person.

Every trace fix (#746 is the one that asked for this) used to end by handing the Datadog look to a person. This
prints what that person would look at: the newest `ml_app:burritobot` traces in LLM Observability, each with its
spans, and with --apm the newest APM spans under env burritobot-kubecon-na-26.

Where the key comes from (--via, required; there is no default and no fallback):

  sources  A dispatched run. Each call goes through hecaton's read wrapper as
           `sudo -n -u michael /var/lib/hecaton/cli/sources datadog GET <path>`, which adds the read-only key pair
           itself and prints {"status": <http status>, "body": <json>}. The run never holds the key, as it never
           holds a GitHub token (the hecaton follow-up of #759 adds the verb).
  env      A session with the key in hand: WIB_DD_TRACES_API_KEY and WIB_DD_TRACES_APP_KEY, and WIB_DD_SITE
           (default datadoghq.com, the sandbox org is US1).

Either way the key is the one #759 created for reading traces: an application key scoped to llm_observability_read,
apm_read and user_self_profile_read, with its own API key. It is not watch-it-burn/datadog's pair, which the clusters
ship with, and Whitney's rules (#629) forbid using an existing key. Every call is a GET, so even an unscoped key
could write nothing through this file.

The org must be named with WIB_DD_POOL_PREFIX (default "Datadog", as in fleet_monitors.py and room_view.py) before
anything is read, so a key that reaches some other org reads nothing there.

Usage:
    python3 verify/dd_traces.py --via sources [--minutes 60] [--traces 3] [--apm] [--json]
    python3 verify/dd_traces.py --via sources --trace <trace id>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra" / "datadog-fleet"))
from fleet_monitors import Datadog, org_name  # noqa: E402

ML_APP = "burritobot"
DD_ENV = "burritobot-kubecon-na-26"
APM_QUERY = f"env:{DD_ENV} service:burritobot*"
LLMOBS_PATH = "/api/v2/llm-obs/v1/spans/events"
APM_PATH = "/api/v2/spans/events"
SOURCES = ["sudo", "-n", "-u", "michael", "/var/lib/hecaton/cli/sources", "datadog"]
API_KEY_ENV = "WIB_DD_TRACES_API_KEY"
APP_KEY_ENV = "WIB_DD_TRACES_APP_KEY"
# How many spans one listing reads to find the newest traces; each chosen trace is then read whole by its id.
LISTING_LIMIT = 500


def sources_http(run=subprocess.run):
    """A Datadog transport through hecaton's `sources datadog` verb: GET only, no key on this side."""
    def http(method: str, url: str, headers: dict, body: bytes | None):
        if method != "GET" or body is not None:
            raise RuntimeError(f"sources datadog reads only; refusing {method}")
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        out = run([*SOURCES, "GET", path], capture_output=True, text=True, timeout=90)
        if out.returncode != 0:
            raise RuntimeError(f"sources datadog GET {parts.path} exited {out.returncode}: "
                               f"{(out.stderr or out.stdout).strip()[:300]}")
        try:
            got = json.loads(out.stdout)
            return int(got["status"]), got.get("body") or {}
        except (ValueError, KeyError, TypeError) as e:
            raise RuntimeError(f"sources datadog GET {parts.path} printed no {{status, body}} object: {e}") from e
    return http


def client(via: str, env: dict, run=subprocess.run, http=None) -> Datadog:
    if via == "sources":
        # The wrapper adds the real headers; the site in the URL is only there to be stripped.
        return Datadog("datadoghq.com", "", "", http=http or sources_http(run))
    missing = [k for k in (API_KEY_ENV, APP_KEY_ENV) if not env.get(k)]
    if missing:
        raise RuntimeError(f"--via env needs {' and '.join(missing)}: the read-only pair #759 created, "
                           "not watch-it-burn/datadog's")
    return Datadog(env.get("WIB_DD_SITE") or "datadoghq.com", env[API_KEY_ENV], env[APP_KEY_ENV], http=http)


def get(dd: Datadog, path: str, params: dict) -> dict:
    return dd.call("GET", f"{path}?{urllib.parse.urlencode(params)}")


def llmobs_spans(dd: Datadog, minutes: int, limit: int, trace_id: str | None = None) -> list[dict]:
    params = {"filter[ml_app]": ML_APP, "filter[from]": f"now-{minutes}m", "filter[to]": "now",
              "sort": "-timestamp", "page[limit]": limit}
    if trace_id:
        params["filter[trace_id]"] = trace_id
    return [s.get("attributes") or {} for s in get(dd, LLMOBS_PATH, params).get("data") or []]


def apm_spans(dd: Datadog, minutes: int, limit: int) -> list[dict]:
    params = {"filter[query]": APM_QUERY, "filter[from]": f"now-{minutes}m", "filter[to]": "now",
              "sort": "-timestamp", "page[limit]": limit}
    return [s.get("attributes") or {} for s in get(dd, APM_PATH, params).get("data") or []]


def newest_traces(spans: list[dict], n: int) -> list[str]:
    """The ids of the n traces whose first span started last, newest first."""
    start: dict[str, int] = {}
    for s in spans:
        tid = s.get("trace_id")
        if tid:
            start[tid] = min(start.get(tid, s.get("start_ns") or 0), s.get("start_ns") or 0)
    return sorted(start, key=lambda t: start[t], reverse=True)[:n]


def when(ns) -> str:
    return dt.datetime.fromtimestamp((ns or 0) / 1e9, dt.UTC).isoformat(timespec="seconds")


def ms(ns) -> str:
    return f"{(ns or 0) / 1e6:.0f} ms"


def tag(span: dict, key: str) -> str:
    tags = span.get("tags") or []
    if isinstance(tags, dict):
        return str(tags.get(key, "-"))
    return next((t.split(":", 1)[1] for t in tags if isinstance(t, str) and t.startswith(key + ":")), "-")


def show_trace(tid: str, spans: list[dict], say=print) -> None:
    """A trace as its roots and their children, indented, in start order."""
    ids = {s.get("span_id") for s in spans}
    kids: dict[str | None, list[dict]] = {}
    for s in sorted(spans, key=lambda s: s.get("start_ns") or 0):
        parent = s.get("parent_id")
        kids.setdefault(parent if parent in ids else None, []).append(s)
    roots = kids.get(None, [])
    first = min((s.get("start_ns") or 0 for s in spans), default=0)
    say(f"trace {tid}  {when(first)}  {len(spans)} spans  {len(roots)} root(s)  env={tag(roots[0] if roots else {}, 'env')}")

    def walk(s: dict, depth: int) -> None:
        tokens = (s.get("metrics") or {}).get("total_tokens")
        say(f"  {'  ' * depth}{s.get('span_kind', '?')} {s.get('name', '?')}  {ms(s.get('duration'))}  "
            f"{s.get('status', '?')}" + (f"  {tokens:.0f} tokens" if isinstance(tokens, (int, float)) else ""))
        for c in kids.get(s.get("span_id"), []):
            walk(c, depth + 1)
    for r in roots:
        walk(r, 0)


def show_apm(spans: list[dict], say=print) -> None:
    say(f"APM: the newest {len(spans)} spans for {APM_QUERY}")
    for s in spans:
        say(f"  {s.get('start_timestamp') or s.get('timestamp') or '?'}  {s.get('service', '?')}  "
            f"{s.get('resource_name') or s.get('operation_name') or '?'}  trace {s.get('trace_id', '?')}")


def main(argv=None, env=None, run=subprocess.run, http=None, say=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--via", required=True, choices=("sources", "env"))
    ap.add_argument("--minutes", type=int, default=60, help="how far back to look (default 60)")
    ap.add_argument("--traces", type=int, default=3, help="how many of the newest traces to print (default 3)")
    ap.add_argument("--trace", help="print this one trace instead of the newest")
    ap.add_argument("--apm", action="store_true", help="also print the env's newest APM spans")
    ap.add_argument("--json", action="store_true", help="print the spans as JSON instead of text")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    prefix = env.get("WIB_DD_POOL_PREFIX", "Datadog")
    try:
        dd = client(a.via, env, run=run, http=http)
        org = org_name(dd)
        if not org.startswith(prefix):
            print(f"dd_traces: the key reaches org '{org}', not the sandbox org (prefix {prefix}); nothing read",
                  file=sys.stderr)
            return 1
        ids = [a.trace] if a.trace else newest_traces(llmobs_spans(dd, a.minutes, LISTING_LIMIT), a.traces)
        if not ids:
            print(f"dd_traces: no ml_app:{ML_APP} span in {org} in the last {a.minutes} minutes",
                  file=sys.stderr)
            return 1
        traces = {t: llmobs_spans(dd, a.minutes, LISTING_LIMIT, trace_id=t) for t in ids}
        empty = [t for t, spans in traces.items() if not spans]
        if empty:
            print(f"dd_traces: no ml_app:{ML_APP} span of trace {', '.join(empty)} in the last {a.minutes} minutes",
                  file=sys.stderr)
            return 1
        apm = apm_spans(dd, a.minutes, 50) if a.apm else None
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print(f"dd_traces: {e}", file=sys.stderr)
        return 1
    if a.json:
        say(json.dumps({"org": org, "ml_app": ML_APP, "traces": traces,
                        **({"apm": apm} if apm is not None else {})}, indent=2))
        return 0
    say(f"== {org}: ml_app:{ML_APP}, last {a.minutes} minutes ==")
    for t in ids:
        show_trace(t, traces[t], say=say)
    if apm is not None:
        show_apm(apm, say=say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
