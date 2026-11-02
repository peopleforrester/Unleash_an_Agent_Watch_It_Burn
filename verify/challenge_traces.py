# ABOUTME: Checks the latest ml_app:burritobot trace for each KubeCon challenge against verify/challenge-trace-shapes.yaml
# ABOUTME: (#760) and prints PASS or FAIL per challenge with a link to the trace, so a bad trace shows up days ahead.
"""Before each timed run-through, and the night before the talk:

    python3 verify/challenge_traces.py --profile accen-dev
    python3 verify/challenge_traces.py --profile accen-dev --tag k8s.cluster.name:burritobot-private

The presenters open each challenge's trace in front of the room, so each challenge's newest trace in Whitney's
sandbox org must have the shape the YAML file writes down: one root row, the prompt and the reply on it, tokens and
cost, the root's duration covering the chat, and the key calls under the root. The check reads LLM Observability's
span list (GET /api/v2/llm-obs/v1/spans/events) with the repo's read-only key (infra/datadog-fleet, the Secrets
Manager entry watch-it-burn/datadog that the KubeCon clusters ship with):

1. every tool row in the window, so it knows which traces hold which calls;
2. per challenge, the newest trace whose tool rows include all its key calls (--tag narrows to a cluster or a
   session; every --tag must be on the tool row);
3. every row of that trace, which is judged against the shape.

Ends CHALLENGE TRACES GREEN (exit 0) when all four pass, RED (exit 1) otherwise, each FAIL with its reasons. Exit 2
when Datadog cannot be read, when it answers a list with meta.status "timeout", or when the window holds more tool
rows than --max-pages reads: a check that judged only part of the window could pass on an old trace. --out writes
the results as JSON, for filing each failure as an issue with its link.

The one-root part of the shape is #746, whose collector copy is on staging and whose live look is still owed; until
it passes in the org, every challenge fails on it, as #760 asks. Tokens and cost are #784's.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import urllib.parse

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "infra/datadog-fleet"))

SHAPES_FILE = HERE / "challenge-trace-shapes.yaml"
SPANS_PATH = "/api/v2/llm-obs/v1/spans/events"
PAGE_LIMIT = 100
# Pods on one node still stamp their spans from their own clocks; a second is far below the 14 ms root #746 saw.
ROOT_SLACK_S = 1.0
# What a root's parent_id reads in the span list: absent, or one of these.
NO_PARENT = {None, "", "0", "undefined"}
COST_METRICS = ("input_tokens", "output_tokens", "estimated_total_cost")
SKIPPED_COST = "cost_estimate_status:skipped"
TOOL_PREFIX = "execute_tool "


class ReadError(RuntimeError):
    pass


def load_shapes(path: pathlib.Path = SHAPES_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def datadog(profile: str, region: str):
    import fleet_monitors as fm
    api, app, site = fm.read_keys(profile, region)
    return fm.Datadog(site, api, app), site


def trace_url(site: str, ml_app: str, trace_id: str) -> str:
    return f"https://app.{site}/llm/traces?" + urllib.parse.urlencode({"query": f"ml_app:{ml_app} trace_id:{trace_id}"})


def list_spans(dd, params: dict, max_pages: int) -> list[dict]:
    """Every span the filters match, following the cursor. Running out of pages is an error, not a partial read."""
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        q = {**params, "page[limit]": PAGE_LIMIT, **({"page[cursor]": cursor} if cursor else {})}
        data = dd.call("GET", f"{SPANS_PATH}?{urllib.parse.urlencode(q)}")
        if (data.get("meta") or {}).get("status") == "timeout":
            raise ReadError(f"Datadog timed out listing spans for {params}: narrow --hours or --tag")
        out.extend(s.get("attributes") or {} for s in data.get("data") or [])
        cursor = ((data.get("meta") or {}).get("page") or {}).get("after")
        if not cursor:
            return out
    raise ReadError(f"more than {max_pages} pages of {PAGE_LIMIT} spans for {params}: narrow --hours or --tag, "
                    "or raise --max-pages")


def tool_name(span: dict) -> str:
    name = span.get("name") or ""
    return name[len(TOOL_PREFIX):] if name.startswith(TOOL_PREFIX) else name


def text_of(io) -> str:
    """The text a row shows for its input or output: the plain value, else its messages' content."""
    if not isinstance(io, dict):
        return ""
    value = (io.get("value") or "").strip()
    if value:
        return value
    return "\n".join((m.get("content") or "").strip() for m in io.get("messages") or [] if m.get("content")).strip()


def roots(spans: list[dict]) -> list[dict]:
    """Rows LLM Observability draws at the top: no parent, or a parent that is not in the trace."""
    ids = {s.get("span_id") for s in spans}
    rs = [s for s in spans if s.get("parent_id") in NO_PARENT or s.get("parent_id") not in ids]
    return sorted(rs, key=lambda s: s.get("start_ns") or 0)


def under(root: dict, spans: list[dict]) -> list[dict]:
    """Every row whose parent chain reaches the root."""
    by_id = {s.get("span_id"): s for s in spans}
    rid, out = root.get("span_id"), []
    for s in spans:
        seen, p = set(), s.get("parent_id")
        while p in by_id and p not in seen:
            if p == rid:
                out.append(s)
                break
            seen.add(p)
            p = by_id[p].get("parent_id")
    return out


def judge(shape: dict, spans: list[dict]) -> list[str]:
    """What is wrong with one trace against the challenge's shape; empty when it has the shape."""
    if not spans:
        return ["the trace has no rows"]
    problems: list[str] = []
    rs = roots(spans)
    if not rs:
        return ["no root row: every row's parent is in the trace"]
    if len(rs) != 1:
        problems.append(f"{len(rs)} root rows ({', '.join(s.get('name') or '?' for s in rs)}), not one (#746)")
    root = rs[0]
    rname = root.get("name") or "?"
    if not text_of(root.get("input")):
        problems.append(f"root row {rname} has no input: the prompt is not on it")
    if not text_of(root.get("output")):
        problems.append(f"root row {rname} has no output: the reply is not on it")

    llm = [s for s in spans if s.get("span_kind") == "llm"]
    if not llm:
        problems.append("no llm row, so no tokens or cost (#784)")
    for s in llm:
        m = s.get("metrics") or {}
        missing = [k for k in COST_METRICS if not (m.get(k) or 0) > 0]
        if missing:
            problems.append(f"llm row {s.get('name') or '?'} has no {', '.join(missing)} (#784)")
    skipped = sorted({t for s in spans for t in s.get("tags") or [] if t.startswith(SKIPPED_COST)})
    if skipped:
        problems.append(f"cost skipped: {', '.join(skipped)} (#784)")

    start = root.get("start_ns") or 0
    end = start + (root.get("duration") or 0)
    slack = ROOT_SLACK_S * 1e9
    first = min(s.get("start_ns") or 0 for s in spans)
    last = max((s.get("start_ns") or 0) + (s.get("duration") or 0) for s in spans)
    if first < start - slack or last > end + slack:
        problems.append(f"root row {rname} lasts {(end - start) / 1e9:.3f} s, the trace {(last - first) / 1e9:.3f} s")

    below = under(root, spans)
    for call in shape["key_calls"]:
        if any(tool_name(s) == call for s in below):
            continue
        where = "is in the trace but not under the root row" if any(tool_name(s) == call for s in spans) else \
            "is not in the trace"
        problems.append(f"{call} {where}")
    if shape.get("ordered"):
        firsts = [min((s.get("start_ns") or 0 for s in below if tool_name(s) == c), default=None)
                  for c in shape["key_calls"]]
        if None not in firsts and firsts != sorted(firsts):
            problems.append(f"the key calls are not in the order {' then '.join(shape['key_calls'])}")
    reads = shape.get("reads")
    if reads:
        calls = [s for s in below if tool_name(s) == reads["call"]]
        if calls and not any(reads["contains"] in json.dumps(s.get("input") or {}) for s in calls):
            problems.append(f"{reads['call']} does not read {reads['contains']}")
    return problems


def latest_traces(tool_spans: list[dict], tags: list[str]) -> list[tuple[str, set[str], int]]:
    """(trace id, its tool names, its newest tool row's start), newest first, over tool rows carrying every tag."""
    traces: dict[str, tuple[set[str], int]] = {}
    for s in tool_spans:
        if not all(t in (s.get("tags") or []) for t in tags) or not s.get("trace_id"):
            continue
        names, newest = traces.get(s["trace_id"], (set(), 0))
        names.add(tool_name(s))
        traces[s["trace_id"]] = (names, max(newest, s.get("start_ns") or 0))
    return sorted(((t, n, at) for t, (n, at) in traces.items()), key=lambda x: -x[2])


def check(dd, site: str, shapes: dict, hours: int, tags: list[str], max_pages: int) -> list[dict]:
    ml_app = shapes["ml_app"]
    window = {"filter[from]": f"now-{hours}h", "filter[to]": "now"}
    tool_spans = list_spans(dd, {**window, "filter[ml_app]": ml_app, "filter[span_kind]": "tool"}, max_pages)
    traces = latest_traces(tool_spans, tags)
    results = []
    for shape in shapes["challenges"]:
        row = {"challenge": shape["id"], "title": shape["title"], "key_calls": shape["key_calls"],
               "trace_id": None, "url": None}
        tid = next((t for t, names, _ in traces if set(shape["key_calls"]) <= names), None)
        if tid is None:
            # No trace to judge; the newest one with any of the key calls is the evidence to look at, and the newest
            # trace holding each call is named, so a challenge played one call per chat shows as that.
            near = next((t for t, names, _ in traces if names & set(shape["key_calls"])), None)
            row["problems"] = [f"no trace in the last {hours} h has all of {', '.join(shape['key_calls'])}"]
            for call in shape["key_calls"]:
                alone = next((t for t, names, _ in traces if call in names), None)
                if alone:
                    row["problems"].append(f"the newest {call} is in trace {alone}: {trace_url(site, ml_app, alone)}")
            if near:
                row["trace_id"], row["url"] = near, trace_url(site, ml_app, near)
        else:
            # The whole trace, every ml_app: a second root in another app is still a second root in the view.
            spans = list_spans(dd, {"filter[from]": f"now-{hours + 1}h", "filter[to]": "now", "filter[trace_id]": tid},
                               max_pages)
            row["trace_id"], row["url"] = tid, trace_url(site, ml_app, tid)
            row["problems"] = judge(shape, spans)
        row["verdict"] = "FAIL" if row["problems"] else "PASS"
        results.append(row)
    return results


def report(results: list[dict]) -> bool:
    for r in results:
        print(f"{r['verdict']:<4}  Challenge {r['challenge']}  {r['title']}  ({', '.join(r['key_calls'])})")
        for p in r["problems"]:
            print(f"      - {p}")
        print(f"      {r['url'] or 'no trace to link'}")
    return all(r["verdict"] == "PASS" for r in results)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="AWS profile holding watch-it-burn/datadog")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--hours", type=int, default=24, help="how far back the latest trace may be (default 24)")
    ap.add_argument("--tag", action="append", default=[],
                    help="only traces whose tool rows carry this tag, e.g. k8s.cluster.name:burritobot-private")
    ap.add_argument("--max-pages", type=int, default=50, help=f"pages of {PAGE_LIMIT} spans read per list")
    ap.add_argument("--shapes", type=pathlib.Path, default=SHAPES_FILE)
    ap.add_argument("--out", type=pathlib.Path, help="write the results as JSON here")
    args = ap.parse_args(argv)
    try:
        dd, site = datadog(args.profile, args.region)
        results = check(dd, site, load_shapes(args.shapes), args.hours, args.tag, args.max_pages)
    # No aws CLI, a refused key, an unreachable Datadog, a window too big to read: the traces were not judged.
    except (ReadError, RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"challenge_traces: cannot read the traces: {e}", file=sys.stderr)
        return 2
    ok = report(results)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"site": site, "hours": args.hours, "tags": args.tag, "results": results},
                                       indent=2) + "\n")
        print(f"written: {args.out}")
    print(f"CHALLENGE TRACES {'GREEN' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
