#!/usr/bin/env python3
# ABOUTME: The plan-time policy check: the Kyverno JSON-mode policies, then Checkov and Trivy, over plan JSON.
# ABOUTME: Usage: check-plan.py [--require-all-exceptions-used] <plan.json>...; non-zero names every broken policy.
#
# Input is `terraform show -json <planfile>` (or `tofu show -json`, which writes the same format). The
# check reads the plan, not the HCL, so it judges what an apply would actually create, module internals
# included, and it does not care which binary made the plan.
#
# Order and gating (#200):
#   1. Kyverno CLI, `kyverno apply <policies> --json <plan>`: the four starter policies in policies/.
#      Any fail, error, warn or skip fails the check.
#   2. Checkov and Trivy over the same plan. A finding fails the check when its rule is in gates.yaml and
#      the exact (tool, rule, address) is not in exceptions.md. Every other finding is printed as advisory.
#
# Nothing can be quietly excused from outside this directory. Both scanners run from an empty working
# directory with their environment overrides stripped, so a stray .checkov.yaml, .trivyignore, trivy.yaml,
# TRIVY_SEVERITY or CKV_* variable cannot narrow what they check. Checkov gets no repo root, so
# `#checkov:skip` comments in the HCL are not applied. A scanner that reports a skipped check fails.
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
TOOLS = ("kyverno", "checkov", "trivy")
SCANNER_ENV_PREFIXES = ("TRIVY_", "CKV_", "BC_", "PRISMA_", "CHECKOV_")


def load_exceptions() -> list[dict]:
    """The table under '## Exceptions' in exceptions.md, one dict per row."""
    rows, in_table = [], False
    for line in (HERE / "exceptions.md").read_text().splitlines():
        if line.startswith("## "):
            in_table = line.strip() == "## Exceptions"
            continue
        if not in_table or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("Tool", "") or set(cells[0]) <= {"-"}:
            continue
        if len(cells) != 4:
            raise SystemExit(f"exceptions.md: row does not have 4 cells: {line}")
        tool, rule, address, reason = cells
        rows.append({"tool": tool, "rule": rule, "address": address.strip("`"), "reason": reason})
    return rows


def policy_names() -> list[str]:
    return [yaml.safe_load(p.read_text())["metadata"]["name"] for p in sorted(POLICY_DIR.glob("*.yaml"))]


def config_errors(exceptions: list[dict], gates: dict) -> list[str]:
    errors, names = [], set(policy_names())
    for row in exceptions:
        where = f"exceptions.md row {row['tool']} {row['rule']} {row['address']}"
        if row["tool"] not in TOOLS:
            errors.append(f"{where}: tool must be one of {', '.join(TOOLS)}")
        elif row["tool"] == "kyverno" and row["rule"] not in names:
            errors.append(f"{where}: no policy named {row['rule']} in policies/")
        elif row["tool"] != "kyverno" and row["rule"] not in gates.get(row["tool"], {}):
            errors.append(f"{where}: {row['rule']} is not a gated {row['tool']} rule in gates.yaml, so it excuses nothing")
        if not row["reason"]:
            errors.append(f"{where}: no reason given")
    for tool, rules in gates.items():
        for rule, policy in rules.items():
            if policy not in names:
                errors.append(f"gates.yaml {tool} {rule}: maps to {policy}, which is not a policy in policies/")
    return errors


def tool_version(cmd: list[str], pattern: str) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except FileNotFoundError:
        return None
    m = re.search(pattern, out, re.MULTILINE)
    return m.group(1) if m else "unparseable: " + out.strip()[:80]


def version_errors(pins: dict) -> list[str]:
    found = {
        "kyverno": tool_version(["kyverno", "version"], r"^Version:\s*v?(\S+)"),
        "checkov": tool_version(["checkov", "--version"], r"^(\d+\.\d+\.\d+)"),
        "trivy": tool_version(["trivy", "--version"], r"^Version:\s*v?(\S+)"),
    }
    errors = []
    for tool, got in found.items():
        want = str(pins["binaries"].get(tool, pins["python"].get(tool, {})).get("version"))
        if got is None:
            errors.append(f"{tool} is not on PATH (install the pinned set: python3 {HERE / 'install-tools.py'} <dir>)")
        elif got != want:
            errors.append(f"{tool} is {got}, pinned {want} in tools.yaml")
    return errors


def scanner_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith(SCANNER_ENV_PREFIXES) or k == "TRIVY_CACHE_DIR"}


def run_kyverno(plan: Path, policies: list[Path]) -> tuple[list[str], dict[str, str], str]:
    """(problems other than a named failure, {policy: message} for each failure, raw output)."""
    proc = subprocess.run(["kyverno", "apply", *map(str, policies), "--json", str(plan)],
                          capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    # The CLI loads ZERO policies from a relative directory path and still exits 0, so the count it
    # reports is checked against the files given, not trusted.
    applied = re.search(r"Applying (\d+) policy rule", out)
    summary = re.search(r"pass: (\d+), fail: (\d+), warn: (\d+), error: (\d+), skip: (\d+)", out)
    failures = dict(re.findall(r"^policy (\S+) -> resource .*?failed:\n\d+ -\s+(.*)$", out, re.MULTILINE))
    problems = []
    if applied is None or int(applied.group(1)) != len(policies):
        problems.append(f"kyverno applied {applied.group(1) if applied else 'no'} policies of the {len(policies)} given")
    if summary is None:
        problems.append(f"kyverno printed no result summary (exit {proc.returncode})")
    else:
        counts = dict(zip(("pass", "fail", "warn", "error", "skip"), map(int, summary.groups())))
        problems += [f"kyverno reported {counts[k]} {k}" for k in ("warn", "error", "skip") if counts[k]]
        if counts["fail"] != len(failures):
            problems.append(f"kyverno reported {counts['fail']} fail but named {len(failures)}")
    if proc.returncode != 0 and not failures and not problems:
        problems.append(f"kyverno exited {proc.returncode}")
    return problems, failures, out


def unexempted_offenders(plan: Path) -> dict[str, str]:
    """Each policy's failure message with its exempt list emptied: shows which exemptions this plan used."""
    with tempfile.TemporaryDirectory() as tmp:
        copies = []
        for p in sorted(POLICY_DIR.glob("*.yaml")):
            doc = yaml.safe_load(p.read_text())
            for var in doc["spec"]["variables"]:
                if var["name"] == "exempt":
                    var["expression"] = "[]"
            copy = Path(tmp) / p.name
            copy.write_text(yaml.safe_dump(doc))
            copies.append(copy)
        return run_kyverno(plan, copies)[1]


def run_checkov(plan: Path, managed: int) -> tuple[list[tuple[str, str, str]], list[str]]:
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(
            ["checkov", "-f", str(plan), "--framework", "terraform_plan", "--quiet", "--compact",
             "-o", "json", "--soft-fail", "--skip-download"],
            capture_output=True, text=True, cwd=cwd, env=scanner_env(), timeout=900)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], [f"checkov produced no JSON report (exit {proc.returncode}): {proc.stderr.strip()[-400:]}"]
    reports = report if isinstance(report, list) else [report]
    findings, errors = [], []
    scanned = sum(r.get("summary", r).get("resource_count", 0) for r in reports)
    if managed and not scanned:
        errors.append(f"checkov scanned 0 resources of a plan with {managed}: it checked nothing")
    for r in reports:
        results = r.get("results", {})
        if results.get("skipped_checks"):
            errors.append(f"checkov skipped {len(results['skipped_checks'])} check(s); skips belong in exceptions.md")
        for c in results.get("failed_checks", []):
            findings.append((c["check_id"], c.get("resource_address") or c["resource"], c["check_name"]))
    return findings, errors


def trivy_addresses(plan_doc: dict) -> dict[str, list[str]]:
    """Trivy renames a module's resources to <name>_<md5 of the module address>; map them back."""
    index: dict[str, list[str]] = {}
    for rc in plan_doc.get("resource_changes", []):
        if rc.get("mode") != "managed":
            continue
        name = rc["name"]
        if rc.get("module_address"):
            name += "_" + hashlib.md5(rc["module_address"].encode()).hexdigest()  # noqa: S324 (Trivy's own scheme)
        index.setdefault(f"{rc['type']}.{name}", []).append(rc["address"])
    return index


def run_trivy(plan: Path, plan_doc: dict, managed: int) -> tuple[list[tuple[str, tuple[str, ...], str]], list[str]]:
    with tempfile.TemporaryDirectory() as cwd:
        # --skip-check-update: evaluate with the checks embedded in the pinned binary, not whatever bundle
        # is newest today, so the same plan gets the same verdict next month.
        proc = subprocess.run(
            ["trivy", "config", "--quiet", "--skip-check-update", "--include-non-failures", "--format", "json",
             "--severity", "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL", "--exit-code", "0", str(plan)],
            capture_output=True, text=True, cwd=cwd, env=scanner_env(), timeout=900)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], [f"trivy produced no JSON report (exit {proc.returncode}): {proc.stderr.strip()[-400:]}"]
    index, findings, errors, evaluated = trivy_addresses(plan_doc), [], [], 0
    for result in report.get("Results") or []:
        for m in result.get("Misconfigurations") or []:
            evaluated += 1
            if m.get("Status") != "FAIL":
                continue
            resource = m.get("CauseMetadata", {}).get("Resource", "")
            findings.append((m["ID"], tuple(index.get(resource, [resource])), m["Title"]))
    if managed and not evaluated:
        errors.append(f"trivy evaluated 0 checks on a plan with {managed} managed resources: it checked nothing")
    return findings, errors


def check_plan(path: Path, gates: dict, exceptions: list[dict], used: set) -> list[str]:
    """Prints the report for one plan; returns the policy failures, one line each."""
    failures: list[str] = []
    plan = path.resolve()
    doc = json.loads(plan.read_text())
    if "format_version" not in doc or "planned_values" not in doc:
        return [f"{path}: not a plan (expected `terraform show -json <planfile>` output)"]
    managed = sum(1 for rc in doc.get("resource_changes", []) if rc.get("mode") == "managed")
    print(f"\n== {path} (plan from version {doc.get('terraform_version', '?')}, {managed} managed resources)")

    policies = sorted(POLICY_DIR.glob("*.yaml"))
    print(f"\n-- kyverno: {len(policies)} policies in {POLICY_DIR.relative_to(HERE.parents[2])}")
    problems, kfail, raw = run_kyverno(plan, policies)
    print(raw.strip())
    for policy, message in kfail.items():
        failures.append(f"{policy} (kyverno): {message}")
    failures += [f"{p} (see its output above)" for p in problems]
    exempt_rows = [e for e in exceptions if e["tool"] == "kyverno"]
    if exempt_rows:
        unexempted = unexempted_offenders(plan)
        for e in exempt_rows:
            # Bounded, so aws_s3_bucket.x is not "used" by an offender named module.y.aws_s3_bucket.x.
            if re.search(rf"(?<![\w.\]]){re.escape(e['address'])}(?![\w.\[])", unexempted.get(e["rule"], "")):
                used.add((e["tool"], e["rule"], e["address"]))
                print(f"  EXCEPTED  {e['rule']}  {e['address']}  (exceptions.md)")

    excused = {(e["tool"], e["rule"], e["address"]) for e in exceptions}
    ck_findings, ck_errors = run_checkov(plan, managed)
    tv_findings, tv_errors = run_trivy(plan, doc, managed)
    scanner_findings = [("checkov", rule, (addr,), title) for rule, addr, title in ck_findings]
    scanner_findings += [("trivy", rule, addrs, title) for rule, addrs, title in tv_findings]
    for tool, errors in (("checkov", ck_errors), ("trivy", tv_errors)):
        rows = sorted({f for f in scanner_findings if f[0] == tool}, key=lambda f: (f[1] not in gates[tool], f[1], f[2]))
        print(f"\n-- {tool}: {len(rows)} findings, {sum(1 for f in rows if f[1] in gates[tool])} on gated rules")
        for _, rule, addrs, title in rows:
            label = ", ".join(addrs)
            if rule not in gates[tool]:
                print(f"  advisory  {rule}  {label}  {title}")
            elif all((tool, rule, a) in excused for a in addrs):
                used.update((tool, rule, a) for a in addrs)
                print(f"  EXCEPTED  {gates[tool][rule]}  {rule}  {label}  (exceptions.md)")
            else:
                print(f"  FAIL      {gates[tool][rule]}  {rule}  {label}  {title}")
                failures.append(f"{gates[tool][rule]} ({tool} {rule}): {label}")
        for err in errors:
            print(f"  ERROR     {err}")
            failures.append(f"{tool}: {err}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plans", nargs="+", type=Path, help="plan JSON from `terraform show -json` or `tofu show -json`")
    ap.add_argument("--require-all-exceptions-used", action="store_true",
                    help="fail when an exceptions.md row matched no finding in any of the plans (stale exception)")
    args = ap.parse_args()

    gates = yaml.safe_load((HERE / "gates.yaml").read_text())
    exceptions = load_exceptions()
    setup = config_errors(exceptions, gates) + version_errors(yaml.safe_load((HERE / "tools.yaml").read_text()))
    if setup:
        print("PLAN POLICY CHECK CANNOT RUN:", *setup, sep="\n  - ", file=sys.stderr)
        sys.exit(2)

    used: set = set()
    failures = {str(p): check_plan(p, gates, exceptions, used) for p in args.plans}
    unused = [e for e in exceptions if (e["tool"], e["rule"], e["address"]) not in used]

    print("\n== summary")
    for e in unused:
        print(f"  unused exception: {e['tool']} {e['rule']} {e['address']}")
    bad = False
    for plan, lines in failures.items():
        print(f"  {plan}: {'FAIL' if lines else 'pass'}")
        for line in lines:
            print(f"    {line}")
        bad = bad or bool(lines)
    if args.require_all_exceptions_used and unused:
        print(f"  FAIL: {len(unused)} exception(s) in exceptions.md matched nothing; remove them or fix the address")
        bad = True
    if bad:
        sys.exit(1)
    print("PLAN POLICY CHECK PASSED")


if __name__ == "__main__":
    main()
