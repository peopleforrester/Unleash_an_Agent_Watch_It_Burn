# ABOUTME: Reads Challenge 2's four games (#991) from their registries anonymously: each image BurritoBot's prompt names
# ABOUTME: is served at its pinned digest with no credential, and is linux/amd64, the only architecture these nodes have.
# SUITE: e2e (needs the network: Docker Hub, quay.io and public.ecr.aws are each asked for their manifests)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. Since #991 deploy_app applies the image the bot writes and picks none itself, so BurritoBot's system prompt
# (gitops/workshop-agent/agent.yaml) names four games by exact image and digest: Tron, 2048, Infinite Mario and Tetris.
# A guest's "deploy Tron" pulls that pin, anonymously, on a node. A digest the registry stopped serving would leave the
# room's deployment in ImagePullBackOff while the page said it landed, and an image with no linux/amd64 build would
# never start (decisions.md, 2026-10-25, "No arm64 image"). Each pin is the amd64 image itself, not an index, so its
# config is read for its platform. Two of the four are on Docker Hub, where a manifest GET counts against the
# anonymous pull limit of the address it comes from; this reads two such manifests a run. verify/test_public_images.py
# holds the offline half: the prompt's pins equal images.lock's rows, and deploy_app applies them as written.
# verify/test_public_images_retry.py lifts opened(), token() and the names they use out of this file and runs them
# offline.
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from docker_hub import HUB_HOSTS  # noqa: E402

# Docker Hub's names, from the gate's own list, so this file names no Docker Hub host (test_no_docker_hub.py, check 2):
# the name a reference uses, and the host its v2 API answers on.
HUB, HUB_API = HUB_HOSTS[0], HUB_HOSTS[2]
ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


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
# every try gets no answer, opened() raises Unreachable, which names the registry the request went to, and the test
# fails on that alone, so an unreachable registry never reads as an image that is not served.
# The resolver is on that path too (#1029). Run 17937's tier went red on one "[Errno -3] Temporary failure in name
# resolution" for public.ecr.aws, read as an image that does not pull, and passed 23 of 23 on its own twice. A
# temporary resolver failure (EAI_AGAIN) is no answer, retried on the same budget. Any other resolver failure (the
# name is not known, or the resolver failed for good) is not retried, and raises Unreachable at once: the host cannot
# find the registry, which is no verdict on an image either.
# Any other error (an HTTP status that is not 429, a certificate the host cannot verify), or a fifth 429, still fails
# at once.
# REGISTRY is the one whose token endpoint takes no scope, token()'s default; since #991 the games are on three.
REGISTRY = "public.ecr.aws"
RETRIES_ON_429 = 4
RETRIES_ON_NO_ANSWER = 2
NO_ANSWER_WAIT = 5


class Unreachable(Exception):
    """Every try at one request got no answer, or the registry's name did not resolve: a verdict on this host's
    path to the registry, not on an image."""


def reason_of(e: BaseException) -> BaseException:
    """What went wrong under urlopen: a URLError's reason from the open, or the error itself, raised bare."""
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        return e.reason if isinstance(e.reason, BaseException) else e
    return e


def unresolved(e: BaseException) -> bool:
    """The resolver could not give the registry's address, for good: not a temporary failure (EAI_AGAIN)."""
    reason = reason_of(e)
    return isinstance(reason, socket.gaierror) and reason.errno != socket.EAI_AGAIN


def no_answer(e: BaseException) -> bool:
    """A timeout, a dropped connection or a temporary resolver failure: raised bare from the read, or as a URLError's
    reason from the open."""
    reason = reason_of(e)
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
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
            if unresolved(e):
                raise Unreachable(f"{req.host}'s name did not resolve on this host, for {req.full_url}: "
                                  f"{type(e).__name__}: {e}") from e
            if not no_answer(e):
                raise
            silent += 1
            if silent > RETRIES_ON_NO_ANSWER:
                raise Unreachable(f"{req.host} gave no answer to {req.full_url} on {silent} tries, {NO_ANSWER_WAIT} s "
                                  f"apart; the last: {type(e).__name__}: {e}") from e
            time.sleep(NO_ANSWER_WAIT)


def token(url: str = f"https://{REGISTRY}/token/") -> str:
    """An anonymous pull token from a registry's token service (token_url names each one's)."""
    return json.loads(opened(urllib.request.Request(url)))["token"]


def token_url(host: str, repo: str) -> str:
    scope = f"repository:{repo}:pull"
    if host == HUB_API:
        return f"https://auth.{HUB}/token?service=registry.{HUB}&scope={scope}"
    if host == "quay.io":
        return f"https://quay.io/v2/auth?service=quay.io&scope={scope}"
    return f"https://{host}/token/"


def split(ref: str) -> tuple[str, str, str]:
    """The registry host the v2 API answers on, the repository, and the pinned digest."""
    path, _, digest = ref.partition("@")
    host, _, repo = path.partition("/")
    repo = repo.rsplit(":", 1)[0] if ":" in repo.rsplit("/", 1)[-1] else repo
    return (HUB_API if host == HUB else host), repo, digest


def fetch(host: str, tok: str, repo: str, ref: str) -> tuple[str, dict]:
    paced()
    req = urllib.request.Request(f"https://{host}/v2/{repo}/manifests/{ref}",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": ACCEPT})
    # The digest is the sha256 of the bytes served, computed here: not every registry sends Docker-Content-Digest.
    raw = opened(req)
    return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(raw)


def blob(host: str, tok: str, repo: str, digest: str) -> dict:
    paced()
    req = urllib.request.Request(f"https://{host}/v2/{repo}/blobs/{digest}",
                                 headers={"Authorization": f"Bearer {tok}"})
    return json.loads(opened(req))


def unreachable(e: Unreachable) -> None:
    """A registry gave no answer: this says nothing of the pins still unread, so it fails as that, by name."""
    print(f"\nFAILED: a game's registry is unreachable from this host, and the images not yet read have no verdict: {e}")
    for f in failures:
        print(f"  - failed before it stopped answering: {f}")
    sys.exit(1)


PROMPT = yaml.safe_load((REPO / "gitops/workshop-agent/agent.yaml").read_text())["spec"]["declarative"]["systemMessage"]
GAMES = dict(re.findall(r"^\s*- (Tron|2048|Infinite Mario|Tetris): (\S+)$", PROMPT, re.M))
check("the prompt names the four games", sorted(GAMES) == ["2048", "Infinite Mario", "Tetris", "Tron"], str(GAMES))

try:
    TOKENS = {game: token(token_url(*split(ref)[:2])) for game, ref in GAMES.items()}
except Unreachable as e:
    unreachable(e)
except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
    print(f"FAILED: a game's registry gave no anonymous token: {type(e).__name__}: {e}")
    sys.exit(1)

try:
    print("== each game the prompt names is served at its pin, with no credential, on linux/amd64 ==")
    for game, ref in GAMES.items():
        host, repo, digest = split(ref)
        tok = TOKENS[game]
        try:
            served, doc = fetch(host, tok, repo, digest)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            check(f"{game}: {host}/{repo}@{digest[:19]}... answers an anonymous pull", False,
                  f"{type(e).__name__}: {e}")
            continue
        check(f"{game}: {host}/{repo}@{digest[:19]}... answers an anonymous pull", served == digest, served)
        is_index = doc.get("mediaType") in INDEX_TYPES or "manifests" in doc
        check(f"{game}: the pin is one image, not an index", not is_index, str(doc.get("mediaType")))
        if is_index or not isinstance(doc.get("config"), dict):
            continue
        try:
            cfg = blob(host, tok, repo, doc["config"]["digest"])
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            check(f"{game}: its config answers", False, f"{type(e).__name__}: {e}")
            continue
        check(f"{game}: the image is linux/amd64", (cfg.get("os"), cfg.get("architecture")) == ("linux", "amd64"),
              f"{cfg.get('os')}/{cfg.get('architecture')}")
        ports = sorted((cfg.get("config") or {}).get("ExposedPorts") or {})
        print(f"  INFO  {game}: exposes {', '.join(ports) or 'no port'}")
except Unreachable as e:
    unreachable(e)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The four games BurritoBot's prompt names are served at their pins, on linux/amd64.")
