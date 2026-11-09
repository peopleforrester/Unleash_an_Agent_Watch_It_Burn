# ABOUTME: Runs images/kyverno-counter-fix/build.sh on a warm host artifact cache with every proxy a closed port (#1216):
# ABOUTME: its three bases come from the cache's OCI layouts and its source from the cache's kyverno mirror at the pin.
# SUITE: e2e (needs the network on a cache miss: reg.kyverno.io serves the three bases, GitHub the kyverno repository)
# E2E TIER: tools (no cluster, no AWS: the pinned crane from e2e-tools.lock, its own registry on loopback)
"""Why (#1216). build.sh pulled its three pinned Kyverno bases from reg.kyverno.io (crane append -b) and shallow-cloned
kyverno from GitHub on every build. Now each base comes from verify/image_cache.py, an OCI layout keyed by the index
digest images.lock pins, pushed to the build's own registry on loopback, and the source from verify/git_mirror.py's
bare mirror at KYVERNO_COMMIT. A cache hit reads neither.

How. This test asks the cache for the three layouts and the mirror first, so a cold cache is filled here. Then it runs
build.sh, unchanged, into crane's registry on a free loopback port with every proxy variable naming a closed port on
loopback and ARTIFACT_FETCH_LOG pointed at a file of its own, so a build that reached reg.kyverno.io, GitHub or any
registry but its own would fail, and a fetch through the cache would leave a line in that log. The Go build is not
what this holds: `go` is a stub on PATH that prints go1.26.6 and writes a small file for each binary, so the test
needs no Go toolchain and no module download. The digests the real build gives are held to images.lock by the
workflow (scripts/ghcr_version_tag.py refuses any other) and were rebuilt by hand in run 19412 (decisions.md, #1216).

What it checks on each of the three built images: its layers are the cached amd64 image's layers, in order, with one
more on top, that top layer holds ko-app/<binary> as the stub wrote it, and the patch label is set. Then the cache's
mirror is copied (sharing its objects) into a scratch cache root with the v1.19.1 tag moved to the commit before the
pin, and build.sh, pointed at that root, must stop naming both hashes before it builds anything.

Run by hand: CRANE=verify/.tools/bin/crane python3 verify/test_kyverno_counter_fix_cache.py
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD = REPO / "images/kyverno-counter-fix/build.sh"
sys.path.insert(0, str(REPO / "verify"))
import artifact_cache  # noqa: E402
import git_mirror  # noqa: E402
import image_cache  # noqa: E402

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
    print("build.sh builds the three controllers from the host artifact cache, reaching no registry but its own.")
    raise SystemExit(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def amd64_digest(dest: pathlib.Path) -> str:
    """The digest of the linux/amd64 image manifest a cached layout holds (the index's child, for an index)."""
    blobs = dest / "blobs" / "sha256"
    top = json.loads((dest / "index.json").read_text())["manifests"][0]
    doc = json.loads((blobs / top["digest"].removeprefix("sha256:")).read_bytes())
    if image_cache._media_type(doc) in image_cache.INDEX_TYPES:
        return image_cache._platform_child(doc, "linux/amd64", str(dest))["digest"]
    return top["digest"]


crane = os.environ.get("CRANE", "")
if not crane or not os.access(crane, os.X_OK):
    print(f"CRANE must name the pinned crane (verify/fetch-e2e-tools.sh puts it at verify/.tools/bin/crane); got {crane!r}")
    raise SystemExit(1)

text = BUILD.read_text(encoding="utf-8")


def pin(name: str) -> str:
    m = re.search(rf'^{name}="([^"]+)"$', text, re.M)
    if not m:
        print(f"FAIL: {BUILD.relative_to(REPO)} has no {name}=\"...\" line")
        raise SystemExit(1)
    return m.group(1)


url, tag, commit = pin("KYVERNO_URL"), pin("KYVERNO_TAG"), pin("KYVERNO_COMMIT")
block = re.search(r"^declare -A BASE=\((.*?)^\)", text, re.M | re.S)
bases = dict(re.findall(r'\[([\w-]+)\]="([^"]+)"', block.group(1))) if block else {}
if len(bases) != 3:
    print(f"FAIL: {BUILD.relative_to(REPO)}'s BASE array names {sorted(bases)}, not the three controllers")
    raise SystemExit(1)

print("== the host artifact cache serves the three bases and the kyverno mirror ==")
layouts = {}
for b, ref in sorted(bases.items()):
    try:
        layouts[b] = image_cache.layout(ref)
        check(f"{b}: an OCI layout keyed by its pinned index digest", layouts[b].name == ref.rsplit(":", 1)[1])
    except Exception as err:  # noqa: BLE001 - the check names what failed
        check(f"{b}: an OCI layout keyed by its pinned index digest", False, f"{type(err).__name__}: {err}")
try:
    mirror = git_mirror.ensure(url, commit)
    check(f"a bare mirror of {url} holds {commit[:12]}", mirror.is_dir())
except Exception as err:  # noqa: BLE001
    check(f"a bare mirror of {url} holds {commit[:12]}", False, f"{type(err).__name__}: {err}")
if failures:
    finish()

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    stub = tmp / "stub-bin"
    stub.mkdir()
    (stub / "go").write_text("""#!/usr/bin/env bash
# A stand-in for the go command: build.sh's version check, and one small file per binary it builds.
set -euo pipefail
case "$1" in
  env) [[ "$2" == GOVERSION ]] && { echo "${GOTOOLCHAIN}"; exit 0; } ;;
  build) out=""; pkg=""
    while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2 ;; ./cmd/*) pkg="$1"; shift ;; *) shift ;; esac; done
    [[ -f "${pkg}/main.go" ]] || { echo "stub go: ${pkg} has no main.go in $(pwd)" >&2; exit 1; }
    printf 'stub %s %s\\n' "${pkg}" "$(git rev-parse HEAD)" >"${out}"; exit 0 ;;
esac
echo "stub go: unexpected $*" >&2; exit 1
""")
    (stub / "go").chmod(0o755)
    port = free_port()
    addr = f"127.0.0.1:{port}"
    dead = f"http://127.0.0.1:{free_port()}"
    fetch_log = tmp / "fetch.log"
    offline = {**os.environ, "CRANE": crane, "PATH": f"{stub}:{os.environ['PATH']}", "ARTIFACT_FETCH_LOG": str(fetch_log),
               "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
               **{v: dead for v in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy")}}
    log = (tmp / "registry.log").open("w")
    reg = subprocess.Popen([crane, "registry", "serve", "--address", addr], stdout=log, stderr=log)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://{addr}/v2/", timeout=2).read()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        else:
            check(f"crane's registry answers on {addr}", False, (tmp / "registry.log").read_text()[-300:])
            finish()

        print("== build.sh, unchanged, on the warm cache, with no registry or GitHub reachable ==")
        r = subprocess.run(["bash", str(BUILD), addr], env=offline, capture_output=True, text=True, timeout=900)
        out = r.stdout + r.stderr
        check("build.sh builds all three (exit 0), every proxy a closed port", r.returncode == 0, out[-800:])
        check("the cache fetched nothing: the run's fetch log was never written",
              not fetch_log.exists() or fetch_log.read_text() == "", fetch_log.read_text() if fetch_log.exists() else "")
        built = dict(re.findall(r"^built (\S+) (sha256:[0-9a-f]{64})$", r.stdout, re.M))
        check("it prints a built line for each of the three", len(built) == 3, r.stdout[-400:])
        tags = dict(re.findall(r'\[([\w-]+)\]="([^"]+)"',
                               re.search(r"^declare -A TAG=\((.*?)^\)", text, re.M | re.S).group(1)))
        for b in sorted(bases):
            ref = f"{addr}/peopleforrester/watch-it-burn:{tags[b]}"
            cached = image_cache.image(layouts[b])
            m = subprocess.run([crane, "--insecure", "manifest", ref], capture_output=True, text=True, timeout=60)
            try:
                manifest = json.loads(m.stdout)
            except json.JSONDecodeError:
                check(f"{b}: the build is in the loopback registry", False, m.stderr.strip()[:200])
                continue
            want = [d["digest"] for d in cached["manifest"]["layers"]]
            got = [d["digest"] for d in manifest.get("layers", [])]
            check(f"{b}: its layers are the cached amd64 base's {len(want)}, in order, and one more on top",
                  got[:-1] == want and len(got) == len(want) + 1, f"{got} vs {want}")
            pushed_base = subprocess.run([crane, "--insecure", "digest", f"{addr}/kyverno-base/{b}"],
                                         capture_output=True, text=True, timeout=60).stdout.strip()
            check(f"{b}: the base build.sh pushed to loopback is the cached amd64 image",
                  pushed_base == amd64_digest(layouts[b]), f"{pushed_base} vs {amd64_digest(layouts[b])}")
            blob = subprocess.run([crane, "--insecure", "blob", f"{addr}/peopleforrester/watch-it-burn@{got[-1]}"],
                                  capture_output=True, timeout=60).stdout if got else b""
            files = {}
            try:
                with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
                    files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
            except tarfile.TarError as err:
                files = {"<unreadable>": str(err).encode()}
            check(f"{b}: the top layer is ko-app/{b} alone, built from the pinned checkout",
                  list(files) == [f"ko-app/{b}"]
                  and files[f"ko-app/{b}"].decode() == f"stub ./cmd/{b} {commit}\n", f"{files}")
            c = subprocess.run([crane, "--insecure", "config", ref], capture_output=True, text=True, timeout=60)
            labels = (json.loads(c.stdout or "{}").get("config") or {}).get("Labels") or {}
            check(f"{b}: the config carries the patch label",
                  "kyverno/kyverno#17085" in labels.get("io.github.peopleforrester.watch-it-burn.kyverno-patch", ""),
                  f"{labels}")

        print("== a mirror whose tag names another commit stops the build, naming both hashes ==")
        root = artifact_cache.scratch_dir("kyverno-counter-fix-test-")
        try:
            moved = git_mirror.mirror_path(url, root)
            moved.parent.mkdir(parents=True)
            subprocess.run(["git", "clone", "--quiet", "--bare", "--shared", str(mirror), str(moved)], check=True)
            parent = subprocess.run(["git", "--git-dir", str(moved), "rev-parse", f"{commit}^"], check=True,
                                    capture_output=True, text=True).stdout.strip()
            subprocess.run(["git", "--git-dir", str(moved), "tag", "-f", tag, parent], check=True, capture_output=True)
            r = subprocess.run(["bash", str(BUILD), addr], env={**offline, "WIB_ARTIFACT_CACHE": str(root)},
                               capture_output=True, text=True, timeout=300)
            check("build.sh exits 1", r.returncode == 1, (r.stdout + r.stderr)[-400:])
            check(f"its message names the tag, the commit the mirror's tag names and the pin",
                  f"kyverno {tag} is {parent} in the mirror {moved}, not {commit}" in r.stderr, r.stderr[-400:])
            check("nothing was built", "built " not in r.stdout, r.stdout[-200:])
        finally:
            shutil.rmtree(root, ignore_errors=True)
    finally:
        reg.terminate()
        reg.wait(timeout=10)
        log.close()

finish()
