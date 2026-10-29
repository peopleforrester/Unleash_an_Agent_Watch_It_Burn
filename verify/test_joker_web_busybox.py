# ABOUTME: Runs C6's Joker entrypoint (#664) on the busybox the image is built from: images/villains/build.sh's pinned
# ABOUTME: JOKER_BASE, pulled from Docker Hub by digest. The page must be served, the laugh logged, and SIGTERM obeyed.
# SUITE: e2e (needs the network: Docker Hub is asked for the pinned busybox)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it, #572)
#
# Why. build.sh needs the Docker Hub Team credentials, so a run cannot push the image and see it serve. What can be
# checked without them is everything the image adds to its base: start.sh and www/, run by the base's own busybox
# (its sh, its httpd), exactly as the layer build.sh appends lays them out. The busybox is fetched by the digest
# build.sh pins, every blob checked against its sha256, and only bin/busybox is taken from the layer.
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
JOKER = REPO / "images/villains/joker-web"
PAGE = (JOKER / "www/index.html").read_bytes()
REGISTRY = "https://registry-1.docker.io"
ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))

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
    print("The Joker's entrypoint serves its page on the pinned busybox.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def get(repo: str, token: str, path: str, digest: str) -> bytes:
    """A manifest or blob by digest, checked against it. A blob's redirect is followed without the token."""
    req = urllib.request.Request(f"{REGISTRY}/v2/{repo}/{path}/{digest}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
    try:
        with _opener.open(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 307, 308):
            raise
        with urllib.request.urlopen(e.headers["Location"], timeout=120) as r:
            body = r.read()
    got = "sha256:" + hashlib.sha256(body).hexdigest()
    if got != digest:
        raise ValueError(f"{path}/{digest} came back as {got}")
    return body


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fetch(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, "", str(e).encode()


print("== the pinned base ==")
m = re.search(r'^JOKER_BASE="docker\.io/(library/busybox)@(sha256:[0-9a-f]{64})"', BUILD, re.M)
check("build.sh pins JOKER_BASE to a busybox digest", m is not None)
if not m:
    finish()
repo, index_digest = m.group(1), m.group(2)
try:
    with urllib.request.urlopen(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
                                timeout=30) as r:
        token = json.load(r)["token"]
    index = json.loads(get(repo, token, "manifests", index_digest))
    amd64 = next(d["digest"] for d in index.get("manifests", [])
                 if d.get("platform", {}).get("os") == "linux" and d["platform"].get("architecture") == "amd64")
    manifest = json.loads(get(repo, token, "manifests", amd64))
    layers = manifest.get("layers", [])
    blobs = [get(repo, token, "blobs", layer["digest"]) for layer in layers]
except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
    check(f"Docker Hub serves {repo}@{index_digest} for linux/amd64, every blob matching its digest", False,
          f"{type(e).__name__}: {e}")
    finish()
check(f"Docker Hub serves {repo}@{index_digest[:19]}... for linux/amd64, every blob matching its digest", True)

work = pathlib.Path(tempfile.mkdtemp(prefix="joker-web-"))
try:
    bindir = work / "bin"
    bindir.mkdir()
    found = False
    for blob in blobs:
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            # bin/busybox is a hard link in this layer (to bin/[); extractfile follows it to the file.
            member = next((t for t in tar.getmembers() if t.name.lstrip("./") == "bin/busybox"
                           and (t.isfile() or t.islnk())), None)
            if member is not None:
                (bindir / "busybox").write_bytes(tar.extractfile(member).read())
                found = True
    check("the base's layer carries bin/busybox", found)
    if not found:
        finish()
    (bindir / "busybox").chmod(0o755)
    for applet in ("sh", "httpd", "sleep", "dirname"):
        (bindir / applet).symlink_to("busybox")
    # Laid out as build.sh's layer is: joker-web/ becomes /villain.
    villain = work / "villain"
    shutil.copytree(JOKER, villain)

    print("== start.sh refuses to run without PORT ==")
    p = subprocess.run([str(bindir / "sh"), str(villain / "start.sh")], env={"PATH": str(bindir)},
                       capture_output=True, text=True, timeout=10)
    check("no PORT: it exits non-zero and says so", p.returncode != 0 and "PORT is not set" in p.stderr,
          f"rc={p.returncode} {p.stderr.strip()[:160]}")

    print("== start.sh serves the page and laughs ==")
    port = free_port()
    log = work / "log"
    with open(log, "w") as out:
        proc = subprocess.Popen([str(bindir / "sh"), str(villain / "start.sh")],
                                env={"PATH": str(bindir), "PORT": str(port)}, stdout=out, stderr=subprocess.STDOUT)
    try:
        status, ctype, body = 0, "", b""
        for _ in range(50):
            status, ctype, body = fetch(f"http://127.0.0.1:{port}/")
            if status == 200:
                break
            time.sleep(0.1)
        check(f"GET / answers 200 on PORT={port}", status == 200, f"{status} {body[:160]!r}")
        check("it is www/index.html, byte for byte", body == PAGE)
        check("as text/html", ctype.startswith("text/html"), ctype)
        status, _, _ = fetch(f"http://127.0.0.1:{port}/etc/passwd")
        check("a path outside www/ is a 404", status == 404, str(status))
        text = log.read_text()
        check("the log carries the Joker's laugh",
              "HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?" in text, text[:200])

        print("== SIGTERM ends it, and the port with it ==")
        proc.send_signal(signal.SIGTERM)
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            rc = None
        check("the entrypoint exits 0 within 5 seconds of SIGTERM", rc == 0, f"rc={rc}")
        time.sleep(0.3)
        status, _, _ = fetch(f"http://127.0.0.1:{port}/")
        check("httpd is gone with it", status == 0, str(status))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if shutil.which("pkill"):   # an httpd left behind by a failed run, not one that SIGTERM ended
            subprocess.run(["pkill", "-f", f"httpd -f -p {port} "], capture_output=True)
finally:
    shutil.rmtree(work, ignore_errors=True)

finish()
