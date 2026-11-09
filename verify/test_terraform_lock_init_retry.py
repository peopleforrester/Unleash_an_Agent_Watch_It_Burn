# ABOUTME: test_terraform_lock_init.py runs an init the network broke again, in a new empty directory, and fails any
# ABOUTME: other init at once (#1047). Offline: it is run against a stub terraform that answers as told.
"""Offline. The real inits are test_terraform_lock_init.py in the tools tier, against the provider mirror.

On Tanjiro's CI runner (Actions run 42407284907) one provider query to registry.terraform.io ran out of time and the
tier went red. The tier test now asks again when terraform's output reads as the network failing, and never when the
lock does not match. Each case here runs the real test with TERRAFORM naming a stub that counts its runs, fails the
runs it is told to with the words it is given, and otherwise exits 0 leaving the lock as it found it.

#1247: the tier test seeds a root that calls a module from the module cache (tf_module_cache.py) and runs that init
with the network closed (iam_plan_render.CLOSED_NETWORK), and keeps the install on a miss. The stub's successful init
of such a root writes .terraform/modules/modules.json, as a real install does, so the miss is kept in the case's own
artifact root; the warm case runs the tier test once to fill it and then again, and reads which inits were seeded and
what proxy each saw. A seeded init the network breaks is not run again: with the network closed, that error means the
kept modules no longer serve the root.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import iam_plan_render  # noqa: E402
import tf_plugin_cache  # noqa: E402
TEST = HERE / "test_terraform_lock_init.py"
SRC = TEST.read_text(encoding="utf-8")

# The words terraform printed on the runner, and the words a lock that does not match gets.
NETWORK = ('Error: Failed to query available provider packages\n\nCould not retrieve the list of available versions '
           'for provider hashicorp/time: could not query provider registry for registry.terraform.io/hashicorp/time: '
           'the request failed after 2 attempts, please try again later: Get '
           '"https://registry.terraform.io/v1/providers/hashicorp/time/versions": context deadline exceeded\n')
LOCK = ('Error: Failed to install provider\n\nError while installing hashicorp/aws v6.70.0: the local package for '
        'registry.terraform.io/hashicorp/aws 6.70.0 doesn\'t match any of the checksums previously recorded in the '
        'dependency lock file\n')

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


for anchor in ("ROOTS = [", "BACKOFF = ", "TF_LOCK_INIT_BACKOFF", "is_network_error(", "RETRY ",
               "tf_module_cache.seed(", "iam_plan_render.CLOSED_NETWORK"):
    if anchor not in SRC:
        print(f"FAIL: {anchor!r} is not in {TEST.name}: this test drives that test by it")
        sys.exit(1)
ROOTS = SRC.count('"infra/')
# The roots that call a module, the ones the module cache seeds, in the tier test's order. The warm case below fails
# when another root starts calling one, since its init is then seeded too.
MODULE_ROOTS = ["infra/terraform/aws/cluster", "infra/terraform/aws/network"]


def run(fail_runs: str, words: str, warm: bool = False) -> tuple[int, str, int, list[tuple[str, str]]]:
    """The tier test's exit, output and how many times it ran terraform, with a stub that fails the runs fail_runs
    names (a shell case pattern, `*` for all, `0` for none) printing words; and for each run, whether it started
    seeded (.terraform/modules there before init) and the HTTPS_PROXY it saw. warm runs the tier test once first,
    with no failure, so the module cache holds what that run kept; its runs are not counted."""
    # Outside the checkout, since the tier test refuses a cache inside it and TMPDIR can be (#1114). The stub never
    # writes the cache, so an offline run leaves nothing behind.
    with tf_plugin_cache.scratch("tf-lock-init-retry-") as td:
        tmp = pathlib.Path(td)
        (tmp / "words").write_text(words)
        stub = tmp / "terraform"
        stub.write_text("#!/bin/sh\n"
                        f'if [ -f .terraform/modules/modules.json ]; then s=seeded; else s=fresh; fi\n'
                        f'if [ ! -e "{tmp}/warming" ]; then\n'
                        f'  n=$(cat "{tmp}/n" 2>/dev/null); n=$((n+1)); echo $n > "{tmp}/n"\n'
                        f'  echo "$s ${{HTTPS_PROXY:-none}}" >> "{tmp}/calls"\n'
                        f'  case $n in {fail_runs}) cat "{tmp}/words" >&2; exit 1;; esac\n'
                        'fi\n'
                        # As a real install does: a root that calls a module leaves modules.json.
                        'if grep -q "^module \\"" ./*.tf && [ $s = fresh ]; then\n'
                        '  mkdir -p .terraform/modules && echo \'{"Modules":[{"Key":"","Source":"","Dir":"."}]}\' '
                        '> .terraform/modules/modules.json\n'
                        'fi\n'
                        'echo "Terraform has been successfully initialized!"\n')
        stub.chmod(0o755)
        # An artifact root of its own with the provider mirror's config already written, as a workflow's
        # `tf_plugin_cache.py prepare` leaves it, so the tier test fills nothing and an offline run never touches the
        # network or the shared cache (#1119).
        root = tmp / "artifacts"
        env = {k: v for k, v in os.environ.items() if k != "HECATON_TOOLS_CACHE"}
        env.update({"TERRAFORM": str(stub), "TF_LOCK_INIT_BACKOFF": "0,0", "WIB_ARTIFACT_CACHE": str(root),
                    "TF_CLI_CONFIG_FILE": str(tf_plugin_cache.write_config(root)),
                    "TF_PLUGIN_CACHE_DIR": str(tmp / "plugin-cache")})
        if warm:
            (tmp / "warming").touch()
            w = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, env=env, timeout=120)
            (tmp / "warming").unlink()
            if w.returncode:
                return w.returncode, "(the warming run failed)\n" + w.stdout + w.stderr, 0, []
        p = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, env=env, timeout=120)
        runs = int((tmp / "n").read_text()) if (tmp / "n").exists() else 0
        calls = [tuple(ln.split(" ", 1)) for ln in (tmp / "calls").read_text().splitlines()] \
            if (tmp / "calls").exists() else []
    return p.returncode, p.stdout + p.stderr, runs, calls


check("the tier test inits five roots", ROOTS == 5, str(ROOTS))
check("the tier test inits both roots that call modules", all(f'"{r}"' in SRC for r in MODULE_ROOTS))
check("the tier test fills the provider mirror before its inits", "tf_plugin_cache.terraform_env(" in SRC)

print("== one init the network broke is run again, and the tier test passes ==")
code, out, runs, calls = run("1", NETWORK)
check("exit 0", code == 0, out[-600:])
check("terraform ran once more than there are roots", runs == ROOTS + 1, str(runs))
check("the retry is printed, naming the root and the try",
      out.count("RETRY ") == 1 and "RETRY infra/terraform/aws/cluster: init failed on the network" in out
      and "try 1 of 3" in out, out[-600:])

print("== an init the network breaks on every try fails, naming the tries ==")
code, out, runs, calls = run("*", NETWORK)
check("exit 1", code == 1, out[-600:])
check("each root is tried three times", runs == ROOTS * 3, str(runs))
check("the failure names the network error and the tries",
      "context deadline exceeded" in out and "(a network error on each of 3 tries)" in out, out[-600:])

print("== a lock that does not match fails on the first try ==")
code, out, runs, calls = run("*", LOCK)
check("exit 1", code == 1, out[-600:])
check("each root is tried once", runs == ROOTS, str(runs))
check("nothing is retried", "RETRY " not in out, out[-600:])
check("the failure carries terraform's words", "doesn't match any of the checksums" in out, out[-600:])

print("== with no failure, each root is inited once ==")
code, out, runs, calls = run("0", "")
check("exit 0, one init a root, no retry", code == 0 and runs == ROOTS and "RETRY " not in out
      and "ALL TERRAFORM LOCK-INIT CHECKS GREEN" in out, f"{code} {runs} {out[-400:]}")
check("on a cold module cache no init is seeded, and none has the network closed",
      calls == [("fresh", "none")] * ROOTS, str(calls))
check("each root that calls a module is installed and kept",
      out.count("installed from the network (a module cache miss), now kept") == len(MODULE_ROOTS), out[-800:])

REFUSED = iam_plan_render.CLOSED_NETWORK["HTTPS_PROXY"]
print("== on a warm module cache, each root that calls a module is seeded and inits with the network closed ==")
code, out, runs, calls = run("0", "", warm=True)
check("exit 0, one init a root, no retry", code == 0 and runs == ROOTS and "RETRY " not in out
      and "ALL TERRAFORM LOCK-INIT CHECKS GREEN" in out, f"{code} {runs} {out[-400:]}")
check("the cluster and network inits start seeded, behind the refusing proxy; the other three fresh and open",
      calls == [("seeded", REFUSED)] * len(MODULE_ROOTS) + [("fresh", "none")] * (ROOTS - len(MODULE_ROOTS)),
      str(calls))
check("the output says each seeded init's modules came from the cache",
      out.count("seeded from the module cache, init run with the network closed") == len(MODULE_ROOTS), out[-800:])
check("nothing is installed again", "installed from the network" not in out, out[-800:])

print("== a seeded init the network breaks fails at once, saying it was seeded ==")
code, out, runs, calls = run("1", NETWORK, warm=True)
check("exit 1", code == 1, out[-600:])
check("terraform ran once a root: the seeded cluster init is not run again", runs == ROOTS, str(runs))
check("nothing is retried", "RETRY " not in out, out[-600:])
check("the failure says the init was seeded with the network closed",
      "seeded from the module cache, with the network closed" in out and "context deadline exceeded" in out,
      out[-600:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All terraform lock-init retry checks passed.")
