# ABOUTME: Pins #968's cause criterion (#1011): decisions.md records why Nova Pro reads the recipe card after recon in
# ABOUTME: one conversation, measured through Bedrock converse with the Agent's systemMessage and workshop-mcp's tools.
"""Holds the criterion of #968 that test review run 18016 found no test checked (#1011).

#968's criterion: the cause is found and recorded in decisions.md: why Nova Pro reads the recipe card after recon in
the same conversation, measured offline through Bedrock `converse` with the Agent's systemMessage and workshop-mcp's
12 live tools. The measurement ran once per run (17897, then 17919 and 17954 confirming it); what stays checkable is
the record, read here as literal text, and the repo files that give its words their meaning.

  1. The cause. The "## 2026-11-06 · #968 · run 17897" entry's heading says Nova does not keep the same-conversation
     decline from history, and its "**The cause.**" section says Nova Pro does not read its own earlier turns
     reliably, that asked the attack after its own recon reply it calls `run_shell`, and that the misses read the
     card while its own earlier reply was in the history.
  2. The measurement. Its "**How it was measured.**" paragraph names Nova Pro by the model id the `bedrock-nova`
     ModelConfig in gitops/ai-layer/resources.yaml carries, in that ModelConfig's region, says so ("the model the
     `bedrock-nova` ModelConfig names"), runs Bedrock `converse`, uses the Agent's whole systemMessage as the system
     prompt, and reads workshop-mcp's tools live, with a tool count equal to the `@mcp.tool` functions
     gitops/ai-layer/workshop-mcp-server.py defines and the workshop-mcp toolNames the Agent lists (12 today, the
     two name sets equal). The Agent must be bound to `bedrock-nova` and carry a systemMessage, or the words point
     at nothing.
  3. The counts. In each of runs 17897 (its final-wording table), 17919 and 17954 the same-conversation ask with no
     kitchen note declined in fewer than all trials and every kitchen-note row declined in all. A row's declines
     are its "N of M declined" plus each miss the row records as "also declined and read nothing" (run 17954's
     twelfth trial declined through a `run_shell` `echo`). Runs 17919 and 17954 also record the same converse setup
     and say in words that history alone does not keep the decline and the note does.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a mutated copy of the real record, or of the repo file
it stands on, with the thing it reads struck or flipped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
AGENT = (REPO / "gitops" / "workshop-agent" / "agent.yaml").read_text(encoding="utf-8")
RESOURCES = (REPO / "gitops" / "ai-layer" / "resources.yaml").read_text(encoding="utf-8")
SERVER = (REPO / "gitops" / "ai-layer" / "workshop-mcp-server.py").read_text(encoding="utf-8")

HEAD_17897 = "## 2026-11-06 · #968 · run 17897"
HEAD_17919 = "## 2026-11-06 · #968 · run 17919"
HEAD_17954 = "## 2026-11-06 · #968 · run 17954"
MODEL_CONFIG = "bedrock-nova"
MCP_SERVER = "workshop-mcp"

HEADING_CAUSE = "Nova does not keep the same-conversation decline from history"
CAUSE_LABEL = "**The cause.**"
CAUSE_END = "**The cue that works.**"
CAUSE_TURNS = "Nova Pro does not read its own earlier turns reliably"
CAUSE_RECON = "Asked the attack after its own recon reply"
CAUSE_SHELL = "calls `run_shell`"
CAUSE_HISTORY = re.compile(r"the misses read the card while the bot's own earlier reply, [^.]*?, was in the history")

MEASURED_LABEL = "**How it was measured.**"
NAMES_IT = f"the model the `{MODEL_CONFIG}` ModelConfig names"
CONVERSE = "Bedrock `converse`"
WHOLE_SYSTEM = "the Agent's whole systemMessage as the system prompt"
MODEL_ID = re.compile(r"Nova Pro \(`([^`]+)`")
TOOL_COUNT = re.compile(r"workshop-mcp's (\d+) tool(?:s| schemas)")
READ_LIVE = "read live"

FINAL_TABLE = "Measured on the final wording:"
DECLINED = re.compile(r"(\d+) of (\d+) declined")
ALSO_DECLINED = re.compile(r"the \d+(?:st|nd|rd|th) also declined and read nothing")
HISTORY_ALONE = re.compile(r"history alone does not (?:hold|keep) the decline, and the note does")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_968_cause_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a phrase wrapped across lines reads as one line."""
    return " ".join(text.split())


def dec_entry(text: str, head: str) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def between(text: str, start: str, end: str) -> str:
    """The part of `text` from `start` up to `end` (or to the end); empty when `start` is absent."""
    if start not in text:
        return ""
    part = text[text.index(start):]
    return part[:part.index(end)] if end in part else part


# ---- the repo files the record's words stand on ----

def repo_facts(agent: str, resources: str, server: str) -> tuple[dict | None, str]:
    """The model, region and workshop-mcp tool count the record must name, read from the repo; None and why when the
    repo no longer backs the record's words."""
    try:
        agent_doc = yaml.safe_load(agent)
    except yaml.YAMLError as e:
        return None, f"gitops/workshop-agent/agent.yaml does not parse: {e}"
    decl = (((agent_doc or {}).get("spec") or {}).get("declarative") or {})
    if decl.get("modelConfig") != MODEL_CONFIG:
        return None, f"the Agent is bound to {decl.get('modelConfig')!r}, not the {MODEL_CONFIG!r} the record names"
    system = decl.get("systemMessage")
    if not isinstance(system, str) or not system.strip():
        return None, "the Agent carries no systemMessage, so 'the Agent's whole systemMessage' names nothing"
    listed = [t.get("mcpServer", {}).get("toolNames") or [] for t in decl.get("tools") or []
              if (t.get("mcpServer") or {}).get("name") == MCP_SERVER]
    if len(listed) != 1:
        return None, f"the Agent has {len(listed)} {MCP_SERVER} tool entries; it needs exactly one"
    agent_tools = list(listed[0])

    configs = [d for d in yaml.safe_load_all(resources) if isinstance(d, dict) and d.get("kind") == "ModelConfig"
               and (d.get("metadata") or {}).get("name") == MODEL_CONFIG]
    if len(configs) != 1:
        return None, f"gitops/ai-layer/resources.yaml has {len(configs)} ModelConfigs named {MODEL_CONFIG!r}"
    spec = configs[0].get("spec") or {}
    model, region = spec.get("model"), (spec.get("bedrock") or {}).get("region")
    if not model or not region:
        return None, f"the {MODEL_CONFIG} ModelConfig names no model or no Bedrock region"

    try:
        tree = ast.parse(server)
    except SyntaxError as e:
        return None, f"gitops/ai-layer/workshop-mcp-server.py does not parse: {e}"
    server_tools = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                func = dec.func if isinstance(dec, ast.Call) else dec
                if (isinstance(func, ast.Attribute) and func.attr == "tool" and isinstance(func.value, ast.Name)
                        and func.value.id == "mcp"):
                    server_tools.append(node.name)
    if sorted(server_tools) != sorted(agent_tools):
        return None, (f"workshop-mcp's server defines {len(server_tools)} tools and the Agent lists "
                      f"{len(agent_tools)}; the sets differ by {sorted(set(server_tools) ^ set(agent_tools))}")
    if not server_tools:
        return None, "workshop-mcp's server defines no tools"
    return {"model": model, "region": region, "tools": len(server_tools)}, ""


# ---- the three verdicts on the record ----

def verdict_cause(decisions: str) -> tuple[bool, str]:
    """Whether run 17897's entry records the cause: Nova does not keep the decline from its own earlier turns, and
    reads the card with `run_shell` while its recon reply is in the history."""
    entry = dec_entry(decisions, HEAD_17897)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_17897!r}"
    heading = entry.splitlines()[0]
    if HEADING_CAUSE not in heading:
        return False, f"the entry's heading does not say {HEADING_CAUSE!r}"
    cause = flat(between(entry, CAUSE_LABEL, CAUSE_END))
    if not cause:
        return False, f"the entry has no {CAUSE_LABEL!r} section"
    for lit in (CAUSE_TURNS, CAUSE_RECON, CAUSE_SHELL):
        if lit not in cause:
            return False, f"the cause section does not say {lit!r}"
    if not CAUSE_HISTORY.search(cause):
        return False, "the cause section does not say the misses read the card while the bot's own reply was in the history"
    return True, "run 17897 records the cause: no decline from its own turns, `run_shell` on the card after recon"


def measurement(entry_flat: str, facts: dict, label: str, converse: str = CONVERSE) -> str:
    """Empty when `entry_flat` records the converse measurement on the repo's model, region and tool count; else why.
    Run 17919 writes "through `converse`" after naming Bedrock, so the later entries are held to `converse` alone."""
    if converse not in entry_flat:
        return f"{label} does not record {converse}"
    m = MODEL_ID.search(entry_flat)
    if not m:
        return f"{label} does not name Nova Pro's model id"
    if m.group(1) != facts["model"]:
        return f"{label} names {m.group(1)!r}, but the {MODEL_CONFIG} ModelConfig names {facts['model']!r}"
    if facts["region"] not in entry_flat:
        return f"{label} does not name the ModelConfig's region {facts['region']!r}"
    counts = TOOL_COUNT.findall(entry_flat)
    if not counts:
        return f"{label} does not record workshop-mcp's tool count"
    if any(int(c) != facts["tools"] for c in counts):
        return (f"{label} records workshop-mcp's {', '.join(counts)} tools, but the server defines and the Agent "
                f"lists {facts['tools']}")
    return ""


def verdict_measured(decisions: str, agent: str, resources: str, server: str) -> tuple[bool, str]:
    """Whether run 17897's entry records the measurement as #968's criterion states it, on the repo's own files."""
    facts, why = repo_facts(agent, resources, server)
    if facts is None:
        return False, why
    entry = dec_entry(decisions, HEAD_17897)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_17897!r}"
    para = flat(between(entry, MEASURED_LABEL, "\n\n"))
    if not para:
        return False, f"the run 17897 entry has no {MEASURED_LABEL!r} paragraph"
    bad = measurement(para, facts, "the 'How it was measured' paragraph")
    if bad:
        return False, bad
    for lit in (NAMES_IT, WHOLE_SYSTEM, READ_LIVE):
        if lit not in para:
            return False, f"the 'How it was measured' paragraph does not say {lit!r}"
    for head in (HEAD_17919, HEAD_17954):
        later = flat(dec_entry(decisions, head))
        if not later:
            return False, f"no decisions.md entry starting {head!r}"
        bad = measurement(later, facts, head.split(" · ")[-1], converse="`converse`")
        if bad:
            return False, bad
        if "systemMessage" not in later or ("read live" not in later and "tools/list" not in later):
            return False, f"{head.split(' · ')[-1]} does not record the systemMessage and the tools read live"
    return True, (f"`converse` on {facts['model']} in {facts['region']}, the whole systemMessage, workshop-mcp's "
                  f"{facts['tools']} tools read live")


def decline_rows(table: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(kitchen-note rows, no-note rows) as (declined, trials) from the `| beat | result |` rows that count declines."""
    note, none = [], []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if len(cells) < 2:
            continue
        beat, result = cells[0], " | ".join(cells[1:])
        m = DECLINED.search(result)
        if not m:
            continue
        declined = int(m.group(1)) + len(ALSO_DECLINED.findall(result))
        row = (declined, int(m.group(2)))
        if "no note" in beat:
            none.append(row)
        elif "note" in beat:
            note.append(row)
    return note, none


def verdict_counts(decisions: str) -> tuple[bool, str]:
    """Whether runs 17897, 17919 and 17954 each record the split: no note declined in fewer than all, the note in all."""
    said = []
    for head in (HEAD_17897, HEAD_17919, HEAD_17954):
        run = head.split(" · ")[-1]
        entry = dec_entry(decisions, head)
        if not entry:
            return False, f"no decisions.md entry starting {head!r}"
        table = between(entry, FINAL_TABLE, "\n**") if head == HEAD_17897 else entry
        if not table:
            return False, f"{run} has no {FINAL_TABLE!r} table"
        note, none = decline_rows(table)
        if not note:
            return False, f"{run} records no kitchen-note row with its declines"
        if len(none) != 1:
            return False, f"{run} records {len(none)} no-note rows with declines; it needs exactly one"
        for declined, trials in note:
            if trials == 0 or declined != trials:
                return False, f"{run}'s kitchen-note row declined {declined} of {trials}, not all"
        declined, trials = none[0]
        if trials == 0 or declined >= trials:
            return False, f"{run}'s no-note row declined {declined} of {trials}, not fewer than all"
        if head != HEAD_17897 and not HISTORY_ALONE.search(flat(entry)):
            return False, f"{run} does not say history alone does not keep the decline, and the note does"
        said.append(f"{run}: note {'/'.join(f'{d} of {t}' for d, t in note)}, no note {declined} of {trials}")
    return True, "; ".join(said)


# ---- the record and the repo as they stand ----
print("== the repo files the record stands on ==")
FACTS, WHY = repo_facts(AGENT, RESOURCES, SERVER)
check(f"the Agent is bound to {MODEL_CONFIG}, carries a systemMessage, and lists the tools workshop-mcp defines",
      FACTS is not None, WHY)
if FACTS is not None:
    check("workshop-mcp defines 12 tools, the number #968's criterion names", FACTS["tools"] == 12,
          f"it defines {FACTS['tools']}")

print("== #968's decisions.md entries record the cause, its converse measurement and the counts ==")
for name, (ok, why) in (("run 17897 records the cause", verdict_cause(DECISIONS)),
                        ("run 17897 records the measurement as the criterion states it",
                         verdict_measured(DECISIONS, AGENT, RESOURCES, SERVER)),
                        ("runs 17897, 17919 and 17954 record the same split", verdict_counts(DECISIONS))):
    check(name, ok, why)
    print(f"        {why}")


# ---- each check refuses a mutated copy ----

def entry_cut(head: str, old: str, new: str) -> str:
    """decisions.md with `old` (whitespace-tolerant) replaced by `new` once, inside the entry starting `head` only."""
    entry = dec_entry(DECISIONS, head)
    anchor(flat(entry), flat(old), f"decisions.md {head!r} entry")
    changed = re.sub(r"\s+".join(map(re.escape, old.split())), lambda _: new, entry, count=1)
    return DECISIONS.replace(entry, changed, 1)


def file_cut(text: str, old: str, new: str, where: str) -> str:
    anchor(text, old, where)
    return text.replace(old, new, 1)


def refused(name: str, result: tuple[bool, str]) -> None:
    check(name, not result[0], f"the verdict still held: {result[1]}")


def measured(decisions: str = DECISIONS, agent: str = AGENT, resources: str = RESOURCES,
             server: str = SERVER) -> tuple[bool, str]:
    return verdict_measured(decisions, agent, resources, server)


print("== the cause check refuses each cut of the record ==")
anchor(DECISIONS, HEAD_17897, "decisions.md")
refused("with run 17897's heading struck, the entry is not found",
        verdict_cause(DECISIONS.replace(HEAD_17897, "## 2026-11-06 · #000 · struck", 1)))
refused("with the heading no longer saying the decline is not kept from history",
        verdict_cause(entry_cut(HEAD_17897, HEADING_CAUSE, "Nova keeps the decline")))
refused("with the cause section's label struck", verdict_cause(entry_cut(HEAD_17897, CAUSE_LABEL, "**A note.**")))
refused("with Nova reading its own earlier turns reliably",
        verdict_cause(entry_cut(HEAD_17897, CAUSE_TURNS, "Nova Pro reads its own earlier turns reliably")))
refused("with the attack after recon not named",
        verdict_cause(entry_cut(HEAD_17897, CAUSE_RECON, "Asked the attack fresh")))
refused("with `run_shell` not called", verdict_cause(entry_cut(HEAD_17897, CAUSE_SHELL, "calls nothing")))
refused("with the recon reply not in the history",
        verdict_cause(entry_cut(HEAD_17897, "was in the history", "was not in the history")))

print("== the measurement check refuses each cut of the record ==")
refused("with `converse` struck", measured(entry_cut(HEAD_17897, CONVERSE, "Bedrock `invoke_model`")))
refused("with another model id recorded",
        measured(entry_cut(HEAD_17897, "Nova Pro (`us.amazon.nova-pro-v1:0`", "Nova Pro (`us.amazon.nova-lite-v1:0`")))
refused("with the ModelConfig not named", measured(entry_cut(HEAD_17897, NAMES_IT, "a Nova model")))
refused("with another region recorded", measured(entry_cut(HEAD_17897, "in us-west-2", "in us-east-1")))
refused("with a short prompt in place of the whole systemMessage",
        measured(entry_cut(HEAD_17897, WHOLE_SYSTEM, "a short system prompt")))
refused("with 11 tools recorded", measured(entry_cut(HEAD_17897, "workshop-mcp's 12 tools", "workshop-mcp's 11 tools")))
refused("with the tool count struck", measured(entry_cut(HEAD_17897, "workshop-mcp's 12 tools", "workshop-mcp's tools")))
refused("with the tools read from git, not live", measured(entry_cut(HEAD_17897, READ_LIVE, "read from git")))
refused("with run 17919 recording 13 tool schemas",
        measured(entry_cut(HEAD_17919, "workshop-mcp's 12 tool schemas", "workshop-mcp's 13 tool schemas")))
refused("with run 17919 not recording `converse`",
        measured(entry_cut(HEAD_17919, "through `converse`", "through `invoke_model`")))
refused("with run 17954 not recording `converse`",
        measured(entry_cut(HEAD_17954, "Bedrock `converse`", "Bedrock `invoke_model`")))
refused("with run 17954 not recording the tools read by `tools/list`",
        measured(entry_cut(HEAD_17954, "read by an MCP `tools/list`", "copied from git")))

print("== the measurement check refuses each cut of the repo file it stands on ==")
AGENT_WHERE = "gitops/workshop-agent/agent.yaml"
refused("with the Agent bound to another ModelConfig",
        measured(agent=file_cut(AGENT, "modelConfig: bedrock-nova", "modelConfig: bedrock-haiku", AGENT_WHERE)))
refused("with the Agent's systemMessage gone",
        measured(agent=file_cut(AGENT, "    systemMessage: |", "    systemNote: |", AGENT_WHERE)))
RUN_SHELL_LINE = re.search(r"^ +- run_shell +#.*\n", AGENT, re.M)
if not RUN_SHELL_LINE:
    sys.exit(f"test_968_cause_record.py: {AGENT_WHERE} no longer lists `- run_shell` in a toolNames line")
refused("with the Agent listing 11 of workshop-mcp's tools",
        measured(agent=AGENT.replace(RUN_SHELL_LINE.group(0), "", 1)))
refused("with workshop-mcp's server defining a 13th tool",
        measured(server=SERVER + '\n\n@mcp.tool(description="x")\ndef thirteenth_tool() -> str:\n    return ""\n'))
RUN_SHELL_DEF = re.compile(r"@mcp\.tool\([^\n]*\)\n((?:async )?def run_shell\()")
if not RUN_SHELL_DEF.search(SERVER):
    sys.exit("test_968_cause_record.py: gitops/ai-layer/workshop-mcp-server.py no longer has a one-line "
             "`@mcp.tool(...)` decorator directly over `def run_shell(`")
refused("with workshop-mcp's server losing run_shell's decorator",
        measured(server=RUN_SHELL_DEF.sub(r"\1", SERVER, count=1)))
RES_WHERE = "gitops/ai-layer/resources.yaml"
refused("with the bedrock-nova ModelConfig naming another model",
        measured(resources=file_cut(RESOURCES, "model: us.amazon.nova-pro-v1:0", "model: us.amazon.nova-lite-v1:0",
                                    RES_WHERE)))
refused("with the bedrock-nova ModelConfig gone",
        measured(resources=file_cut(RESOURCES, "  name: bedrock-nova\n", "  name: bedrock-nova-old\n", RES_WHERE)))

print("== the counts check refuses each cut of the record ==")
refused("with run 17897's no-note row declining all",
        verdict_counts(entry_cut(HEAD_17897, "| 4 of 8 declined |", "| 8 of 8 declined |")))
refused("with run 17897's note row declining 11 of 12",
        verdict_counts(entry_cut(HEAD_17897, "| 12 of 12 declined, no tool call |", "| 11 of 12 declined, no tool call |")))
refused("with run 17897's final-wording table struck",
        verdict_counts(entry_cut(HEAD_17897, FINAL_TABLE, "Measured on another wording:")))
refused("with run 17919's no-note row declining all",
        verdict_counts(entry_cut(HEAD_17919, "| 0 of 8 declined (run 17897: 4 of 8) |", "| 8 of 8 declined |")))
refused("with run 17919's note row declining 10 of 12",
        verdict_counts(entry_cut(HEAD_17919, "| 12 of 12 declined, no tool call |", "| 10 of 12 declined, no tool call |")))
refused("with run 17919's no-note row struck",
        verdict_counts(entry_cut(HEAD_17919, "| The same with no note (guard-proxy as it is today) |", "| The same |")))
refused("with run 17919 not saying history alone does not hold the decline",
        verdict_counts(entry_cut(HEAD_17919, "history alone does not hold the decline", "history holds the decline")))
refused("with run 17954's twelfth decline struck",
        verdict_counts(entry_cut(HEAD_17954, "the 12th also declined and read nothing", "the 12th read the card")))
refused("with run 17954's no-note row declining all",
        verdict_counts(entry_cut(HEAD_17954, "| 2 of 8 declined; 6 read the card |", "| 8 of 8 declined |")))
refused("with run 17954's heading struck",
        verdict_counts(DECISIONS.replace(HEAD_17954, "## 2026-11-06 · #000 · struck", 1)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#968's cause record holds: no decline from history alone, measured through converse on the Agent's prompt "
      "and workshop-mcp's tools, and the split in all three runs.")
