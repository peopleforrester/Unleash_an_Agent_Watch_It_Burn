# ABOUTME: Holds the run-of-show, /kubecon and the fallback kit's README and prompts to the guardrails-<name>-on/off
# ABOUTME: switch names (#1352): no old name (#1350's aliases) outside the dated records and alias notes listed here.
"""The presenter-facing pages name each stage switch by its guardrails-<name>-on/off name (#1352).

#1350 renamed every stage switch on the private terminal to guardrails-<name>-on/off and kept each old name
(guardrails-on, guards-off, guard-mcp-on and the rest) as an alias until #1363 removes them. #1352 moved the pages the
presenters read onto the new names: `facilitation/kubecon-na-2026-run-of-show.md` (rehearsal and Night Before steps
included), `gitops/ai-layer/web/kubecon.html`, and the fallback kit's `README.md` and `prompts.yaml`. Text that records
what happened under an old name keeps it, as does the one note on each page that says the old names are aliases.

This test reads the old names from the terminal's own ALIASES table in
`gitops/ai-layer/web-terminal/entrypoint.sh`, so a name #1350 kept as an alias is one this test refuses, and cuts out of
each file only the spans listed in KEPT below, each found by its literal first and named when it is gone ("Tests own
their inputs"). What is left must name no old switch. Each check is also run on a copy with an old name put back
outside the kept spans, so a scan that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TERMINAL = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"

# Each file, with the spans that keep an old name on purpose: (start literal, end literal, why). A span runs from its
# start literal to the end of its end literal, and each literal must be in the file once.
KEPT: dict[str, list[tuple[str, str, str]]] = {
    "facilitation/kubecon-na-2026-run-of-show.md": [
        ("### Probe record\n", "\n## The one platform, and the two clusters on it",
         "the dated probe runs, each recorded with the switch names it typed then"),
        ("The names the terminal had before #1350 (", "leaves the on-topic guard as it is.",
         "the note that the old names still answer as aliases"),
        ("on 2026-11-08 LLM Guard scored such a\n  ticket clean", "alone (#1102,\n  question 1120).",
         "what the admin bot did on 2026-11-08, under the name typed then"),
        ("  - On 2026-11-09 (run 19175) it ended RED", "full pass, GREEN, is owed until the guard-proxy pin carries",
         "run 19175's stage-switch result, under the names it ran"),
    ],
    "gitops/ai-layer/web/kubecon.html": [
        ("The old names (<code>guardrails-on</code>,", "still run their new ones through 2026-11-12.",
         "the footer's note that the old names still answer as aliases"),
    ],
    "facilitation/kubecon-na-2026/fallback/README.md": [
        ("Two planned shots are not in it.", "that rehearsal's recording left this repo with M4.",
         "the two shots planned for the first full rehearsal, named as they were then"),
    ],
    "facilitation/kubecon-na-2026/fallback/prompts.yaml": [],
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


term = TERMINAL.read_text(encoding="utf-8")
if "<<'ALIASES'\n" not in term or "\nALIASES\n" not in term:
    sys.exit(f"ANCHOR MISSING: the <<'ALIASES' table of old switch names in {TERMINAL.relative_to(REPO)}")
ALIASES = dict(ln.split() for ln in term.split("<<'ALIASES'\n", 1)[1].split("\nALIASES\n", 1)[0].splitlines())

print("== the old names are the terminal's aliases, each of a guardrails-<name> switch ==")
check(f"the ALIASES table holds the 21 old names #1350 kept ({len(ALIASES)})", len(ALIASES) == 21)
check("each alias runs a guardrails-<name> switch the terminal writes",
      all(n.startswith("guardrails-") and f'cat > "$HOME/{n}" <<' in term for n in ALIASES.values()),
      str({o: n for o, n in ALIASES.items() if f'cat > "$HOME/{n}" <<' not in term}))

# An old name as a word of its own: not inside a longer name (guardrails-on-x, guard-proxy). guard-*-on is the
# run-of-show's old shorthand for "the segment's switch".
OLD = re.compile(r"(?<![\w-])(" + "|".join(re.escape(o) for o in sorted(ALIASES, key=len, reverse=True))
                 + r"|guard-\*-on|guard-\*-off)(?![\w-])")


def cut(text: str, path: str) -> str:
    """The file's text with each KEPT span cut out; exits naming the literal and the file when one is not there once."""
    for start, end, why in KEPT[path]:
        for lit in (start, end):
            if text.count(lit) != 1:
                sys.exit(f"ANCHOR MISSING: {lit!r} ({why}) is in {path} {text.count(lit)} times, not once")
        a = text.index(start)
        b = text.index(end, a) + len(end) if end in text[a:] else -1
        if b < 0:
            sys.exit(f"ANCHOR ORDER: {end!r} does not follow {start!r} in {path}")
        text = text[:a] + text[b:]
    return text


def old_names(text: str) -> list[str]:
    """Each old switch name in the text, with its line, in order."""
    return [f"{text.count(chr(10), 0, m.start()) + 1}: {m.group(1)}" for m in OLD.finditer(text)]


print("== each presenter page names only guardrails-<name>-on/off switches outside its kept spans ==")
for path in KEPT:
    text = (REPO / path).read_text(encoding="utf-8")
    rest = cut(text, path)
    found = old_names(rest)
    check(f"{path} names no old switch outside its {len(KEPT[path])} kept span(s)", not found,
          "; ".join(found[:12]) + " (line numbers in the file with the kept spans cut out)")
    check(f"{path} names the new switches", "guardrails-" in rest and re.search(r"guardrails-[a-z0-9]+-o(n|ff)", rest))
    # The scan catches an old name put back outside the kept spans.
    check(f"{path}: an old name put back outside the kept spans is caught",
          bool(old_names(cut(text + "\nrun `guards-off` again\n", path))))

print("== the switches the stage types read in the run-of-show's table of switches ==")
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
table = ros.split("| Switch | What it turns on or off | On stage |", 1)
if len(table) != 2:
    sys.exit("ANCHOR MISSING: the table of switches ('| Switch | What it turns on or off | On stage |') in the run-of-show")
rows = table[1].split("\n\n", 1)[0]
for name in sorted({n.rsplit("-", 1)[0] for n in ALIASES.values() if n.endswith("-on")} - {"guardrails-rbac",
                                                                                        "guardrails-admission"}):
    check(f"the table lists {name}-on / -off", f"`{name}-on` / `-off`" in rows)
check("the table lists guardrails-all-on / -off and guardrails-status",
      "`guardrails-all-on` / `-off`" in rows and "`guardrails-status`" in rows)
check("the run-of-show says guards-off is now guardrails-ai-off and leaves the on-topic guard",
      "`guards-off` is now `guardrails-ai-off` and leaves the on-topic guard as it is" in re.sub(r"\s+", " ", ros))

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL PRESENTER SWITCH-NAME CHECKS PASS")
