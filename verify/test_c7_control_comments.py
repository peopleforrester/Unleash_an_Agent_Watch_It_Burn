# ABOUTME: Render gate for #516's last criterion: no comment in #516's files, in resources.yaml's Agent tools comment
# ABOUTME: or in toggle-mcp-authz-on.sh, nor C7's FACILITATOR.md control section, names toolNames as C7's only control (#569, #575).
"""Why this exists (#569).

#516 gave C7 one control per cluster (#496): on a workshop cluster the kagent toolNames allow-list on
workshop-agent, on an admin cluster (the KubeCon breakout) agentgateway's mcpAuthorization rule for evil-mcp,
the line of agentgateway-c7-config marked `# c7-rule`. It rewrote every comment in its files that said
toolNames was C7's control and nothing else, and no check held them: verify/test_agent_tools_exist.py only
looks for the word toolNames in the toggle's code.

A comment block that calls toolNames, or the agent's tool allow-list, a control is held to name the admin
cluster's gateway rule too, so a sentence like "the control is its toolNames allowlist" cannot stand alone.
The phrasings #516 removed are refused outright. Comments and docstrings are read in code files, and in
decisions.md only #516's own entry, since the entries before it are records of what was true then. The
pre-#516 comments are kept below as fixtures, and the check must refuse each of them, so it cannot pass by
reading nothing.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

REPO = pathlib.Path(__file__).resolve().parents[1]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


# #516's files, its Agent tools comment and the beat-3 toggle. resources.yaml is read for its Agent tools
# comment only; its other comments are about other things.
CODE_FILES = (
    "gitops/ai-layer/web-terminal/entrypoint.sh",
    "images/web-terminal/entrypoint.sh",
    "verify/kubecon_probe.py",
    "verify/test_kubecon_probe.py",
    "verify/test_c7_gateway_toggle.py",
    "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh",
)
RESOURCES = "gitops/workshop-agent/agent.yaml"  # the Agent, in its own Application since #707
DECISION_516 = "## 2026-10-25 · #516 ·"

TOOLNAMES = re.compile(r"\btoolnames\b|\btool allow-?list\b|\bagent'?s (?:\w+ )?allow-?list\b|\bkagent'?s? (?:\w+ )?allow-?list\b",
                       re.I)
CONTROL = re.compile(r"\bcontrols?\b", re.I)
# A sentence that names one thing as C7's control: "the C7 control is ...", "C7's control", or "the control is"
# in a sentence about C7's tools (Challenge 4's "the control is a per-agent budget" is not one).
ONE_CONTROL = re.compile(r"\bC7(?:'s)? (?:\(beat-3\) )?control\b|\bthe control is\b", re.I)
C7_TOPIC = re.compile(r"\bC7\b|\bevil-mcp\b|\brogue\b|\bmcp\b", re.I)
ADMIN = re.compile(r"\badmin cluster\b", re.I)
GATEWAY = re.compile(r"\bgateway\b|\bagentgateway\b|# c7-rule|\bmcpAuthorization\b", re.I)
# What the corrected comments said: "The C7 (beat-3) control that is actually IN PATH is kagent's toolNames
# allowlist", "that bind's mcpAuthorization rule is committed 'true' and nothing flips it, so it does not gate
# the rogue tools", "The in-path, deployed, deterministic control is the kagent toolNames allowlist", "so
# toolNames stays the control", "The MCP guard patches the kagent Agent's toolNames allow-list".
STALE = re.compile(r"\bactually in path\b|\bnothing flips it\b|\bdoes not gate the rogue tools\b"
                   r"|\bin-path, deployed, deterministic control\b|\btoolnames stays the control\b"
                   r"|\bthe mcp guard patches\b|\bonly (?:\w+ ){0,2}control\b|\bcontrol\b[^.;]*\bonly\b", re.I)


def python_blocks(src: str) -> list[tuple[int, str]]:
    """Each run of comment lines, and each docstring, as one (first line, text) block."""
    blocks: list[tuple[int, str]] = []
    last = -2
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        line, text = tok.start[0], tok.string.lstrip("#").strip()
        if line == last + 1 and blocks:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + " " + text)
        else:
            blocks.append((line, text))
        last = line
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                blocks.append((body[0].lineno, " ".join(body[0].value.value.split())))
    return sorted(blocks)


def hash_blocks(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Each run of whole-line `#` comments (a bare `#` included, it only breaks a paragraph) as one block."""
    blocks: list[tuple[int, str]] = []
    last = -2
    for line, raw in lines:
        s = raw.strip()
        if not s.startswith("#") or s.startswith("#!"):
            continue
        text = s.lstrip("#").strip()
        if line == last + 1 and blocks:
            blocks[-1] = (blocks[-1][0], (blocks[-1][1] + " " + text).strip())
        else:
            blocks.append((line, text))
        last = line
    return blocks


def agent_tools_comment(src: str) -> list[tuple[int, str]]:
    """The Agent's tools comment: the comment block right above workshop-agent's `tools:`, and the
    comments inside that list."""
    lines = src.splitlines()
    agent = next((n for n, l in enumerate(lines) if l == "kind: Agent"
                  and any(m == "  name: workshop-agent" for m in lines[n + 1:n + 4])), None)
    check(f"{RESOURCES} declares the workshop-agent Agent", agent is not None)
    if agent is None:
        return []
    end = next((n for n in range(agent + 1, len(lines)) if lines[n] == "---"), len(lines))
    tools = next((n for n in range(agent, end) if lines[n] == "    tools:"), None)
    check("and its tools list", tools is not None)
    if tools is None:
        return []
    top = tools
    while top > agent and lines[top - 1].lstrip().startswith("#"):
        top -= 1
    above = hash_blocks([(n + 1, lines[n]) for n in range(top, tools)])
    inside = [(n + 1, lines[n].split(" # ", 1)[1].strip() if " # " in lines[n] and not lines[n].lstrip().startswith("#")
               else lines[n].strip().lstrip("#").strip())
              for n in range(tools + 1, end) if "#" in lines[n]]
    check("the Agent tools comment is there and names toolNames", len(above) == 1 and bool(TOOLNAMES.search(above[0][1])),
          f"{above}")
    return above + inside


def decision_516(src: str) -> list[tuple[int, str]]:
    """#516's decisions entry as one block: its opening paragraph names both controls for the bullets below it."""
    lines = src.splitlines()
    start = next((n for n, l in enumerate(lines) if l.startswith(DECISION_516)), None)
    check(f"decisions.md has #516's entry ({DECISION_516!r})", start is not None)
    if start is None:
        return []
    end = next((n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")), len(lines))
    return [(start + 1, " ".join(" ".join(lines[start + 1:end]).split()))]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;!?])\s+", text) if s]


def wrong(block: str) -> str:
    """Why this block names toolNames as C7's only control, or '' when it does not."""
    stale = [s for s in sentences(block) if STALE.search(s) and (TOOLNAMES.search(s) or "c7" in s.lower()
                                                                  or "rogue" in s.lower())]
    if stale:
        return f"says {stale[0][:140]!r}"
    if any((TOOLNAMES.search(s) and CONTROL.search(s)) or (ONE_CONTROL.search(s) and C7_TOPIC.search(s)) for s in sentences(block)) \
            and not (ADMIN.search(block) and GATEWAY.search(block)):
        return "names C7's control, or calls toolNames a control, and never names the admin cluster's gateway rule"
    return ""


# --- the check refuses what #516 corrected ----------------------------------------------------------------
print("the pre-#516 comments are refused")
PRE_516 = {
    "resources.yaml's Agent tools comment":
        "Committed tool config = the VULNERABLE default (challenge 7 \"7a: see the weakness\"), consistent with the "
        "input/output guards which also boot OFF. The C7 (beat-3) control that is actually IN PATH is kagent's "
        "toolNames allowlist: the agent dials evil-mcp through agentgateway :3003 (#514), but that bind's "
        "mcpAuthorization rule is committed 'true', so it does not gate the rogue tools (workshop-mcp's :3001 rule "
        "is allow-all too; #239).",
    "toggle-mcp-authz-on.sh's WHY":
        "WHY this toggles toolNames and not the agentgateway config: The rogue tools are served by evil-mcp, and "
        "the `evil-mcp` RemoteMCPServer goes through agentgateway on its own bind, :3003 (#514). That bind's "
        "mcpAuthorization rule is committed 'true' and nothing flips it, so it does not gate the rogue tools. The "
        "in-path, deployed, deterministic control is the kagent toolNames allowlist on the Agent CRD, which kagent "
        "enforces when it renders the agent's tool set. This toggle patches that.",
    "toggle-mcp-authz-on.sh's alternative":
        "The gateway-enforced alternative (flip that bind's CEL rule, the line marked `# c7-rule`) is weighed in "
        "docs/research/2026-10-24-agentgateway-evaluation.md (#239). It blocks the same tool names toolNames does "
        "and no more, so toolNames stays the control.",
    "the entrypoint's toggle comment":
        "Output/input guards flip via the guard-proxy /toggle (no new pod, ArgoCD-safe, the cost counter "
        "survives). The MCP guard patches the kagent Agent's toolNames allow-list; the ai-layer app ignores drift "
        "on .spec.declarative.tools so the toggle persists.",
    "a sentence with no admin cluster in its block":
        "evil-mcp stays WIRED in both states; the control is its toolNames allowlist.",
    "toggle-mcp-authz-on.sh's wiring claim":
        "The rogue tools are served by evil-mcp-shim, reachable via the `evil-mcp` RemoteMCPServer, NOT by "
        "workshop-mcp. So the C7 control is whether `evil-mcp` is wired into the agent's toolset at all; adding the "
        "rogue tool NAMES to workshop-mcp's allowlist does nothing.",
    "toolNames called the only control":
        "On a workshop cluster and an admin cluster alike, toolNames is C7's only control; the gateway rule stays "
        "'true'.",
}
for label, text in PRE_516.items():
    check(f"refused: {label}", bool(wrong(text)))

# --- and finds it nowhere now -------------------------------------------------------------------------------
print("\n#516's comments on C7's control")
for rel in CODE_FILES:
    src = (REPO / rel).read_text(encoding="utf-8")
    blocks = python_blocks(src) if rel.endswith(".py") else hash_blocks(list(enumerate(src.splitlines(), 1)))
    named = [b for b in blocks if TOOLNAMES.search(b[1])]
    bad = [f"{line}: {why}" for line, text in blocks if (why := wrong(text))]
    check(f"{rel} has comments that name toolNames, and none names it as C7's only control",
          bool(named) and not bad, "; ".join(bad) or "no comment names toolNames, so nothing was read")

agent_tools = agent_tools_comment((REPO / RESOURCES).read_text(encoding="utf-8"))
bad = [f"{line}: {why}" for line, text in agent_tools if (why := wrong(text))]
check(f"{RESOURCES}'s Agent tools comment does not name toolNames as C7's only control", bool(agent_tools) and not bad,
      "; ".join(bad))
check("it names the admin cluster's gateway rule beside toolNames",
      bool(agent_tools) and bool(ADMIN.search(agent_tools[0][1]) and GATEWAY.search(agent_tools[0][1])),
      agent_tools[0][1][:200] if agent_tools else "")

entry = decision_516((REPO / "decisions.md").read_text(encoding="utf-8"))
bad = [f"{line}: {why}" for line, text in entry if (why := wrong(text))]
check("decisions.md's #516 entry does not name toolNames as C7's only control", bool(entry) and not bad, "; ".join(bad))


# --- FACILITATOR.md's control section (#575) ------------------------------------------------------------------
# The runbook said the agent dials its MCP servers directly, so agentgateway was not in the path. Since #514 the
# evil-mcp RemoteMCPServer's url is agentgateway's :3003 bind, so the section is held to the same per-cluster
# reading as the comments, and to naming that bind.
print("\nFACILITATOR.md's control section")
FACILITATOR = "challenges/03-bad-mcp-excessive-agency/FACILITATOR.md"
DIRECT = re.compile(r"\bdials (?:\w+ ){0,3}\**directly\b|\bnot agentgateway\b", re.I)
PRE_575 = ("The agent (kagent `Agent` CRD, `workshop-agent`) dials its MCP servers **directly**, so the in-path "
           "control is the **kagent `toolNames` allow-list on the Agent**, not agentgateway.")
check("refused: the pre-#575 control section", bool(DIRECT.search(PRE_575)) and bool(wrong(PRE_575)))
m = re.search(r"^## The control\b.*?(?=^## )", (REPO / FACILITATOR).read_text(encoding="utf-8"), re.S | re.M)
section = " ".join(m.group(0).split()) if m else ""
check(f"{FACILITATOR} has a control section that names toolNames", bool(TOOLNAMES.search(section)))
check("it does not say the agent dials its MCP servers directly", not DIRECT.search(section),
      (DIRECT.search(section) or [""])[0])
check("it does not name toolNames as C7's only control", not wrong(section), wrong(section))
check("it names evil-mcp's :3003 bind and its `# c7-rule` line",
      "agentgateway.agent:3003/mcp" in section and "# c7-rule" in section)
check("it says the :3003 rule stays 'true' on a workshop cluster",
      bool(re.search(r"workshop cluster\*{0,2}[^.]*\brule stays `'true'`", section)))

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: #516's comments give C7 a control per cluster, toolNames on a workshop cluster and the gateway rule on "
      "an admin cluster")
