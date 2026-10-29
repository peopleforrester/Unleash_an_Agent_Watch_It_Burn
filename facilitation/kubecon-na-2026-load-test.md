# KubeCon NA 2026: load test one public cluster at 500 users (#644)

Agreed on the 2026-10-28 planning call (`kubecon-na-2026-planning-2026-10-28.md`, "Resilience and load"):
load test one public cluster at 500 users by replaying the prompt traffic recorded at the last delivery.
This file holds the method and the results. The ballroom sizing it informs is #450.

## What is replayed

The last delivery is DevOpsDays Portland 2026 (talks-knowledge `talks/register.md`, section 2). Its prompts
are in the post-event harvest, `.harvest/devopsdays-portland/prompts/<cluster>.json`, which
`scripts/harvest/run.sh` pulled from each cluster's Datadog spans before teardown. `.harvest/` is gitignored
because it holds attendee-typed text, so the load test runs on the machine that holds the harvest.

`scripts/load-replay.py` reads every distinct prompt from it (each span's last user entry, earlier probes
dropped) and hands them to 500 virtual users. Each user is one browser session, starts somewhere in the
first 60 seconds, and sends 3 recorded prompts, reading each reply for 20 seconds before the next.
Neighbouring prompts from one recorded cluster go to the same user, so a user replays something close to one
attendee's conversation. Every prompt carries guard-proxy's probe marker, so the replayed Portland text never
reaches the side-screen feed or the prompt wall. The results name each prompt by an index and a hash, never
by its text, and keep no reply, so they can be committed.

## The run

Run it against one cluster built from the community row (the burn profile), with an explicit target. On a
cluster that the room will use, run `fleet.sh reset-bot` afterwards, so its cost counter and its `$25`
backstop start from zero again.

```
python3 scripts/load-replay.py --target https://<public-host> --dry-run
python3 scripts/load-replay.py --target https://<public-host>
./fleet.sh reset-bot <cluster>        # infra/terraform/fleet; then /cost reads $0 over 0 requests
```

New turns stop after 900 seconds, or once the replies have reported `$10` of spend (`--budget-usd`), which
is below the cluster's own `$25` backstop. The run writes `.harvest/load-<run id>/requests.jsonl`,
`summary.json` and `summary.md`. Paste `summary.md` under Results below.

## What the configuration predicts

These are the limits as deployed on `staging`. The run is what says which one gives out first.

- **guard-proxy's cluster window**, `RATE_LIMIT_RPM` 150 model-bound turns a minute
  (`gitops/ai-layer/resources.yaml`). 500 users offering a turn every 20 to 30 seconds is about 1,000 a
  minute, so most turns should come back as `cluster_limit` ("Slow down, hungry traveler.") and the served
  rate should sit at about 150 a minute.
- **Per conversation**, `RATE_LIMIT_SESSION_RPM` 10. At 3 turns a user it should never bite; a `session_limit`
  in the results means a session was shared.
- **The cost backstop**, `COST_CAP_USD` 25 for the whole cluster. The `$10` client budget keeps the run under it.
- **Bedrock**: two Nova Pro calls a turn, so 150 turns a minute is about 300 of the account's 500
  cross-region requests a minute (`verify/model_pin_check.py`). Throttling there shows as slow or empty
  replies, or guard-proxy's 502.
- **Timeouts**: console nginx gives `/chat` 160 seconds and guard-proxy gives the agent 150. A 504 is nginx
  giving up; the harness waits 170 seconds so it records that rather than its own timeout.
- **One guard-proxy pod** (`replicas: 1`) on Python's `ThreadingHTTPServer`, whose listen backlog is 5, and one
  LLM Guard pod when the input classifier is on. Under a burst these show as connection errors (502 from nginx)
  or as latency that grows faster than the window explains.

## Results

Not yet run. The first run needs a public cluster up, the Portland harvest, and Michael's go for the Bedrock
spend (at most `$10` by the budget). Record each run here, newest first, with the cluster, the date, and what
gave out first.
