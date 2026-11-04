# ABOUTME: Reads #796's comments from GitHub anonymously and checks one names both causes AGENTS.md's fourth and fifth
# ABOUTME: Dispatched runs items were extended for: run 15816's E2E wait and run 9604's ai-isms failure (#834).
# SUITE: e2e (needs the network: api.github.com is asked for the issue's comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #796's first criterion is "The cause is named in a comment on this issue." verify/test_dispatched_runs.py
# holds what the fix says in AGENTS.md, but nothing in the tree is the comment (#834). Michael's comment on #796, and
# hecaton's first run report there, name both causes. Run 15816: verify/run-e2e-tools.sh took longer than the
# 20 minutes that run gave its background job, and pgrep by script name matched other runs' processes. Run 9604:
# hecaton's ai-isms gate counts every form of the talk's verb as a hype verb, and decisions.md, PROJECT_STATE.md and
# PROGRESS.md already read major, so the repo's nickname in a run's record failed the run. This asks GitHub for the
# issue's comments, as anyone may (the repo is public), and fails when no comment by hecaton or Michael names both,
# or names other runs, or another time limit, than the ones AGENTS.md cites.
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"
ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#796"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
# Who may name the cause on the issue: the dispatcher that posts each run's report, and the repo's owner.
AUTHORS = {"hecatongithub[bot]", "peopleforrester"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", ""))


def comments() -> tuple[list[dict], str]:
    """Every comment on the issue, following the Link header's next pages, or [] and why not."""
    url = f"https://api.github.com/repos/{OWNER_REPO}/issues/{NUMBER}/comments?per_page=100"
    out: list[dict] = []
    try:
        while url:
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "verify-prose-gate-e2e-wait-cause-comment"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out += json.load(r)
                nxt = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
                url = nxt.group(1) if nxt else ""
    except urllib.error.HTTPError as e:
        left = e.headers.get("X-RateLimit-Remaining") if e.headers else None
        return [], f"HTTP {e.code} {e.reason}" + (f", {left} anonymous requests left this hour" if left else "")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return [], f"{type(e).__name__}: {e}"
    return out, ""


# The runs, and the time limit, AGENTS.md cites for the two causes, so the comment and the fix name the same ones.
agents = AGENTS.read_text(encoding="utf-8")
m = re.search(r"^## Dispatched runs \(hecaton\)\s*$(.*?)(?=^## |\Z)", agents, re.M | re.S)
runs = flat(m.group(1)) if m else ""
print("== AGENTS.md names the two runs whose causes the comment must name ==")
check("AGENTS.md has a 'Dispatched runs (hecaton)' section", bool(runs), str(AGENTS))
cited = re.search(r"Run (\d+) lost its time to the fourth as well, and run (\d+) to the fifth \(#796\)", runs)
check("the section's intro names the run that lost its time to the fourth item and the one that lost it to the "
      "fifth (#796)", bool(cited), "no 'Run N lost its time to the fourth as well, and run N to the fifth (#796)'")
e2e_run, prose_run = cited.groups() if cited else ("", "")
limit = re.search(rf"run {e2e_run} gave it (\d+) minutes and it was cut off", runs) if e2e_run else None
check(f"item 4 names the background limit run {e2e_run or '?'} gave the E2E job", bool(limit))
minutes = limit.group(1) if limit else ""
check("item 4 warns against pgrep by script name", "Do not watch the job with pgrep or pkill by script name" in runs)
check("item 5 names the ai-isms gate and its hype-verb list",
      "Prose is put through the ai-isms gate" in runs and "on the hype-verb list" in runs)

print(f"== a comment on {ISSUE} names the cause ==")
got, why = comments()
check(f"GitHub answers an anonymous read of {ISSUE}'s comments with at least one", bool(got), why or "none")
ours = [c for c in got if c.get("user", {}).get("login") in AUTHORS]
check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours) or not got,
      ", ".join(sorted({c.get("user", {}).get("login", "?") for c in got})))


def e2e_cause(body: str) -> bool:
    """Run 15816's E2E command outran the background limit it was given, and pgrep by name found other runs."""
    low = body.lower()
    return (bool(e2e_run) and bool(minutes) and f"run {e2e_run}" in low and "run-e2e-tools.sh" in low
            and re.search(rf"\b{minutes}[- ]minute", low) is not None and "pgrep" in low and "other runs" in low)


def prose_cause(body: str) -> bool:
    """Run 9604's record used the repo's nickname, which the ai-isms gate counts as a hype verb in a major file."""
    low = body.lower()
    return (bool(prose_run) and f"run {prose_run}" in low and "ai-isms gate" in low
            and re.search(r"hype[- ]verb", low) is not None and "unleash" in low and "major" in low
            and all(f in low for f in ("decisions.md", "project_state.md", "progress.md")))


bodies = [(c.get("html_url", "?"), flat(c.get("body") or "")) for c in ours]
both = [url for url, body in bodies if e2e_cause(body) and prose_cause(body)]
if ours:
    check(f"a comment names run {e2e_run} (#796): run-e2e-tools.sh outran the {minutes}-minute background limit, "
          "and pgrep by name matched other runs", any(e2e_cause(b) for _, b in bodies))
    check(f"a comment names run {prose_run} (#796): the ai-isms gate counts the repo's nickname as a hype verb, and "
          "decisions.md, PROJECT_STATE.md and PROGRESS.md already read major", any(prose_cause(b) for _, b in bodies))
    check("one comment names both causes", bool(both))
    if both:
        print(f"  the cause is named at {both[0]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All #796 cause comment checks passed.")
