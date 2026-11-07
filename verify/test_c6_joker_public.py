# ABOUTME: Reads both published Jokers from ghcr.io anonymously (#671, #829): Challenge 6's, which HC-7731 names, and the
# ABOUTME: breakout's -internal tag, which the internal registry seeds: each at images.lock's pin, with its page on top.
# SUITE: e2e (needs the network: ghcr.io is asked for both Joker tags and for lab-platform's copy of their busybox base)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #671 moved C6 off Docker Hub's peopleforrester account, so the Deployment the ticket causes still pulls once the Docker
# Hub villains are retired. A node pulls gitops/ai-layer/ticket_site.py's C6_IMAGE with no credential, so a private
# or missing package admits the Deployment on the public cluster and leaves the pod in ImagePullBackOff, and
# maintenance-shell-<cluster> shows the console's "Nothing is running" page. The image is pushed by hand
# (images/villains/build.sh joker), so an edit to joker-web/ that was never pushed is also a page the room does not
# get: the pushed layer must hold this checkout's start.sh and page, byte for byte, on build.sh's pinned busybox.
# verify/test_c6_villain_endpoint.py holds the same image to build.sh offline, and verify/test_joker_web_busybox.py
# runs the entrypoint; this file reads what is actually published.
#
# The breakout's Joker (#775, #829), ...:busybox-1.38.0-internal, is the same build with joker-web-internal/'s page laid
# over joker-web/'s. gitops/internal-registry/ copies it by digest into registry.burritobot.co for KubeCon's HC-666, and
# verify/test_joker_build_digest.py rebuilds it at images.lock's pin, but only this file reads what ghcr.io serves for
# the tag. Each Joker is held to the digest images.lock pins for it, so a pin that was never pushed (or a push that
# was never re-pinned) fails here, and to its top layer: its page, joker-web's start.sh and the shell banner (#714).
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import tarfile
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ghcr_pull import ACCEPT, read_url, served_digest  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
VILLAINS = REPO / "images/villains"
LOCK = (REPO / "images.lock").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("Both Jokers are public, at images.lock's pins, and are this checkout's page Jokers.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def get(url: str, token: str, digest: str | None = None) -> bytes:
    """A manifest or blob, checked against its digest when one is given. A blob's redirect to storage is followed
    without the token, which the storage host does not take."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
    try:
        body = read_url(req, timeout=60, opener=_opener)
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 307, 308):
            raise
        body = read_url(e.headers["Location"], timeout=120)
    if digest is not None:
        got = "sha256:" + hashlib.sha256(body).hexdigest()
        if got != digest:
            raise ValueError(f"{url} came back as {got}")
    return body


def token(url: str) -> str:
    return json.loads(read_url(url))["token"]


def pinned(ref: str) -> str | None:
    """images.lock's digest for a tag reference: the row whose reference is <ref>@sha256:..."""
    m = re.search(rf"^{re.escape(ref)}@(sha256:[0-9a-f]{{64}}) ", LOCK, re.M)
    return m.group(1) if m else None


def amd64(manifest: dict, repo: str, tok: str) -> dict:
    """The linux/amd64 image of an index, or the manifest itself: the nodes are linux/amd64, and build.sh's crane
    append takes its base's linux/amd64 image."""
    if "manifests" not in manifest:
        return manifest
    amd = next(d["digest"] for d in manifest["manifests"]
               if d.get("platform", {}).get("os") == "linux" and d["platform"].get("architecture") == "amd64")
    return json.loads(get(f"https://ghcr.io/v2/{repo}/manifests/{amd}", tok, amd))


spec = importlib.util.spec_from_file_location("ticket_site", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
image = site.C6_IMAGE

print("== the two Jokers: the ticket's image and build.sh's -internal tag beside it ==")
check("the ticket names an image on ghcr.io, not Docker Hub (#671)", image.startswith("ghcr.io/peopleforrester/"),
      image)
ref = re.search(r'^JOKER_REF="([^"]+)"$', BUILD, re.M)
check("the ticket's image is build.sh's JOKER_REF, the tag `build.sh joker` pushes", bool(ref) and ref.group(1) == image,
      ref.group(1) if ref else "no JOKER_REF line in images/villains/build.sh")
suffix = re.search(r'^JOKER_INTERNAL_REF="\$\{JOKER_REF\}(-[a-z0-9.-]+)"$', BUILD, re.M)
check("build.sh's JOKER_INTERNAL_REF is a tag beside it, in the same public package (#775)", bool(suffix),
      "no JOKER_INTERNAL_REF=\"${JOKER_REF}-...\" line in images/villains/build.sh")
if failures:
    finish()
# name, reference, the directory whose www/index.html is the page, and the build.sh command that pushes it
JOKERS = [("the workshop Joker", image, "joker-web", "joker"),
          ("the breakout's Joker", image + suffix.group(1), "joker-web-internal", "joker-internal")]

base = re.search(r'^JOKER_BASE="ghcr\.io/(peopleforrester/lab-platform/mirror/library/busybox):[^@"]+@(sha256:[0-9a-f]{64})"',
                 BUILD, re.M)
check("build.sh pins JOKER_BASE to lab-platform's ghcr.io busybox copy by digest (#714)", base is not None)
base_layers: list[str] | None = None
if base is not None:
    try:
        btok = token(f"https://ghcr.io/token?scope=repository:{base.group(1)}:pull")
        bman = amd64(json.loads(get(f"https://ghcr.io/v2/{base.group(1)}/manifests/{base.group(2)}", btok,
                                    base.group(2))), base.group(1), btok)
        base_layers = [x["digest"] for x in bman["layers"]]
        check(f"ghcr.io serves {base.group(1)}@{base.group(2)[:19]}... anonymously", True)
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
        check(f"ghcr.io serves {base.group(1)}@{base.group(2)[:19]}... anonymously", False,
              f"{type(e).__name__}: {e}")
port = re.search(r"--env PORT=(\d+)", BUILD)
env = re.search(r"--env ENV=(\S+)", BUILD)
check("build.sh sets PORT, which the maintenance-shell Service targets, and ENV, the shell banner (#714)",
      port is not None and env is not None)
# The banner's path is the one busybox sh reads and the one the issue names (#938): a different ENV in build.sh would
# otherwise move the layer member this file holds along with it.
check("build.sh's ENV is /etc/villain-banner.sh, the banner's path in the layer (#938)",
      env is not None and env.group(1) == "/etc/villain-banner.sh", env.group(1) if env else "no --env ENV= flag")

for name, ref, page_dir, cmd in JOKERS:
    print(f"\n== {name}, {ref}, answers an anonymous pull at images.lock's pin ==")
    want = pinned(ref)
    check(f"images.lock pins {ref} by digest", want is not None, f"no {ref}@sha256:... row in images.lock")
    digest, why = served_digest(ref)
    check(f"{ref} answers an anonymous pull", digest is not None, why)
    if digest is None or want is None:
        continue
    check(f"ghcr.io serves {ref} at images.lock's {want[:19]}...", digest == want,
          f"served {digest}: push it with `CRANE=verify/.tools/bin/crane bash images/villains/build.sh {cmd}`, "
          "or re-pin images.lock and the internal registry's seed")

    repo = ref.partition("/")[2].rsplit(":", 1)[0]
    label = f"ghcr.io serves {ref}'s manifest, config and top layer, each matching its digest"
    try:
        tok = token(f"https://ghcr.io/token?scope=repository:{repo}:pull")
        manifest = amd64(json.loads(get(f"https://ghcr.io/v2/{repo}/manifests/{digest}", tok, digest)), repo, tok)
        config = json.loads(get(f"https://ghcr.io/v2/{repo}/blobs/{manifest['config']['digest']}", tok,
                                manifest["config"]["digest"]))
        top = manifest["layers"][-1]["digest"]
        layer = get(f"https://ghcr.io/v2/{repo}/blobs/{top}", tok, top)
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, StopIteration) as e:
        check(label, False, f"{type(e).__name__}: {e}")
        continue
    check(label, True)

    print(f"== {name} runs as build.sh says: start.sh, PORT, ENV, amd64, on the pinned busybox ==")
    cfg = config.get("config", {})
    check(f"{name}: the platform is linux/amd64, the nodes'",
          (config.get("os"), config.get("architecture")) == ("linux", "amd64"),
          f"{config.get('os')}/{config.get('architecture')}")
    check(f"{name}: the entrypoint is start.sh under the image's own sh",
          cfg.get("Entrypoint") == ["/bin/sh", "/villain/start.sh"], str(cfg.get("Entrypoint")))
    if port is not None and env is not None:
        check(f"{name}: PORT and ENV are the ones build.sh sets",
              {f"PORT={port.group(1)}", f"ENV={env.group(1)}"} <= set(cfg.get("Env", [])), str(cfg.get("Env")))
    if base_layers is not None:
        got = [x["digest"] for x in manifest["layers"][:-1]]
        check(f"{name}: every layer under the Joker's is the pinned busybox's linux/amd64 layer", got == base_layers,
              f"{got} != {base_layers}")

    print(f"== {name}'s top layer is this checkout's {page_dir}/ page, joker-web's start.sh and the banner ==")
    with tarfile.open(fileobj=io.BytesIO(layer)) as tar:
        members = {t.name.lstrip("./"): t for t in tar.getmembers() if t.isfile()}
        expected = {"villain/start.sh": VILLAINS / "joker-web/start.sh",
                    "villain/www/index.html": VILLAINS / page_dir / "www/index.html"}
        if env is not None:
            expected[env.group(1).lstrip("/")] = VILLAINS / "villain-banner.sh"
        for member, src in expected.items():
            pushed = tar.extractfile(members[member]).read() if member in members else None
            check(f"{name}: {member} is {src.relative_to(REPO)}, byte for byte", pushed == src.read_bytes(),
                  "missing from the layer" if pushed is None
                  else f"differs: push it again with `CRANE=verify/.tools/bin/crane bash images/villains/build.sh {cmd}`")
        sh = members.get("villain/start.sh")
        check(f"{name}: villain/start.sh is executable in the layer", sh is not None and sh.mode & 0o111 != 0,
              oct(sh.mode) if sh else "missing")

finish()
