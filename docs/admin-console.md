<!-- ABOUTME: The admin console (#268): fleet health and per-cluster restarts from the provisioning app's -->
<!-- ABOUTME: admin page, run by `fleet.sh serve-actions`. The runner's behaviour and the app's HTTP contract. -->

# Admin console: fleet health and per-cluster actions

A presenter (Whitney, Michael) can check every cluster's health and restart part of one from the
provisioning app's admin page without kubectl or AWS credentials. The app runs on Railway and has no AWS
credentials, so it never touches a cluster. It **queues** the action and keeps the record. A runner on a
host that already holds the fleet profiles **executes** it with `fleet.sh`. That host is a presenter laptop
by default; netcup stays out of the path. No new credential exists anywhere: the runner uses the
provisioning admin token `fleet.sh` already resolves for `ingest`. Decided as question 629 in
`decisions.md`.

```
admin page ──POST /admin/actions──▶ provisioning app (queue + audit) ◀──poll / claim / result── fleet.sh serve-actions ──▶ EKS
                                            ▲                                                         │
                                            └──────────── POST /admin/health (walkthrough report) ◀───┘
```

## Running the runner

```
infra/terraform/fleet/fleet.sh serve-actions          # loop for the length of the workshop
infra/terraform/fleet/fleet.sh serve-actions --once   # one health report and one pass over the queue
```

Start it before the doors open and leave it up. While it is down, actions stay pending and the health
report ages, and the page shows both (below). Tuning: `WIB_ACTIONS_POLL` (queue poll, default 10 s),
`WIB_ACTIONS_HEALTH_EVERY` (health report, default 300 s), `WIB_RESTART_WAIT` (how long a restart waits
for a Ready replacement, default 180 s). It needs `curl`, `python3`, `aws` and `kubectl`, plus `terraform`
for `converge`.

## The actions

Each action is a `fleet.sh` verb, and the runner runs nothing outside this list (`ADMIN_ACTIONS`). A
queued name, cluster or id it does not recognise is answered as `failed` and not run. So is a cluster with
no Terraform state on the runner, because the fleet did not provision it.

| Action | Verb | What it does |
|---|---|---|
| `restart-agent` | `fleet.sh restart-agent <name>` | Deletes BurritoBot's pod (`app.kubernetes.io/name=workshop-agent`, ns `agent`) and waits for a Ready replacement. |
| `restart-console` | `fleet.sh restart-console <name>` | The same for the console pod (`app.kubernetes.io/name=console`). |
| `converge` | `fleet.sh converge <name>` | The existing repair loop: hard-refresh unhealthy Argo apps, run the repairs, and wait for the console endpoint to answer 200. |
| `terminal-password` | `fleet.sh terminal-password <name>` | Rewrites `terminal-auth` with the credential the cluster's role is handed (`terminal_creds_for`), then restarts the terminal so ttyd reads it. This restores the expected login. It does not mint a new one, because the access page every student reads shows the role's credential. |

Restarts are pod deletes, never `kubectl rollout restart`. A rollout restart is a Deployment UPDATE, which
`block-argocd-drift` denies for any principal other than Argo CD, kagent, a system account or
system:masters. A pod DELETE is matched by neither admission policy, and the Deployment recreates the pod
from the spec Argo CD owns. Before every mutation the runner checks that the kubeconfig's context is the
named cluster, and refuses if it is not.

## The health report

`fleet.sh verify all` (`verify/fleet-walkthrough.sh --json`) writes the report the page shows. Each row
covers one cluster:

```json
{"cluster": "watch-it-burn-attendee-007", "host": "...agenticburn.com", "status": "ok|fail",
 "issues": ["argo=36/38", "agent-not-ready"],
 "console_http": 200,
 "argo": {"synced_healthy": 36, "total": 38},
 "agent_ready": true,
 "last_trace": "2026-10-24T16:05:00+00:00"}
```

The top level carries `generated`, `clusters`, `healthy`, `failed` and `last_trace_error`. `null` in a
column means unknown: the cluster was unreachable, or (for `last_trace`) no span arrived in the last 24
hours. An idle cluster outside a session is a correct cluster, so a missing trace is not an issue.
`last_trace` comes from one query to the instructor Datadog org, which every cluster dual-ships to
(`verify/last_trace.py`). When that query fails, `last_trace_error` says why, and the page should show the
column as unknown, not as silent.

## HTTP contract for the provisioning app

The app implements every route below. All of them take the admin token the existing admin routes take
(`X-Admin-Token` header, or `?token=` on the page), and refuse without it (403). The runner side is
`fleet.sh` (`_prov_call`, `run_admin_action`, `post_fleet_health`). `verify/test_admin_actions.sh` holds
the runner to this contract.

| Route | Called by | Body / answer |
|---|---|---|
| `POST /admin/actions` | the admin page | `{"cluster", "action", "requested_by"}`. Stores a pending action with an id and `requested_at`. `requested_by` is required and must be one of the app's admin emails: the token is shared, so it cannot tell one presenter from another, and the person has to be named. |
| `GET /admin/actions?status=pending` | runner, every poll | `200 {"actions": [{"id", "action", "cluster", "requested_by", "requested_at"}]}`, oldest first. |
| `POST /admin/actions/<id>/claim` | runner, before running | `200` when the action moved from pending to running in one atomic update, `409` otherwise. A second runner, or the same runner restarted, never runs an action twice. |
| `POST /admin/actions/<id>/result` | runner, after running | `{"status": "done"\|"failed", "exit_code", "output" (last 4000 bytes), "runner" (hostname), "finished_at"}` → `200`. |
| `POST /admin/health` | runner, every health interval | The health report above, stored as the latest → `200`. |

**The audit line.** The app keeps one record per action: who (`requested_by`), what (`action`, `cluster`),
when (`requested_at`, then `finished_at`), the outcome (`status`, `exit_code`) and where it ran (`runner`).
The admin page lists them newest first, so two presenters acting on the same fleet can each see what the
other did. The runner also appends a local line to `infra/terraform/fleet/logs/admin-actions.tsv` (when,
id, who, action, cluster, exit code), which survives the app being unreachable.

**What the page shows.** One row per cluster from the latest health report, with the four columns above,
each row's actions, and the age of the report. It also shows the oldest pending action's age. A report
older than three health intervals, or an action pending for more than a minute, means the runner is not
up, and the page should say so instead of looking calm.
