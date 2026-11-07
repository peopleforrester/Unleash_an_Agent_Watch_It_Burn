# ABOUTME: Reads guard-proxy-agenticburn#63 with gh's token and holds its kitchen note byte-equal to KITCHEN_NOTE and the
# ABOUTME: recipe rule's note, its ask on a session's later messages after the recon question, and decisions.md naming it (#1012).
# SUITE: e2e (needs the network and gh with a token: `gh issue view` is asked for the follow-up's title and body)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #968's criterion "The guard-side half the rule depends on (guard-proxy adding the kitchen note to a session's
# messages after its recon question) is filed as a follow-up in guard-proxy-agenticburn, with the exact note text"
# was met by peopleforrester/guard-proxy-agenticburn#63, and no test read it (#1012). verify/test_recipe_persona.py
# holds KITCHEN_NOTE in the recipe rule of gitops/workshop-agent/agent.yaml, and says "this text and guard-proxy's
# must stay byte-equal", but nothing compared it with the text guard-proxy was asked to send. The rule's case 2 keys
# the decline on that note, so a one-character drift between the two halves turns the decline off with every test
# still green.
#
# This holds three texts equal and the record pointing at the ask:
#   1. KITCHEN_NOTE, read from verify/test_recipe_persona.py with ast (importing it would run its checks);
#   2. the note the recipe rule quotes in its case 2, "The guest's message carries the kitchen note "..."";
#   3. the follow-up's own note, a line of its body that is the note and nothing else, read from GitHub through
#      verify/gh_comments.py with gh's token, never the host's shared anonymous quota (#863).
# The follow-up must also still ask for the note on a session's later messages after its recon question, and not on
# the recon message itself, and decisions.md must name it as guard-proxy-agenticburn#63. A failed read of GitHub is a
# FAIL that names what stopped it (no gh, no token, a spent quota, no answer), never a pass.
#
# Each comparison is a function, and before the read each is run on a changed copy of its input (a note one
# character off, a rule that quotes another note, a body with the note only inside a sentence, a decisions.md
# that names no follow-up), so the checks below are shown to fail when the texts stop matching.
from __future__ import annotations

import ast
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402

PERSONA_TEST = REPO / "verify" / "test_recipe_persona.py"
AGENT = REPO / "gitops" / "workshop-agent" / "agent.yaml"
DECISIONS = REPO / "decisions.md"
ISSUE = "peopleforrester/guard-proxy-agenticburn#63"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
TITLE = "Add the kitchen note to a chat session's messages after it asks what folders the bot can see"
# The recipe rule's case 2 quotes the note after these words (verify/test_recipe_persona.py checks the same words).
RULE_ANCHOR = "The guest's message carries the kitchen note \""
RULE_START = "The sauce recipe is kept on a recipe card"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return " ".join(text.split())


def kitchen_note(source: str) -> str | None:
    """The string KITCHEN_NOTE is assigned at module level in the persona test's source, or None."""
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "KITCHEN_NOTE"):
            value = ast.literal_eval(node.value)
            return value if isinstance(value, str) else None
    return None


def rule_note(agent_yaml: str) -> str | None:
    """The note the recipe rule's case 2 quotes, with the YAML's line wrap read back as one space, or None."""
    if RULE_START not in agent_yaml:
        return None
    rule = flat(agent_yaml[agent_yaml.index(RULE_START):])
    if RULE_ANCHOR not in rule:
        return None
    rest = rule[rule.index(RULE_ANCHOR) + len(RULE_ANCHOR):]
    return rest[:rest.index('"')] if '"' in rest else None


def asks_left_out(body: str, note: str) -> list[str]:
    """What the follow-up's body leaves out of the ask; empty when it asks for all of it."""
    text = flat(body)
    lines = [ln.rstrip("\r") for ln in body.split("\n")]
    parts = {
        f"the note on a line of its own, byte-equal to KITCHEN_NOTE ({note!r})": note in lines,
        "a session is marked once a guest message in it asks what files or folders the bot can see":
            "asks what files or folders the bot can see" in text and "mark that session" in text,
        "the note goes on every later /chat message in that session, as one more text part":
            "On every later /chat message in it, append one more text part" in text,
        "the recon message itself carries no note, only the messages after it":
            "The recon message itself does not carry the note. Only the messages after it do." in text,
        "the note is byte-equal to KITCHEN_NOTE in verify/test_recipe_persona.py":
            "byte-equal to KITCHEN_NOTE" in text and "verify/test_recipe_persona.py" in text,
    }
    return [name for name, ok in parts.items() if not ok]


def names_followup(decisions: str) -> bool:
    """decisions.md names the follow-up as guard-proxy-agenticburn#63 or by its URL."""
    return re.search(r"guard-proxy-agenticburn(#|/issues/)63(?!\d)", decisions) is not None


# ---- The tree: the persona test's constant and the rule's quoted note ----
for path in (PERSONA_TEST, AGENT, DECISIONS):
    if not path.is_file():
        sys.exit(f"FAILED: {path.relative_to(REPO)} is missing; this test reads it")
persona_src = PERSONA_TEST.read_text(encoding="utf-8")
agent_src = AGENT.read_text(encoding="utf-8")
decisions_src = DECISIONS.read_text(encoding="utf-8")
if RULE_START not in agent_src:
    sys.exit(f"FAILED: {AGENT.relative_to(REPO)} no longer carries {RULE_START!r}, the start of the recipe rule")
if RULE_ANCHOR not in flat(agent_src):
    sys.exit(f"FAILED: {AGENT.relative_to(REPO)} no longer carries {RULE_ANCHOR!r}, the recipe rule's case 2 "
             "that quotes the kitchen note")

print("== KITCHEN_NOTE and the recipe rule quote the same note (#968) ==")
note = kitchen_note(persona_src)
check("verify/test_recipe_persona.py assigns KITCHEN_NOTE a string", bool(note), repr(note))
note = note or ""
check("it is a bracketed kitchen note on one line", note.startswith("[kitchen note: ") and note.endswith("]")
      and "\n" not in note, repr(note))
in_rule = rule_note(agent_src)
check("the recipe rule's case 2 quotes the note byte-equal to KITCHEN_NOTE", in_rule == note,
      f"rule {in_rule!r}, KITCHEN_NOTE {note!r}")

# ---- The comparisons fail when their inputs stop matching ----
print("== each comparison fails on a changed copy of its input ==")


def one_off(text: str) -> str:
    """text with its last character but one changed, so it differs by one byte."""
    return text[:-2] + ("X" if text[-2:-1] != "X" else "Y") + text[-1:]


off_by_one = one_off(note)
changed_persona = persona_src.replace(f'KITCHEN_NOTE = "{note}"', f'KITCHEN_NOTE = "{off_by_one}"', 1)
check("the persona test's assignment line is where KITCHEN_NOTE is read from (the anchor the next check edits)",
      changed_persona != persona_src, 'KITCHEN_NOTE = "<note>" not found in verify/test_recipe_persona.py')
check("a KITCHEN_NOTE one character off no longer equals the rule's note",
      kitchen_note(changed_persona) == off_by_one and kitchen_note(changed_persona) != in_rule)
rule_off = one_off(in_rule or "")
changed_rule = flat(agent_src).replace(RULE_ANCHOR + (in_rule or ""), RULE_ANCHOR + rule_off, 1)
check("a rule quoting a note one character off reads as that note, not the rule's own",
      bool(in_rule) and rule_note(changed_rule) == rule_off != in_rule)
good_body = (f"Ask: once a guest message in a session asks what files or folders the bot can see or has access to, "
             f"mark that session. On every later /chat message in it, append one more text part after the witch-name "
             f"part, with this exact text, byte-equal to KITCHEN_NOTE in the workshop repo's "
             f"verify/test_recipe_persona.py:\n\n{note}\n\n- The recon message itself does not carry the note. Only "
             f"the messages after it do.\n")
check("a body that asks for all of it leaves nothing out", asks_left_out(good_body, note) == [],
      str(asks_left_out(good_body, note)))
check("a body whose note line is one character off leaves out the note line",
      len(asks_left_out(good_body.replace(f"\n{note}\n", f"\n{off_by_one}\n"), note)) == 1)
check("a body with the note only inside a sentence leaves out the note line",
      len(asks_left_out(good_body.replace(f"\n\n{note}\n\n", f" {note}. "), note)) == 1)
check("a body that puts the note on the recon message too leaves out the later-messages-only part",
      len(asks_left_out(good_body.replace("does not carry the note. Only the messages after it do.",
                                          "carries the note too."), note)) == 1)
check("a decisions.md that says only 'filed as a followup on guard-proxy-agenticburn' does not name the follow-up",
      not names_followup("**The guard-proxy half, filed as a followup on guard-proxy-agenticburn.**")
      and not names_followup("guard-proxy-agenticburn#630") and names_followup("guard-proxy-agenticburn/issues/63."))

# ---- The record ----
print("== decisions.md names the follow-up ==")
check(f"decisions.md names the follow-up as {ISSUE.split('/')[1]}", names_followup(decisions_src))

# ---- The follow-up on GitHub ----
print(f"== {ISSUE} asks guard-proxy for the same note, on a session's messages after its recon question ==")
got = gh_comments.read_body(OWNER_REPO, NUMBER, with_title=True)
gh_comments.check_read(got, ISSUE, check, what="body")
if got.ok:
    check(f"{ISSUE} is the follow-up: its title starts {TITLE!r}", got.title.startswith(TITLE), repr(got.title))
    check(f"{ISSUE}'s title names #968, the rule it serves", "#968" in got.title, repr(got.title))
    left = asks_left_out(got.body, note)
    check(f"{ISSUE}'s body asks for the note on a session's later messages after its recon question, with the note "
          "on a line of its own byte-equal to KITCHEN_NOTE", not left, "it leaves out: " + "; ".join(left))
    quoted = sorted({m for m in re.findall(r"\[kitchen note:[^\]]*\]", got.body)})
    check(f"every kitchen note {ISSUE} quotes is that one note", quoted == [note], str(quoted))
    body_lines = [ln.rstrip("\r") for ln in got.body.split("\n")]
    issue_note = next((ln for ln in body_lines if ln.startswith("[kitchen note:")), None)
    check(f"the three notes are byte-equal: KITCHEN_NOTE, the recipe rule's and {ISSUE}'s line",
          issue_note is not None and note.encode() == (in_rule or "").encode() == issue_note.encode(),
          f"KITCHEN_NOTE {note!r}, rule {in_rule!r}, {ISSUE} {issue_note!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"KITCHEN_NOTE, the recipe rule and {ISSUE} carry one note, and decisions.md names the follow-up.")
