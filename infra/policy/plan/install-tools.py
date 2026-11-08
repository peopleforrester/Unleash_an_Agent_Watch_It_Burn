#!/usr/bin/env python3
# ABOUTME: Installs the pinned plan-policy toolchain from tools.yaml into one directory, verifying every download.
# ABOUTME: Usage: python3 install-tools.py <dir>; then put <dir>/bin on PATH for check-plan.py and plan-fleet.py.
#
# Nothing is installed system-wide and nothing is taken from PATH: the point of a pinned toolchain is that
# the check means the same thing on a laptop, on the netcup runner and in the e2e suite. A download whose
# sha256 does not match the pin is a hard failure, never a retry against a different URL.
#
# Each binary's archive comes from the host artifact cache by its pinned sha256 (verify/artifact_cache.py, #1117):
# WIB_ARTIFACT_CACHE in CI (verify/ci-artifact-cache.sh, #1123), else the per-user default. A hit is hashed again
# before use and a miss is fetched once and checked before it is kept, so a second install on the host downloads none.
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent.parent / "verify"))
import artifact_cache  # noqa: E402


def fetch(url: str, sha256: str) -> bytes:
    try:
        path = artifact_cache.get_retrying(sha256, url)
    except artifact_cache.ArtifactCacheError as e:
        sys.exit(f"ARTIFACT CACHE FAILED for {url}: {e}")
    data = path.read_bytes()
    # get_retrying() has checked the file; this check is on the bytes actually unpacked, in case it changed since.
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f"CHECKSUM MISMATCH for {url}\n  pinned {sha256}\n  got    {got}")
    return data


def extract(data: bytes, url: str, member: str, dest: Path) -> None:
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            payload = zf.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            fh = tf.extractfile(member)
            if fh is None:
                sys.exit(f"{url} has no regular file named {member}")
            payload = fh.read()
    # Written by name, never extracted by path: an archive cannot place a file anywhere but dest.
    dest.write_bytes(payload)
    dest.chmod(0o755)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: install-tools.py <install-dir>")
    root = Path(sys.argv[1]).resolve()
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    tools = yaml.safe_load((HERE / "tools.yaml").read_text())

    for name, spec in tools["binaries"].items():
        dest = bindir / name
        print(f"{name} {spec['version']}: {spec['url']}")
        extract(fetch(spec["url"], spec["sha256"]), spec["url"], spec["member"], dest)

    for name, spec in tools["python"].items():
        venv = root / "venvs" / name
        print(f"{name} {spec['version']}: pip install {spec['package']}=={spec['version']} into {venv}")
        subprocess.run([sys.executable, "-m", "venv", "--clear", str(venv)], check=True)
        subprocess.run([str(venv / "bin" / "pip"), "install", "--quiet", f"{spec['package']}=={spec['version']}"],
                       check=True)
        link = bindir / spec["command"]
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(venv / "bin" / spec["command"])

    print(f"\ninstalled into {bindir}; run the checks with PATH=\"{bindir}:$PATH\"")


if __name__ == "__main__":
    main()
