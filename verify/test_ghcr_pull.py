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
finally:
    urllib.request.urlopen = real

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All ghcr_pull step checks passed.")
