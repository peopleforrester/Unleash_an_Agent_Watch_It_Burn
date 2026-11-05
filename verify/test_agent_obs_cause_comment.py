# ABOUTME: Reads #783's comments with gh's token (#863) and checks one names why Agent Observability got no BurritoBot
# ABOUTME: spans from 2026-11-01: the copy kept APM's trace id, whose spans carry dd_llmobs_enabled false (#811).
# SUITE: e2e (needs the network and gh with a token: `gh api` is asked for the issue's comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #783's first criterion is "The cause of Agent Observability receiving no BurritoBot spans since 2026-11-01
# ~03:30 UTC is named in a comment on this issue." verify/test_trace_shape_e2e.py holds the fix in the collector, and
# decisions.md's #783 entry holds the cause, but nothing in the tree is the comment. Hecaton's run report and merge
# comment on #783 name it: #746's collector change (241f8e6) sent Agent Observability a copy of each trace under the
# original trace id and marked every APM span dd_llmobs_enabled false, and an explicit false on any span stops
# conversion of the whole trace. This asks GitHub for the issue's comments through verify/gh_comments.py, with
# gh's token and not the host's shared anonymous quota (#863), and fails when no comment by hecaton or Michael
# names that cause, or names another commit than decisions.md does.
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402

DECISIONS = REPO / "decisions.md"
VALUES = REPO / "gitops" / "otel-collector" / "values.yaml"
ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#783"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
# Who may name the cause on the issue: the dispatcher that posts each run's report, and the repo's owner.
# gh issue view reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", ""))



# The cause as decisions.md records it, so the comment and the record name the same change.
decisions = DECISIONS.read_text(encoding="utf-8")
m = re.search(r"^## [^\n]*· #783 · Agent Observability's copy gets a trace id of its own[^\n]*$(.*?)(?=^## |\Z)",
              decisions, re.M | re.S)
entry = flat(m.group(1)) if m else ""
print("== decisions.md's #783 entry names the cause the comment must name ==")
check("decisions.md has #783's entry on the copy's own trace id", bool(entry))
cited = re.search(r"\*\*The cause\.\*\* #746's collector change \(([0-9a-f]{7,40}),", entry)
check("the entry's cause names #746's collector change by its commit", bool(cited))
commit = cited.group(1) if cited else ""
check("the entry says the copy kept the original trace id", "The copy kept the original trace id" in entry)
check("the entry says APM's spans are marked dd_llmobs_enabled false", "dd_llmobs_enabled false" in entry)
check("the entry says an explicit false on any span prevents conversion of the entire trace",
      "an explicit false on any span prevents conversion of the entire trace" in entry)

# The fix the cause calls for is still in the collector: the copy's trace id is derived, not APM's.
values = VALUES.read_text(encoding="utf-8")
check("the collector's transform/llmobs_one_root gives the copy a SHA-256-derived trace id",
      "set(trace_id.string, Substring(SHA256(trace_id.string), 0, 32))" in values)


def names_cause(body: str) -> list[str]:
    """What the comment leaves out of the cause; empty when it names all of it."""
    low = body.lower()
    parts = {
        "#746's collector change": "#746" in low,
        f"commit {commit}": bool(commit) and commit in low,
        "a copy for Agent Observability": "copy" in low and "agent observability" in low,
        "under the original trace id": "original trace id" in low,
        "APM spans marked dd_llmobs_enabled false": "dd_llmobs_enabled false" in low and "apm" in low,
        "an explicit false on any span stops conversion of the whole trace":
            re.search(r"explicit false on any span \w+ conversion of the (whole|entire) trace", low) is not None,
    }
    return [name for name, ok in parts.items() if not ok]


print(f"== a comment on {ISSUE} names the cause ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, ISSUE, check)
got = read.comments
ours = [c for c in got if c["login"] in AUTHORS]
if got:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in got})))
if ours:
    missing = [(c["url"], names_cause(flat(c.get("body") or ""))) for c in ours]
    named = [url for url, left in missing if not left]
    closest = min(missing, key=lambda x: len(x[1]))
    check(f"one comment names the cause: #746's change ({commit}) sent the copy under the original trace id, APM's "
          "spans are marked dd_llmobs_enabled false, and an explicit false vetoes the whole trace", bool(named),
          f"closest is {closest[0]}, which leaves out: {'; '.join(closest[1])}")
    if named:
        print(f"  the cause is named at {named[0]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All #783 cause comment checks passed.")
