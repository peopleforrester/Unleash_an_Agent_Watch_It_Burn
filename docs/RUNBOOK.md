<!-- ABOUTME: One line per fleet operation, naming the command. No prose, no context: this is the page -->
<!-- ABOUTME: you open when you need to do something and do not want to read anything first. -->
# Runbook

Every operation, the command that does it. If something here needs an agent, it is a bug (see #397).

## Fleet

| Task | Command |
|---|---|
| Build N clusters | `WIB_APPLY=1 fleet.sh up <n>` |
| Build across all accounts | `WIB_APPLY=1 fleet.sh up-fleet <n>` |
| Tear everything down | `WIB_APPLY=1 fleet.sh down all` |
| Tear down, keep networking for a fast rebuild | `WIB_KEEP_VPC=1 WIB_APPLY=1 fleet.sh down all` |
| Tear down named clusters | `WIB_APPLY=1 fleet.sh down <name>...` |
| Destroy only the lab VPCs | `WIB_APPLY=1 fleet.sh down-infra [accounts]` |
| Delete our Secrets Manager entries | `WIB_APPLY=1 fleet.sh reap-secrets [accounts]` |
| Delete attendee IAM users whose cluster is gone | `WIB_APPLY=1 fleet.sh reap-iam-users [accounts]` |
| Repair drifted live state | `WIB_APPLY=1 fleet.sh converge` |
| Republish the routing table | `fleet.sh routes` |

`down all` includes the tag audit, per-cluster log groups, orphaned security groups, the attendee IAM
users and their access keys, the lab VPCs and a final audit. `teardown/teardown.sh` is a wrapper over it and adds nothing.

Secrets are NOT reaped by `down all`, on purpose: the Datadog pool is what the next `up` provisions
against.

## Checks

| Question | Command |
|---|---|
| Is anything of ours still running, anywhere? | `verify/account-audit.sh [--all-regions]` |
| Is anything billable left? (narrower, faster) | `fleet.sh audit-zero` |
| What is behind its latest GA? | `python3 verify/version-drift.py` |
| Does the platform still work end to end? | `verify/run-all.sh` |
| Do the challenges still land? | `python3 verify/agent_probe.py <host> --context <ctx>` |
| Are the Datadog orgs current and unexpired? | `verify/datadog-orgs.sh --pool` |

## After an event

| Task | Command |
|---|---|
| Capture everything before teardown | `scripts/harvest/run.sh <event-name>` |

Run it while the clusters are UP. Most of it reads live cluster state and none of that is recoverable
afterwards. Output lands in `.harvest/<event>/`, which is gitignored because it holds attendee-typed
text; the code is tracked.

## Scheduled

| Task | Command |
|---|---|
| Build at a set time | `scheduled-up.sh <attendees>` via cron (builds a pool of attendees + 2) |
| Tear down at a set time | `scheduled-down.sh` via cron |

The pool is always the attendee count plus two: Michael and Whitney each claim a pool cluster by email,
as an attendee does (#295). `scheduled-up.sh` adds the two (`WIB_SCHED_PRESENTER_SEATS`, default 2);
`scale <n>` and `up-fleet <n>` do not, so pass `attendees + 2` to `scale`, and to `up-fleet` the
per-account count `ceil((attendees + 2) / accounts)`.

Cron runs in the machine's local timezone, which on this box is Europe/Berlin and is neither UTC nor
event time. Compute the fields rather than doing the arithmetic in your head.
