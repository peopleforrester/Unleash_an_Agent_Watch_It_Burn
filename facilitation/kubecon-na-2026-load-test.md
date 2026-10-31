# KubeCon NA 2026: load test one public cluster at 500 users (#644)

Agreed on the 2026-10-28 planning call (`kubecon-na-2026-planning-2026-10-28.md`, "Resilience and load"):
load test one public cluster at 500 users by replaying the prompt traffic recorded at the last delivery.
This file holds the method, the limits the configuration predicts, and the results. The ballroom limits it
measures are #450's (run-of-show, "The audience path").

## What is replayed

The last delivery is DevOpsDays Portland 2026 (talks-knowledge `talks/register.md`, section 2). Its prompts
are in the post-event harvest, `.harvest/devopsdays-portland/prompts/<cluster>.json`, which
`scripts/harvest/run.sh` pulled from each cluster's Datadog spans before teardown. `.harvest/` is gitignored
because it holds attendee-typed text, so the load test runs on the machine that holds the harvest. On
2026-10-31 that harvest held 30 cluster files and 1,092 distinct prompts, 359 of them from attackme.

`scripts/load-replay.py` reads every distinct prompt from it (each span's last user entry, earlier probes
dropped) and hands them to 500 virtual users. Each user is one browser session, starts somewhere in the
first 60 seconds, and sends 3 recorded prompts, reading each reply for 20 seconds before the next. That is
1,500 turns, so the recording is used once and a third of it again. Neighbouring prompts from one recorded
cluster go to the same user, so a user replays something close to one attendee's conversation. Each turn
carries the session in its body and as `X-BurritoBot-Session`, as the storefront sends it. Every prompt
carries guard-proxy's probe marker, so the replayed Portland text never reaches the side-screen feed or the
prompt wall. The results name each prompt by an index and a hash, never by its text, and keep no reply, so
they can be committed.

## The runs

Run against one public cluster that is not serving a room: the community cluster, or one of attackme's
standbys from `infra/terraform/fleet/backups.tsv` (#643). Name the target explicitly; the harness has no
default. Afterwards run `fleet.sh reset-bot` on it, so its cost counter and its `$25` backstop start from
zero again.

**Run A, the venue NAT, through the public hostname.** Every user leaves this machine through its one public
address, as most of a ballroom leaves the venue Wi-Fi through one NAT address. This is the run the issue asks
for.

```
python3 scripts/load-replay.py --target https://<public-host> --dry-run
python3 scripts/load-replay.py --target https://<public-host>
./fleet.sh reset-bot <cluster>        # infra/terraform/fleet; then /cost reads $0 over 0 requests
```

**Run B, the cluster past the network ceiling, at the console's own load balancer.** The front door sends the
caller's address as the one `X-Forwarded-For`, so a caller cannot spread itself over networks through it.
Straight at the console NLB (`kubectl --context <ctx> -n agent get svc console`, port 80), `--networks 50`
gives each user one of 50 documentation addresses (RFC 5737), ten users to a network, which nginx keys its
ceiling on. That leaves guard-proxy's window and Bedrock as the limits.

```
python3 scripts/load-replay.py --target http://<console-nlb-hostname> --networks 50
./fleet.sh reset-bot <cluster>
```

New turns stop after 900 seconds, or once the replies have reported `$10` of spend (`--budget-usd`), which
is below the cluster's own `$25` backstop. Each run writes `.harvest/load-<run id>/requests.jsonl`,
`summary.json` and `summary.md`. Paste `summary.md` under Results below, with the cluster and the date.

## What the configuration predicts

These are the limits as deployed on `staging` on 2026-10-31. The runs are what say which one gives out first.

- **The console's nginx, per network**: 120 a minute per `X-Forwarded-For` address with burst 60
  (`gitops/ai-layer/console.conf`, `wib_chat_address`). Run A offers 1,500 turns in about two minutes from one
  address, so nginx should pass about 60 at once and then 2 a second, about 300 in all, and answer the other
  1,200 or so as `edge_limit` ("Slow down, hungry traveler. BurritoBot takes 10 a minute per conversation and
  120 a minute from one network"). In Run B each network offers 30 turns in two minutes, under its ceiling.
- **The console's nginx, per conversation**: 10 a minute per `X-Burritobot-Session` with burst 9. At 3 turns a
  user it should never bite. nginx's one reply covers both its zones, so `edge_limit` does not say which.
- **guard-proxy's cluster window**, `RATE_LIMIT_RPM` 150 model-bound turns a minute
  (`gitops/ai-layer/resources.yaml`). In Run A nginx's burst plus its first minute pass about 180, so about
  30 should come back `cluster_limit` ("... cap on this cluster") in the first minute, and after that the
  network ceiling (120) binds before the window does. In Run B the window is the limit: about 150 served a
  minute and most of the rest `cluster_limit`.
- **Per conversation in guard-proxy**, `RATE_LIMIT_SESSION_RPM` 10. Never at 3 turns; a `session_limit` means a
  session was shared.
- **The cost backstop**, `COST_CAP_USD` 25 for the whole cluster. Each run serves about 300 turns, at about half
  a cent a turn (`verify/test_audience_path_live.py`'s figure for one probe turn) about `$1.50`, so neither the
  `$10` client budget nor the backstop should bite.
- **Bedrock**: the cross-region quotas `verify/model_pin_check.py` holds against `RATE_LIMIT_RPM`. Throttling
  shows as slow or empty replies, or guard-proxy's 502 "kitchen isn't answering".
- **Timeouts**, outside in: Railway's edge 300 s with no data, the console nginx's `/chat` 285 s, guard-proxy's
  `TURN_TIMEOUT` 270 s for the whole turn. The harness waits 320 s, so it records the hop that gave up (nginx's
  504, or the edge's own error) rather than its own timeout.
- **One guard-proxy pod** (`replicas: 1`) on Python's `ThreadingHTTPServer`, whose listen backlog is 5, and one
  LLM Guard pod when the input classifier is on. Under a burst these show as connection errors (502 from nginx)
  or as latency that grows faster than the window explains.

## Results

Not yet run. Both runs need a public cluster up, the machine holding the Portland harvest, and Michael's go
for the Bedrock spend (about `$1.50` a run by the prediction, at most `$10` by the budget). Record each run
here, newest first, with the cluster, the date, and what gave out first.
