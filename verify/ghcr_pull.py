# ABOUTME: Asks ghcr.io, with no credential, which digest a reference serves: what a node with no pull secret gets.
# ABOUTME: Shared by the tools-tier checks that lab-platform's mirror/ copies, promo/ villains and C6's Joker are public.
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))

# A dropped connection is asked again, up to TRIES times in all, BACKOFF seconds times the try between: on 2026-11-07
# ghcr.io closed one manifest HEAD with no response (http.client.RemoteDisconnected) and the tools tier went red on it
# (#1047). An HTTP answer, a 401 or a 404, is ghcr.io's reply and is never asked again.
TRIES = 3
BACKOFF = 2.0
_sleep = time.sleep
DROPPED = (http.client.HTTPException, ConnectionError, TimeoutError)


def _open(req):
    """urlopen(req), asked again while the connection drops before an answer; the last drop is raised."""
    for attempt in range(1, TRIES + 1):
        try:
            return urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, *DROPPED) as e:
            if attempt == TRIES:
                e.add_note(f"after {TRIES} tries")
                raise
            _sleep(BACKOFF * attempt)
    raise AssertionError("unreachable")


def served_digest(reference: str) -> tuple[str | None, str]:
    """The digest ghcr.io serves for <host>/<repo>:<tag> to a client with no credential, or None and why not."""
    host, _, rest = reference.partition("/")
    repo, tag = rest.rsplit(":", 1)
    # Each step names itself when it fails (#678): ghcr.io refuses the anonymous token itself, 401, for a private
    # or missing package, while a public one gets a token and only then can 404 on a tag it does not have.
    step = "token"
    try:
        with _open(f"https://{host}/token?scope=repository:{repo}:pull") as r:
            token = json.load(r)["token"]
        step = "manifest"
        req = urllib.request.Request(f"https://{host}/v2/{repo}/manifests/{tag}", method="HEAD",
                                     headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
        with _open(req) as r:
            return r.headers.get("Docker-Content-Digest"), ""
    except urllib.error.HTTPError as e:
        if step == "token" and e.code == 401:
            return None, f"token refused, HTTP {e.code} {e.reason}: the package is private or does not exist"
        return None, f"{step}: HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, *DROPPED, KeyError, ValueError) as e:
        notes = "".join(f" ({n})" for n in getattr(e, "__notes__", []))
        return None, f"{step}: {type(e).__name__}: {e}{notes}"
