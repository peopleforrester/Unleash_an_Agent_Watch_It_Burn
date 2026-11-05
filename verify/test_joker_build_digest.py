# ABOUTME: Rebuilds both Jokers with images/villains/build.sh into a throwaway local registry (#775) and holds each digest
# ABOUTME: to images.lock: the workshop's festival-ops Joker as published, and the breakout's internal-registry Joker.
# SUITE: e2e (needs the network: ghcr.io serves build.sh's pinned busybox base, lab-platform's copy)
# E2E TIER: tools (no cluster, no AWS: the pinned crane from e2e-tools.lock, its own registry on loopback)
"""Why (#775). Challenge 3 at KubeCon asks for registry.burritobot.co/burritobot/maintenance-shell, which the internal
registry (gitops/internal-registry/) copies from ghcr.io by digest at every start. Its page differs from the workshop
Joker's: it says admission passed it, because it came from a registry the cluster trusts. That digest was pinned
before its first push, so this test is what says the pin is right: build.sh, run unchanged, has to build exactly the
digests images.lock pins, and the seed has to copy that one.

The build is reproducible: no timestamp goes into either image, the layer's tar sets owner, mtime, order and modes,
and crane 0.22.1 compresses it the same way each time. On 2026-11-03 the rebuild gave the festival-ops Joker's
published digest, d8dae795, byte for byte, under umask 002 and 022. So after a page change this test names the pin
that moves; re-pin it in images.lock (and the internal registry's seed), and push-jokers.yml, on the push to staging
that carries the new pin, pushes the build to the tag only when its digest is that pin.

How. crane's own registry serves on a free loopback port. images/villains/build-loopback.sh runs build.sh with CRANE
set to a wrapper that sends its ghcr.io/peopleforrester/festival-ops/ references to that registry, so nothing is
pushed anywhere else. .github/workflows/push-jokers.yml builds with the same script before it hands each tag to
scripts/ghcr_version_tag.py, so the build this test holds to the pins is the one the workflow pushes. Then each tag's
digest is read back and its top layer is opened: the internal Joker carries joker-web-internal's page and joker-web's
start.sh, and the workshop Joker joker-web's own.

Install: none. verify/fetch-e2e-tools.sh fetches crane from e2e-tools.lock, and run-e2e.sh and run-e2e-tools.sh point
$CRANE at it. Run by hand: CRANE=verify/.tools/bin/crane python3 verify/test_joker_build_digest.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import pathlib
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
VILLAINS = REPO / "images/villains"
BUILD = (VILLAINS / "build.sh").read_text(encoding="utf-8")
LOCK = (REPO / "images.lock").read_text(encoding="utf-8")
SEED = (REPO / "gitops/internal-registry/internal-registry.yaml").read_text(encoding="utf-8")
PREFIX = "ghcr.io/peopleforrester/festival-ops/"
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
    print("build.sh builds both Jokers at the digests images.lock pins.")


def pinned(ref: str) -> str | None:
    """images.lock's digest for a tag reference: the row whose reference is <ref>@sha256:..."""
    m = re.search(rf"^{re.escape(ref)}@(sha256:[0-9a-f]{{64}}) ", LOCK, re.M)
    return m.group(1) if m else None


spec = importlib.util.spec_from_file_location("ghcr_version_tag", REPO / "scripts/ghcr_version_tag.py")
gvt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gvt)

crane = os.environ.get("CRANE", "")
if not crane or not os.access(crane, os.X_OK):
    print(f"CRANE must name the pinned crane (verify/fetch-e2e-tools.sh puts it at verify/.tools/bin/crane); got {crane!r}")
    raise SystemExit(1)

print("== build.sh names both Jokers ==")
joker = re.search(r'^JOKER_REF="([^"]+)"$', BUILD, re.M)
internal = re.search(r'^JOKER_INTERNAL_REF="\$\{JOKER_REF\}(-[a-z0-9.-]+)"$', BUILD, re.M)
check("JOKER_REF is a festival-ops tag", bool(joker) and joker.group(1).startswith(PREFIX))
check("JOKER_INTERNAL_REF is a tag beside it, in the same public package", bool(internal))
if not (joker and internal):
    finish()
refs = {"joker": joker.group(1), "joker-internal": joker.group(1) + internal.group(1)}
want = {name: pinned(ref) for name, ref in refs.items()}
for name, ref in refs.items():
    check(f"images.lock pins {ref} by digest", want[name] is not None)
seed = [line.split() for line in SEED.split("images.txt: |", 1)[-1].split("seed.sh: |", 1)[0].splitlines()
        if line.strip() and not line.strip().startswith("#")]
check("the internal registry seeds burritobot/maintenance-shell from the internal Joker, at its pinned digest",
      [refs["joker-internal"] + "@" + str(want["joker-internal"]), "burritobot/maintenance-shell:busybox-1.38.0"] in seed,
      str(seed))

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    local = f"127.0.0.1:{port}/festival-ops/"
    log = (tmp / "registry.log").open("w")
    reg = subprocess.Popen([crane, "registry", "serve", "--address", f"127.0.0.1:{port}"], stdout=log, stderr=log)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/v2/", timeout=2).read()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        else:
            check(f"crane's registry answers on 127.0.0.1:{port}", False, (tmp / "registry.log").read_text()[-300:])
            finish()
        print("== build.sh, unchanged, into the loopback registry, through build-loopback.sh ==")
        r = subprocess.run(["bash", str(VILLAINS / "build-loopback.sh"), f"127.0.0.1:{port}"],
                           env={**os.environ, "CRANE": crane}, capture_output=True, text=True, timeout=600)
        check("build-loopback.sh builds both Jokers (exit 0)", r.returncode == 0, (r.stdout + r.stderr)[-600:])
        check("build-loopback.sh refuses an address that is not loopback, before building",
              subprocess.run(["bash", str(VILLAINS / "build-loopback.sh"), "ghcr.io"], env={**os.environ, "CRANE": crane},
                             capture_output=True, text=True, timeout=60).returncode == 1)
        for name, ref in refs.items():
            here = ref.replace(PREFIX, local)
            d = subprocess.run([crane, "--insecure", "digest", here], capture_output=True, text=True, timeout=60)
            got = d.stdout.strip()
            check(f"{name}: build.sh's digest is images.lock's {str(want[name])[:19]}...", got == want[name],
                  f"built {got or d.stderr.strip()[:200]}: re-pin it, and push-jokers.yml pushes it on staging")
            try:
                read = gvt.crane_digest(here)
            except gvt.Refused as err:
                read = str(err)
            check(f"{name}: ghcr_version_tag.py's crane: build reads the same digest push-jokers.yml compares to the pin",
                  read == got, read)
            out = tmp / f"{name}.tar"
            e = subprocess.run([crane, "--insecure", "export", here, str(out)], capture_output=True, text=True,
                               timeout=120)
            files = {}
            if e.returncode == 0:
                with tarfile.open(out) as tar:
                    for m in tar.getmembers():
                        if m.isfile() and m.name.lstrip("./").startswith("villain/"):
                            files[m.name.lstrip("./")] = tar.extractfile(m).read()
            page = (VILLAINS / ("joker-web-internal" if name == "joker-internal" else "joker-web") / "www/index.html")
            check(f"{name}: /villain/www/index.html is {page.relative_to(REPO)}",
                  files.get("villain/www/index.html") == page.read_bytes(), e.stderr.strip()[:200])
            check(f"{name}: /villain/start.sh is images/villains/joker-web/start.sh",
                  files.get("villain/start.sh") == (VILLAINS / "joker-web/start.sh").read_bytes())
    finally:
        reg.terminate()
        reg.wait(timeout=10)
        log.close()

print("== the two pages differ only where the breakout's story does ==")
work = (VILLAINS / "joker-web/www/index.html").read_text(encoding="utf-8")
brk = (VILLAINS / "joker-web-internal/www/index.html").read_text(encoding="utf-8")
check("the workshop page still says an allow-list at admission would have stopped it",
      "registry allow-list at admission" in work and "image nobody vetted" in work)
check("the breakout page says it came from registry.burritobot.co, which admission trusts",
      "registry.burritobot.co" in brk and "nobody vetted" not in brk and "allow-list" not in brk)
check("the breakout page names Challenge 3's two fixes: the input classifier and a bot that cannot create Deployments",
      "input classifier" in brk and "cannot create Deployments" in brk)
check("the persona stays: HA HA HA and the same title", "HA HA HA!" in brk
      and re.search(r"<title>(.*?)</title>", brk).group(1) == re.search(r"<title>(.*?)</title>", work).group(1))

finish()
