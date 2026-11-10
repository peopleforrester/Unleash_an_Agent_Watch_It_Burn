# ABOUTME: Asks ghcr.io, with no credential, which digest a reference serves: what a node with no pull secret gets.
# ABOUTME: Shared by the tools-tier checks that lab-platform's mirror/ copies, promo/ villains and C6's Joker are public.
from __future__ import annotations

import http.client
import io
import json
import time
import urllib.error
import urllib.request

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))

# A dropped connection is asked again, up to TRIES times in all, BACKOFF seconds times the try between: on 2026-11-07
# ghcr.io closed one manifest HEAD with no response (http.client.RemoteDisconnected) and the tools tier went red on it
# (#1047). An HTTP answer, a 401 or a 404, is ghcr.io's reply and is never asked again. Later the same day (CI run
# 42405149040) two TLS handshakes to ghcr.io timed out in test_joker_web_busybox.py and test_image_version_tags.py,
# which opened it with urlopen of their own; they and test_c6_joker_public.py now read it through open_url or read_url.
# A busy answer is asked again the same way (#1192): on 2026-11-08 the blob redirect of a ttyd layer in
# test_image_version_tags.py got "HTTP Error 503: The server is busy." in run 18643's tools tier. BUSY is the set of
# codes that say the server could not answer now (429, 502, 503, 504), not what the package is; every other HTTP
# answer, a 307, 401 or 404 included, is still raised at once.
TRIES = 3
BACKOFF = 2.0
_sleep = time.sleep
DROPPED = (http.client.HTTPException, ConnectionError, TimeoutError)
BUSY = frozenset({429, 502, 503, 504})


def _retried(call):
    """call(), asked again while the connection drops before an answer or the server answers busy (BUSY); the last
    drop or busy answer is raised, any other HTTP answer at once."""
    for attempt in range(1, TRIES + 1):
        try:
            return call()
        except urllib.error.HTTPError as e:
            if e.code not in BUSY:
                raise
            if attempt == TRIES:
                e.add_note(f"after {TRIES} tries")
                raise
            _sleep(BACKOFF * attempt)
        except (urllib.error.URLError, *DROPPED) as e:
            if attempt == TRIES:
                e.add_note(f"after {TRIES} tries")
                raise
            _sleep(BACKOFF * attempt)
    raise AssertionError("unreachable")


def _opener_of(opener):
    # urllib.request.urlopen is looked up at each call, so a test's stub of it is the one asked.
    return opener.open if opener is not None else urllib.request.urlopen


def open_url(req, timeout: float = 30, opener=None):
    """The response to req, from opener (urlopen by default), asked again while the connection drops before an
    answer. Only the open is retried: a caller that streams the body owns a drop part way through it."""
    return _retried(lambda: _opener_of(opener)(req, timeout=timeout))


# A blob streamed whole is resumed, not read again from the start (#1314). On Tanjiro's runner the stream of a
# web-terminal layer in test_image_version_tags.py ended early with no error in CI runs 42863038669 and 42866956234,
# after 887 s and 1061 s: http.client hands back an empty read when a connection closes before Content-Length, so
# tarfile stopped on "unexpected end of data". RESUMES is how many times one blob is asked again from the first byte
# not yet read.
RESUMES = 5


class BlobBody(io.RawIOBase):
    """The body of a blob whose size the manifest gives, read start to end. When the connection ends or drops before
    size bytes, the rest is asked for with a Range header from the first byte not yet read, up to RESUMES times; an
    answer that is not a 206 from that byte is refused, never spliced in."""

    def __init__(self, req, size: int, timeout: float = 30, opener=None) -> None:
        super().__init__()
        self.req = req if isinstance(req, urllib.request.Request) else urllib.request.Request(req)
        self.size, self.timeout, self.opener = size, timeout, opener
        self.pos = 0
        self.resumes = 0
        self.resp = open_url(self.req, timeout, opener)

    def readable(self) -> bool:
        return True

    def _resume(self, why: str) -> None:
        url = self.req.full_url
        if self.resumes == RESUMES:
            raise ConnectionError(f"{url}: the body ended at byte {self.pos} of {self.size} ({why}), "
                                  f"and {RESUMES} resumes did not finish it")
        self.resumes += 1
        self.resp.close()
        # The request's own headers only: header_items() also holds the Host urllib added on the first open, and
        # carried across ghcr.io's redirect it sends the blob host's CDN Host: ghcr.io, which answers 421.
        headers = {**self.req.headers, "Range": f"bytes={self.pos}-"}
        self.resp = open_url(urllib.request.Request(url, headers=headers), self.timeout, self.opener)
        status = getattr(self.resp, "status", None)
        got = (self.resp.headers.get("Content-Range") or "") if self.resp.headers else ""
        if status != 206 or not got.startswith(f"bytes {self.pos}-"):
            self.resp.close()
            raise ConnectionError(f"{url}: asked for the rest from byte {self.pos} of {self.size} after {why}, "
                                  f"the answer was HTTP {status} with Content-Range {got!r}, not a 206 from that byte")

    def readinto(self, b) -> int:
        while self.pos < self.size:
            try:
                n = self.resp.readinto(b)
                why = "the connection closed"
            except DROPPED as e:
                n, why = 0, f"{type(e).__name__}: {e}"
            if n:
                self.pos += n
                return n
            self._resume(why)
        return 0

    def close(self) -> None:
        # No resp when the first open raised; close() still runs, from IOBase's __del__.
        if not self.closed and getattr(self, "resp", None) is not None:
            self.resp.close()
        super().close()


def open_blob(req, size: int, timeout: float = 30, opener=None) -> BlobBody:
    """The body of the blob at req, size bytes long, resumed where it ends early (BlobBody)."""
    return BlobBody(req, size, timeout, opener)


def read_url(req, timeout: float = 30, opener=None) -> bytes:
    """The whole body of the response to req, asked again from the start while the connection drops before the last
    byte."""
    def once() -> bytes:
        with _opener_of(opener)(req, timeout=timeout) as r:
            return r.read()
    return _retried(once)


def served_digest(reference: str) -> tuple[str | None, str]:
    """The digest ghcr.io serves for <host>/<repo>:<tag> to a client with no credential, or None and why not."""
    host, _, rest = reference.partition("/")
    repo, tag = rest.rsplit(":", 1)
    # Each step names itself when it fails (#678): ghcr.io refuses the anonymous token itself, 401, for a private
    # or missing package, while a public one gets a token and only then can 404 on a tag it does not have.
    step = "token"
    try:
        with open_url(f"https://{host}/token?scope=repository:{repo}:pull") as r:
            token = json.load(r)["token"]
        step = "manifest"
        req = urllib.request.Request(f"https://{host}/v2/{repo}/manifests/{tag}", method="HEAD",
                                     headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
        with open_url(req) as r:
            return r.headers.get("Docker-Content-Digest"), ""
    except urllib.error.HTTPError as e:
        if step == "token" and e.code == 401:
            return None, f"token refused, HTTP {e.code} {e.reason}: the package is private or does not exist"
        notes = "".join(f" ({n})" for n in getattr(e, "__notes__", []))
        return None, f"{step}: HTTP {e.code} {e.reason}{notes}"
    except (urllib.error.URLError, *DROPPED, KeyError, ValueError) as e:
        notes = "".join(f" ({n})" for n in getattr(e, "__notes__", []))
        return None, f"{step}: {type(e).__name__}: {e}{notes}"
