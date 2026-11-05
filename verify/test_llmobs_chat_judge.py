# ABOUTME: Offline tests for verify/llmobs_chat_judge.py (#771): it judges a real recorded LLM Observability payload
# ABOUTME: as the live org read it, and each way of breaking one of #746's five checks turns that check red.
"""Nothing here reaches Datadog or AWS. The org is a fake transport answering /api/v2/current_user and the LLM
Observability span listing, and refusing anything else. What it answers with is verify/fixtures/llmobs-chat-judge/
chat-098fcb00.json: two real responses of the spans API from Whitney's sandbox org, recorded by run 17405 (the
community bot's HC-666 chat of 2026-11-05T08:29:02Z, read by its trace id, and every span listed in its interval).

As recorded, the payload passes four checks and fails the cost one, as the live org did: its llm rows read
cost_estimate_status:skipped_unsupported_model_pricing (#876). With an estimated cost put on those rows it passes all
five. Each break below starts from that passing copy and must turn exactly the check it breaks red: a judge that
passes whatever it is fed proves nothing.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import llmobs_chat_judge as judge  # noqa: E402

FIXTURE = HERE / "fixtures" / "llmobs-chat-judge" / "chat-098fcb00.json"
RECORDED = json.loads(FIXTURE.read_text())
TID = "098fcb005cbe5ed190ad9022a96b03c0"
COST = "every llm row has an estimated cost (metrics.estimated_total_cost)"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def spans_of(resp: dict) -> list[dict]:
    return [s["attributes"] for s in resp["data"]]


def priced(rec: dict) -> dict:
    """The recording with a cost on every llm row and its skipped status gone, as a priced model would read."""
    rec = copy.deepcopy(rec)
    for part in ("trace", "window"):
        for a in spans_of(rec[part]):
            if a.get("span_kind") == "llm":
                a["metrics"]["estimated_total_cost"] = 61_000_000  # nanodollars
                a["tags"] = [t for t in a["tags"] if not t.startswith("cost_estimate_status:")]
    return rec


class Org:
    """Answers the judge's three listings: the window (`now-<n>m`), the trace (filter[trace_id]) and the interval."""

    def __init__(self, rec: dict, listing: list[dict] | None = None, name: str = "Datadog"):
        self.rec, self.name, self.calls = rec, name, []
        self.listing = rec["window"]["data"] if listing is None else listing

    def http(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        self.calls.append((method, parts.path, q))
        if method != "GET":
            return 405, {"errors": ["fake org: reads only"]}
        if parts.path == "/api/v2/current_user":
            return 200, {"data": {"type": "users"}, "included": [{"type": "orgs", "attributes": {"name": self.name}}]}
        if parts.path != judge.dd_traces.LLMOBS_PATH or q.get("filter[ml_app]") != "burritobot":
            return 404, {"errors": [f"fake org: no {parts.path} {q}"]}
        if "filter[trace_id]" in q:
            data = [s for s in self.rec["trace"]["data"] if s["attributes"]["trace_id"] == q["filter[trace_id]"]]
            return 200, {"data": data, "meta": {"page": None}}
        if q.get("filter[from]", "").startswith("now-"):
            return 200, {"data": self.listing, "meta": {"page": None}}
        return 200, self.rec["window"]


def run(rec: dict, argv=(), listing=None, org="Datadog"):
    o = Org(rec, listing, org)
    out, err = io.StringIO(), io.StringIO()
    lines: list[str] = []
    with contextlib.redirect_stderr(err):
        rc = judge.main(["--profile", "accen-dev", *argv], env={}, keys=lambda p, r: ("api", "app", "datadoghq.com"),
                        http=o.http, say=lines.append)
    text = "\n".join(lines)
    failed = [ln.split("FAIL", 1)[1].strip() for ln in text.splitlines() if ln.strip().startswith("FAIL ")]
    return rc, failed, text + err.getvalue(), o


print("== the recording is a real response with the fields the judge reads ==")
rt = spans_of(RECORDED["trace"])
check("the recording holds the 8 spans of the community bot's HC-666 chat", len(rt) == 8 and
      {s["trace_id"] for s in rt} == {TID})
root = [s for s in rt if s["parent_id"] == "undefined"]
check("its root's parent_id is the string 'undefined', as Datadog writes a root", len(root) == 1)
check("its root carries url.path:/chat, span.kind:server and a session_id",
      bool(root) and {"url.path:/chat", "span.kind:server"} <= set(root[0]["tags"])
      and any(t.startswith("session_id:") for t in root[0]["tags"]))
check("its input and output are {'value': ...} objects",
      bool(root) and isinstance(root[0]["input"], dict) and "value" in root[0]["output"])
llms = [s for s in rt if s["span_kind"] == "llm"]
check("its 3 llm rows carry input_tokens and output_tokens and read skipped_unsupported_model_pricing",
      len(llms) == 3 and all(s["metrics"]["input_tokens"] > 0 and s["metrics"]["output_tokens"] > 0 for s in llms)
      and all("cost_estimate_status:skipped_unsupported_model_pricing" in s["tags"] for s in llms))

print("== the recording, judged as the live org was ==")
rc, failed, text, org = run(RECORDED)
check("it fails, on the cost check alone", rc == 1 and failed == [COST], f"rc {rc}, failed {failed}")
check("the cost failure names the status and #876", "skipped_unsupported_model_pricing" in text and "#876" in text)
check("it picked the recorded chat as the newest that called both tools",
      f"trace {TID} (the newest of 1 /chat traces that called read_support_ticket and deploy_app)" in text, text[:300])
check("every request was a GET", all(m == "GET" for m, _, _ in org.calls))
interval = [q for _, p, q in org.calls if p == judge.dd_traces.LLMOBS_PATH
            and not q["filter[from]"].startswith("now-") and "filter[trace_id]" not in q]
check("it listed the chat's own interval with ISO times, one second each side",
      len(interval) == 1 and interval[0]["filter[from]"] == "2026-11-05T08:29:01.616Z"
      and interval[0]["filter[to]"] == "2026-11-05T08:29:08.503Z", str(interval))

print("== priced, the same chat passes all five ==")
GOOD = priced(RECORDED)
rc, failed, text, _ = run(GOOD)
check("it passes", rc == 0 and not failed and "meets all five of #746's checks" in text, f"rc {rc}, failed {failed}")


def edit(fn) -> dict:
    rec = copy.deepcopy(GOOD)
    fn(rec, {s["name"]: s for s in spans_of(rec["trace"])}, rec["window"])
    return rec


def breaks(label: str, rec: dict, want: list[str], argv=()) -> None:
    rc, failed, text, _ = run(rec, argv)
    check(f"{label}: fails {want}", rc == 1 and failed == want, f"rc {rc}, failed {failed}")


def second_root(rec, by, _):
    by["workshop_agent"]["parent_id"] = "undefined"


def other_trace_same_session(rec, by, window):
    extra = copy.deepcopy(window["data"][0])
    extra["attributes"]["trace_id"] = "0" * 32
    window["data"].append(extra)


def page_after(rec, by, window):
    window["meta"]["page"] = {"after": "more"}


def root_not_chat(rec, by, _):
    by["POST"]["tags"] = [t for t in by["POST"]["tags"] if t != "url.path:/chat"]


def no_session(rec, by, _):
    by["POST"]["tags"] = [t for t in by["POST"]["tags"] if not t.startswith("session_id:")]


def no_content(rec, by, _):
    by["POST"].pop("output")


def echo(rec, by, _):
    by["POST"]["output"] = dict(by["POST"]["input"])


def no_prompt(rec, by, _):
    by["POST"]["input"] = {"value": ""}


def no_deploy(rec, by, _):
    rec["trace"]["data"] = [s for s in rec["trace"]["data"] if s["attributes"]["name"] != "deploy_app"]


def short_root(rec, by, _):
    by["POST"]["duration"] = 14 * 10**6  # kagent's own server span, the root #746 replaced


def late_root(rec, by, _):
    by["POST"]["start_ns"] += 500 * 10**6
    by["POST"]["duration"] -= 500 * 10**6


def no_output_tokens(rec, by, _):
    next(s for s in spans_of(rec["trace"]) if s["span_kind"] == "llm")["metrics"].pop("output_tokens")


def unpriced(rec, by, _):
    for s in spans_of(rec["trace"]):
        if s["span_kind"] == "llm":
            s["metrics"].pop("estimated_total_cost")


def skipped_tokens(rec, by, _):
    by["POST"]["tags"].append("cost_estimate_status:skipped_tokens_missing")


def no_llm(rec, by, _):
    rec["trace"]["data"] = [s for s in rec["trace"]["data"] if s["attributes"]["span_kind"] != "llm"]


print("== each break turns its check red ==")
breaks("1. a second root row (workshop_agent parentless)", edit(second_root),
       ["the chat's trace has exactly one root row",
        "the root row shows the prompt and the final reply",
        "a tool row read_support_ticket sits under the root",
        "a tool row deploy_app sits under the root",
        "the root's duration covers every span of the chat"])
breaks("1. a second row for the chat in another trace", edit(other_trace_same_session),
       ["no other trace in the chat's interval carries its session_id (no second row for the chat)"])
breaks("1. more spans in the interval than one page", edit(page_after),
       [f"the listing of the chat's interval is complete (under {judge.LISTING_LIMIT} spans)"])
breaks("1. the root is not guard-proxy's /chat span", edit(root_not_chat),
       ["the root is guard-proxy's /chat server span (url.path:/chat, span.kind:server)"], ["--trace", TID])
breaks("1. the root carries no session_id", edit(no_session),
       ["the root carries the chat's session_id"])
breaks("2. the root reads No content for its output", edit(no_content),
       ["the root's output is the reply (not empty, not the prompt)"])
breaks("2. the root's output is the prompt again", edit(echo),
       ["the root's output is the reply (not empty, not the prompt)"])
breaks("2. the root's input is empty", edit(no_prompt), ["the root's input is the prompt (not empty)"])
breaks("3. no deploy_app row", edit(no_deploy), ["a tool row deploy_app sits under the root"], ["--trace", TID])
breaks("4. the root lasts 14 ms", edit(short_root),
       ["the root starts with the chat and ends after its last span (100 ms slack)"])
breaks("4. the root starts half a second late", edit(late_root),
       ["the root starts with the chat and ends after its last span (100 ms slack)"])
breaks("5. an llm row without output tokens", edit(no_output_tokens), ["every llm row carries input and output tokens"])
breaks("5. no estimated cost", edit(unpriced), [COST])
breaks("5. a row reads skipped_tokens_missing", edit(skipped_tokens),
       ["no row reads cost_estimate_status:skipped_tokens_missing"])
breaks("5. no llm row at all", edit(no_llm), ["the chat has model-call (llm) rows"])
rc, failed, text, _ = run(edit(lambda r, b, w: None), ["--trace", "f" * 32])
check("a trace with no spans fails", rc == 1 and failed == ["the trace has spans in Agent Observability"], str(failed))

print("== which chat is judged ==")
chat_root = next(s for s in GOOD["window"]["data"] if s["attributes"]["name"] == "POST")


def toolless_chat(tid: str, later_s: int) -> dict:
    s = copy.deepcopy(chat_root)
    s["attributes"].update(trace_id=tid, start_ns=s["attributes"]["start_ns"] + later_s * 10**9)
    return s


rc, failed, text, _ = run(GOOD, listing=GOOD["window"]["data"] + [toolless_chat("a" * 32, 60)])
check("a newer chat that called no tool is passed over for the one that called both",
      f"trace {TID} (the newest of 2 /chat traces that called" in text and rc == 0, text[:300])
lone = toolless_chat("b" * 32, 60)
rc, failed, text, _ = run(GOOD, listing=[lone])
check("with no chat that called both, the newest chat is judged and named as such",
      "none of them called read_support_ticket and deploy_app" in text and rc == 1, text[:300])
rc, failed, text, _ = run(GOOD, listing=[s for s in GOOD["window"]["data"] if s["attributes"]["name"] != "POST"])
check("no /chat in the window fails, never skips, and says to drive one",
      rc == 1 and "FAIL: no /chat" in text and "Send one chat" in text, text[-300:])
rc, failed, text, _ = run(GOOD, listing=[])
check("an empty window fails the same way", rc == 1 and "FAIL: no /chat" in text, text[-300:])
rc, failed, text, org = run(GOOD, org="Some Other Org")
check("a key that reaches another org judges nothing there",
      rc == 1 and "not the sandbox org" in text and not any(p == judge.dd_traces.LLMOBS_PATH for _, p, _ in org.calls))

print("== the live test is in the E2E suite, this one is not ==")
check("test_llmobs_chat_judge_live.py carries '# SUITE: e2e'",
      "\n# SUITE: e2e" in (HERE / "test_llmobs_chat_judge_live.py").read_text())
check("this offline test does not", "\n# SUITE: e2e" not in pathlib.Path(__file__).read_text())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("llmobs_chat_judge judges the recorded payload as the live org read it, and each break turns its check red.")
