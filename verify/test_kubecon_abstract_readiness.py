# ABOUTME: Holds docs/KUBECON-ABSTRACT-READINESS.md to the accepted KubeCon abstract in docs/ABSTRACT.md: nine
# ABOUTME: rows in order, a legend status on each, a tally that matches, quotes found verbatim, cited paths that exist.
"""The KubeCon NA 2026 breakout's readiness against its accepted abstract (#456).

The breakout is held to the accepted Sessionize text (session 1249553), which `docs/ABSTRACT.md` carries
verbatim as Version 4. The readiness file has one row per point the text promises. It is kept current until
delivery, so this test holds what drifts when it is edited by hand: a row dropped or renumbered, a status
outside the legend, a verdict tally that no longer adds up, a quote reworded away from the accepted text,
or a cited file that was moved or deleted. It also holds the run-of-show's point table to the same nine
numbers, so the two files cannot disagree on what the points are.

Whether a status is right is a judgment made from the evidence on `staging`; this test cannot make it.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
READINESS = (REPO / "docs/KUBECON-ABSTRACT-READINESS.md").read_text(encoding="utf-8")
ABSTRACT = (REPO / "docs/ABSTRACT.md").read_text(encoding="utf-8")
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")

STATUSES = ("READY", "PARTIAL", "MISSING")
# Top-level directories whose backticked paths are checked for existence. A token outside them (a branch
# name such as agent/496-7224, an env var, a command) is not a path in this checkout.
PATH_ROOTS = ("gitops/", "challenges/", "facilitation/", "verify/", "infra/", "docs/", "observability-idp/",
              "scripts/", "images/", "teardown/", "backstage/", "policies/")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def section(text: str, heading: str) -> str:
    """The body under a markdown heading, up to the next heading of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def table_rows(body: str) -> list[list[str]]:
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-| ]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


print("== docs/ABSTRACT.md carries the accepted KubeCon text as its own version ==")
v4 = next((h for h in re.findall(r"^## (Version 4, .+)$", ABSTRACT, re.M)), "")
check("a Version 4 heading names KubeCon", "KubeCon" in v4)
v4_body = section(ABSTRACT, v4) if v4 else ""
check("Version 4 names Sessionize session 1249553", "1249553" in v4_body)
check("Version 4 names its verbatim source in talks-knowledge",
      "abstracts/recovered/sessionize-public-profile.md" in v4_body and "section 5" in v4_body)
accepted = normalize(section(v4_body, "Abstract (as published)")) if v4_body else ""
check("Version 4 has an 'Abstract (as published)' body", len(accepted) > 400)
title = normalize(section(v4_body, "Title")) if v4_body else ""
check("Version 4's title is the accepted session title",
      title == "BurritoBot Said Let's Dance, the Platform Said No")
check("the KubeCon version comes before the Portland version",
      0 <= ABSTRACT.find("## Version 4,") < ABSTRACT.find("## Version 3,"))
check("docs/ABSTRACT.md points at the readiness file", "docs/KUBECON-ABSTRACT-READINESS.md" in ABSTRACT)

print("== the readiness file names what it is held to ==")
check("it names Sessionize 1249553", "1249553" in READINESS)
check("it names the accepted text in docs/ABSTRACT.md", "docs/ABSTRACT.md" in READINESS)
check("it names the nine-point checklist's source",
      "talks/2026-10-16_hard-dated-commitments.md" in READINESS)
legend = section(READINESS, "Legend")
for s in STATUSES:
    check(f"the legend defines {s}", f"**{s}:**" in legend)

print("== nine rows, in order, one legend status each ==")
rows = table_rows(section(READINESS, "The nine points"))
header, body = (rows[0], rows[1:]) if rows else ([], [])
check("the table has a header row with a Status column", "Status" in header)
check("the table has exactly nine point rows", len(body) == 9)
status_col = header.index("Status") if "Status" in header else -1
evidence_col = next((i for i, h in enumerate(header) if h.startswith("Evidence")), -1)
check("the table has an Evidence column", evidence_col >= 0)
check("the table has a Live column, apart from the status", "Live" in header)
check("rows are numbered 1 to 9 in order", [r[0] for r in body] == [str(n) for n in range(1, 10)])
tally = {s: 0 for s in STATUSES}
for r in body:
    if len(r) != len(header):
        check(f"row {r[0]} has {len(header)} cells", False)
        continue
    status = r[status_col]
    check(f"row {r[0]} status '{status}' is in the legend", status in STATUSES)
    if status in tally:
        tally[status] += 1
    quote = re.fullmatch(r'"(.+)"', r[1])
    check(f"row {r[0]} quotes the abstract", bool(quote))
    if quote:
        # The text opens sentences in upper case where the quote picks up mid-sentence, so case is not held.
        check(f"row {r[0]}'s quote is in the accepted text, word for word",
              normalize(quote.group(1)).lower() in accepted.lower())
    paths = re.findall(r"`([^`\s]+)`", r[evidence_col]) if evidence_col >= 0 else []
    repo_paths = [p for p in paths if p.startswith(PATH_ROOTS)]
    check(f"row {r[0]} cites at least one file in this repo", bool(repo_paths))

print("== every cited path exists ==")
for p in sorted(set(re.findall(r"`([^`\s]+)`", READINESS))):
    if p.startswith(PATH_ROOTS):
        check(f"{p} exists", (REPO / p.rstrip("/")).exists())

print("== the verdict and the record agree with the table ==")
verdict = section(READINESS, next((h for h in re.findall(r"^## (Verdict, .+)$", READINESS, re.M)), "Verdict"))
expected = f"{tally['READY']} READY, {tally['PARTIAL']} PARTIAL, {tally['MISSING']} MISSING"
check(f"the verdict states the tally ({expected})", expected in verdict)
record = table_rows(section(READINESS, "Keeping this current"))
latest = record[-1] if len(record) > 1 else []
check("the record's latest line carries the same tally",
      latest[2:5] == [str(tally["READY"]), str(tally["PARTIAL"]), str(tally["MISSING"])])

print("== the run-of-show's point table has the same nine points ==")
ros_rows = table_rows(section(ROS, "Abstract points to segments"))
check("the run-of-show numbers points 1 to 9", [r[0] for r in ros_rows[1:]] == [str(n) for n in range(1, 10)])
check("the run-of-show points at the readiness file", "docs/KUBECON-ABSTRACT-READINESS.md" in ROS)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nKUBECON ABSTRACT READINESS GREEN")
