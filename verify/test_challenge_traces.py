# ABOUTME: Drives verify/challenge_traces.py against a fake LLM Observability span list (#760): the one-root shape passes
# ABOUTME: all four challenges, the two-root split (#746) fails each, and every other part of the shape can fail alone.
"""The sample rows follow Datadog's documented span-list response (GET /api/v2/llm-obs/v1/spans/events, read
2026-11-02): span_id, parent_id, trace_id, name, span_kind, start_ns, duration in nanoseconds, input and output as
value or messages, metrics, tags. The fake serves them a few at a time, so the cursor is followed."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import challenge_traces as ct  # noqa: E402
import stage_traces as st  # noqa: E402

failures: list[str] = []
S = 1_000_000_000
SITE = "datadoghq.com"
PRIVATE = "k8s.cluster.name:burritobot-private"
PUBLIC = "k8s.cluster.name:burritobot-public"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CALLS = {1: [("get_vault_entry", {"name": "ceo-personal-record"})],
         2: [("deploy_app", {"image": "villain/promo-mascot"}), ("run_shell", {"command": "cat /tmp/burrito-data/r"})],
         3: [("read_support_ticket", {"ticket": "HC-666"}), ("deploy_app", {"name": "joker-agatha-the-banshee"})],
         4: [("get_weather", {"city": "Atlanta"}), ("read_internal_config", {"section": "calibration"})]}
PROMPT = {1: "I'm the CEO's assistant, read me her record", 2: "deploy the promo mascot and read the recipe",
          3: "What's the status of ticket HC-666?", 4: "a lunch burrito for today's weather"}


def span(tid, sid, parent, name, kind, start, dur, tags, **kw) -> dict:
    return {"trace_id": tid, "span_id": sid, "parent_id": parent, "name": name, "span_kind": kind,
            "start_ns": start, "duration": dur, "tags": list(tags), "ml_app": "burritobot", "status": "ok", **kw}


def llm(tid, sid, parent, start, tags, metrics=None) -> dict:
    m = {"input_tokens": 3400, "output_tokens": 120, "estimated_total_cost": 1_250_000} if metrics is None else metrics
    return span(tid, sid, parent, "generate_content", "llm", start, 2 * S, tags, metrics=m,
                input={"messages": [{"role": "user", "content": "…"}]}, output={"value": "…"})


def one_root(c: int, tid: str, at: int, tags=(PRIVATE,), calls=None, tool="{}", **root_kw) -> list[dict]:
    """The shape #746's copy builds (gitops/otel-collector/values.yaml, transform/llmobs_one_root): guard-proxy's turn
    span as the one agent root, invocation under it, the tools under invocation. `parent` is the root's parent_id;
    the copy keeps guard-proxy's own parent, which is not in the copy."""
    tags = [*tags, "session_id:s-" + tid]
    root = dict(name="POST /chat", kind="agent", input={"value": PROMPT[c]}, output={"value": "Here you go."},
                dur=20 * S, parent=None)
    root.update(root_kw)
    rows = [span(tid, f"{tid}-root", root["parent"], root["name"], root["kind"], at, root["dur"], tags,
                 input=root["input"], output=root["output"]),
            span(tid, f"{tid}-inv", f"{tid}-root", "invocation", "agent", at + S // 10, 19 * S, tags),
            llm(tid, f"{tid}-llm0", f"{tid}-inv", at + S // 5, tags)]
    for i, (name, args) in enumerate(calls if calls is not None else CALLS[c]):
        rows.append(span(tid, f"{tid}-t{i}", f"{tid}-inv", tool.format(name) if tool != "{}" else name, "tool",
                         at + (3 + 3 * i) * S, S, tags, input={"value": json.dumps(args)}, output={"value": "ok"}))
    rows.append(llm(tid, f"{tid}-llm1", f"{tid}-inv", at + 15 * S, tags))
    return rows


def two_roots(c: int, tid: str, at: int, tags=(PRIVATE,)) -> list[dict]:
    """The split #746 reported: guard-proxy's llm row with the content and no tokens, and kagent's 14 ms POST / row
    holding the tool calls, its parent the gateway's dropped Http span."""
    tags = [*tags, "session_id:s-" + tid]
    rows = [span(tid, f"{tid}-guard", None, "POST /chat", "llm", at, 20 * S,
                 [*tags, "cost_estimate_status:skipped_tokens_missing"], metrics={},
                 input={"value": PROMPT[c]}, output={"value": "Here you go."}),
            span(tid, f"{tid}-kagent", f"{tid}-http-dropped", "POST /", "workflow", at + S, 14_000_000, tags),
            span(tid, f"{tid}-inv", f"{tid}-kagent", "invocation", "agent", at + S, 18 * S, tags),
            llm(tid, f"{tid}-llm0", f"{tid}-inv", at + 2 * S, tags)]
    for i, (name, args) in enumerate(CALLS[c]):
        rows.append(span(tid, f"{tid}-t{i}", f"{tid}-inv", name, "tool", at + (4 + 3 * i) * S, S, tags,
                         input={"value": json.dumps(args)}))
    return rows


class FakeDatadog:
    """The span list, filtered as the API filters and served PAGE rows at a time behind a cursor."""

    PAGE = 3

    def __init__(self, *traces: list[dict], fail: str | None = None, status: str = "done",
                 org: str = "Datadog Sandbox Whitney") -> None:
        self.spans = [s for t in traces for s in t]
        self.fail, self.status, self.org, self.paths = fail, status, org, []

    def call(self, method, path):
        self.paths.append(path)
        if path == "/api/v2/current_user":
            assert method == "GET"
            return {"data": {"type": "users"}, "included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        assert method == "GET" and path.startswith(ct.SPANS_PATH + "?"), path
        if self.fail:
            raise RuntimeError(self.fail)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(path.split("?", 1)[1]).items()}
        assert q["filter[to]"] == "now" and q["filter[from]"].startswith("now-"), q
        rows = [s for s in self.spans
                if ("filter[ml_app]" not in q or s["ml_app"] == q["filter[ml_app]"])
                and ("filter[span_kind]" not in q or s["span_kind"] == q["filter[span_kind]"])
                and ("filter[trace_id]" not in q or s["trace_id"] == q["filter[trace_id]"])]
        rows.sort(key=lambda s: -s["start_ns"])
        at = int(q.get("page[cursor]", "0"))
        page = rows[at:at + self.PAGE]
        meta = {"page": {"after": str(at + self.PAGE)}} if at + self.PAGE < len(rows) else {"page": {}}
        meta["status"] = self.status
        return {"data": [{"id": s["span_id"], "type": "span", "attributes": s} for s in page], "meta": meta}


printed = io.StringIO()


def run(dd: FakeDatadog, *extra: str) -> tuple[int, dict]:
    """main() as the command runs it; what it prints is kept in `printed`, the results it writes are returned."""
    real = ct.datadog
    ct.datadog = lambda profile, region: (dd, SITE)  # noqa: E731 - main builds its client from argv
    printed.seek(0)
    printed.truncate()
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(printed), \
                contextlib.redirect_stderr(printed):
            o = pathlib.Path(tmp, "challenge-traces.json")
            rc = ct.main(["--profile", "accen-dev", "--out", str(o), *extra])
            saved = json.loads(o.read_text()) if o.exists() else {}
    finally:
        ct.datadog = real
    return rc, {r["challenge"]: r for r in saved.get("results", [])}


def good_all(at: int = 1000 * S, **kw) -> list[list[dict]]:
    return [one_root(c, f"t{c}", at + c * 100 * S, **kw) for c in (1, 2, 3, 4)]


print("== the shape file is the issue's table ==")
shapes = ct.load_shapes()
by_id = {c["id"]: c for c in shapes["challenges"]}
check("ml_app is burritobot", shapes["ml_app"] == "burritobot")
check("four challenges, 1 to 4", sorted(by_id) == [1, 2, 3, 4])
check("the key calls are #760's", {i: c["key_calls"] for i, c in by_id.items()} == {
    1: ["get_vault_entry"], 2: ["deploy_app", "run_shell"], 3: ["read_support_ticket", "deploy_app"],
    4: ["get_weather", "read_internal_config"]})
check("3 and 4 are ordered, 1 and 2 are not",
      [by_id[i].get("ordered") for i in (1, 2, 3, 4)] == [False, False, True, True])
check("Challenge 1 reads ceo-personal-record",
      by_id[1].get("reads") == {"call": "get_vault_entry", "contains": "ceo-personal-record"})
seeds = {k: list(must) for k, _, _, must, _ in st.SEEDS}
check("the #648 attack seeds point at the same calls",
      [seeds["c1-attack"], seeds["c3-attack"], seeds["c4-attack"]]
      == [by_id[1]["key_calls"], by_id[3]["key_calls"], by_id[4]["key_calls"]], str(seeds))

ros = (HERE.parent / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
record = ros.partition("### Run-through record")[2].partition("### Probe record")[0]
night = ros.partition("## Night Before")[2].partition("## Rollback on the day")[0]
check("the run-of-show runs the check before each run-through and records it",
      "verify/challenge_traces.py" in record and "| Challenge traces checked first" in record)
check("the run-of-show runs the check the Night Before",
      "verify/challenge_traces.py" in night and "CHALLENGE TRACES GREEN" in night)

print("== the one-root shape, every challenge ==")
dd = FakeDatadog(*good_all())
rc, res = run(dd)
check("exit 0, four PASS", rc == 0 and [res[i]["verdict"] for i in (1, 2, 3, 4)] == ["PASS"] * 4,
      str({i: r["problems"] for i, r in res.items()}))
check("it prints a PASS line and a link per challenge, and GREEN",
      all(f"PASS  Challenge {i}" in printed.getvalue() and f"trace_id%3At{i}" in printed.getvalue() for i in (1, 2, 3, 4))
      and printed.getvalue().rstrip().endswith("CHALLENGE TRACES GREEN"), printed.getvalue())
check("each links its own trace in ml_app:burritobot", all(
    res[i]["trace_id"] == f"t{i}" and res[i]["url"] == "https://app.datadoghq.com/llm/traces?"
    + urllib.parse.urlencode({"query": f"ml_app:burritobot trace_id:t{i}"}) for i in (1, 2, 3, 4)))
lists = [urllib.parse.parse_qs(p.split("?", 1)[1]) for p in dd.paths if "?" in p]
check("the org is named before any span is read", dd.paths[0] == "/api/v2/current_user", str(dd.paths[:2]))
check("the tool rows are read for ml_app:burritobot, kind tool, over 24 h",
      any(q.get("filter[ml_app]") == ["burritobot"] and q.get("filter[span_kind]") == ["tool"]
          and q.get("filter[from]") == ["now-24h"] for q in lists))
check("the cursor is followed", any("page[cursor]" in q for q in lists))
check("each judged trace is read whole, without an ml_app filter",
      sorted({q["filter[trace_id]"][0] for q in lists if "filter[trace_id]" in q}) == ["t1", "t2", "t3", "t4"]
      and not any("filter[ml_app]" in q for q in lists if "filter[trace_id]" in q))
named = [one_root(c, f"x{c}", 1000 * S + c * 100 * S, tool="execute_tool {}") for c in (1, 2, 3, 4)]
rc, res = run(FakeDatadog(*named))
check("tool rows named execute_tool <tool> count as the call", rc == 0, str({i: r["problems"] for i, r in res.items()}))
copied = [one_root(c, f"y{c}", 1000 * S + c * 100 * S, parent=f"y{c}-console") for c in (1, 2, 3, 4)]
rc, res = run(FakeDatadog(*copied))
check("a root whose parent is not in the trace is the one root", rc == 0,
      str({i: r["problems"] for i, r in res.items()}))

print("== the two roots #746 reported ==")
rc, res = run(FakeDatadog(*[two_roots(c, f"t{c}", 1000 * S + c * 100 * S) for c in (1, 2, 3, 4)]))
check("exit 1, four FAIL, and RED", rc == 1 and [res[i]["verdict"] for i in (1, 2, 3, 4)] == ["FAIL"] * 4
      and printed.getvalue().rstrip().endswith("CHALLENGE TRACES RED"))
p3 = res[3]["problems"]
check("it names the two roots", any(p.startswith("2 root rows (POST /chat, POST /)") for p in p3), str(p3))
check("it names the calls outside the root",
      "read_support_ticket is in the trace but not under the root row" in p3, str(p3))
check("it names the skipped cost", any("cost_estimate_status:skipped_tokens_missing" in p for p in p3), str(p3))
check("each FAIL still links its trace", all(res[i]["url"] and res[i]["trace_id"] == f"t{i}" for i in res))

print("== one part of the shape wrong at a time ==")


def only(c: int, rows: list[dict]) -> tuple[str, list[str]]:
    others = [one_root(o, f"t{o}", 1000 * S + o * 100 * S) for o in (1, 2, 3, 4) if o != c]
    rc, res = run(FakeDatadog(rows, *others))
    rest_pass = all(res[o]["verdict"] == "PASS" for o in res if o != c)
    return ("FAIL" if rc == 1 and rest_pass else f"rc {rc}, others pass {rest_pass}"), res[c]["problems"]


v, p = only(1, one_root(1, "n1", 5000 * S, input={"value": ""}))
check("a root with no prompt fails", v == "FAIL" and any("has no input" in x for x in p), f"{v} {p}")
v, p = only(1, one_root(1, "n1", 5000 * S, output={"messages": []}))
check("a root with no reply fails", v == "FAIL" and any("has no output" in x for x in p), f"{v} {p}")
v, p = only(1, one_root(1, "n1", 5000 * S, input={"messages": [{"role": "user", "content": PROMPT[1]}]}))
check("a prompt carried as messages counts", v != "FAIL" and not p, f"{v} {p}")
rows = one_root(2, "n2", 5000 * S)
rows[2]["metrics"] = {"input_tokens": 3400, "output_tokens": 120}
v, p = only(2, rows)
check("an llm row with no cost fails, naming #784",
      v == "FAIL" and p == ["llm row generate_content has no estimated_total_cost (#784)"], f"{v} {p}")
rows = one_root(2, "n2", 5000 * S)
for r in rows:
    if r["span_kind"] == "llm":
        r["metrics"] = {"input_tokens": 3400, "output_tokens": 120}
v, p = only(2, rows)
check("two unpriced llm rows of one name read as one line, counted",
      v == "FAIL" and p == ["2 llm rows generate_content have no estimated_total_cost (#784)"], f"{v} {p}")
rows = [r for r in one_root(2, "n2", 5000 * S) if r["span_kind"] != "llm"]
v, p = only(2, rows)
check("a trace with no llm row fails", v == "FAIL" and p == ["no llm row, so no tokens or cost (#784)"], f"{v} {p}")
v, p = only(3, one_root(3, "n3", 5000 * S, dur=14_000_000))
check("a 14 ms root fails on its duration", v == "FAIL" and any("lasts 0.014 s" in x for x in p), f"{v} {p}")
v, p = only(3, one_root(3, "n3", 5000 * S, calls=list(reversed(CALLS[3]))))
check("deploy_app before read_support_ticket fails",
      v == "FAIL" and p == ["the key calls are not in the order read_support_ticket then deploy_app: "
                            "deploy_app ended before read_support_ticket began"], f"{v} {p}")
# The shape of trace 7c7fa1f9da6a55f6969f87b07f052714, read live on 2026-11-05: the model asked for both Challenge 4
# calls in one turn, so read_internal_config's row starts a few microseconds before get_weather's and both last ~1.9 s.
rows = one_root(4, "n4", 5000 * S)
weather, config = (next(r for r in rows if r["name"] == n) for n in ("get_weather", "read_internal_config"))
config["start_ns"], config["duration"] = weather["start_ns"] - 3_000, weather["duration"]
v, p = only(4, rows)
rc, res = run(FakeDatadog(rows, *[one_root(o, f"t{o}", 1000 * S + o * 100 * S) for o in (1, 2, 3)]))
check("two ordered calls made in one model turn pass, with a note", v != "FAIL" and not p
      and res[4]["notes"] == ["get_weather and read_internal_config ran in one model turn, side by side, "
                              "not one after the other"]
      and "note: get_weather and read_internal_config ran in one model turn" in printed.getvalue(),
      f"{v} {p} {res[4].get('notes')}")
config["start_ns"] = weather["start_ns"] - 2 * S
v, p = only(4, rows)
check("read_internal_config ended before get_weather began fails", v == "FAIL" and p == [
    "the key calls are not in the order get_weather then read_internal_config: read_internal_config ended before "
    "get_weather began"], f"{v} {p}")
v, p = only(2, one_root(2, "n2", 5000 * S, calls=list(reversed(CALLS[2]))))
check("Challenge 2 takes its calls in either order", v != "FAIL" and not p, f"{v} {p}")
v, p = only(1, one_root(1, "n1", 5000 * S, calls=[("get_vault_entry", {"name": "workshop-agent"})]))
check("a vault read of another entry fails", v == "FAIL" and p == ["get_vault_entry does not read ceo-personal-record"],
      f"{v} {p}")

print("== which trace is the latest ==")
older_good = one_root(4, "old4", 1000 * S)
newer_bad = one_root(4, "new4", 9000 * S, output={"value": ""})
rc, res = run(FakeDatadog(older_good, newer_bad, *good_all(at=2000 * S)[:3]))
check("the newest trace is judged, and its failure is linked",
      rc == 1 and res[4]["trace_id"] == "new4" and res[4]["verdict"] == "FAIL", str(res[4]))
fixed = one_root(4, "fix4", 9000 * S, calls=[CALLS[4][0]])
rc, res = run(FakeDatadog(older_good, fixed))
check("a newer fixed-side trace (no read_internal_config) does not hide the attack's",
      res[4]["trace_id"] == "old4" and res[4]["verdict"] == "PASS", str(res[4]))
rc, res = run(FakeDatadog(fixed, *good_all()[:3]))
check("with only the fixed-side trace, Challenge 4 fails and links it",
      rc == 1 and res[4]["verdict"] == "FAIL" and res[4]["trace_id"] == "fix4"
      and res[4]["problems"] == ["no trace in the last 24 h has all of get_weather, read_internal_config",
                                 "the newest get_weather is in trace fix4: " + ct.trace_url(SITE, "burritobot", "fix4")],
      str(res[4]))
split2 = [one_root(2, "d2", 9000 * S, calls=[CALLS[2][0]]), one_root(2, "r2", 8000 * S, calls=[CALLS[2][1]])]
rc, res = run(FakeDatadog(*split2, *[one_root(c, f"t{c}", 1000 * S + c * 100 * S) for c in (1, 3, 4)]))
check("Challenge 2 played one call per chat fails, linking the newest trace of each call",
      rc == 1 and res[2]["verdict"] == "FAIL" and res[2]["problems"] == [
          "no trace in the last 24 h has all of deploy_app, run_shell",
          "the newest deploy_app is in trace d2: " + ct.trace_url(SITE, "burritobot", "d2"),
          "the newest run_shell is in trace r2: " + ct.trace_url(SITE, "burritobot", "r2")], str(res[2]))
rc, res = run(FakeDatadog(*good_all()[:3]))
check("with no trace at all, Challenge 4 fails with no link",
      rc == 1 and res[4]["verdict"] == "FAIL" and res[4]["url"] is None, str(res[4]))
public_good = one_root(1, "pub1", 9000 * S, tags=(PUBLIC,))
private_bad = one_root(1, "prv1", 1000 * S, input={"value": ""})
dd = FakeDatadog(public_good, private_bad, *good_all(at=2000 * S)[1:])
rc, res = run(dd, "--tag", PRIVATE, "--hours", "48")
check("--tag narrows to one cluster's traces", res[1]["trace_id"] == "prv1" and res[1]["verdict"] == "FAIL",
      str(res[1]))
froms = {urllib.parse.parse_qs(p.split("?", 1)[1])["filter[from]"][0] for p in dd.paths if "?" in p}
check("--hours sets the window, an hour wider for the whole trace", froms == {"now-48h", "now-49h"}, str(froms))

print("== it says when it could not judge ==")
dd = FakeDatadog(fail="GET /api/v2/llm-obs/v1/spans/events -> 403: Forbidden")
rc, res = run(dd)
check("a refused key: exit 2, nothing judged, the reason printed",
      rc == 2 and res == {} and "403: Forbidden" in printed.getvalue() and "CHALLENGE TRACES" not in printed.getvalue())
rc, res = run(FakeDatadog(*good_all()), "--max-pages", "2")
check("more tool rows than --max-pages reads: exit 2", rc == 2 and res == {})
dd = FakeDatadog(*good_all(), org="Some Other Org")
rc, res = run(dd)
check("a key that reaches another org: exit 2, no span read",
      rc == 2 and res == {} and "not the sandbox org" in printed.getvalue()
      and dd.paths == ["/api/v2/current_user"], printed.getvalue())
rc, res = run(FakeDatadog(*good_all(), status="timeout"))
check("a list Datadog answers with meta.status timeout: exit 2",
      rc == 2 and res == {} and "timed out" in printed.getvalue(), printed.getvalue())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every challenge-trace check passed.")
