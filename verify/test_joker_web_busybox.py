# ABOUTME: Runs C6's Joker entrypoint (#664) and its shell banner (#714) on the busybox the image is built from:
# ABOUTME: build.sh's pinned JOKER_BASE, lab-platform's ghcr.io copy, from the host artifact cache by digest. The page
# ABOUTME: must be served, the laugh logged, SIGTERM obeyed, and the banner shown to an interactive shell only.
# SUITE: e2e (needs the network on a cache miss: ghcr.io is asked for the pinned busybox)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it, #572)
#
# Why. build.sh needs a ghcr.io write credential, so a run cannot push the image and see it serve. What can be
# checked without them is everything the image adds to its base: start.sh, www/ and the shell banner, run by the
# base's own busybox (its sh, its httpd), exactly as the layer build.sh appends lays them out. The busybox is the digest
# build.sh pins, served by verify/image_cache.py as an OCI layout in the host artifact cache (#1122): every blob is
# checked against its sha256, on a hit as on a miss, ghcr.io is read only on a miss, and only bin/busybox is taken from
# the layer. Whether lab-platform's copy answers an anonymous pull is test_c6_joker_public.py's check, read live.
from __future__ import annotations

import io
import os
import pathlib
import pty
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import artifact_cache  # noqa: E402
import image_cache  # noqa: E402

BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
JOKER = REPO / "images/villains/joker-web"
PAGE = (JOKER / "www/index.html").read_bytes()
BANNER = REPO / "images/villains/villain-banner.sh"
LINE = "ACCESS GRANTED... just kidding, you deployed me. Why so trusting about admission control?"
LAUGH = "HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?"

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


def interactive_sh(bindir: pathlib.Path, env: dict[str, str]) -> str:
    """busybox sh with a pty as its stdin, stdout and stderr, as `kubectl exec -it <pod> -- sh` gives it: it types
    one command and exit, and returns everything the terminal showed."""
    master, slave = pty.openpty()
    proc = subprocess.Popen([str(bindir / "sh")], stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
                            start_new_session=True)
    os.close(slave)
    os.write(master, b"echo still-$((40+2))\nexit\n")
    out = b""
    deadline = time.time() + 10
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.5)
        if ready:
            try:
                chunk = os.read(master, 4096)
            except OSError:   # EIO: the shell exited and closed the pty
                break
            if not chunk:
                break
            out += chunk
        elif proc.poll() is not None:
            break
    os.close(master)
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    return out.decode("utf-8", "replace")


def run_banner_alone(bindir: pathlib.Path, root: pathlib.Path) -> str:
    """The banner file run on its own by the pinned busybox's sh, its output as text."""
    p = subprocess.run([str(bindir / "sh"), str(root / "etc/villain-banner.sh")], env={"PATH": str(bindir)},
                       capture_output=True, text=True, timeout=10)
    return p.stdout if p.returncode == 0 else f"rc={p.returncode} {p.stderr}"


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
m = re.search(r'^JOKER_BASE="ghcr\.io/(peopleforrester/lab-platform/mirror/library/busybox):[^@"]+@(sha256:[0-9a-f]{64})"',
              BUILD, re.M)
check("build.sh pins JOKER_BASE to lab-platform's ghcr.io busybox copy by digest", m is not None)
if not m:
    finish()
repo, base_digest = m.group(1), m.group(2)
ref = re.search(r'^JOKER_BASE="([^"]+)"', BUILD, re.M).group(1)
try:
    base = image_cache.image(image_cache.layout(ref))
    config = base["config"]
    blobs = [p.read_bytes() for p in base["layers"]]
except (artifact_cache.ArtifactCacheError, OSError, ValueError, KeyError) as e:
    check(f"the host artifact cache serves {repo}@{base_digest} as an OCI layout, every blob matching its digest", False,
          f"{type(e).__name__}: {e}")
    finish()
check(f"the host artifact cache serves {repo}@{base_digest[:19]}... as an OCI layout, every blob matching its digest",
      True)
check("the base is linux/amd64, the nodes' platform", (config.get("os"), config.get("architecture")) == ("linux", "amd64"),
      f"{config.get('os')}/{config.get('architecture')}")

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

    print("== the shell banner: an interactive sh greets, nothing else changes (#714) ==")
    # Laid out as build.sh's layer is: villain-banner.sh becomes /etc/villain-banner.sh, and the image sets ENV to it.
    # A run cannot write the host's /etc, so ENV names the same file under the scratch root; busybox reads whatever
    # path ENV holds.
    (work / "etc").mkdir()
    shutil.copyfile(BANNER, work / "etc/villain-banner.sh")
    image_env = {"PATH": str(bindir), "PORT": str(free_port()), "ENV": str(work / "etc/villain-banner.sh")}
    banner_lines = [ln for ln in run_banner_alone(bindir, work).splitlines() if ln.strip()]
    check("the banner prints Michael's line in the Joker's voice (2026-10-30)",
          any(LINE in ln for ln in banner_lines), str(banner_lines))
    check("and a few green lines first (ANSI 32), reset before the punchline",
          "\x1b[32m" in "\n".join(banner_lines) and "\x1b[0m" in "\n".join(banner_lines), str(banner_lines))
    # `kubectl exec -it <pod> -- sh`: a pty on stdin, stdout and stderr, so busybox sh is interactive and reads ENV.
    tty_out = interactive_sh(bindir, image_env)
    check("an interactive sh on a tty (kubectl exec -it) prints the banner", LINE in tty_out, tty_out[-300:])
    # The pty echoes what is typed, so the proof is the arithmetic's answer, which only a running shell prints.
    check("and is still a working shell after it", "still-42" in tty_out, tty_out[-300:])
    # `kubectl exec <pod> -- sh -c ...` and `kubectl exec -i <pod> -- sh` with no tty: not interactive, so no banner.
    p = subprocess.run([str(bindir / "sh"), "-c", "echo ok"], env=image_env, capture_output=True, text=True, timeout=10)
    check("a non-interactive exec prints only its command's output", (p.returncode, p.stdout, p.stderr) == (0, "ok\n", ""),
          f"rc={p.returncode} out={p.stdout[:200]!r} err={p.stderr[:200]!r}")
    p = subprocess.run([str(bindir / "sh")], input="echo ok\n", env=image_env, capture_output=True, text=True,
                       timeout=10)
    check("a sh fed from a pipe, no tty (kubectl exec -i), prints only its commands' output",
          (p.returncode, p.stdout, p.stderr) == (0, "ok\n", ""),
          f"rc={p.returncode} out={p.stdout[:200]!r} err={p.stderr[:200]!r}")
    # The CMD, with ENV set as the image sets it: the log is the laugh and the serving line, as before the banner.
    log = work / "log-env"
    with open(log, "w") as out:
        proc = subprocess.Popen([str(bindir / "sh"), str(villain / "start.sh")], env=image_env, stdout=out,
                                stderr=subprocess.STDOUT)
    try:
        time.sleep(0.5)
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    text = log.read_text()
    check("with ENV set, start.sh logs the laugh and nothing of the banner",
          LAUGH in text and LINE not in text and "\x1b[" not in text and rc == 0, f"rc={rc} {text[:300]!r}")
    if shutil.which("pkill"):
        subprocess.run(["pkill", "-f", f"httpd -f -p {image_env['PORT']} "], capture_output=True)

    print("== the banner is harmless: printf only ==")
    code = [ln.strip() for ln in BANNER.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    check("every line of villain-banner.sh is one printf of quoted text, so it cannot reach the network, write a file "
          "or end the shell", bool(code) and all(re.fullmatch(r"printf '[^']*'(?: '[^']*')?", ln) for ln in code),
          str([ln for ln in code if not re.fullmatch(r"printf '[^']*'(?: '[^']*')?", ln)]))
finally:
    shutil.rmtree(work, ignore_errors=True)

finish()
