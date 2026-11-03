# ABOUTME: Runs build-web-terminal.yml's push step with the real pinned crane against a registry on loopback (#815):
# ABOUTME: crane's own "no such tag" answer, and a moved tag put back on its pinned index at the same digest.
# SUITE: e2e (needs the pinned crane binary from e2e-tools.lock)
# E2E TIER: tools (no cluster, no AWS: the pinned crane from e2e-tools.lock, its own registry on loopback)
"""Why (#815). test_web_terminal_push_guard.py holds the push step's decisions with a stub crane. Two things a stub
cannot say are held here with the crane the workflow installs, go-containerregistry 0.22.1:

- that crane's answer for a tag that does not exist carries MANIFEST_UNKNOWN, the one answer the step treats as
  "push"; any other failure fails the job;
- that `crane tag <repo>@<pin> <tag>` puts the tag back on the pinned digest unchanged, for an OCI index like the
  pinned web terminal (sha256:68004fb5... is an index), not a re-encoded copy of it.

How. crane's registry serves on a free loopback port. Two small images and an index over one of them are written
into it with crane; the index stands in for the pinned build and the other image for a rebuild. The step's script,
taken out of the workflow file, runs with a crane on PATH that adds --insecure (loopback is plain HTTP) and a docker
whose push copies the "rebuild" under the tag, and with a scratch images.lock that pins the tag at the index.

Install: none. verify/fetch-e2e-tools.sh fetches crane, and run-e2e.sh and run-e2e-tools.sh point $CRANE at it.
Run by hand: CRANE=verify/.tools/bin/crane python3 verify/test_web_terminal_push_guard_registry.py
"""
from __future__ import annotations

import io
import os
import pathlib
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8"))
steps = {s.get("name", ""): s for s in WORKFLOW["jobs"]["build"]["steps"]}
SCRIPT = steps.get("Push, never over a tag that exists", {}).get("run", "")
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
    print("The push step, with the real crane, pushes only a missing tag and puts a moved tag back on its pin.")
    raise SystemExit(0)


crane = os.environ.get("CRANE", "")
if not crane or not os.access(crane, os.X_OK):
    print(f"CRANE must name the pinned crane (verify/fetch-e2e-tools.sh puts it at verify/.tools/bin/crane); got {crane!r}")
    raise SystemExit(1)
crane = os.path.abspath(crane)  # the wrappers below run from another directory
check("build-web-terminal.yml has a 'Push, never over a tag that exists' step", bool(SCRIPT))
if not SCRIPT:
    finish()


def layer(path: pathlib.Path, text: str) -> pathlib.Path:
    data = text.encode()
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("hello.txt")
        info.size, info.mtime = len(data), 0
        tar.addfile(info, io.BytesIO(data))
    return path


def c(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([crane, "--insecure", *args], capture_output=True, text=True, timeout=60)


with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    repo = f"127.0.0.1:{port}/peopleforrester/watch-it-burn"
    tag = f"{repo}:web-terminal-ttyd-1.7.7"
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

        print("== the stand-in images ==")
        a = c("append", "-f", str(layer(tmp / "a.tar", "pinned build\n")), "-t", f"{repo}:pinned-image")
        b = c("append", "-f", str(layer(tmp / "b.tar", "a rebuild\n")), "-t", f"{repo}:rebuild")
        i = c("index", "append", "-m", f"{repo}:pinned-image", "-t", f"{repo}:pinned")
        check("crane writes two images and an index over the first", 0 == a.returncode == b.returncode == i.returncode,
              (a.stderr + b.stderr + i.stderr)[-400:])
        pin = c("digest", f"{repo}:pinned").stdout.strip()
        rebuild = c("digest", f"{repo}:rebuild").stdout.strip()
        check("the pin is an OCI index", '"manifests"' in c("manifest", f"{repo}@{pin}").stdout)

        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "crane").write_text(f'#!/usr/bin/env bash\nexec {crane} --insecure "$@"\n')
        (bindir / "docker").write_text("#!/usr/bin/env bash\n"
                                       'echo "docker $*" >>"${CALLS}"\n'
                                       f'if [ "$1" = push ]; then exec {crane} --insecure copy {repo}:rebuild "$2"; fi\n')
        for f in bindir.iterdir():
            f.chmod(0o755)
        work = tmp / "work"
        work.mkdir()
        (work / "images.lock").write_text(f"{tag}@{pin} {pin} repo:x -\n")
        calls = tmp / "calls"

        def run() -> tuple[int, str, list[str]]:
            calls.write_text("")
            env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "TAG": tag, "CALLS": str(calls)}
            p = subprocess.run(["bash", "-e", "-c", SCRIPT], cwd=work, env=env, capture_output=True, text=True,
                               timeout=120)
            return p.returncode, p.stdout + p.stderr, calls.read_text().splitlines()

        print("== crane's answer for a tag that does not exist ==")
        miss = c("digest", tag)
        check("crane digest fails and says MANIFEST_UNKNOWN", miss.returncode != 0 and "MANIFEST_UNKNOWN" in miss.stderr,
              miss.stderr.strip()[-200:])

        print("== no such tag: the step pushes the build ==")
        rc, out, log_calls = run()
        check("exit 0", rc == 0, out[-400:])
        check("docker pushes the tag", f"docker push {tag}" in log_calls, str(log_calls))
        check("the tag serves the build", c("digest", tag).stdout.strip() == rebuild)

        print("== the tag moved off its pin: the step puts it back and pushes nothing ==")
        rc, out, log_calls = run()
        check("exit 0", rc == 0, out[-400:])
        check("no docker push", not [x for x in log_calls if x.startswith("docker push")], str(log_calls))
        check(f"the tag serves the pinned index {pin[:19]}... again", c("digest", tag).stdout.strip() == pin,
              c("digest", tag).stdout.strip())

        print("== the tag serves its pin: the step pushes nothing and moves nothing ==")
        rc, out, log_calls = run()
        check("exit 0", rc == 0, out[-400:])
        check("no docker push", not log_calls, str(log_calls))
        check("the tag still serves the pin", c("digest", tag).stdout.strip() == pin)
        check("and says it was not overwritten", "not overwritten" in out, out[-400:])
    finally:
        reg.terminate()
finish()
