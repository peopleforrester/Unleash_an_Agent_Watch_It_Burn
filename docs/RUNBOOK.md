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
| Repair drifted live state | `WIB_APPLY=1 fleet.sh converge` |
| Republish the routing table | `fleet.sh routes` |

`down all` includes the tag audit, per-cluster log groups, orphaned security groups, the lab VPCs and a
final audit. `teardown/teardown.sh` is a wrapper over it and adds nothing.

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
| Build at a set time | `scheduled-up.sh <n>` via cron |
| Tear down at a set time | `scheduled-down.sh` via cron |

Cron runs in the machine's local timezone, which on this box is Europe/Berlin and is neither UTC nor
event time. Compute the fields rather than doing the arithmetic in your head.
