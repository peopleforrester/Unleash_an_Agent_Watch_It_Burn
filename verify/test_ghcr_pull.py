# ABOUTME: verify/ghcr_pull.py says which step of an anonymous ghcr.io pull failed (#678): a refused token is a
# ABOUTME: private or missing package, told apart from a manifest that will not serve. Offline: urlopen is a stub.
"""Offline. The real anonymous pulls are test_promo_villains_public.py and test_mirror_copies_public.py (tools tier).

#678 found every promo/ villain failing with a bare "HTTP 401 Unauthorized", and the issue could not tell whether the
packages were private or ghcr.io's anonymous token flow had broken. ghcr.io answers the token request itself with 401
for a private or missing package, and gives a public one a token, so the step that failed is the answer.
"""
from __future__ import annotations

import http.client
import io
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ghcr_pull  # noqa: E402

REF = "ghcr.io/peopleforrester/lab-platform/promo/promo-mascot:v1"
DIGEST = "sha256:" + "ab" * 32

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


class Reply(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}


def stub(token_code: int, manifest_code: int):
    """urlopen that answers the token request, then the manifest HEAD, with the given status codes."""
    seen: list[str] = []

    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        seen.append(url)
        code = token_code if "/token?" in url else manifest_code
        if code != 200:
            raise urllib.error.HTTPError(url, code, {401: "Unauthorized", 404: "Not Found"}[code], {}, None)
        if "/token?" in url:
            return Reply(json.dumps({"token": "t"}).encode())
        return Reply(b"", {"Docker-Content-Digest": DIGEST})

    return urlopen, seen


real = urllib.request.urlopen
try:
    print("== a public package with the tag serves its digest ==")
    urllib.request.urlopen, seen = stub(200, 200)
    got = ghcr_pull.served_digest(REF)
    check("the digest comes back with no reason", got == (DIGEST, ""), repr(got))
    check("it asks for the token, then the manifest",
          seen == ["https://ghcr.io/token?scope=repository:peopleforrester/lab-platform/promo/promo-mascot:pull",
                   "https://ghcr.io/v2/peopleforrester/lab-platform/promo/promo-mascot/manifests/v1"], repr(seen))

    print("== a refused token names the package as private or missing ==")
    urllib.request.urlopen, seen = stub(401, 200)
    digest, why = ghcr_pull.served_digest(REF)
    check("no digest", digest is None, repr(digest))
    check("the reason is the refused token", why.startswith("token refused, HTTP 401 Unauthorized"), why)
    check("the reason says private or does not exist", "private or does not exist" in why, why)
    check("the manifest is never asked for", len(seen) == 1, repr(seen))

    print("== a manifest failure after a token is the manifest's, not the package's visibility ==")
    urllib.request.urlopen, _ = stub(200, 404)
    digest, why = ghcr_pull.served_digest(REF)
    check("no digest", digest is None, repr(digest))
    check("the reason names the manifest step", why == "manifest: HTTP 404 Not Found", why)
    check("it does not blame visibility", "private" not in why, why)

    print("== a dropped connection is asked again, an HTTP answer never (#1047) ==")
    naps: list[float] = []
    ghcr_pull._sleep = naps.append

    def dropping(drops: int):
        """stub(200, 200), but the first <drops> manifest HEADs lose the connection before any answer."""
        answer, seen = stub(200, 200)
        left = [drops]

        def urlopen(req, timeout=None):
            url = req if isinstance(req, str) else req.full_url
            if "/manifests/" in url and left[0] > 0:
                left[0] -= 1
                seen.append(url)
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            return answer(req, timeout)

        return urlopen, seen

    urllib.request.urlopen, seen = dropping(1)
    got = ghcr_pull.served_digest(REF)
    check("one dropped HEAD, then the digest", got == (DIGEST, ""), repr(got))
    check("the HEAD was asked twice, after one nap", sum("/manifests/" in u for u in seen) == 2 and len(naps) == 1,
          repr((seen, naps)))
    naps.clear()
    urllib.request.urlopen, seen = dropping(ghcr_pull.TRIES)
    digest, why = ghcr_pull.served_digest(REF)
    check("a HEAD that drops every try is no digest", digest is None, repr(digest))
    check("its reason names the manifest step, the drop and the tries",
          why.startswith("manifest: RemoteDisconnected: Remote end closed connection")
          and f"after {ghcr_pull.TRIES} tries" in why, why)
    check(f"asked {ghcr_pull.TRIES} times in all", sum("/manifests/" in u for u in seen) == ghcr_pull.TRIES, repr(seen))
    naps.clear()
    urllib.request.urlopen, seen = stub(200, 404)
    digest, why = ghcr_pull.served_digest(REF)
    check("a 404 is asked once, with no nap", why == "manifest: HTTP 404 Not Found"
          and sum("/manifests/" in u for u in seen) == 1 and not naps, repr((why, seen, naps)))

    print("== open_url and read_url, the reads the blob-pulling tier tests make, ask a dropped connection again ==")
    naps.clear()
    handshake = urllib.error.URLError(TimeoutError("_ssl.c:1012: The handshake operation timed out"))

    class Body(io.BytesIO):
        """A response whose read drops part way through, <drops> times, before it serves the whole body."""
        left = [0]

        def read(self, *a):
            if Body.left[0] > 0:
                Body.left[0] -= 1
                raise http.client.IncompleteRead(b"par", 3)
            return super().read(*a)

    def failing(errors: list, body: bytes = b"blob"):
        """urlopen that raises each of errors in turn, then answers body."""
        seen: list = []

        def urlopen(req, timeout=None):
            seen.append(timeout)
            if errors:
                raise errors.pop(0)
            return Body(body)

        return urlopen, seen

    urllib.request.urlopen, seen = failing([handshake])
    got = ghcr_pull.read_url("https://ghcr.io/token?scope=repository:x:pull", timeout=7)
    check("a timed-out TLS handshake (CI run 42405149040) is asked again and the body read",
          got == b"blob" and len(seen) == 2 and len(naps) == 1, repr((got, seen, naps)))
    check("the caller's timeout is passed on each try", seen == [7, 7], repr(seen))
    naps.clear()
    urllib.request.urlopen, seen = failing([])
    Body.left[0] = 1
    got = ghcr_pull.read_url("https://ghcr.io/v2/x/blobs/sha256:00")
    check("a body that drops part way is read again from the start", got == b"blob" and len(seen) == 2,
          repr((got, seen)))
    naps.clear()
    urllib.request.urlopen, seen = failing([handshake] * ghcr_pull.TRIES)
    try:
        ghcr_pull.read_url("https://ghcr.io/v2/x/blobs/sha256:00")
        check("a handshake that times out every try is raised", False, "it returned")
    except urllib.error.URLError as e:
        check("a handshake that times out every try is raised, naming the tries",
              f"after {ghcr_pull.TRIES} tries" in getattr(e, "__notes__", []) and len(seen) == ghcr_pull.TRIES,
              repr((getattr(e, "__notes__", None), seen)))
    naps.clear()
    urllib.request.urlopen, seen = failing([handshake])
    with ghcr_pull.open_url("https://ghcr.io/v2/x/blobs/sha256:00", timeout=120) as r:
        got = r.read()
    check("open_url asks a timed-out handshake again and hands back the open response",
          got == b"blob" and seen == [120, 120], repr((got, seen)))

    class Opener:
        """A no-redirect opener, as the Joker tests build: a blob's 307 is an HTTPError the caller follows."""
        def __init__(self) -> None:
            self.asked = 0

        def open(self, req, timeout=None):
            self.asked += 1
            raise urllib.error.HTTPError("https://ghcr.io/v2/x/blobs/sha256:00", 307, "Temporary Redirect",
                                         {"Location": "https://pkg-containers.githubusercontent.com/x"}, None)

    naps.clear()
    opener = Opener()
    urllib.request.urlopen, seen = failing([])
    try:
        ghcr_pull.read_url("https://ghcr.io/v2/x/blobs/sha256:00", opener=opener)
        check("the opener's redirect reaches the caller", False, "it returned")
    except urllib.error.HTTPError as e:
        check("the opener given is the one asked, and its redirect reaches the caller at once",
              e.code == 307 and opener.asked == 1 and not seen and not naps, repr((e.code, opener.asked, seen, naps)))
finally:
    urllib.request.urlopen = real

print("== the tier tests that pull blobs from ghcr.io read it through these helpers (CI run 42405149040) ==")
HERE = pathlib.Path(__file__).resolve().parent
for name in ("test_joker_web_busybox.py", "test_image_version_tags.py", "test_c6_joker_public.py"):
    src = (HERE / name).read_text(encoding="utf-8")
    direct = [line.strip() for line in src.splitlines()
              if "_opener.open(" in line or 'urlopen(e.headers["Location"]' in line or "urlopen(req" in line
              or 'urlopen(f"https://ghcr.io' in line or "urlopen(url, timeout=30)" in line]
    check(f"{name} imports read_url or open_url from ghcr_pull",
          bool(re.search(r"^from ghcr_pull import .*\b(read_url|open_url)\b", src, re.M)))
    check(f"{name} opens no ghcr.io URL with urlopen of its own", not direct, repr(direct))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All ghcr_pull step checks passed.")
