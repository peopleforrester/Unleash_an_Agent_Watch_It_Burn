# ABOUTME: CLAUDE.md's "Dispatched runs" point 1 says a run checks live only for a live-check issue or a change to what
# ABOUTME: the clusters run, and that a docs, records or harness-only change skips it and says so (#1062).
"""Holds both lists of #1062 in CLAUDE.md, so a later edit cannot drop one without this failing.

Every dispatched run used to check live on watch-it-burn-community or watch-it-burn-private, a run that only added a
decisions.md entry or a test included. Michael ruled on 2026-11-07 that a run checks live only when the issue's own
work is a live check or a live run, or when the change touches what the clusters run, and that a change touching only
the records, docs, `facilitation/` or harness files skips it and says so in one line of its decisions.md entry.

The live list is held two ways: each path the issue names is in it, and each path the repo itself says a cluster runs
is in it too. That second half reads the tree: the top directory of every local source an Argo CD Application in
gitops/bootstrap/apps/ names, every submodule in .gitmodules, and every verify/ script fleet.sh runs. A new Application
source, submodule or fleet.sh call then fails here until point 1 names it. A self-check drops each entry from a copy
of the text in turn and confirms the check reports it missing.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
APPS = REPO / "gitops/bootstrap/apps"
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
GITMODULES = REPO / ".gitmodules"

ITEM_LABEL = "A run checks live on the two clusters that are up, and brings none up or down"
LIVE_START = "a run checks live only when"
LIVE_END = "A change that touches only"
SKIP_END = "skips the live check and says so in one line of its decisions.md entry"

# What the issue names, word for word as point 1 writes it.
LIVE_NAMED = [
    "the issue's own work is a live check or a live run",
    "`gitops/`",
    "`policies/`",
    "`images/`",
    "`gitops/workshop-agent/agent.yaml` (the agent prompt)",
    "fleet.sh",
    "guard-proxy",
    "llm-guard",
    "submodule pointer",
]
SKIP_NAMED = [
    "`decisions.md`",
    "`PROGRESS.md`",
    "`PROJECT_STATE.md`",
    "docs",
    "`facilitation/`",
    "files under `verify/` that no cluster runs",
]
# The rest of point 1 that #1062 leaves as it was.
KEPT = [
    "`$KUBECONFIG` whose only contexts are `watch-it-burn-community`",
    "`watch-it-burn-private`",
    "never creates or tears down a cluster or nodegroup",
    "there is no third cluster",
    "Each `kubectl` call still names its `--context`",
    "A live check that changes a cluster leaves it as found",
    '"Not yet run on a cluster"',
]

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def point_one(text: str) -> str:
    """Point 1 of the Dispatched runs section, continuation lines included, whitespace folded."""
    sec = re.search(r"^## Dispatched runs \(hecaton\)\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not sec:
        return ""
    m = re.search(rf"^1\. \*\*{re.escape(ITEM_LABEL)}.*?(?=^\d+\. |^\S|\Z)", sec.group(1), re.M | re.S)
    return flat(m.group(0)) if m else ""


def lists(item: str) -> tuple[str, str]:
    """The live sentence and the skip sentence of point 1, or empty strings when an anchor is gone."""
    start = item.find(LIVE_START)
    mid = item.find(LIVE_END, start)
    end = item.find(SKIP_END, mid)
    if start < 0 or mid < 0 or end < 0:
        return "", ""
    return item[start:mid], item[mid:end + len(SKIP_END)]


def cluster_run_paths() -> list[str]:
    """Each path the tree says a cluster runs: Application source tops, submodules, verify/ scripts fleet.sh runs."""
    paths: set[str] = set()
    for app in sorted(APPS.glob("*.yaml")):
        for src in re.findall(r"^\s+path:\s*['\"]?([^'\"\s]+)", app.read_text(encoding="utf-8"), re.M):
            top = src.split("/")[0]
            # A JSON patch's `path: /spec/...` is not a source; a source path is relative to this repo.
            if top and (REPO / top).is_dir():
                paths.add(f"`{top}/`")
    for sub in re.findall(r"^\s*path\s*=\s*(\S+)", GITMODULES.read_text(encoding="utf-8"), re.M):
        paths.add(f"`{sub}`")
    for script in re.findall(r"\$\{INFRA_DIR\}/\.\./(verify/[\w.-]+)", FLEET.read_text(encoding="utf-8")):
        paths.add(f"`{script}`")
    return sorted(paths)


def missing(text: str, derived: list[str]) -> list[str]:
    """Every entry of either list, or of the kept text, that point 1 of `text` no longer says."""
    item = point_one(text)
    if not item:
        return [f"point 1 ({ITEM_LABEL!r})"]
    live, skip = lists(item)
    if not live:
        return [f"the anchors {LIVE_START!r}, {LIVE_END!r} and {SKIP_END!r}, in that order"]
    out = [f"live: {e}" for e in LIVE_NAMED + derived if e not in live]
    out += [f"skip: {e}" for e in SKIP_NAMED if e not in skip]
    out += [f"kept: {e}" for e in KEPT if e not in item]
    return out


text = CLAUDE.read_text(encoding="utf-8")
derived = cluster_run_paths()

print("== CLAUDE.md is the file point 1 lives in ==")
check("CLAUDE.md exists and reads as AGENTS.md", CLAUDE.exists() and text == (REPO / "AGENTS.md").read_text(encoding="utf-8"))

print("== the tree names what the clusters run ==")
for need in ("`gitops/`", "`policies/`", "`gitops/ai-layer/guard-proxy`", "`images/llm-guard`", "`verify/datadog-orgs.sh`"):
    check(f"the derived list holds {need}", need in derived)
print(f"  derived: {', '.join(derived)}")
for entry in derived:
    path = entry.strip("`").rstrip("/")
    check(f"{entry} exists in the tree", (REPO / path).exists())

print("== point 1 says when a run checks live and when it skips (#1062) ==")
gone = missing(text, derived)
for entry in LIVE_NAMED + derived:
    check(f"the live list names {entry}", f"live: {entry}" not in gone)
for entry in SKIP_NAMED:
    check(f"the skip list names {entry}", f"skip: {entry}" not in gone)
check("a skipping run says so in one line of its decisions.md entry", SKIP_END in point_one(text))
check("it names Michael's ruling of 2026-11-07 and #1062", "2026-11-07 (#1062)" in point_one(text))
for entry in KEPT:
    check(f"the rest of point 1 still says {entry}", f"kept: {entry}" not in gone)
check("nothing else is reported missing", not gone)
if gone:
    print("  missing: " + "; ".join(gone))

print("== self-check: dropping any entry from a copy of the text is caught ==")
item_raw = re.search(rf"^1\. \*\*{re.escape(ITEM_LABEL)}.*?(?=^\d+\. |^\S|\Z)", text, re.M | re.S)
check(f"the anchor {ITEM_LABEL!r} is in {CLAUDE.name}", bool(item_raw))
if item_raw:
    flat_text = text[: item_raw.start()] + flat(item_raw.group(0)) + "\n" + text[item_raw.end():]
    check("the folded copy reports nothing missing", not missing(flat_text, derived))
    for label, entries in (("live", LIVE_NAMED + derived), ("skip", SKIP_NAMED), ("kept", KEPT)):
        for entry in entries:
            if label == "live":
                live, _ = lists(point_one(flat_text))
                cut = flat_text.replace(live, live.replace(entry, "<dropped>"), 1)
            elif label == "skip":
                _, skip = lists(point_one(flat_text))
                cut = flat_text.replace(skip, skip.replace(entry, "<dropped>"), 1)
            else:
                cut = flat_text.replace(entry, "<dropped>")
            check(f"dropping {label} {entry} is caught", f"{label}: {entry}" in missing(cut, derived))
    for anchor in (LIVE_START, LIVE_END, SKIP_END):
        check(f"losing the anchor {anchor!r} is caught", bool(missing(flat_text.replace(anchor, "<dropped>"), derived)))

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed")
    sys.exit(1)
print("\nPASS: CLAUDE.md point 1 holds both live-check lists (#1062)")
