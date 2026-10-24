# ABOUTME: Rounds 1/2/3 are retired fleet-wide (#290). No code path may still name one: not a route alias, not
# ABOUTME: the lab page's role check, not a script argument, not a comment. Only dated records may name the old clusters.
"""The round nomenclature is gone from the code, not just from the docs (#290).

The restructure replaced Round 1/2/3 with one Community cluster, two admin clusters and the attendee pool.
`test_docs_current.py` keeps the markdown honest and `test_cluster_roles.sh` pins the roster. Neither looked
at the code, and the code still spoke rounds in three places that DID something:

* `fleet.sh routes` published a `round<role>.agenticburn.com` alias. With roles in the roster instead of
  round numbers, that became `roundadmin.agenticburn.com`, a host nobody was ever told.
* The lab page decided INSTRUCTOR vs STUDENT by matching `watch-it-burn-r<N>-<n>` and `roundN` hostnames.
  No cluster has either name any more, so an admin cluster's lab page called its presenter a student. That
  is the same class of bug as #265, #272 and #284: two places disagreeing about what a cluster is called,
  with nothing failing.
* `infra/setup-instructor-cluster.sh` still took `<round 1|2|3>` and mapped it to a profile itself.

So the live checks here compare the lab page against fleet.sh for every kind of cluster, and the sweep
keeps the vocabulary out of every tracked file outside markdown (which test_docs_current.py owns), the tests
(which have to name the old forms to prove they are gone) and vendored code. A line that carries a date is
a record of where something was measured, and it keeps the cluster name it was measured on: rewriting it
would falsify the record.
"""
from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
LAB = REPO / "gitops/ai-layer/web/lab.html"
SETUP = REPO / "infra/setup-instructor-cluster.sh"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def fleet(expr: str) -> str:
    """Evaluate a shell expression against a sourced fleet.sh. Pure naming functions, no cloud access."""
    out = subprocess.run(
        ["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; load_roster; {expr}"],
        cwd=FLEET.parent, capture_output=True, text=True, check=False,
    )
    return out.stdout


def function_body(src: str, fn: str) -> str:
    m = re.search(rf"^{fn}\(\) \{{\n(.*?)^\}}", src, re.S | re.M)
    return m.group(1) if m else ""


FLEET_SRC = FLEET.read_text(encoding="utf-8")

print("== the lab page names a cluster's role the way fleet.sh does ==")
lab = LAB.read_text(encoding="utf-8")
name_m = re.search(r"var _rosterName=/(.+?)/i;", lab)
host_m = re.search(r"var _rosterHost=/(.+?)/i;", lab)
check("lab.html still has a roster-name and a roster-host pattern", bool(name_m and host_m))
if name_m and host_m:
    name_re = re.compile(name_m.group(1), re.I)
    host_re = re.compile(host_m.group(1), re.I)
    # Every class of cluster, plus the retired ones, which must now read as nothing special.
    names = [
        "watch-it-burn-community",
        "watch-it-burn-michael-admin",
        "watch-it-burn-whitney-admin",
        "watch-it-burn-attendee-001",
        "watch-it-burn-attendee-042",
        "watch-it-burn-michael-student",
        "watch-it-burn-r1-1",
        "watch-it-burn-r3-2",
    ]
    rows = fleet("for n in " + " ".join(names) + "; do "
                 "if is_instructor_name \"$n\"; then i=1; else i=0; fi; "
                 "printf '%s|%s|%s\\n' \"$n\" \"$i\" \"$(public_host_for \"$n\")\"; done")
    seen = 0
    for row in rows.splitlines():
        name, inst, host = row.split("|")
        seen += 1
        want = inst == "1"
        label = host.split(".")[0]
        check(f"{name}: lab reads the cluster name as {'instructor' if want else 'student'}",
              bool(name_re.match(name)) == want)
        check(f"{name}: lab reads its host {label} as {'instructor' if want else 'student'}",
              bool(host_re.match(label)) == want)
    check("fleet.sh answered for every cluster asked about", seen == len(names))

print("== fleet.sh routes publishes no round alias ==")
routes = function_body(FLEET_SRC, "cmd_routes")
routes_code = "\n".join(l for l in routes.splitlines() if not l.lstrip().startswith("#"))
check("cmd_routes was found", bool(routes))
check("cmd_routes emits no round<N> host", not re.search(r"\bround", routes_code, re.I))
check("the primary-owner knob that bound the roundN alias is gone", "WIB_PRIMARY_OWNER" not in FLEET_SRC)
check("the per-round account knobs are gone", not re.search(r"WIB_ACCOUNT_R[0-9]", FLEET_SRC))
check("no selector accepts 'rounds'", not re.search(r"\|rounds\)", FLEET_SRC))
check("the provision spec carries a role, not a round", not re.search(r"BOOTSTRAP_ROUND|\bbround\b", FLEET_SRC))

print("== a cluster's bootstrap profile follows its role, in one place ==")
check("community bootstraps burn", fleet("bootstrap_profile_for_role community") == "burn")
check("admin bootstraps admin (every guardrail armed)", fleet("bootstrap_profile_for_role admin") == "admin")
check("cmd_instructors asks bootstrap_profile_for_role",
      "bootstrap_profile_for_role" in function_body(FLEET_SRC, "cmd_instructors"))

print("== setup-instructor-cluster.sh takes a roster cluster, not a round ==")
setup_src = SETUP.read_text(encoding="utf-8")
check("it derives the role from fleet.sh", "role_of_instructor_name" in setup_src)
check("it derives the profile from fleet.sh", "bootstrap_profile_for_role" in setup_src)
with tempfile.TemporaryDirectory() as tmp:
    # A stub aws that records being called: a refusal has to happen before anything touches an account.
    stub = pathlib.Path(tmp, "aws")
    called = pathlib.Path(tmp, "aws.called")
    stub.write_text(f"#!/usr/bin/env bash\ntouch '{called}'\nexit 1\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
    for args, why in [
        (["watch-it-burn-r1-1"], "a retired round cluster"),
        (["watch-it-burn-attendee-001"], "an attendee cluster (claimed through provisioning)"),
        (["watch-it-burn-michael-student"], "a retired presenter student cluster"),
        ([], "no cluster at all"),
    ]:
        r = subprocess.run(["bash", str(SETUP), *args], capture_output=True, text=True, env=env, check=False)
        check(f"it refuses {why}, before calling aws", r.returncode != 0 and not called.exists())
    r = subprocess.run(["bash", str(SETUP)], capture_output=True, text=True, env=env, check=False)
    check("its usage names no round", not re.search(r"\bround", r.stderr, re.I))

print("== no tracked file outside the docs and tests speaks rounds ==")
SHAPES = re.compile(
    r"(?i:\brounds?[ -]?[123]\b)"          # Round 1, round-2, Rounds 2, round3, michael-round1
    r"|\bR[123]\b"                          # the R1/R2/R3 shorthand
    r"|(?i:watch-it-burn-r[0-9<])"          # watch-it-burn-r2-1, watch-it-burn-r<round>-<n>
    r"|\br[123]-[0-9]\b"                    # r1-1, r3-3
    r"|(?i:\bper-round\b|<round>|\broundN\b|\bround[ -](gating|toggle|selector|behaviou?r)\b)"
    r"|--r[123]\b"                          # CSS custom properties named for a round
)
DATED = re.compile(r"\b20[0-9]{2}-[01][0-9]-[0-3][0-9]\b")


def swept(rel: str) -> bool:
    if rel.endswith(".md"):
        return False  # test_docs_current.py owns the docs, with its own history exemptions
    if rel.startswith("verify/test_"):
        return False  # tests name the retired forms to prove they are gone
    if rel.startswith("mockups/"):
        return False  # pre-restructure design mockups, a record of what was proposed then
    if "/.yarn/" in rel or "node_modules/" in rel:
        return False  # vendored
    return True


tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
offenders: list[str] = []
scanned = 0
for rel in tracked:
    if not swept(rel):
        continue
    p = REPO / rel
    # A symlink's content belongs to its target. agent/gateway/guard-proxy/proxy.py points into the
    # guard-proxy submodule, which is its own repository and not changed from here.
    if p.is_symlink() or not p.is_file():
        continue
    raw = p.read_bytes()
    if b"\0" in raw:
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue
    scanned += 1
    for i, line in enumerate(text.splitlines(), 1):
        m = SHAPES.search(line)
        if m and not DATED.search(line):
            offenders.append(f"{rel}:{i}: {m.group(0)!r}")
check(f"the sweep read the repo ({scanned} files)", scanned > 200)
check("no round vocabulary in code, config or scripts"
      + (f" (found {len(offenders)}: {offenders[:6]})" if offenders else ""), not offenders)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All round-retirement checks passed.")
