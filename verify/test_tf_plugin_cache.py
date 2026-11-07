# ABOUTME: Offline check that verify/tf_plugin_cache.py names a Terraform provider cache that outlives the checkout and
# ABOUTME: never sits in it, and that the lock-init test, the tools tier and verify-suites.yml all use it (#1114).
"""Offline. The real inits against the cache are test_terraform_lock_init.py and test_terraform_plugin_cache_lock.py.

#1114: the lock-init test downloaded about 2.4 GB of providers on every run, since it cleared TF_PLUGIN_CACHE_DIR
and the tier's own cache sat in verify/.tools, which each new checkout starts empty. The cache is now named by
tf_plugin_cache.py: TF_PLUGIN_CACHE_DIR when set, else $HECATON_TOOLS_CACHE/terraform-plugin-cache, else the user's
cache directory, and an error when that is inside the working tree, relative or not writable.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import tf_plugin_cache as tpc  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def refused(env: dict[str, str], words: str) -> bool:
    try:
        tpc.resolve(env)
    except tpc.CacheError as e:
        return words in str(e)
    return False


with tpc.scratch("tf-plugin-cache-test-") as td:
    out = pathlib.Path(td)
    print("== the cache is named in order, each outside the checkout ==")
    full = {"TF_PLUGIN_CACHE_DIR": str(out / "given"), "HECATON_TOOLS_CACHE": str(out / "hecaton"),
            "XDG_CACHE_HOME": str(out / "xdg"), "HOME": str(out / "home")}
    check("TF_PLUGIN_CACHE_DIR first, as the caller set it",
          tpc.resolve(full) == ((out / "given").resolve(), "TF_PLUGIN_CACHE_DIR"), str(tpc.resolve(full)))
    env = {k: v for k, v in full.items() if k != "TF_PLUGIN_CACHE_DIR"}
    check("then hecaton's shared tools cache (#1004), under terraform-plugin-cache",
          tpc.resolve(env) == ((out / "hecaton/terraform-plugin-cache").resolve(), "HECATON_TOOLS_CACHE"),
          str(tpc.resolve(env)))
    env.pop("HECATON_TOOLS_CACHE")
    check("then $XDG_CACHE_HOME/unleash-watch-it-burn/terraform-plugin-cache",
          tpc.resolve(env) == ((out / "xdg/unleash-watch-it-burn/terraform-plugin-cache").resolve(), "XDG_CACHE_HOME"),
          str(tpc.resolve(env)))
    env.pop("XDG_CACHE_HOME")
    check("then $HOME/.cache/unleash-watch-it-burn/terraform-plugin-cache",
          tpc.resolve(env) == ((out / "home/.cache/unleash-watch-it-burn/terraform-plugin-cache").resolve(), "HOME"),
          str(tpc.resolve(env)))
    check("an empty TF_PLUGIN_CACHE_DIR counts as unset",
          tpc.resolve({"TF_PLUGIN_CACHE_DIR": "", "HOME": str(out / "home")})[1] == "HOME")

    print("== a cache that cannot outlive the checkout, or cannot be used, is an error, never the next rule ==")
    check("inside the working tree is refused, naming it",
          refused({"TF_PLUGIN_CACHE_DIR": str(REPO / "verify/.tools/plugin-cache"), "HOME": str(out / "home")},
                  f"inside the working tree {REPO}"))
    check("the working tree itself is refused", refused({"TF_PLUGIN_CACHE_DIR": str(REPO)}, "inside the working tree"))
    check("a path that resolves into the tree through .. is refused",
          refused({"TF_PLUGIN_CACHE_DIR": str(out / os.path.relpath(REPO / "c", out))}, "inside the working tree"))
    check("a HOME inside the tree is refused, not passed over",
          refused({"HOME": str(REPO / "tmp" / "home")}, "from HOME"))
    check("a relative path is refused", refused({"TF_PLUGIN_CACHE_DIR": "cache"}, "a relative path"))
    check("with nothing set there is no cache", refused({}, "none of TF_PLUGIN_CACHE_DIR"))
    ro = out / "readonly"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        try:
            tpc.ensure({"TF_PLUGIN_CACHE_DIR": str(ro)})
            ok = False
        except tpc.CacheError as e:
            ok = "is not writable" in str(e)
    finally:
        ro.chmod(0o755)
    check("a cache that is not writable is refused", ok)
    check("refusing a cache inside the tree creates nothing there",
          not (REPO / "verify/.tools/plugin-cache-test-1114").exists()
          and subprocess.run([sys.executable, str(HERE / "tf_plugin_cache.py")], capture_output=True,
                             env={**os.environ, "TF_PLUGIN_CACHE_DIR": str(REPO / "verify/.tools/plugin-cache-test-1114")}
                             ).returncode == 1
          and not (REPO / "verify/.tools/plugin-cache-test-1114").exists())

    print("== as a script it prints the cache it created, or says why it cannot ==")
    want = out / "made" / "cache"
    r = subprocess.run([sys.executable, str(HERE / "tf_plugin_cache.py")], capture_output=True, text=True,
                       env={**os.environ, "TF_PLUGIN_CACHE_DIR": str(want)})
    check("exit 0, the path printed and created", r.returncode == 0 and r.stdout == f"{want.resolve()}\n"
          and want.is_dir(), r.stdout + r.stderr)
    r = subprocess.run([sys.executable, str(HERE / "tf_plugin_cache.py")], capture_output=True, text=True,
                       env={**os.environ, "TF_PLUGIN_CACHE_DIR": "relative"})
    check("exit 1 with the reason on stderr", r.returncode == 1 and r.stdout == ""
          and r.stderr.startswith("TERRAFORM PLUGIN CACHE UNUSABLE: "), r.stdout + r.stderr)
check("the scratch directory is gone when the test is done with it", not out.exists())

print("== the lock-init test inits with the cache, and with the lock's check on ==")
lock_init = (HERE / "test_terraform_lock_init.py").read_text()
check("it no longer clears TF_PLUGIN_CACHE_DIR", 'env.pop("TF_PLUGIN_CACHE_DIR"' not in lock_init)
check("it names the cache through tf_plugin_cache.ensure",
      'env["TF_PLUGIN_CACHE_DIR"] = str(tf_plugin_cache.ensure(env))' in lock_init)
check("it unsets TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE, the one switch past the lock's checksums",
      'env.pop("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", None)' in lock_init)
check("each init is still -lockfile=readonly in a new empty directory",
      '"init", "-lockfile=readonly"' in lock_init and "tempfile.TemporaryDirectory(" in lock_init)
cache_lock = (HERE / "test_terraform_plugin_cache_lock.py").read_text()
check("test_terraform_plugin_cache_lock.py is a terraform tier test that takes its turn",
      all(re.search(rf"^{re.escape(m)}", cache_lock, re.M) for m in
          ("# SUITE: e2e", "# E2E TIER: tools", "# E2E SERIAL: terraform")))

print("== the tools tier and its CI job keep the cache outside the checkout ==")
runner = (HERE / "run-e2e-tools.sh").read_text()
code = "\n".join(ln for ln in runner.splitlines() if not ln.lstrip().startswith("#"))
check("run-e2e-tools.sh takes its cache from tf_plugin_cache.py",
      'TF_CACHE="$(python3 "${SCRIPT_DIR}/tf_plugin_cache.py")"' in code)
check("and no longer keeps one in verify/.tools", ".tools/plugin-cache" not in code)
check("each tier test gets it as TF_PLUGIN_CACHE_DIR", 'TF_PLUGIN_CACHE_DIR="${TF_CACHE}"' in code)
check("with TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE unset", "-u TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"
      in code)
check("a terraform test holds the cache's lock while it runs",
      'TF_CACHE_LOCK="${TF_CACHE}.lock"' in code and 'flock -w "${TF_CACHE_LOCK_WAIT}"' in code)
workflow = (REPO / ".github/workflows/verify-suites.yml").read_text()
job = workflow.split("\n  e2e-tools:\n", 1)[1] if "\n  e2e-tools:\n" in workflow else ""
check("verify-suites.yml's e2e-tools job keeps the cache under the runner's tool cache, which outlives the job",
      "      TF_PLUGIN_CACHE_DIR: ${{ runner.tool_cache }}/terraform-plugin-cache\n" in job, job[:400])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All terraform plugin-cache checks passed.")
