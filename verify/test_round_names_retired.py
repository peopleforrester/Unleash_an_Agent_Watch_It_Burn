# ABOUTME: The fleet scripts and gitops Applications describe roles, not rounds (#560): no round wording, no
# ABOUTME: per-round knobs, and setup-instructor-cluster.sh takes a roster cluster whose role fleet.sh names.
"""Holds the non-markdown files #498 did not reach to the role model.

#498 retired the R1/R2/R3 shorthand in the current markdown, held there by `test_docs_current.py`. The code
still spoke rounds: fleet.sh's usage said R2/R3 instructors bootstrap 'full' and R1 'burn', when attendees
take 'attendee', the community cluster 'burn' and the admin clusters 'admin'; it defined WIB_ACCOUNT_R1..R3,
which nothing read; and infra/setup-instructor-cluster.sh still took `<name> <round 1|2|3>`. The gitops
Applications said R1 where they meant the community cluster.

What this checks, all offline:

- the swept files carry none of `round_shapes.CODE_SHAPES`, except on a dated line, which records where
  something was measured. Retired cluster and host names are history in a comment and are not swept.
- fleet.sh's usage text says no round, the per-round account knobs and the `rounds` selector are gone, and
  the role picks the bootstrap profile in one function that the setup script also asks.
- setup-instructor-cluster.sh refuses an attendee name, a non-fleet name and the old round argument before
  it touches AWS, and resolves a roster cluster's account through fleet.sh.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from round_shapes import CODE_SHAPES, DATED  # noqa: E402

REPO = HERE.parent
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
SETUP = REPO / "infra/setup-instructor-cluster.sh"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def swept() -> list[pathlib.Path]:
    out = [FLEET, SETUP]
    for d in ("gitops/apps", "gitops/bootstrap"):
        out += sorted(p for p in (REPO / d).rglob("*") if p.is_file() and p.suffix != ".md")
    return out


def fleet_q(expr: str) -> str:
    """Run one expression against a sourced fleet.sh. No cloud access: pure functions only."""
    r = subprocess.run(["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; {expr}"], cwd=FLEET.parent,
                       capture_output=True, text=True, timeout=60)
    return r.stdout


def function_src(src: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src, re.S | re.M)
    return m.group(0) if m else ""


def comment_above(src: str, name: str) -> str:
    """The contiguous comment block directly above a function definition."""
    lines = src[:src.index(f"\n{name}() {{")].splitlines()
    block = []
    while lines and lines[-1].startswith("#"):
        block.insert(0, lines.pop())
    return "\n".join(block)


print("== the shapes catch round wording and leave retired names and plain 'round' alone ==")
for text in ("R2/R3 instructors with the 'full' profile", "Flip a round-2/3 cluster's guardrails",
             "A half-armed Round 2 that reports success", "rounds 2 and 3 were pre-blocked",
             "BURN (R1) omits it", "per-round account profiles"):
    check(f"caught: {text!r}", CODE_SHAPES.search(text) is not None)
for text in ("measured on watch-it-burn-r2-1", "michael-round2 and whitney-round2 returned 502",
             'log "converge round ${round}/${CONVERGE_ROUNDS}"', "round-robin by its number",
             "peopleforrester/rounds-agenticburn", "one extra round trip"):
    check(f"not caught: {text!r}", CODE_SHAPES.search(text) is None)

print("== the fleet scripts and gitops Applications describe no cluster as a round ==")
offenders = []
for p in swept():
    rel = p.relative_to(REPO).as_posix()
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = CODE_SHAPES.search(line)
        if m and not DATED.search(line):
            offenders.append(f"{rel}:{i}: {m.group(0)!r}")
check(f"no round wording in {len(swept())} swept files"
      + (f" (found {len(offenders)}: {offenders[:4]})" if offenders else ""), not offenders)

print("== fleet.sh: usage, knobs and the role-to-profile map ==")
src = FLEET.read_text(encoding="utf-8")
usage = src[src.index("usage() {"):]
usage = usage[:usage.index("\nEOF\n")]
check("the usage text names no round", not re.search(r"\brounds?\b", usage, re.I))
check("the usage text says attendees bootstrap the 'attendee' profile", "the 'attendee' profile" in usage)
check("the per-round account knobs are gone", "WIB_ACCOUNT_R" not in src)
check("the 'rounds' selector alias is gone", "instructors|rounds)" not in src)
check("the provision spec carries no bootstrap round", "BOOTSTRAP_ROUND" not in src and "bround" not in src)
check("bootstrap_one takes a name and a profile, no round",
      'local name="$1" profile="$2"\n' in function_src(src, "bootstrap_one"))
arm = comment_above(src, "arm_infra_guardrails") + function_src(src, "arm_infra_guardrails")
check("arm_infra_guardrails and its comment say no round", not re.search(r"\bround\b", arm, re.I))
check("bootstrap_profile_for_role: community gets burn",
      fleet_q("bootstrap_profile_for_role community") == "burn")
check("bootstrap_profile_for_role: admin gets admin", fleet_q("bootstrap_profile_for_role admin") == "admin")
check("cmd_instructors takes the profile from bootstrap_profile_for_role",
      'bp="$(bootstrap_profile_for_role "${r}")"' in function_src(src, "cmd_instructors"))

print("== setup-instructor-cluster.sh takes a roster cluster, not a round ==")
setup = SETUP.read_text(encoding="utf-8")
check("its usage takes a roster cluster name and an optional profile",
      "Usage: ${0##*/} <roster-cluster-name> [aws-profile]" in setup)
check("it keeps no role-to-profile map of its own",
      'fleet_q bootstrap_profile_for_role "${ROLE}"' in setup and "BOOT=burn" not in setup
      and "BOOT=full" not in setup)

with tempfile.TemporaryDirectory() as tmp:
    shim = pathlib.Path(tmp) / "bin"
    shim.mkdir()
    calls = pathlib.Path(tmp) / "calls"
    # aws and kubectl record their arguments and fail, so a run stops at the first cloud step it reaches.
    for tool in ("aws", "kubectl"):
        (shim / tool).write_text(f'#!/usr/bin/env bash\necho "{tool} $*" >>"{calls}"\nexit 1\n')
        (shim / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}"}

    def run(*args: str) -> tuple[int, str, str]:
        if calls.exists():
            calls.unlink()
        r = subprocess.run(["bash", str(SETUP), *args], env=env, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stderr, calls.read_text() if calls.exists() else ""

    for args, why in ((("watch-it-burn-attendee-007",), "an attendee cluster"),
                      (("watch-it-burn-michael-student",), "a retired presenter student name"),
                      (("some-other-cluster",), "a cluster that is not the fleet's"),
                      (("watch-it-burn-community", "2"), "the old round argument"),
                      (("watch-it-burn-michael-admin", "3"), "the old round argument on an admin cluster")):
        rc, err, called = run(*args)
        check(f"refuses {why} before touching AWS", rc != 0 and called == "")
    rc, err, _ = run("watch-it-burn-community", "2")
    check("says why it refuses a bare number", "rounds are gone" in err)

    rc, err, called = run("watch-it-burn-whitney-admin")
    want = fleet_q("account_for_role admin")
    check("a roster cluster defaults to the account fleet.sh gives its role",
          bool(want) and f"({want}/us-west-2)" in err)
    check("and reaches the kubeconfig step with that cluster's name",
          "eks update-kubeconfig" in called and "--name watch-it-burn-whitney-admin" in called)
    rc, err, called = run("watch-it-burn-community", "aws1-student31")
    check("an explicit profile wins", "(aws1-student31/us-west-2)" in err)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All round-retirement checks passed.")
