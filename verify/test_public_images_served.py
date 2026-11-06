# ABOUTME: Reads each of Challenge 2's public images (#773) from public.ecr.aws anonymously: every tag still serves the
# ABOUTME: digest deploy_app pins, and each image runs on linux/amd64, the only architecture these nodes have.
# SUITE: e2e (needs the network: public.ecr.aws is asked for each manifest)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. deploy_app turns "deploy nginx" into PUBLIC_IMAGES' reference, pinned by digest, and a node pulls it with no
# credential. A digest the registry stopped serving would leave the room's deployment in ImagePullBackOff while the
# page said it landed, and an image with no linux/amd64 build would never start (decisions.md, 2026-10-25, "No arm64
# image"). The tag is read as well: when it has moved on, the pin still pulls and this prints that it moved, so a
# refresh of the pin is a choice someone makes. verify/test_public_images.py holds the offline half.
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
import time
import types
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_served", REPO / "gitops/ai-layer/workshop-mcp-server.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def token() -> str:
    return json.loads(opened(urllib.request.Request(f"https://{REGISTRY}/token/")))["token"]


def paced() -> None:
    """ECR Public answers an anonymous client about once a second and 429s the rest, so each request waits its turn."""
    time.sleep(1.2)


# The once-a-second budget is per source address, and this host runs other runs' suites from the same address, so a
# request paced here can still meet a 429 spent by someone else (run 16863: busybox's first manifest, then green on a
# rerun). A 429 says wait, not no: it is retried after Retry-After (at most 30 s), or 2, 4, 8 and 16 seconds,
# five tries in all.
#
# No answer at all is not a no either (#976). Run 17813's tier went red on one TLS handshake to the token endpoint that
# timed out, and passed on its own a minute later: the registry had said nothing about any image. A timeout or a
# dropped connection, on the connect, the handshake or the read, is tried again 5 s later, three tries in all. When
# every try gets no answer, opened() raises Unreachable, which names the registry, and the test fails on that alone,
# so an unreachable registry never reads as an image that is not served.
# Any other error (an HTTP status that is not 429, a certificate the host cannot verify, a name that does not
# resolve), or a fifth 429, still fails at once.
REGISTRY = "public.ecr.aws"
RETRIES_ON_429 = 4
RETRIES_ON_NO_ANSWER = 2
NO_ANSWER_WAIT = 5


class Unreachable(Exception):
    """Every try at one request got no answer: a verdict on this host's path to the registry, not on an image."""


def no_answer(e: BaseException) -> bool:
    """A timeout or a dropped connection: raised bare from the read, or as a URLError's reason from the open."""
    if isinstance(e, urllib.error.HTTPError):
        return False
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    return isinstance(reason, (TimeoutError, ConnectionError))


def opened(req: urllib.request.Request) -> bytes:
    limited = silent = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or limited == RETRIES_ON_429:
                raise
            limited += 1
            wait = e.headers.get("Retry-After", "") if e.headers else ""
            time.sleep(min(int(wait), 30) if wait.isdigit() else 2 ** limited)
        except OSError as e:
            if not no_answer(e):
                raise
            silent += 1
            if silent > RETRIES_ON_NO_ANSWER:
                raise Unreachable(f"{REGISTRY} gave no answer to {req.full_url} on {silent} tries, {NO_ANSWER_WAIT} s "
                                  f"apart; the last: {type(e).__name__}: {e}") from e
            time.sleep(NO_ANSWER_WAIT)


def fetch(tok: str, repo: str, ref: str, accept: str = ACCEPT) -> tuple[str, dict]:
    paced()
    req = urllib.request.Request(f"https://public.ecr.aws/v2/{repo}/manifests/{ref}",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": accept})
    # The digest is the sha256 of the bytes served, computed here: ECR Public sends no Docker-Content-Digest on a GET.
    raw = opened(req)
    return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(raw)


def blob(tok: str, repo: str, digest: str) -> dict:
    paced()
    req = urllib.request.Request(f"https://public.ecr.aws/v2/{repo}/blobs/{digest}",
                                 headers={"Authorization": f"Bearer {tok}"})
    return json.loads(opened(req))


def unreachable(e: Unreachable) -> None:
    """The registry gave no answer: this says nothing of the pins still unread, so it fails as that, by name."""
    print(f"\nFAILED: {REGISTRY} is unreachable from this host, and the images not yet read have no verdict: {e}")
    for f in failures:
        print(f"  - failed before it stopped answering: {f}")
    sys.exit(1)


try:
    TOKEN = token()
except Unreachable as e:
    unreachable(e)
except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
    print(f"FAILED: {REGISTRY} gave no anonymous token: {type(e).__name__}: {e}")
    sys.exit(1)

print(f"== every public image deploy_app pins is served by {REGISTRY}, with no credential ==")
try:
    for name, ref in m.PUBLIC_IMAGES.items():
        path, _, digest = ref.partition("@")
        repo, _, tag = path.removeprefix(f"{REGISTRY}/").rpartition(":")
        try:
            served, doc = fetch(TOKEN, repo, digest)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            check(f"{name}: {digest[:19]}... answers an anonymous pull", False, f"{type(e).__name__}: {e}")
            continue
        check(f"{name}: {digest[:19]}... answers an anonymous pull", served == digest, served)
        if "manifests" in doc:
            amd64 = [x for x in doc["manifests"] if x.get("platform", {}).get("os") == "linux"
                     and x.get("platform", {}).get("architecture") == "amd64"]
            check(f"{name}: the index has a linux/amd64 image", bool(amd64))
        else:
            cfg = blob(TOKEN, repo, doc["config"]["digest"])
            check(f"{name}: the image is linux/amd64", (cfg.get("os"), cfg.get("architecture")) == ("linux", "amd64"),
                  f"{cfg.get('os')}/{cfg.get('architecture')}")
        try:
            now, _ = fetch(TOKEN, repo, tag)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            now = f"{type(e).__name__}: {e}"
        moved = "" if now == digest else " (moved on from the pin)"
        print(f"  INFO  {name}: :{tag} now serves {now[:19]}...{moved}")
except Unreachable as e:
    unreachable(e)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Every public image deploy_app pins is served, on linux/amd64.")
