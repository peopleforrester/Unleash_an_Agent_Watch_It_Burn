<!-- ABOUTME: What watches the fleet during the workshop: the instructor-org monitors and dashboard, how -->
<!-- ABOUTME: they are loaded, and what each one means when it fires (#267). -->

# Fleet monitoring (instructor Datadog org)

"How do I know if a student cluster suddenly fails?" Before #267 the honest answer was that a student
raised a hand. Every cluster already shipped its telemetry to the instructor org (dual shipping, #242);
nothing looked at it. These files are what looks.

| File | What it is |
|---|---|
| `monitors.yaml` | Seven monitors: six with one alert group per `kube_cluster_name`, and one for the whole org on Agent Observability's own count |
| `dashboard.yaml` | The fleet dashboard: one row per cluster, plus the alert list and the room's spend |
| `leaderboard.yaml` | The challenge leaderboard (#307): one row per cluster, one green cell per challenge done |
| `fleet_monitors.py` | The loader. Dry run by default, `--apply` writes, `--check` compares the live org, `--data` checks every query answers, `--board` checks every leaderboard column fills |

## Loading

```bash
infra/terraform/fleet/fleet.sh monitors                                   # dry run, offline
WIB_FLEET_MONITORS_APP_KEY=<key> \
  infra/terraform/fleet/fleet.sh monitors --apply --session 2026-09-08T16:00Z/2026-09-08T19:30Z
infra/terraform/fleet/fleet.sh monitors --check                           # read-only
infra/terraform/fleet/fleet.sh monitors --data \
  --cluster burritobot-public --cluster burritobot-private                # read-only, after a /chat on each
infra/terraform/fleet/fleet.sh monitors --board \
  --cluster burritobot-private                                            # read-only, after challenges 1 to 6
```

`--check` says the org holds what the repo defines; `--data` says it is fed (#706). It fails on any blank:
a monitor that fires on absence must have a group for every `--cluster` in a state other than No Data, a
monitor that fires on a rising count (empty when healthy) must have its `signal` answer for every cluster, and
every query on the fleet dashboard must answer for every cluster over its widget's window. A blank is a wrong
name, a cluster that is not shipping, or, for traces and spend, no /chat on that cluster inside the window.
The leaderboard is left out: its cells are blank until the room plays. `--board` is its check.

It follows the Datadog pool loader's pattern (#256): `--apply` reads the instructor org's API key from Secrets
Manager `watch-it-burn/datadog`, asks Datadog to validate every monitor, and writes nothing if any one is
rejected. Monitors are matched by their `wib-monitor:<key>` tag and updated in place, a monitor removed
from the file is deleted, and the dashboard is matched by title, so its URL is stable within an org. Run
`--apply` once per event, against that event's instructor org.

For KubeCon NA 2026 the instructor org is Whitney's sandbox org: Datadog no longer issues per-student orgs, so
both clusters ship there (#629). The application key in `watch-it-burn/datadog` is read-only, which is all
`--check` needs, so `--apply` takes its application key from `WIB_FLEET_MONITORS_APP_KEY`: an unscoped key
Whitney issues from her own user (Datadog refuses log monitors created with a scoped one). Both modes refuse an
org whose name does not start with `WIB_DD_POOL_PREFIX` (default `Datadog`, as `verify/datadog-orgs.sh` uses).

`--notify @handle` (repeatable) adds a Datadog notification handle to every monitor. Without it the
monitors still change state on the dashboard and the Monitors page, but they page nobody.

## The monitors

| Key | Fires when | What the student sees |
|---|---|---|
| `cluster-silent` | `datadog.agent.running` is absent or zero for 5 min | Possibly nothing yet; the cluster is gone from view |
| `console-unavailable` | the `console` Deployment has no available replica for 5 min | A 502 on their link |
| `burritobot-not-ready` | the `workshop-agent` Deployment (kagent) has no ready pod for 5 min | Every chat fails |
| `guard-proxy-erroring` | more than 2 guard-proxy error logs in 5 min | "BurritoBot's kitchen isn't answering" |
| `node-not-ready` | a node reports Ready false/unknown for 5 min | Pods stop scheduling, then everything above |
| `no-traces` | no span reaches the collector for 10 min, **during the session only** | Idle, or a broken trace path |
| `agent-obs-silent` | Agent Observability files no `ml_app:burritobot` trace for 10 min, from any cluster, **during the session only** | Nothing; the presenters' Agent Observability tab is empty on stage |

`no-traces` and `agent-obs-silent` are the session-scoped monitors: outside the session an idle cluster is a
healthy one. The loader mutes them with downtimes until `--session` START and again from END (and indefinitely when no
window is given), and cancels its own previous downtimes on every apply.

A cluster torn down on purpose fires `cluster-silent` once. Resolve it from the monitor page.

### Agent Observability, for the whole org (#810)

`agent-obs-silent` watches `ml_obs.trace{ml_app:burritobot}`, Agent Observability's own count of the traces it
filed: one per BurritoBot turn. It exists because of #783: for six hours Agent Observability filed nothing while
APM kept every span, and `no-traces` stayed green, because the collector's span count is upstream of the
conversion that failed. Agent Observability's metrics carry `env`, `ml_app`, `service`, `version` and a few
more, never a span's `k8s.cluster.name` (Datadog's metrics page: "other tags set on spans are not available as
tags on Agent Observability metrics"), so this monitor cannot be per cluster. It is `scope: org`: one alert,
no cluster filter, no group. The loader allows that only on `ml_obs.*` (`ORG_SCOPE_METRICS` in
`fleet_monitors.py`), refuses an `ml_obs.*` monitor without it, and `--data` checks its overall state, one value
for the org, in place of a group per cluster.

What it cannot see: one cluster whose copy stops while the other's still arrives. That is what
`python3 verify/agent_obs_flow.py chat --profile accen-dev` answers, per cluster, before every run-through; the
alert's message names it.

## The challenge leaderboard

A projector view for the room, not a page each attendee opens: put it on the second screen once the
challenges start. The apply prints its URL as `challenge leaderboard:`; Datadog's TV mode on that URL is
the projector setting.

It lives here, not on the provisioning page, because the provisioning service knows email to cluster and
nothing else, and the clusters already ship everything a completion looks like to this org. No exercise
reports anything new for it. Rows are cluster names and nothing resolves them to a person, so nobody in
the room is publicly stuck on Challenge 1 (the same call as feedback-agenticburn#6).

| Column | Green when the instructor org has seen, in the last 4 hours |
|---|---|
| 1 exfil | a workshop-mcp tool audit line: `run_shell` with a command naming the beacon |
| 2 villain | any log line from a villain image on the roster in `images/villains/README.md` |
| 3 recipe | Falco's `Recipe Snoop In Agent Namespace` rule, counted by its `falco.rules.matches.count` metric, since Falco's log line arrives with no cluster tag (never on the Community cluster: no Falco) |
| 4 bill (USD) | not a tick: the cluster's `gen_ai.client.cost`, with the room's top ten beside the table |
| 5 guarded | a guard-proxy `/chat` span stamped `witb.guard.decision` `output_redacted`: the output guard is installed and redacted a reply |
| 6 blocked | guard-proxy `input_blocklist_hit` or `input_classifier_block`: the input guard refused a prompt |

Columns 1 to 3 go green when the attack lands, 5 and 6 when the fix is in and the attack has been run again
against it. Challenges 7 and 8 have no column: the rogue tool server writes no logs on purpose (#18), and
Challenge 8 goes around everything that records, which is what it teaches. Column 1 counts the call
reaching the tool; `https://beacon.burritobot.co/beacon/view` stays the count of POSTs that landed, and it
cannot say from which cluster.

### Every column fills (`--board`, #862)

Walk one cluster through challenges 1 to 6, then, within the board's 4 hours, run
`fleet.sh monitors --board --cluster <its kube_cluster_name>` (the live test is `verify/test_leaderboard_live.py`).
It is read-only and fails on any of three things. The board is not in the org. The org's table differs from
`leaderboard.yaml`: its window, a query's source, filter, aggregator or grouping, or a column's formula, title or
green rule. Or a cell is blank. It sends the table's whole request in one scalar query, every metrics, logs and
spans query with every formula, which is how the widget joins them on `kube_cluster_name`. A cell counts as filled
when it is green under its column's conditional format, or, for the bill, above 0. Name a cluster with Falco:
column 3 never fills on the Community cluster.

## Joined with the claims

The leaderboard never says who holds a cluster, on purpose. The presenter-side view that does is
`fleet.sh ops` (`infra/ops-view/`, #308): it sends the leaderboard's own queries and joins them with the
provisioning claims and each console's liveness, one row per cluster, for the instructor screen only.

## From outside

`verify/fleet-walkthrough.sh` (run by `fleet.sh verify`, and at the end of every `up` and `scale`) answers
the same question by walking what a student touches. The monitors are the continuous version of it, and
every alert names the `fleet.sh verify <cluster>` command for the cluster it is about.

## Not here yet

- `monitoring.agenticburn.com` lives in the apex router (`peopleforrester/apex-agenticburn`, Caddyfile),
  which is a separate repo. Since apex-agenticburn#34 it is a 302 to `WIB_MONITORING_URL` on the
  `watch-it-burn-apex` Railway service, and a 503 until that is set. The dashboard URL changes every event,
  so the apply prints the `railway variables --service watch-it-burn-apex --set WIB_MONITORING_URL='<url>'`
  command after the `fleet dashboard:` URL (#550). Running it stays a manual step, during event setup:
  changing a Railway variable redeploys the apex service and restarts the router.
- The per-attendee orgs get none of this; each student's org sees only their own cluster.
