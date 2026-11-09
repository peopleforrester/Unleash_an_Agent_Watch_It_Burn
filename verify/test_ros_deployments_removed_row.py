# ABOUTME: Holds the KubeCon run-of-show's deployments-page paragraph (#1051): every landed row kept, a swept one greyed
# ABOUTME: as "..., removed at <time>", an internal-registry one left as it was, and the paragraph through prose_gate.py.
"""The run-of-show's guardrails-switch section says what the deployments page shows once the sweep runs (#1051, #1169).

`facilitation/kubecon-na-2026-run-of-show.md`, in "The Kubernetes guardrails switch (#774)", has a paragraph on the
sweep (`remove-untrusted-room-workloads`, #990). Since #1049 and #1050 it ends by saying the deployments page keeps
every app that landed, that one the sweep removed stays listed, greyed, and reads "..., removed at <time>" within about
a minute and a half of `guardrails-on`, and that a `registry.burritobot.co` app's line is left as it was. No test read
that wording (test review run 18571). This one holds:

  1. The paragraph is in that section and says each of those things, and the wording it replaced ("still lists what
     landed", "a record of the room's asks") is gone from the file.
  2. What it quotes is what the page writes: the page's script in `gitops/ai-layer/ticket_site.py` appends
     ", removed at " and the removed time to a row with one and gives it the class `removed`, which the page's style
     greys, and gives a row with no removed time neither.
  3. The paragraph passes `verify/prose_gate.py`: in a throwaway repo whose base holds the run-of-show with the
     paragraph cut out, the run-of-show as it stands passes the gate, and the same file with an em-dash, the talk's
     hype verb or the connective the gate reads as "let's" put into the paragraph fails it. The real scanner is on
     hecaton hosts only, so this drives the script with `verify/fixtures/prose-gate/fake_aiisms.py`, the stand-in
     `verify/test_prose_gate.py` uses, and checks the paragraph itself carries no em-dash and no en-dash, which the
     gate fails at any severity. A run holds the paragraph to the real scanner with
     `python3 verify/prose_gate.py /var/lib/hecaton/app/current/src/hecaton/run/aiisms.py origin/staging`.

The page's behaviour on a cluster is verify/test_deployments_removed_live.py's, and offline
verify/test_deployments_witch_line_e2e.py's. Each cut on repo text checks its literal first and exits naming it when it
is gone ("Tests own their inputs"), and each wording check is run again on a copy with the old wording put back or a
claim cut, so a check that could never fail shows up here.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
ROS_PATH = REPO / ROS_REL
SITE_PATH = REPO / "gitops/ai-layer/ticket_site.py"
PROSE_GATE = REPO / "verify/prose_gate.py"
FAKE = REPO / "verify/fixtures/prose-gate/fake_aiisms.py"

SECTION = "**The Kubernetes guardrails switch (#774).**"
PARA_START = "Kyverno also clears what the room left behind (#990)"

# Each claim the paragraph makes, as words that must appear in it once its line breaks are read as spaces.
CLAIMS = [
    ("the page keeps every landed row", "The deployments page keeps every app that landed."),
    ("a swept row stays listed and greyed", "One the sweep removed stays listed, greyed,"),
    ("a swept row reads \"..., removed at <time>\"", "reads \"..., removed at <time>\""),
    ("the mark comes within about a minute and a half of guardrails-on",
     "within about a minute and a half of `guardrails-on` (#1049, #1050)"),
    ("an internal-registry row is left as it was", "a `registry.burritobot.co` app's line is left as it was."),
]
# What the paragraph said before #1051; neither may come back.
OLD_WORDING = ["still lists what landed", "record of the room"]

# The page's script and style, as ticket_site.py writes them (#1049).
SITE_REMOVED_LINE = "if(x.removed_at){li.className='removed';li.appendChild(document.createTextNode(', removed at '+x.removed_at));}"
SITE_GREY_STYLE = "li.removed,li.removed b{color:#9b93a8}"

EM_DASH, EN_DASH = "—", "–"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def need(literal: str, text: str, where: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR GONE: {literal!r} is not in {where}; reword this test with the text, do not revert the text")


def paragraph(ros: str) -> tuple[int, int]:
    """The [start, end) offsets of the sweep paragraph inside the guardrails-switch section."""
    need(SECTION, ros, ROS_REL)
    sec = ros.index(SECTION)
    need(PARA_START, ros[sec:], f"{ROS_REL}'s guardrails-switch section")
    start = ros.index(PARA_START, sec)
    end = ros.find("\n\n", start)
    return start, (len(ros) if end < 0 else end)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def wording_failures(ros: str) -> list[str]:
    """The claims and old-wording rules a copy of the run-of-show breaks, by name."""
    start, end = paragraph(ros)
    para = flat(ros[start:end])
    broken = [name for name, words in CLAIMS if words not in para]
    broken += [f"old wording {old!r} is back" for old in OLD_WORDING if old in flat(ros)]
    return broken


ros = ROS_PATH.read_text(encoding="utf-8")
start, end = paragraph(ros)
para_text = ros[start:end]

print("== 1. the run-of-show's paragraph says what the page shows after the sweep ==")
para = flat(para_text)
for name, words in CLAIMS:
    check(name, words in para, f"no {words!r} in the paragraph: {para}")
for old in OLD_WORDING:
    check(f"the old wording {old!r} is gone", old not in flat(ros))
check("the claims come in order: kept, greyed, removed at, the internal line",
      all(para.index(CLAIMS[i][1]) < para.index(CLAIMS[i + 1][1]) for i in range(len(CLAIMS) - 1)
          if CLAIMS[i][1] in para and CLAIMS[i + 1][1] in para), para)

print("== 1b. each wording check fails on a copy that breaks it ==")
check("the file as it stands breaks none", wording_failures(ros) == [], str(wording_failures(ros)))
for name, words in CLAIMS:
    need(words, para, f"{ROS_REL}'s sweep paragraph (flattened)")
    # Cut the claim's words from the paragraph, with its line breaks flattened so a claim across two lines is cut whole.
    broken_copy = ros[:start] + flat(para_text).replace(words, "") + ros[end:]
    check(f"a copy without {name!r} fails it", name in wording_failures(broken_copy), str(wording_failures(broken_copy)))
for old in OLD_WORDING:
    old_copy = ros[:end] + f" The page {old}." + ros[end:]
    check(f"a copy with {old!r} put back fails", f"old wording {old!r} is back" in wording_failures(old_copy),
          str(wording_failures(old_copy)))

print("== 2. what the paragraph quotes is what the page writes ==")
site = SITE_PATH.read_text(encoding="utf-8")
need("_DEPLOY_SCRIPT", site, "gitops/ai-layer/ticket_site.py")
need("_DEPLOY_STYLE", site, "gitops/ai-layer/ticket_site.py")
check("a row with a removed time gets ', removed at <time>' and the class removed", SITE_REMOVED_LINE in site,
      f"no {SITE_REMOVED_LINE!r} in ticket_site.py")
check("the page's style greys the class removed, text and witch name", SITE_GREY_STYLE in site,
      f"no {SITE_GREY_STYLE!r} in ticket_site.py")
check("only that branch sets the class removed or writes ', removed at '",
      site.count("li.className='removed'") == 1 and site.count("', removed at '") == 1,
      "a second place in the page's script greys a row or writes the removed time")

print("== 3. the paragraph passes verify/prose_gate.py ==")
check("the paragraph carries no em-dash", EM_DASH not in para_text, para_text)
check("the paragraph carries no en-dash", EN_DASH not in para_text, para_text)

tmp = pathlib.Path(tempfile.mkdtemp())
repo = tmp / "r"
env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
env.update(HOME=str(tmp), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(*args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, capture_output=True)


def put(text: str) -> None:
    f = repo / ROS_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def gate() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(PROSE_GATE), str(FAKE), "staging"], cwd=repo, env=env,
                          capture_output=True, text=True)


subprocess.run(["git", "-c", "init.defaultBranch=staging", "init", "-q", str(repo)], env=env, check=True)
put(ros[:start] + ros[end:])
git("add", "-A")
git("commit", "-q", "-m", "base: the run-of-show without the sweep paragraph")
git("checkout", "-q", "-b", "agent/1169-1")

put(ros)
r = gate()
check("the run-of-show with the paragraph added passes the gate", r.returncode == 0, r.stdout + r.stderr)
check("the gate read the run-of-show", "pass, 1 public-prose file(s) read" in r.stdout, r.stdout + r.stderr)

# The same paragraph with one thing the gate fails put into it: each must fail, or the pass above proves nothing.
need("stays listed, greyed,", para_text, f"{ROS_REL}'s sweep paragraph")
for label, bad, expect in [
    ("an em-dash", "stays listed " + EM_DASH + " greyed,", "em-dash (+1)"),
    ("the talk's hype verb", "stays listed, greyed, Unleashed,", "vocabulary: hype verbs (+1)"),
    ("the connective read as let's", "stays listed, greyed, lets it", "connective: let's (+1)"),
]:
    put(ros[:start] + para_text.replace("stays listed, greyed,", bad, 1) + ros[end:])
    r = gate()
    check(f"the paragraph with {label} fails the gate, naming it", r.returncode == 1 and expect in r.stdout,
          r.stdout + r.stderr)

subprocess.run(["rm", "-rf", str(tmp)], check=False)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All run-of-show deployments removed-row checks passed.")
