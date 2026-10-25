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
which is the copy `test_instructor_brief.py` keeps current. `decisions.md` is append-only like the decision
log, `notes/DEBRIEF-worlds-fair-2026.md` records the June delivery as it ran (#460), and `ACTION_ITEMS.md`
is items extracted from dated transcripts, which are kept verbatim under `transcripts/`.

**The shorthand too (#498).** The numbered names went first, but the round tables were mostly written as
"R1 succeeds / R2/R3 blocked", "The Three Rounds", "per-round", "round table". Those lines were rewritten to
say what happens on the Community cluster, on an admin cluster, and on a student's cluster before and after
they apply the control, with `challenges/LAB-TEXT.md` as the source, so the shorthand is held off as well.
`docs/ABSTRACT.md` is the published listing, which is public prose and already maps "three rounds" onto the
current workshop in its own table, so only the numbered names are held against it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from round_shapes import DATED, NUMBERED_SHAPES, ROUND_SHAPES  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

# Append-only history and the explicitly-superseded artifact. Exempt as a whole file.
EXEMPT = {
    "PROJECT_STATE.md",
    "docs/DECISION-LOG.md",
    "docs/RUN-OF-SHOW-2026-08.md",
    "decisions.md",
    "notes/DEBRIEF-worlds-fair-2026.md",
    "ACTION_ITEMS.md",
}

# Routed recordings, kept verbatim: they say what was said on the day, rounds included.
TRANSCRIPTS = "transcripts/"

# The vocabulary that must not describe the current workshop: the numbered names, then the shorthand. It
# lives in round_shapes.py, which test_round_names_retired.py holds the fleet scripts and gitops to as well.

# Public prose held to the numbered names only (see the docstring).
PUBLIC_PROSE = {"docs/ABSTRACT.md"}

# A dated measurement or verification is a historical fact even inside a current doc, so a line that
# carries a date is allowed to name the cluster it was measured on (DATED).

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
        if rel in EXEMPT or rel.startswith(TRANSCRIPTS):
            continue
        out.append(p)
    return out


print("== the round shapes catch the shorthand and nothing that merely contains 'round' ==")
for text in ("R1 (no guardrails) | succeeds", "R2/R3 (egress allow-list)", "### The Three Rounds",
             "Per-round instructor setup script", "(See Part II for the round table.)", "r2/r3 stay on",
             "the egress round-toggle", "set the round toggle state", "cross-round concurrency",
             "a three-round spectacle"):
    check(f"caught: {text!r}", ROUND_SHAPES.search(text) is not None)
for text in ("one extra round trip to Bedrock", "the model round-trip is already paid for",
             "peopleforrester/rounds-agenticburn", '"--r3": "#003E82"', "Rounds & Challenges deck",
             "There is no round selector", "WIB_ACCOUNT_R1"):
    check(f"not caught: {text!r}", ROUND_SHAPES.search(text) is None)

print("== no current-description doc names a numbered round, a retired cluster or the round shorthand ==")
offenders: list[str] = []
for p in tracked_markdown():
    rel = p.relative_to(REPO).as_posix()
    shapes = NUMBERED_SHAPES if rel in PUBLIC_PROSE else ROUND_SHAPES
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = shapes.search(line)
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
