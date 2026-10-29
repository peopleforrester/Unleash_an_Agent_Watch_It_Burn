# ABOUTME: Asks ghcr.io, with no credential, which digest a reference serves: what a node with no pull secret gets.
# ABOUTME: Shared by the tools-tier checks that lab-platform's mirror/ copies and promo/ villains are public.
from __future__ import annotations

import json
import urllib.error
import urllib.request

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))


def served_digest(reference: str) -> tuple[str | None, str]:
    """The digest ghcr.io serves for <host>/<repo>:<tag> to a client with no credential, or None and why not."""
    host, _, rest = reference.partition("/")
    repo, tag = rest.rsplit(":", 1)
    # Each step names itself when it fails (#678): ghcr.io refuses the anonymous token itself, 401, for a private
    # or missing package, while a public one gets a token and only then can 404 on a tag it does not have.
    step = "token"
    try:
        with urllib.request.urlopen(f"https://{host}/token?scope=repository:{repo}:pull", timeout=30) as r:
            token = json.load(r)["token"]
        step = "manifest"
        req = urllib.request.Request(f"https://{host}/v2/{repo}/manifests/{tag}", method="HEAD",
                                     headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.headers.get("Docker-Content-Digest"), ""
    except urllib.error.HTTPError as e:
        if step == "token" and e.code == 401:
            return None, f"token refused, HTTP {e.code} {e.reason}: the package is private or does not exist"
        return None, f"{step}: HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        return None, f"{step}: {type(e).__name__}: {e}"
