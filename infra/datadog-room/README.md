<!-- ABOUTME: The room's read-only Datadog view for KubeCon NA 2026 (#665): what it shows, why it is fenced the -->
<!-- ABOUTME: way it is, how it is built in Whitney's sandbox org, and what is still owed. -->

# The room's view (burritobot-public)

The 2026-10-28 planning call (`facilitation/kubecon-na-2026-planning-2026-10-28.md`, Public console) asked for a
read-only Datadog view for the room, scoped to `burritobot-public`, once the PII question was settled. #647 settled
it: attackme's collector scrubs e-mails, card numbers, SSNs and phone numbers before export. The same decision
says no attendee gets a Datadog login, because Whitney's sandbox org holds `burritobot-private` and other
projects' data. This view needs no login. It is a public shared dashboard: anyone with the link can open it.

| File | What it is |
|---|---|
| `room_view.yaml` | The dashboard (Datadog API body) and the settings of its public share |
| `room_view.py` | The loader: dry run by default, `--json` for the UI, `--apply` writes, `--check` compares |
| `share.json` | Written by `--apply`: the dashboard id, the share token and the public URL. Commit it |

## What the room sees

Six widgets: a note saying what the page is, the number of chats, the number of tool calls the bot made, the
model bill so far, a top list of the tools the room talked the bot into calling, and chats per minute. The
window is the last hour. It refreshes about once a minute, which is Datadog's fixed rate for shared dashboards.

The room does not see individual traces or prompts. Datadog lists the widgets a shared dashboard renders
(docs.datadoghq.com/dashboards/sharing/shared_dashboards, read 2026-10-29). The List widget, which lists LLM
Observability spans (`llm_observability_stream`), is not on that list, and opening a trace needs the Datadog app.
So without a login the room gets counts, not traces. Traces are read on Whitney's projected `burritobot-public`
tab in segment 5. The prompts themselves are on the prompt wall.

## The fence

A shared dashboard runs its queries with its author's permissions, and Whitney can read the whole sandbox org. So
the only thing that keeps the page to attackme is the filter in each query. `room_view.py` refuses to load a
definition that breaks any of these rules:

- Every query is a metric query whose filter carries `kube_cluster_name:burritobot-public` and no other cluster.
  This tag is the only one that tells attackme apart from the presenters' cluster: the two share `env`, `ml_app` and
  every service name.
- No `ml_obs.*` metric. Datadog's LLM Observability metrics do not carry span tags ("Other tags set on spans are
  not available as tags on Agent Observability metrics", docs.datadoghq.com/llm_observability/monitoring/metrics,
  read 2026-10-29), so they cannot be limited to one cluster. The counts come from the collector's `span_metrics`
  connector (`traces.span.metrics.calls`), which keeps the resource attributes, the cluster name among them.
- Results are grouped by `span.name` only, never by a content attribute, so no attendee text reaches the page.
- Only widget types a shared dashboard renders (note, query value, timeseries, top list). Datadog accepts any other
  type without an error and then shows it empty.
- No template variables, and the share lets the viewer select neither a time nor a variable.
- The share is `open` and expires `2026-11-13T12:00:00Z`, the morning after the talk. The `burritobot-public` data
  is purged from Whitney's org after the talk (decisions.md, #647). Without an expiry Datadog keeps the link alive
  for a year.

## Building it

Only Whitney, or Michael signed in to her org, can build it. The application key in `watch-it-burn/datadog` is
read-only, and sharing a dashboard needs `dashboards_write` and `dashboards_public_share`. Whitney creates an
application key from her own user, so the share's author is her, and passes it for this one command:

```bash
python3 infra/datadog-room/room_view.py                                   # dry run, offline
WIB_ROOM_VIEW_APP_KEY=<key> python3 infra/datadog-room/room_view.py --profile accen-dev --region us-west-2 --apply
python3 infra/datadog-room/room_view.py --profile accen-dev --region us-west-2 --check   # read-only
```

`--apply` refuses any org whose name does not start with `WIB_DD_POOL_PREFIX` (default `Datadog`, as in
`verify/datadog-orgs.sh`). It prints the public URL and writes `share.json`; commit that file. A second `--apply`
updates the dashboard and the share in place, so the URL and its QR code stay the same.

Built by hand instead: `room_view.py --json > room-view.json`, then use Import dashboard JSON on a new dashboard.
Then choose Share, Share dashboard, Public. Set the time to Past 1 Hour and leave the time unselectable. Add no
variables, and set the expiry to 2026-11-13. Put the dashboard id, token and URL into `share.json` by hand, so that
`--check` can find them.

The QR code for the slide, with the same settings as the audience QR (`scripts/audience-qr.py`, segno 1.6.6 pinned
in decisions.md):

```bash
python3 -m venv /tmp/qr && /tmp/qr/bin/pip install segno==1.6.6
/tmp/qr/bin/python -c 'import json,segno; u=json.load(open("infra/datadog-room/share.json"))["public_url"]; segno.make(u, error="m", micro=False).save("facilitation/kubecon-na-2026-room-view-qr.svg", scale=10, border=4, dark="#000000", light="#ffffff", title=u)'
```

## Checked live

`verify/test_room_view_live.py` (run by `verify/run-e2e.sh`) runs `--check`. It confirms that the dashboard holds
these queries, and that the share is open, active, unselectable and expiring. It also fetches the public URL with
no credentials. Things only a live org can show, which a reader of the page should check once it is built:

- Each widget shows data after a prompt to `https://attackme.burritobot.co`. The cluster tag on
  `traces.span.metrics.calls` and `gen_ai.client.cost` is what the fleet dashboard already uses, but it has not
  been read in the sandbox org.
- `burritobot-private` traffic does not move any number. Send a prompt to the private bot and confirm the counts
  stay still.
