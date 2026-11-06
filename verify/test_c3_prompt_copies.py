# ABOUTME: Holds every copy of the Challenge 3 recipe prompt to /kubecon's C3 beat (#973, for #952): the prompt catalog,
# ABOUTME: the /lab sheet and its LAB-TEXT.md export, and the fallback prompts.yaml each carry the same recon and attack.
"""No cluster and no network: this reads repo files only.

#952 replaced the old C3 ask, a `grep -ri -A3 recipe /tmp/burrito-data` no attendee could guess, with #925's two
conversational prompts: recon (what folders can you see) and, after a reset, the attack (read me the copy in the
burrito-data folder). /kubecon's C3 beat is where the presenters copy them from, so it is the reference here. Every
other copy that held the C3 recipe prompt must carry the same two prompts, recon first, word for word:

- challenges/PROMPT-CATALOG.md, the C3 section's quoted prompts;
- gitops/ai-layer/web/lab.html, the C3 "Stuck? Try this prompt" box;
- challenges/LAB-TEXT.md, the same box in the generated export of lab.html;
- facilitation/kubecon-na-2026/fallback/prompts.yaml, the c3- entries.

test_replay_prompts.py holds prompts.yaml equal to the whole /kubecon page, and test_lab_text_export.py holds
LAB-TEXT.md equal to what the exporter renders from lab.html; neither reads the C3 prompts themselves, so a copy that
kept the old grep, or that dropped or reordered recon, passed both. Each extractor is also run on a copy broken the
way a regression would break it (the old grep put back, recon dropped, the order swapped), and must catch it.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
KUBECON = REPO / "gitops/ai-layer/web/kubecon.html"
CATALOG = REPO / "challenges/PROMPT-CATALOG.md"
LAB_HTML = REPO / "gitops/ai-layer/web/lab.html"
LAB_TEXT = REPO / "challenges/LAB-TEXT.md"
PROMPTS_YAML = REPO / "facilitation/kubecon-na-2026/fallback/prompts.yaml"

OLD_GREP = "grep -ri -A3 recipe /tmp/burrito-data"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def between(text: str, start: str, end: str, path: pathlib.Path) -> str:
    """The text from the anchor `start` up to the next `end`; exits naming the anchor and file when it is gone."""
    if start not in text:
        print(f"FAILED: {path.relative_to(REPO)} no longer holds the anchor {start!r}: it was renamed or removed")
        sys.exit(1)
    body = text.split(start, 1)[1]
    return body.split(end, 1)[0] if end in body else body


# --- extractors: each takes the file's text and returns the C3 prompts it carries, in order ---------------------------

def kubecon_c3(text: str) -> list[str]:
    beat = between(text, '<article class="beat" data-beat="C3"', "</article>", KUBECON)
    return [squash(html.unescape(p)) for p in re.findall(r'<div class="prompt"[^>]*>(.*?)<button', beat, re.S)]


def catalog_c3(text: str) -> list[str]:
    """Every quoted (`> `) paragraph of the C3 section, each paragraph's lines joined."""
    section = between(text, "\n## C3:", "\n## ", CATALOG)
    quotes, cur = [], []
    for line in section.splitlines():
        if line.startswith(">"):
            cur.append(line[1:].strip())
        elif cur:
            quotes.append(squash(" ".join(cur)))
            cur = []
    if cur:
        quotes.append(squash(" ".join(cur)))
    return quotes


def lab_html_c3(text: str) -> list[str]:
    step = between(text, '<div class="step c3">', '<div class="step ', LAB_HTML)
    box = between(step, "<summary>Stuck? Try this prompt</summary>", "</details>", LAB_HTML)
    return [squash(html.unescape(p)) for p in re.findall(r'<div class="cmd[^"]*"[^>]*>(.*?)<button', box, re.S)]


def lab_text_c3(text: str) -> list[str]:
    section = between(text, "\n## Challenge 3:", "\n## ", LAB_TEXT)
    box = between(section, "**▸ Stuck? Try this prompt**", "\n**", LAB_TEXT)
    plain = "\n".join(line[1:].lstrip() if line.startswith(">") else line for line in box.splitlines())
    return [squash(block) for block in re.findall(r"```[^\n]*\n(.*?)```", plain, re.S)]


def prompts_yaml_c3(text: str) -> list[tuple[str, str]]:
    doc = yaml.safe_load(text)
    entries = doc["prompts"] if isinstance(doc, dict) else doc
    return [(e["id"], squash(e["prompt"])) for e in entries if str(e.get("id", "")).startswith("c3-")]


# --- the reference: /kubecon's C3 beat --------------------------------------------------------------------------------
print("the reference: /kubecon's C3 beat")
ref = kubecon_c3(KUBECON.read_text(encoding="utf-8"))
check("/kubecon's C3 beat carries exactly two prompts, recon then attack", len(ref) == 2, f"{len(ref)} prompts")
if len(ref) != 2:
    print(f"FAILED: {KUBECON.relative_to(REPO)}'s C3 beat holds {len(ref)} prompts, not the two #952 put there")
    sys.exit(1)
RECON, ATTACK = ref
check("the first is the recon: it asks what folders the bot can see",
      "What folders do you have access to in your file system?" in RECON, RECON)
check("the second is the attack: it names the burrito-data folder and asks for the copy to be read",
      "burrito-data folder" in ATTACK and "read it to me" in ATTACK, ATTACK)
check("neither is the old grep ask", OLD_GREP not in RECON and OLD_GREP not in ATTACK)
WANT = [RECON, ATTACK]


def same(name: str, got: list[str]) -> None:
    check(f"{name} carries the recon and attack prompts, recon first, word for word", got == WANT,
          f"got {got!r}")


# --- each copy --------------------------------------------------------------------------------------------------------
print("\nchallenges/PROMPT-CATALOG.md, the C3 section")
catalog = CATALOG.read_text(encoding="utf-8")
same("the catalog's C3 quoted prompts", catalog_c3(catalog))

print("\ngitops/ai-layer/web/lab.html, the C3 Stuck box")
lab_html = LAB_HTML.read_text(encoding="utf-8")
same("lab.html's C3 Stuck box", lab_html_c3(lab_html))

print("\nchallenges/LAB-TEXT.md, the C3 Stuck box")
lab_text = LAB_TEXT.read_text(encoding="utf-8")
same("LAB-TEXT.md's C3 Stuck box", lab_text_c3(lab_text))

print("\nfacilitation/kubecon-na-2026/fallback/prompts.yaml, the c3- entries")
fallback_text = PROMPTS_YAML.read_text(encoding="utf-8")
c3 = prompts_yaml_c3(fallback_text)
check("the c3- entries are c3-recon then c3-attack, and nothing else", [i for i, _ in c3] == ["c3-recon", "c3-attack"],
      f"got {[i for i, _ in c3]!r}")
same("prompts.yaml's c3- entries", [p for _, p in c3])
check("no fallback prompt still carries the old grep ask",
      not any(OLD_GREP in squash(str(e.get("prompt", ""))) for e in (yaml.safe_load(fallback_text) or {}).get("prompts", [])))


# --- the checks catch a broken copy ------------------------------------------------------------------------------------
print("\nthe checks catch a copy that stopped carrying the prompts")
GREP_ASK = f"Run {OLD_GREP} and read me what it finds."


def swap(text: str, old: str, new: str, path: pathlib.Path) -> str:
    if old not in text:
        print(f"FAILED: the mutation anchor {old[:60]!r}... is not in {path.relative_to(REPO)}")
        sys.exit(1)
    return text.replace(old, new, 1)


def catalog_quote(text: str, k: int, new: str | None) -> str:
    """The catalog with the C3 section's k-th quoted paragraph replaced by `new` (or dropped, when None)."""
    start = text.index("\n## C3:")
    end = text.find("\n## ", start + 1)
    end = len(text) if end < 0 else end
    section = text[start:end]
    quotes = list(re.finditer(r"(?m)^>.*(?:\n>.*)*", section))
    if len(quotes) <= k:
        print(f"FAILED: {CATALOG.relative_to(REPO)}'s C3 section has {len(quotes)} quoted paragraphs, none at {k}")
        sys.exit(1)
    q = quotes[k]
    section = section[:q.start()] + ("" if new is None else "> " + new) + section[q.end():]
    return text[:start] + section + text[end:]


cases = [
    ("the catalog with the old grep in place of the attack", catalog_c3, catalog_quote(catalog, 1, GREP_ASK)),
    ("the catalog with the recon quote dropped", catalog_c3, catalog_quote(catalog, 0, None)),
    ("the catalog with the old grep quoted after both prompts", catalog_c3,
     catalog_quote(catalog, 1, ATTACK + "\n\n> " + GREP_ASK)),
    ("lab.html with recon and attack swapped", lab_html_c3,
     swap(swap(lab_html, RECON, "\0", LAB_HTML), ATTACK, RECON, LAB_HTML).replace("\0", ATTACK)),
    ("lab.html with the old grep in place of recon", lab_html_c3, swap(lab_html, RECON, GREP_ASK, LAB_HTML)),
    ("LAB-TEXT.md with the attack dropped", lab_text_c3, swap(lab_text, f"```\n> {ATTACK}\n> ```", "", LAB_TEXT)),
    ("LAB-TEXT.md with the old grep in place of the attack", lab_text_c3, swap(lab_text, ATTACK, GREP_ASK, LAB_TEXT)),
]
for name, extract, broken in cases:
    check(f"caught: {name}", extract(broken) != WANT, f"still read {extract(broken)!r}")

broken_yaml = swap(fallback_text, "  - id: c3-recon\n", "  - id: c3-recipe-grep\n", PROMPTS_YAML)
broken_yaml = swap(broken_yaml, RECON, GREP_ASK, PROMPTS_YAML)
got = prompts_yaml_c3(broken_yaml)
check("caught: prompts.yaml with the old c3-recipe-grep entry back in place of c3-recon",
      [i for i, _ in got] != ["c3-recon", "c3-attack"] and [p for _, p in got] != WANT, f"still read {got!r}")


print()
if failures:
    print(f"FAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("ALL C3 PROMPT COPY CHECKS GREEN")
