# ABOUTME: Reads Challenge 2's landing-page image (#773, #992) and the official images deploy_app moves off Docker Hub
# ABOUTME: from public.ecr.aws anonymously: each is served there, on linux/amd64, the only architecture these nodes have.
# SUITE: e2e (needs the network: public.ecr.aws is asked for each manifest)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. deploy_app serves an app the room names with no image ("deploy Tron") on LANDING_IMAGE, pinned by digest, and a
# node pulls it with no credential. A digest the registry stopped serving would leave the room's deployment in
# ImagePullBackOff while the page said it landed, and an image with no linux/amd64 build would never start
# (decisions.md, 2026-10-25, "No arm64 image"). The tag is read as well: when it has moved on, the pin still pulls and
# this prints that it moved, so a refresh of the pin is a choice someone makes. Since #992 deploy_app rewrites any
# Docker official image named on Docker Hub to public.ecr.aws/docker/library/ (OFFICIAL_MIRROR), which holds only if
# Amazon's registry carries Docker's official images, the old five pins and others besides: each of OFFICIAL is read
# there at its tag. verify/test_public_images.py holds the offline half.
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
    with urllib.request.urlopen("https://public.ecr.aws/token/", timeout=30) as r:
        return json.load(r)["token"]


def paced() -> None:
    """ECR Public answers an anonymous client about once a second and 429s the rest, so each request waits its turn."""
    time.sleep(1.2)


# The once-a-second budget is per source address, and this host runs other runs' suites from the same address, so a
# request paced here can still meet a 429 spent by someone else (run 16863: busybox's first manifest, then green on a
# rerun). A 429 says wait, not no: it is retried after Retry-After (at most 30 s), or 2, 4, 8 and 16 seconds,
# five tries in all.
# Any other error, or a sixth 429, still fails the check.
RETRIES_ON_429 = 4
# Docker official images as the room might name them on Docker Hub: the five pins #992 dropped, and others no list
# here ever carried. Each tag is a multi-arch index on Docker Hub, and so on public.ecr.aws.
OFFICIAL = ("busybox:1.38.0", "alpine:3.23", "httpd:2.4-alpine", "redis:8-alpine", "postgres:17", "memcached:1.6",
            "rabbitmq:4")


def opened(req: urllib.request.Request) -> bytes:
    for attempt in range(RETRIES_ON_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RETRIES_ON_429:
                raise
            wait = e.headers.get("Retry-After", "") if e.headers else ""
            time.sleep(min(int(wait), 30) if wait.isdigit() else 2 ** (attempt + 1))
    raise AssertionError("unreachable")


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


try:
    TOKEN = token()
except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
    print(f"FAILED: public.ecr.aws gave no anonymous token: {type(e).__name__}: {e}")
    sys.exit(1)

print("== the landing-page image deploy_app pins is served by public.ecr.aws, with no credential ==")
for name, ref in (("landing", m.LANDING_IMAGE),):
    path, _, digest = ref.partition("@")
    repo, _, tag = path.removeprefix("public.ecr.aws/").rpartition(":")
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
    print(f"  INFO  {name}: :{tag} now serves {now[:19]}..." + ("" if now == digest else " (moved on from the pin)"))

print("== Docker's official images are on public.ecr.aws, where deploy_app moves a Docker Hub reference ==")
for asked in OFFICIAL:
    image, refused = m._off_docker_hub(asked)
    repo, _, tag = image.removeprefix("public.ecr.aws/").rpartition(":")
    check(f"{asked}: deploy_app moves it to {image}", not refused and image.startswith(m.OFFICIAL_MIRROR), refused)
    try:
        served, doc = fetch(TOKEN, repo, tag)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        check(f"{asked}: {image} answers an anonymous pull", False, f"{type(e).__name__}: {e}")
        continue
    check(f"{asked}: {image} answers an anonymous pull", served.startswith("sha256:"), served)
    amd64 = [x for x in doc.get("manifests", []) if x.get("platform", {}).get("os") == "linux"
             and x.get("platform", {}).get("architecture") == "amd64"]
    check(f"{asked}: its index has a linux/amd64 image", bool(amd64))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The landing-page image and Docker's official images deploy_app moves to are served, on linux/amd64.")
