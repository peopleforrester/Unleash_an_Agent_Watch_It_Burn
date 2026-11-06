# ABOUTME: One GET against the weather feed that returns its status, JSON body and elapsed time, error statuses
# ABOUTME: included, so test_weather_feed_e2e.py prints why the feed failed instead of an HTTPError traceback (#964).
"""The feed answers 502 when its own call to Open-Meteo fails, and puts that failure in the body's `error` field
(gitops/ai-layer/weather_feed.py). Run 17801 on #882 saw a 502 that the e2e test never explained, because urlopen
raised HTTPError and the body was never read. This reads it.

There is no retry here. One failed request is a failed test, and what it prints names the cause.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Answer:
    status: int
    body: dict
    seconds: float

    def describe(self) -> str:
        """The status, the feed's error text and the time taken, on one line."""
        return f"HTTP {self.status} after {self.seconds:.1f}s, error: {self.body.get('error', '<no error field>')!r}"


def _parse(raw: bytes) -> dict:
    try:
        body = json.loads(raw)
    except ValueError:
        return {"error": f"<body is not JSON: {raw[:300]!r}>"}
    return body if isinstance(body, dict) else {"error": f"<body is not a JSON object: {raw[:300]!r}>"}


def get(url: str, timeout: float = 20) -> Answer:
    """GET url and return what the feed answered. A connection that fails outright still raises: no answer."""
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return Answer(r.status, _parse(r.read()), time.monotonic() - start)
    except urllib.error.HTTPError as e:
        with e:
            return Answer(e.code, _parse(e.read()), time.monotonic() - start)
