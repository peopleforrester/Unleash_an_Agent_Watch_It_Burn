# ABOUTME: Holds #1068: decisions.md records a guard_toggle line read on watch-it-burn-private after a verify toggle
# ABOUTME: (#1046's #1052 check), the pinned proxy.py writes that line, and the live check's judge fails each wrong log.
"""#1046's fourth criterion: one guard_toggle log line is read on watch-it-burn-private after a verify toggle (the
#1052 check), recorded in decisions.md. verify/test_guard_toggle_log_live.py runs that toggle and prints one
`guard_toggle read:` line; this holds, offline:

- the newest `guard_toggle read:` line in decisions.md, under a #1046 or #1068 entry: on watch-it-burn-private, the
  output guard, one line per change and every line matched, at least one read, at a checksum/proxy-py that is the
  proxy.py of a guard-proxy commit holding 0e7f15b (guard-proxy-agenticburn#67, the toggle log) at or before the pin;
- run 18491's entry, the first record (#1046): the line it quoted from watch-it-burn-private's log, at 5772a5d;
- that the pinned proxy.py writes the line: its formatter and _log_toggles, run from the pinned source, log one
  guard_toggle object per changed guard and none for a /toggle that changes nothing, and the judge reads them;
- the judges, on made-up logs: a clean log passes, and each way the criterion can stop holding fails it (no line, a
  line for a read, a change with no line, a wrong guard or value, no caller, the wrong caller, an empty peer);
- that the live check is an e2e test on PRIVATE_CONTEXT, so verify/run-e2e.sh runs it.
"""
from __future__ import annotations

import ast
import io
import json
import logging
import pathlib
import sys
import textwrap

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_toggle_log as gt  # noqa: E402
import pantry_replay as pr  # noqa: E402

REPO = HERE.parent
DECISIONS = REPO / "decisions.md"
LIVE = HERE / "test_guard_toggle_log_live.py"
TOGGLE_LOG = "0e7f15b89ac9ddca7182d48375813337c5f08f59"  # guard-proxy-agenticburn#67: the guard_toggle line
FIRST_PIN = "5772a5d8d7cb"  # the pin run 18491 read the line at
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def holds_log(commit: str) -> bool:
    return pr.git("merge-base", "--is-ancestor", TOGGLE_LOG, commit, cwd=pr.SUB).returncode == 0


def heading_above(text: str, pos: int) -> str:
    start = text.rfind("\n## ", 0, pos)
    return text[start + 1:text.find("\n", start + 1)] if start >= 0 else ""


text = DECISIONS.read_text(encoding="utf-8")
if pr.git("cat-file", "-e", f"{TOGGLE_LOG}^{{commit}}", cwd=pr.SUB).returncode != 0:
    print(f"FAILED: guard-proxy commit {TOGGLE_LOG[:7]} (#67) is not in {pr.SUB}; run verify/ensure-submodules.sh")
    sys.exit(1)
pin = pr.pinned()
check("the guard-proxy pin holds 0e7f15b, the guard_toggle line (guard-proxy-agenticburn#67)", holds_log(pin),
      f"pin {pin[:12]}")

print("== decisions.md's newest guard_toggle read line ==")
records = list(gt.RECORD_RE.finditer(text))
stray = [ln for ln in text.splitlines() if gt.RECORD_PREFIX + " watch-it-burn" in ln and not gt.RECORD_RE.search(ln)]
check("every `guard_toggle read:` line in decisions.md reads as the live check prints it", not stray, f"{stray[:2]}")
check("decisions.md records the live guard_toggle read", bool(records),
      f"no line matches {gt.RECORD_RE.pattern!r}: run verify/test_guard_toggle_log_live.py and record its line")
if records:
    m = records[-1]
    r = m.groupdict()
    n = {k: int(r[k]) for k in ("changes", "reads", "lines", "matched")}
    print(f"  INFO  {m.group(0)}")
    head = heading_above(text, m.start())
    check("it sits in a #1046 or #1068 entry", " · #1046 · " in head or " · #1068 · " in head, f"under {head!r}")
    check("it was read on watch-it-burn-private", r["context"] == "watch-it-burn-private", r["context"])
    check(f"the toggled guard is {gt.GUARD}", r["guard"] == gt.GUARD, r["guard"])
    check("a toggle changed the guard, and a read changed nothing", n["changes"] >= 1 and n["reads"] >= 1, f"{n}")
    check("one guard_toggle line per change, none for a read", n["lines"] == n["changes"], f"{n}")
    check("every line named its change, a peer and the caller", n["matched"] == n["changes"], f"{n}")
    made = next((c for c in pr.git("rev-list", f"{TOGGLE_LOG}^..{pin}", "--", "proxy.py", cwd=pr.SUB).stdout.split()
                 if pr.proxy_checksum(c) == r["checksum"]), "")
    check(f"proxy-py {r['checksum']} is a guard-proxy build from 0e7f15b to the pin {pin[:12]}", bool(made),
          "no commit in that range has that proxy.py")

print("== run 18491's read, the first record (#1046) ==")
first_head = "## 2026-11-08 · #1046 · run 18491 ·"
start = text.find(first_head)
if start < 0:
    print(f"FAILED: decisions.md has no heading starting {first_head!r}; this test reads run 18491's entry under it")
    sys.exit(1)
flat = " ".join(text[start:text.find("\n## ", start + 1)].split())
for words in ("watch-it-burn-private -n agent logs deploy/guard-proxy -c proxy",
              '"event": "guard_toggle", "guard": "output", "value": true, "was": false, "peer": "127.0.0.1",',
              "one per change, and none for the two reads",
              f"guard-proxy-agenticburn main `{FIRST_PIN}`"):
    check(f"run 18491's entry says {words!r}", words in flat)
first = pr.git("rev-parse", "-q", "--verify", f"{FIRST_PIN}^{{commit}}", cwd=pr.SUB).stdout.strip()
check("5772a5d, the pin it read at, holds 0e7f15b", bool(first) and holds_log(first))

print("== the pinned proxy.py writes the line the judge reads ==")
src = pr.git("show", f"{pin}:proxy.py", cwd=pr.SUB).stdout
tree = ast.parse(src)


def top(name: str) -> str:
    node = next((n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.Assign))
                 and name in ([n.name] if not isinstance(n, ast.Assign) else [getattr(t, "id", "") for t in n.targets])),
                None)
    if node is None:
        print(f"FAILED: the pinned proxy.py has no top-level {name}; this test runs it")
        sys.exit(1)
    return ast.get_source_segment(src, node)


method = next((f for c in tree.body if isinstance(c, ast.ClassDef) for f in c.body
               if isinstance(f, ast.FunctionDef) and f.name == "_log_toggles"), None)
if method is None:
    print("FAILED: the pinned proxy.py has no _log_toggles method; it writes the guard_toggle line")
    sys.exit(1)
buf = io.StringIO()
logger = logging.getLogger("guard-toggle-record-test")
logger.propagate = False
ns: dict = {"json": json, "logging": logging, "_OTEL_AVAILABLE": False, "log": logger}
for name in ("TOGGLE_KEYS", "TOGGLE_CALLER_MAX", "_TraceJsonFormatter", "_toggle_value_text"):
    exec(top(name), ns)  # noqa: S102
exec(textwrap.dedent(ast.get_source_segment(src, method)), ns)  # noqa: S102
handler = logging.StreamHandler(buf)
handler.setFormatter(ns["_TraceJsonFormatter"]())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
check("the pinned proxy.py keeps as much of X-WIB-Caller as the judge expects",
      ns["TOGGLE_CALLER_MAX"] == gt.CALLER_MAX, f"TOGGLE_CALLER_MAX is {ns['TOGGLE_CALLER_MAX']}")


class FakeHandler:
    client_address = ("127.0.0.1", 51234)

    def __init__(self, caller: str | None) -> None:
        self.headers = {"X-WIB-Caller": caller} if caller is not None else {}


state = {"input_blocklist": False, "input_classifier": False, "output": False, "budget": False, "topic": False,
         "cost_cap": 25.0}
holder = "verify/test_guard_toggle_log_live.py pid 1 by someone@host in a-checkout " + "x" * 200
ns["_log_toggles"](FakeHandler(holder), state, {**state, "output": True})
ns["_log_toggles"](FakeHandler(holder), {**state, "output": True}, {**state, "output": True})
ns["_log_toggles"](FakeHandler(holder), {**state, "output": True}, state)
logged = gt.parse(buf.getvalue())
changes = [("output", True, False), ("output", False, True)]
check("the pinned proxy.py logs one guard_toggle line per change and none for the read between",
      len(logged) == 2, f"{len(logged)} lines: {buf.getvalue()[:400]}")
check("the judge passes the lines the pinned proxy.py writes", not gt.judge(logged, changes, holder),
      f"{gt.judge(logged, changes, holder)}")
buf.truncate(0)
buf.seek(0)
ns["_log_toggles"](FakeHandler(None), state, {**state, "topic": True, "cost_cap": 2.0})
both = gt.parse(buf.getvalue())
check("a /toggle that changes two keys logs two lines, the caller empty with no header",
      [(x.get("guard"), x.get("caller")) for x in both] == [("topic", ""), ("cost_cap", "")], f"{both}")

print("== the judges, on made-up logs ==")
CALLER = "verify/test_guard_toggle_log_live.py pid 9 by me@host in 1270196839-1068-1"


def obj(guard: str, value, was, **over) -> dict:
    d = {"timestamp": "2026-11-09 00:00:00,000", "level": "INFO", "logger": "guard-proxy",
         "message": f"guard {guard} set to {json.dumps(value)}", "event": "guard_toggle", "guard": guard,
         "value": value, "was": was, "peer": "127.0.0.1", "caller": CALLER}
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


def log_of(*objs: dict) -> str:
    noise = json.dumps({"level": "INFO", "event": "chat_turn", "message": "turn"})
    return "\n".join(["not json", noise, *(json.dumps(o) for o in objs), noise])


CHANGES = [("output", True, False), ("output", False, True)]
clean = log_of(obj("output", True, False), obj("output", False, True))
check("the parser keeps only guard_toggle objects", len(gt.parse(clean)) == 2, f"{gt.parse(clean)}")
check("a clean log passes", not gt.judge(gt.parse(clean), CHANGES, CALLER), f"{gt.judge(gt.parse(clean), CHANGES, CALLER)}")
check("its record line parses back", (lambda m: bool(m) and m.group("matched") == "2" and m.group("lines") == "2")(
    gt.RECORD_RE.search(gt.record_line("watch-it-burn-private", "ddf97ec452c0", "output", 2, 3, 2, 2))))
check("a kubectl --prefix line still parses", len(gt.parse("[pod/guard-proxy-1/proxy] " + json.dumps(
    obj("output", True, False)))) == 1)


def fails(name: str, log: str, words: str, changes=CHANGES, caller: str = CALLER) -> None:
    got = gt.judge(gt.parse(log), changes, caller)
    check(f"fails: {name}", any(words in p for p in got), f"problems {got}")


fails("no guard_toggle line at all", log_of(), "0 guard_toggle line(s) for 2 change(s)")
fails("a line for a read as well", log_of(obj("output", True, False), obj("output", True, True),
                                          obj("output", False, True)), "3 guard_toggle line(s)")
fails("a change with no line", log_of(obj("output", True, False)), "1 guard_toggle line(s) for 2")
fails("a line naming the wrong guard", log_of(obj("topic", True, False), obj("output", False, True)), "the change was")
fails("a line with the wrong value", log_of(obj("output", False, False), obj("output", False, True)), "the change was")
fails("a line with no caller", log_of(obj("output", True, False, caller=None), obj("output", False, True)),
      "names no caller")
fails("a line naming another caller", log_of(obj("output", True, False, caller="someone else"),
                                             obj("output", False, True)), "the X-WIB-Caller sent was")
fails("a line with an empty peer", log_of(obj("output", True, False, peer=""), obj("output", False, True)),
      "empty peer")
fails("no change made", log_of(), "no /toggle changed a guard", changes=[])
check("matched counts the lines that name their change",
      gt.matched(gt.parse(log_of(obj("output", True, False, peer=""), obj("output", False, True))), CHANGES, CALLER) == 1)

print("== the live check runs on the private cluster under verify/run-e2e.sh ==")
live = LIVE.read_text(encoding="utf-8")
check("test_guard_toggle_log_live.py is an e2e test", "\n# SUITE: e2e\n" in live)
check("it reads PRIVATE_CONTEXT", 'os.environ.get("PRIVATE_CONTEXT"' in live)
check("it judges with guard_toggle_log and prints its record line",
      "gt.judge(" in live and "gt.record_line(" in live)
check("verify/run-e2e.sh requires PRIVATE_CONTEXT",
      'missing+=("PRIVATE_CONTEXT is not set' in (HERE / "run-e2e.sh").read_text(encoding="utf-8"))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\ndecisions.md records the guard_toggle read on watch-it-burn-private, and the pinned build writes it.")
