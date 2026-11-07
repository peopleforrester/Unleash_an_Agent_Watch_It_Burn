# ABOUTME: Names the Terraform provider plugin cache the tools tier shares between runs (#1114), always outside the
# ABOUTME: repo's working tree, and creates it. As a script it prints the path; any reason it cannot be used exits 1.
"""Where the terraform tests keep their providers.

#1114: test_terraform_lock_init.py took 326 s in the tools tier, most of it `terraform init` downloading about
2.4 GB of providers (three aws versions and the datadog one). The cache sat in verify/.tools/plugin-cache, so each
new checkout, which is each hecaton run, started it cold. The cache now lives where it outlives the checkout:

1. TF_PLUGIN_CACHE_DIR, when the caller sets it. verify-suites.yml sets it on Tanjiro's runner to a directory under
   RUNNER_TOOL_CACHE, which outlives the job and is not in the workspace.
2. $HECATON_TOOLS_CACHE/terraform-plugin-cache, when hecaton names its shared tools cache (#1004, hecaton#540).
3. $XDG_CACHE_HOME (or $HOME/.cache)/unleash-watch-it-burn/terraform-plugin-cache, the user's own cache, which on a
   hecaton host is the pool's home and outlives the run.

A cache that resolves inside this repo's working tree, a relative path, or one that cannot be created or written is
an error, never a reason to try the next place. The cache cannot let a provider through that a lock does not vouch
for: Terraform 1.4 and later use a cached provider only when its h1: checksum is one the lock records, and otherwise
download it again and verify that (test_terraform_plugin_cache_lock.py holds this for a tampered cache entry).
TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE is the one way around that, and test_terraform_lock_init.py unsets it.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from collections.abc import Mapping

REPO = pathlib.Path(__file__).resolve().parents[1]
SUBDIR = "terraform-plugin-cache"
APP = "unleash-watch-it-burn"


class CacheError(Exception):
    pass


def resolve(env: Mapping[str, str]) -> tuple[pathlib.Path, str]:
    """The cache directory env names and which rule named it. Raises CacheError when it is unusable."""
    if env.get("TF_PLUGIN_CACHE_DIR"):
        raw, why = env["TF_PLUGIN_CACHE_DIR"], "TF_PLUGIN_CACHE_DIR"
    elif env.get("HECATON_TOOLS_CACHE"):
        raw, why = os.path.join(env["HECATON_TOOLS_CACHE"], SUBDIR), "HECATON_TOOLS_CACHE"
    elif env.get("XDG_CACHE_HOME") or env.get("HOME"):
        raw = str(user_cache_root(env) / APP / SUBDIR)
        why = "XDG_CACHE_HOME" if env.get("XDG_CACHE_HOME") else "HOME"
    else:
        raise CacheError("none of TF_PLUGIN_CACHE_DIR, HECATON_TOOLS_CACHE, XDG_CACHE_HOME or HOME is set, so there "
                         "is no directory outside the checkout to keep the provider cache in")
    path = pathlib.Path(raw)
    if not path.is_absolute():
        raise CacheError(f"the provider cache from {why} is {raw!r}, a relative path; it must be absolute")
    path = path.resolve()
    if path == REPO or REPO in path.parents:
        raise CacheError(f"the provider cache from {why} is {path}, inside the working tree {REPO}; it must outlive "
                         "the checkout, so it never sits in it (#1114)")
    return path, why


def user_cache_root(env: Mapping[str, str]) -> pathlib.Path:
    """$XDG_CACHE_HOME, else $HOME/.cache: where rule 3 keeps the cache."""
    if env.get("XDG_CACHE_HOME"):
        return pathlib.Path(env["XDG_CACHE_HOME"])
    if env.get("HOME"):
        return pathlib.Path(env["HOME"]) / ".cache"
    raise CacheError("neither XDG_CACHE_HOME nor HOME is set")


def scratch(prefix: str) -> tempfile.TemporaryDirectory:
    """A temp directory outside the working tree, for a test that needs a cache of its own. Not TMPDIR: a hecaton run's
    TMPDIR is <worktree>/tmp/hecaton, inside the checkout, so a cache there is one resolve() refuses. It sits under
    the user's cache directory and is removed when the test is done with it."""
    root = user_cache_root(os.environ) / APP
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=root)


def ensure(env: Mapping[str, str]) -> pathlib.Path:
    """resolve(env), created and checked writable."""
    path, why = resolve(env)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CacheError(f"the provider cache from {why}, {path}, cannot be created: {e}") from e
    if not os.access(path, os.W_OK | os.X_OK):
        raise CacheError(f"the provider cache from {why}, {path}, is not writable; terraform init installs into it")
    return path


def main() -> int:
    try:
        print(ensure(os.environ))
    except CacheError as e:
        print(f"TERRAFORM PLUGIN CACHE UNUSABLE: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
