# ABOUTME: Judges one recent BurritoBot /chat in Agent Observability against #746's five checks, read from the LLM
# ABOUTME: Observability spans API with watch-it-burn/datadog's read-only pair (#771). GETs only; exit 1 on any FAIL.
"""Whitney's done-when list on #746, read on live traces instead of by eye in her sandbox org:

1. one root row per chat;
2. the prompt and the final reply on that root;
3. read_support_ticket and deploy_app under it;
4. a duration covering the whole chat;
5. tokens and an estimated cost, with no cost_estimate_status:skipped_tokens_missing.

Datadog's API reference gives no response schema for /api/v2/llm-obs/v1/spans/events, so every field read here was
read off a real response first (run 17405, 2026-11-05; verify/fixtures/llmobs-chat-judge/ holds it). Each element of
`data` is a span whose `attributes` hold trace_id, span_id, parent_id (the string "undefined" on a root), name,
span_kind (agent, llm, tool), start_ns, duration (ns), status, input and output (each {"value": str, "messages": [...]})
on the rows that have them, metrics (input_tokens, output_tokens, total_tokens on llm rows; Datadog's cost docs name
estimated_total_cost, in nanodollars, beside them) and tags, a list of "key:value" strings. Datadog writes the outcome
of its cost estimate as the tag cost_estimate_status (skipped_tokens_missing, skipped_unsupported_model_pricing).
filter[from] and filter[to] take ISO 8601 times as well as `now-<n>m`; filter[tags] and filter[session_id] are ignored.

Which chat. guard-proxy's server span for a chat carries url.path:/chat. The judge lists the last --minutes of
ml_app:burritobot spans, takes the traces holding such a span, and judges the newest one whose spans include both
tools (the HC-666 support-ticket chat). When no chat in the window called both, it judges the newest chat, and check
3 fails naming it. When there is no /chat in the window at all, that is a FAIL: there is nothing to judge, so drive
one first (the HC-666 prompt on either KubeCon bot). --trace judges one given trace instead.

The chosen trace is read whole by its id. For check 1 the judge also lists every span in the chat's own interval and
fails when a span of another trace carries the chat's session_id: that is a second row for the same chat.

Usage:
    . "$HECATON_CLUSTER_ENV"
    python3 verify/llmobs_chat_judge.py --profile accen-dev [--region us-west-2] [--minutes 1440] [--trace <id>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dd_traces  # noqa: E402

fm = dd_traces.fm
CHAT_TAG = "url.path:/chat"
TOOLS = ("read_support_ticket", "deploy_app")
SKIPPED_TOKENS = "skipped_tokens_missing"
# What each skipped cost status has meant on BurritoBot's rows, printed beside a failed cost check.
COST_HINTS = {
    SKIPPED_TOKENS: "the row has no gen_ai.usage token counts (#784)",
    "skipped_unsupported_model_pricing": "Datadog has no price for the model name, the cluster's Bedrock application "
                                         "inference-profile ARN (#876)",
}
# How far a child may stick out past the root before check 4 calls the root short. The spans come from three pods
# (guard-proxy, agentgateway, kagent) whose clocks can differ by a few ms; kagent's own server span, the root #746
# replaced, ends seconds before the chat does, so this slack hides nothing the check is for.
SLACK_NS = 100 * 10**6
LISTING_LIMIT = dd_traces.LISTING_LIMIT


def attrs(resp: dict) -> list[dict]:
    return [s.get("attributes") or {} for s in resp.get("data") or []]


def tag_values(span: dict, key: str) -> list[str]:
    return [t.split(":", 1)[1] for t in span.get("tags") or [] if isinstance(t, str) and t.startswith(key + ":")]


def text(field) -> str:
    """The `value` of an input or output field; "" when the row has none."""
    return str((field or {}).get("value") or "") if isinstance(field, dict) else ""


def start(s: dict) -> int:
    return s.get("start_ns") or 0


def end(s: dict) -> int:
    return start(s) + (s.get("duration") or 0)


def iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_chat(s: dict) -> bool:
    return CHAT_TAG in (s.get("tags") or [])


def pick_chat(listing: list[dict]) -> tuple[str | None, str]:
    """The trace to judge: the newest /chat whose spans include every tool in TOOLS, else the newest /chat."""
    chats: dict[str, int] = {}
    for s in listing:
        if is_chat(s) and s.get("trace_id"):
            chats[s["trace_id"]] = max(chats.get(s["trace_id"], 0), start(s))
    if not chats:
        return None, ""
    tools: dict[str, set] = {}
    for s in listing:
        if s.get("span_kind") == "tool":
            tools.setdefault(s.get("trace_id"), set()).add(s.get("name"))
    newest = sorted(chats, key=chats.get, reverse=True)
    full = [t for t in newest if set(TOOLS) <= tools.get(t, set())]
    if full:
        return full[0], f"the newest of {len(newest)} /chat traces that called {' and '.join(TOOLS)}"
    return newest[0], f"the newest of {len(newest)} /chat traces; none of them called {' and '.join(TOOLS)}"


def judge(spans: list[dict], window: list[dict] | None, window_full: bool = False, say=print) -> list[str]:
    """The five checks on one trace's spans; `window` is every span listed in the root's interval. Returns failures."""
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        say(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    if not spans:
        check("the trace has spans in Agent Observability", False, "the spans API returned none for it")
        return failures
    ids = {s.get("span_id") for s in spans}
    by_id = {s.get("span_id"): s for s in spans}
    roots = [s for s in spans if s.get("parent_id") not in ids]
    root = roots[0] if len(roots) == 1 else None

    say("== 1. one root row per chat ==")
    check("the chat's trace has exactly one root row", len(roots) == 1,
          f"{len(roots)} roots: " + ", ".join(f"{r.get('span_kind')} {r.get('name')} (parent {r.get('parent_id')})"
                                              for r in roots))
    if root is not None:
        check(f"the root is guard-proxy's /chat server span ({CHAT_TAG}, span.kind:server)",
              is_chat(root) and "server" in tag_values(root, "span.kind"),
              f"the root is {root.get('span_kind')} {root.get('name')} with span.kind "
              f"{tag_values(root, 'span.kind') or '(none)'} and url.path {tag_values(root, 'url.path') or '(none)'}")
        session = (tag_values(root, "session_id") or [""])[0]
        check("the root carries the chat's session_id", bool(session),
              "no session_id tag, so a second row for this chat cannot be told from another chat")
        if window is None:
            check("the chat's interval could be listed", False, "no listing of the root's interval was read")
        else:
            check(f"the listing of the chat's interval is complete (under {LISTING_LIMIT} spans)", not window_full,
                  "Datadog has more spans in the interval than one page; a second row could be past it")
            others = sorted({f"trace {s.get('trace_id')}: {s.get('span_kind')} {s.get('name')}" for s in window
                             if session and s.get("trace_id") != root.get("trace_id")
                             and session in tag_values(s, "session_id")})
            check("no other trace in the chat's interval carries its session_id (no second row for the chat)",
                  not others, "; ".join(others[:5]))

    say("== 2. the prompt and the final reply on the root ==")
    if root is None:
        check("the root row shows the prompt and the final reply", False, "there is no single root to read")
    else:
        prompt, reply = text(root.get("input")), text(root.get("output"))
        check("the root's input is the prompt (not empty)", bool(prompt.strip()), "the root's input is empty")
        check("the root's output is the reply (not empty, not the prompt)",
              bool(reply.strip()) and reply.strip() != prompt.strip(),
              "the root's output is empty" if not reply.strip() else "the root's output is the prompt again")
        say(f"        prompt: {prompt[:100]!r}")
        say(f"        reply:  {reply[:100]!r}")

    say(f"== 3. {' and '.join(TOOLS)} under the root ==")

    def under_root(s: dict) -> bool:
        seen = set()
        while s is not None and s.get("span_id") not in seen:
            if root is not None and s is root:
                return True
            seen.add(s.get("span_id"))
            s = by_id.get(s.get("parent_id"))
        return False

    for tool in TOOLS:
        rows = [s for s in spans if s.get("span_kind") == "tool" and s.get("name") == tool]
        check(f"a tool row {tool} sits under the root", any(under_root(s) for s in rows),
              f"{len(rows)} {tool} row(s) in the trace, none under a single root" if rows
              else f"no {tool} row in the trace; the chat judged did not call it")

    say("== 4. the root's duration covers the whole chat ==")
    if root is None:
        check("the root's duration covers every span of the chat", False, "there is no single root to measure")
    else:
        first, last = min(map(start, spans)), max(map(end, spans))
        check("the root starts with the chat and ends after its last span (100 ms slack)",
              start(root) <= first + SLACK_NS and end(root) >= last - SLACK_NS,
              f"root {iso(start(root))} to {iso(end(root))} ({(root.get('duration') or 0) / 1e6:.0f} ms); the chat's "
              f"spans run {iso(first)} to {iso(last)} ({(last - first) / 1e6:.0f} ms)")
        say(f"        root {(root.get('duration') or 0) / 1e6:.0f} ms; the chat's spans span {(last - first) / 1e6:.0f} ms")

    say("== 5. tokens and an estimated cost ==")
    llms = [s for s in spans if s.get("span_kind") == "llm"]
    check("the chat has model-call (llm) rows", bool(llms), "no llm row in the trace")
    if llms:
        def metric(s: dict, k: str):
            v = (s.get("metrics") or {}).get(k)
            return v if isinstance(v, (int, float)) else 0
        no_tokens = [s.get("name") for s in llms if not (metric(s, "input_tokens") > 0 and metric(s, "output_tokens") > 0)]
        check("every llm row carries input and output tokens", not no_tokens, ", ".join(map(str, no_tokens[:5])))
        no_cost = [s for s in llms if not metric(s, "estimated_total_cost") > 0]
        statuses = sorted({v for s in no_cost for v in tag_values(s, "cost_estimate_status")}) or ["(no status tag)"]
        check("every llm row has an estimated cost (metrics.estimated_total_cost)", not no_cost,
              f"{len(no_cost)} of {len(llms)} llm rows have none; cost_estimate_status: {', '.join(statuses)}"
              + "".join(f"\n        {s}: {COST_HINTS[s]}" for s in statuses if s in COST_HINTS))
        say(f"        {sum(metric(s, 'total_tokens') for s in llms):.0f} tokens over {len(llms)} model calls, "
            f"estimated cost {sum(metric(s, 'estimated_total_cost') for s in llms) / 1e9:.6f} USD")
    skipped = sorted({str(s.get("name")) for s in spans if SKIPPED_TOKENS in tag_values(s, "cost_estimate_status")})
    check(f"no row reads cost_estimate_status:{SKIPPED_TOKENS}", not skipped, ", ".join(skipped[:5]))
    return failures


def llmobs(dd, params: dict) -> dict:
    return dd_traces.get(dd, dd_traces.LLMOBS_PATH, {"filter[ml_app]": dd_traces.ML_APP, "sort": "-timestamp",
                                                     "page[limit]": LISTING_LIMIT, **params})


def main(argv=None, env=None, keys=fm.read_keys, http=None, say=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", required=True, help="AWS profile that reads watch-it-burn/datadog (accen-dev)")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--minutes", type=int, default=1440, help="how far back to look for a /chat (default 1440)")
    ap.add_argument("--trace", help="judge this trace instead of the newest /chat")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    prefix = env.get("WIB_DD_POOL_PREFIX", "Datadog")
    try:
        api, app, site = keys(a.profile, a.region)
        dd = fm.Datadog(site, api, app, http=http)
        org = dd_traces.org_name(dd)
        if not org.startswith(prefix):
            print(f"FAIL: the key reaches org '{org}', not the sandbox org (prefix {prefix}); nothing judged",
                  file=sys.stderr)
            return 1
        window_from = {"filter[from]": f"now-{a.minutes}m", "filter[to]": "now"}
        if a.trace:
            tid, why = a.trace, "the trace named with --trace"
        else:
            tid, why = pick_chat(attrs(llmobs(dd, window_from)))
            if tid is None:
                print(f"FAIL: no /chat ({CHAT_TAG}) in ml_app:{dd_traces.ML_APP} in {org} in the last {a.minutes} "
                      "minutes, so there is nothing to judge. Send one chat (the HC-666 support-ticket prompt) to "
                      "either KubeCon bot and run this again after Datadog's few minutes of delay.", file=sys.stderr)
                return 1
        spans = attrs(llmobs(dd, {**window_from, "filter[trace_id]": tid}))
        ids = {s.get("span_id") for s in spans}
        roots = [s for s in spans if s.get("parent_id") not in ids]
        window, full = None, False
        if len(roots) == 1:
            r = roots[0]
            resp = llmobs(dd, {"filter[from]": iso(start(r) - 10**9), "filter[to]": iso(end(r) + 10**9)})
            window = attrs(resp)
            full = len(window) >= LISTING_LIMIT or bool(((resp.get("meta") or {}).get("page") or {}).get("after"))
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    first = min(map(start, spans), default=0)
    say(f"== {org}: ml_app:{dd_traces.ML_APP} trace {tid} ({why}), {iso(first) if first else '?'}, {len(spans)} spans, "
        f"cluster {', '.join(sorted({v for s in spans for v in tag_values(s, 'k8s.cluster.name')})) or '?'} ==")
    failures = judge(spans, window, full, say=say)
    if failures:
        say(f"\nFAILED: {len(failures)} of #746's checks on trace {tid}:")
        for f in failures:
            say(f"  - {f}")
        return 1
    say(f"\nTrace {tid} meets all five of #746's checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
