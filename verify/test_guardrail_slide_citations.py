# ABOUTME: Searches facilitation/, gitops/ai-layer/web/, challenges/ and verify/ for "slide"/"slides" and fails on any
# ABOUTME: citation of live slides 29 to 32 as single guardrail slides, the 2026-11-06 deck's close (#1097, #1125).
"""No file in the four directories cites live slides 29 to 32 as single guardrail slides (#1125, from #1097).

The 2026-11-06 deck closed segment 3 on slide 28's switch and four single guardrail slides, live 29 to 32, one per
guardrail. The 2026-11-07 deck (rounds-agenticburn#77) replaced them: slide 29 is the room's retry, "Try your attacks
again.", and slides 30 to 42 are one set per guardrail (RBAC 30 to 33, Kyverno 34 to 36, KubeArmor 37 to 39,
NetworkPolicy 40 to 42). #1097 swept the citations by hand with `grep -rniE "slides? *[0-9]"`; this test runs that
search on every file git tracks or would track (`git ls-files --cached --others --exclude-standard`) under
`facilitation/`, `gitops/ai-layer/web/`, `challenges/` and `verify/`, and fails on any of:

  range      "slides 29 to 32" (or 29-32, 29 through 32), or 29 to 32 within 40 characters after "slide"
  per-slide  "one slide per guardrail" (or "for each" / "each")
  four       "four slides", "four guardrail slides", "four single guardrail slides"
  guardrail  "guardrail slide(s)", the old deck's name for the four
  numbered   "slide N", N one of 29 to 32 and not the start of a range, with a guardrail named in its own clause after
             it (up to the first . ; : quote or bracket, at most 60 characters) or just before it ("KubeArmor (slide
             31)"), where the 2026-11-07 deck does not put that guardrail: slide 29 carries none, 30 to 32 are RBAC's

Text is read with HTML tags, `*` and backticks blanked, whitespace flattened and case folded, so a citation wrapped
across lines or bolded is still found. A hit passes only where ALLOWED names its file and a stretch of text that
contains it, with why it is not a citation of the current deck: the run-of-show's dated history of the change, and the
stale wording other tests swap in to show their checks fail. Each ALLOWED entry must still be found in its file, so
the list cannot outlive the text it excuses. A block-level HTML tag reads as a sentence break. This test's own
docstring, comments and ALLOWED stretches necessarily name the forms it bans, so it is the one file the search leaves
out; its fixtures are built from pieces (`S` is "slide") all the same.

The self-checks run each rule on the pre-#1095 run-of-show and pre-#1096 /kubecon wording quoted from git history and on
synthetic numbered citations, show the current deck's wording passes, show a hit planted in a real file is found on
its line, and show a stale ALLOWED entry and an uncovered hit both fail.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DIRS = ("facilitation", "gitops/ai-layer/web", "challenges", "verify")
S = "slide"

GUARDS = {
    "rbac": r"rbac|\brole\b",
    "admission": r"kyverno|admission|deny-external-registries|restrict-image-registries",
    "runtime": r"kubearmor|runtime|block-recipe-snoop",
    "network": r"networkpolic|network polic|egress|agent-egress-allowlist",
}
GUARD_RE = re.compile("|".join(f"(?P<{k}>{v})" for k, v in GUARDS.items()))
# The 2026-11-07 deck: which guardrail each of live 29 to 32 shows. Slide 29 is the retry and shows none.
DECK = {29: set(), 30: {"rbac"}, 31: {"rbac"}, 32: {"rbac"}}

RANGE_TO = r"\s*(?:to|through|-|–|—)\s*"
PHRASES = [
    ("range", re.compile(rf"\bslides?\b[^.;¶]{{0,40}}?\b29{RANGE_TO}32\b")),
    ("per-slide", re.compile(r"\bone\s+slide\s+(?:per|for\s+each|each)\s+guardrail")),
    ("four", re.compile(r"\bfour\s+(?:single\s+)?(?:kubernetes\s+)?(?:guardrail\s+)?slides\b")),
    ("guardrail", re.compile(r"\bguardrail\s+slides?\b")),
]
NUMBERED = re.compile(rf"\bslides?\s+(29|30|31|32)\b(?!(?:'s)?{RANGE_TO}\d|\s+and\s+\d)")
# A block-level tag ends a sentence, so a heading's last word is not read into the next element's first.
BREAK = "¶"
BLOCK_TAG = re.compile(r"</?(?:h[1-6]|div|p|li|ul|ol|tr|td|th|table|article|section|details|summary|br|pre)\b", re.I)
CLAUSE_END = re.compile(rf"[.;:\"“”()\[\]!?{BREAK}]")
BEFORE = re.compile(rf"(?:{'|'.join(GUARDS.values())})[\w-]*\W{{0,4}}(?:(?:on|is|at|in)\s+)?$")

# (file, a stretch of its normalized text holding the hit, why it is not a citation of the current deck)
ALLOWED = [
    ("facilitation/kubecon-na-2026-run-of-show.md",
     "on the switch and four single guardrail slides in about a minute. the 2026-11-07 deck replaces those four",
     "the Timing paragraph's dated history: what the 2026-11-06 deck did and that the 2026-11-07 deck replaces it"),
    ("verify/test_progress_entries.py",
     "one set per guardrail on slides 30 to 42 replaces the four single guardrail slides that were live 29 to 32",
     "it pins #1065's PROGRESS.md entry, which records the replacement"),
    ("verify/test_instructor_brief.py",
     "check(\"the run-of-show no longer has one slide per guardrail or the four slides\", \"one slide per guardrail\" "
     "not in \" \".join(ros.split()).lower() and \"its four slides\" not in",
     "the stale wording the check bans"),
    ("verify/test_instructor_brief.py",
     "check(\"the page has no one slide per guardrail, and no old slide 28 title\", \"one slide per guardrail\" not in",
     "the stale wording the check bans"),
    ("verify/test_ros_segments_table_seg3.py",
     "neither says \"one slide per guardrail\" or \"four slides\" any more (the 2026-11-06 deck's \"its four slides\")",
     "the docstring naming the stale wording the test bans"),
    ("verify/test_ros_segments_table_seg3.py",
     "stale = (\"one slide per guardrail\", \"four slides\")",
     "the stale wording the test bans"),
    ("verify/test_ros_segments_table_seg3.py",
     "text.replace(phrase, \"the guardrail slides\")",
     "the filler a self-check swaps in to show a phrase check fails"),
    ("verify/test_ros_segments_table_seg3.py",
     "re.sub(r\"one set per guardrail\", \"its four slides\", text) check(f\"{label} with the 2026-11-06 close's 'its "
     "four slides' fails\", not run(broken)[f\"{label} no longer says 'four slides'\"])",
     "the stale wording a self-check puts back"),
    ("verify/test_seg3_timing.py",
     "names slide 29's retry and the guardrail sets on slides 30 to 42, and no longer the four single guardrail slides.",
     "the docstring naming the stale wording the test bans"),
    ("verify/test_seg3_timing.py",
     "\"four guardrail slides\",",
     "the stale wording a self-check puts back"),
]

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def normalize(text: str) -> tuple[str, list[int]]:
    """Tags, `*` and backticks blanked, whitespace runs to one space, case folded; idx maps each char back."""
    blanked = re.sub(r"<[^>]*>|[*`]", lambda m: (BREAK if BLOCK_TAG.match(m.group(0)) else " ").ljust(len(m.group(0))),
                     text)
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(blanked):
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
            continue
        out.append(ch.lower())
        idx.append(i)
    return "".join(out), idx


def numbered_hits(flat: str):
    for m in NUMBERED.finditer(flat):
        n = int(m.group(1))
        after = flat[m.end():m.end() + 60]
        paren = re.match(r"(?:'s)?\s*\(([^)]*)\)", after)
        if paren:
            clause = paren.group(1)
        else:
            cut = CLAUSE_END.search(after)
            clause = after[:cut.start()] if cut else after
        named = {k for g in GUARD_RE.finditer(clause) for k, v in g.groupdict().items() if v}
        before = BEFORE.search(flat[max(0, m.start() - 40):m.start()])
        if before:
            named |= {k for g in GUARD_RE.finditer(before.group(0)) for k, v in g.groupdict().items() if v}
        wrong = named - DECK[n]
        if wrong:
            yield m.start(), m.end(), f"numbered (slide {n} with {', '.join(sorted(wrong))})"


def hits(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, rule, matched text) in the normalized text."""
    flat, _ = normalize(text)
    found = [(m.start(), m.end(), rule, m.group(0)) for rule, rx in PHRASES for m in rx.finditer(flat)]
    found += [(a, b, rule, flat[a:b]) for a, b, rule in numbered_hits(flat)]
    return sorted(found)


def offences(rel: str, text: str, allowed=ALLOWED) -> list[str]:
    """Each hit no ALLOWED entry for this file covers, as 'file:line: rule: text'."""
    flat, idx = normalize(text)
    spans = []
    for path, ctx, _why in allowed:
        if path != rel:
            continue
        spans += [(m.start(), m.start() + len(ctx)) for m in re.finditer(re.escape(ctx), flat)]
    out = []
    for a, b, rule, got in hits(text):
        if any(s <= a and b <= e for s, e in spans):
            continue
        line = text.count("\n", 0, idx[a]) + 1
        out.append(f"{rel}:{line}: {rule}: {got!r}")
    return out


def stale_allowed(read, allowed=ALLOWED) -> list[str]:
    """ALLOWED entries whose text is no longer in their file."""
    out = []
    for path, ctx, _why in allowed:
        text = read(path)
        if text is None or ctx not in normalize(text)[0]:
            out.append(f"{path}: {ctx[:70]!r}")
    return out


def tree_files() -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                          "--", *DIRS], capture_output=True, check=False)
    if res.returncode != 0:
        sys.exit(f"git ls-files failed in {REPO}: {res.stderr.decode(errors='replace').strip()}")
    return sorted(p for p in set(res.stdout.decode().split("\0")) if p and (REPO / p).is_file())


def read_text(rel: str) -> str | None:
    p = REPO / rel
    if not p.is_file():
        return None
    data = p.read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def fixtures() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(name, stale text) cases each rule must flag, and (name, current text) cases none may flag."""
    gr = "guardrail"
    stale = [
        ("the pre-#1095 run-of-show step 6", f"6. **One {S} per {gr} ({S}s 29 to 32),** each named, not deep."),
        ("the pre-#1095 segments paragraph", f"guardrails switch and its four {S}s (#774). Each challenge keeps"),
        ("the pre-#1096 /kubecon switch beat", f"three asks above are stopped. Then one {S} per {gr}.</div>"),
        ("the pre-#1096 /kubecon story, wrapped",
         f"the room tries Challenges 1 and 2 again and is stopped, and one {S} per\n    {gr} follows."),
        ("a range with a hyphen", f"the guardrails on {S}s 29-32"),
        ("a range after other words", f"the {S}s that were live 29 to 32"),
        ("four guardrail slides", f"then the four {gr} {S}s"),
        ("a guardrail slide", f"the KubeArmor {gr} {S}"),
        ("slide 29 as RBAC", f"{S.capitalize()} 29 (RBAC) shows the Role."),
        ("slide 30 as Kyverno", f"{S} 30, Kyverno admission, prints the deny"),
        ("KubeArmor before slide 31", f"KubeArmor (<b>{S} 31</b>) blocks the read"),
        ("slide 32 as the egress NetworkPolicy", f"on {S} 32 the egress NetworkPolicy"),
        ("slide 29 with its guardrail after a colon-free clause", f"{S} 29 names `deny-external-registries`"),
    ]
    current = [
        ("slide 29's retry", f"{S} 29's retry, \"Try your attacks again.\", and one set per {gr} on {S}s 30 to 42"),
        ("the sets' ranges", f"one set per {gr} on {S}s 30 to 42 (RBAC 30 to 33, Kyverno 34 to 36, KubeArmor 37 to 39"),
        ("slide 31's RBAC line", f"{S.capitalize()} 31 adds \"This attack was prevented with RBAC.\""),
        ("slide 32's Role rule", f"{S.capitalize()} 32 shows BurritoBot's overprivileged Role rule from before"),
        ("the /kubecon marker", f"Then one set per {gr}, {S}s 30 to 42: RBAC, an admission policy (Kyverno)"),
        ("the switch before slide 29",
         f"arms RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy. Then {S} 29, \"Try your attacks"),
        ("RBAC's range", f"**RBAC, {S}s 30 to 33.** {S.capitalize()} 30 recalls the Challenge 1 attack"),
        ("slide 36", f"{S} 36's deny message from Kyverno"),
        ("a heading ending on a guardrail before a slide 28 line",
         f"<h3>the retry, one set per {gr}</h3>\n<div class=\"who\">{S.capitalize()} 28: click its line</div>"),
    ]
    return stale, current


def main() -> None:
    files = tree_files()
    print(f"== the search: {len(files)} files under {', '.join(d + '/' for d in DIRS)} ==")
    for d in DIRS:
        check(f"the search reads files under {d}/", any(f.startswith(d + "/") for f in files))
    me = str(pathlib.Path(__file__).resolve().relative_to(REPO))
    check("this test is the one file the search leaves out, and it is under verify/", me in files)
    texts = {f: t for f in files if (t := read_text(f)) is not None}
    found = [o for f, t in texts.items() if f != me for o in offences(f, t)]
    for o in found:
        print("  " + o)
    check("no file cites live slides 29 to 32 as single guardrail slides", not found)
    stale = stale_allowed(read_text)
    for s in stale:
        print("  ALLOWED entry no longer found: " + s)
    check("every ALLOWED entry is still in its file", not stale)

    print("== each rule can fail ==")
    stale_cases, current_cases = fixtures()
    for name, text in stale_cases:
        check(f"{name} is flagged", bool(hits(text)))
    for name, text in current_cases:
        check(f"{name} passes", not hits(text))
    for rule, _ in PHRASES:
        check(f"the {rule} rule flags one of the stale cases",
              any(r == rule for _, t in stale_cases for _, _, r, _ in hits(t)))
    check("the numbered rule flags one of the stale cases",
          any(r.startswith("numbered") for _, t in stale_cases for _, _, r, _ in hits(t)))

    target = next(f for f in texts if f.startswith("challenges/"))
    base = texts[target]
    planted = base + f"\nThen one {S} per guardrail.\n"
    got = offences(target, planted)
    want_line = planted.count("\n")
    check(f"a citation planted at the end of {target} is found on line {want_line}",
          any(o.startswith(f"{target}:{want_line}: per-slide") for o in got))
    path, ctx, why = ALLOWED[0]
    check("a hit outside every ALLOWED stretch fails", bool(offences(path, texts[path], allowed=[])))
    check("a stale ALLOWED entry fails",
          bool(stale_allowed(read_text, allowed=[(path, ctx + " and then some text no file holds", why)])))
    check("an ALLOWED entry for one file does not cover another",
          bool(offences(target, f"x {ctx} y", allowed=ALLOWED)))

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nNO GUARDRAIL SLIDE CITATION OF LIVE 29 TO 32 GREEN")


if __name__ == "__main__":
    main()
