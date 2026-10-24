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

## From outside

`verify/fleet-walkthrough.sh` (run by `fleet.sh verify`, and at the end of every `up` and `scale`) answers
the same question by walking what a student touches. The monitors are the continuous version of it, and
every alert names the `fleet.sh verify <cluster>` command for the cluster it is about.

## Not here yet

- `monitoring.agenticburn.com` lives in the apex router (`peopleforrester/apex-agenticburn`, Caddyfile),
  which is a separate repo. Until it has a handle, the link is the `fleet dashboard:` URL the apply prints.
- The per-attendee orgs get none of this; each student's org sees only their own cluster.
