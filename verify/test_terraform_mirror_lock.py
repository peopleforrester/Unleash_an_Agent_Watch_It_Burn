# ABOUTME: A provider zip in the host artifact cache that the lock does not match makes terraform init fail (#1119),
# ABOUTME: with no network: a made-up provider served from a scratch mirror through tf_plugin_cache, on the pinned terraform.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM; no network, no cluster, no AWS)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
# E2E SERIAL: terraform (run-e2e-tools.sh runs one such test at a time, #1005; its caches are scratch ones)
"""The provider mirror cannot pass a zip the lock does not vouch for, at either of its two checks.

tf_plugin_cache.py fills a filesystem mirror in the host artifact cache with each zip a lock pins, through
artifact_cache.get() by the zh: SHA-256 the lock records, and points terraform at it with a CLI config that installs
registry.terraform.io providers from nowhere else. Two checks stand between a changed zip and an init:

  - the fill: artifact_cache.get() hashes every hit, so a cache entry whose bytes changed fails tf_plugin_cache before
    terraform runs, as does a registry answer whose SHA-256 the lock does not record;
  - terraform itself: a zip from the mirror must match the lock's zh: (its bytes) or h1: (its contents) hashes.

Where a lock records an h1: hash, as every committed lock does, terraform passes a zip whose files match it whatever
its bytes: on the cluster lock's hashicorp/null, a zip with bytes appended after the archive installed cleanly
(decisions.md, #1119). The fill's byte check is the one that catches that, and it is held here too.

Nothing here touches the network or the host's cache: the provider is a made-up registry.terraform.io/wib-test/fake
1.0.0, its zip built here, the registry's answer and the download stubbed, the artifact root and plugin cache scratch
directories outside the checkout. The init never reaches the network either, since the config has no direct source for
registry.terraform.io, so this runs where the tools tier runs with no internet at all.

1. good: the fill fetches the zip once and links it into the mirror; init installs it from the mirror, lock unchanged.
2. contents changed: the cache entry is replaced by a zip whose provider binary differs. init, given the same config,
   fails on the lock's checksums and installs nothing; and the fill refuses the entry, naming both sums.
3. bytes appended: the fill refuses the entry, so the init it would feed never runs.
4. a registry answer whose SHA-256 the lock does not record is refused before anything is fetched.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import tf_plugin_cache as tpc  # noqa: E402

ADDRESS = "registry.terraform.io/wib-test/fake"
VERSION = "1.0.0"
PLAT = "linux_amd64"
URL = "https://releases.example.invalid/terraform-provider-fake_1.0.0_linux_amd64.zip"
INIT_TIMEOUT = 120
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def provider_zip(script: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo(f"terraform-provider-fake_v{VERSION}_x5", date_time=(2026, 11, 8, 0, 0, 0))
        info.external_attr = 0o755 << 16
        z.writestr(info, script)
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); e2e-tools.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)

GOOD = provider_zip(b"#!/bin/sh\necho fake provider\n")
CHANGED = provider_zip(b"#!/bin/sh\necho fake provider, changed\n")
LOCK = (f'provider "{ADDRESS}" {{\n  version = "{VERSION}"\n  hashes = [\n    "zh:{sha(GOOD)}",\n  ]\n}}\n').encode()
MAIN_TF = f'terraform {{\n  required_providers {{\n    fake = {{ source = "wib-test/fake", version = "{VERSION}" }}\n  }}\n}}\n'
LOCKED = tpc.parse_lock(LOCK.decode(), "the fake lock")
fetches: list[str] = []
lookups: list[str] = []


def meta(answer_sha: str):
    def fetch_meta(url: str) -> dict:
        lookups.append(url)
        return {"shasum": answer_sha, "download_url": URL, "filename": f"terraform-provider-fake_{VERSION}_{PLAT}.zip"}
    return fetch_meta


def serve(url: str, out) -> None:
    fetches.append(url)
    out.write(GOOD)


def no_network(*_a) -> dict:
    raise AssertionError("a warm fill went to the network")


def fill_error(root: pathlib.Path, fetch_meta=no_network) -> str:
    try:
        tpc.terraform_env({}, LOCKED, root=root, fetch_meta=fetch_meta, fetch=no_network, plat=PLAT)
    except tpc.CacheError as e:
        return str(e)
    return ""


def init(work: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess | None:
    work.mkdir()
    (work / "main.tf").write_text(MAIN_TF)
    (work / ".terraform.lock.hcl").write_bytes(LOCK)
    try:
        return subprocess.run([exe, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color"],
                              cwd=work, env=env, capture_output=True, text=True, timeout=INIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None


def said(r: subprocess.CompletedProcess | None) -> str:
    return "timed out" if r is None else (r.stdout + r.stderr)[-1500:]


base = {k: v for k, v in os.environ.items()
        if k not in ("TF_CLI_CONFIG_FILE", "TF_PLUGIN_CACHE_DIR", "TF_DATA_DIR",
                     "TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE")}
base.update({"TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"})

with tpc.scratch("tf-mirror-lock-") as td:
    tmp = pathlib.Path(td)
    root = tmp / "artifacts"
    entry = root / "sha256" / sha(GOOD)

    print("== good: the fill fetches the zip once into the artifact cache, and init installs it from the mirror ==")
    env = tpc.terraform_env(base, LOCKED, root=root, fetch_meta=meta(sha(GOOD)), fetch=serve, plat=PLAT)
    link = tpc.mirror_dir(root) / "registry.terraform.io/wib-test/fake" / f"terraform-provider-fake_{VERSION}_{PLAT}.zip"
    check("one registry lookup and one fetch", len(lookups) == 1 and fetches == [URL], f"{lookups} {fetches}")
    check("the mirror's zip is a link to the artifact cache entry", link.is_symlink() and link.resolve() == entry)
    check("the config installs registry.terraform.io providers from that mirror only",
          env["TF_CLI_CONFIG_FILE"] == str(tpc.config_path(root)) and
          pathlib.Path(env["TF_CLI_CONFIG_FILE"]).read_text() == tpc.render_config(tpc.mirror_dir(root)))
    r = init(tmp / "good", env)
    out = said(r)
    check("init succeeds against the lock", r is not None and r.returncode == 0, out)
    check("it installs the provider from the mirror", f"Installed wib-test/fake v{VERSION} (unauthenticated)" in out, out)
    check("the lock is unchanged", (tmp / "good/.terraform.lock.hcl").read_bytes() == LOCK)
    tpc.terraform_env(base, LOCKED, root=root, fetch_meta=no_network, fetch=no_network, plat=PLAT)
    check("a second fill is warm: no lookup, no fetch", len(lookups) == 1 and len(fetches) == 1)

    print("== contents changed: init fails on the lock's checksums, and the fill refuses the entry ==")
    entry.chmod(0o644)
    entry.write_bytes(CHANGED)
    (tmp / "plugin-cache-changed").mkdir()
    r = init(tmp / "changed", {**env, "TF_PLUGIN_CACHE_DIR": str(tmp / "plugin-cache-changed")})
    out = said(r)
    check("init fails", r is not None and r.returncode != 0, out)
    check("terraform says the package does not match the lock",
          "doesn't match any of the checksums previously recorded in the dependency lock file" in " ".join(out.split()),
          out)
    check("nothing is installed into the plugin cache",
          not any(p.is_file() for p in (tmp / "plugin-cache-changed").rglob("*")))
    err = fill_error(root)
    check("the fill refuses the entry, naming both sums and not fetching again",
          f"expected SHA-256 {sha(GOOD)}, got {sha(CHANGED)}" in err and len(fetches) == 1, err)
    check("and leaves the entry where it is for a person to look at", entry.read_bytes() == CHANGED)

    print("== bytes appended: the fill's byte check refuses it, so the init it would feed never runs ==")
    entry.write_bytes(GOOD + b"#1119 appended")
    err = fill_error(root)
    check("the fill refuses the entry, naming both sums",
          f"expected SHA-256 {sha(GOOD)}, got {sha(GOOD + b'#1119 appended')}" in err, err)

    print("== a registry answer the lock does not vouch for is refused before anything is fetched ==")
    other = tmp / "other-root"
    err = fill_error(other, meta(sha(CHANGED)))
    check("refused, naming the sum and the lock",
          f"has SHA-256 {sha(CHANGED)}, which is not one of the 1 zh: hashes the fake lock records" in err, err)
    check("nothing was fetched or put in the mirror",
          len(fetches) == 1 and not (other / "sha256").exists() and not tpc.mirror_dir(other).exists())
    check("and no index entry was written", not (other / tpc.PROVIDERS_SUBDIR / "index").exists())
    print(json.dumps({"lookups": len(lookups), "fetches": len(fetches)}))

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL TERRAFORM MIRROR LOCK CHECKS GREEN")
