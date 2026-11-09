# ABOUTME: Holds the #1267 research note to its criterion: per surface the room can write to, what reaches the screen
# ABOUTME: today, the option chosen and why, and every vendor claim it rests on dated and sourced (#1290).
"""No cluster, no network, standard library only.

#1267's first criterion asks for a research note in docs/research/ that names, for each surface the issue lists (the
prompt wall, the chat page's saved-prompts rail, the prompt sent to the bot, the bot's reply, the support desk, the
deployments page, the cluster's objects and the Datadog traces shown on stage), what reaches the screen today, the
option chosen and why, with each claim about a vendor feature dated and sourced. The note is
docs/research/2026-11-09-coc-floor/README.md. test_coc_floor_spike.py reruns its measurement but reads none of that,
so a row dropped from the surfaces table, an emptied "Why", or a vendor claim that lost its link passed every test.

This reads the note's "The surfaces" table and its "Vendor facts used, dated and sourced" section and fails on:
a surface with no row, a row with an empty cell, a code name a row cites that the repo no longer has,
a vendor claim with no source, a read date that is missing, malformed, in the future or disagrees with the note's
opening line, or a vendor the surfaces table relies on with no dated block. It then runs the same checks on the note
with each of those faults written in, so a check that stops seeing its fault fails too.
"""
from __future__ import annotations

import datetime
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
NOTE_PATH = REPO / "docs/research/2026-11-09-coc-floor/README.md"

# The surfaces #1267 lists under "What exists today", each with a pattern its row's Surface cell must match.
SURFACES = {
    "prompt wall": r"prompt wall",
    "chat page's saved-prompts rail": r"saved prompts",
    "prompt sent to the bot": r"prompt sent to the bot",
    "bot's reply": r"bot's reply",
    "support desk": r"support desk",
    "deployments page": r"deployments page",
    "cluster objects": r"cluster objects",
    "Datadog traces": r"datadog traces",
}
COLUMNS = ("Surface", "What reaches the screen today", "Chosen", "Why")
# Code names a row cites for what reaches the screen and where the choice lands, and the repo file that must
# still hold each. guard-proxy's proxy.py is a
# submodule and is not read here; test_guard_proxy_pin_1267.py and test_prompt_wall_redaction.py hold it.
CHAT_PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
DESK = REPO / "gitops/ai-layer/ticket_site.py"
MCP_SERVER = REPO / "gitops/ai-layer/workshop-mcp-server.py"
COLLECTOR = REPO / "gitops/otel-collector/values-burn.yaml"
ROW_CITES = {
    "chat page's saved-prompts rail": [("COC_TERMS", CHAT_PAGE)],
    "support desk": [("/submit", DESK)],
    "deployments page": [("record_landing", DESK)],
    "cluster objects": [("deploy_app", MCP_SERVER), ("run_shell", MCP_SERVER)],
    "Datadog traces": [("transform/scrub_pii", COLLECTOR)],
}
# The vendor blocks the vendor section must hold, by the words each block opens with.
VENDOR_BLOCKS = ("Amazon Bedrock Guardrails", "agentgateway", "kagent", "LLM Guard", "Datadog",
                 "OpenTelemetry Collector")
# A vendor the surfaces table relies on (the word in the table) and the block that must date and source it.
TABLE_VENDORS = {"Bedrock": "Amazon Bedrock Guardrails", "Datadog": "Datadog", "collector": "OpenTelemetry Collector"}
# A source is a link, or a file named in backticks at a released version ("`go/api/...go` at v0.10.1").
SOURCE = re.compile(r"https?://\S+|`[\w./-]+\.\w+` at v\d+(?:\.\d+)+")
OPENING = re.compile(r"Vendor claims below were read on (\S+?) and carry their source\.")
VENDOR_HEADING = re.compile(r"^## Vendor facts used, dated and sourced \(read ([^)]*)\)$", re.M)


def section(text: str, heading: str) -> str | None:
    match = re.search(r"^## " + re.escape(heading) + r".*$", text, re.M)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(r"^## ", rest, re.M)
    return rest[: end.start()] if end else rest


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def iso_date(raw: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


def vendor_claims(body: str) -> list[tuple[str, str]]:
    """(block, claim) pairs: each bullet under a block that ends in a colon, or a whole paragraph otherwise."""
    claims: list[tuple[str, str]] = []
    for para in re.split(r"\n\s*\n", body.strip()):
        lines = para.splitlines()
        if not lines:
            continue
        head = lines[0]
        if head.rstrip().endswith(":") and len(lines) > 1 and lines[1].startswith("- "):
            bullet: list[str] = []
            for line in lines[1:]:
                if line.startswith("- ") and bullet:
                    claims.append((head, " ".join(bullet)))
                    bullet = []
                bullet.append(line.strip())
            if bullet:
                claims.append((head, " ".join(bullet)))
        else:
            claims.append((head, " ".join(line.strip() for line in lines)))
    return claims


def problems(text: str, today: datetime.date) -> list[str]:
    found: list[str] = []

    # Per surface: a row, its four cells filled, and the code names its "today" cell cites still in the repo.
    table = section(text, "The surfaces")
    if table is None:
        return ["the note has no '## The surfaces' section"]
    rows = [cells(line) for line in table.splitlines() if line.startswith("|")]
    if not rows or tuple(rows[0][: len(COLUMNS)]) != COLUMNS:
        found.append(f"the surfaces table's header is not {' | '.join(COLUMNS)} (found {rows[0] if rows else None})")
        return found
    data = [r for r in rows[2:] if r and r[0]]
    for name, pattern in SURFACES.items():
        matched = [r for r in data if re.search(pattern, r[0], re.I)]
        if len(matched) != 1:
            found.append(f"surface '{name}': {len(matched)} rows in the surfaces table, want 1")
            continue
        row = matched[0]
        for column, cell in zip(COLUMNS[1:], row[1:len(COLUMNS)]):
            if len(cell.split()) < 3:
                found.append(f"surface '{name}': its '{column}' cell is empty or a stub ({cell!r})")
        if len(row) < len(COLUMNS):
            found.append(f"surface '{name}': its row has {len(row)} cells, want at least {len(COLUMNS)}")
        for cite, path in ROW_CITES.get(name, []):
            if not any(cite in cell for cell in row):
                found.append(f"surface '{name}': its row no longer cites {cite!r}, which this test holds")
            elif cite not in path.read_text(encoding="utf-8"):
                found.append(f"surface '{name}': the note cites {cite!r} but {path.relative_to(REPO)} no longer holds it")

    # Every vendor claim dated and sourced.
    opening = OPENING.search(text)
    heading = VENDOR_HEADING.search(text)
    if not opening:
        found.append("the note's opening no longer says when the vendor claims were read")
    if not heading:
        found.append("no '## Vendor facts used, dated and sourced (read <date>)' heading")
        return found
    dates = {"opening": opening.group(1) if opening else None, "heading": heading.group(1)}
    for where, raw in dates.items():
        if raw is None:
            continue
        day = iso_date(raw)
        if day is None:
            found.append(f"the {where}'s read date {raw!r} is not a YYYY-MM-DD date")
        elif day > today:
            found.append(f"the {where}'s read date {raw} is after today ({today})")
    if dates["opening"] and dates["opening"] != dates["heading"]:
        found.append(f"the opening reads vendor claims on {dates['opening']}, the vendor heading on {dates['heading']}")

    body = section(text, "Vendor facts used")
    claims = vendor_claims(body or "")
    if not claims:
        found.append("the vendor section holds no claims")
    for block, claim in claims:
        if not SOURCE.search(claim):
            found.append(f"vendor claim under {block.split(':')[0]!r} carries no source: {claim[:90]!r}")
    heads = [block for block, _ in claims]
    for vendor in VENDOR_BLOCKS:
        if not any(h.startswith(vendor) for h in heads):
            found.append(f"no dated, sourced block for {vendor} in the vendor section")
    for word, vendor in TABLE_VENDORS.items():
        if word in table and not any(h.startswith(vendor) for h in heads):
            found.append(f"the surfaces table relies on {word} but the vendor section has no {vendor} block")
    return found


def replace_once(text: str, old: str, new: str) -> str:
    """The mutation's anchor must be in the note, so a reworded note reads as that and not as a broken check."""
    if text.count(old) != 1:
        print(f"FAIL anchor {old[:70]!r} appears {text.count(old)} times in {NOTE_PATH.relative_to(REPO)}, want 1")
        sys.exit(1)
    return text.replace(old, new)


def drop_line(text: str, starts: str) -> str:
    lines = [line for line in text.splitlines(keepends=True) if line.startswith(starts)]
    if len(lines) != 1:
        print(f"FAIL anchor line {starts!r} appears {len(lines)} times in {NOTE_PATH.relative_to(REPO)}, want 1")
        sys.exit(1)
    return text.replace(lines[0], "")


def main() -> int:
    note = NOTE_PATH.read_text(encoding="utf-8")
    today = datetime.date.today()
    failures = 0

    print("== the note as it stands ==")
    real = problems(note, today)
    for problem in real:
        print("FAIL " + problem)
    if not real:
        print(f"PASS all {len(SURFACES)} surfaces have a row naming what reaches the screen, the choice and why")
        claims = vendor_claims(section(note, "Vendor facts used") or "")
        print(f"PASS all {len(claims)} vendor claims in {len(VENDOR_BLOCKS)} blocks carry a source, read on a stated date")
    failures += len(real)

    print("== each fault, written into the note, is caught ==")
    datadog = section(note, "Vendor facts used") or ""
    datadog_para = next((p for p in re.split(r"\n\s*\n", datadog) if p.startswith("Datadog:")), None)
    if datadog_para is None:
        print(f"FAIL anchor 'Datadog:' paragraph not in {NOTE_PATH.relative_to(REPO)}'s vendor section")
        return 1
    desk_row = "| Support desk (`POST /submit`) |"
    mutations = {
        "the support desk's row removed": (drop_line(note, desk_row), "surface 'support desk': 0 rows"),
        "a cited code name dropped from its row": (
            replace_once(note, "; `record_landing` masks the row's fields", "; the desk masks the row's fields"),
            "no longer cites 'record_landing'"),
        "a row's Why emptied": (
            replace_once(note, "| one list everywhere; the page otherwise saves what `/chat` refuses |", "| |"),
            "'Why' cell is empty"),
        "a row's today cell emptied": (
            replace_once(note, "| raw prompts and replies, by design for the LLM Observability panels |", "| |"),
            "surface 'Datadog traces': its 'What reaches the screen today' cell is empty"),
        "a vendor claim's links removed": (
            replace_once(note, datadog_para, re.sub(r"https?://\S+", "the docs", datadog_para)),
            "under 'Datadog' carries no source"),
        "the Datadog block removed": (replace_once(note, datadog_para, ""), "relies on Datadog"),
        "the vendor heading undated": (
            replace_once(note, "## Vendor facts used, dated and sourced (read 2026-11-09)",
                         "## Vendor facts used, dated and sourced (read recently)"),
            "not a YYYY-MM-DD date"),
        "a read date in the future": (
            replace_once(note, "read on 2026-11-09 and carry", f"read on {today + datetime.timedelta(days=1)} and carry"),
            "is after today"),
        "the opening's read date dropped": (
            replace_once(note, "Vendor claims below were read on 2026-11-09 and carry their source.", ""),
            "no longer says when the vendor claims were read"),
    }
    for what, (mutated, expect) in mutations.items():
        got = problems(mutated, today)
        hit = [p for p in got if expect in p]
        print(("PASS " if hit else "FAIL ") + f"{what}: " + (hit[0] if hit else f"not caught (got {got})"))
        failures += 0 if hit else 1

    print(f"{failures} failure(s)" if failures else "ALL CHECKS PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
