# ABOUTME: Offline check of test_public_images_served.py's 429 handling: its opened() helper is lifted out of the file
# ABOUTME: and run against a stubbed urlopen and sleep, so a rate-limited pull is retried and any other error is not.
"""The tools-tier test reads public.ecr.aws anonymously, whose budget is about one request a second per source
address. This host runs other runs' suites from the same address, so run 16863 met a 429 on busybox's first manifest
and went green on a rerun. The fix retries a 429 only, a bounded number of times. This holds that without the network:
the helper is taken from the file by name, so what runs here is the code the tier test runs.
"""
from __future__ import annotations

import ast
import email.message
import pathlib
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC_PATH = REPO / "verify/test_public_images_served.py"
SRC = SRC_PATH.read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# The two names this lifts out of the file are checked first, so a rename reads as that and not as a broken check.
tree = ast.parse(SRC)
nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
nodes.update({t.id: n for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)})
missing = [name for name in ("RETRIES_ON_429", "opened") if name not in nodes]
if missing:
    print(f"FAILED: {SRC_PATH.relative_to(REPO)} has no top-level {', '.join(missing)} to lift out")
    sys.exit(1)
check("the tier test's fetch and blob both read through opened()",
      "raw = opened(req)" in SRC and "return json.loads(opened(req))" in SRC
      and "urllib.request.urlopen(req" in ast.get_source_segment(SRC, nodes["opened"])
      and SRC.count("urllib.request.urlopen(req") == 1)


class _Resp:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self.body


def _err(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://public.ecr.aws/v2/x/manifests/y", code, "stub", h, None)


def run(script: list) -> tuple[object, list[float], int]:
    """Run opened() against a urlopen that answers each item of script in turn: bytes, or an HTTPError to raise."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def urlopen(req, timeout=None):
        item = script[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    fake_urllib = type("U", (), {})()
    fake_urllib.request = type("R", (), {"urlopen": staticmethod(urlopen), "Request": urllib.request.Request})
    fake_urllib.error = urllib.error
    ns = {"urllib": fake_urllib, "time": type("T", (), {"sleep": staticmethod(sleeps.append)})}
    for name in ("RETRIES_ON_429", "opened"):
        exec(compile(ast.Module(body=[nodes[name]], type_ignores=[]), str(SRC_PATH), "exec"), ns)
    try:
        out: object = ns["opened"](urllib.request.Request("https://public.ecr.aws/v2/x/manifests/y"))
    except urllib.error.HTTPError as e:
        out = e
    return out, sleeps, calls["n"]


print("== a rate-limited anonymous pull is retried; nothing else is (#844, run 16863) ==")
out, sleeps, n = run([_err(429), _err(429), b"manifest"])
check("two 429s then an answer returns the answer", out == b"manifest" and n == 3, f"{out!r} after {n} calls")
check("and waits 2 s then 4 s between them, with no Retry-After", sleeps == [2, 4], str(sleeps))

out, sleeps, n = run([_err(429, "3"), b"manifest"])
check("a Retry-After is honoured", out == b"manifest" and sleeps == [3], str(sleeps))
out, sleeps, n = run([_err(429, "3600"), b"manifest"])
check("and capped at 30 s, so a long one cannot stall the tier", sleeps == [30], str(sleeps))

out, sleeps, n = run([_err(429)] * 5 + [b"never read"])
check("five 429s in a row still fail, after four waits", isinstance(out, urllib.error.HTTPError) and out.code == 429
      and n == 5 and sleeps == [2, 4, 8, 16], f"{out!r}, {n} calls, {sleeps}")

out, sleeps, n = run([_err(404), b"never read"])
check("a 404 fails at once, with no retry and no wait",
      isinstance(out, urllib.error.HTTPError) and out.code == 404 and n == 1 and sleeps == [], f"{n} calls, {sleeps}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("A 429 from public.ecr.aws is retried, and only a 429.")
