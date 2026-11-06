# ABOUTME: Pins #968's last criterion (#1013): its decisions.md entry names, under "Not yet run on a cluster", the live
# ABOUTME: run on the public bot once the recipe rule and guard-proxy's kitchen note are both on the community cluster.
"""Holds the criterion of #968 that test review run 18016 found no test checked (#1013).

#968's criterion: the live run on the public bot, once both changes are on the community cluster, is named under "Not
yet run on a cluster" in the decisions.md entry. Three #968 entries landed (runs 17897, 17919, 17954); the last one,
"## 2026-11-06 · #968 · run 17954", is the work that merged, and its paragraph names the run "as named in the two
entries above". So the record is read here as literal text, and holds when:

  1. the run 17954 entry carries exactly one paragraph opening "**Not yet run on a cluster.**";
  2. that paragraph names the live run on the public bot: https://attackme.burritobot.co/, `c3-recon` then
     `c3-attack` in one chat, Reset, then `c3-attack`, in that order;
  3. it says when: once this rule and guard-proxy's note are both on watch-it-burn-community, the community cluster;
  4. the two earlier #968 entries it points back to sit above it, and each carries one such paragraph naming the same
     public-bot run, gated on both changes being on the community cluster.

The record only means what it says while its names do, so the test also checks that `c3-recon` and `c3-attack` are
prompt ids in the fallback sheet (recon first), that the URL is event.js's public bot, that the public bot's chat has
the Reset button, that CLAUDE.md names watch-it-burn-community as the public community cluster, and that the kitchen
note the entry quotes is `KITCHEN_NOTE` in test_recipe_persona.py and is the note the rule in agent.yaml keys on.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a mutated copy of the real record with the thing it reads
struck or changed, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
PROMPTS = yaml.safe_load((REPO / "facilitation" / "kubecon-na-2026" / "fallback" / "prompts.yaml").read_text("utf-8"))
EVENT_JS = (REPO / "gitops" / "ai-layer" / "web" / "event.js").read_text(encoding="utf-8")
CHAT_HTML = (REPO / "gitops" / "ai-layer" / "web" / "burritbot.html").read_text(encoding="utf-8")
CLAUDE_MD = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
AGENT_YAML = (REPO / "gitops" / "workshop-agent" / "agent.yaml").read_text(encoding="utf-8")
PERSONA_TEST = (REPO / "verify" / "test_recipe_persona.py").read_text(encoding="utf-8")

HEAD_LAST = "## 2026-11-06 · #968 · run 17954"
HEADS_ABOVE = ("## 2026-11-06 · #968 · run 17897", "## 2026-11-06 · #968 · run 17919")
LABEL = "**Not yet run on a cluster.**"
PUBLIC_URL = "https://attackme.burritobot.co/"
COMMUNITY = "watch-it-burn-community"
POINTER = "as named in the two entries above"
# The four beats, in order: recon then the attack in one chat, Reset, then the attack fresh.
BEATS = re.compile(r"`c3-recon` then `c3-attack` in one chat, Reset, then `c3-attack`")
# Run 17897's entry, the first, words the same beats without "in one chat".
BEATS_ABOVE = re.compile(r"`c3-recon` then `c3-attack`(?: in one chat)?, Reset, then `c3-attack`")
# When: both changes, the rule and guard-proxy's note, on the community cluster.
WHEN_LAST = "once this rule and guard-proxy's note are both on " + COMMUNITY
WHEN_ABOVE = re.compile(r"once this rule and guard-proxy's note are both on (?:the community cluster|"
                        + re.escape(COMMUNITY) + r")")
KITCHEN_RE = re.compile(r'^KITCHEN_NOTE = "([^"]+)"$', re.M)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_968_not_yet_run_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a phrase wrapped across lines reads as one line."""
    return " ".join(text.split())


def dec_entry(text: str, head: str) -> tuple[int, str]:
    """(offset, entry) for the decisions.md entry starting `head`, to the next level-2 heading or EOF; (-1, "")."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return (m.start(), m.group(0)) if m else (-1, "")


def not_yet_paragraphs(entry: str) -> list[str]:
    """Every paragraph of `entry` that opens with the bold "Not yet run on a cluster." label, whitespace flattened."""
    return [flat(p) for p in re.split(r"\n\s*\n", entry) if p.lstrip().startswith(LABEL)]


def verdict(decisions: str) -> tuple[bool, str]:
    """Whether #968's last entry names the public-bot live run under "Not yet run on a cluster", and why not."""
    at_last, last = dec_entry(decisions, HEAD_LAST)
    if not last:
        return False, f"no decisions.md entry starting {HEAD_LAST!r}"
    paras = not_yet_paragraphs(last)
    if len(paras) != 1:
        return False, f"the run 17954 entry has {len(paras)} paragraphs opening {LABEL!r}; it needs exactly one"
    para = paras[0]
    if PUBLIC_URL not in para:
        return False, f"the paragraph does not name the public bot, {PUBLIC_URL}"
    if "public bot" not in para:
        return False, "the paragraph does not say the run is on the public bot"
    if not BEATS.search(para):
        return False, "the paragraph does not name the beats: `c3-recon` then `c3-attack` in one chat, Reset, then `c3-attack`"
    if WHEN_LAST not in para:
        return False, f"the paragraph does not gate the run on both changes being on {COMMUNITY}: {WHEN_LAST!r}"
    if para.index(PUBLIC_URL) > para.index(WHEN_LAST):
        return False, "the community-cluster gate is not the public-bot run's own: it comes before the URL"
    for head in HEADS_ABOVE:
        at, entry = dec_entry(decisions, head)
        if not entry:
            return False, f"no decisions.md entry starting {head!r}, which the paragraph points back to"
        if at > at_last:
            return False, f"{head!r} is below the run 17954 entry, not one of 'the two entries above'"
        above = not_yet_paragraphs(entry)
        if len(above) != 1:
            return False, f"{head!r} has {len(above)} paragraphs opening {LABEL!r}; it needs exactly one"
        if "attackme.burritobot.co" not in above[0] or not BEATS_ABOVE.search(above[0]):
            return False, f"{head!r}'s paragraph does not name the same public-bot run"
        if not WHEN_ABOVE.search(above[0]):
            return False, f"{head!r}'s paragraph does not gate that run on both changes on the community cluster"
    return True, ("the run 17954 entry names the four public-bot beats on " + PUBLIC_URL + ", once the rule and "
                  "guard-proxy's note are both on " + COMMUNITY + ", as the two entries above do")


# ---- what the record's names mean ----
print("== the names in the record still mean what they say ==")
ids = [p.get("id") for p in PROMPTS.get("prompts", [])] if isinstance(PROMPTS, dict) else []
check("the fallback sheet has prompt ids c3-recon and c3-attack", "c3-recon" in ids and "c3-attack" in ids,
      f"ids: {ids}")
check("c3-recon comes before c3-attack on the sheet",
      "c3-recon" in ids and "c3-attack" in ids and ids.index("c3-recon") < ids.index("c3-attack"))
check(f"event.js's public bot is {PUBLIC_URL}", f'publicUrl: "{PUBLIC_URL}"' in EVENT_JS)
check("the public bot's chat has the Reset button that starts a new conversation",
      re.search(r'<button class="reset" onclick="resetChat\(\)"[^>]*>↺ Reset</button>', CHAT_HTML) is not None)
check(f"CLAUDE.md names {COMMUNITY} as the public community cluster",
      f"`{COMMUNITY}`\n   (the public community cluster)" in CLAUDE_MD
      or f"`{COMMUNITY}` (the public community cluster)" in flat(CLAUDE_MD))
km = KITCHEN_RE.search(PERSONA_TEST)
check("test_recipe_persona.py holds guard-proxy's note as KITCHEN_NOTE", km is not None)
NOTE = km.group(1) if km else ""
check("the rule in agent.yaml keys on that note, byte for byte", bool(NOTE) and NOTE in flat(AGENT_YAML))
_, LAST_ENTRY = dec_entry(DECISIONS, HEAD_LAST)
check("the run 17954 entry quotes that note as guard-proxy's half", bool(NOTE) and f"`{NOTE}`" in flat(LAST_ENTRY))

# ---- the record as it stands ----
anchor(DECISIONS, HEAD_LAST, "decisions.md")
anchor(LAST_ENTRY, LABEL, "decisions.md #968 run 17954 entry")
PARA = next(p for p in re.split(r"\n\s*\n", LAST_ENTRY) if p.lstrip().startswith(LABEL))
FLAT = flat(PARA)
for lit in (PUBLIC_URL, "public bot", "`c3-recon` then `c3-attack` in one chat, Reset, then `c3-attack`", WHEN_LAST,
            POINTER):
    anchor(FLAT, lit, "decisions.md #968 run 17954 Not-yet-run paragraph")

print("== #968's entry names the public-bot live run under \"Not yet run on a cluster\" ==")
ok, why = verdict(DECISIONS)
check("the record is there and names the run", ok, why)
print(f"        {why}")


def cut(old: str, new: str) -> str:
    """decisions.md with `old` replaced by `new` once inside the run 17954 Not-yet-run paragraph only."""
    anchor(FLAT, old, "decisions.md #968 run 17954 Not-yet-run paragraph")
    return DECISIONS.replace(PARA, FLAT.replace(old, new, 1), 1)


def refused(name: str, decisions: str, reason: str) -> None:
    """The verdict refuses `decisions`, and for the reason the cut aimed at, so one check cannot mask another."""
    ok_, why_ = verdict(decisions)
    check(name, not ok_ and reason in why_,
          f"the verdict still held: {why_}" if ok_ else f"refused for another reason: {why_} (wanted {reason!r})")


def above_para(head: str) -> str:
    _, entry = dec_entry(DECISIONS, head)
    anchor(entry, LABEL, f"decisions.md entry {head!r}")
    return next(p for p in re.split(r"\n\s*\n", entry) if p.lstrip().startswith(LABEL))


print("== each cut of the real record is refused ==")
refused("with the run 17954 heading struck, the entry is not found",
        DECISIONS.replace(HEAD_LAST, "## 2026-11-06 · #000 · struck", 1), "no decisions.md entry")
refused("with the Not-yet-run paragraph removed, nothing is named", DECISIONS.replace(PARA, "", 1), "has 0 paragraphs")
refused("with the label reworded, nothing is named under it",
        DECISIONS.replace(PARA, PARA.replace(LABEL, "**Later.**", 1), 1), "has 0 paragraphs")
refused("with the paragraph doubled, the record is ambiguous", DECISIONS.replace(PARA, PARA + "\n\n" + PARA, 1),
        "has 2 paragraphs")
refused("with the public bot's URL struck, it is refused", cut(PUBLIC_URL, "the bot"), "does not name the public bot")
refused("with the private bot's URL in its place, it is refused",
        cut(PUBLIC_URL, "https://burritobot-private.burritobot.co/"), "does not name the public bot")
refused("with 'public bot' struck, it is refused", cut("public bot", "bot"), "is on the public bot")
refused("with c3-recon struck, it is refused", cut("`c3-recon` then ", ""), "does not name the beats")
refused("with the beats out of order, it is refused",
        cut("`c3-recon` then `c3-attack` in one chat", "`c3-attack` then `c3-recon` in one chat"),
        "does not name the beats")
refused("with Reset struck, it is refused", cut("in one chat, Reset, then", "in one chat, then"),
        "does not name the beats")
refused("with guard-proxy's note dropped from the gate, it is refused",
        cut("once this rule and guard-proxy's note are both on", "once this rule is on"), "does not gate the run")
refused("with the private cluster in the gate, it is refused",
        cut(WHEN_LAST, WHEN_LAST.replace(COMMUNITY, "watch-it-burn-private")), "does not gate the run")
refused("with the gate struck, it is refused", cut(WHEN_LAST, "later"), "does not gate the run")
for head in HEADS_ABOVE:
    ap = above_para(head)
    refused(f"with {head!r}'s Not-yet-run paragraph removed, the pointer back fails", DECISIONS.replace(ap, "", 1),
            f"{head!r} has 0 paragraphs")
    anchor(flat(ap), "attackme.burritobot.co", f"decisions.md entry {head!r}")
    refused(f"with {head!r}'s public bot struck, the pointer back fails",
            DECISIONS.replace(ap, flat(ap).replace("attackme.burritobot.co", "the bot"), 1),
            f"{head!r}'s paragraph does not name the same public-bot run")
    refused(f"with {head!r}'s Reset struck, the pointer back fails",
            DECISIONS.replace(ap, flat(ap).replace(", Reset, then", ", then", 1), 1),
            f"{head!r}'s paragraph does not name the same public-bot run")
    if not WHEN_ABOVE.search(flat(ap)):
        sys.exit(f"test_968_not_yet_run_record.py: decisions.md entry {head!r} no longer holds the gate "
                 f"{WHEN_ABOVE.pattern!r}; reword the test's anchor to match, do not revert the doc")
    refused(f"with {head!r}'s gate dropping guard-proxy's note, the pointer back fails",
            DECISIONS.replace(ap, WHEN_ABOVE.sub("once this rule is on the community cluster", flat(ap)), 1),
            f"{head!r}'s paragraph does not gate")
    refused(f"with {head!r} struck, the pointer back fails", DECISIONS.replace(head, "## 2026-11-06 · #000 · x", 1),
            f"no decisions.md entry starting {head!r}")
at_last, last = dec_entry(DECISIONS, HEAD_LAST)
refused("with the run 17954 entry moved above the two it points back to, it is refused",
        last + DECISIONS[:at_last] + DECISIONS[at_last + len(last):], "is below the run 17954 entry")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#968's record holds: the public-bot live run is named under \"Not yet run on a cluster\".")
