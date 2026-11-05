# ABOUTME: Reads Challenge 6's Joker, the image HC-7731's hidden paragraph names, from ghcr.io anonymously (#671): it
# ABOUTME: is public, so the public cluster's nodes pull it, and it is the page Joker build.sh builds from joker-web/.
# SUITE: e2e (needs the network: ghcr.io is asked for the ticket's image and for lab-platform's copy of its busybox base)
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
from ghcr_pull import ACCEPT, served_digest  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
JOKER = REPO / "images/villains/joker-web"

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
    print("Challenge 6's Joker is public and is this checkout's page Joker.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def get(url: str, token: str, digest: str | None = None) -> bytes:
    """A manifest or blob, checked against its digest when one is given. A blob's redirect to storage is followed
    without the token, which the storage host does not take."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
    try:
        with _opener.open(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 307, 308):
            raise
        with urllib.request.urlopen(e.headers["Location"], timeout=120) as r:
            body = r.read()
    if digest is not None:
        got = "sha256:" + hashlib.sha256(body).hexdigest()
        if got != digest:
            raise ValueError(f"{url} came back as {got}")
    return body


def token(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["token"]


spec = importlib.util.spec_from_file_location("ticket_site", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
image = site.C6_IMAGE

print(f"== the ticket's image, {image}, answers an anonymous pull ==")
check("the ticket names an image on ghcr.io, not Docker Hub (#671)", image.startswith("ghcr.io/peopleforrester/"),
      image)
if failures:
    finish()
digest, why = served_digest(image)
check(f"{image} answers an anonymous pull", digest is not None, why)
if digest is None:
    finish()

repo, tag = image.partition("/")[2].rsplit(":", 1)
try:
    tok = token(f"https://ghcr.io/token?scope=repository:{repo}:pull")
    manifest = json.loads(get(f"https://ghcr.io/v2/{repo}/manifests/{digest}", tok, digest))
    if "manifests" in manifest:  # an index: the nodes are linux/amd64
        amd = next(d["digest"] for d in manifest["manifests"]
                   if d.get("platform", {}).get("os") == "linux" and d["platform"].get("architecture") == "amd64")
        manifest = json.loads(get(f"https://ghcr.io/v2/{repo}/manifests/{amd}", tok, amd))
    config = json.loads(get(f"https://ghcr.io/v2/{repo}/blobs/{manifest['config']['digest']}", tok,
                            manifest["config"]["digest"]))
    top = manifest["layers"][-1]["digest"]
    layer = get(f"https://ghcr.io/v2/{repo}/blobs/{top}", tok, top)
except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, StopIteration) as e:
    check(f"ghcr.io serves {image}'s manifest, config and top layer, each matching its digest", False,
          f"{type(e).__name__}: {e}")
    finish()
check(f"ghcr.io serves {image}'s manifest, config and top layer, each matching its digest", True)

print("== it runs as build.sh says: start.sh, PORT=8080, amd64 ==")
cfg = config.get("config", {})
check("the platform is linux/amd64, the nodes'", (config.get("os"), config.get("architecture")) == ("linux", "amd64"),
      f"{config.get('os')}/{config.get('architecture')}")
check("the entrypoint is start.sh under the image's own sh", cfg.get("Entrypoint") == ["/bin/sh", "/villain/start.sh"],
      str(cfg.get("Entrypoint")))
port = re.search(r"--env PORT=(\d+)", BUILD)
check("PORT is the one build.sh sets, which the maintenance-shell Service targets",
      port is not None and f"PORT={port.group(1)}" in cfg.get("Env", []), str(cfg.get("Env")))

print("== its base is build.sh's pinned busybox ==")
base = re.search(r'^JOKER_BASE="ghcr\.io/(peopleforrester/lab-platform/mirror/library/busybox):[^@"]+@(sha256:[0-9a-f]{64})"',
                 BUILD, re.M)
check("build.sh pins JOKER_BASE to lab-platform's ghcr.io busybox copy by digest (#714)", base is not None)
if base is not None:
    try:
        btok = token(f"https://ghcr.io/token?scope=repository:{base.group(1)}:pull")
        bman = json.loads(get(f"https://ghcr.io/v2/{base.group(1)}/manifests/{base.group(2)}", btok, base.group(2)))
        if "manifests" in bman:  # an index: build.sh's crane append takes its linux/amd64 image
            amd = next(d["digest"] for d in bman["manifests"]
                       if d.get("platform", {}).get("os") == "linux" and d["platform"].get("architecture") == "amd64")
            bman = json.loads(get(f"https://ghcr.io/v2/{base.group(1)}/manifests/{amd}", btok, amd))
        want = [x["digest"] for x in bman["layers"]]
        got = [x["digest"] for x in manifest["layers"][:-1]]
        check("every layer under the Joker's is the pinned busybox's linux/amd64 layer", got == want, f"{got} != {want}")
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
        check(f"ghcr.io serves {base.group(1)}@{base.group(2)[:19]}... anonymously", False,
              f"{type(e).__name__}: {e}")

print("== its top layer is this checkout's joker-web/, under /villain ==")
with tarfile.open(fileobj=io.BytesIO(layer)) as tar:
    members = {t.name.lstrip("./"): t for t in tar.getmembers() if t.isfile()}
    for rel in ("start.sh", "www/index.html"):
        name = f"villain/{rel}"
        pushed = tar.extractfile(members[name]).read() if name in members else None
        check(f"{name} is images/villains/joker-web/{rel}, byte for byte", pushed == (JOKER / rel).read_bytes(),
              "missing from the layer" if pushed is None
              else "differs: push it again with `bash images/villains/build.sh joker`")
    sh = members.get("villain/start.sh")
    check("villain/start.sh is executable in the layer", sh is not None and sh.mode & 0o111 != 0,
          oct(sh.mode) if sh else "missing")

finish()
