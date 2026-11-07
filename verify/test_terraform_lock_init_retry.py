# ABOUTME: test_terraform_lock_init.py runs an init the network broke again, in a new empty directory, and fails any
# ABOUTME: other init at once (#1047). Offline: it is run against a stub terraform that answers as told.
"""Offline. The real inits are test_terraform_lock_init.py in the tools tier, against registry.terraform.io.

On Tanjiro's CI runner (Actions run 42407284907) one provider query to registry.terraform.io ran out of time and the
tier went red. The tier test now asks again when terraform's output reads as the network failing, and never when the
lock does not match. Each case here runs the real test with TERRAFORM naming a stub that counts its runs, fails the
runs it is told to with the words it is given, and otherwise exits 0 leaving the lock as it found it.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
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


for anchor in ("ROOTS = [", "BACKOFF = ", "TF_LOCK_INIT_BACKOFF", "is_network_error(", "RETRY "):
    if anchor not in SRC:
        print(f"FAIL: {anchor!r} is not in {TEST.name}: this test drives that test by it")
        sys.exit(1)
ROOTS = SRC.count('"infra/')


def run(fail_runs: str, words: str) -> tuple[int, str, int]:
    """The tier test's exit, output and how many times it ran terraform, with a stub that fails the runs fail_runs
    names (a shell case pattern, `*` for all, `0` for none) printing words."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        (tmp / "words").write_text(words)
        stub = tmp / "terraform"
        stub.write_text("#!/bin/sh\n"
                        f'n=$(cat "{tmp}/n" 2>/dev/null); n=$((n+1)); echo $n > "{tmp}/n"\n'
                        f'case $n in {fail_runs}) cat "{tmp}/words" >&2; exit 1;; esac\n'
                        'echo "Terraform has been successfully initialized!"\n')
        stub.chmod(0o755)
        env = {**os.environ, "TERRAFORM": str(stub), "TF_LOCK_INIT_BACKOFF": "0,0"}
        p = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, env=env, timeout=120)
        runs = int((tmp / "n").read_text()) if (tmp / "n").exists() else 0
    return p.returncode, p.stdout + p.stderr, runs


check("the tier test inits five roots", ROOTS == 5, str(ROOTS))

print("== one init the network broke is run again, and the tier test passes ==")
code, out, runs = run("1", NETWORK)
check("exit 0", code == 0, out[-600:])
check("terraform ran once more than there are roots", runs == ROOTS + 1, str(runs))
check("the retry is printed, naming the root and the try",
      out.count("RETRY ") == 1 and "RETRY infra/terraform/aws/cluster: init failed on the network" in out
      and "try 1 of 3" in out, out[-600:])

print("== an init the network breaks on every try fails, naming the tries ==")
code, out, runs = run("*", NETWORK)
check("exit 1", code == 1, out[-600:])
check("each root is tried three times", runs == ROOTS * 3, str(runs))
check("the failure names the network error and the tries",
      "context deadline exceeded" in out and "(a network error on each of 3 tries)" in out, out[-600:])

print("== a lock that does not match fails on the first try ==")
code, out, runs = run("*", LOCK)
check("exit 1", code == 1, out[-600:])
check("each root is tried once", runs == ROOTS, str(runs))
check("nothing is retried", "RETRY " not in out, out[-600:])
check("the failure carries terraform's words", "doesn't match any of the checksums" in out, out[-600:])

print("== with no failure, each root is inited once ==")
code, out, runs = run("0", "")
check("exit 0, one init a root, no retry", code == 0 and runs == ROOTS and "RETRY " not in out
      and "ALL TERRAFORM LOCK-INIT CHECKS GREEN" in out, f"{code} {runs} {out[-400:]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All terraform lock-init retry checks passed.")
