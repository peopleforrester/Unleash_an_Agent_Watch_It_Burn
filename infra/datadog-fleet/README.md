<!-- ABOUTME: What watches the fleet during the workshop: the instructor-org monitors and dashboard, how -->
<!-- ABOUTME: they are loaded, and what each one means when it fires (#267). -->

# Fleet monitoring (instructor Datadog org)

"How do I know if a student cluster suddenly fails?" Before #267 the honest answer was that a student
raised a hand. Every cluster already shipped its telemetry to the instructor org (dual shipping, #242);
nothing looked at it. These files are what looks.

| File | What it is |
|---|---|
| `monitors.yaml` | Six monitors, each one alert group per `kube_cluster_name` |
| `dashboard.yaml` | The fleet dashboard: one row per cluster, plus the alert list and the room's spend |
| `leaderboard.yaml` | The challenge leaderboard (#307): one row per cluster, one green cell per challenge done |
| `fleet_monitors.py` | The loader. Dry run by default, `--apply` writes, `--check` compares the live org |

## Loading

```bash
infra/terraform/fleet/fleet.sh monitors                                   # dry run, offline
infra/terraform/fleet/fleet.sh monitors --apply --session 2026-09-08T16:00Z/2026-09-08T19:30Z
infra/terraform/fleet/fleet.sh monitors --check                           # read-only
```

It follows the Datadog pool loader's pattern (#256): `--apply` reads the instructor org keys from Secrets Manager
`watch-it-burn/datadog`, asks Datadog to validate every monitor, and writes nothing if any one is
rejected. Monitors are matched by their `wib-monitor:<key>` tag and updated in place, a monitor removed
from the file is deleted, and the dashboard is matched by title, so its URL is stable within an org. Every
event brings a new instructor org, so run `--apply` once per event, after the pool is loaded.

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

`no-traces` is the only session-scoped monitor: outside the session an idle cluster is a healthy one. The
loader mutes it with downtimes until `--session` START and again from END (and indefinitely when no
window is given), and cancels its own previous downtimes on every apply.

A cluster torn down on purpose fires `cluster-silent` once. Resolve it from the monitor page.

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
| 3 recipe | Falco's `Recipe Snoop In Agent Namespace` alert (never on the Community cluster: no Falco) |
| 4 bill (USD) | not a tick: the cluster's `gen_ai.client.cost`, with the room's top ten beside the table |
| 5 guarded | guard-proxy `output_scrub`: the output guard is installed and redacted a reply |
| 6 blocked | guard-proxy `input_blocklist_hit` or `input_classifier_block`: the input guard refused a prompt |

Columns 1 to 3 go green when the attack lands, 5 and 6 when the fix is in and the attack has been run again
against it. Challenges 7 and 8 have no column: the rogue tool server writes no logs on purpose (#18), and
Challenge 8 goes around everything that records, which is what it teaches. Column 1 counts the call
reaching the tool; `provisioning.agenticburn.com/beacon/view` stays the count of POSTs that landed, and it
cannot say from which cluster.

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
  which is a separate repo. Until it has a handle, the link is the `fleet dashboard:` URL the apply prints.
- The per-attendee orgs get none of this; each student's org sees only their own cluster.
