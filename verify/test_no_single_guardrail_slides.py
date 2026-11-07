# ABOUTME: Searches facilitation/, gitops/ai-layer/web/, challenges/ and verify/ for slide citations and fails on any
# ABOUTME: that still cites live slides 29 to 32 as the 2026-11-06 deck's four single guardrail slides (#1097, #1125).
"""No file the presenters or the tests read cites slides 29 to 32 as single guardrail slides (#1125).

The 2026-11-06 deck closed segment 3 on the switch (slide 28) and four single guardrail slides, one per guardrail,
on live slides 29 to 32: RBAC on 29, the admission policy (Kyverno) on 30, runtime security (KubeArmor) on 31 and the
egress NetworkPolicy on 32. The 2026-11-07 deck (rounds-agenticburn#77) keeps slide 28, makes slide 29 the room's
retry, "Try your attacks again.", and gives each guardrail a set: RBAC 30 to 33, Kyverno 34 to 36, KubeArmor 37 to 39,
NetworkPolicy 40 to 42. #1097 swept the citations by hand with a grep; this test runs that search every time.

It reads every file under the four directories (dot directories and `__pycache__` aside, and this file, which
plants the old citations to show each rule fails) and finds each slide citation: "slide" or "slides" followed by a
number, a range ("29 to 32", "29-32", "29 through 32") or a list ("29, 30, 31 and 32"). Then:

  1. No citation cites exactly slides 29 to 32, the four single guardrail slides as a block.
  2. No citation of slides only from 29 to 32 is bound to a guardrail the live deck does not show there. Slide 29 is
     the retry and shows none; slides 30 to 32 are RBAC's, so RBAC is the one guardrail they may name. A guardrail
     is bound to the citation when it is named in the same sentence after the number, before the next citation, or
     just before the word "slide" ("Kyverno (slide 30)"). The names: RBAC; Kyverno or admission; KubeArmor or
     runtime security; NetworkPolicy, network policy or egress.
  3. In facilitation/, gitops/ai-layer/web/ and challenges/, no text calls the close "one slide per guardrail",
     "four slides", "four guardrail slides" or "single guardrail slides". verify/ is held to rules 1 and 2 alone:
     there these words are the stale text other tests plant to prove their own checks fail, not a citation.

A sentence that names the 2026-11-06 deck is the history of the change, as the run-of-show's Timing paragraph keeps
it (#1095), not a citation of the live deck, and no rule reads it.

Before reading the result, the test checks that the search sees the live citations it should (slide 29's retry and
slides 30 to 42 in the run-of-show and on /kubecon), so a moved file or a broken pattern reads as that. Then each rule
is run on copies of the real files with an old citation planted, and the live deck's own forms are run through it,
so a rule that could never fail, or one that flags the live deck, shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SELF = pathlib.Path(__file__).resolve()
DIRS = ("facilitation", "gitops/ai-layer/web", "challenges", "verify")
PROSE_DIRS = ("facilitation", "gitops/ai-layer/web", "challenges")
ROS = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
KUBECON = REPO / "gitops/ai-layer/web/kubecon.html"
OLD_SLIDES = frozenset(range(29, 33))
# What the 2026-11-07 deck shows on each of the old four: 29 the retry, 30 to 32 RBAC's set.
LIVE_GUARDRAIL = {29: frozenset(), 30: frozenset({"RBAC"}), 31: frozenset({"RBAC"}), 32: frozenset({"RBAC"})}
HISTORY = "2026-11-06"

GUARDRAILS = (
    ("RBAC", re.compile(r"\bRBAC\b", re.I)),
    ("the admission policy", re.compile(r"\bKyverno\b|\badmission\b", re.I)),
    ("runtime security", re.compile(r"\bKubeArmor\b|\bruntime\s+security\b", re.I)),
    ("NetworkPolicy", re.compile(r"\bNetwork\s*Polic(?:y|ies)\b|\begress\b", re.I)),
)
CITE = re.compile(r"\bslides?\b(?:\s|&nbsp;)*(?:#|no\.)?\s*(\d+(?:\s*(?:,|and|to|through|-|–|—)\s*\d+)*)",
                  re.I)
RANGE_SEPS = ("to", "through", "-", "–", "—")
STALE_PHRASES = re.compile(
    r"\b(?:one|a)\s+slide\s+(?:per|for\s+each)\s+guardrail\b"
    r"|\bfour\s+(?:single\s+)?(?:guardrail\s+)?slides\b"
    r"|\bsingle[\s-]+guardrail\s+slides?\b", re.I)
# A sentence ends at . ; ! or ? before a space, a quote, a bracket, markup or the end; at a table cell; at the
# page's middle-dot separator; or at a blank line.
BOUNDARY = re.compile(r"[.;!?](?=[\s\"'”)\]<*`|]|$)|\||·|\n[ \t]*\n")
BACK_REACH, FORWARD_REACH = 60, 160

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"\n{detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def slides_of(spec: str) -> frozenset[int]:
    nums: set[int] = set()
    prev = None
    for sep, n in re.findall(r"(,|and|to|through|-|–|—)?\s*(\d+)", spec, re.I):
        n = int(n)
        if prev is not None and sep.lower() in RANGE_SEPS and prev < n <= prev + 100:
            nums.update(range(prev + 1, n + 1))
        nums.add(n)
        prev = n
    return frozenset(nums)


def sentence(text: str, bounds: list[int], start: int, end: int) -> str:
    lo = max([b for b in bounds if b < start], default=-1) + 1
    hi = min([b for b in bounds if b >= end], default=len(text))
    return text[lo:hi]


def findings(rel: str, text: str) -> list[str]:
    """Each citation of the old single guardrail slides in one file, as 'path:line: why: the text'."""
    out: list[str] = []
    bounds = [m.start() for m in BOUNDARY.finditer(text)]
    cites = list(CITE.finditer(text))

    def where(pos: int) -> str:
        return f"{rel}:{text.count(chr(10), 0, pos) + 1}"

    for i, m in enumerate(cites):
        s, e = m.start(), m.end()
        if HISTORY in sentence(text, bounds, s, e):
            continue
        nums = slides_of(m.group(1))
        quoted = " ".join(m.group(0).split())
        if nums == OLD_SLIDES:
            out.append(f"{where(s)}: cites slides 29 to 32, the four single guardrail slides: {quoted!r}")
            continue
        if not nums or not nums <= OLD_SLIDES:
            continue
        prev_end = cites[i - 1].end() if i else 0
        next_start = cites[i + 1].start() if i + 1 < len(cites) else len(text)
        back = max([b + 1 for b in bounds if b < s] + [prev_end, s - BACK_REACH, 0])
        fwd = min([b for b in bounds if b >= e] + [next_start, e + FORWARD_REACH, len(text)])
        window = text[back:s] + " " + text[e:fwd]
        allowed = frozenset.intersection(*(LIVE_GUARDRAIL[n] for n in nums))
        named = [g for g, rx in GUARDRAILS if rx.search(window) and g not in allowed]
        if named:
            ctx = " ".join(text[back:fwd].split())
            out.append(f"{where(s)}: cites {quoted!r} as the {' and '.join(named)} slide, which the live deck "
                       f"does not show there: {ctx!r}")
    if rel.startswith(PROSE_DIRS):
        for m in STALE_PHRASES.finditer(text):
            if HISTORY in sentence(text, bounds, m.start(), m.end()):
                continue
            out.append(f"{where(m.start())}: calls the close {' '.join(m.group(0).split())!r}, the 2026-11-06 deck's "
                       f"four single guardrail slides")
    return out


def files(directory: str) -> list[pathlib.Path]:
    root = REPO / directory
    if not root.is_dir():
        sys.exit(f"ANCHOR MISSING: {root} is not a directory; the slide-citation search reads it")
    found = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(REPO).parts
        if not p.is_file() or p.resolve() == SELF:
            continue
        if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in rel):
            continue
        found.append(p)
    if not found:
        sys.exit(f"ANCHOR MISSING: {root} holds no files; the slide-citation search reads it")
    return found


def read(p: pathlib.Path) -> str:
    return p.read_bytes().decode("utf-8", errors="replace")


def rel_of(p: pathlib.Path) -> str:
    return p.relative_to(REPO).as_posix()


def main() -> None:
    # The search sees the live citations it should, so a moved file or a broken pattern does not pass as clean.
    for path, live in ((ROS, ("slide 29's retry", "slides 30 to 42")),
                       (KUBECON, ('slide 29, "Try your attacks again."', "slides 30 to 42"))):
        if not path.is_file():
            sys.exit(f"ANCHOR MISSING: {path} is gone; the search is checked against its live slide citations")
        text = read(path)
        flat = " ".join(text.split())
        for literal in live:
            if literal not in flat:
                sys.exit(f"ANCHOR MISSING: {literal!r} is not in {path}; the search is checked against it")
        got = [slides_of(m.group(1)) for m in CITE.finditer(text)]
        check(f"the search finds {rel_of(path)}'s citations of slide 29 and slides 30 to 42",
              frozenset({29}) in got and frozenset(range(30, 43)) in got)

    print("== the search over the four directories ==")
    for d in DIRS:
        found: list[str] = []
        listed = files(d)
        for p in listed:
            found += findings(rel_of(p), read(p))
        check(f"no file in {d}/ ({len(listed)} read) cites live slides 29 to 32 as single guardrail slides",
              not found, "\n".join("  " + f for f in found))

    print("== each rule fails on an old citation, and passes the live deck's own ==")
    ros, page = read(ROS), read(KUBECON)
    planted = [
        ("slides 29 to 32", "Then one set of slides 29 to 32 closes the segment."),
        ("slides 29-32", "The guardrails are on slides 29-32."),
        ("slides 29–32", "The guardrails are on slides 29–32."),
        ("slides 29 through 32", "Read slides 29 through 32 aloud."),
        ("slides 29, 30, 31 and 32", "Each of slides 29, 30, 31 and 32 names one."),
        ("slide 29 as RBAC", "Slide 29: RBAC, the Role on one Secret."),
        ("slide 29 as the egress policy", "Slide 29 shows the egress allowlist."),
        ("slide 30 as Kyverno", "Slide 30 is the admission policy (Kyverno)."),
        ("Kyverno before slide 30", "Then Kyverno (slide 30) denies the image."),
        ("slide 31 as KubeArmor", "On slide 31, KubeArmor blocks the recipe read."),
        ("slide 31 as runtime security", "Runtime security, slide 31, blocks the read."),
        ("slide 32 as NetworkPolicy", "Slide 32 shows the NetworkPolicy."),
        ("slides 30 and 31 as the admission policy and KubeArmor", "Slides 30 and 31: Kyverno, then KubeArmor."),
    ]
    for label, sentence_text in planted:
        for rel, base in (("facilitation/kubecon-na-2026-run-of-show.md", ros),
                          ("gitops/ai-layer/web/kubecon.html", page),
                          ("verify/test_seg3_timing.py", "# " + sentence_text + "\n")):
            check(f"{label} planted in {rel} fails", len(findings(rel, base + "\n\n" + sentence_text + "\n"))
                  > len(findings(rel, base)))
    for label, phrase in (("one slide per guardrail", "Then one slide per guardrail."),
                          ("its four slides", "Then the switch and its four slides."),
                          ("four guardrail slides", "The four guardrail slides follow."),
                          ("single guardrail slides", "Each single-guardrail slide is named.")):
        for rel, base in (("facilitation/kubecon-na-2026-run-of-show.md", ros),
                          ("gitops/ai-layer/web/kubecon.html", page),
                          ("challenges/LAB-TEXT.md", "")):
            check(f"{label!r} planted in {rel} fails", len(findings(rel, base + "\n\n" + phrase + "\n"))
                  > len(findings(rel, base)))
        check(f"{label!r} in verify/, another test's stale text, is not read",
              not findings("verify/test_seg3_timing.py", f"STALE = {phrase!r}\n"))

    history = "The 2026-11-06 deck closed on four single guardrail slides, slides 29 to 32, RBAC on slide 29."
    check("a sentence naming the 2026-11-06 deck is history and passes",
          not findings("facilitation/kubecon-na-2026-run-of-show.md", history))
    check("the same sentence without the date fails",
          len(findings("facilitation/kubecon-na-2026-run-of-show.md", history.replace("The 2026-11-06 deck", "The deck"))) == 3)

    live = [
        "**RBAC, slides 30 to 33.** Slide 30 recalls the Challenge 1 attack.",
        'Slide 31 adds "This attack was prevented with RBAC."',
        "Slide 32 shows BurritoBot's overprivileged Role rule; slide 33 sets it beside the scoped one.",
        "Slide 32's rule is the RBAC Role guardrails-off leaves.",
        "the egress NetworkPolicy on both clusters. Then slide 29, \"Try your attacks again.\": the room retries.",
        "then the room's retry (slide 29). Kyverno, slides 34 to 36, then KubeArmor, slides 37 to 39.",
        "32 words on slide 28 and 29 on slide 29, then 317 across slides 30 to 42.",
        "one set per guardrail on slides 30 to 42 (RBAC 30 to 33, Kyverno 34 to 36, NetworkPolicy 40 to 42)",
        "<b>NetworkPolicy</b>, slides 40 to 42: the beacon.",
    ]
    for text in live:
        got = findings("facilitation/kubecon-na-2026-run-of-show.md", text)
        check(f"the live deck's {text[:48]!r}... passes", not got, "\n".join("  " + f for f in got))

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nNO SINGLE GUARDRAIL SLIDE CITATIONS GREEN")


if __name__ == "__main__":
    main()
