<!-- ABOUTME: The shared ops view (#308): one row per cluster with who claimed it, whether it is up, and which -->
<!-- ABOUTME: challenges it has done, joined from provisioning, the apex router and the instructor Datadog org. -->

# Ops view: who has it, is it up, where are they

A presenter's question in the middle of a workshop is one question about one cluster. Before #308 the answer
took three credentials and two URLs, and neither page could answer the other's half:

| Before | Answers | Cannot answer |
|---|---|---|
| provisioning `/admin/roster?token=` | who claimed which cluster, which seats are free | whether the cluster is up, what the attendee has done |
| `start.agenticburn.com` | which routed consoles answer `/cost` | who claimed one |
| the challenge leaderboard | which cluster did which challenge | who it is (by design: it is on the projector) |

`fleet.sh ops` joins the three into one table, by cluster name:

```bash
infra/terraform/fleet/fleet.sh ops                     # the table, plus logs/ops-view.html
infra/terraform/fleet/fleet.sh ops alice@ attendee-04  # only rows whose cluster, host or email matches every term
infra/terraform/fleet/fleet.sh ops --watch 30          # refresh every 30s; open the HTML, it reloads itself
infra/terraform/fleet/fleet.sh ops --json              # the joined rows, for anything else that wants them
```

Read-only: it reads every source and writes only its own HTML file. It lives in this repo because this repo is
the only part of the workshop that already talks to all three sources. Provisioning, the apex router and the
clusters each keep their own surface, and none of them is asked to read another's
(`provisioning-agenticburn/AGENTS.md`, Michael, 2026-09-03).

## Columns

| Column | Source | Notes |
|---|---|---|
| cluster | the public host, from `fleet.sh hosts` | the name the room hears (`attackme`, `michael-admin`, the two-word attendee names) |
| name | the cluster name | what claims and Datadog call it |
| claimed by | provisioning `GET /admin/export` | `-` unclaimed, `?` the claims could not be read |
| console | `start.agenticburn.com/roster.json`, then `GET https://<host>/cost` | the same probe the start page makes; `unrouted` means the router has no line for it |
| agent | instructor org, `datadog.agent.running` | `silent` means the org has not heard from the cluster in the window |
| 1 to 6 | instructor org, the leaderboard's own queries | `x` done, `.` not yet, `?` unknown; 4 is the bill in USD |
| needs attention | derived | a **claimed** cluster whose console is down or unrouted, or whose agent is silent. These rows sort first |

The progress columns are not defined here. `ops_view.py` reads `infra/datadog-fleet/leaderboard.yaml` and sends
each of its queries, unchanged, to Datadog's scalar query API over the board's own window, so the ops view and
the projector board cannot disagree about what "done" means. A column added to the board appears here with no
edit. The name table is `fleet.sh hosts`, which asks `public_host_for`, so this view joins on exactly the
hostnames the router publishes and holds no copy of the name grid.

## Credentials

| Source | Credential | How it is found |
|---|---|---|
| claims | the provisioning `ADMIN_TOKEN` | `resolve_admin_token`: `WIB_ADMIN_TOKEN`, else the Railway service, else `~/secrets` |
| liveness | none | `roster.json` and `/cost` are public |
| progress | the instructor org keys | Secrets Manager `watch-it-burn/datadog`, as `WIB_DEFAULT_ACCOUNT` in `WIB_REGION` |

The token reaches `ops_view.py` in its environment and never on its command line. It is sent only to
`/admin/export`, and no message, table or page prints it.

## When a source fails

The view still renders. The failed source is named at the top in red and its cells read `?`, never `-` or `.`:
a blank that reads as "unclaimed" or "not done" is the wrong answer in front of a room. A one-shot run exits 1
if any source failed, so a script can tell. `--watch` keeps polling and shows the error until it clears.

## Not for the projector

The table names attendees by email, so it is for the people running the room. The HTML is written mode 0600
under the gitignored `infra/terraform/fleet/logs/`. The projector view is the challenge leaderboard, which names
clusters and never people (#307).

## Known limits

- **Free seats are counted from the routing table.** `/admin/export` lists claimed rows only, so a seat is free
  here when an attendee cluster is routed and unclaimed. A seat provisioning holds back for one owner
  (`RESERVED_CLUSTERS`) counts as free here and not on `/admin/roster`. That page stays the authority for
  seats at the door; a JSON `/admin/roster` would close the gap, and provisioning has offered it (#308).
- It runs on a presenter's machine, not as a page on the web. Anyone running it needs the provisioning token
  and the AWS profile, as for every other `fleet.sh` verb.
