# Fleet analytics: what attendees actually did, across every cluster

Issue #150. Every other signal in this repo is per attendee, so a student can watch their own workload. This
is the instructor's side: one view across the whole attendee pool, readable live during the session and
again afterwards. It is the "did" half that `feedback-agenticburn`'s "said" half joins against.

> **Attendees are told.** The markers are on with the disclosure Michael approved on question 753
> (2026-10-25, `decisions.md`). On question 693 he had kept them off until that wording existed. It is in
> the BurritoBot warning on the lab page (`lab.html`), after the sentence about the instructor screen:
>
> "The lab also records which steps, hints and commands you open (never what you type), and the instructors keep your prompts after the workshop to improve it."
>
> `verify/test_lab_events.py` fails if the markers are on without that sentence, so the switch and the
> wording change together.

## Which question is answered where

| Question | Live (instructor dashboard) | After the event (harvest pass 6) |
|---|---|---|
| How far did people get? | "Fix installed, by attendee" grid, C1 to C8 | `LAB-PROGRESS.md` funnel and "Furthest fix installed" |
| Which challenges were opened, attempted, fixed, abandoned? | "Challenge opened" grid, opens and fixes over time | per-challenge funnel: opened, hint, prompt, fixed |
| Where did they get stuck, and for how long? | hints and prompts revealed, by challenge and by attendee | median minutes from opening a challenge to its fix being measured on |
| Which challenges were solved quickly, which never? | fixes-over-time against opens-over-time | the same funnel; `lab-progress.csv` per attendee |
| What did attendees ask their agents? What did the guardrails catch? | messages per cluster; guard-proxy catches by cluster and guard | passes 1 and 5 (prompts, kept out of git) |
| Unused clusters, or claimed and abandoned in ten minutes? | labs open now / ever opened / clusters running | "Never opened the lab" and "Left within 10 minutes" |
| Did the fork bomb get triggered, and by how many? | "Fork bomb triggered, by cluster" (Falco logs) | pass 3 (Falco) |

## How the data gets there

```
lab page (lab-events.js) --POST /lab-events--> console nginx --> collector otlp/lab :4319
    --> traces/lab: filter/lab_contract, transform/lab_contract, resource
        --> instructor org (spans, and witb.lab.calls via span_metrics/lab)
```

- **The emitter** is `gitops/ai-layer/web/lab-events.js`, loaded by `lab.html`. Each event is a zero-length
  OTLP span named `lab.<event>`: `session.start`, `heartbeat` (once a minute while the tab is visible),
  `step.open`, `hint.open`, `command.send`, `feedback.open`, `control.installed` and `control.removed`.
- **"Fixed" is measured, not reported.** The page polls BurritoBot's `/controls`, the same source as the
  badge strip, and emits `lab.control.installed` when a challenge's control is measured ON: the C1
  NetworkPolicy, C2 Kyverno in Enforce, C3 KubeArmor, the C4 to C6 guard-proxy switches, the C7 tool
  allow-list and the C8 scoped Role. Falco is left out because it is always on.
- **The route** is `location = /lab-events` in `gitops/ai-layer/console.conf`. It accepts POST only, caps
  the body at 16k, is rate-capped, and resolves the collector when a request arrives. A cluster without a
  collector answers 502 on that one route, and the console still starts.
- **The collector does not trust the page.** The route is public, so `otlp/lab` feeds a pipeline of its
  own. That pipeline drops any span not named `lab.*` and drops span events. It resets the resource to
  `service.name=burritobot-lab`, keeps only the documented attributes, and truncates their values to 64
  characters. A modified page cannot use it to forge BurritoBot traces or send anything wider.
- **Where it lands.** The two lab pipelines are in the collector's base config (`relay.yaml`, from
  `gitops/otel-collector/values.yaml`) and export to `debug` only. So a cluster with no `datadog-secret`
  receives the markers and drops them. The Datadog overlay that the `datadog-gate` loads when the secret
  exists (#500) adds the org, the same way it does for traces and metrics:
  - On attendee clusters, `values-dual.yaml` adds `datadog/admin` only, so the markers reach the
    instructor org (#242) and never the student's own. The student's org is for the student's workload,
    and one more unfamiliar service there is noise. A presenter's student cluster is a claimed attendee
    cluster since #295, so the same applies to it.
  - On instructor clusters (admin and full), `datadog` already is the instructor org.
  - On the Community cluster (burn), `datadog` is that cluster's org. The room shares that cluster, so
    the dashboard leaves it out by default.
- **Metrics, not just spans**, because indexed spans are sampled and a two-hour session needs every
  event. `span_metrics/lab` turns the spans into `witb.lab.calls`, tagged with `span.name`,
  `kube_cluster_name`, `witb.lab.alias`, `witb.lab.role`, `witb.lab.challenge`, `witb.lab.kind` and
  `witb.lab.control`. `session.id` is kept on the span but is not a metric tag, because one series per
  browser tab would be cardinality for nothing.

## What is collected, and what is not

Sent: the event name; `session.id`, random per browser tab; `witb.lab.alias`, the friendly cluster name
the student was given; `witb.lab.role`; the challenge number; the position of the hint or command block
within its step (`witb.lab.item`); and whether that was a hint or the "try this prompt" reveal, or whether
the command went to the terminal or the chat (`witb.lab.kind`).

Never sent: anything the student typed; the text of a command block (two of them are the student's Datadog
login); the e-mail, since `?user=` is never passed to the emitter; the query string; the client address,
since the route forwards none; hover, mouse or scroll tracking. A browser sending Global Privacy Control or
Do Not Track sends nothing at all. `verify/test_lab_events.py` and `verify/test_lab_events_behaviour.py`
assert each of these.

**The switch:** `var ENABLED = …;` at the top of `lab-events.js`. It is `true` (question 753). With it set to
`false` the page sends nothing and the pipeline is idle. The tests arm it in their harness, so the sending
code stays tested whichever way it is set. Turning it off needs no change to the warning, but the warning
would then claim more than is collected, so remove the sentence in the same commit.

## Joining with the feedback app

The join key is the friendly cluster name: `witb.lab.alias` in the instructor org, the `alias` column of
`lab-progress.csv`, and the `cluster` value the feedback app records from the lab's Feedback links (`?cluster=`,
#383). A feedback response marked **anonymous** carries no cluster and is never joined back to a row here.
That is by construction, and nothing in this path tries to recover it.

## The dashboard

`infra/terraform/dashboards/fleet-analytics.json`, managed by the `fleet_analytics` resource in
`infra/terraform/dashboards/main.tf`. Apply it with the **instructor org's** `DD_API_KEY` and `DD_APP_KEY`.
In a student's org it renders empty by design. The `cluster` template variable defaults to
`watch-it-burn-attendee-*`; set it to `*` to include the Community and admin clusters. A presenter's student
cluster is a claimed attendee slot (#295), so it is inside the default scope. Scope by
cluster name, not by `role`. The lab infers its role from the hostname, so an admin cluster's lab opened
without `?role=` reports itself as a student.

## After the event

`scripts/harvest/run.sh <event>` now runs pass 6, `06-lab-progress.py`. It reads the instructor org with
`WITB_DD_ADMIN_API_KEY` and `WITB_DD_ADMIN_APP_KEY`, and the window from `WIB_FROM`/`WIB_TO` (default: the
last 12 hours). It writes `LAB-PROGRESS.md` (aggregate), `lab-progress.csv` (one row per attendee cluster,
for the join) and `raw/lab-progress.json` under the gitignored `.harvest/<event>/`. Unlike passes 1 to 3 it
does not need the clusters to still be up.

## Prompt content

The dashboard carries no prompt text. Separately from this path, attendee clusters
dual-ship their traces to the instructor org (#242). Those traces include the conversation
(`gen_ai.input.messages`), so prompt text is already in the instructor org's Agent Observability, and
harvest pass 1 extracts it into `.harvest/`. The lab guide tells attendees both things: that their prompts
may be shown on the instructor screen during the workshop, and, since question 753, that the instructors
keep them afterwards to improve the workshop. The same sentence tells them which lab actions are recorded.

## Validating on a cluster

What is checked without a cluster:

- `verify/test_lab_events.py` and `verify/test_lab_progress_harvest.py` (offline) check the contract
  across the five files and the harvest reducer.
- `verify/test_lab_events_behaviour.py` (E2E, node) runs the emitter against a fake lab page.
- `verify/test_lab_pipeline_collector.py` (E2E, otelcol-contrib 0.160.0) validates every profile's collector
  config (instructor, attendee and burn, each with and without `datadog-secret`, rendered by
  `verify/collector_render.py`) with the real binary. It then feeds the lab pipeline the page's own
  payload and a forged one, and asserts that only the contract comes out.
- On 2026-10-24 the console's nginx config was also run under nginx 1.26 (Debian 13), with the
  cluster-local upstreams pointed at loopback, in front of that collector pipeline. `nginx -t` passed. A
  real payload answered 200 and arrived as spans. A GET answered 403, a 20k body 413, and a burst of 40
  requests 20 × 200 then 429.

What has not been run against a live cluster or the instructor org yet:

1. After sync, `kubectl --context "$CONTEXT" -n monitoring get svc otel-collector-opentelemetry-collector`
   lists port 4319, and the collector pods are Running. A config the collector rejects CrashLoops it.
2. Open `https://<alias>.agenticburn.com/lab`, expand a challenge and open a hint. In the browser's network
   tab, `POST /lab-events` answers 200 within ten seconds.
3. In the instructor org, `witb.lab.calls` appears by `kube_cluster_name` and `span.name` within about a
   minute, and nothing named `burritobot-lab` appears in the student's own org.
4. Apply the dashboard and confirm every widget renders. The log widgets assume guard-proxy's JSON `event`
   field and Falco's JSON `rule` field are parsed as `@event` and `@rule`.
