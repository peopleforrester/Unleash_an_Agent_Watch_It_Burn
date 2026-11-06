# ABOUTME: Offline check of infra/terraform/aws/audit/import-state.sh (#955): its import list is main.tf's resources one
# ABOUTME: for one, with the names main.tf builds, and it refuses a live state and reports an unclean plan, all on fakes.
"""Offline: python3, bash and the repo. terraform and aws are fakes first on PATH, ahead of the no-cloud stubs, so
nothing here reaches an account. The script is run from a copy of its directory layout in a temp dir, so the repo's
own gitignored audit states are never read or written.

The script is the way back when an audit state is lost, as run 17588's was when its worktree was retired. If a
resource is added to main.tf and not to the script, a rebuilt state silently misses it and a later destroy leaves it
standing; so the list is held to main.tf here.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
AUDIT = REPO / "infra/terraform/aws/audit"
SCRIPT = AUDIT / "import-state.sh"
MAIN = (AUDIT / "main.tf").read_text(encoding="utf-8")
FLOOR = (REPO / "docs/floor.md").read_text(encoding="utf-8")
EVENT_SH = REPO / "infra/terraform/fleet/event.sh"
ACCOUNT = "123456789012"
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """The checks below rest on these lines of main.tf; a reworded one is named, not read as a broken check."""
    if literal not in text:
        sys.exit(f"anchor missing: {literal!r} is not in {where}; the import ids below are built from it")


for lit in ('name       = "watch-it-burn"', 'bucket     = "watch-it-burn-audit-${local.account_id}-${var.region}"',
            'name                 = "${local.name}-config-recorder"', 'name = "config-delivery"',
            'policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWS_ConfigRole"'):
    anchor(MAIN, lit, "infra/terraform/aws/audit/main.tf")
anchor(EVENT_SH.read_text(encoding="utf-8"), 'WIB_EVENT="${WIB_EVENT:-', "infra/terraform/fleet/event.sh")
EVENT = re.search(r'WIB_EVENT="\$\{WIB_EVENT:-([^}]*)\}"', EVENT_SH.read_text(encoding="utf-8")).group(1)

FAKE_TF = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"${FAKE_LOG}"
args=" $* "
case "${args}" in
  *" state list "*) [[ -f "${FAKE_STATE_LIST:-}" ]] && cat "${FAKE_STATE_LIST}"; exit 0 ;;
  *" import "*) [[ -n "${FAKE_IMPORT_FAIL:-}" && "${args}" == *" ${FAKE_IMPORT_FAIL} "* ]] && exit 1; exit 0 ;;
  *" plan "*) echo "fake plan body"; exit "${FAKE_PLAN_RC:-0}" ;;
  *) exit 0 ;;
esac
"""
FAKE_AWS = r"""#!/usr/bin/env bash
printf 'aws %s\n' "$*" >>"${FAKE_LOG}"
printf '%s\n' "${FAKE_ACCOUNT}"
"""


def run(tmp: pathlib.Path, args: list[str], *, state: str | None = None, account: str = ACCOUNT,
        plan_rc: int = 0, import_fail: str = "", init: bool = True) -> tuple[int, str, list[str]]:
    root = tmp / f"case{len(list(tmp.iterdir()))}"
    audit = root / "infra/terraform/aws/audit"
    fleet = root / "infra/terraform/fleet"
    audit.mkdir(parents=True)
    fleet.mkdir(parents=True)
    shutil.copy(SCRIPT, audit / "import-state.sh")
    shutil.copy(EVENT_SH, fleet / "event.sh")
    if init:
        (audit / ".terraform").mkdir()
    env = {k: v for k, v in os.environ.items() if k != "WIB_EVENT"}
    if state is not None:
        (audit / "states").mkdir()
        (audit / "states/p1.tfstate").write_text('{"version": 4}\n')
        (root / "state-list").write_text(state)
        env["FAKE_STATE_LIST"] = str(root / "state-list")
    bindir = root / "bin"
    bindir.mkdir()
    for name, body in (("terraform", FAKE_TF), ("aws", FAKE_AWS)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = root / "calls"
    log.write_text("")
    env.update(PATH=f"{bindir}:{env['PATH']}", FAKE_LOG=str(log), FAKE_ACCOUNT=account, FAKE_PLAN_RC=str(plan_rc),
               FAKE_IMPORT_FAIL=import_fail)
    p = subprocess.run(["bash", str(audit / "import-state.sh"), *args], env=env, capture_output=True, text=True,
                       timeout=60)
    return p.returncode, p.stdout + p.stderr, log.read_text().splitlines()


def main() -> int:
    resources = re.findall(r'^resource "([a-z0-9_]+)" "([a-z0-9_]+)"', MAIN, re.M)
    want = [f"{t}.{n}" for t, n in resources]
    print(f"main.tf manages {len(want)} resources")
    check("main.tf manages resources at all (the regex still reads it)", len(want) >= 10)

    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)

        rc, out, calls = run(tmp, ["p1"])
        imports = [c for c in calls if c.startswith("-chdir=") and " import " in f" {c} "]
        addrs = [c.split()[-2] for c in imports]
        ids = {c.split()[-2]: c.split()[-1] for c in imports}
        check(f"a clean rebuild exits 0 and says the plan is clean (rc {rc})", rc == 0 and "plan: no changes" in out)
        check(f"the script imports every resource main.tf manages, once each (missing {sorted(set(want) - set(addrs))},"
              f" extra {sorted(set(addrs) - set(want))})", sorted(addrs) == sorted(want) and len(addrs) == len(set(addrs)))
        bucket = f"watch-it-burn-audit-{ACCOUNT}-us-west-2"
        role = "watch-it-burn-config-recorder"
        expect = {
            "aws_s3_bucket.audit": bucket,
            "aws_s3_bucket_policy.audit": bucket,
            "aws_iam_role.config": role,
            "aws_iam_role_policy_attachment.config": f"{role}/arn:aws:iam::aws:policy/service-role/AWS_ConfigRole",
            "aws_iam_role_policy.config_delivery": f"{role}:config-delivery",
            "aws_config_configuration_recorder.fleet": "watch-it-burn",
            "aws_cloudtrail.fleet": f"arn:aws:cloudtrail:us-west-2:{ACCOUNT}:trail/watch-it-burn",
        }
        for addr, want_id in expect.items():
            check(f"{addr} is imported by {want_id}", ids.get(addr) == want_id)
        check("every bucket-scoped resource is imported by the bucket's name",
              all(v == bucket for k, v in ids.items() if k.startswith("aws_s3_bucket")))
        tf_calls = [c for c in calls if c.startswith("-chdir=")]
        writes = [c for c in tf_calls if re.search(r" (import|apply|plan) ", f" {c} ")]
        check("every import, apply and plan names the state, the profile, the region and event.sh's event",
              bool(writes) and all("-state=states/p1.tfstate" in c and "-var profile=p1" in c and
                                   "-var region=us-west-2" in c and f"-var event={EVENT}" in c for c in writes))
        verbs = [("refresh" if "-refresh-only" in c else "target" if "-target=aws_s3_bucket.audit" in c else
                  c.split()[1]) for c in writes]
        last_import = max(i for i, v in enumerate(verbs) if v == "import")
        check(f"after the imports: a refresh-only apply, the bucket's targeted apply, then the plan ({verbs[last_import + 1:]})",
              verbs[last_import + 1:] == ["refresh", "target", "plan"])
        check("the only apply that is not refresh-only is targeted at the bucket alone",
              all("-refresh-only" in c or c.count("-target=") == 1 and "-target=aws_s3_bucket.audit " in f"{c} "
                  for c in writes if " apply " in f" {c} "))
        check("the plan asks for a detailed exit code", any(" plan " in f" {c} " and "-detailed-exitcode" in c
                                                            for c in writes))
        check("the account is read through the profile it was given",
              any(c.startswith("aws sts get-caller-identity") and "--profile p1" in c for c in calls))

        rc, out, calls = run(tmp, ["p1"], state="data.aws_caller_identity.current\naws_cloudtrail.fleet\n")
        check(f"a state that manages a resource is refused, naming it (rc {rc})",
              rc == 1 and "refusing" in out and "aws_cloudtrail.fleet" in out)
        check("nothing is imported or applied over a live state",
              not any(re.search(r" (import|apply|plan) ", f" {c} ") for c in calls))

        rc, out, calls = run(tmp, ["p1"], state="data.aws_caller_identity.current\n")
        check(f"a state holding only data sources is rebuilt (rc {rc})",
              rc == 0 and sum(" import " in f" {c} " for c in calls) == len(want))

        rc, out, calls = run(tmp, ["p1"], plan_rc=2)
        check(f"a plan with changes fails and prints the plan (rc {rc})",
              rc == 1 and "fake plan body" in out and "not clean" in out)

        rc, out, calls = run(tmp, ["p1"], import_fail="aws_iam_role.config")
        check(f"a failed import stops the run and names the resource (rc {rc})",
              rc == 1 and "aws_iam_role.config" in out and not any(" plan " in f" {c} " for c in calls))

        rc, out, calls = run(tmp, [])
        check(f"no profile is a usage error with no call made (rc {rc})", rc == 1 and "usage" in out and not calls)

        rc, out, calls = run(tmp, ["p1"], account="None")
        check(f"an account that is not 12 digits stops before any import (rc {rc})",
              rc == 1 and not any(" import " in f" {c} " for c in calls))

        rc, out, calls = run(tmp, ["p1"], init=False)
        check(f"an uninitialised root is refused (rc {rc})", rc == 1 and "init" in out and not calls)

    check("docs/floor.md gives the rebuild command", "infra/terraform/aws/audit/import-state.sh <profile>" in FLOOR)

    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nimport-state.sh checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
