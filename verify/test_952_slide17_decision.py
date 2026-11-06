# ABOUTME: Pins #952's slide-17 criterion (#974): its decisions.md entry decides whether the chosen folder name
# ABOUTME: changes slide 17, and a "changes" verdict carries a rounds-agenticburn agent-task issue link.
"""Holds the criterion of #952 that test review run 17827 found no test checked (#974).

#952's criterion: whether the chosen folder name changes slide 17 is decided and recorded in decisions.md; if it
does, an agent-task issue is filed on rounds-agenticburn and the issue link is recorded. The record is history, read
here as literal text:

  1. decisions.md's "## 2026-11-06 · #952 · run 17805" entry carries one bold "**Slide 17 ...**" paragraph, and its
     label states exactly one verdict: "Slide 17 is unchanged" or "Slide 17 changes".
  2. A "changes" verdict links an issue on peopleforrester/rounds-agenticburn (the URL or the owner/repo#N form).
  3. An "unchanged" verdict says no agent-task issue is filed, and names the folder it was decided for. That folder
     must be the one #951's entry records as chosen and the one the C3 attack prompt in
     facilitation/kubecon-na-2026/fallback/prompts.yaml sends (verify/test_replay_prompts.py holds the /kubecon sheet
     equal to it). A later change of folder leaves the recorded verdict about a folder nobody uses, so this fails
     then, asking for the slide-17 question to be decided again for the new name.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a mutated copy with the thing it reads struck or
flipped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
PROMPTS_PATH = REPO / "facilitation" / "kubecon-na-2026" / "fallback" / "prompts.yaml"
PROMPTS_TEXT = PROMPTS_PATH.read_text(encoding="utf-8")

HEAD_952 = "## 2026-11-06 · #952 · run 17805"
HEAD_951 = "## 2026-11-05 · #951 · run 17734"
SLIDE_LABEL = "**Slide 17"
UNCHANGED = "Slide 17 is unchanged"
CHANGES = "Slide 17 changes"
NO_ISSUE = "no agent-task issue is filed"
FOLDER_951 = re.compile(r"folder `([a-z0-9-]+)`")
FOLDER_952 = re.compile(r"The folder\s+#951 chose is `([a-z0-9-]+)`")
ATTACK_FOLDER = re.compile(r"in the ([a-z0-9-]+) folder")
ISSUE_LINK = re.compile(
    r"https://github\.com/peopleforrester/rounds-agenticburn/issues/\d+|peopleforrester/rounds-agenticburn#\d+")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_952_slide17_decision.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def dec_entry(text: str, head: str) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def slide_paragraphs(entry: str) -> list[str]:
    """Every paragraph of `entry` that opens with the bold slide-17 label."""
    return [p for p in re.split(r"\n\s*\n", entry) if p.lstrip().startswith(SLIDE_LABEL)]


def attack_folder(prompts_text: str) -> str:
    """The folder the c3-attack prompt names, or empty when the prompt or the phrase is gone."""
    doc = yaml.safe_load(prompts_text) or {}
    items = doc.get("prompts", doc) if isinstance(doc, dict) else doc
    for item in items or []:
        if isinstance(item, dict) and item.get("id") == "c3-attack":
            m = ATTACK_FOLDER.search(str(item.get("prompt", "")))
            return m.group(1) if m else ""
    return ""


def verdict(decisions: str, prompts_text: str) -> tuple[bool, str]:
    """Whether #952's slide-17 criterion holds on these texts, and why not when it does not."""
    entry = dec_entry(decisions, HEAD_952)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_952!r}"
    paras = slide_paragraphs(entry)
    if len(paras) != 1:
        return False, f"the #952 entry has {len(paras)} paragraphs opening {SLIDE_LABEL!r}; it needs exactly one"
    para = paras[0]
    label = para.split("**", 2)[1] if para.count("**") >= 2 else ""
    says_unchanged, says_changes = UNCHANGED in label, CHANGES in label
    if says_unchanged == says_changes:
        return False, (f"the slide-17 label {label!r} must state exactly one verdict, "
                       f"{UNCHANGED!r} or {CHANGES!r}")
    if says_changes:
        if not ISSUE_LINK.search(para):
            return False, "slide 17 changes, but the paragraph links no rounds-agenticburn agent-task issue"
        return True, "slide 17 changes and the rounds-agenticburn issue is linked"
    if NO_ISSUE not in para:
        return False, f"slide 17 is unchanged, but the paragraph does not say {NO_ISSUE!r}"
    m = FOLDER_952.search(para)
    if not m:
        return False, "the unchanged verdict does not name the folder it was decided for"
    folder = m.group(1)
    m951 = FOLDER_951.search(dec_entry(decisions, HEAD_951))
    if not m951 or m951.group(1) != folder:
        return False, (f"the verdict is for folder {folder!r}, but #951's entry records "
                       f"{m951.group(1) if m951 else 'no folder'!r} as chosen")
    sent = attack_folder(prompts_text)
    if sent != folder:
        return False, (f"the verdict is for folder {folder!r}, but the c3-attack prompt in {PROMPTS_PATH.name} "
                       f"names {sent or 'no folder'!r}: decide slide 17 again for the folder in use and record it")
    return True, f"slide 17 is unchanged for folder {folder!r}, the one #951 chose and the attack prompt sends"


# ---- the record as it stands ----
anchor(DECISIONS, HEAD_952, "decisions.md")
anchor(DECISIONS, HEAD_951, "decisions.md")
ENTRY = dec_entry(DECISIONS, HEAD_952)
PARAS = slide_paragraphs(ENTRY)
anchor(ENTRY, SLIDE_LABEL, "decisions.md #952 entry")
PARA = PARAS[0]
for lit in (UNCHANGED, NO_ISSUE, "#951 chose is `burrito-data`"):
    anchor(PARA, lit, "decisions.md #952 slide-17 paragraph")
anchor(dec_entry(DECISIONS, HEAD_951), "folder `burrito-data`", "decisions.md #951 entry")
anchor(PROMPTS_TEXT, "in the burrito-data folder", str(PROMPTS_PATH.relative_to(REPO)))

print("== #952's decisions.md entry decides whether the folder name changes slide 17 ==")
ok, why = verdict(DECISIONS, PROMPTS_TEXT)
check("the slide-17 verdict is recorded and holds", ok, why)
print(f"        {why}")


def mutated(old: str, new: str, text: str = DECISIONS, where: str = "decisions.md") -> str:
    anchor(text, old, where)
    return text.replace(old, new, 1)


def fails(name: str, decisions: str, prompts_text: str = PROMPTS_TEXT) -> None:
    ok_, why_ = verdict(decisions, prompts_text)
    check(name, not ok_, f"the verdict still held: {why_}")


print("== the check fails when the criterion stops holding ==")
fails("with the #952 heading struck, the entry is not found",
      mutated(HEAD_952, "## 2026-11-06 · #000 · struck"))
fails("with the slide-17 paragraph removed, no verdict is recorded",
      DECISIONS.replace(PARA, "", 1))
fails("with the slide-17 paragraph doubled, the verdict is ambiguous",
      DECISIONS.replace(PARA, PARA + "\n\n" + PARA, 1))
fails("with the label stating no verdict, it is not decided",
      mutated(f"{SLIDE_LABEL} is unchanged", f"{SLIDE_LABEL} was looked at"))
fails("with the label stating both verdicts, it is not decided",
      mutated(UNCHANGED, f"{UNCHANGED}; {CHANGES}"))
changed_no_link = DECISIONS.replace(PARA, f"**{CHANGES}, so an agent-task issue.** The deck shows the folder.", 1)
fails("with slide 17 changing and no rounds-agenticburn issue linked, it fails", changed_no_link)
fails("with slide 17 changing and only another repo's issue linked, it fails",
      DECISIONS.replace(PARA, f"**{CHANGES}.** Filed https://github.com/peopleforrester/other/issues/12.", 1))
fails("with the unchanged verdict not saying no issue is filed, it fails",
      DECISIONS.replace(PARA, mutated(NO_ISSUE, "an issue may follow", PARA, "slide-17 paragraph"), 1))
fails("with the unchanged verdict naming a folder #951 did not choose, it fails",
      mutated("#951 chose is `burrito-data`", "#951 chose is `kitchen-files`"))
fails("with #951's entry recording another folder, it fails",
      DECISIONS.replace(dec_entry(DECISIONS, HEAD_951),
                        dec_entry(DECISIONS, HEAD_951).replace("folder `burrito-data`", "folder `kitchen-files`"), 1))
fails("with the c3-attack prompt sending another folder, it fails",
      DECISIONS, mutated("in the burrito-data folder", "in the kitchen-files folder", PROMPTS_TEXT, PROMPTS_PATH.name))

print("== a 'changes' verdict with its issue linked passes, in both link forms ==")
for link in ("https://github.com/peopleforrester/rounds-agenticburn/issues/123", "peopleforrester/rounds-agenticburn#123"):
    ok_, why_ = verdict(DECISIONS.replace(PARA, f"**{CHANGES}, so an agent-task issue.** Filed as {link}.", 1),
                        PROMPTS_TEXT)
    check(f"slide 17 changing with {link} recorded holds", ok_, why_)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("All #952 slide-17 decision checks passed.")
