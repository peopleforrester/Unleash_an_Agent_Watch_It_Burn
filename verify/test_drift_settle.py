# ABOUTME: Every documented apply of the lab VPC, boundary or audit root is followed by a refresh-only apply with the
# ABOUTME: same arguments (#956), so a fresh state does not read as drifted in the next drift report.
"""Offline: python3, git and the repo.

A fresh apply leaves attributes AWS reads back unwritten. On 2026-11-06 a fresh lab VPC state read five resources as
changed outside Terraform in a refresh-only plan (route tables, the NAT address, the default ACL and route table) and
a fresh boundary state one (`tags: null -> {}`), as the audit root's three had on 2026-11-05 (#795). The drift report
cannot tell that from an out-of-band change, so each apply is followed by `apply -refresh-only -auto-approve` with the
same arguments (docs/floor.md, "Settling a fresh state").

These three roots are applied by hand, so what holds the step is the commands a person copies: every tracked
document, root header and printed hint outside the history records and the tests. For each `terraform apply` of one
of them that is not itself refresh-only, a refresh-only apply of the same root with the same arguments must follow
it, later in the same line or within the next three lines. The cluster root is applied by fleet.sh, and
test_fleet_settle_after_apply.sh holds that step by running it.

The parser is checked first on cases this file owns, so a parser that finds nothing cannot pass the repo.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# The roots, by how each document names its directory: a path, the shell variable fleet.sh and preflight.sh use,
# or the f-string field backups.py uses.
ROOTS = {
    "network": re.compile(r"(aws/network|LAB_VPC_DIR|\{lab\})"),
    "boundary": re.compile(r"(org/boundary|BOUNDARY_DIR)"),
    "audit": re.compile(r"aws/audit"),
}
# History is not a command anyone copies; the tests quote commands to check them.
SKIP_FILES = {"decisions.md", "PROGRESS.md", "PROJECT_STATE.md", "docs/DECISION-LOG.md"}
SKIP_DIRS = ("verify/",)
SUFFIXES = (".md", ".tf", ".sh", ".py")
# Flags that say how to run, not what to apply; the settle adds the first two.
RUN_FLAGS = {"-refresh-only", "-auto-approve", "-no-color", "-input=false"}
TF = re.compile(r"\bterraform(?:\s+-chdir=(\S+))?\s+apply\b(.*)")
CD = re.compile(r"\bcd\s+(\S+)")
WINDOW = 3


def root_of(where: str) -> str | None:
    for name, rx in ROOTS.items():
        if rx.search(where):
            return name
    return None


def applies(line: str):
    """(root, refresh_only, args) for each `terraform apply` of a tracked root in one line, in order. A line is split
    on `&&`; a `cd <dir>` earlier in the line is the directory of an apply that carries no -chdir."""
    cwd = None
    out = []
    for seg in line.split("&&"):
        m_cd = CD.search(seg)
        if m_cd and "terraform" not in seg[: m_cd.start()]:
            cwd = m_cd.group(1)
        m = TF.search(seg)
        if not m:
            continue
        root = root_of(m.group(1) or cwd or "")
        if root is None:
            continue
        # The arguments end where the command does: a closing backtick, quote or parenthesis of the text around it.
        rest = re.split(r"[`\"')]", m.group(2), maxsplit=1)[0]
        toks = rest.split()
        out.append((root, "-refresh-only" in toks, tuple(sorted(t for t in toks if t not in RUN_FLAGS))))
    return out


def unsettled(lines: list[str]) -> list[tuple[int, str]]:
    """(line number, root) of every apply with no refresh-only apply of the same root and arguments after it."""
    found = [(i, k, a) for i, ln in enumerate(lines) for k, a in enumerate(applies(ln))]
    bad = []
    for i, k, (root, refresh, args) in found:
        if refresh:
            continue
        settled = any(r == root and rf and ag == args and (j > i or (j == i and kk > k)) and j - i <= WINDOW
                      for j, kk, (r, rf, ag) in found)
        if not settled:
            bad.append((i + 1, root))
    return bad


print("== the parser, on cases this test owns ==")
E = '-var profile=<p> -var event="${WIB_EVENT}"'
cases = {
    "settled on the next line": ([f"terraform -chdir=infra/org/boundary apply -state=s {E}",
                                  f"terraform -chdir=infra/org/boundary apply -refresh-only -auto-approve -state=s {E}"],
                                 []),
    "settled later on the same line, after a cd": (
        [f"cd aws/network && terraform init && terraform apply {E} && terraform apply -refresh-only -auto-approve {E}"],
        []),
    "no settle": ([f"terraform -chdir=infra/terraform/aws/audit apply -state=s {E}"], [(1, "audit")]),
    "a settle with other arguments": ([f"terraform -chdir=infra/org/boundary apply -state=a {E}",
                                       f"terraform -chdir=infra/org/boundary apply -refresh-only -auto-approve -state=b {E}"],
                                      [(1, "boundary")]),
    "a settle of another root": ([f"terraform -chdir=${{LAB_VPC_DIR}} apply -state=s {E}",
                                  f"terraform -chdir=${{BOUNDARY_DIR}} apply -refresh-only -auto-approve -state=s {E}"],
                                 [(1, "network")]),
    "a settle before the apply": ([f"terraform -chdir=infra/org/boundary apply -refresh-only -auto-approve -state=s {E}",
                                   f"terraform -chdir=infra/org/boundary apply -state=s {E}"],
                                  [(2, "boundary")]),
    "a settle too far below": ([f"terraform -chdir=infra/org/boundary apply -state=s {E}", "", "", "",
                                f"terraform -chdir=infra/org/boundary apply -refresh-only -auto-approve -state=s {E}"],
                               [(1, "boundary")]),
    "a quoted hint ends at its quote": (
        ['x="terraform -chdir=${BOUNDARY_DIR} apply -state=s -var event=e && terraform -chdir=${BOUNDARY_DIR} apply '
         '-refresh-only -auto-approve -state=s -var event=e"; y'],
        []),
    "the f-string field backups.py prints": (
        ['log(f"  terraform -chdir={lab} init && terraform -chdir={lab} apply {args} "',
         '    f"&& terraform -chdir={lab} apply -refresh-only -auto-approve {args}")'],
        []),
    "a cluster apply is not this test's": ([f"terraform -chdir=cluster apply -state=s {E}"], []),
}
for name, (lines, want) in cases.items():
    got = unsettled(lines)
    check(f"{name}: {want or 'settled'}", got == want, f"got {got}")

print("== every documented apply of the lab VPC, boundary and audit roots is settled ==")
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
files = [f for f in tracked if f.endswith(SUFFIXES) and f not in SKIP_FILES and not f.startswith(SKIP_DIRS)]
seen: dict[str, int] = {}
missing: list[str] = []
for rel in files:
    path = REPO / rel
    if not path.is_file():
        continue
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    n = sum(1 for ln in lines for _, refresh, _ in applies(ln) if not refresh)
    if n:
        seen[rel] = n
    missing += [f"{rel}:{ln} ({root})" for ln, root in unsettled(lines)]

# Where the commands are today. A document that loses its apply is fine; one the parser stops seeing is not, so the
# set is checked as a floor rather than left to whatever the scan happens to find.
EXPECTED = {
    "docs/BUILD-SPEC.md", "docs/MASTER-RECREATION-SPEC.md", "docs/floor.md",
    "facilitation/kubecon-na-2026-run-of-show.md", "infra/attendee-cluster/README.md", "infra/org/README.md",
    "infra/org/boundary/main.tf", "infra/shared-vpc/README.md", "infra/terraform/README.md",
    "infra/terraform/aws/audit/main.tf", "infra/terraform/fleet/backups.py", "infra/terraform/fleet/fleet.sh",
    "infra/terraform/fleet/preflight.sh",
}
check(f"the scan finds the documented applies ({sum(seen.values())} in {len(seen)} files)",
      EXPECTED <= set(seen), f"not found in: {sorted(EXPECTED - set(seen))}")
check("each is followed by a refresh-only apply of the same root with the same arguments",
      not missing, "unsettled: " + ", ".join(missing))

print("== floor.md explains the step for every root ==")
FLOOR = (REPO / "docs/floor.md").read_text(encoding="utf-8")
section = FLOOR.split("### Settling a fresh state", 1)[1].split("\n### ", 1)[0] if "### Settling a fresh state" in FLOOR else ""
check("floor.md has a 'Settling a fresh state' section", bool(section))
for word in ("lab VPC", "boundary", "audit", "fleet.sh", "test_drift_settle.py", "test_fleet_settle_after_apply.sh"):
    check(f"and it names {word}", word in section)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Every documented apply of the lab VPC, boundary and audit roots is settled.")
