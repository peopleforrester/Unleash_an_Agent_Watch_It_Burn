#!/usr/bin/env python3
# ABOUTME: The IAM policy pipeline (#207): pulls every policy document out of `terraform show -json` and runs
# ABOUTME: syntax (Access Analyzer), semantic diff (check-no-new-access), structural (conftest) and effect checks.
"""Usage:

  pipeline.py extract    --show SHOW.json
  pipeline.py structural --show SHOW.json
  pipeline.py syntax     --show SHOW.json --profile P --region R
  pipeline.py diff       --show SHOW.json --base BASE.json --profile P --region R [--accept-new ADDRESS ...]
  pipeline.py effect     --show SHOW.json --suite boundary|cluster --profile P --region R
  pipeline.py run        --show SHOW.json --base BASE.json --suite boundary|cluster --profile P --region R

SHOW.json is `terraform show -json` of a saved plan (`terraform plan -out x.tfplan; terraform show -json
x.tfplan`) or of a state file. BASE.json is the same for merged main, planned from a worktree of it. The
AWS profile and region are always passed explicitly, never read from a shared default (AGENTS.md, rule 6).

Nothing is skipped. A document that is unknown until apply cannot be checked, so it fails the run; plan
against an applied cluster's state to see every document. The structural check needs conftest on PATH (or
CONFTEST); the other three need the aws CLI and credentials, and check 2 is billed per call."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ORG = pathlib.Path(__file__).resolve().parent
POLICY_DIR = ORG / "policy"
EXCEPTIONS = ORG / "exceptions.md"
BOUNDARY_TEMPLATE = ORG / "permissions-boundary.json.tftpl"
EFFECT_TESTS = ORG / "effect-tests.yaml"
# Keep in step with infra/org/boundary/main.tf and infra/terraform/aws/cluster/main.tf.
BOUNDARY_NAME = "watch-it-burn-permissions-boundary"
# The Terraform roots the pipeline runs on, by --suite. A root that creates an IAM or org policy document
# goes here and gets a suite in effect-tests.yaml; verify/test_iam_policy_coverage.py fails on one that does not.
ROOTS = {"boundary": ORG / "boundary", "cluster": ORG.parents[1] / "infra/terraform/aws/cluster"}

# The kinds whose statements grant permission. Check 3's rules apply to these; trust and resource policies
# (a role's assume-role policy, a KMS key policy) are checked by Access Analyzer only, because their Allow
# is a grant to a principal and key policies require Resource "*" by definition.
PERMISSION_KINDS = ("identity", "boundary", "scp", "rcp")
# Check 2 compares these. check-no-new-access does not take SCPs or RCPs, which is why check 3 exists.
DIFF_KINDS = ("identity", "boundary")
RULES = ("allow-without-condition", "condition-key", "action-star", "resource-star")

# Access Analyzer's --policy-type (and --validate-policy-resource-type) for each kind.
VALIDATE_TYPES = {
    "identity": ("IDENTITY_POLICY", None),
    "boundary": ("IDENTITY_POLICY", None),
    "trust": ("RESOURCE_POLICY", "AWS::IAM::AssumeRolePolicyDocument"),
    "kms-key": ("RESOURCE_POLICY", "AWS::KMS::Key"),
    "s3-bucket": ("RESOURCE_POLICY", "AWS::S3::Bucket"),
    "scp": ("SERVICE_CONTROL_POLICY", None),
    "rcp": ("RESOURCE_CONTROL_POLICY", None),
}
ORG_POLICY_KINDS = {"SERVICE_CONTROL_POLICY": "scp", "RESOURCE_CONTROL_POLICY": "rcp"}
FAILING_FINDINGS = ("ERROR", "SECURITY_WARNING")


class PipelineError(Exception):
    """The run cannot judge what it was given. Always a failure, never a skip."""


# --- extraction --------------------------------------------------------------------------------------------

def _modules(module: dict):
    yield module
    for child in module.get("child_modules", []) or []:
        yield from _modules(child)


def _resources(show: dict, section: str) -> list[dict]:
    root = (show.get(section) or {}).get("root_module")
    if not root:
        return []
    return [r for m in _modules(root) for r in m.get("resources", []) or []]


def _managed(show: dict) -> list[dict]:
    # A saved plan carries planned_values; a state file's show carries values. Never both.
    section = "planned_values" if "planned_values" in show else "values"
    if section not in show:
        raise PipelineError("not `terraform show -json` output: it has neither planned_values nor values")
    return [r for r in _resources(show, section) if r.get("mode") == "managed"]


def _after_unknown(show: dict) -> dict[str, dict]:
    return {rc["address"]: (rc.get("change") or {}).get("after_unknown") or {}
            for rc in show.get("resource_changes", []) or []}


def _parse_doc(address: str, attribute: str, text) -> dict:
    if isinstance(text, dict):
        return text
    try:
        doc = json.loads(text)
    except (TypeError, json.JSONDecodeError) as e:
        raise PipelineError(f"{address}.{attribute} is not a JSON policy document: {e}") from e
    if not isinstance(doc, dict) or "Statement" not in doc:
        raise PipelineError(f"{address}.{attribute} has no Statement")
    return doc


def extract(show: dict) -> dict:
    """Every policy document and every role in the plan, plus whatever is known only after apply."""
    unknown_by_addr = _after_unknown(show)
    documents, roles, unknown = [], [], []

    def add(res: dict, attribute: str, kind: str, text, unknown_flag) -> None:
        addr = res["address"]
        if unknown_flag is True or (text is None and unknown_flag):
            unknown.append(f"{addr}.{attribute}")
            return
        if text in (None, ""):
            return
        documents.append({"address": addr, "attribute": attribute, "kind": kind,
                          "document": _parse_doc(addr, attribute, text)})

    for res in _managed(show):
        t, v = res["type"], res.get("values") or {}
        au = unknown_by_addr.get(res["address"], {})
        if t == "aws_iam_policy":
            name = v.get("name") or v.get("name_prefix") or ""
            add(res, "policy", "boundary" if name == BOUNDARY_NAME else "identity", v.get("policy"), au.get("policy"))
        elif t in ("aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"):
            add(res, "policy", "identity", v.get("policy"), au.get("policy"))
        elif t == "aws_iam_role":
            add(res, "assume_role_policy", "trust", v.get("assume_role_policy"), au.get("assume_role_policy"))
            inline_unknown = au.get("inline_policy")
            for i, block in enumerate(v.get("inline_policy") or []):
                flag = inline_unknown[i].get("policy") if isinstance(inline_unknown, list) and i < len(inline_unknown) else inline_unknown
                add(res, f"inline_policy[{i}].policy", "identity", block.get("policy"), flag)
            if au.get("permissions_boundary") is True:
                unknown.append(f"{res['address']}.permissions_boundary")
            roles.append({"address": res["address"], "name": v.get("name") or v.get("name_prefix"),
                          "permissions_boundary": v.get("permissions_boundary") or ""})
        elif t == "aws_kms_key":
            add(res, "policy", "kms-key", v.get("policy"), au.get("policy"))
        elif t == "aws_s3_bucket_policy":
            add(res, "policy", "s3-bucket", v.get("policy"), au.get("policy"))
        elif t == "aws_organizations_policy":
            kind = ORG_POLICY_KINDS.get(v.get("type", "SERVICE_CONTROL_POLICY"))
            if kind is None:
                # The S3 BPA and other management policy types are not IAM documents and Access Analyzer has
                # no validator for them. Extend the pipeline before adding one, do not let it pass unseen.
                raise PipelineError(f"{res['address']}: organizations policy type {v.get('type')!r} has no check")
            add(res, "content", kind, v.get("content"), au.get("content"))
    return {"documents": documents, "roles": roles, "unknown": unknown}


def require_known(ext: dict) -> None:
    if ext["unknown"]:
        raise PipelineError(
            "known only after apply, so no check can see them (plan against an applied cluster's state):\n    "
            + "\n    ".join(ext["unknown"]))


# --- exceptions.md -----------------------------------------------------------------------------------------

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")


def load_exceptions(path: pathlib.Path = EXCEPTIONS) -> list[dict]:
    """Rows of the table in exceptions.md: | `address glob` | statement | rule | why |."""
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = _ROW.match(line)
        if not m:
            continue
        address, statement, rule, why = m.groups()
        statement = statement.strip("` ")
        rule = rule.strip("` ")
        if rule not in RULES:
            raise PipelineError(f"{path.name}:{n}: rule {rule!r} is not one of {', '.join(RULES)}")
        if not why:
            raise PipelineError(f"{path.name}:{n}: an exception without a reason is not reviewable")
        rows.append({"address": address, "statement": statement, "rule": rule, "why": why})
    return rows


# --- check 3: structural (conftest) ------------------------------------------------------------------------

def conftest_binary() -> str:
    exe = os.environ.get("CONFTEST") or shutil.which("conftest")
    if not exe or not os.access(exe, os.X_OK):
        raise PipelineError("conftest is not on PATH (or set CONFTEST); the structural check cannot run. "
                            "Install v0.71.1: github.com/open-policy-agent/conftest/releases/tag/v0.71.1")
    return exe


def structural(ext: dict, exceptions: list[dict] | None = None) -> list[str]:
    """Check 3. Returns the deny messages; empty means the plan passes."""
    require_known(ext)
    exceptions = load_exceptions() if exceptions is None else exceptions
    with tempfile.TemporaryDirectory() as tmp:
        inp = pathlib.Path(tmp) / "input.json"
        data = pathlib.Path(tmp) / "data.json"
        inp.write_text(json.dumps({"documents": ext["documents"], "roles": ext["roles"],
                                   "boundary_name": BOUNDARY_NAME}), encoding="utf-8")
        data.write_text(json.dumps({"exceptions": exceptions}), encoding="utf-8")
        proc = subprocess.run([conftest_binary(), "test", "--no-color", "--output", "json", "--policy",
                               str(POLICY_DIR), "--namespace", "iam", "--data", str(data), str(inp)],
                              capture_output=True, text=True)
    try:
        results = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise PipelineError(f"conftest gave no JSON (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout}") from e
    msgs = sorted(f["msg"] for r in results for f in r.get("failures") or [])
    if proc.returncode != 0 and not msgs:
        raise PipelineError(f"conftest failed without a deny message (exit {proc.returncode}): {proc.stderr.strip()}")
    return msgs


# --- AWS calls ---------------------------------------------------------------------------------------------

def aws(profile: str, region: str, *args: str) -> dict:
    if not shutil.which("aws"):
        raise PipelineError("the aws CLI is not on PATH")
    proc = subprocess.run(["aws", *args, "--profile", profile, "--region", region, "--output", "json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise PipelineError(f"aws {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "{}")


def _compact(doc: dict) -> str:
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


# --- check 1: syntax ---------------------------------------------------------------------------------------

def syntax_failures(rec: dict, response: dict) -> list[str]:
    """Access Analyzer findings that fail the run: ERROR and SECURITY_WARNING."""
    out = []
    for f in response.get("findings", []):
        if f.get("findingType") in FAILING_FINDINGS:
            where = ", ".join(str(p.get("index", p.get("value", ""))) for loc in f.get("locations", [])
                              for p in loc.get("path", [])[:2])
            out.append(f"{rec['address']}.{rec['attribute']}: {f['findingType']} {f.get('issueCode', '')}: "
                       f"{f.get('findingDetails', '').strip()}" + (f" (at {where})" if where else ""))
    return out


def syntax(ext: dict, profile: str, region: str) -> list[str]:
    require_known(ext)
    out = []
    for rec in ext["documents"]:
        ptype, rtype = VALIDATE_TYPES[rec["kind"]]
        args = ["accessanalyzer", "validate-policy", "--policy-type", ptype,
                "--policy-document", _compact(rec["document"])]
        if rtype:
            args += ["--validate-policy-resource-type", rtype]
        out += syntax_failures(rec, aws(profile, region, *args))
    return out


# --- check 2: semantic diff --------------------------------------------------------------------------------

def diff_pairs(head: dict, base: dict) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """(changed pairs to send to check-no-new-access, documents with no base). Unchanged ones cost nothing."""
    key = lambda r: (r["address"], r["attribute"])  # noqa: E731
    base_by = {key(r): r for r in base["documents"] if r["kind"] in DIFF_KINDS}
    pairs, new = [], []
    for rec in head["documents"]:
        if rec["kind"] not in DIFF_KINDS:
            continue
        old = base_by.get(key(rec))
        if old is None:
            new.append(rec)
        elif _compact(old["document"]) != _compact(rec["document"]):
            pairs.append((rec, old))
    return pairs, new


def diff_failures(rec: dict, response: dict) -> list[str]:
    if response.get("result") == "PASS":
        return []
    reasons = "; ".join(f"Statement[{r.get('statementIndex')}] {r.get('description', '').strip()}"
                        for r in response.get("reasons", []))
    return [f"{rec['address']}.{rec['attribute']}: grants new access ({response.get('result')}): "
            f"{response.get('message', '').strip()}" + (f" [{reasons}]" if reasons else "")]


def diff(head: dict, base: dict, profile: str, region: str, accept_new: list[str]) -> list[str]:
    require_known(head)
    require_known(base)
    pairs, new = diff_pairs(head, base)
    out = [f"{r['address']}.{r['attribute']}: new {r['kind']} policy with nothing on merged main to compare; "
           f"review it and pass --accept-new {r['address']}" for r in new if r["address"] not in accept_new]
    for rec, old in pairs:
        out += diff_failures(rec, aws(profile, region, "accessanalyzer", "check-no-new-access",
                                      "--policy-type", "IDENTITY_POLICY",
                                      "--new-policy-document", _compact(rec["document"]),
                                      "--existing-policy-document", _compact(old["document"])))
    return out


# --- check 4: effect tests ---------------------------------------------------------------------------------

def account_id(show: dict) -> str:
    for section in ("prior_state", "values"):
        src = show.get(section) or {}
        if section == "prior_state":
            src = src.get("values") or {}
        for r in (r for m in _modules(src.get("root_module") or {}) for r in m.get("resources", []) or []):
            if r.get("type") == "aws_caller_identity" and (r.get("values") or {}).get("account_id"):
                return r["values"]["account_id"]
    raise PipelineError("no data.aws_caller_identity in the plan, so the effect tests cannot name the account")


def render_boundary(acct: str, partition: str = "aws") -> dict:
    text = BOUNDARY_TEMPLATE.read_text(encoding="utf-8")
    for k, v in (("account_id", acct), ("partition", partition), ("boundary_name", BOUNDARY_NAME)):
        text = text.replace("${" + k + "}", v)
    if "${" in text:
        raise PipelineError(f"{BOUNDARY_TEMPLATE.name} has a placeholder the pipeline does not fill")
    return json.loads(text)


ALLOW_ALL = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}


def _subst(s: str, env: dict) -> str:
    for k, v in env.items():
        s = s.replace("${" + k + "}", v)
    return s


def simulate_request(case: dict, ext: dict, env: dict) -> dict:
    """The simulate-custom-policy input for one case. Identity documents are named by plan address."""
    by_addr = {r["address"]: r["document"] for r in ext["documents"] if r["kind"] == "identity"}
    if case.get("identity") == "allow-all":
        identity = [ALLOW_ALL]
    else:
        missing = [a for a in case["identity"] if a not in by_addr]
        if missing:
            raise PipelineError(f"effect case {case['name']!r}: not an identity policy in this plan: {missing}")
        identity = [by_addr[a] for a in case["identity"]]
    req = {"PolicyInputList": [_compact(d) for d in identity],
           "ActionNames": [case["action"]],
           "ResourceArns": [_subst(case.get("resource", "*"), env)]}
    if case.get("boundary", "canonical") == "canonical":
        req["PermissionsBoundaryPolicyInputList"] = [_compact(render_boundary(env["account_id"]))]
    ctx = case.get("context") or {}
    if ctx:
        req["ContextEntries"] = [{"ContextKeyName": k, "ContextKeyValues": [_subst(str(v), env)],
                                  "ContextKeyType": "string"} for k, v in ctx.items()]
    return req


def effect_failure(case: dict, response: dict) -> str | None:
    got = [r.get("EvalDecision") for r in response.get("EvaluationResults", [])]
    want = case["expect"]
    ok = bool(got) and all(g == want or (want == "denied" and g in ("explicitDeny", "implicitDeny")) for g in got)
    return None if ok else f"effect {case['name']!r}: {case['action']} expected {want}, simulator said {got or 'nothing'}"


def load_cases(suite: str) -> list[dict]:
    spec = yaml.safe_load(EFFECT_TESTS.read_text(encoding="utf-8"))
    if suite not in spec:
        raise PipelineError(f"{EFFECT_TESTS.name} has no suite {suite!r}")
    return spec[suite]


def effect_env(show: dict, suite: str) -> dict:
    env = {"account_id": account_id(show)}
    if suite == "cluster":
        env.update(cluster_name=cluster_name(show), region=plan_region(show))
    return env


def effect(ext: dict, show: dict, suite: str, profile: str, region: str) -> list[str]:
    require_known(ext)
    env = effect_env(show, suite)
    out = []
    for case in load_cases(suite):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(simulate_request(case, ext, env), f)
        try:
            resp = aws(profile, region, "iam", "simulate-custom-policy", "--cli-input-json", f"file://{f.name}")
        finally:
            os.unlink(f.name)
        msg = effect_failure(case, resp)
        if msg:
            out.append(msg)
    return out


# A saved plan carries the root variables; a state file does not, so fall back to the cluster resource.
def _var(show: dict, name: str):
    return ((show.get("variables") or {}).get(name) or {}).get("value")


def _eks_cluster(show: dict) -> dict:
    for r in _managed(show):
        if r["type"] == "aws_eks_cluster" and (r.get("values") or {}).get("arn"):
            return r["values"]
    return {}


def cluster_name(show: dict) -> str:
    name = _var(show, "name") or _eks_cluster(show).get("name")
    if not name:
        raise PipelineError("cannot tell the cluster name: no `name` variable and no aws_eks_cluster")
    return name


def plan_region(show: dict) -> str:
    region = _var(show, "region") or (_eks_cluster(show).get("arn") or "::::").split(":")[3]
    if not region:
        raise PipelineError("cannot tell the region: no `region` variable and no aws_eks_cluster ARN")
    return region


# --- CLI ---------------------------------------------------------------------------------------------------

def _load(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PipelineError(f"cannot read {path}: {e}") from e


def _report(name: str, failures: list[str]) -> bool:
    print(f"== check {name}: {'PASS' if not failures else f'FAIL ({len(failures)})'}")
    for f in failures:
        print(f"  {f}")
    return not failures


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("extract", "structural", "syntax", "diff", "effect", "run"):
        p = sub.add_parser(name)
        p.add_argument("--show", required=True)
        if name in ("syntax", "diff", "effect", "run"):
            p.add_argument("--profile", required=True)
            p.add_argument("--region", required=True)
        if name in ("diff", "run"):
            p.add_argument("--base", required=True)
            p.add_argument("--accept-new", action="append", default=[])
        if name in ("effect", "run"):
            p.add_argument("--suite", required=True, choices=tuple(ROOTS))
    a = ap.parse_args(argv)
    try:
        show = _load(a.show)
        ext = extract(show)
        if a.cmd == "extract":
            print(json.dumps(ext, indent=2))
            return 0
        ok = True
        if a.cmd in ("structural", "run"):
            ok &= _report("3 structural", structural(ext))
        if a.cmd in ("syntax", "run"):
            ok &= _report("1 syntax", syntax(ext, a.profile, a.region))
        if a.cmd in ("diff", "run"):
            ok &= _report("2 semantic diff", diff(ext, extract(_load(a.base)), a.profile, a.region, a.accept_new))
        if a.cmd in ("effect", "run"):
            ok &= _report("4 effect", effect(ext, show, a.suite, a.profile, a.region))
        return 0 if ok else 1
    except PipelineError as e:
        print(f"PIPELINE CANNOT JUDGE THIS PLAN: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
