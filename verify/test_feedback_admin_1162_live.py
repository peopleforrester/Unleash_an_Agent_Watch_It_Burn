# ABOUTME: Holds #1162's last criterion (#1244): a comment on #1162 by the repo owner or hecaton confirms a marked
# ABOUTME: #1162 test submission in feedback's /admin under kubecon-na-2026 with source burritobot.
# SUITE: e2e (needs gh with a token to read #1162's comments, and the confirmation only someone with /admin can give)
"""The live half of #1244: #1162's /admin criterion, held on GitHub.

#1162's criterion: a test submission shows in the feedback app's /admin under kubecon-na-2026 with source
burritobot. /admin answers 403 to this repo's runs, so Michael or a feedback-agenticburn run reads the row and
confirms it in a comment on #1162. This test reads #1162's comments through verify/gh_comments.py and fails unless
one by the repo owner or hecaton passes verify/feedback_admin_1162.py's `comment_verdict`: it names /admin,
kubecon-na-2026, source burritobot and a marked #1162 test submission, says the row was confirmed, and does not say
/admin was not read (run 19100's own report names the four items and is the ask, not the answer). When none passes,
the FAIL names what each of their comments that names /admin lacks.

It also says which of the marked submissions in feedback_admin_1162.SUBMISSIONS a passing comment confirms, as a
NOTE: the criterion needs one confirmed row, not every one.

It is not in the promotion gate's tools tier: it is red until the confirming comment exists, and in the tier that
would hold every gate that selects it red. The offline half, verify/test_feedback_admin_1162_record.py, holds the
verdict.

Run: python3 verify/test_feedback_admin_1162_live.py
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import feedback_admin_1162 as fa  # noqa: E402
import gh_comments  # noqa: E402

OWNER_REPO, _, NUMBER = fa.ISSUE.partition("#")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print(f"== a comment on {fa.ISSUE} confirms a marked test submission in feedback's /admin ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, fa.ISSUE, check)
ours = [c for c in read.comments if c["login"] in fa.AUTHORS]
verdicts = [(c, fa.comment_verdict(c["body"])) for c in ours]
passing = [(c, why) for c, (ok, why) in verdicts if ok]
if read.ok:
    near = "; ".join(f"{c['url']}: {why}" for c, (ok, why) in verdicts if not ok and "/admin" in fa.flat(c["body"]))
    check(f"a comment by {' or '.join(sorted(fa.AUTHORS))} names /admin, {fa.EVENT}, source {fa.SOURCE} and a "
          "marked #1162 test submission, and says it confirmed the row", bool(passing),
          near or f"no comment of {len(ours)} by them names /admin; feedback-agenticburn, or Michael, reads the "
                  f"rows of runs {' and '.join(fa.SUBMISSIONS)} in /admin and confirms them on {fa.ISSUE}")
for c, why in passing:
    print(f"        confirmed at {c['url']} by {c['login']}: {why}")
if passing:
    confirmed = {r for c, _ in passing for r in fa.runs(c["body"])}
    for run, at in fa.SUBMISSIONS.items():
        print(f"  NOTE  run {run}'s marked submission ({at}) is "
              + ("confirmed" if run in confirmed else "not confirmed yet by a comment"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#1162's /admin criterion holds: a comment on the issue confirms a marked test submission under "
      f"{fa.EVENT} with source {fa.SOURCE}.")
