#!/usr/bin/env python3
# ABOUTME: Runs verify/ci-uv.sh (#1331) beside a stub artifact-cache.sh: uv alone unpacked under RUNNER_TEMP, PATH and
# ABOUTME: UV_PYTHON_INSTALL_DIR written as setup-uv wrote them, and every way it can go wrong fails, writing nothing. Offline.
"""Offline.

#1331: both verify-suites jobs failed in "Set up job" on staging 44f3939c (Actions run 42966599043) and d2ebbd3e
(42968258309). The runner downloads every action again for every job, and astral-sh/setup-uv's archive timed out three
times on Tanjiro's link, before any step could run. verify/ci-uv.sh replaces the action: it reads uv's release
archive from the host artifact cache by its pinned SHA-256 and puts uv on the job's PATH.

The script runs here from a copy in a throwaway directory, beside a stub artifact-cache.sh that logs its arguments and
prints the path of an archive the test builds, so nothing is fetched and the real cache is never touched. The stub's
log shows the script asks the cache for the SHA-256 and URL its own UV_SHA256 and UV_URL name. A run that passes
leaves uv alone under $RUNNER_TEMP/uv-<version>, appends to GITHUB_PATH the three directories setup-uv added on a
self-hosted runner, in its order, and writes UV_PYTHON_INSTALL_DIR to GITHUB_ENV (the runner's own value when it has
one). Each failure (no cache root, no GITHUB_PATH, GITHUB_ENV or RUNNER_TEMP, a cache that fails or names no file, an
archive without uv, a uv that fails or reports another version, 0.13.70 included) exits 1 with CI UV FAILED and
leaves GITHUB_PATH and GITHUB_ENV as they were.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "verify" / "ci-uv.sh"
MEMBER_DIR = "uv-x86_64-unknown-linux-gnu"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def pinned(name: str, text: str) -> str:
    m = re.search(rf'^{name}="([^"]+)"$', text, re.M)
    if not m:
        print(f"FAIL: {SCRIPT.relative_to(REPO)} has no {name}=\"...\" line to read the pin from", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


text = SCRIPT.read_text(encoding="utf-8")
VERSION = pinned("UV_VERSION", text)
SHA = pinned("UV_SHA256", text)
URL = pinned("UV_URL", text).replace("${UV_VERSION}", VERSION)

check("the pin is a version, a SHA-256 and an https URL that names that version",
      re.fullmatch(r"\d+\.\d+\.\d+", VERSION) is not None and re.fullmatch(r"[0-9a-f]{64}", SHA) is not None
      and URL.startswith("https://") and f"/{VERSION}/" in URL and URL.endswith(f"/{MEMBER_DIR}.tar.gz"),
      f"{VERSION} {SHA} {URL}")
check("the script fetches nothing itself: no curl or wget outside comments",
      not any(re.search(r"\b(curl|wget)\b", ln) for ln in text.splitlines() if not ln.lstrip().startswith("#")))

STUB_CACHE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_LOG}"
[[ "${STUB_MODE:-}" == fail ]] && { echo "ARTIFACT CACHE FAILED: stub" >&2; exit 1; }
printf '%s\\n' "${STUB_ARCHIVE}"
"""


def uv_stub(report: str, code: int = 0) -> bytes:
    return f"#!/bin/sh\necho '{report}'\nexit {code}\n".encode()


def archive(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        d =tarfile.TarInfo(MEMBER_DIR)
        d.type, d.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(d)
        for name, data in members.items():
            info = tarfile.TarInfo(f"{MEMBER_DIR}/{name}")
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    return path


# The release archive holds a second binary beside uv; the stub stands in for it, and it is never unpacked.
GOOD = {"uv": uv_stub(f"uv {VERSION} (x86_64-unknown-linux-gnu)"), "other-tool": uv_stub("other")}


def run(tmp: Path, members: dict[str, bytes] | None = None, *, drop: tuple[str, ...] = (), mode: str = "",
        archive_path: str | None = None, **extra: str) -> tuple[int, str, dict]:
    """Run a fresh copy of the script in tmp; return its exit code, its output and what it left."""
    vdir = tmp / "copy"
    vdir.mkdir(parents=True)
    shutil.copy2(SCRIPT, vdir / "ci-uv.sh")
    (vdir / "artifact-cache.sh").write_text(STUB_CACHE)
    rt, home = tmp / "runner-temp", tmp / "home"
    rt.mkdir()
    home.mkdir()
    gpath, genv, log = tmp / "github_path", tmp / "github_env", tmp / "stub.log"
    gpath.write_text("")
    genv.write_text("")
    arc = archive(tmp / "uv.tar.gz", GOOD if members is None else members)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "RUNNER_TEMP": str(rt),
           "GITHUB_PATH": str(gpath), "GITHUB_ENV": str(genv), "WIB_ARTIFACT_CACHE": str(tmp / "cache-root"),
           "STUB_LOG": str(log), "STUB_ARCHIVE": archive_path or str(arc), "STUB_MODE": mode}
    env.update(extra)
    for k in drop:
        env.pop(k, None)
    r = subprocess.run(["bash", str(vdir / "ci-uv.sh")], env=env, capture_output=True, text=True, timeout=60)
    left = {"path": gpath.read_text().splitlines(), "env": genv.read_text().splitlines(),
            "log": log.read_text().splitlines() if log.exists() else [], "rt": rt, "home": home}
    return r.returncode, r.stdout + r.stderr, left


def case(label: str, **kw) -> tuple[int, str, dict]:
    with tempfile.TemporaryDirectory(prefix="ci-uv-") as t:
        code, out, left = run(Path(t), **kw)
        left = {**left, "uv_ok": (left["rt"] / f"uv-{VERSION}" / "uv").is_file()
                and os.access(left["rt"] / f"uv-{VERSION}" / "uv", os.X_OK),
                "only_uv": sorted(p.name for p in (left["rt"] / f"uv-{VERSION}").iterdir())
                if (left["rt"] / f"uv-{VERSION}").is_dir() else [],
                "rt": str(left["rt"]), "home": str(left["home"])}
        return code, out, left


# A good run, on a runner with no UV_PYTHON_INSTALL_DIR or XDG variables of its own.
code, out, left = case("good", drop=("UV_PYTHON_INSTALL_DIR", "XDG_BIN_HOME", "XDG_DATA_HOME"))
home, rt = left["home"], left["rt"]
check("a good run exits 0", code == 0, out)
check("it asks the cache once, for the pinned SHA-256 and URL", left["log"] == [f"get {SHA} {URL}"], str(left["log"]))
check("uv alone is unpacked under RUNNER_TEMP/uv-<version>", left["uv_ok"] and left["only_uv"] == ["uv"],
      f"{left['only_uv']}\n{out}")
check("GITHUB_PATH gets ~/.local/bin, uv's directory and the Python directory, in setup-uv's order",
      left["path"] == [f"{home}/.local/bin", f"{rt}/uv-{VERSION}", f"{home}/.local/share/uv/python"], str(left["path"]))
check("GITHUB_ENV gets UV_PYTHON_INSTALL_DIR at setup-uv's default", left["env"] == [
    f"UV_PYTHON_INSTALL_DIR={home}/.local/share/uv/python"], str(left["env"]))
check("it says which uv it put where", f"uv {VERSION} (x86_64-unknown-linux-gnu) from " in out, out)

# The runner's own UV_PYTHON_INSTALL_DIR and XDG directories are kept, as setup-uv kept them.
code, out, left = case("runner dirs", UV_PYTHON_INSTALL_DIR="/srv/uv-python", XDG_BIN_HOME="/srv/bin")
check("a runner's UV_PYTHON_INSTALL_DIR and XDG_BIN_HOME are what it writes",
      code == 0 and left["path"][0] == "/srv/bin" and left["path"][2] == "/srv/uv-python"
      and left["env"] == ["UV_PYTHON_INSTALL_DIR=/srv/uv-python"], f"{code} {left['path']} {left['env']}\n{out}")
code, out, left = case("xdg data", drop=("XDG_BIN_HOME",), XDG_DATA_HOME="/srv/data")
check("with XDG_DATA_HOME and no XDG_BIN_HOME the tool directory is XDG_DATA_HOME/../bin",
      code == 0 and left["path"][0] == "/srv/data/../bin", f"{code} {left['path']}\n{out}")


def refused(label: str, needle: str, *, asks_cache: bool = True, **kw) -> None:
    code, out, left = case(label, **kw)
    check(f"{label}: exits 1, saying CI UV FAILED and {needle!r}",
          code == 1 and "CI UV FAILED" in out and needle in out, f"exit {code}: {out}")
    check(f"{label}: writes nothing to GITHUB_PATH or GITHUB_ENV", left["path"] == [] and left["env"] == [],
          f"{left['path']} {left['env']}")
    if not asks_cache:
        check(f"{label}: never asks the cache", left["log"] == [], str(left["log"]))


refused("no WIB_ARTIFACT_CACHE", "ci-artifact-cache.sh first", asks_cache=False, drop=("WIB_ARTIFACT_CACHE",))
refused("an empty WIB_ARTIFACT_CACHE", "ci-artifact-cache.sh first", asks_cache=False, WIB_ARTIFACT_CACHE="")
refused("no RUNNER_TEMP", "RUNNER_TEMP", asks_cache=False, drop=("RUNNER_TEMP",))
refused("a RUNNER_TEMP that is not a directory", "RUNNER_TEMP", asks_cache=False, RUNNER_TEMP="/nonexistent/rt")
refused("the cache failing", "could not serve uv", mode="fail")
refused("the cache naming no file", "which is not a file", archive_path="/nonexistent/uv.tar.gz")
refused("an archive without uv", "cannot unpack", members={"other-tool": GOOD["other-tool"]})
refused("a uv that reports 0.13.6", "not uv " + VERSION, members={**GOOD, "uv": uv_stub("uv 0.13.6 (x86)")})
refused(f"a uv that reports {VERSION}0", "not uv " + VERSION, members={**GOOD, "uv": uv_stub(f"uv {VERSION}0")})
refused("a uv that fails", "--version failed", members={**GOOD, "uv": uv_stub(f"uv {VERSION}", code=3)})

# GITHUB_PATH or GITHUB_ENV missing: the script cannot write to them, and stops before asking the cache.
for var in ("GITHUB_PATH", "GITHUB_ENV"):
    code, out, left = case(f"no {var}", drop=(var,))
    check(f"no {var}: exits 1 naming it, before asking the cache",
          code == 1 and f"CI UV FAILED: {var} is not set" in out and left["log"] == [], f"exit {code}: {out}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nci-uv.sh holds")
