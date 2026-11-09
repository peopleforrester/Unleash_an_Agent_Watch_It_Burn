# ABOUTME: Holds test_gateway_api_crds_upstream.py's fetch() offline (#1248): a transient network error is retried after
# ABOUTME: each wait in artifact_cache.BACKOFF, a 404 or other error fails at once, and every failure names its error.
"""Staging b344e331's heavy gate failed the Gateway API upstream check with inputs that passed before and after it
(#1248). Its fetch then caught only URLError and TimeoutError, once, so one 5xx, 429 or reset from github.com failed
the gate, and a reset mid-body ended in a traceback. This drives fetch() with a stub reader and a stub sleep, so no
network is read and no time passes, and checks each case: every attempt, every retry line, every wait."""
from __future__ import annotations

import contextlib
import http.client
import io
import pathlib
import sys
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
import test_gateway_api_crds_upstream as up  # noqa: E402

URL = "https://example.invalid/standard-install.yaml"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, f"status {code}", None, None)


def drive(outcomes: list) -> tuple[bytes | None, list[str], list[float], str, list[str]]:
    """Run fetch() with a reader that gives each outcome in turn (bytes are returned, an exception raised)."""
    calls: list[str] = []
    waits: list[float] = []

    def read(url: str) -> bytes:
        calls.append(url)
        o = outcomes[len(calls) - 1]
        if isinstance(o, BaseException):
            raise o
        return o

    up.failures.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        got = up.fetch(URL, read=read, sleep=waits.append)
    return got, calls, waits, out.getvalue(), list(up.failures)


attempts = len(artifact_cache.BACKOFF) + 1
check("the backoff is the artifact cache's, three waits", up.fetch.__kwdefaults__["backoff"] == artifact_cache.BACKOFF
      and len(artifact_cache.BACKOFF) == 3, f"{up.fetch.__kwdefaults__['backoff']} vs {artifact_cache.BACKOFF}")

print("== a first good read is returned, no retry ==")
got, calls, waits, out, fails = drive([b"body"])
check("the bytes are returned", got == b"body", repr(got))
check("one read, no wait, no RETRY line, no failure", len(calls) == 1 and not waits and "RETRY" not in out and not fails,
      f"calls {len(calls)}, waits {waits}, failures {fails}\n{out}")

print("== each transient error is retried, then the read succeeds ==")
transients = [http_error(503), http_error(429), http_error(408), TimeoutError("timed out"),
              ConnectionResetError(104, "Connection reset by peer"), urllib.error.URLError("[Errno -3] name lookup"),
              http.client.IncompleteRead(b"part", 10), http.client.RemoteDisconnected("closed")]
for e in transients:
    got, calls, waits, out, fails = drive([e, b"body"])
    name = type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")
    check(f"{name} then a good read returns the bytes after one wait of {artifact_cache.BACKOFF[0]}s",
          got == b"body" and len(calls) == 2 and waits == [artifact_cache.BACKOFF[0]] and not fails,
          f"got {got!r}, calls {len(calls)}, waits {waits}, failures {fails}")
    check(f"{name}: the retry line names the URL, the error and attempt 1 of {attempts}",
          f"RETRY {URL}: {type(e).__name__}" in out and f"(attempt 1 of {attempts}; again in" in out, out)

print("== a transient error on every attempt fails after every wait, naming the last error ==")
errs = [http_error(502), http_error(503), ConnectionResetError(104, "reset"), http_error(504)]
got, calls, waits, out, fails = drive(errs)
check(f"{attempts} reads, waits {list(artifact_cache.BACKOFF)}, None returned",
      got is None and len(calls) == attempts and waits == list(artifact_cache.BACKOFF),
      f"got {got!r}, calls {len(calls)}, waits {waits}")
check("one FAIL check, the URL is fetched", fails == [f"{URL} is fetched"], str(fails))
check(f"the failure names the last error and attempt {attempts} of {attempts}",
      "HTTPError: HTTP Error 504" in out and f"(attempt {attempts} of {attempts})" in out, out)
check(f"{attempts - 1} RETRY lines", out.count("  RETRY ") == attempts - 1, out)

print("== a 404 and a non-network error fail on the first attempt ==")
for e in (http_error(404), http_error(403), ValueError("unknown url type")):
    got, calls, waits, out, fails = drive([e, b"body"])
    name = type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")
    check(f"{name}: one read, no wait, None and one FAIL naming {type(e).__name__} at attempt 1",
          got is None and len(calls) == 1 and not waits and fails == [f"{URL} is fetched"]
          and f"{type(e).__name__}: " in out and f"(attempt 1 of {attempts})" in out and "RETRY" not in out,
          f"got {got!r}, calls {len(calls)}, waits {waits}, failures {fails}\n{out}")

up.failures.clear()
if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: the Gateway API upstream check retries a fetch the network broke and fails at once on any other error")
