# ABOUTME: Offline check of verify/policy_spec.py: the restrict-agent-spawned-workloads expressions escalation 755 read
# ABOUTME: off watch-it-burn-private match the repo's once whitespace is collapsed, and a real change still differs.
"""Escalation 755 (#608) stopped verify/test_llm_bypass_live.py at "live restrict-agent-spawned-workloads validation
expressions are the repo's" on a cluster synced to the checkout's own revision. The live expressions 2 and 3, the
#607 secret-volume and secretKeyRef rules, each had one empty line after their first line that PyYAML's reading of
policies/kyverno/restrict-agent-spawned-workloads.yaml does not have. This builds that live form from the repo file
the way the escalation's diff shows it, and holds the comparison to two things: the whitespace-only difference
passes, and a changed operator, name, literal or count does not. No cluster.
"""
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from policy_spec import cel, expressions, first_difference, normalized  # noqa: E402

SPAWN_FILE = REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml"
BYPASS_FILE = REPO / "policies/kyverno/deny-llm-endpoint-bypass.yaml"
LIVE_TEST = REPO / "verify/test_llm_bypass_live.py"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def kustomize_form(expr: str) -> str:
    """What kustomize writes, and so what the cluster held, for a `>-` expression whose second line is more
    indented (escalation 755's diff): one more line break after the first line. Expressions on one line, or
    folded at one indent, are unchanged."""
    first, sep, rest = expr.partition("\n")
    return f"{first}\n\n{rest}" if sep and rest.startswith(" ") else expr


spawn = yaml.safe_load(SPAWN_FILE.read_text())["spec"]
repo_vals = spawn["validations"]
live_vals = [{**v, "expression": kustomize_form(v["expression"])} for v in repo_vals]

print("== the live form escalation 755 read ==")
changed = [i for i, (h, w) in enumerate(zip(live_vals, repo_vals)) if h["expression"] != w["expression"]]
check("the repo's restrict-agent-spawned-workloads has four validations", len(repo_vals) == 4, str(len(repo_vals)))
check("exactly expressions 2 and 3 (the #607 Secret rules) take the extra line break, as in the live diff",
      changed == [2, 3], str(changed))
check("expression 2 on the cluster reads `exists(v,` then an empty line, as escalation 755 printed",
      live_vals[2]["expression"].startswith("!object.spec.?volumes.orValue([]).exists(v,\n\n  (has(v.secret)"),
      repr(live_vals[2]["expression"][:80]))
check("expression 3 on the cluster reads `exists(c,` then an empty line, as escalation 755 printed",
      live_vals[3]["expression"].startswith("!variables.containers.exists(c,\n\n  c.?env.orValue([])"),
      repr(live_vals[3]["expression"][:80]))
check("compared exactly, as the live test did before #608, the two forms differ (the FAIL escalation 755 saw)",
      [v["expression"] for v in live_vals] != [v["expression"] for v in repo_vals])

print("== whitespace alone passes ==")
check("expressions() of the live form equals the repo's", expressions(live_vals) == expressions(repo_vals),
      first_difference(expressions(live_vals), expressions(repo_vals)))
check("first_difference names nothing when they match", first_difference(expressions(live_vals),
                                                                         expressions(repo_vals)) == "")
check("normalized() of the live validations equals the repo's (messages kept as they are)",
      normalized(live_vals) == normalized(repo_vals))
check("tabs, CRLF and trailing spaces collapse too", cel("a &&\r\n\t b  ") == "a && b")
# The same parser difference on any other `>-` expression with a more-indented line, in either policy and in any
# field the live test compares, is whitespace too.
for path in (SPAWN_FILE, BYPASS_FILE):
    spec = yaml.safe_load(path.read_text())["spec"]
    for field in ("matchConditions", "variables", "validations"):
        repo_items = spec.get(field) or []
        live_items = [{**i, "expression": kustomize_form(i["expression"])} for i in repo_items]
        check(f"{path.name} {field}: the kustomize form compares equal to the repo's, normalized",
              normalized(live_items) == normalized(repo_items))

print("== a real change still differs ==")


def edited(index: int, old: str, new: str) -> list:
    out = [dict(v) for v in live_vals]
    assert old in out[index]["expression"], (index, old)
    out[index]["expression"] = out[index]["expression"].replace(old, new, 1)
    return out


for label, vals in (
        ("an operator (&& to ||) in the secret-volume rule", edited(2, "&&", "||")),
        ("a field name (secretName to name) in the secret-volume rule", edited(2, "secretName", "name")),
        ("a negation dropped in the secretKeyRef rule", edited(3, "!variables", "variables")),
        ("a string literal ('' to 'x') in the secretKeyRef rule", edited(3, "orValue('')", "orValue('x')")),
):
    diff = first_difference(expressions(vals), expressions(repo_vals))
    check(f"{label} is a difference", expressions(vals) != expressions(repo_vals))
    check(f"{label}: first_difference names the expression", diff.startswith(("expression 2:", "expression 3:")),
          diff)
check("a validation missing on the cluster is a difference, by count",
      first_difference(expressions(live_vals[:3]), expressions(repo_vals)) == "cluster has 3 expressions, the repo 4")
renamed = [dict(v) for v in spawn["variables"]]
renamed[0]["name"] = renamed[0]["name"] + "X"
check("a renamed variable is a difference (normalized() keeps every key but expression)",
      normalized(renamed) != normalized(spawn["variables"]))
reworded = [dict(v) for v in repo_vals]
reworded[2]["message"] = reworded[2]["message"] + " "
check("a changed message is a difference in normalized()", normalized(reworded) != normalized(repo_vals))

print("== the live test uses it ==")
src = LIVE_TEST.read_text()
check("test_llm_bypass_live.py imports expressions, first_difference and normalized from policy_spec",
      "from policy_spec import expressions, first_difference, normalized" in src)
check("test_llm_bypass_live.py no longer compares raw expression strings",
      re.search(r"v\.get\(\"expression\"\) for v in", src) is None)
check("test_llm_bypass_live.py compares both policies' validations through expressions()",
      src.count('expressions(have.get("validations"))') == 1
      and src.count('expressions(have_spawn.get("validations"))') == 1)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("policy_spec compares live and repo expressions modulo whitespace only.")
