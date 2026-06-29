# Beacon collector — build spec (for the provisioning app)

Hand this to the provisioning agent. Goal: make `/beacon` a **stateful collector** so we can see the
Challenge-1 exfil posts (a live count + recent payloads) instead of a black-hole 200. This is the
"watch the data leave the building" room view Whitney asked for.

## What exists today
`agenticburn.com/beacon` is currently a **static Caddy 200-responder** on the apex router. It accepts the
POST and replies, but stores and shows nothing. We are replacing that black hole with a real collector
that lives in the **provisioning app** (it already has a DB + a `/data` volume and deploys from GitHub
main).

## Routes to add (on the provisioning service)

### 1. `POST /beacon` — ingest
- Accept **any** body (it is the exfiltrated marketing JSON; treat as arbitrary text/JSON, do NOT
  validate a schema).
- Append a record to durable storage on the existing `/data` volume (survives redeploys): a SQLite
  table `beacons` or an appended JSONL file. Fields:
  `{ ts: <iso8601 UTC>, remote_ip: <request source IP>, bytes: <len of body>, body: <raw, truncated to ~4 KB> }`
- Increment a running total counter.
- **Return HTTP 200 with this EXACT body** (the lab text and the in-cluster `curl` expect it):
  ```
  beacon received by the agenticburn status collector (HC-204 OK)
  ```
- No CORS needed — the POST is a server-to-server in-cluster `curl`, not a browser.

### 2. `GET /beacon/view` — the room view
- Render a simple HTML page: a **big total count**, then a table of the **last ~50 beacons**
  (ts, remote_ip, byte size, body snippet).
- Auto-refresh ~5s (`<meta http-equiv="refresh" content="5">` is fine) so the room watches them arrive
  live. Keep it readable on a projector.

### 3. (optional) `POST /beacon/reset` or a button on the view
- Clear the records + counter between rehearsal runs.

## Notes
- **Storage** goes under the same `/data` volume the provisioning app already mounts.
- **Pedagogy:** the egress NetworkPolicy blocks the beacon from R2/R3 clusters, so **only R1 posts
  actually arrive**. The view will show R1 exfils landing and R2/R3 exfils NOT landing (blocked) — a live
  "leaked in round 1, blocked in round 2" picture.

## The one apex hand-off (Michael's side, not provisioning's)
`agenticburn.com/beacon` is intercepted by the apex Caddy router today. Once `/beacon` + `/beacon/view`
are live on the provisioning service, **tell Michael** and he will repoint apex so
`agenticburn.com/beacon` and `/beacon/view` `reverse_proxy` into the provisioning app (same pattern apex
already uses for `provisioning` / `rounds` / `feedback`). The provisioning agent does NOT need to touch
apex — just build the two routes and report the path.
