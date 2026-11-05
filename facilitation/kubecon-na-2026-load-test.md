# KubeCon NA 2026: the community bot at room scale (#644)

Agreed on the 2026-10-28 planning call (`kubecon-na-2026-planning-2026-10-28.md`): load test one public
cluster by replaying the last delivery's recorded prompts at 500 users. Michael's go of 2026-11-01 on #644
asks for a re-run after #450 drops nginx's per-network limit, at two sizes: 500 sessions, and 150, the room
he expects. This file holds the method, the plan for each run and the results. The Night Before step in
`kubecon-na-2026-run-of-show.md` runs the same harness.

## Method

`verify/load_replay.py` replays the DevOpsDays Portland 2026 harvest's attendee prompts
(`.harvest/devopsdays-portland/prompts/`, gitignored, so its path is passed with `--harvest`) at the public
host's `/chat`. Each user is its own session and sends it as `X-BurritoBot-Session`, as the storefront does.
Users start across a 60 s ramp and send 3 turns each, 15 to 45 s apart. Prompts go as recorded, with only
guard-proxy's probe marker `[[wib-probe]]` added, so they are answered but never reach the prompt wall.

Every send leaves from one machine, so every turn arrives from one address. That is the venue NAT case: on
venue Wi-Fi the whole ballroom shares one public address.

The harness stops new turns at `--max-calls`, after 900 s, or once `/cost` has risen $10. Without `--yes` it
prints the plan and the estimate and sends nothing. The report gives outcomes by limit, errors by HTTP status,
latency percentiles of served turns and the `/cost` spend. It ends `LOAD REPLAY GREEN` only when every turn,
served or refused, came back with a sentence a phone can read. A 502, 504, timeout or empty reply fails it.

## The limits in front of the model

| Limit | Where | Before #450 | After #450 |
|---|---|---|---|
| Per conversation | console nginx, `wib_chat_session` | 10 a minute, burst 9 | unchanged |
| Per network address | console nginx, `wib_chat_address` | 120 a minute, burst 60 | removed |
| Per session | guard-proxy, `RATE_LIMIT_SESSION_RPM` | 10 a minute | unchanged |
| Per cluster | guard-proxy, `RATE_LIMIT_RPM` | 150 a minute | unchanged |
| Cost backstop | guard-proxy, `COST_CAP_USD` | $25 | unchanged |
| Turn timeout | guard-proxy `PROXY_TIMEOUT` | 120 s | unchanged |

A replayed session sends 3 turns at least 15 s apart, so neither per-conversation limit is reached. Once
#450's change is live, guard-proxy's 150 a minute per cluster is the only limit a one-address room meets.

## The runs

Michael's go of 2026-11-01 waited on #450's per-person chat limit reaching watch-it-burn-community. #786 made
that change on staging, and it was live by 2026-11-03 (#789). Before the runs of 2026-11-05 the live console
carried only `wib_chat_session` (10 a minute, burst 9) on `/chat`, with no `wib_chat_address`, and Argo CD's
ai-layer was synced to staging `f4e1273`. guard-proxy ran `RATE_LIMIT_RPM` 150, `RATE_LIMIT_SESSION_RPM` 10,
`COST_CAP_USD` 25 and `PROXY_TIMEOUT` 120.

**Run A again: 500 sessions from one address, through the public hostname.**

```bash
python3 verify/load_replay.py attackme.burritobot.co --yes --users 500 --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts --json-out tmp/load-replay-attackme-500.json
```

**Run B: 150 sessions from one address, the expected room.**

```bash
python3 verify/load_replay.py attackme.burritobot.co --yes --users 150 --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts --json-out tmp/load-replay-attackme-150.json
```

After each run, read the guard-proxy and agent logs as the run-of-show's Night Before step says (#750), then
name the cause of every turn that did not come back as a readable sentence. The report lists each such turn
with the UTC time it was sent, its session and what answered it: `chat json, with a reply` is guard-proxy's or
the console nginx's own error body, `not chat json` is a hop in front of the console (the public host's Caddy or
Railway's edge, named by its Server and Via headers), and `client timeout` never got an answer.

The replayed prompts are the Portland room's, attacks included, so the bot deploys what they ask for. Clear it
afterwards. `./fleet.sh reset-bot watch-it-burn-community` does that as its first step.

## Results

### What limits a room

These are the limits, measured on 2026-11-05 with #450's change live, from one address, as on a venue NAT:

- **guard-proxy's 150 a minute per cluster is the only rate limit a room meets.** At 500 phones it refused
  1,153 of 1,500 turns (77 %). At 150 phones it refused 138 of 450 (31 %), all from about a minute in, once
  first and second turns overlap. Its refusal tells the phone to wait and send again.
- **The per-conversation limits were never reached.** nginx's `wib_chat_session` and guard-proxy's
  `RATE_LIMIT_SESSION_RPM` refused 0 turns at both sizes, since a phone sends 3 turns at least 15 s apart.
- **The cost cap is far off.** A served turn cost $0.0060 by `/cost`, so the $25 `COST_CAP_USD` holds about 4,100
  served turns. Run A cost $2.04 and run B $1.85.
- **`PROXY_TIMEOUT` (120 s) is the only cause of a failed turn.** 13 turns (8 at 500 phones, 5 at 150) came back
  502 at 120 s. In each one the agent ran the same shell command again and again until the deadline. 12 retried a
  `run_shell` that failed every time, mostly `Syntax error: Unterminated quoted string`, 22 to 74 times in the
  turn. One ran a working command 80 times. A conversation in that loop timed out again on its next turn (one
  session 3 times). Every such 502 carried guard-proxy's `/chat` body, so the storefront showed its sentence,
  "BurritoBot's kitchen isn't answering. Try again in a moment.", but only after two minutes, with no answer.
  Each matched a guard-proxy `forward_error` at the 120 s deadline. Within 60 ms each was followed by a
  `task_cancel` of the agent's task with state `canceled`, and no `task_cancel_failed`. The two traces
  looked up in Datadog APM (`988bfbb5...`, `caa8a7c7...`) are there with guard-proxy's `chat` span, the agent's
  `invoke_agent` span and its `run_shell` spans. Since #885 workshop-mcp refuses a turn's third identical tool call
  and every call after its twentieth, keyed on the turn's trace id (`gitops/ai-layer/tool_audit.py`). The replay
  that should show none of these 502s runs once that change is on attackme.
- **Nothing in front of the console failed.** No turn came back without guard-proxy's or nginx's body, so the
  public host's Caddy and Railway's edge answered every turn. The first run's 11 unexplained 502s did not recur.
- **Served latency stays phone-friendly.** p50 4 to 5 s and p95 9 to 14 s at both sizes. The slowest served turn
  took 40 s.

### Run A again, 2026-11-05 06:35 UTC, 500 sessions, after #450 (run 202611050635)

attackme.burritobot.co, from one machine, 500 sessions from the Portland harvest (1,144 prompts in 30
conversations), 1,500 turns in 352 s.

| | Turns |
|---|---|
| Served | 339 |
| Refused by nginx per conversation (`wib_chat_session`) | 0 |
| Refused by guard-proxy per session (10 a minute) | 0 |
| Refused by guard-proxy per cluster (150 a minute) | 1,153 |
| HTTP 502, guard-proxy at `PROXY_TIMEOUT` | 8 |

- Latency of served turns: p50 5.3 s, p95 13.8 s, p99 20.7 s, max 40.0 s. All turns: p50 0.29 s.
- Cost $2.04 by `/cost` ($0.2373 before, $2.2773 after), $0.0060 per served turn.
- `LOAD REPLAY RED`, on the 8 timeouts alone. They came from 5 sessions, 3 of which timed out twice. In those 5
  sessions the agent made 22 to 93 tool calls, almost all failing `run_shell` retries.
- The bot deployed 15 Deployments and 7 Pods in `agent` for the replayed attack prompts (`maintenance-shell`,
  `loyalty-rewards`, a dozen `*-agent` Deployments, `nginx`, `redis` and others). They were deleted after the run,
  leaving only objects older than the run.

### Run B, 2026-11-05 06:43 UTC, 150 sessions, after #450 (run 202611050643)

attackme.burritobot.co, from one machine, 150 sessions from the same harvest, 450 turns in 405 s.

| | Turns |
|---|---|
| Served | 307 |
| Refused by nginx per conversation (`wib_chat_session`) | 0 |
| Refused by guard-proxy per session (10 a minute) | 0 |
| Refused by guard-proxy per cluster (150 a minute) | 138 |
| HTTP 502, guard-proxy at `PROXY_TIMEOUT` | 5 |

- Latency of served turns: p50 4.1 s, p95 9.1 s, p99 18.0 s, max 26.1 s.
- Cost $1.85 by `/cost` ($2.2773 before, $4.1274 after), $0.0060 per served turn.
- `LOAD REPLAY RED`, on the 5 timeouts alone: 3 sessions, one of which timed out on all 3 turns.
- No turn was refused in the first minute. The cluster window started refusing at about 60 s, when the last
  phones' first turns met the first phones' second turns.
- The bot deployed 3 more objects, deleted after the run.

Prompts were replayed as recorded with only the probe marker added. guard-proxy keeps any prompt carrying it off
the feed (`_is_probe`, proxy.py), and the live `/prompts` feed read after both runs held none of the harvest's
prompts.

### Run A, 2026-10-31 16:45 UTC, before #450 (run 202610311645)

attackme.burritobot.co, from one machine, 500 sessions from the Portland harvest, 1,500 turns in 289 s.

| | Turns |
|---|---|
| Served | 291 |
| Refused by nginx per network (`wib_chat_address`) | 1,164 |
| Refused by guard-proxy per cluster (150 a minute) | 30 |
| HTTP 502 | 15 |

- Latency of served turns: p50 3.1 s, p95 11.4 s, p99 47.7 s, max 73.8 s.
- Cost $1.58 by `/cost`, $0.0054 per served turn. The $25 cost cap was never reached.
- `LOAD REPLAY RED`: 15 turns did not come back as a sentence a phone can read.
- Causes of the 15 HTTP 502s: 4 are guard-proxy's `chat forward failed: timed out` at `PROXY_TIMEOUT` 120 s,
  filed as #750. The other 11 are not in the console's access log, which logged 10 of the 1,500 `/chat`
  lines, so their source is still unknown.
- What it measured: from one address the per-network nginx limit refused 78 % of turns, which on venue Wi-Fi
  is one bucket for the whole ballroom. That led to Michael's 2026-11-01 ruling on #450 to limit per person.

## What these runs did not cover

The 2026-11-05 runs loaded attackme's `/chat` and what stands in front of the model: guard-proxy's rate limits, its
cost tally and `PROXY_TIMEOUT`. They did not load the room's prompt feed or the wall (#924 asks about both):

- **guard-proxy's `/prompts` feed under load.** Every replayed prompt carried `[[wib-probe]]`, and guard-proxy keeps a
  probe-marked prompt off the feed (`_is_probe`, proxy.py). No replayed prompt reached `/prompts`, so how the feed
  holds up at hundreds of prompts a minute was not measured.
- **The wall's SSE fan-out to many viewers.** The wall at `prompts.burritobot.co` (prompts-agenticburn) polls each
  cluster's `/prompts` every 3 s and streams new prompts to every open page over SSE. With no replayed prompt on the
  feed it had nothing new to stream, and `load_replay.py` opens no wall page, so the stream to a room of phones and
  the projector was not loaded at all.
- **The cost cap's refusal.** The runs measured the cap's headroom, $0.0060 a served turn against $25, but `/cost`
  ended at $4.13, so the refusal guard-proxy sends once the cap is reached was never met under load.
- **The admin cluster.** Only attackme, on watch-it-burn-community, was loaded; burritobot-private was not.

A run that loads the feed and the wall sends prompts without the marker, which puts them on the live wall, and opens
many wall pages at once. No such run is on record.
