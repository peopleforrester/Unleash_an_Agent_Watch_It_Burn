# ABOUTME: Render gate for #514's last criterion: guard-proxy-reader may get configmaps/agentgateway-c7-config by
# ABOUTME: name, get only, and no comment or doc in #514's files still says the agent dials evil-mcp directly (#564).
"""Why this exists (#564).

#514 put evil-mcp behind agentgateway's own :3003 bind, served by the agentgateway-c7 container from the
ConfigMap agentgateway-c7-config. The C7 badge (guard-proxy-agenticburn#5) reads that ConfigMap's
`# c7-rule` line, so guard-proxy-reader was given `get` on it by name. Nothing held that grant: a wider one
(list, watch, every ConfigMap in `agent`, which holds the guard settings and the LLM Guard wiring) or a renamed
one would have passed, and so would a badge that could not read its rule at all.

#514 also corrected every comment and doc in its own files that said the agent dials evil-mcp directly, and
no check held those either. verify/test_agentgateway_path.py holds six other working docs to it (#563); this
holds #514's eight. Comments and docstrings are read in code files, all prose in docs, and in decisions.md
only #514's own entry, since the entries before it are records of what was true then.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()))
GATEWAY = list(yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()))
C7_CONFIGMAP = "agentgateway-c7-config"
READER = "guard-proxy-reader"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def one(docs: list, kind: str, name: str) -> dict:
    found = [d for d in docs if d and d.get("kind") == kind and d.get("metadata", {}).get("name") == name]
    check(f"{kind}/{name} is declared exactly once", len(found) == 1)
    return found[0] if found else {}


def touches_configmaps(rule: dict) -> bool:
    return (any(g in ("", "*") for g in rule.get("apiGroups", []))
            and any(r in ("configmaps", "*") for r in rule.get("resources", [])))


# --- guard-proxy-reader: get on configmaps/agentgateway-c7-config, by name, and nothing more -------------
print("guard-proxy-reader's ConfigMap grant (#514)")
role = one(RESOURCES, "Role", READER)
check(f"Role {READER} is in namespace agent", role.get("metadata", {}).get("namespace") == "agent",
      f"{role.get('metadata', {}).get('namespace')!r}")
cm_rules = [r for r in role.get("rules", []) if touches_configmaps(r)]
check(f"exactly one {READER} rule reaches ConfigMaps", len(cm_rules) == 1, f"{cm_rules}")
rule = cm_rules[0] if cm_rules else {}
check("that rule is the core API group's configmaps only",
      rule.get("apiGroups") == [""] and rule.get("resources") == ["configmaps"], f"{rule}")
check(f"by name: resourceNames is exactly [{C7_CONFIGMAP!r}]", rule.get("resourceNames") == [C7_CONFIGMAP],
      f"{rule.get('resourceNames')}")
check("get only: verbs is exactly ['get'] (no list or watch, which ignore resourceNames)",
      rule.get("verbs") == ["get"], f"{rule.get('verbs')}")
cluster_role = one(RESOURCES, "ClusterRole", READER)
check(f"ClusterRole {READER} grants nothing on ConfigMaps",
      not any(touches_configmaps(r) for r in cluster_role.get("rules", [])), f"{cluster_role.get('rules')}")

binding = one(RESOURCES, "RoleBinding", READER)
check(f"RoleBinding {READER} binds Role {READER}",
      binding.get("roleRef", {}).get("kind") == "Role" and binding.get("roleRef", {}).get("name") == READER,
      f"{binding.get('roleRef')}")
check(f"to ServiceAccount agent/{READER}, and only it",
      binding.get("subjects") == [{"kind": "ServiceAccount", "name": READER, "namespace": "agent"}],
      f"{binding.get('subjects')}")
proxy = one(RESOURCES, "Deployment", "guard-proxy").get("spec", {}).get("template", {}).get("spec", {})
check(f"guard-proxy runs as {READER}", proxy.get("serviceAccountName") == READER,
      f"{proxy.get('serviceAccountName')!r}")

# The name the grant carries has to be the ConfigMap the badge reads: key config.yaml, one `# c7-rule` line.
c7 = one(GATEWAY, "ConfigMap", C7_CONFIGMAP)
rule_lines = [l for l in c7.get("data", {}).get("config.yaml", "").splitlines() if l.rstrip().endswith("# c7-rule")]
check(f"the granted name is the {C7_CONFIGMAP} that has config.yaml with one line ending `# c7-rule`",
      len(rule_lines) == 1, f"{rule_lines}")

# --- no comment or doc in #514's files says the agent dials evil-mcp directly -------------------------------
print("\n#514's files on the evil-mcp hop")
CHILD_FILES = (
    "gitops/ai-layer/agentgateway.yaml",
    "gitops/ai-layer/resources.yaml",
    "verify/test_agentgateway_path.py",
    "verify/test_agentgateway_config.py",
    "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh",
    "docs/research/2026-10-24-agentgateway-evaluation.md",
    "docs/MASTER-RECREATION-SPEC.md",
    "decisions.md",
)
DECISION_514 = "## 2026-10-25 · #514 ·"
# What the corrected lines said: "dials evil-mcp directly", "points DIRECT at", "(rogue tools, direct)",
# "evil-mcp and default inference bypass it", "direct, not through agentgateway".
STALE = re.compile(r"\bdirect(?:ly)?\b|\bbypass|\bnot (?:\w+ ){0,2}through (?:the )?(?:agent)?gateway"
                   r"|\b(?:skips?|skipped|around) (?:the )?(?:agent)?gateway", re.I)
BLOCK_START = re.compile(r"^(?:[-*|>]|#{1,6} |\d+\. |```)")


def python_text(src: str) -> list[tuple[int, str]]:
    """Comments and docstrings, each a (line, text) pair; the code itself is not prose."""
    out = [(tok.start[0], tok.string.lstrip("#").strip())
           for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT]
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out += [(body[0].lineno + i, l.strip()) for i, l in enumerate(body[0].value.value.splitlines())]
    return sorted(out)


def shell_or_yaml_text(src: str) -> list[tuple[int, str]]:
    """Every line; a comment line loses its `#` so that a comment block reads as prose."""
    return [(i, l.strip().lstrip("#").strip() if l.strip().startswith("#") else "\0" + l.strip())
            for i, l in enumerate(src.splitlines(), 1)]


def markdown_text(rel: str, src: str) -> list[tuple[int, str]]:
    lines = list(enumerate(src.splitlines(), 1))
    if rel == "decisions.md":
        start = next((n for n, (_, l) in enumerate(lines) if l.startswith(DECISION_514)), None)
        check(f"decisions.md has #514's entry ({DECISION_514!r})", start is not None)
        if start is None:
            return []
        end = next((n for n in range(start + 1, len(lines)) if lines[n][1].startswith("## ")), len(lines))
        lines = lines[start:end]
    out, fenced = [], False
    for i, l in lines:
        if l.strip().startswith("```"):
            fenced = not fenced
        # A line of a fenced block (the spec's path diagram) stands alone, like a line of code.
        out.append((i, ("\0" if fenced else "") + l.strip()))
    return out


def sentences(text: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join wrapped lines into paragraphs, then cut at sentence ends and table cells. A code line ("\\0"),
    a blank, a list item, a table row or a heading starts a new paragraph, so neighbouring lines that are
    not one sentence are never read as one."""
    paragraphs: list[tuple[int, str]] = []
    joinable = False
    for line, t in text:
        code = t.startswith("\0")
        t = t.lstrip("\0")
        if not t:
            joinable = False
            continue
        if joinable and not code and not BLOCK_START.match(t):
            paragraphs[-1] = (paragraphs[-1][0], paragraphs[-1][1] + " " + t)
        else:
            paragraphs.append((line, t))
        joinable = not code and not t.startswith("|") and not re.match(r"#{1,6} ", t)
    return [(line, s) for line, p in paragraphs for s in re.split(r"(?<=[.;!?])\s+|\s\|\s", p) if s]


for rel in CHILD_FILES:
    src = (REPO / rel).read_text(encoding="utf-8")
    if rel.endswith(".py"):
        text = python_text(src)
    elif rel.endswith(".md"):
        text = markdown_text(rel, src)
    else:
        text = shell_or_yaml_text(src)
    stale = [f"{line}: {s[:160]}" for line, s in sentences(text) if "evil-mcp" in s.lower() and STALE.search(s)]
    check(f"{rel} has no comment or doc saying evil-mcp is dialled directly", not stale, "; ".join(stale))

# The two places that said it without the word "direct": the evaluation's routing table and the spec's diagram.
evaluation = (REPO / "docs/research/2026-10-24-agentgateway-evaluation.md").read_text(encoding="utf-8")
rows = [l for l in evaluation.splitlines() if l.startswith("|") and "evil-mcp" in l.split("|")[2]]
check("the evaluation's routing table has one evil-mcp row, port 3003, through the gateway",
      len(rows) == 1 and rows[0].split("|")[1].strip() == "3003" and "**yes" in rows[0].split("|")[3], f"{rows}")
spec = (REPO / "docs/MASTER-RECREATION-SPEC.md").read_text(encoding="utf-8")
diagram = [l for l in spec.splitlines() if 'RemoteMCPServer "evil-mcp"' in l]
check("the spec's MCP path diagram routes evil-mcp through agentgateway:3003",
      len(diagram) == 1 and "-> agentgateway:3003/mcp ->" in diagram[0], f"{diagram}")

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print(f"\nPASS: {READER} may only get configmaps/{C7_CONFIGMAP}, and #514's files say evil-mcp goes through :3003")
