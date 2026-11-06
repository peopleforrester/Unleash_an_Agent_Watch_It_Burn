# ABOUTME: Offline check that decisions.md records #759's live read: a #759 entry gives the command a run read one
# ABOUTME: recent BurritoBot trace with (sourced session, then dd_traces.py), that it exited 0, and the trace it printed (#893).
"""#759's criterion "A run reads back one recent BurritoBot trace through that access and records the command in
decisions.md" was held only in part (#893). test_dd_traces_live.py does the read, and test_dd_traces.py judges the
reader against a fake org, but nothing read decisions.md, so the record could be dropped or go stale and no test
would say so.

This reads decisions.md and fails unless one entry headed with #759 records the read whole:

  the access:   `. "$HECATON_CLUSTER_ENV"` and then a `python3 verify/dd_traces.py` command, and the entry names the
                secret fleet_monitors.read_keys reads (fleet_monitors.SECRET_ID);
  the command:  run through dd_traces.main against a fake org of three traces, with a keys stub, it asks for the pair
                as the profile and region AGENTS.md gives a dispatched run's session, exits 0, and prints exactly
                one trace, the newest;
  the outcome:  the entry says the command exited 0;
  the output:   after the command, the header dd_traces.main prints for ml_app:burritobot over the command's own
                --minutes, then a trace line of the shape show_trace prints, then at least one span line under it;
  recent:       the entry stamps when the command ran (`At <YYYY-MM-DDTHH:MMZ>` before the source step), and the
                printed trace started inside the command's window before then.

It then cuts the record it found in nine ways (no command, `--traces` 3, another profile, `--scopes`, no source
step, no trace line, a header for another window, a run time two days on, no exit 0) and checks each one fails, so the
checks above are shown to bite on the real entry and not only on a fixture. Nothing here reaches Datadog or AWS.
"""
from __future__ import annotations

import datetime as dt
import io
import pathlib
import re
import shlex
import sys
import urllib.parse
from contextlib import redirect_stderr

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import dd_traces  # noqa: E402

fm = dd_traces.fm
DECISIONS = REPO / "decisions.md"
AGENTS = REPO / "AGENTS.md"
ISSUE = "#759"
SOURCE_STEP = '. "$HECATON_CLUSTER_ENV"'
COMMAND = "python3 verify/dd_traces.py"
# A run's clock and Datadog's agree to within this; the record stamps the run to the minute.
SKEW = dt.timedelta(minutes=1)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ---- What the tree says: the run's profile and region, the secret, the shape of a printed trace ----
print("== the tree names a run's AWS session, the secret and what dd_traces.py prints ==")
agents = flat(AGENTS.read_text(encoding="utf-8"))
m = re.search(r"a 12-hour session for the `([\w-]+)` AWS profile \(account (\d+), ([a-z]{2}-[a-z]+-\d)\)", agents)
check("AGENTS.md names the AWS profile and region of a dispatched run's session", bool(m))
profile, region = (m.group(1), m.group(3)) if m else ("", "")
secret_id = fm.SECRET_ID
check("fleet_monitors names the secret the pair is read from", bool(secret_id))

# The trace line as show_trace prints it: `trace <id>  <start>  <n> spans  <r> root(s)  env=<env>`.
TRACE_LINE = re.compile(r"^trace ([0-9a-f]{16,32})  (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00)  (\d+) spans  "
                        r"(\d+) root\(s\)  env=\S+$")
SPAN_LINE = re.compile(r"^  +\S+ .*  \d+ ms  \S+")
HEADER = re.compile(r"^== (.+): ml_app:(\S+), last (\d+) minutes ==$")
STAMP = re.compile(r"\b(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z)")

T0 = 1_793_000_000 * 10**9  # ns; the fake org's spans start from here


def fake_span(trace: str, sid: str, parent: str, name: str, kind: str, start_s: int) -> dict:
    return {"id": sid, "type": "span", "attributes": {
        "trace_id": trace, "span_id": sid, "parent_id": parent, "name": name, "span_kind": kind, "status": "ok",
        "ml_app": dd_traces.ML_APP, "start_ns": T0 + start_s * 10**9, "duration": 900 * 10**6,
        "tags": [f"env:{dd_traces.DD_ENV}"], "metrics": {}}}


NEWEST = "c" * 32
SPANS = [fake_span("a" * 32, "a1", "undefined", "POST", "agent", 0),
         fake_span(NEWEST, "c1", "undefined", "POST", "agent", 120),
         fake_span(NEWEST, "c2", "c1", "generate_content", "llm", 121),
         fake_span("b" * 32, "b1", "undefined", "POST", "agent", 60)]


def fake_http(method, url, headers, body):
    """The fake org: the current user, the LLM Observability span listing (by trace when asked) and APM; GETs only."""
    parts = urllib.parse.urlsplit(url)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    if method != "GET":
        return 405, {"errors": ["fake org: reads only"]}
    if parts.path == dd_traces.ME_PATH:
        return 200, {"data": {"type": "users"}, "included": [{"type": "orgs", "attributes": {"name": "Datadog"}}]}
    if parts.path == dd_traces.LLMOBS_PATH:
        t = q.get("filter[trace_id]")
        return 200, {"data": [s for s in SPANS if t is None or s["attributes"]["trace_id"] == t]}
    if parts.path == dd_traces.APM_PATH:
        return 200, {"data": []}
    return 404, {"errors": [f"fake org: no {parts.path}"]}


shown: list[str] = []
dd_traces.show_trace(NEWEST, [s["attributes"] for s in SPANS if s["attributes"]["trace_id"] == NEWEST],
                     say=shown.append)
check("show_trace prints the trace line and span lines this test reads in the record",
      bool(shown) and bool(TRACE_LINE.match(shown[0])) and all(SPAN_LINE.match(s) for s in shown[1:]),
      repr(shown[:2]))


def fake_run(cmd: str) -> dict | str:
    """What the command does in dd_traces.main against the fake org, or why it is not a command a run could use."""
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return f"not a shell command: {e}"
    if argv[:2] != COMMAND.split():
        return f"does not run {COMMAND}"
    asked: list[tuple[str, str]] = []

    def keys(p: str, r: str):
        asked.append((p, r))
        return "fake-api", "fake-app", "datadoghq.com"

    out: list[str] = []
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            rc = dd_traces.main(argv[2:], env={}, keys=keys, http=fake_http, say=out.append)
    except SystemExit as e:
        return f"dd_traces.py's parser refuses it (exit {e.code}): {flat(err.getvalue()).strip()[:200]}"
    lines = "\n".join(out).splitlines()
    header = next((HEADER.match(ln) for ln in lines if HEADER.match(ln)), None)
    return {"rc": rc, "asked": asked, "traces": [t.group(1) for t in map(TRACE_LINE.match, lines) if t],
            "minutes": int(header.group(3)) if header else None, "err": flat(err.getvalue()).strip()}


# ---- What decisions.md records ----
def entries(text: str) -> list[tuple[str, str]]:
    """decisions.md's entries as (heading, body), split at each `## ` line."""
    out, head, body = [], None, []
    for ln in text.splitlines():
        if ln.startswith("## "):
            if head is not None:
                out.append((head, "\n".join(body)))
            head, body = ln, []
        elif head is not None:
            body.append(ln)
    if head is not None:
        out.append((head, "\n".join(body)))
    return out


def commands(body: str) -> list[tuple[int, str]]:
    """Each `python3 verify/dd_traces.py ...` in the entry, from a code block line or a code span, with its line."""
    found = []
    for i, ln in enumerate(body.splitlines()):
        for span in re.findall(r"`([^`]*python3 verify/dd_traces\.py[^`]*)`", ln) or [ln]:
            s = span.strip()
            if s.startswith(COMMAND):
                found.append((i, s))
    return found


def record_problems(body: str) -> list[str]:
    """What the entry leaves out of a record of the read; empty when it records it whole."""
    lines = body.splitlines()
    left: list[str] = []
    src = next((i for i, ln in enumerate(lines) if ln.strip() == SOURCE_STEP), None)
    if src is None:
        left.append(f"the source step {SOURCE_STEP} on a line of its own")
    if secret_id not in body:
        left.append(f"the secret {secret_id}")
    if "exited 0" not in flat(body):
        left.append("that the command exited 0")
    cmds = [(i, c) for i, c in commands(body) if src is not None and i > src]
    if not cmds:
        left.append(f"a `{COMMAND}` command after the source step")
        return left
    runs = {c: fake_run(c) for _, c in cmds}

    def reads_one(r) -> bool:
        return (isinstance(r, dict) and r["rc"] == 0 and r["asked"] == [(profile, region)]
                and r["traces"] == [NEWEST])

    good = [(i, c) for i, c in cmds if reads_one(runs[c])]
    if not good:
        left.append(f"a command that, against a fake org of three traces, asks for the pair as {profile} in {region}, "
                    f"exits 0 and prints exactly the newest trace ("
                    + "; ".join(f"{c!r}: " + (str(r) if isinstance(r, str) else
                                              f"exit {r['rc']}, asked {r['asked']}, printed {r['traces']}"
                                              + (f", stderr {r['err'][:120]}" if r["err"] else ""))
                                for c, r in runs.items()) + ")")
        return left
    at, cmd = good[0]
    minutes = runs[cmd]["minutes"]

    # The output, after the command: the header for this window, then one trace line and its spans.
    after = lines[at + 1:]
    head = next((j for j, ln in enumerate(after) if HEADER.match(ln.strip())), None)
    hm = HEADER.match(after[head].strip()) if head is not None else None
    if not hm or hm.group(2) != dd_traces.ML_APP or int(hm.group(3)) != minutes:
        left.append(f"the output header `== <org>: ml_app:{dd_traces.ML_APP}, last {minutes} minutes ==` after the "
                    f"command" + (f" (it reads {after[head].strip()!r})" if hm else ""))
        return left
    rest = [ln[4:] if ln.startswith("    ") else ln for ln in after[head + 1:]]
    rest = [ln for ln in rest if ln.strip()]
    tm = TRACE_LINE.match(rest[0]) if rest else None
    if not tm:
        left.append(f"the trace line show_trace prints, right under the header (it reads {rest[:1]})")
        return left
    if len(rest) < 2 or not SPAN_LINE.match(rest[1]) or int(tm.group(3)) < 1:
        left.append(f"a span line under trace {tm.group(1)}")

    # Recent: the trace started inside the command's window before the run's stamp.
    stamps = [STAMP.findall(ln) for ln in lines[:src]]
    stamp = next((s[-1] for s in reversed(stamps) if s), None)
    if stamp is None:
        left.append("when the command ran (`At <YYYY-MM-DDTHH:MMZ>`, before the source step)")
        return left
    ran = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    started = dt.datetime.fromisoformat(tm.group(2))
    if not (ran - dt.timedelta(minutes=minutes) <= started <= ran + SKEW):
        left.append(f"a trace inside the command's {minutes}-minute window before it ran at {stamp} "
                    f"(trace {tm.group(1)} started {tm.group(2)})")
    return left


print(f"== a {ISSUE} entry in decisions.md records the command a run read one recent trace with, and the trace ==")
text = DECISIONS.read_text(encoding="utf-8")
ours = [(h, b) for h, b in entries(text) if re.search(rf"{re.escape(ISSUE)}(?![\w'])", h)]
check(f"decisions.md has entries headed with {ISSUE}", bool(ours))
found = [(h, b, record_problems(b)) for h, b in ours]
whole = [(h, b) for h, b, p in found if not p]
if found:
    closest = min(found, key=lambda x: len(x[2]))
    check(f"one {ISSUE} entry records `{SOURCE_STEP}`, a `{COMMAND} --profile {profile} ... --traces 1` command "
          f"that exited 0, and the one recent trace it printed", bool(whole),
          f"closest is {closest[0]!r}, which leaves out: {'; '.join(closest[2])}")
if whole:
    heading, body = whole[-1]
    print(f"  the record is {heading!r}")

    # ---- The record, cut: each cut must fail, so the checks above bite on the real entry ----
    print("== the record found, cut in nine ways, fails each time ==")
    cmd = next(c for i, c in commands(body) if not isinstance(fake_run(c), str) and fake_run(c)["rc"] == 0)
    hm = next(HEADER.match(ln.strip()) for ln in body.splitlines() if HEADER.match(ln.strip()))
    trace_ln = next(ln for ln in body.splitlines() if TRACE_LINE.match(ln.strip()))
    src_at = next(i for i, ln in enumerate(body.splitlines()) if ln.strip() == SOURCE_STEP)
    stamp = next(s[-1] for s in reversed([STAMP.findall(ln) for ln in body.splitlines()[:src_at]]) if s)
    two_days_on = (dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")) + dt.timedelta(days=2)
                   ).strftime("%Y-%m-%dT%H:%MZ")
    cuts = {
        "no command": (cmd, ""),
        "--traces 3": ("--traces 1", "--traces 3"),
        "another profile": (f"--profile {profile}", "--profile someone-else"),
        "--scopes instead": (cmd, f"{COMMAND} --profile {profile} --scopes"),
        "no source step": (SOURCE_STEP, ""),
        "no trace line": (trace_ln, ""),
        "a header for another window": (hm.group(0), hm.group(0).replace(f"last {hm.group(3)} minutes",
                                                                         f"last {int(hm.group(3)) + 1} minutes")),
        "run two days on": (stamp, two_days_on),
        "no exit 0": ("exited 0", "exited"),
    }
    for name, (old, new) in cuts.items():
        if old not in body:
            print(f"{DECISIONS.name}: the record no longer holds {old!r}, which the cut '{name}' replaces; "
                  f"reword the cut with the record", file=sys.stderr)
            sys.exit(1)
        cut = body.replace(old, new)
        got = record_problems(cut)
        check(f"cut '{name}': the record is refused", bool(got))
        print(f"        ({'; '.join(got)})")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {ISSUE} trace record checks passed.")
