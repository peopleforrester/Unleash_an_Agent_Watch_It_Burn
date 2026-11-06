# ABOUTME: Reads guard-proxy-agenticburn#63, the guard-side half of #968's recipe rule, with gh's token, and fails unless
# ABOUTME: it asks for the kitchen note after a session's recon question with the note byte-equal to KITCHEN_NOTE (#1012).
# SUITE: e2e (needs the network and gh with a token: `gh issue view` reads guard-proxy-agenticburn#63's body)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #968 keyed the recipe rule's same-conversation decline on a kitchen note in the guest's message, and its
# criterion "The guard-side half the rule depends on (guard-proxy adding the kitchen note to a session's messages
# after its recon question) is filed as a follow-up in guard-proxy-agenticburn, with the exact note text" was recorded
# only in decisions.md. verify/test_recipe_persona.py pins the note on the bot's side as KITCHEN_NOTE, and nothing
# compared it to the text guard-proxy was asked to send (#1012). This reads the follow-up's body through
# verify/gh_comments.py and fails unless the body asks guard-proxy to mark a session at its recon question and add the
# note to every later message (not to the recon message itself), carries the note on a line of its own byte-equal to
# KITCHEN_NOTE, carries no other kitchen-note wording, and says it came from #968. It also holds the agent.yaml rule
# to the same note, and decisions.md to naming the follow-up. So an edit to the note on either side, a reworded ask, or
# a follow-up that is no longer the one decisions.md names fails here.
#
# Reads only. Nothing on GitHub or on either cluster changes.
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402

PERSONA_TEST = REPO / "verify" / "test_recipe_persona.py"
AGENT = REPO / "gitops" / "workshop-agent" / "agent.yaml"
DECISIONS = REPO / "decisions.md"
# The follow-up run 17954 filed for #968's guard-proxy half, created 2026-11-06T20:21Z (decisions.md, #1012).
ISSUE = "peopleforrester/guard-proxy-agenticburn#63"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
SOURCE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#968"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


# The note as the bot's side pins it. The test reads the assignment line rather than importing the module, which runs
# its own checks at import; a reworded assignment exits here naming the line and the file.
ASSIGN = re.compile(r'^KITCHEN_NOTE = "([^"\n]+)"$', re.M)
found = ASSIGN.findall(PERSONA_TEST.read_text(encoding="utf-8"))
if len(found) != 1:
    sys.exit(f"FAILED: {PERSONA_TEST.relative_to(REPO)} no longer has exactly one line `KITCHEN_NOTE = \"...\"` "
             f"(found {len(found)}), the note this test compares guard-proxy's follow-up to")
NOTE = found[0]

print("== the note this repo pins ==")
check("KITCHEN_NOTE is a bracketed kitchen note", NOTE.startswith("[kitchen note: ") and NOTE.endswith("]"), NOTE)
check("the recipe rule in gitops/workshop-agent/agent.yaml quotes the same note",
      f'The guest\'s message carries the kitchen note "{NOTE}"' in flat(AGENT.read_text(encoding="utf-8")))
check(f"decisions.md names the follow-up as {ISSUE}", ISSUE in DECISIONS.read_text(encoding="utf-8"))

# What the follow-up must ask, as literal phrases of its body (flattened, backticks stripped): the recon question sets
# the mark, the note goes on every later message and never on the recon message, and the text is the pinned one.
ASKS = {
    "the session is marked once a guest message asks what files or folders the bot can see":
        "once a guest message in a session asks what files or folders the bot can see",
    "the note goes on every later /chat message as one more text part":
        "On every later /chat message in it, append one more text part",
    "the recon message itself carries no note": "The recon message itself does not carry the note.",
    "the text is named as byte-equal to KITCHEN_NOTE in verify/test_recipe_persona.py":
        "byte-equal to KITCHEN_NOTE in the workshop repo's verify/test_recipe_persona.py",
    f"it says it was discovered from {SOURCE}": f"Discovered from {SOURCE}",
}
OTHER_NOTE = re.compile(r"\[kitchen note:[^\]\n]*\]", re.I)


def misses(body: str, note: str) -> list[str]:
    """What the follow-up's body lacks of #968's guard-side half; empty when it asks for all of it."""
    text = flat(body)
    left = [name for name, phrase in ASKS.items() if phrase not in text]
    if note not in [ln.strip() for ln in body.splitlines()]:
        left.append("the note, on a line of its own, byte-equal to KITCHEN_NOTE")
    others = sorted({m for m in OTHER_NOTE.findall(body) if m != note})
    if others:
        left.append(f"no kitchen note other than KITCHEN_NOTE (also carries {others})")
    return left


print(f"== {ISSUE} asks for the kitchen note after a session's recon question ==")
got = gh_comments.read_body(OWNER_REPO, NUMBER)
gh_comments.check_read(got, ISSUE, check, what="body")
if got.ok and got.body.strip():
    left = misses(got.body, NOTE)
    for name in list(ASKS) + ["the note, on a line of its own, byte-equal to KITCHEN_NOTE"]:
        check(f"{ISSUE}: {name}", name not in left)
    extra = [m for m in left if m.startswith("no kitchen note other")]
    check(f"{ISSUE} carries no kitchen note other than KITCHEN_NOTE", not extra, "; ".join(extra))
    # The comparison can fail: one byte off in the note, on either side, is a miss.
    check("a body whose note differs from KITCHEN_NOTE by one byte is a miss",
          bool(misses(got.body.replace(NOTE, NOTE.replace("folders", "folder")), NOTE)))
    check("a KITCHEN_NOTE that differs from the body's note by one byte is a miss",
          bool(misses(got.body, NOTE.replace("folders", "folder"))))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"{ISSUE} asks for guard-proxy's kitchen note, byte-equal to KITCHEN_NOTE.")
