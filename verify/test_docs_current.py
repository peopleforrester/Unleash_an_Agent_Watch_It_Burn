# ABOUTME: The docs a next session reads must describe the workshop that exists: Community + admin +
# ABOUTME: attendee clusters, eight challenges, get_vault_entry. Historical records are exempt by design.
"""Keeps the current-description docs from drifting back to the retired round model (#327).

The restructure (#290, #291) retired rounds fleet-wide. There is no Round 1/2/3 and no
`watch-it-burn-r<N>-<n>` cluster; the fleet is the Community cluster (`attackme.agenticburn.com`, no
guardrails), two admin clusters (all guardrails on), and the attendee pool where each student installs the
controls themselves. A documentation sweep decays, so this asserts it rather than trusting a one-off pass.

**Historical records are deliberately exempt.** `PROJECT_STATE.md` and `docs/DECISION-LOG.md` are
append-only logs, and lines like "LIVE-VALIDATED 2026-07-06 on watch-it-burn-r2-1" or "Measured 2026-08-30
... cluster watch-it-burn-r3-2" are dated facts. Rewriting them would falsify the record, which is a worse
failure than the staleness this test exists to catch. `docs/RUN-OF-SHOW-2026-08.md` is the August artifact
that still describes the round model on purpose; it carries a banner saying so and pointing at `/brief`,
which is the copy `test_instructor_brief.py` keeps current.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# Append-only history and the explicitly-superseded artifact. Exempt as a whole file.
EXEMPT = {
    "PROJECT_STATE.md",
    "docs/DECISION-LOG.md",
    "docs/RUN-OF-SHOW-2026-08.md",
}

# The vocabulary that must not describe the current workshop.
ROUND_SHAPES = re.compile(r"\b(Rounds?\s*[123]\b|round-[123]\b|watch-it-burn-r[0-9]|round[123]\.agenticburn)", re.I)

# A dated measurement or verification is a historical fact even inside a current doc, so a line that
# carries a date is allowed to name the cluster it was measured on.
DATED = re.compile(r"\b20[0-9]{2}-[01][0-9]-[0-3][0-9]\b")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def tracked_markdown() -> list[pathlib.Path]:
    out = []
    for p in sorted(REPO.rglob("*.md")):
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith((".git/", "node_modules/", ".venv/")) or "/.feedback/" in f"/{rel}":
            continue
        if rel in EXEMPT:
            continue
        out.append(p)
    return out


print("== no current-description doc names a numbered round or a retired cluster ==")
offenders: list[str] = []
for p in tracked_markdown():
    rel = p.relative_to(REPO).as_posix()
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = ROUND_SHAPES.search(line)
        if not m:
            continue
        if DATED.search(line):
            continue  # a dated measurement/verification record
        offenders.append(f"{rel}:{i}: {m.group(0)!r}")
check("no round vocabulary outside the history files"
      + (f" (found {len(offenders)}: {offenders[:4]})" if offenders else ""), not offenders)

print("== the headline facts match the workshop that exists ==")
readme = (REPO / "README.md").read_text(encoding="utf-8")
# #305: transcripts about this lab routed to the wrong repo because the README never said the agent's name.
check("the README names BurritoBot", "BurritoBot" in readme)
check("the README says eight challenges, not seven",
      "eight challenges" in readme and "seven challenges" not in readme)

print("== the renamed tool is not resurrected in current docs ==")
stale_tool = [p.relative_to(REPO).as_posix() for p in tracked_markdown()
              if "get_recipe" in p.read_text(encoding="utf-8", errors="replace")]
check(f"no current doc names get_recipe (now get_vault_entry){f' ({stale_tool})' if stale_tool else ''}",
      not stale_tool)

print("== the retired-artifact banner is in place, pointing at the live brief ==")
ros = (REPO / "docs/RUN-OF-SHOW-2026-08.md").read_text(encoding="utf-8")
check("RUN-OF-SHOW says the live run of show is /brief", "THE LIVE RUN OF SHOW IS `/brief`" in ros)
check("and that it describes the retired round model", "retired round model" in ros)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All documentation-currency checks passed.")
