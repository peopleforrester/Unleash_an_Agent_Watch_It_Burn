# ABOUTME: The verdicts #1166's tests hold #647's post-talk purge to: a comment on #647 records the purge with
# ABOUTME: dd_purge_public.py's own lines, and a --verify of that window finds no Agent Observability or APM span left.
"""What "the burritobot-public data is purged from Whitney's Datadog org after the talk, and the result is posted on
#647" means, as two verdicts (#1166).

#647's criterion: after the talk on 2026-11-12, the burritobot-public data (APM spans and Agent Observability spans,
including the check's own wib-pii-scrub-check spans) is purged from Whitney's Datadog org, and the result is posted
on the issue. The purge is verify/dd_purge_public.py, run per the run-of-show's Teardown step. These verdicts read
that script's own output lines, so a comment that pastes them passes and a comment that paraphrases them does not.

`comment_verdict(body)` holds a comment on #647 to the record the Teardown step asks for:

- it names verify/dd_purge_public.py, and the `--apply` run's "Sent N deletion requests for M traces." line;
- it quotes the `--verify` run's "Window <from> to <to>, org <uuid>." line, and that window starts no later than
  2026-10-28, the first build day, and ends no earlier than the talk's end, 2026-11-12T21:20Z
  (conference-knowledge `kubecon-na-2026`: 13:50 MST, 30 minutes);
- it quotes the `--verify` run's "Purged: ..." line, so no Agent Observability span was left in that window;
- it names wib-pii-scrub-check, the scrub check's own service, so its spans are said to be covered;
- it quotes the "APM: N spans under kube_cluster_name:burritobot-public" line and says how those go (retention or
  Datadog support), since APM has no delete API.

`verify_verdict(out, rc, service)` holds a `--verify` run's output to the data being gone: exit 0, the "Purged:"
line, 0 Agent Observability spans and 0 APM spans under the cluster's query (narrowed to the service when one is
given). It returns named checks, so the live test prints each one.
"""
from __future__ import annotations

import datetime as dt
import re

ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#647"
# Who may record the purge on #647: the dispatcher that posts each run's report, and the repo's owner. gh issue view
# reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}
SCRIPT = "verify/dd_purge_public.py"
CHECK_SERVICE = "wib-pii-scrub-check"
FIRST_BUILD = dt.datetime(2026, 10, 28, tzinfo=dt.UTC)
TALK_END = dt.datetime(2026, 11, 12, 21, 20, tzinfo=dt.UTC)
LLMOBS_QUERY = "k8s.cluster.name:burritobot-public"
APM_QUERY = "kube_cluster_name:burritobot-public"
PURGED = "Purged: no Agent Observability span is left for the cluster in the window."

WINDOW = re.compile(r"Window (\S+) to (\S+), org ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.")
SENT = re.compile(r"Sent (\d+) deletion requests for (\d+) traces\.")
APM_LINE = re.compile(r"APM: (\d+) spans under " + re.escape(APM_QUERY) + r"(?: service:\S+)?;")
APM_FATE = re.compile(r"retention|Datadog support", re.I)


def flat(body: str) -> str:
    """The body with Markdown's backticks taken out and every run of whitespace one space, so a pasted line reads
    the same in a code block, in backticks or wrapped."""
    return re.sub(r"\s+", " ", body.replace("`", "")).strip()


def when(text: str) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else None


def window(body: str) -> tuple[str, str, str] | None:
    """The first "Window <from> to <to>, org <uuid>." line the comment quotes, as its three strings."""
    m = WINDOW.search(flat(body))
    return (m.group(1), m.group(2), m.group(3)) if m else None


def comment_verdict(body: str) -> tuple[bool, str]:
    text = flat(body)
    if SCRIPT not in text:
        return False, f"it does not name {SCRIPT}"
    if not SENT.search(text):
        return False, "it quotes no --apply line 'Sent N deletion requests for M traces.'"
    w = window(text)
    if not w:
        return False, "it quotes no --verify line 'Window <from> to <to>, org <uuid>.'"
    frm, to = when(w[0]), when(w[1])
    if not (frm and to):
        return False, f"its window {w[0]} to {w[1]} is not two zoned ISO times"
    if frm > FIRST_BUILD:
        return False, f"its window starts {w[0]}, after the first build day {FIRST_BUILD.date()}"
    if to < TALK_END:
        return False, f"its window ends {w[1]}, before the talk ended at {TALK_END.isoformat()}"
    if PURGED not in text:
        return False, f"it quotes no --verify line {PURGED!r}"
    if CHECK_SERVICE not in text:
        return False, f"it does not name {CHECK_SERVICE}, the scrub check's own spans"
    apm = APM_LINE.search(text)
    if not apm:
        return False, f"it quotes no line 'APM: N spans under {APM_QUERY}'"
    if not APM_FATE.search(text):
        return False, "it does not say whether the APM spans go to retention or to Datadog support"
    return True, (f"window {w[0]} to {w[1]}, {SENT.search(text).group(0)} Purged, "
                  f"APM {apm.group(1)} spans left, {CHECK_SERVICE} named")


def verify_verdict(out: str, rc: int, service: str | None = None) -> list[tuple[str, bool, str]]:
    """Named checks on one `dd_purge_public.py --verify` run: nothing of the cluster's (or the service's) is left."""
    llm = f"{LLMOBS_QUERY} service:{service}" if service else LLMOBS_QUERY
    apm = f"{APM_QUERY} service:{service}" if service else APM_QUERY
    tail = " (including its wib-pii-scrub-check spans)" if not service else ""
    left = re.search(r"Agent Observability: (\d+) spans in (\d+) traces under " + re.escape(llm) + r"\.", out)
    apm_left = re.search(r"APM: (\d+) spans under " + re.escape(apm) + ";", out)
    last = out.strip().splitlines()[-1] if out.strip() else f"no output, exit {rc}"
    return [
        (f"--verify under {llm} exits 0", rc == 0, last),
        (f"--verify under {llm} prints the Purged line", PURGED in out, last),
        (f"no Agent Observability span is left under {llm}{tail}", bool(left) and left.group(1) == "0",
         left.group(0) if left else "no 'Agent Observability: N spans' line"),
        (f"no APM span is left under {apm}", bool(apm_left) and apm_left.group(1) == "0",
         (apm_left.group(0) + " APM has no delete API: they go when retention expires them or Datadog support "
          "removes them") if apm_left else "no 'APM: N spans' line"),
    ]
