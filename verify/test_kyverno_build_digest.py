# ABOUTME: Rebuilds Kyverno v1.19.1's admission and reports controllers with kyverno/kyverno#17085 via images/kyverno/build.sh
# ABOUTME: into a throwaway loopback registry (#1015) and holds each digest to images.lock, then reads the fix in each binary.
# SUITE: e2e (needs the network: github.com serves Kyverno's source, proxy.golang.org its modules and Go toolchain, and
# reg.kyverno.io the upstream images build.sh lays its layer over)
# E2E TIER: tools (no cluster, no AWS: the pinned crane from e2e-tools.lock, its own registry on loopback, and any go
# 1.21 or later on PATH, which fetches the toolchain build.sh pins)
"""Why (#1015). gitops/bootstrap/apps/kyverno.yaml runs both report-writing Kyverno controllers from two images this
repo builds, pinned by digest in images.lock before their first push: a run may not write to ghcr.io, and
.github/workflows/push-kyverno.yml pushes a build to its tag only when its digest is the pin. So this test is what
says the pins are right: build.sh, run unchanged, has to build exactly the digests images.lock pins. When it does not
(upstream moved its tag, the patch or the toolchain changed), this names the pin that moves; re-pin it in images.lock
and kyverno.yaml, and the next push to staging pushes the build.

The build is reproducible: the Go toolchain is pinned through GOTOOLCHAIN, the binaries are built with -trimpath and
no VCS stamp, and the layer's tar sets owner, mtime, order and modes. On 2026-11-07 two builds on this host, one with
warm caches and one with empty module and build caches under umask 002, gave the same two digests.

Then each image is opened: its /ko-app binary must carry the fix (the function #17085 adds, (*counter).resync, which
upstream's v1.19.1 binary lacks) and the version build.sh stamps, and its config must be upstream's (entrypoint, user)
with the patch label. verify/test_kyverno_breaker_fix.py (offline) holds the Application, the pins, build.sh and the
workflow together.

Install: none beyond a go on PATH. verify/fetch-e2e-tools.sh fetches crane from e2e-tools.lock, and run-e2e.sh and
run-e2e-tools.sh point $CRANE at it. Run by hand: CRANE=verify/.tools/bin/crane python3 verify/test_kyverno_build_digest.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD_SH = REPO / "images/kyverno/build.sh"
BUILD = BUILD_SH.read_text(encoding="utf-8")
LOCK = (REPO / "images.lock").read_text(encoding="utf-8")
FIX = b"pkg/breaker.(*counter).resync"
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
    print("build.sh builds both patched Kyverno images at the digests images.lock pins, each with the fix in its binary.")


def const(name: str) -> str | None:
    m = re.search(rf'^{name}="([^"]*)"$', BUILD, re.M)
    return m.group(1) if m else None


def pinned(ref: str) -> str | None:
    m = re.search(rf"^{re.escape(ref)}@(sha256:[0-9a-f]{{64}}) ", LOCK, re.M)
    return m.group(1) if m else None


spec = importlib.util.spec_from_file_location("ghcr_version_tag", REPO / "scripts/ghcr_version_tag.py")
gvt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gvt)

crane = os.environ.get("CRANE", "")
if not crane or not os.access(crane, os.X_OK):
    print(f"CRANE must name the pinned crane (verify/fetch-e2e-tools.sh puts it at verify/.tools/bin/crane); got {crane!r}")
    raise SystemExit(1)
if not shutil.which("go"):
    print("no go on PATH: build.sh needs any go 1.21 or later, which fetches the toolchain it pins")
    raise SystemExit(1)

print("== build.sh names both images and images.lock pins them ==")
images = {"kyverno": const("KYVERNO_REF"), "reports-controller": const("REPORTS_REF")}
bases = {"kyverno": const("KYVERNO_BASE"), "reports-controller": const("REPORTS_BASE")}
version = const("BUILD_VERSION")
for name, ref in images.items():
    check(f"build.sh names the {name} tag in ghcr.io/peopleforrester/watch-it-burn",
          bool(ref) and ref.startswith("ghcr.io/peopleforrester/watch-it-burn:"))
    check(f"images.lock pins {ref} by digest", bool(ref) and pinned(ref) is not None)
check("build.sh stamps a version", bool(version))
if failures:
    finish()
want = {name: pinned(ref) for name, ref in images.items()}

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    addr = f"127.0.0.1:{port}"
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
        print("== build.sh, unchanged, into the loopback registry ==")
        check("build.sh refuses an address that is not loopback, before building",
              subprocess.run(["bash", str(BUILD_SH), "ghcr.io"], env={**os.environ, "CRANE": crane},
                             capture_output=True, text=True, timeout=60).returncode == 1)
        started = time.monotonic()
        r = subprocess.run(["bash", str(BUILD_SH), addr], env={**os.environ, "CRANE": crane},
                           capture_output=True, text=True, timeout=2400)
        print(f"        build.sh took {time.monotonic() - started:.0f}s")
        check("build.sh builds both images, upstream's recovery tests passing first (exit 0)", r.returncode == 0,
              (r.stdout + r.stderr)[-1200:])
        check("upstream's recovery tests ran and passed on the patched tree",
              "ok  \tgithub.com/kyverno/kyverno/pkg/breaker" in r.stdout
              and "ok  \tgithub.com/kyverno/kyverno/cmd/kyverno/watch" in r.stdout, r.stdout[-600:])
        for name, ref in images.items():
            here = ref.replace("ghcr.io/", f"{addr}/", 1)
            d = subprocess.run([crane, "--insecure", "digest", here], capture_output=True, text=True, timeout=60)
            got = d.stdout.strip()
            check(f"{name}: build.sh's digest is images.lock's {str(want[name])[:19]}...", got == want[name],
                  f"built {got or d.stderr.strip()[:200]}: re-pin it in images.lock and gitops/bootstrap/apps/kyverno.yaml")
            try:
                read = gvt.crane_digest(here)
            except gvt.Refused as err:
                read = str(err)
            check(f"{name}: ghcr_version_tag.py's crane: build reads the same digest push-kyverno.yml compares to the pin",
                  read == got, read)
            c = subprocess.run([crane, "--insecure", "config", here], capture_output=True, text=True, timeout=60)
            b = subprocess.run([crane, "config", "--platform", "linux/amd64", bases[name]], capture_output=True,
                               text=True, timeout=120)
            try:
                cfg, base_cfg = json.loads(c.stdout)["config"], json.loads(b.stdout)["config"]
            except (json.JSONDecodeError, KeyError):
                cfg, base_cfg = {}, {"Entrypoint": "unread"}
            check(f"{name}: the entrypoint, user and environment are upstream's",
                  all(cfg.get(k) == base_cfg.get(k) for k in ("Entrypoint", "User", "Env")),
                  f"{cfg.get('Entrypoint')} {cfg.get('User')} vs {base_cfg.get('Entrypoint')} {base_cfg.get('User')}")
            check(f"{name}: the image is labelled with the upstream PR it carries",
                  (cfg.get("Labels") or {}).get("io.github.peopleforrester.watch-it-burn.kyverno-patch")
                  == "https://github.com/kyverno/kyverno/pull/17085", str(cfg.get("Labels")))
            out = tmp / f"{name}.tar"
            e = subprocess.run([crane, "--insecure", "export", here, str(out)], capture_output=True, text=True,
                               timeout=600)
            binary = b""
            if e.returncode == 0:
                with tarfile.open(out) as tar:
                    for m in tar.getmembers():
                        if m.isfile() and m.name.lstrip("./") == f"ko-app/{name}":
                            binary = tar.extractfile(m).read()
            out.unlink(missing_ok=True)
            check(f"{name}: /ko-app/{name} is in the image", bool(binary), e.stderr.strip()[:200])
            check(f"{name}: the binary carries #17085's (*counter).resync", FIX in binary)
            check(f"{name}: the binary reports {version}", version.encode() in binary)
    finally:
        reg.terminate()
        reg.wait(timeout=10)
        log.close()

finish()
