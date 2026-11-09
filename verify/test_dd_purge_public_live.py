# ABOUTME: Holds #647's post-talk purge (#1166): a comment on #647 records dd_purge_public.py's purge, and a --verify of
# ABOUTME: its window finds no burritobot-public Agent Observability or APM span, the scrub check's own included.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, gh with a token for #647's comments, and the purge after the talk)
"""The live half of #1166: #647's criterion, held on GitHub and in Whitney's Datadog org.

#647's criterion: after the talk on 2026-11-12, the burritobot-public data (APM spans and Agent Observability spans,
including the check's own wib-pii-scrub-check spans) is purged from Whitney's Datadog org, and the result is posted
on the issue. This test fails until both hold, and fails again if either stops holding:

1. A comment on #647 by hecaton or Michael passes verify/purge_647.py's `comment_verdict`: it pastes
   verify/dd_purge_public.py's `--apply` and `--verify` lines for a window from the first build day (2026-10-28) to
   after the talk ended (2026-11-12T21:20Z), names wib-pii-scrub-check, and says what APM count is left and how it
   goes. The comment's org is the one watch-it-burn/datadog names.
2. `dd_purge_public.py --verify` over that window, run now with the secret's read pair (GETs only), prints the Purged
   line, 0 Agent Observability spans and 0 APM spans under the cluster's tag, and the same again narrowed to
   `--service wib-pii-scrub-check`. APM has no delete API, so the APM half holds once retention has expired those
   spans or Datadog support has removed them; until then this check names the count left.

With no such comment yet, the second part still runs, over 2026-10-28 to now, so the output shows what is left.
Before the talk this test is red, as the criterion is not met yet: the purge is owed on or after 2026-11-13.
It reads and deletes nothing it was not asked to: `--verify` sends no deletion, and the write key is never read.

The offline half, verify/test_purge_647_record.py, holds both verdicts to the script's real output lines.

Run (after `. "$HECATON_CLUSTER_ENV"` in a dispatched run): python3 verify/test_dd_purge_public_live.py
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import dd_purge_public as p  # noqa: E402
import gh_comments  # noqa: E402
import purge_647 as purge  # noqa: E402

OWNER_REPO, _, NUMBER = purge.ISSUE.partition("#")
profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print(f"== a comment on {purge.ISSUE} records the post-talk purge ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, purge.ISSUE, check)
ours = [c for c in read.comments if c["login"] in purge.AUTHORS]
verdicts = [(c, purge.comment_verdict(c["body"])) for c in ours]
passing = [c for c, (ok, _) in verdicts if ok]
if read.ok:
    near = "; ".join(f"{c['url']}: {why}" for c, (_, why) in verdicts if purge.SCRIPT in purge.flat(c["body"]))
    check(f"a comment by {' or '.join(sorted(purge.AUTHORS))} pastes dd_purge_public.py's --apply and --verify lines "
          f"for a window from {purge.FIRST_BUILD.date()} to after {purge.TALK_END.isoformat()}", bool(passing),
          near or f"no comment of {len(ours)} by them names {purge.SCRIPT}; the purge is owed after the talk on "
                  "2026-11-12, per the run-of-show's Teardown step")
if passing:
    print(f"        recorded at {passing[0]['url']}: {purge.comment_verdict(passing[0]['body'])[1]}")
    frm, to, org = purge.window(passing[0]["body"])
else:
    frm, to, org = purge.FIRST_BUILD.isoformat(), dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), None

print(f"== nothing of burritobot-public is left in Whitney's org, {frm} to {to} ==")
try:
    secret = p.read_secret(profile, region)
    want = p.org_id(secret)
except (RuntimeError, OSError, ValueError) as e:
    print(f"FAIL: {e}")
    sys.exit(1)
if org:
    check("the comment's org is the one watch-it-burn/datadog names", org == want, f"{org} is not {want}")
for service in (None, purge.CHECK_SERVICE):
    out: list[str] = []
    args = ["--profile", profile, "--region", region, "--from", frm, "--to", to, "--verify"]
    rc = p.main(args + (["--service", service] if service else []), keys=lambda *_: dict(secret), say=out.append)
    print("        " + "\n        ".join(out))
    for name, ok, why in purge.verify_verdict("\n".join(out), rc, service):
        check(name, ok, why)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#647's purge holds: a comment on the issue records it, and no burritobot-public Agent Observability or APM "
      "span, the scrub check's included, is left in Whitney's org for the window it names.")
