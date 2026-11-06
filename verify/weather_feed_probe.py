# ABOUTME: One request to the weather feed, timed, with its status and body kept on an error (#982), and the line
# ABOUTME: a failed request prints. Shared by test_weather_feed_e2e.py and its offline check; importing it starts nothing.
"""Ask the weather feed (gitops/ai-layer/weather_feed.py) one question and keep what it answered.

Run 17801 saw the e2e test die on an uncaught `HTTPError: HTTP Error 502` for Salt Lake City. The feed answers
502 only when its own call to Open-Meteo fails, and it says why in the JSON body's `error` field; urlopen raises
before anyone reads that body. `request` catches the error and returns the status, the body and how long the
request took, so the test can print the cause and fail with it.

No retry: one request is made, and its answer, good or bad, is what the caller gets.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import NamedTuple, Union

Body = Union[dict, list, str]


class Reply(NamedTuple):
    """What one request got back.

    status: the HTTP status, or None when no HTTP answer came (refused, reset, timed out).
    body: the parsed JSON body, or the raw text when it is not JSON (for status None, the error urllib raised).
    elapsed: seconds from sending the request to having the whole answer, or to the failure.
    """
    status: int | None
    body: Body
    elapsed: float


def _parse(raw: bytes) -> Body:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def request(url: str, timeout: float = 20) -> Reply:
    """GET url once and return its status, body and elapsed seconds. Never raises for an HTTP or network error."""
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return Reply(None, f"{type(e).__name__}: {getattr(e, 'reason', e)}", time.monotonic() - start)
    return Reply(status, _parse(raw), time.monotonic() - start)


def error_field(body: Body, limit: int = 300) -> str:
    """The feed's stated reason: the body's `error` field, else the body itself, cut to `limit` characters."""
    if isinstance(body, dict) and "error" in body:
        text = str(body["error"])
    elif isinstance(body, str):
        text = body.strip() or "<empty body>"
    else:
        text = f"<no error field in {json.dumps(body)}>"
    return text if len(text) <= limit else text[:limit] + "..."


def failure_line(what: str, reply: Reply, expected: int = 200) -> str:
    """The line a request that did not get `expected` prints: its status, the feed's error and how long it took."""
    status = "no HTTP answer" if reply.status is None else f"HTTP {reply.status}"
    return (f"{what}: {status} (expected {expected}) after {reply.elapsed:.2f} s; "
            f"error: {error_field(reply.body)}")
