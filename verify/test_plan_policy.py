# ABOUTME: Render gate for the plan-time policy check (#200): policies, exceptions, gates and pins agree.
# ABOUTME: Offline half; verify/test_plan_policy_e2e.py runs the real tools against real plans.
"""Why this exists (#200).

The plan-time check has one promise that is easy to break quietly: nothing gets through without a named
reason in infra/policy/plan/exceptions.md. Kyverno cannot read that file, so its exemptions live in each
policy's `exempt` variable, and the two can drift apart in either direction. Drift one way silently excuses
a finding nobody wrote a reason for. Drift the other way leaves a documented exception that excuses
nothing, so the next reviewer trusts a row that does not work. This holds them equal.

It also keeps the other ways of silencing a scanner out of the repo: inline `#checkov:skip` and
`trivy:ignore` comments, .trivyignore and .checkov.yaml files. check-plan.py already runs the scanners
where those cannot reach, so their presence would only mislead: they would look like they excuse
something when they do not.
"""
from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
PLAN = REPO / "infra" / "policy" / "plan"

spec = importlib.util.spec_from_file_location("check_plan", PLAN / "check-plan.py")
check_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_plan)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def cel_string_list(expr: str) -> list[str] | None:
    """The addresses in a CEL list literal of single-quoted strings, or None if it is anything else."""
    expr = expr.strip()
    if not (expr.startswith("[") and expr.endswith("]")):
        return None
    inner = expr[1:-1].strip()
    if not inner:
        return []
    items = [i.strip() for i in inner.split(",")]
    if not all(re.fullmatch(r"'[^']+'", i) for i in items):
        return None
    return [i[1:-1] for i in items]


policies = {p: yaml.safe_load(p.read_text()) for p in sorted((PLAN / "policies").glob("*.yaml"))}
exceptions = check_plan.load_exceptions()
gates = yaml.safe_load((PLAN / "gates.yaml").read_text())
tools = yaml.safe_load((PLAN / "tools.yaml").read_text())

print("== every policy is a JSON-mode ValidatingPolicy that names itself ==")
check("there are policies to check", len(policies) >= 4)
for path, doc in policies.items():
    name = doc.get("metadata", {}).get("name", "")
    check(f"{path.name}: ValidatingPolicy policies.kyverno.io/v1",
          doc.get("apiVersion") == "policies.kyverno.io/v1" and doc.get("kind") == "ValidatingPolicy")
    check(f"{path.name}: evaluation.mode is JSON", doc.get("spec", {}).get("evaluation", {}).get("mode") == "JSON")
    check(f"{path.name}: metadata.name matches the file name", name == path.stem)
    # A matchCondition that is false makes the CLI report "skip" for the whole plan, which a reader of
    # the output could take for a pass. check-plan.py fails skips too, but none should be possible.
    check(f"{path.name}: no matchConditions that could skip the whole plan", "matchConditions" not in doc["spec"])
    validations = doc["spec"].get("validations", [])
    check(f"{path.name}: exactly one validation", len(validations) == 1)
    check(f"{path.name}: the failure message starts with the policy name",
          all(v.get("messageExpression", "").strip().startswith(f"'{name}:") for v in validations))

print("== every Kyverno exemption has a reason in exceptions.md, and every Kyverno row is an exemption ==")
for path, doc in policies.items():
    name = doc["metadata"]["name"]
    exempt = [v for v in doc["spec"].get("variables", []) if v["name"] == "exempt"]
    check(f"{path.name}: has one `exempt` variable", len(exempt) == 1)
    listed = cel_string_list(exempt[0]["expression"]) if exempt else None
    check(f"{path.name}: `exempt` is a plain list of quoted addresses", listed is not None)
    documented = sorted(e["address"] for e in exceptions if e["tool"] == "kyverno" and e["rule"] == name)
    in_policy_only = sorted(set(listed or []) - set(documented))
    in_doc_only = sorted(set(documented) - set(listed or []))
    for a in in_policy_only:
        print(f"        exempt in {path.name} with no row in exceptions.md: {a}")
    for a in in_doc_only:
        print(f"        row in exceptions.md not in {path.name}'s exempt list: {a}")
    check(f"{name}: exempt list == exceptions.md rows", not in_policy_only and not in_doc_only)

print("== exceptions.md rows are well formed ==")
errors = check_plan.config_errors(exceptions, gates)
for e in errors:
    print(f"        {e}")
check("check-plan.py's own config check passes", not errors)
keys = [(e["tool"], e["rule"], e["address"]) for e in exceptions]
check("no duplicate rows", len(keys) == len(set(keys)))
check("every reason is a real explanation (40+ characters)", all(len(e["reason"]) >= 40 for e in exceptions))
check("every address looks like a plan address",
      all(re.fullmatch(r"(module\.[\w-]+(\[[^\]]+\])?\.)*[a-z0-9_]+\.[\w-]+(\[[^\]]+\])?", e["address"])
          for e in exceptions))

print("== every starter policy has an independent scanner re-check ==")
gated = {p for rules in gates.values() for p in rules.values()}
for doc in policies.values():
    check(f"{doc['metadata']['name']} is gated by at least one scanner rule", doc["metadata"]["name"] in gated)

print("== the toolchain is pinned ==")
for name, b in tools["binaries"].items():
    check(f"{name}: sha256 is 64 hex", re.fullmatch(r"[0-9a-f]{64}", str(b.get("sha256", ""))) is not None)
    check(f"{name}: https url that names version {b.get('version')}",
          str(b.get("url", "")).startswith("https://") and str(b.get("version")) in str(b.get("url")))
for name, p in tools["python"].items():
    check(f"{name}: exact version", re.fullmatch(r"\d+\.\d+\.\d+", str(p.get("version", ""))) is not None)
check("Kyverno CLI is at least 1.18 (#200: the --json nil-pointer fix)",
      tuple(int(x) for x in str(tools["binaries"]["kyverno"]["version"]).split(".")[:2]) >= (1, 18))
check("no standalone kyverno-json, tfsec or terrascan in the toolchain",
      not ({"kyverno-json", "tfsec", "terrascan"} & (set(tools["binaries"]) | set(tools["python"]))))

print("== Trivy findings map back to plan addresses ==")
# Measured on Trivy 0.76.1's own output: it renamed module.eks.aws_eks_cluster.this[0] to this.
probe_doc = {"resource_changes": [
    {"mode": "managed", "type": "aws_eks_cluster", "name": "this", "module_address": "module.eks",
     "address": "module.eks.aws_eks_cluster.this[0]"},
    {"mode": "managed", "type": "aws_s3_bucket", "name": "b", "address": "aws_s3_bucket.b"},
]}
index = check_plan.trivy_addresses(probe_doc)
check("module resource: <name>_<md5 of module address>",
      index.get("aws_eks_cluster.this_6f5dc2b565d5e07d187c87c2c6fab935") == ["module.eks.aws_eks_cluster.this[0]"])
check("the md5 is of the module address", hashlib.md5(b"module.eks").hexdigest() == "6f5dc2b565d5e07d187c87c2c6fab935")
check("root resource keeps its name", index.get("aws_s3_bucket.b") == ["aws_s3_bucket.b"])

print("== nothing in the repo tries to silence a scanner outside exceptions.md ==")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".terraform"}
inline = re.compile(r"(checkov:skip|trivy:ignore|tfsec:ignore)")
silencers = []
for path in REPO.rglob("*"):
    rel = path.relative_to(REPO)
    if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
        continue
    if path.name in {".trivyignore", ".trivyignore.yaml", ".checkov.yaml", ".checkov.yml", "trivy.yaml"}:
        silencers.append(str(rel))
    elif path.suffix in {".tf", ".hcl"} and inline.search(path.read_text(errors="replace")):
        silencers.append(str(rel))
for s in silencers:
    print(f"        {s}")
check(f"no scanner suppression files or inline skips ({len(silencers)} found)", not silencers)

# aws/network keeps its real state as terraform.tfstate in the root. A copy that carries it makes the mock
# plan refresh live resource ids against moto and fail, which it did on 2026-10-27 once the lab VPC was up.
_plan_fleet = (PLAN / "plan-fleet.py").read_text(encoding="utf-8")
check("plan-fleet.py copies each root without its local state",
      re.search(r'ignore_patterns\([^)]*"\*\.tfstate\*"', _plan_fleet) is not None)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll plan-policy checks passed.")
