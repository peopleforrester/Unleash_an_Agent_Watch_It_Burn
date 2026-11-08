# ABOUTME: Offline check of the wib-e2e-tools image (#1188): its Containerfile pins exactly e2e-tools.lock's tools and
# ABOUTME: versions, its tag moves with the lock, its installer refuses a wrong SHA-256, and its launcher never downloads.
"""Offline: no network, no image and no container. The real build is .github/workflows/build-e2e-tools-image.yml and
`bash verify/e2e-image.sh build`; the real run is `bash verify/e2e-image.sh run`.

#1188 replaces the tier's per-run tool downloads with one image, ghcr.io/peopleforrester/wib-e2e-tools, built from
verify/e2e-tools.lock. What this holds:
  1. verify/e2e-image/Containerfile's `install.sh tool` lines are the lock's rows, field for field and in order, and
     verify/e2e_image.py's check says so; a copy with a tool dropped, added, moved, or a version, sum, URL or member
     changed fails it, naming the tool.
  2. The tag is the first 16 hex of the lock's SHA-256, then 8 of the other build inputs': a changed lock changes the
     first part, a changed build file only the second. .dockerignore lets the build read nothing the tag does not hash.
  3. verify/e2e-image/install.sh installs a file whose SHA-256 is the pin's and records it in tools.txt, and refuses
     one whose sum is not, installing nothing. Its fetches are of file:// URLs this test writes.
  4. tools.txt is held to the lock the same way inside the image (`e2e_image.py matches`), and run-e2e-tools.sh runs
     that check first in the image and fails on a tools.txt that is not the lock's, and fetches nothing there.
  5. verify/e2e-image.sh run, with a podman stand-in: a host that holds the tag starts it with --pull=never and pulls
     nothing; a host that lacks it pulls once; a host where the pull fails exits 1 naming the image and
     `bash verify/e2e-image.sh build`, and runs no container, no curl and no fetch-e2e-tools.sh.
  6. The workflow builds on a GitHub-hosted runner, only when the lock or a build input changes, checks the pins
     first, and pushes through scripts/ghcr_version_tag.py.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import artifact_cache  # noqa: E402
import e2e_image  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


LOCK_TEXT = e2e_image.LOCK.read_text(encoding="utf-8")
CF_TEXT = e2e_image.CONTAINERFILE.read_text(encoding="utf-8")
LOCK = e2e_image.lock_rows(LOCK_TEXT)

print("== 1. the Containerfile pins exactly the lock's tools and versions ==")
built = e2e_image.containerfile_rows(CF_TEXT)
check("the lock names the eleven tools #1188 lists",
      sorted(r[0] for r in LOCK) == sorted(["agentgateway", "caddy", "kyverno", "conftest", "terraform", "kubectl",
                                            "helm", "otelcol-contrib", "ttyd", "crane", "weaver"]),
      str([r[0] for r in LOCK]))
check("the Containerfile's tool lines are the lock's rows, in order", built == LOCK,
      "\n".join(e2e_image.pin_problems(LOCK_TEXT, CF_TEXT)))
for name, version, *_ in LOCK:
    check(f"the Containerfile installs {name} {version}",
          any(r[0] == name and r[1] == version for r in built))
r = subprocess.run([sys.executable, str(HERE / "e2e_image.py"), "check"], capture_output=True, text=True)
check("`e2e_image.py check` passes on the repo", r.returncode == 0, r.stdout + r.stderr)

first = LOCK[0]
line0 = f"RUN /usr/local/lib/wib-e2e/install.sh tool {' '.join(first)}"
if line0 not in CF_TEXT:
    print(f"FAIL: the anchor {line0!r} is not in {e2e_image.CONTAINERFILE}; the mutations below need it")
    sys.exit(1)
second = LOCK[1]
line1 = f"RUN /usr/local/lib/wib-e2e/install.sh tool {' '.join(second)}"
MUTATIONS = {
    "a tool dropped": (CF_TEXT.replace(line0 + "\n", ""), first[0]),
    "a tool the lock lacks added": (CF_TEXT.replace(line0, line0 + "\nRUN /usr/local/lib/wib-e2e/install.sh tool "
                                                   "jq 1.7 " + "0" * 64 + " https://example.invalid/jq -"), "jq"),
    "a version changed": (CF_TEXT.replace(line0, line0.replace(f" {first[1]} ", " v0.0.1 ")), "v0.0.1"),
    "a SHA-256 changed": (CF_TEXT.replace(line0, line0.replace(first[2], "f" * 64)), "f" * 64),
    "a URL changed": (CF_TEXT.replace(line0, line0.replace(first[3], first[3] + ".bak")), ".bak"),
    "a member changed": (CF_TEXT.replace(line0, line0[: -len(first[4])] + "other-member"), "other-member"),
    "two tools swapped": (CF_TEXT.replace(line0 + "\n" + line1, line1 + "\n" + line0), "order"),
}
for label, (text, named) in MUTATIONS.items():
    problems = e2e_image.pin_problems(LOCK_TEXT, text)
    check(f"the check fails on a Containerfile with {label}, naming it",
          bool(problems) and any(named in p for p in problems), str(problems))

print("== 2. the tag is the lock's hash and the build's, and the build reads only what it hashes ==")
tag = e2e_image.tag()
lock_sha = hashlib.sha256(e2e_image.LOCK.read_bytes()).hexdigest()
check("the tag is <16 hex>-<8 hex>", re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{8}", tag) is not None, tag)
check("its first part is the lock's SHA-256", tag.startswith(lock_sha[:16] + "-"), f"{tag} vs {lock_sha}")
check("the reference is ghcr.io/peopleforrester/wib-e2e-tools:<tag>",
      e2e_image.ref() == f"ghcr.io/peopleforrester/wib-e2e-tools:{tag}")
inputs = {p.relative_to(HERE).as_posix() for p in e2e_image.build_inputs()}
check("the build inputs are e2e-image/, the three Python pin files and .dockerignore",
      inputs == {"e2e-image/Containerfile", "e2e-image/install.sh", "e2e-image/gh", "python.lock",
                 "package_cache.py", "artifact_cache.py", ".dockerignore"}, str(sorted(inputs)))
ignore = e2e_image.DOCKERIGNORE.read_text(encoding="utf-8")
check(".dockerignore lets in exactly those", e2e_image.dockerignore_problems(ignore) == [])
check(".dockerignore that also lets in .tools fails", e2e_image.dockerignore_problems(ignore + "!.tools/\n") != [])
copies = re.findall(r"^COPY (.+) \S+$", CF_TEXT, re.M)
copied = {src for line in copies for src in line.split()}
check("every file the Containerfile copies is a build input", copied and copied <= inputs, str(copied))

with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    shutil.copytree(e2e_image.IMAGE_DIR, t / "e2e-image")
    for f in (*e2e_image.CONTEXT_FILES, ".dockerignore", "e2e-tools.lock"):
        shutil.copy2(HERE / f, t / f)
    saved = (e2e_image.VERIFY, e2e_image.LOCK, e2e_image.IMAGE_DIR, e2e_image.DOCKERIGNORE)
    e2e_image.VERIFY, e2e_image.LOCK = t, t / "e2e-tools.lock"
    e2e_image.IMAGE_DIR, e2e_image.DOCKERIGNORE = t / "e2e-image", t / ".dockerignore"
    try:
        check("a copy of the inputs gives the same tag", e2e_image.tag() == tag, e2e_image.tag())
        (t / "e2e-tools.lock").write_text(LOCK_TEXT + "# a new line\n", encoding="utf-8")
        new = e2e_image.tag()
        check("a changed lock changes the tag's first part", new.split("-")[0] != tag.split("-")[0], new)
        (t / "e2e-tools.lock").write_text(LOCK_TEXT, encoding="utf-8")
        (t / "e2e-image" / "Containerfile").write_text(CF_TEXT + "# a new line\n", encoding="utf-8")
        new = e2e_image.tag()
        check("a changed Containerfile changes only the tag's second part",
              new.split("-")[0] == tag.split("-")[0] and new != tag, new)
        (t / "e2e-image" / "Containerfile").write_text(CF_TEXT, encoding="utf-8")
        (t / "python.lock").write_text((HERE / "python.lock").read_text() + "# x\n", encoding="utf-8")
        check("a changed python.lock changes the tag", e2e_image.tag() != tag)
    finally:
        e2e_image.VERIFY, e2e_image.LOCK, e2e_image.IMAGE_DIR, e2e_image.DOCKERIGNORE = saved

print("== 3. install.sh installs only a file whose SHA-256 is the pin ==")
INSTALL = HERE / "e2e-image" / "install.sh"
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    payload = t / "fake-tool"
    payload.write_bytes(b"#!/bin/sh\necho fake\n")
    good = hashlib.sha256(payload.read_bytes()).hexdigest()
    env = {**os.environ, "WIB_E2E_TOOLS": str(t / "tools"), "TMPDIR": str(t)}
    r = subprocess.run(["bash", str(INSTALL), "tool", "fake", "v1", good, payload.as_uri(), "-"],
                       capture_output=True, text=True, env=env)
    installed = t / "tools" / "bin" / "fake"
    check("a file whose sum is the pin is installed, executable", r.returncode == 0 and installed.is_file()
          and os.stat(installed).st_mode & stat.S_IXUSR, r.stdout + r.stderr)
    check("and tools.txt records its name, version and sum",
          (t / "tools" / "tools.txt").read_text() == f"fake v1 {good}\n")
    r = subprocess.run(["bash", str(INSTALL), "tool", "other", "v1", "a" * 64, payload.as_uri(), "-"],
                       capture_output=True, text=True, env=env)
    check("a file whose sum is not the pin fails the build, naming both sums",
          r.returncode != 0 and good in r.stderr and "a" * 64 in r.stderr, r.stderr)
    check("and nothing is installed or recorded for it", not (t / "tools" / "bin" / "other").exists()
          and "other" not in (t / "tools" / "tools.txt").read_text())
    r = subprocess.run(["bash", str(INSTALL), "tool", "short", "v1", "abc", payload.as_uri(), "-"],
                       capture_output=True, text=True, env=env)
    check("a pin that is not a SHA-256 fails", r.returncode != 0 and "not a SHA-256" in r.stderr, r.stderr)

print("== 4. inside the image, tools.txt must be the lock's, and nothing is fetched ==")
TOOLS_TXT = "".join(f"{n} {v} {s}\n" for n, v, s, *_ in LOCK)
check("the lock's own rows match", e2e_image.tools_txt_problems(LOCK_TEXT, TOOLS_TXT) == [])
check("a tools.txt with another version does not",
      e2e_image.tools_txt_problems(LOCK_TEXT, TOOLS_TXT.replace(f" {first[1]} ", " v0.0.1 ")) != [])
check("a tools.txt missing a tool does not",
      e2e_image.tools_txt_problems(LOCK_TEXT, "".join(TOOLS_TXT.splitlines(True)[1:])) != [])
runner = (HERE / "run-e2e-tools.sh").read_text(encoding="utf-8")
check("run-e2e-tools.sh fetches only outside the image",
      re.search(r'in_image}" -eq 0 \]\] && ! bash "\$\{SCRIPT_DIR\}/fetch-e2e-tools\.sh"', runner) is not None)
check("and runs the image's tools from WIB_E2E_TOOLS", 'TOOLS_BIN="${WIB_E2E_TOOLS}/bin"' in runner)
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    (t / "tools.txt").write_text(TOOLS_TXT.replace(f" {first[1]} ", " v0.0.1 "), encoding="utf-8")
    fakebin = t / "bin"
    fakebin.mkdir()
    log = t / "calls.log"
    for tool in ("curl", "wget"):
        (fakebin / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit 1\n')
        (fakebin / tool).chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "HECATON_BASE_SHA"}
    env.update(WIB_E2E_TOOLS=str(t), PATH=f"{fakebin}:{os.environ['PATH']}")
    r = subprocess.run(["bash", str(HERE / "run-e2e-tools.sh")], capture_output=True, text=True, env=env,
                       timeout=120)
    check("run-e2e-tools.sh in an image of another lock exits 1 before any check, naming the mismatch",
          r.returncode == 1 and "v0.0.1" in r.stderr and "is not e2e-tools.lock's" in r.stderr
          and "checks ran" not in r.stdout, (r.stdout + r.stderr)[-800:])
    check("and calls no curl or wget", not log.exists(), log.read_text() if log.exists() else "")

print("== 5. e2e-image.sh run: present is used, absent is pulled once, unpullable fails naming the image ==")
REF = e2e_image.ref()


def launcher(state: str) -> tuple[subprocess.CompletedProcess, str]:
    """Run `e2e-image.sh run` with a podman stand-in whose image is present, pullable or neither."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        fakebin = t / "bin"
        fakebin.mkdir()
        log = t / "calls.log"
        podman = f"""#!/bin/sh
echo "podman $*" >> "{log}"
case "$1" in
  image) [ "{state}" = present ] && exit 0; exit 1 ;;
  pull) [ "{state}" = pullable ] && exit 0; echo "Error: {REF}: manifest unknown" >&2; exit 125 ;;
  run) exit 0 ;;
esac
exit 3
"""
        stubs = {"podman": podman, "gh": "#!/bin/sh\nexit 0\n",
                 "curl": f'#!/bin/sh\necho "curl $*" >> "{log}"\nexit 1\n',
                 "wget": f'#!/bin/sh\necho "wget $*" >> "{log}"\nexit 1\n'}
        for name, body in stubs.items():
            (fakebin / name).write_text(body)
            (fakebin / name).chmod(0o755)
        cache = artifact_cache.scratch_dir("e2e-image-test-")
        env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}",
               "WIB_ARTIFACT_CACHE": str(cache), "HECATON_TOOLS_CACHE": ""}
        try:
            r = subprocess.run(["bash", str(HERE / "e2e-image.sh"), "run"], capture_output=True, text=True, env=env,
                               timeout=120)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        return r, (log.read_text() if log.exists() else "")


r, calls = launcher("present")
runs = [ln for ln in calls.splitlines() if ln.startswith("podman run ")]
check("an image on the host is run, and nothing is pulled", r.returncode == 0 and len(runs) == 1
      and "podman pull" not in calls, calls + r.stderr)
check("it is started with --pull=never, under the lock's tag", bool(runs) and "--pull=never" in runs[0]
      and f" {REF} " in runs[0], runs[0] if runs else calls)
check("the container runs run-e2e-tools.sh in this checkout",
      bool(runs) and f"-w {REPO} " in runs[0] and f"-v {REPO}:{REPO} " in runs[0]
      and "bash verify/run-e2e-tools.sh" in runs[0], runs[0] if runs else "")
check("with the host's gh reached through the relay socket, and no AWS or KUBECONFIG passed",
      bool(runs) and ":/run/wib-gh " in runs[0] and "AWS_" not in runs[0] and "KUBECONFIG" not in runs[0],
      runs[0] if runs else "")
check("rootless podman keeps the user's own ids", bool(runs) and "--userns=keep-id" in runs[0])
r, calls = launcher("pullable")
check("an image the host lacks is pulled once, then run", r.returncode == 0
      and calls.count("podman pull ") == 1 and calls.count("podman run ") == 1, calls + r.stderr)
r, calls = launcher("absent")
check("an image that cannot be pulled fails, naming the image and how to build it",
      r.returncode == 1 and REF in r.stderr and "bash verify/e2e-image.sh build" in r.stderr
      and "not a skip" in r.stderr, r.stderr)
check("and no container runs, and nothing is downloaded instead",
      "podman run" not in calls and "curl" not in calls and "wget" not in calls, calls)
check("e2e-image.sh never runs fetch-e2e-tools.sh",
      "fetch-e2e-tools" not in (HERE / "e2e-image.sh").read_text(encoding="utf-8"))

print("== 6. the workflow builds and pushes only for a new lock or build ==")
wf_path = REPO / ".github/workflows/build-e2e-tools-image.yml"
wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
on = wf.get(True) or wf.get("on")
paths = set(on["push"]["paths"])
check("it runs on a push that changes the lock", "verify/e2e-tools.lock" in paths)
want_paths = {p.relative_to(REPO).as_posix() for p in e2e_image.build_inputs() if p.parent != e2e_image.IMAGE_DIR}
check("and on each other build input, and on nothing else but its own tooling",
      paths == {"verify/e2e-tools.lock", "verify/e2e-image/**", "verify/e2e_image.py", "verify/e2e-image.sh",
                *want_paths, "scripts/ghcr_version_tag.py", ".github/workflows/build-e2e-tools-image.yml"},
      str(sorted(paths)))
job = wf["jobs"]["build"]
runs_text = "\n".join(s.get("run", "") for s in job["steps"])
check("it builds on a GitHub-hosted runner", job["runs-on"] == "ubuntu-latest")
check("it checks the pins before it builds", runs_text.index("e2e_image.py check") < runs_text.index("e2e-image.sh build"))
check("it pushes through scripts/ghcr_version_tag.py, which never pushes over an existing tag",
      'python3 scripts/ghcr_version_tag.py "${REF}" "${REF}"' in runs_text and "docker push" not in runs_text)
check("it may write packages", wf["permissions"].get("packages") == "write")
check("the build labels the image with its tag, which ghcr_version_tag.py reads as its source",
      'io.github.peopleforrester.watch-it-burn.source-tree=${ref##*:}' in (HERE / "e2e-image.sh").read_text())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll e2e image checks passed.")
