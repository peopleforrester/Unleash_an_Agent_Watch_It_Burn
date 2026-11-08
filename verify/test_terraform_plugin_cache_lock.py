# ABOUTME: The plugin cache test_terraform_lock_init.py reads cannot let a provider through that the lock does not
# ABOUTME: match (#1114): a cached provider whose bytes were changed is never what an init links in.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and on a cold artifact cache network to registry.terraform.io)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
# E2E SERIAL: terraform (run-e2e-tools.sh runs one such test at a time: they share the provider cache, #1005)
"""A tampered provider in the plugin cache never reaches an init.

#1114 gave test_terraform_lock_init.py a plugin cache that outlives the checkout, so its inits read providers an
earlier run left. Terraform 1.4 and later use a cached provider only when its h1: checksum is one the lock records,
and otherwise install it again from its source and check that against the lock. Since #1119 the source is the
provider mirror in the host artifact cache (tf_plugin_cache.terraform_env), so nothing is downloaded either way. This
holds that on the pinned terraform, with the environment the lock-init test gives it
(TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE unset).

It uses hashicorp/null, a few MB, with the block the cluster root's lock records for it, and a plugin cache of its own
outside the checkout, so the shared cache is never the one tampered with:

1. cold: an init into the empty cache installs null there from the mirror and links it into .terraform/providers.
2. warm: a fresh init takes null from the cache and installs nothing, lock unchanged.
3. tampered: bytes are added to the cached binary; a fresh init does not take it, installs null again from the mirror
   and puts the verified bytes back, lock unchanged. Nothing the lock does not vouch for is linked in.
Terraform downloads nothing in any of the three: a registry download names its signer, and none does.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import tf_plugin_cache  # noqa: E402

LOCK_SRC = REPO / "infra/terraform/aws/cluster/.terraform.lock.hcl"
PROVIDER = "registry.terraform.io/hashicorp/null"
INIT_TIMEOUT = 300
TAMPER = b"\n#1114 tampered\n"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)

# The lock block this test inits against, cut from the cluster root's lock. A reworded or removed block is named here,
# not read as a broken check further on.
block = re.search(rf'^provider "{re.escape(PROVIDER)}" {{\n.*?^}}\n', LOCK_SRC.read_text(), re.M | re.S)
version = re.search(r'^\s*version\s*=\s*"([^"]+)"', block.group(0), re.M) if block else None
if not block or not version or "h1:" not in block.group(0):
    print(f'FAIL: no provider "{PROVIDER}" block with a version and an h1: hash in {LOCK_SRC.relative_to(REPO)}; '
          "this test inits against that block", file=sys.stderr)
    sys.exit(1)
LOCK = block.group(0).encode()
VERSION = version.group(1)
MAIN_TF = ('terraform {\n  required_providers {\n'
           f'    null = {{ source = "hashicorp/null", version = "{VERSION}" }}\n  }}\n}}\n')
try:
    BASE_ENV = tf_plugin_cache.terraform_env({**os.environ, "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"},
                                             tf_plugin_cache.parse_lock(block.group(0), str(LOCK_SRC.relative_to(REPO))))
except tf_plugin_cache.CacheError as e:
    print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
BASE_ENV.pop("TF_DATA_DIR", None)


def init(work: pathlib.Path, cache: pathlib.Path) -> subprocess.CompletedProcess | None:
    """A fresh `terraform init -lockfile=readonly` in work against the mirror and cache, the lock-init test's way.
    None when it timed out."""
    env = {**BASE_ENV, "TF_PLUGIN_CACHE_DIR": str(cache)}
    work.mkdir()
    (work / "main.tf").write_text(MAIN_TF)
    (work / ".terraform.lock.hcl").write_bytes(LOCK)
    try:
        return subprocess.run([exe, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color"],
                              cwd=work, env=env, capture_output=True, text=True, timeout=INIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None


def linked(work: pathlib.Path) -> pathlib.Path:
    return work / ".terraform/providers" / PROVIDER / VERSION / "linux_amd64"


def binary(d: pathlib.Path) -> pathlib.Path | None:
    found = sorted(d.glob("terraform-provider-null_*")) if d.is_dir() else []
    return found[0] if found else None


def digest(p: pathlib.Path | None) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p else ""


def said(r: subprocess.CompletedProcess | None) -> str:
    return "timed out" if r is None else (r.stdout + r.stderr)[-1500:]


def downloaded(out: str) -> bool:
    return "(signed by" in out or "(self-signed" in out


with tf_plugin_cache.scratch("tf-cache-lock-") as td:
    tmp = pathlib.Path(td)
    cache = tmp / "cache"
    cache.mkdir()
    entry = cache / PROVIDER / VERSION / "linux_amd64"

    print(f"== cold: an init into an empty cache installs {PROVIDER} {VERSION} there from the mirror ==")
    r = init(tmp / "cold", cache)
    check("init succeeds against the lock", r is not None and r.returncode == 0, said(r))
    check("terraform downloads nothing: the provider comes from the mirror", not downloaded(said(r)), said(r))
    good = binary(entry)
    check("the provider is in the cache", good is not None, str(entry))
    check(".terraform/providers links to the cache entry",
          linked(tmp / "cold").is_symlink() and linked(tmp / "cold").resolve() == entry.resolve(),
          str(linked(tmp / "cold")))
    check("the lock is unchanged", (tmp / "cold/.terraform.lock.hcl").read_bytes() == LOCK)
    if good is None:
        print(f"\n{len(failures)} FAILED: no cached provider to go on with", file=sys.stderr)
        sys.exit(1)
    verified = digest(good)

    print("== warm: a fresh init takes the provider from the cache and downloads nothing ==")
    r = init(tmp / "warm", cache)
    out = said(r)
    check("init succeeds against the lock", r is not None and r.returncode == 0, out)
    check("terraform says it used the cache", "from the shared cache directory" in out, out)
    check("nothing is installed or downloaded", f"Installing hashicorp/null v{VERSION}" not in out
          and not downloaded(out), out)
    check(".terraform/providers links to the cache entry", linked(tmp / "warm").resolve() == entry.resolve())
    check("the lock is unchanged", (tmp / "warm/.terraform.lock.hcl").read_bytes() == LOCK)

    print("== tampered: a cached provider the lock does not match is never linked in ==")
    with good.open("ab") as f:
        f.write(TAMPER)
    tampered = digest(good)
    check("the cached binary now differs from the verified one", tampered != verified)
    r = init(tmp / "tampered", cache)
    out = said(r)
    check("init succeeds against the lock", r is not None and r.returncode == 0, out)
    check("terraform installs the provider again from the mirror rather than take the cached one",
          f"Installing hashicorp/null v{VERSION}" in out and "from the shared cache directory" not in out
          and not downloaded(out), out)
    now = binary(linked(tmp / "tampered"))
    check("the binary the init links in is the verified one", digest(now) == verified,
          f"{now}: {digest(now)}, verified {verified}")
    check("no tampered bytes reach the init", now is not None and not now.read_bytes().endswith(TAMPER))
    check("the cache entry holds the verified bytes again", digest(binary(entry)) == verified)
    check("the lock is unchanged", (tmp / "tampered/.terraform.lock.hcl").read_bytes() == LOCK)

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL TERRAFORM PLUGIN-CACHE LOCK CHECKS GREEN")
