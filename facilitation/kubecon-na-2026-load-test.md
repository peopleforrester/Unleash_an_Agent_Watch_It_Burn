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

## The runs still owed

Both wait on #450's per-person chat limit reaching staging and syncing to watch-it-burn-community. Run 15018's
draft of it (`b40c18a`, on `agent/450-15018`) never landed; #786 made it again on the current staging, and it moves
`verify/load_replay.py` off the per-network zone too. Before sending, confirm that the live console no longer
carries `wib_chat_address`.

**Run A again: 500 sessions from one address, through the public hostname.**

```bash
python3 verify/load_replay.py attackme.burritobot.co --yes --users 500 --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts --json-out tmp/load-replay-attackme-500.json
```

Predicted: 1,500 turns offered over about 2.5 min. About 375 are served (150 a minute over the run), and most
of the rest come back as guard-proxy's cluster-window refusal. That costs about $2.03 at the first run's
$0.0054 a served turn.

**Run B: 150 sessions from one address, the expected room.**

```bash
python3 verify/load_replay.py attackme.burritobot.co --yes --users 150 --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts --json-out tmp/load-replay-attackme-150.json
```

Predicted: 450 turns offered at about 180 a minute at the peak. Most are served, and the cluster window refuses
the overflow in the first two minutes. At most 450 are served, about $2.43.

Together the two runs come to about $4.50 at most, inside the $10 budget of Michael's go. After each run, read
the guard-proxy and workshop-mcp logs as the run-of-show's Night Before step says (#750). Then name the cause of
every turn that did not come back as a readable sentence.

## Results

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

### Run A again, 500 sessions, after #450

Not yet run.

### Run B, 150 sessions, after #450

Not yet run.
