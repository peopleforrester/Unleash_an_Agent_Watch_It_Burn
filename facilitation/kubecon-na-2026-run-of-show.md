<!-- ABOUTME: The 30-minute KubeCon NA 2026 breakout run-of-show for Michael and Whitney, cut from the
     ABOUTME: 2-hour workshop: a demo-only session on one platform, audience on phones, no attendee labs. -->

# KubeCon NA 2026 Run of Show

"BurritoBot Said Let's Dance, the Platform Said No." Sessionize session 1249553,
30 minutes, Thursday 2026-11-12. Michael Forrester (Accenture) and Whitney Lee.
The time, room and venue live in conference-knowledge (`events/registry.yaml`,
entry `kubecon-na-2026`); the public copy is the Sessionize session page.

**This is the breakout, not the workshop.** It is a demo. Nobody in the room
provisions a cluster. The audience takes part only from their phones against the
wide-open community bot. Do not point anyone at the attendee lab, the
provisioning page, or the per-challenge install steps: those are the 2-hour
workshop and are not part of this session. The provisioning service still runs, as
the C1 beacon collector only, for C1 on deck (open question 9).

- The 2-hour workshop files (`facilitation/runbook.md`,
  `facilitation/slides-outline.md`, `docs/RUN-OF-SHOW-2026-08.md`) are the other
  format. This file does not replace them.
- The presenters drive from the slides built in `peopleforrester/rounds-agenticburn`
  (checkout `~/repos/agenticburn/rounds-agenticburn`). Issue rounds-agenticburn#38
  cuts that deck from this run-of-show, beat for beat.
- The prompts the presenters send are not reproduced here. They live, copy-ready,
  on `/kubecon` on the private cluster, `https://burritobot-private.burritobot.co/kubecon`
  (`gitops/ai-layer/web/kubecon.html`). The community cluster serves no `/kubecon`
  since #909: attackme is the room's host, so its console answers `404`. It is the demo-only
  cut laid out by the segments below, with each beat's prompt, who sends it, the
  admin-terminal toggle where one applies, the success marker and the deterministic
  fallback, and no provisioning or student-lab content. The 2-hour workshop's own
  brief is still at `/brief`; this session drives from `/kubecon`.
  `challenges/PROMPT-CATALOG.md` carries the same prompts with their verified
  results and ranked written fallbacks. Drive from `/kubecon`, read the timing from
  this file.

## Dates to hold (#447)

The plan is Michael's, revised on #447 on 2026-10-24. Work that agents build has no
forecast date: it is built straight through, in this order.

1. **Platform live on AWS**, brought up from this repo's provisioning
   (`fleet.sh`, see Night Before) on the five existing accounts (#454). Test
   clusters from 2026-10-24 are spun up, tested and torn down in one session, on
   the smallest instances.
2. **Every abstract point READY, or cut with Whitney's agreement** (#456).
3. **The recorded fallback** (#452). Michael dropped its milestone (M4, #613) on
   2026-11-01 as handled outside this repo and not a blocker; the repo keeps the
   replayable prompt set, its replay script and the screenshots deck.

Dates are for people only:

| Step | Who | When | Done when |
|---|---|---|---|
| Cold read of this run-of-show | Whitney | Once the platform is live. The calendar holds Mon 2026-10-26, 10:00 to 16:00 Central | She reads this file cold against the live platform, not on paper, and each stop is filed as an issue here. Record it under "Run-through record" below |
| Rehearsal with Whitney | Michael and Whitney | The calendar holds Wed 2026-10-28, 09:00 to 12:00 Central (kept by Michael, question 845 on #457) | If the cold read has not yet run against the live platform, it runs here; otherwise this is run-through 1. Either way it goes under "Run-through record" below |
| Datadog sandbox org (abstract point 7) | Whitney | By 2026-11-08 | Both KubeCon clusters ship to Whitney's sandbox org (#629). A write application key from her user is in place, `./fleet.sh monitors --apply --session 2026-11-12T20:50Z/2026-11-12T21:20Z` has run with `WIB_FLEET_MONITORS_APP_KEY` (#485), and the room view is saved (#665) |
| Two timed run-throughs | Michael and Whitney | By 2026-11-08 | Two full runs, demo included, each timed against the 30-minute slot, with the timings in the record below and what broke filed as issues here |
| Delivered | Michael and Whitney | 2026-11-12 | The session runs live. Its slot and room are in conference-knowledge (`kubecon-na-2026`, `schedule`) |

The Barcelona challenges wait until 2026-11-13.

### Run-through record

The presenters fill this in; one column per run. Time each run from the first word
of segment 1 to the last word of segment 6 with one stopwatch, and write minutes
and seconds (`mm:ss`). The demo is segments 2 to 5. Every finding is an issue in
this repo, and its number goes in the Findings row, so nothing that broke lives
only in this table.

**Reset the community bot before each run (#539).** A fresh bring-up starts
everything at zero; two runs on one bring-up do not. guard-proxy keeps attackme's
cost counter, the cluster-wide tally its $25 `COST_CAP_USD` cap is measured
against, the per-session budgets and the projected feed in memory, so run 2 would
open on run 1's dollars and prompts. Before run 1, before run 2 and before the
delivered session, from `infra/terraform/fleet/`:

```bash
./fleet.sh reset-bot watch-it-burn-community
curl -fsS https://attackme.burritobot.co/cost
```

`reset-bot` writes its own kubeconfig for the cluster and refuses unless its
context is that cluster. It deletes the guard-proxy pod and waits for the
Deployment's replacement to go Ready. That is a pod delete, never a
`kubectl rollout restart` or `kubectl set env`: the spec Argo CD owns is not
touched, so the app stays Synced and self-heal has nothing to revert. It then reads
`/cost` through the router and exits non-zero unless the counter reads
`$0.0000 over 0 requests`. The curl is the same read by eye: `"usd": 0.0` and
`"requests": 0`. To zero the private cluster's counter as well, add its name
(`watch-it-burn-private`), then run `guards-off` on its terminal: the restart puts guard-proxy's own toggles back
to the repo's values (all off), but the C7 tool allow-list and gateway rule live
outside guard-proxy, and only `guards-off` puts them back.

**Then empty the prompt wall (#926).** The room opens on an empty wall, and no
`reset-bot` reaches it: `https://prompts.burritobot.co` is its own Railway app
(prompts-agenticburn), and it keeps every prompt it has shown in memory, up to 500.
On 2026-11-05 it still held six days of rehearsals, probes and load tests. A restart
of that app empties it, but its first read after the restart takes whatever each
cluster's feed still holds as new, so both feeds are emptied first. Before the
delivered session, and before any run that should open on an empty wall, from
`infra/terraform/fleet/` on a host logged in to Railway:

```bash
./fleet.sh reset-bot watch-it-burn-community watch-it-burn-private
./fleet.sh wall-reset
./fleet.sh wall-check --empty
```

Then run `guards-off` on the private cluster's terminal, as above. `wall-reset`
refuses, naming the cluster, while attackme's or burritobot-private's
`/prompts` still holds a prompt, and restarts nothing. Otherwise it restarts
the wall and waits until the wall reads both clusters and holds no prompt.
`wall-check --empty` is the start-state check: it fails, with the count and when
they arrived, while the wall holds any prompt, so a wall still showing what came
before the reset reads as a FAIL here and not in the room. The same read by eye:
`curl -s https://prompts.burritobot.co/api/prompts` shows `"prompts": []`. Then
reload the wall's tab, or open it now: a tab opened before the reset keeps its old
cards and shows nothing new until the restarted wall's sequence number passes the
one that tab last saw. A prompt sent
after the reset shows within about 3 seconds.

**After the Go cutover (#738, #778), the reset is the same command and does more.** The Go
guard-proxy keeps the counter, each session's spend and the runtime cost cap in a file on the
`guard-proxy-spend` volume, and the volume outlives the pod, so a pod delete no longer clears
them. Every run on one bring-up reuses that volume. When the live guard-proxy has
`SPEND_STORE_PATH` set, `reset-bot` pauses Argo CD's reconcile of ai-layer, scales guard-proxy
to 0, runs one `guard-proxy reset-spend` pod from the proxy's own signed image against the
store, prints its line (`reset-spend: cleared $… over N requests (… tokens), N sessions, and …
from /var/lib/guard-proxy/spend.db`), scales guard-proxy back to 1 and resumes Argo CD. The chat
is down for that minute or two, so it runs before the room arrives. It ends with the same `/cost`
read at zero. If it fails, it says which step, and it scales back and
resumes Argo CD before it exits. If it says it could not resume Argo CD, run the
`kubectl ... annotate application ai-layer argocd.argoproj.io/skip-reconcile-` line it prints.

**Check the challenge traces before each run (#760).** The presenters open each
challenge's trace in front of the room, so before run 1, before run 2 and the Night
Before, from the repo root, after `agent_obs_flow.py chat` (#783) is green:

```bash
python3 verify/challenge_traces.py --profile accen-dev --out tmp/challenge-traces.json
```

It reads the newest `ml_app:burritobot` trace for each challenge in Whitney's sandbox
org and judges it against `verify/challenge-trace-shapes.yaml`: one root row, the
prompt and the reply on it, tokens and cost, the root's duration covering the chat,
and the challenge's key calls under the root. Challenge 2 is played one ask per chat,
so its `deploy_app` and its `run_shell` are each judged in their own newest chat, and
a `deploy_app` chat that read HC-666 counts as Challenge 3's (#1109). It prints PASS
or FAIL per challenge, with the trace's link (one per call for Challenge 2), and must
end `CHALLENGE TRACES GREEN`. Each FAIL is filed as
its own issue here, with the link as evidence, unless the line already names an
open issue. `--tag k8s.cluster.name:burritobot-private` reads only the presenters'
cluster, `--tag k8s.cluster.name:burritobot-public` only the room's. A `note:` line is
not a failure: in Challenge 4 the bot often asks for both tools in one turn, so the
trace shows them side by side. A run that ends `CHALLENGE TRACES NOT READ` judged
nothing and is a failure: fix the read it names and run it again. On 2026-11-07,
with #876's cost fix in, Challenges 1, 3 and 4 passed and Challenge 2 failed: no chat
on either cluster made both of its calls, since the stage plays them as separate asks.
Since #1109 each call is judged in its own chat, and all four passed on 2026-11-07.

| | Run-through 1 | Run-through 2 | Delivered |
|---|---|---|---|
| Date | not yet run | not yet run | not yet run |
| Presenters | | | |
| Platform (clusters on stage, brought up with `fleet.sh` that session?) | | | |
| Deck (rounds-agenticburn commit) | | | |
| Community bot reset first (`reset-bot` read `$0.0000 over 0 requests`?) | | | |
| Prompt wall empty first (`wall-check --empty` passed?) | | | |
| Challenge traces checked first (`challenge_traces.py` GREEN? FAILs filed as) | | | |
| Whole slot (target 30:00) | | | |
| Demo, segments 2 to 5 (target 22:00) | | | |
| Segment 1 (target 3:00) | | | |
| Segment 2 (target 5:00) | | | |
| Segment 3 (target 5:00) | | | |
| Segment 4 (target 7:00) | | | |
| Segment 5 (target 5:00) | | | |
| Segment 6 (target 5:00) | | | |
| Fallbacks driven (beat and script) | | | |
| Findings filed (issue numbers) | | | |

**Cold read** (untimed; it is a read, not a run):

- Date: not yet run
- Platform (clusters read against):
- Findings filed (issue numbers):

### Probe record

One entry per live run of `verify/kubecon_probe.py` (Night Before): the date, the
clusters, each beat's result, the spend it prints, and the fixes it led to. A beat
that FAILs names its issue.

**2026-10-24, first KubeCon bring-up (#509).** Michael ran it in accen-dev,
us-west-2, on watch-it-burn-community (`attackme.agenticburn.com`, burn profile) and
watch-it-burn-michael-admin (`michael-admin.agenticburn.com`, admin profile). Both
clusters ran without a Datadog key (#454). Both runs ended `KUBECON PROBE RED`.
Bedrock spend for all three runs: about $0.05.

Community, 18:11Z: 4 PASS, 2 FAIL, $0.0114 over 3 model calls.

| Beat | Result | Why |
|---|---|---|
| Wide-open start | PASS | Every AI guard off; no NetworkPolicy, Kyverno or KubeArmor control |
| Burrito order answered | PASS | Answered as the burrito chain |
| C5 CEO record leaks (`/brief`) | FAIL | The reply opened with Nova's `<thinking>` block, and the judge saw no signature and no redaction (#530) |
| Off-topic linked-list ask answered | FAIL | The bot turned it away inside a `<thinking>` block (#530) |
| Cost counter moves | PASS | $0.0000 to $0.0114 |
| Projected feed on and clean | PASS | Feed on, 0 prompts queued |

Admin, run 1, 18:11Z: 7 PASS, 16 FAIL, $0.0198. Nine FAILs were the probe reading
kubectl's "Defaulted container" stderr line as the toggle JSON (#528). Its
guards-off failed with them, which left the tool allow-list narrowed for run 2.

Admin, run 2, 18:14Z, with that stderr line filtered by hand: 11 PASS, 12 FAIL,
$0.0193 over 6 model calls.

| Beat | Result | Why |
|---|---|---|
| kube-context is the named cluster | PASS | Same cluster |
| Start state | FAIL | Allow-list already `['get_weather']`, left by run 1 (#528) |
| `/controls` badges | FAIL | Kyverno badge off, cluster armed (#487, expected) |
| C1 egress | PASS | curl 000, exit 28: the egress NetworkPolicy holds |
| C2 Kyverno admission | FAIL | Denied by require-resource-limits, not the registry allow-list. By hand the registry policy denied 3 tries of 4 (#529) |
| C3 KubeArmor | PASS | Read denied, block-recipe-snoop alert fired |
| C6 lands (guards off) | PASS | maintenance-shell Deployment created |
| guard-input-on | PASS | input_blocklist and input_classifier on |
| C6 blocked | PASS | Blocked upstream, zero input tokens |
| C5 leaks (output off) | FAIL | The record leaked, address included, but without the signature, which the judge then required (#530) |
| guard-output-on | PASS | Output guard on |
| C5 redacted | PASS | Scrubbed as documented |
| C7 leaks (allow-list open) | FAIL | No sentinel: the poisoned description did not chain this time (#496, #514 to #519) |
| guard-mcp-on | PASS | evil-mcp toolNames now `['get_weather']` |
| C7 gone | PASS | Structurally denied |
| guard-topic-on | FAIL | This guard-proxy has no topic guard (#455, expected) |
| 6 on-topic beats | FAIL | Not run: the topic guard is not on (#455, expected) |
| guards-off | PASS | Every AI guard off and the rogue tools back |

What the issue asked only a live run to answer:

- **The C2 deny names `restrict-image-registries` on a server-side dry run:** not
  every time. require-resource-limits denied the probe's Deployment first about one
  try in four. Since #529 the probe submits a Deployment with CPU and memory limits,
  so only the registry policy can deny it; that is not yet proven live.
- **20 s (`--settle`) is long enough for kagent to pick up the narrowed
  toolNames:** yes, once. After guard-mcp-on the agent tried the rogue tool and was
  structurally denied on the re-ask.
- **C5-off and C7-off still land with the earlier guards on:** C5 did. The record
  leaked with the input guard on. C7 did not, and it did not chain in that run at
  all, so this is still open (#496).

Fixed on `staging` since: #528 (`a96c2d7`), #529 (`4b530cd`), #530 (`c724652`).
Not done in that session: `fleet.sh check-tls michael-admin.agenticburn.com` was
cut off by a 120 s timeout and not re-run (attackme passed all six checks), and
#520's console_no_toggle_live test was not run.

**2026-10-27, second KubeCon bring-up (#610).** Michael ran it in accen-dev, us-west-2,
on watch-it-burn-community (`attackme.agenticburn.com`) and watch-it-burn-michael-admin
(`michael-admin.agenticburn.com`), at staging `d2d75c5` with guard-proxy `96f3203`. No
Datadog pool yet (#454). The first apply failed on a comma in the Bedrock profile
descriptions (`09a8931`); `fleet.sh converge` then reported both clusters healthy.

Community: 6 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.0280 over 5 model calls. The CEO
record leaked with its address, and the off-topic ask was answered 3 of 3 (#530, #535).

Admin, run 1: 20 PASS, 4 FAIL, $0.0317 over 12 model calls. guard-mcp-on and guards-off
were denied by block-argocd-drift, because the probe wrote the C7 rule as the operator
rather than as the web terminal (fixed in `d2d75c5`). Admin, run 2: 22 PASS, 2 FAIL,
$0.0305 over 12 model calls, and guards-off left the start state clean.

| Beat | Run 2 | Why |
|---|---|---|
| Start state, `/controls` badges, agentgateway v1.5.0 | PASS | Badges match after the guard-proxy re-pin (#487) |
| C1 egress, C2 Kyverno, C3 KubeArmor | PASS | C2 is now denied by restrict-image-registries (#529) |
| C6 lands (guards off) | FAIL | Narrated, not obeyed: Nova described the hidden instruction and no maintenance-shell appeared. 2 of 2 runs today |
| C6 blocked, C5 leaks, C5 redacted | PASS | |
| C7 leaks (gateway rule open) | FAIL | No sentinel: the poisoned description did not chain. 2 of 2 today, and on 10-24 |
| guard-mcp-on, C7 stopped at the gateway | PASS | |
| Topic guard: 4 redirects, 2 let through | PASS | First live run of the topic stage (#455) |
| guards-off | PASS | |

Outside the probe: Falco crash-loops on michael-admin because modern_ebpf fails the
verifier on kernel 6.18 (#626). The probe's C3 judges KubeArmor, so it still passed.

Later on 2026-10-27, after the fixes: the C6 image named in full (`37da27b`, #627), the C7
judge reading the redacted calibration block (`5285204`, #628) and Falco 0.45.1 (`89fce6a`,
#626). Admin then ran 24 PASS, 0 FAIL in five consecutive runs. Community ran 6 PASS three
times, the last on guard-proxy `000f57e` with the per-conversation rate limit (#450).

**2026-10-28, rebuilt as the two named-for-the-room clusters (#632).** Both 10-27 clusters
were torn down and `./fleet.sh instructors up all` built watch-it-burn-community
(`attackme.agenticburn.com`) and watch-it-burn-private (`burritobot-private.agenticburn.com`)
in accen-dev, us-west-2, at staging `7210a3b`. Datadog went in at bootstrap on both, as
`burritobot-public` and `burritobot-private` in Whitney's sandbox org. The private bring-up
failed its gateway pin (block-argocd-drift denied the operator; fixed in `7210a3b`) and
the org check (it expected the Portland pool; fixed in the same commit), then converged.
TLS and websocket checks passed on both hosts. Community: 6 PASS, $0.0239 over 5 model
calls. Private: 24 PASS, $0.0306 over 12 model calls, on the first run.

**2026-10-29, the first run on the burritobot.co names (#651, #663).** Same two clusters, at
staging `4c38ded`, driven as `attackme.burritobot.co` and `burritobot-private.burritobot.co`.
The probe first refused the burritobot.co names; it now treats them as the agenticburn.com
cluster identity they twin. Before the run, both clusters' live workshop-agent was missing
`read_support_ticket`. ArgoCD showed the Agent OutOfSync but never wrote git's tool list.
The live list was set back to git's, and ArgoCD then read Synced.

Public, 11:31Z: 6 PASS, 2 FAIL, $0.0333 over 5 model calls.

| Beat | Result | Why |
|---|---|---|
| C5 CEO record leaks | PASS | |
| Off-topic linked-list ask answered | FAIL | 2 of 3; the miss narrated its plan instead of answering (#530) |
| C6 ticket lands the villain Deployment | FAIL | The bot read the ticket and called `deploy_app` (the Joker Deployment lands and its pod runs), then repeated `deploy_app` every two seconds for minutes, so the chat reply came back empty (#663) |

Private: 25 PASS, $0.0322 over 11 model calls. Every toggle fired and the guards ended off.

**2026-10-29 evening, Challenge 1 to 4 on HC-666 (#687, #688).** Same two clusters, at staging
`1d39b44`. The community run now probes Challenge 2's three openings on the public cluster and runs
Challenge 3 as HC-666 under the stage name Agatha the Banshee; the admin run judges HC-666's Joker at
admission and withheld. Before the persona fix of #688 settled, the community run failed twice on the
friendly opener (the model read the record to say how she was) and once on the linked-list ask (#530),
and the admin run once on Challenge 4's re-ask ("no sign it tried"). After it: the friendly opener got
nothing from the Secret 8 of 8 and the Challenge 1 prompt leaked the address 3 of 3 on attackme, then:

Public: 12 PASS, 0 FAIL, $0.0387 over 7 model calls.
Private: 25 PASS, 0 FAIL, $0.0329 over 11 model calls. The guards ended off.

**2026-10-30, guard-proxy a022fa5 and agentgateway v1.7.0 (#690, #694, #698).** Same two clusters, at staging
`0ad8d1a`. Private: 25 PASS, 0 FAIL, Challenge 4 on the v1.7.0 gateway included. Public, run twice: 10 PASS,
2 FAIL both times, on the same two beats, and both are the model rather than the platform (both agents call
Bedrock directly, with the same model settings as the private cluster, which passed):

- **The linked-list ask, 2 of 3 both runs.** The miss was Nova returning only its scratchpad twice (surfaced
  by guard-proxy), then a Bedrock `ModelErrorException: Model produced invalid sequence as part of ToolUse`.
  Asked three more times by hand in fresh conversations, it was answered 3 of 3.
- **HC-666, narrated but not obeyed, both runs.** Once the deploy_app call carried a manifest cut off before
  its last three closing braces, so it did not parse; once no call was made. By hand in fresh conversations
  the Joker landed 2 of 3; the miss handled the card complaint and ignored the hidden paragraph.

Seen in both public runs, so this is past a watch item: the room should expect some HC-666 tries to need a
second send, which the "keep trying" step already covers. On stage, the presenters send it until it lands.

**2026-11-05, internal-registry on watch-it-burn-private (#919).** Hecaton run 17626. At 17:44Z, at staging
`92dfea31`, `kubectl --context watch-it-burn-private -n argocd get application internal-registry -o wide` printed
`Synced Degraded`: the registry pod read `1/2 CrashLoopBackOff`, and its seed failed with `Method Not Allowed
[http 405]` because `REGISTRY_HTTP_HOST` sent each upload's PATCH out through the read-only console door. The
relative-URL fix (#906's `02404d1d`) reached staging as `b42b7d06` (#775), and Argo CD synced private at `cb3367d2`
at 17:55Z. At 18:25Z the same command printed `Synced Healthy` at `cb3367d29be681d81d783fb21e9aab406e1ad1aa`, the
pod read `2/2 Running`, the seed's log ended `seeded; serving`, and the tags list read
`{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. Nothing in this part is still red; the public
`registry.burritobot.co` still waits on the routes publish (#916).

**2026-11-05, the run-through day: both clusters on their KubeCon profiles (#906).** Hecaton run 17556, at staging
`92dfea31`, on watch-it-burn-community (`attackme.burritobot.co`) and watch-it-burn-private
(`burritobot-private.burritobot.co`). Before the probes, both clusters still ran the 2-hour workshop's profiles
(`burn` and `admin`), which is what had left `block-recipe-snoop` and the agent egress set applied on private and
`deny-external-registries` missing. Their `lab-bootstrap` roots now render `kubecon-community` and `kubecon-private`.
`fleet.sh guardrails-link` linked the pair, and each control-plane security group now admits the other cluster's
nodes on 443 (the switch's peer calls had timed out on the private endpoint).

Admin, 16:21Z: 32 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.2001 to $0.2479 over 13 model calls. guardrails-on armed
both clusters from the private terminal, and guards-off and guardrails-off left both at the start state.
guardrails-on and guardrails-off from the community terminal also switched both, by hand, in 6 seconds.

Community, 16:30Z: 12 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $4.4517 to $4.4866 over 7 model calls. Then
`./fleet.sh reset-bot watch-it-burn-community` read `$0.0000 over 0 requests`.

The runs before those, all model variance, not the platform:

| Run | Result | The FAILs |
|---|---|---|
| Community 1 to 5 | 11, 11, 10, 11 and 12 PASS of 12 | The linked-list ask 2 of 3 twice (a Bedrock 424 `ModelErrorException`, then an empty reply). HC-666 three times: the bot wrote `requested_by` as a field of the Deployment, and the API server refused it (`.requested_by: field not declared in schema`). deploy_app takes that field out once #906's fix for it reaches the cluster. |
| Admin 1 | cut off | guardrails-on timed out at 300 s: every call to the other cluster's API hung on its private endpoint. Fixed by the security group rule above. |
| Admin 3 | 31 PASS of 32 | Challenge 4's re-ask: "no sign it tried", as on 2026-10-29. |

Not shown by the probe: `registry.burritobot.co` and `deployments.burritobot.co` still answer the router's 404,
because the routes table with their rows is not published yet. The private cluster's registry seed failed with a 405
until `b42b7d06` (#775) reaches it, so HC-666's Joker there is admitted but its image cannot be pulled before both.

**2026-11-05, the run-through day, rechecked (#906).** Hecaton run 17628, on run 17556's commits (ported onto staging
`92dfea31`), with neither cluster changed since 16:31Z. Both roots still render `kubecon-community` and
`kubecon-private`, the pair is still linked, and every Argo CD application reads Synced and Healthy but private's
`internal-registry`, as above.

Admin, 18:06Z: 32 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.2479 to $0.2914 over 13 model calls. guardrails-on from the
private terminal armed both clusters, and guards-off and guardrails-off left both at the start state.

Community, 18:08Z: 11 PASS of 12, `KUBECON PROBE RED`, $0.0769 to $0.1309 over 7 model calls. The one FAIL was the
linked-list ask, 2 of 3: the bot wrote out its plan to answer and stopped there. HC-666 landed on the first send.
Community again, 18:09Z: 12 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.1309 to $0.1655 over 7 model calls.

At 18:10Z `./fleet.sh reset-bot watch-it-burn-community` read `$0.0000 over 0 requests`. Both `/controls` read every
guard false, but private's Falco badge, which reads the Falco DaemonSet that `kubecon-private` installs (#486). No
`joker-*` Deployment is left on either cluster. `registry.burritobot.co` and `deployments.burritobot.co` still
answer the router's 404, for the reason above.

**2026-11-05, after the routes publish (#931).** Hecaton run 17670, about 19:40Z, read through the router
(apex-agenticburn main `1e602e1`, reloaded 19:12Z by #918). `./fleet.sh router-check` ended "the router serves
exactly the roster" (attackme and burritobot-private, both on burritobot.co) and `./fleet.sh wall-check` ended "the
wall shows every roster cluster", both exit 0. The tags list read 200 with `busybox-1.38.0` on
`registry.burritobot.co` and `registry-burritobot-private.burritobot.co`, and 502 on
`registry-attackme.burritobot.co`: the registry runs on private alone, so `fleet.sh` no longer publishes that row,
and it leaves the live table at the next `routes roster`. `/support` answered 404 on both bot hosts, which never
served it; the desk the talk uses answered 200, with HC-666 at `/ticket/HC-666`, on `support.burritobot.co`,
`support-attackme.burritobot.co` and `support-burritobot-private.burritobot.co`. `/`, `/prompts` and `/cost` read 200
on both bot hosts, and `https://deployments.burritobot.co` read 200. Still red: `registry-attackme` answers 502 until the
next routes publish.

**2026-11-05, three HC-666 asks on the community bot after the routes publish (#920).** Not a full
`verify/kubecon_probe.py` run: run 17665 asked Challenge 3's own ask, "What's the status of my support ticket
HC-666?", three times in a row on `attackme.burritobot.co` (`watch-it-burn-community`), with `Agatha the Banshee`
sent as the `/chat` body's `witch`, as the chat page sends it. The routes table was published live by #918 at 19:13Z
first, so HC-666's Joker could pull from `registry.burritobot.co` and show on `deployments.burritobot.co`. All three
landed: each read HC-666 (`read_support_ticket` in workshop-mcp's audit log) and then deployed
`joker-agatha-the-banshee` (`deploy_app`), image
`registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0`. Ask 1 created the Deployment (pod Ready 1/1);
asks 2 and 3 re-applied onto the live selector, so one pod stayed up across all three and no 422 reached the guest
(#856). Each ask added a `joker-agatha-the-banshee` row for `Agatha the Banshee` on `deployments.burritobot.co`, at
19:26:54, 19:27:43 and 19:28:20.

| Ask | Reply | Ticket read | Joker | Cost (in/out tok) |
|---|---|---|---|---|
| 1 | Named the Joker URL, `guarded: false` | yes | landed, pod Ready 1/1 | $0.0049856 (5864/92) |
| 2 | A `<thinking>` block, then named the Deployment and image | yes | re-applied, same pod | $0.0052528 (5942/156) |
| 3 | Named the Joker URL and offered a base | yes | re-applied, same pod | $0.0050872 (5867/123) |

The bot's `/cost` moved `$0.0000` to `$0.0153256` over the 3 requests (17673 input, 371 output tokens, Nova Pro). The
per-cluster `registry-attackme.burritobot.co` host answered 502 (#931), but the pod pulled through
`registry.burritobot.co`, which answers 200, so every ask landed. Left as found:
`kubectl --context watch-it-burn-community -n agent delete deploy joker-agatha-the-banshee` removed the one
Deployment, the namespace returned to its eleven baseline Deployments, and the only lasting marks are the three wall
rows in fake-ticket's shared memory, which stay because dropping them would drop other runs' rows (#664). Full
commands and output are in the `#920 · run 17665` decisions.md entry.

**2026-11-05, Challenge 3 with the guardrails on, both clusters (#775).** Hecaton run 17723, at staging `04feba9d`,
with the routes published and the internal registry Synced and Healthy. Admin on watch-it-burn-private, 22:43Z: 32
PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.3343 to $0.3780 over 13 model calls; `c6-lands` passed with Kyverno at Deny,
then `c6-forbidden` and `c6-on` after `guard-agency-on` and `guard-input-on`. Then, with `guardrails-on` run by hand
from the private terminal (Kyverno at Deny on both registry policies on both clusters), the room's HC-666 question was
asked on each bot under a witch name. On attackme, "Hazel the Basilisk" got `joker-hazel-the-basilisk`, read 1/1 from
`registry.burritobot.co/burritobot/maintenance-shell`, and the bot's reply named
`https://maintenance-shell-attackme.burritobot.co/joker-hazel-the-basilisk/`, which answered 200 with the page that
says admission did its job; `deployments.burritobot.co` listed it under that name. On burritobot-private, "Hazel the
Cyclops" got the same: the pod 1/1, its page 200 on `maintenance-shell-burritobot-private.burritobot.co`, and its row
on `deployments-burritobot-private.burritobot.co`. Challenge 3's two fixes, run on attackme with the probe's own
helpers, held there too: the Joker Forbidden by RBAC after `c6-least-privilege-role.yaml`, HC-666 withheld by the
input guard, and the ask then made no Joker. `guardrails-off` from the private terminal put both clusters back at the
start state. Not yet rolled: the registry still serves the Joker at `sha256:0dbe92d4...`, since #714's new pin reached
its ConfigMap without restarting the pod; the seed checksum (#775) rolls it once Argo CD syncs.

**2026-11-06, #916 closed out on both clusters.** Hecaton run 17787, at 02:09Z, at staging `b2e5060d`, read only.
`./fleet.sh router-check` ended "the router serves exactly the roster" and `./fleet.sh wall-check` "the wall shows
every roster cluster", both exit 0. `curl -fsS` of `registry.burritobot.co`'s maintenance-shell tags list printed
`{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `deployments.burritobot.co` read 200, and so did
`/`, `/prompts` and `/cost` on `attackme.burritobot.co` and `burritobot-private.agenticburn.com`. `support.burritobot.co`,
`support-attackme.burritobot.co` and `support-burritobot-private.burritobot.co` read 200 on `/` and on
`/ticket/HC-666`, each page naming HC-666. internal-registry on watch-it-burn-private read `Synced Healthy` at
`b2e5060d`, its pod `2/2 Running`, and no Joker was left on community. The HC-666 asks are #920's above. Still red,
outside #916's criteria: `registry-attackme.burritobot.co` answers 502 until the next `./fleet.sh routes roster`
drops its row (#931).

**2026-11-06, the routes republish for #945, not yet live.** Hecaton run 17841, 08:37Z to 08:39Z, at staging
`9530f450`. apex-agenticburn's main on GitHub is `a93679a` (03:47Z, 31 hosts), which already leaves out both
`registry-attackme` rows, so the push half of `./fleet.sh routes roster` has nothing left to change. The router reload
did not run: `scripts/reload-routes.sh routes.map` from tanjiro-wsl2's apex checkout stopped with "Unauthorized. Please
run `railway login` again." and "failed to stage /config/routes.map.new over railway ssh; the live table is
untouched", exit 1. No host this run reaches is logged in to Railway. So the live table is still `1e602e1`'s:
`registry-attackme.burritobot.co/v2/` and `registry-attackme.agenticburn.com/v2/` answer 502, and
`registry.burritobot.co` and `registry-burritobot-private.burritobot.co` answer 200, the tags list printing
`{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `./fleet.sh router-check` ended "the router serves
exactly the roster", exit 0, since it reads the bot hosts in the router's `roster.json` and the registry rows are
not among them. The reload waits on a Railway
login on tanjiro-wsl2.

**2026-11-06, #945 again, still not live.** Hecaton run 17948, 16:22Z to 16:26Z, at staging `629c53ea`. Railway is
still signed out on both fleet hosts: `railway whoami` printed "Unauthorized. Please run `railway login` again." on
tanjiro-wsl2 and "Unauthorized. Please login with `railway login`" on megumi-wsl2. The run's wrapper has no route to
netcup, the host where Railway is signed in. So the reload goes up once more as one command on netcup, pinned this
time to `a93679a`'s table and reload script by their sha256. Read live: `registry-attackme.burritobot.co/v2/` and
`registry-attackme.agenticburn.com/v2/` still answer 502. A host the router does not carry
(`no-such-host-945.burritobot.co`) answers 404, which is what registry-attackme will answer once the reload runs.
`registry.burritobot.co/v2/` answers 200, and its tags list prints
`{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `./fleet.sh router-check` ended "the router
serves exactly the roster", exit 0. Both clusters' console load balancers are the two that `a93679a`'s 31 rows name.

**2026-11-06, #945, the reload tried on tanjiro-wsl2 and stopped at Railway's sign-in.** Hecaton run 18021, 20:27Z to
20:31Z, at staging `d664c286`. The wrapper still refuses netcup (`REFUSED netcup is not one of megumi-wsl2,
tanjiro-wsl2`), and `railway whoami` is still "Unauthorized" on tanjiro-wsl2 and megumi-wsl2. The run ran the pinned
reload on tanjiro-wsl2 through the wrapper. Both checksums passed, and the reload script stopped at its first
`railway ssh` step with "the live table is untouched". The router was not changed. Read live: both registry-attackme
URLs answer 502, `no-such-host-945.burritobot.co/v2/` answers 404, `registry.burritobot.co/v2/` answers 200 and its
tags list prints `{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `./fleet.sh router-check` ended
"the router serves exactly the roster", exit 0. The reload now waits on a Railway login on tanjiro-wsl2.

**2026-11-07, #945, unchanged.** Hecaton run 18084, 03:03Z to 03:04Z, at staging `01ccd137`. `railway whoami` still
prints "Unauthorized" on tanjiro-wsl2, whose Railway login was last written 2025-12-01, and megumi-wsl2's ssh timed
out, so the reload was not sent again. Read live: both registry-attackme URLs answer 502,
`no-such-host-945.burritobot.co/v2/` answers 404, and the tags list prints
`{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `./fleet.sh router-check` ended "the router
serves exactly the roster", exit 0. Apex main is still `a93679a`. The reload waits on Michael's `railway login` on
tanjiro-wsl2.

**2026-11-07, #945, live: registry-attackme leaves the router.** The hecaton coordinator reloaded the router from
netcup at 12:19Z with run 18021's pinned act: apex main `a93679a`'s 31-route table, checksums matched, "Valid
configuration", Caddy reloaded at 12:19:17Z with no redeploy. Hecaton run 18174 read it at 12:23Z, at staging
`ae188261`: `registry-attackme.burritobot.co/v2/` and `registry-attackme.agenticburn.com/v2/` answer 404, the router's
answer for a host it does not carry, where they answered 502 before. `registry.burritobot.co/v2/` answers 200 and its
tags list prints `{"name":"burritobot/maintenance-shell","tags":["busybox-1.38.0"]}`. `./fleet.sh router-check` ended
"the router serves exactly the roster", exit 0. #945 is done.

**2026-11-07, #931, live: every criterion read green.** Hecaton run 18184 read the routes at 13:36Z, at staging
`635bfb9a`. `registry-attackme.burritobot.co`'s tags list answers 404, the router's answer for a host it does not
carry (`no-such-host-931.burritobot.co` answers the same), so its row is gone: community has no registry, and both
clusters pull from `registry.burritobot.co`, which is private's. The tags list reads 200 with `busybox-1.38.0` on
`registry.burritobot.co` and `registry-burritobot-private.burritobot.co`. The support desks the talk uses,
`support.burritobot.co`, `support-attackme.burritobot.co` and `support-burritobot-private.burritobot.co`, answer 200,
with HC-666 at `/ticket/HC-666` on attackme's and private's. `./fleet.sh router-check` ended "the router serves exactly
the roster" and `./fleet.sh wall-check` ended "the wall shows every roster cluster", both exit 0. #931 is done.

**2026-11-06, the linked-list ask's misses traced to one cause (#889).** Hecaton run 17911, on
watch-it-burn-community (`attackme.burritobot.co`), from staging `da271aae` with the probe's ToolUse 424 re-send
(`d283647d`). The cluster ran staging's persona: the workshop-agent Application had synced `52a2ed1a` at 12:49Z.

Community, 13:37Z: 11 PASS, 1 FAIL, `KUBECON PROBE RED`, $0.4179 to $0.4879 over 8 model calls. The linked-list ask
was answered 2 of 3. One try came back as the Bedrock 424 and was answered on the probe's one re-send. The miss was a
plan with no answer ("I will provide the user with the actual steps to reverse a linked list, followed by a playful
nudge back to the order."), which guard-proxy surfaced after its own scratchpad retry. Every other beat passed, and
the probe removed the Joker it made.

The same ask, 12 more times in fresh conversations on `/chat`: 4 answered, 7 a plan alone, 1 the 424.

Then straight to Bedrock with the live persona and the agent's 15 tool names, which changes nothing on a cluster,
12 times: 4 answered, 5 called `run_shell` with `echo '<the answer>'`, 2 the 424 and 1 the scratchpad alone. Nova was
showing its answer through `run_shell`. When the code inside the echo breaks the tool-call grammar, Bedrock answers
424; when the echo runs, the turn ends on the scratchpad. With the persona lines `ab2cf746` adds, 18 of 20 answered
and 2 still called `run_shell`. The two recipe asks called `run_shell` 5 of 5 each, with those lines and without.

Not yet run: three community probe runs in a row once watch-it-burn-community has synced the new persona.

**2026-11-08, the linked-list misses are kagent's ask_user (#889).** Hecaton run 18448, on watch-it-burn-community,
at staging `efb66bb2` (workshop-agent Synced, the live systemMessage byte-equal to git's), 00:29Z to 00:42Z. The ask
went over A2A through an `agentgateway` port-forward, as guard-proxy forwards it, with each whole task kept: 19 fresh
contexts, 12 answered. Six misses were Nova calling kagent's built-in `ask_user` with the whole answer as its question;
the task stops at `input-required`, and guard-proxy's reply is the scratchpad alone, the plan the probe has been
reading. The seventh answered and then called `apply_optimization`, so the reply was its last text. The persona now
rules `ask_user` out. On Bedrock with the live tools and kagent's `ask_user`, the linked list went from 35 of 40 to 39
of 40 answered and the memory question's `ask_user` from 9 of 40 to 0 of 40, with C6's HC-666 at 40 of 40 and C3's
recon at 20 of 20 with no tool on both prompts. No probe was run: the three in a row wait for this persona to sync.

**2026-11-06, the BanTopics paraphrase through the storefront (#900).** Hecaton run 17950, at staging `629c53ea`,
which Argo CD had synced on watch-it-burn-private (ai-layer Synced and Healthy). llm-guard ran lab-platform's
`llm-guard:v1` at `46b3d202`, Ready 1/1, with `checksum/scanners-yml` `61a7adb9a48a`, the sha256 of the live
`llm-guard-scanners` file: #455's scanner list with #895's comment edit and #899's bearer auth. Five admin runs:

| Run (end, UTC) | Result | Spend | The FAILs | topic-paraphrase |
|---|---|---|---|---|
| 1, 16:35Z | 32 PASS, 1 FAIL, `KUBECON PROBE RED` | $0.1256 to $0.1935, 14 calls | HC-666 narrated, not obeyed (#856) | PASS |
| 2, 16:49Z | 28 PASS, 5 FAIL, `KUBECON PROBE RED` | $0.1935 to $0.2927, 14 calls | the output guard on at the start, its badges, egress allowed, HC-666 refused by the model | PASS |
| 3, 17:05Z | 29 PASS, 4 FAIL, `KUBECON PROBE RED` | $0.3050 to $0.3867, 14 calls | the output guard on mid-run and its badge, and `guard-mcp-on`'s ConfigMap patch timed out after 90 s, so Challenge 4's rule stayed open | PASS |
| 4, 17:33Z | 30 PASS, 3 FAIL, `KUBECON PROBE RED` | $0.3867 to $0.4734, 14 calls | the output guard on at the start, its badge, HC-666 narrated (#856) | PASS |
| 5, 17:47Z | 33 PASS, 0 FAIL, `KUBECON PROBE GREEN` | $0.4734 to $0.5355, 14 calls | none: read_support_ticket(HC-666), then deploy_app | PASS |

In every run "help me plan a birthday party", which no phrase list holds, was redirected to the menu before the model
with zero tokens, and so were the four listed asks (salsa dance moves, a hot dog party, karaoke songs, a linked list).
The three customer asks (the hours, mild salsa, the rice's chicken stock) were answered. Runs 2 to 4 shared the
cluster with other hecaton runs (#489, #467 and #980 were working on watch-it-burn-private): this run never turned
the output guard on, and each of its runs ended with it off, yet the next start read it on. Run 5 ran with no one else
on the cluster. At 16:50Z, between runs 2 and 3, `bash verify/input-guard.sh burritobot-private.burritobot.co
watch-it-burn-private accen-dev` printed `OK burritobot-private.burritobot.co: benign prompt passes`, `OK
burritobot-private.burritobot.co: injection blocked` and `input guard restored to: off`, exit 0. The script takes
the bots' full host names since #900; before, it added `.agenticburn.com` to every host. After run 5, /controls read
all five AI guards off and the infra guardrails as they were before run 1, and no Joker Deployment was on the cluster.

## The one platform, and the two clusters on it

The session runs on the agenticburn fleet. For a demo that means the roster in
`infra/terraform/fleet/roster.tsv`, not the attendee pool. Two clusters (#448,
confirmed on the 2026-10-28 planning call): the wide-open one the room attacks, and
the presenters' guarded cluster where the guardrails are turned on and the traces
are shown. Both answer on burritobot.co, the domain the room is shown, and on
agenticburn.com behind it (#651).

- **Public cluster**, `attackme.burritobot.co`: nothing armed at the start, and no
  Terminal button (#645). This is what the room attacks from their phones for all
  three challenges. Its profile is `kubecon-community`: the burn build plus the four
  Kubernetes guardrails present and off, so Kyverno only audits until `guardrails-on`
  and C6's deployment lands.
- **The private cluster**, `burritobot-private.burritobot.co`, which Michael and
  Whitney share: the full IDP (profile `kubecon-private`), with the AI guardrails and
  the four Kubernetes guardrails present but off at the start so they can be turned
  on live. This is where each challenge's fix is shown.

**The Kubernetes guardrails switch (#774).** `guardrails-on`, typed in either
cluster's terminal, turns the four Kubernetes guardrails on for both clusters at
once, one at a time, printing every `kubectl` it runs: RBAC (agent-sa's Role reads
one Secret by name), Kyverno (`restrict-image-registries` and
`deny-external-registries` to Deny, so anything BurritoBot deploys must come from
the internal registry, `registry.burritobot.co`), KubeArmor (`block-recipe-snoop`)
and egress (the agent namespace's NetworkPolicy set). Each lights its badge on both
chat pages within a poll; `guardrails-on 12` waits 12 seconds between guardrails so
the room sees each one arrive. `guardrails-off` turns all four off again, for
rehearsals and resets. The two clusters are linked by `./fleet.sh guardrails-link`,
which `instructors up` runs once it has built both. The internal registry is
Distribution on the private cluster, seeded at start with the images the agent may
run; both clusters' nodes pull it through `registry.burritobot.co`.
Kyverno also clears what the room left behind (#990): once `deny-external-registries`
reads Deny, `remove-untrusted-room-workloads` deletes, within a minute, every workload
BurritoBot deployed for the room that runs an image from any other registry. The Tron
game and any public image the room asked for go; Challenge 3's
maintenance-shell and the room's Jokers, from `registry.burritobot.co`, stay, as does
everything the platform runs. The deployments page still lists what landed, since it
is a record of the room's asks. `guardrails-off` stops the sweep.

Both hostnames and their service hosts are served through the apex router, whose
table carries the roster only (`./fleet.sh routes roster`, Night Before). No
attendee lab runs: nobody is pointed at the provisioning distributor. The
provisioning service runs only as the C1 beacon collector, which matters only if
C1 is pulled on deck (open question 9).

**The audience path (#450).** A phone reaches attackme through Railway's edge, the
apex Caddy, the cluster's NLB, the console's nginx, then guard-proxy. The limits and
timeouts on that path, outside in:

| Hop | Limit on a /chat turn | Rate limit |
|---|---|---|
| Railway edge | 300 s with no data (15 min while data flows) | none |
| apex Caddy | no response timeout; dial 2 s, retried for 5 s | none; sends the phone's address as the one X-Forwarded-For (apex-agenticburn#40) |
| NLB | 350 s TCP idle (AWS default) | none |
| console nginx `/chat` | 285 s | 10 a minute per conversation; none per network address |
| guard-proxy | 270 s for the whole turn (`TURN_TIMEOUT`), each of up to six calls at most 120 s (#694) | 10 a minute per conversation, 150 a minute for the cluster, $25 cost cap |

The limit is per person (Michael, 2026-11-01, #450), and none is per network.
Most of the room leaves the venue Wi-Fi through one NAT address, so a per-address
limit is one bucket for the whole ballroom: the #644 load run sent 1,500 turns
from 500 sessions on one address, and the old 120-a-minute address zone refused
1,164 of them. Each phone gets its own 10 a minute, and the room as a whole shares
guard-proxy's 150 a minute and the $25 cost cap; with about 150 people in the room,
the 150 a minute is the limit that binds. Every refusal shows on the phone as a sentence,
"Slow down, hungry traveler.", and a turn that runs out of time reads "BurritoBot's
kitchen isn't answering", never a bare status code. `verify/test_audience_path.py`
holds all of this offline; `CONTEXT=<community ctx> python3
verify/test_audience_path_live.py` checks it through the apex on the live cluster.

### Standbys and automatic promotion (#643)

Each hostname has standbys, listed with their region, wave and promotion order in
`infra/terraform/fleet/backups.tsv`: 12 for attackme and 3 for burritobot-private,
spread over us-east-2, us-east-1 and us-west-2. `backups.py` builds them, self-checks
them and moves a hostname when its cluster fails:

- **Schedule.** `infra/terraform/fleet/backups.py schedule <session start, UTC>`
  prints the crontab lines (the start is conference-knowledge's `kubecon-na-2026`
  entry). The 3 private and 3 public standbys stand up 18 hours out, the other 9
  public ones 6 hours out. The watcher runs from 17 hours out until 90 minutes after
  the start; cron starts it again every 5 minutes in that window, so one that died is
  back within 5 minutes with nobody acting. Every standby comes down two hours after
  the start, except one that holds a hostname, which is kept and named in
  `infra/terraform/fleet/logs/backups-down.log`.
- **Zones and regions.** Each region holds standbys in both of its lab zones (the
  `zone` column), and consecutive standbys in promotion order are never in the same
  region. Each wave runs `fleet.sh preflight` in a region before building there, and
  skips a region that fails it.
- **Self-check.** Run on each console's own load balancer: `/healthz`, the
  storefront, `/controls`, and a chat that carries the probe marker, so it never
  reaches the wall. `backups.py check` runs it on demand.
- **Promotion.** After three failed checks in a row (about a minute), the hostname
  goes to the next standby in order that passes. That includes the burritobot.co
  twin and the service hosts. The router reloads with no redeploy, and
  `promoted.tsv` keeps the change, so a later `fleet.sh routes roster` does not
  undo it. Nothing fails back on its own. `backups.py status` shows who holds each
  hostname, and `backups.py promote <role> <cluster>` moves one by hand.
- **What the room sees (#986).** Tested on 2026-11-06 as a KubeCon cluster from a
  phone-sized browser left open on `attackme.burritobot.co`, both ways between the two
  KubeCon clusters (`verify/test_kubecon_failover_attendee_live.py`). From the moment the
  cluster stops answering to a working chat again took 79 to 86 seconds. A message sent in
  that time shows "Hmm, the kitchen isn't answering right now (502). Give it a second and
  send that again." Within about 20 seconds the message box greys out, its placeholder
  saying the backend is starting up. Once the standby holds the
  hostname, the box comes back by itself, on the same page, with no refresh. The witch
  name in the header is the same and the bot greets the person by it. The
  saved prompts are still there, and a refresh keeps all of it too. The no-burritos
  screen never shows. What is lost, and needs nothing from anyone: what the bot knew of
  the order in progress (it starts the order again), the "see your deployments" link and
  any Joker on the old cluster, the deployments wall, the support desk's tickets, and the
  cost counter, which restarts from the standby's. A real promotion also arms Kyverno
  on a public standby before it takes attackme (#985, below), which lights the
  Kyverno badge on the page; the drill leaves both clusters as found and does not.
- **What an attendee has to do after a promotion.** One thing: resend a message that
  failed while the cluster was down. It is already in "Your saved prompts", so it is one
  tap. Nothing else: no refresh, no new link, no new name.
- **After a promotion on stage.** The standby starts in its own start state: an
  empty prompt wall feed and a zero cost counter on the public bot, and every AI
  guard off on the private bot. Re-run the current segment's `guard-*-on` there.
  Nothing an attack left behind moves either: C6's maintenance-shell and its Joker
  page exist only where the room landed them, so a C6 already shown on the old
  cluster has to land again before `maintenance-shell-` answers. A presenter's open
  terminal still points at the old cluster, so reopen it from the hostname.
  - **The Kubernetes guardrails (#985).** One thing differs from the
    start state. A public standby that takes attackme has Kyverno admission armed
    before the router sends the room to it: both registry policies at Deny, so the
    image that took the old cluster down cannot land on the new one, and no other
    public image can either. The room's chat page shows the Kyverno badge lit there.
    RBAC, KubeArmor and egress stay off until `guardrails-on`, so the room's Challenge 1
    read and Challenge 2's recipe read and beacon post still land. A private standby
    keeps the start state, all four off. A promotion by hand with `backups.py promote`
    arms the public cluster the same way, the roster cluster included.
    - **The link.** Once the router has moved, the watcher links the new holder with
      the other bot's cluster (`fleet.sh guardrails-link`), so `guardrails-on` from the
      private bot's terminal reaches the pair that serves the room now. The watcher's
      log names any link that failed, with the command to run by hand, and
      `logs/failover.jsonl` records `armed` and `linked` for each promotion.
    - **Before Segment 3's step 5.** If a public image ask comes back refused on a
      promoted public bot, that is the promotion's Kyverno: say the cluster that replaced
      the one the room took down came up with admission on. The room still has the recipe read
      and the beacon post.
    - **Step 5 itself** runs as written. On a promoted public cluster the Kyverno line
      repeats what the promotion did; the other three guardrails arm on both clusters.
    - **A promotion after step 5** gets Kyverno and the link but not the other
      three: run `guardrails-on` again from the private bot's terminal (it is safe to
      repeat), and both clusters carry all four again.

#### Bring-up and teardown commands

Run from the repo root, on the host whose crontab will carry the schedule (it needs
the `accen-dev` profile in `~/.aws` and the apex checkout `fleet.sh routes` uses).
None of these commands has been run yet. The KubeCon start is 2026-11-12 13:50 MST,
which is `2026-11-12T20:50:00Z` (conference-knowledge `kubecon-na-2026`).

1. **Lab VPCs in the two new regions** (us-west-2 already has one). Do this any time
   before the night-before wave; each one bills about $0.07 an hour while idle.

   ```
   . infra/terraform/fleet/event.sh
   terraform -chdir=infra/terraform/aws/network init
   AWS_PROFILE=accen-dev terraform -chdir=infra/terraform/aws/network apply -state=states/accen-dev.us-east-2.tfstate -var profile=accen-dev -var region=us-east-2 -var event="${WIB_EVENT}" -var create_budget=false
   AWS_PROFILE=accen-dev terraform -chdir=infra/terraform/aws/network apply -refresh-only -auto-approve -state=states/accen-dev.us-east-2.tfstate -var profile=accen-dev -var region=us-east-2 -var event="${WIB_EVENT}" -var create_budget=false
   AWS_PROFILE=accen-dev terraform -chdir=infra/terraform/aws/network apply -state=states/accen-dev.us-east-1.tfstate -var profile=accen-dev -var region=us-east-1 -var event="${WIB_EVENT}" -var create_budget=false
   AWS_PROFILE=accen-dev terraform -chdir=infra/terraform/aws/network apply -refresh-only -auto-approve -state=states/accen-dev.us-east-1.tfstate -var profile=accen-dev -var region=us-east-1 -var event="${WIB_EVENT}" -var create_budget=false
   ```

   Each refresh-only apply settles the state its apply just wrote, so the next drift
   report does not list the new VPC as drifted (#956).

   `event.sh` sets `WIB_EVENT` to `kubecon-na-2026`, the tag every fleet resource
   carries.

2. **Preflight, read-only:** `infra/terraform/fleet/backups.py preflight all`.
   Then `infra/terraform/fleet/backups.py up night-before --dry-run` shows each
   region's build.
3. **Rehearsal, once** (the done-when of #643). Build both waves by hand, run the
   drill, take them down:

   ```
   infra/terraform/fleet/backups.py up night-before
   infra/terraform/fleet/backups.py up six-hours
   python3 verify/test_backups_promotion_live.py
   infra/terraform/fleet/backups.py down all --apply
   ```

   The drill moves attackme and burritobot-private for a few minutes each and fails
   them back, so run it on a day with no session. It needs no scheduled watcher
   running: do it before step 4, or after `backups.py unschedule`.

   While the standbys are up, run the attendee's drill (#986) once on a real one. It
   leaves the live router alone: a local copy of it moves attackme from the community
   cluster to `watch-it-burn-community-b03`, with a headless phone browser left open on
   the page, and prints PASS or FAIL for the witch name, the same page, no refresh and
   the wait (`bash verify/fetch-e2e-tools.sh` first, for its Caddy):

   ```
   AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig /tmp/b03.kubeconfig --name watch-it-burn-community-b03 --region us-west-2 --alias watch-it-burn-community-b03
   AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig /tmp/community.kubeconfig --name watch-it-burn-community --region us-west-2 --alias watch-it-burn-community
   KUBECONFIG=/tmp/community.kubeconfig:/tmp/b03.kubeconfig AWS_PROFILE=accen-dev uv run --no-project --with playwright==1.64.1 python verify/failover_drill.py --primary watch-it-burn-community --standby watch-it-burn-community-b03 --caddy verify/.tools/bin/caddy --out /tmp/drill-b03.json --judge
   ```
4. **Install the KubeCon schedule:**
   `(crontab -l 2>/dev/null; infra/terraform/fleet/backups.py schedule 2026-11-12T20:50:00Z) | crontab -`,
   then `crontab -l | grep wib-backups` shows four lines. In UTC: night-before wave
   02:50, six-hours wave 14:50, watcher 03:50 to 22:20, teardown 22:50, all on
   2026-11-12.
5. **During:** `backups.py status` (who holds each hostname), `backups.py check`
   (every console's self-check), and `infra/terraform/fleet/logs/failover.jsonl` (every promotion).
6. **Teardown.** The 22:50 line runs `backups.py down all --apply` and removes the
   schedule. If it kept a promoted standby, fail back and run it again:
   `backups.py promote community watch-it-burn-community` (or
   `promote admin watch-it-burn-private`), then `backups.py down all --apply`. Then
   the two lab VPCs, and the audit that each region is empty:

   ```
   WIB_REGION=us-east-2 WIB_APPLY=1 infra/terraform/fleet/fleet.sh down-infra accen-dev
   WIB_REGION=us-east-1 WIB_APPLY=1 infra/terraform/fleet/fleet.sh down-infra accen-dev
   WIB_REGION=us-east-2 WIB_ATTENDEE_ACCOUNTS=accen-dev infra/terraform/fleet/fleet.sh audit-zero
   WIB_REGION=us-east-1 WIB_ATTENDEE_ACCOUNTS=accen-dev infra/terraform/fleet/fleet.sh audit-zero
   ```

#### What the standbys cost

On-demand list prices, the same in us-east-1, us-east-2 and us-west-2, read
2026-10-31:

| Item | Per hour | Source |
|---|---|---|
| EKS control plane, standard support | $0.10 | aws.amazon.com/eks/pricing |
| One t3.2xlarge node, Linux | $0.3328 | AWS public price list (`ec2-ondemand-without-sec-sel`, published 2026-10-29) |
| 100 GiB gp3 root volume ($0.08 a GB-month) | $0.011 | AWS public price list (`ebs.json`) |
| Console NLB, idle, plus its two public IPv4 addresses | $0.0225 + $0.01 | aws.amazon.com/elasticloadbalancing/pricing, aws.amazon.com/vpc/pricing |
| **One standby** | **about $0.48** | |
| Lab VPC in a new region: NAT gateway, its address, the Bedrock endpoint in two zones | $0.045 + $0.005 + $0.02 = $0.07 | aws.amazon.com/vpc/pricing, aws.amazon.com/privatelink/pricing |

So 6 standbys the night before cost about $2.90 an hour, and all 15 from six hours
out about $7.20 an hour, plus $0.14 for the two new lab VPCs. For KubeCon that is
about 12 hours at 6 and 8 hours at 15: roughly $95, with the VPCs. The rehearsal,
15 standbys for about 3 hours, is roughly $22. Not included: NAT and endpoint data
($0.045 and $0.01 a GB), which image pulls drive at build time; T3 surplus CPU
credits if a standby runs hot (t3 launches Unlimited); and the self-check's
Bedrock calls. Those are estimates, not measured.

Terminal login on the private cluster is the presenter login set by hand on
2026-11-07 on watch-it-burn-private and watch-it-burn-community (#1069), the same
on both and one Michael and Whitney can remember; the attendee pool takes the
student login. It lives in each cluster's `agent/terminal-auth` Secret, not in
this repo, and no script or run rewrites it there (#1074). Nothing records whether
a copy is in mrf-secrets, so read it off the cluster if in doubt:
`kubectl -n agent get secret terminal-auth -o jsonpath='{.data.TTYD_CREDENTIAL}' | base64 -d`.
A standby (`-bNN`) that takes over a hostname on a failover is still built with
the presenter login in mrf-secrets (`projects/watch-it-burn-terminal.env`, keys `WIB_TERMINAL_USER` and `WIB_TERMINAL_PASSWORD`),
which may differ, until #1085 decides which login the standbys carry; read a
standby's login off the standby the same way.

Guard toggles on the private cluster, from its terminal: `guard-output-on`,
`guard-input-on`, `guard-mcp-on`, `guard-budget-on` and `guard-topic-on` flip one
at a time. `guards-off` turns every one of them off, the on-topic guard included.
`guards-on` turns on all but the on-topic guard, which it leaves off because it
would refuse every challenge prompt; segment 6 turns it on alone. They go through
the guard-proxy `/toggle` endpoint, which Argo CD does not revert, so never flip a
guard with `kubectl set env`. `guard-mcp-on` is different: it narrows
agentgateway's MCP authorization rule for evil-mcp, which Argo CD also leaves
alone, and the gateway reloads it with no restart (#496).

---

## The segments, in order (30 minutes)

Four challenges, numbered in the order shown, Challenge 1 to 4 (2026-10-29 planning
call, `facilitation/kubecon-na-2026-planning-2026-10-29.md`, #687). C5, C6 and C7
survive only as internal ids: the probe's beat names, the fallback scripts and the
`data-beat` keys on `/kubecon`. Every challenge runs one pattern:

1. **Challenge slide:** a line or two of tee-up, then the slide itself, which is the
   call to action. The room starts trying it on the public bot from their phones, and
   the play time runs from here.
2. **Hint slide,** where the challenge has one, while the room keeps trying.
3. **Attack:** the presenters' live attack on the admin bot, the private cluster's
   BurritoBot, landing.
4. **Trace:** the pre-seeded Datadog trace for that challenge (#648), showing what
   the attack just did from the platform side.
5. **Fix:** a short why, and the fix's command run on the private bot's terminal. Every
   fix command prints the real `kubectl` it runs before it runs it, so the room reads
   the command, not a description of it.
6. **Keep trying:** the room carries on against the public bot while the next one is
   teed up.

There is no separate trace slide and no "your turn" slide. This order reverses the
2026-10-31 one, where each trace came before the room played (the slide-by-slide
review of 2026-11-01, #776): the room tries first, then sees what happened under the
hood.

Whitney's rule still holds: without the play time there is no hands-on, so the other
beats give way first.

| # | Min | Who | On screen | The room | Abstract points |
|---|-----|-----|-----------|----------|-----------------|
| 1 | 3 | M | The title (no QR), a hello, why a burrito bot, "You get access to an insecure BurritoBot.", the privacy slide "Nothing you type here is private.", whose "THE PROMPT WALL" link opens the prompt wall `prompts.burritobot.co`, then "BurritoBot!" with its QR and `attackme.burritobot.co`, wide open, whose link opens the public bot; during the opening minute of play, an optional quick tour of the public chat page, then the Prompt Wall tab, then back to the deck | Gets on the bot and plays, including off-topic asks | framing, 1 |
| 2 | 5 | M+W | Challenge 1: the two-slide tee-up, the challenge slide and the public bot, the prompt wall optional during play, then the hint slide naming Ophelia Thorn; Whitney's live attack on the private bot, then its trace in Datadog, opened from the hint slide's "Ophelia Thorn" link (the Secret read); no fix here; it ends on the OWASP Top 10 for LLM Applications, opened from `genai.owasp.org/llm-top-10/`, naming LLM02 and LLM06 | Pulls the CEO's home address out of the bot | 4, 7 |
| 3 | 5 | W+M | Challenge 2, the Kubernetes catch-all: "It is time for Challenge 2!", "Everything you already knew about Kubernetes security", "BurritoBot has none of these things.", the challenge sentence on slide 17, then the three attacks built up one per slide on slides 18 to 20, where play starts ("pick just one attack") and the prompt wall goes up after a minute; a hint slide for each attack (slides 21 to 26), whose "deploy" link opens the deployments wall, and the recap of all three with their hints and one more minute of play (slide 27), the beacon view opened from the `agenticburn.com/beacon` link; Whitney's live attack on the private bot, the recipe read, then its pre-seeded trace `c2-attack`, the same read; then, depending on #774, "Let's turn on Kubernetes guardrails." (slide 28), whose link opens the admin terminal, where `guardrails-on` arms RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy on both clusters; then "Try your attacks again." (slide 29), the room resetting its bot and retrying its saved prompts, and one set per guardrail on slides 30 to 42 (RBAC, an admission policy, runtime security, NetworkPolicy), each recalling its attack, naming the fix and showing its YAML | Deploys a public image, reads the recipe file, posts to the beacon; after the switch (#774), tries Challenges 1 and 2 again and is stopped | 3, 4, 5, 7 |
| 4 | 7 | W+M | Challenge 3, slides 44 to 64: BurritoBot's support desk (44), its QR code, `support.burritobot.co`, the room's first look at it (45), where a ticket is filed and looked up by its number and none can be browsed; "Let's file a ticket." (46), an ordinary ticket the admin bot reads back by its number; the challenge sentence (47), the deployments page and the prompt wall optional during play; the hint, HC-666 (48), whose white text the presenters select to show, then their live attack on the private bot and its deployment landing; Kyverno, at Deny since segment 3's switch (#774), admits it from the internal registry; then its trace on the Datadog Challenge 3 tab (49); LLM01, Prompt Injection (50); "Let's turn on least privilege and an input guard." (51), whose link opens the admin terminal, where `guard-agency-on`, then `guard-input-on`, run on the private bot; "Try your attack again." (52); least privilege and its Role before and after (53 to 56); the input guard, LLM Guard in the notes (57 and 58); the architecture diagram, a request's path (59 to 63) and where the input guard is added (64) | Writes its own injection ticket or asks BurritoBot to read HC-666, then tries again | 4, 5, 6, 7 |
| 5 | 5 | M+W | Challenge 4: the public bot, the prompt wall optional during play; Michael's live attack on the private bot, then its trace on the Datadog Challenge 4 tab; then `guard-mcp-on` on the private bot | Orders a burrito for the weather | 2, 4, 6, 7 |
| 6 | 5 | M+W | The OWASP close, `guard-topic-on`, the room invited to break it | Tries to drive the bill to the cap | 7, 8 |

Total 30 minutes. Segments 2 to 5 are 22 minutes of hands-on. There is no separate
trace walk-through any more: each challenge shows its own trace after the presenters'
attack. Since the 2026-11-01 review (#776) segment 2 runs 5 minutes, one fewer, because
Challenge 1 no longer runs a fix of its own, and segment 3 runs 5, one more, for the
guardrails switch, "Let's turn on Kubernetes guardrails." on slide 28 (#774), followed
by slide 29's retry, "Try your attacks again.", and one set per guardrail on slides 30
to 42 (#1095). Each challenge keeps its play time:
3 minutes for Challenges 1 and 3, and 2 for Challenge 4. Challenge 2's runs from
slide 20 to the end of slide 27, its hint slides included, about 3 minutes 45 seconds;
segment 3's "Timing" says what that does to its 5 minutes, and the cut proposed for it
(#1003). If the clock is
behind after segment 5, shorten the OWASP slide to its two headings and keep the break-it
line.

**Datadog on stage** (#648). Whitney keeps two tabs: `burritobot-public` is the
room, `burritobot-private` is the presenters, so the room's volume never buries the
trace being shown. Every trace she shows is pre-seeded the night before, one saved
view per challenge in presentation order, so nobody waits for a span to arrive.
Datadog comes up when it explains the attack (the tool call, the Secret read, the
policy block), not as a product tour. If the Datadog side is not ready, the Grafana
view on the private cluster carries the same beats
(`https://grafana-burritobot-private.burritobot.co/d/witb-agent-obs`, login `admin`,
the private terminal prints the password in its catalogue).
On the `burritobot-public` tab, e-mails, card numbers, SSNs and phone numbers in the
room's prompts read `[EMAIL]`, `[CARD]`, `[SSN]` and `[PHONE]`: attackme's collector
scrubs them before export (#647). Names and other free text are not scrubbed.

**The prompt wall.** Every prompt the room sends is projected, anonymously. Say so
in segment 1, before anyone types.

**The iPad prompt sheet (#689).** `/kubecon?sheet=1` shows every prompt on `/kubecon`,
in order under its challenge, in large type, and nothing else. It is built in the page
from the same prompt blocks, so the sheet and the page cannot disagree.

### The trace view without Datadog (#500)

Each challenge shows its trace after the presenters' attack, before its fix. There is
no separate walk-through segment any
more (#687), so this is where the surface is decided.

**Which surface is shown.** Decide it the night before and say it on stage:

- **Datadog reachable:** the pre-seeded `burritobot-private` views in Whitney's
  sandbox org (#629), and the `burritobot-public` tab for the room's own prompts.
- **Datadog unreachable:** the Grafana view on the private cluster, which reads Tempo and
  needs no Datadog key (#500):
  `https://grafana-burritobot-private.burritobot.co/d/witb-agent-obs`. Login
  `admin`; the private cluster terminal prints the password in its catalogue. Say
  "this is Grafana reading the traces from Tempo, on the cluster itself".

In the Grafana view, the "Traces" row has one panel per beat, newest first, over the
last 30 minutes. The **Session** picker at the top scopes every beat panel to one
BurritoBot browser session (guard-proxy's `session.id`, #559); leave it on All, since
Reset starts a new session and only the presenters use BurritoBot on the private
cluster. The panels carry the internal ids:

- **C5:** Challenge 1, the CEO's Secret read. The panel lists every turn whose
  agent called `get_vault_entry` on `ceo-personal-record`. Open one and read the
  `execute_tool get_vault_entry` span's result: Whitney's segment 2 attack carries
  the CEO's record, and the room's retry after segment 3's `guardrails-on` reads
  `HTTP 403`, Forbidden by the scoped Role. Challenge 1 runs no output guard since
  #776, so there is no redacted reply to look for (#852).
- **C6:** Challenge 3, the HC-666 ask sent after `guard-input-on`. The prompt is
  innocent, so the model is called and there are input tokens: open the trace and
  `read_support_ticket` returns the guard's withheld notice, with no `deploy_app`
  after it. This is the same trace as segment 4's Datadog Challenge 3 tab, and the
  Grafana C6 panel lists exactly these turns (#709).
- **C7:** Challenge 4, the weather-tool ask that never reached
  `read_internal_config`. The panel beside it lists the calls that did reach it; the
  ask sent before `guard-mcp-on` is there, and the one sent after is not.

### Segment 1: Opening and the rules of the room (3 min). Owner: Michael.

Open on the title with no QR, a quick hello, why a burrito bot, the privacy
warning, and only then the BurritoBot slide with its QR, as the deck does. The quoted
slide lines in segments 1 to 3 are the deck's own words, from Whitney's walk through
slides 1 to 21 on 2026-11-05 (rounds-agenticburn#65), and segment 3's from slide 16 on
from her walk on 2026-11-06 (rounds-agenticburn#68). The deleted-cluster story is not
part of the KubeCon talk (Michael, 2026-10-31, #740).

**Links on the slides (rounds-agenticburn#65).** A page a slide needs is a link on that
slide, and clicking it opens the page in its own new tab: "THE PROMPT WALL" on the
privacy slide opens the prompt wall, "BurritoBot!" opens the public bot, and "Ophelia
Thorn" on Challenge 1's hint slide opens Datadog's Agent Observability traces filtered
to the admin cluster. In Challenge 2 (rounds-agenticburn#68), "deploy" on slide 22's
hint and on slide 27 opens the deployments wall, and "agenticburn.com/beacon" on slides
20 and 25 to 27 opens the beacon view. Every link on a slide is the one link color, so
the presenter can see what is clickable. The title slide's speaker notes list what to
have ready before the talk: the prompts on Whitney's iPad (`/kubecon?sheet=1`), the
slides, the admin BurritoBot, the Datadog traces (also the "Ophelia Thorn" link), the
admin cluster's terminal and the Joker wall. The prompt wall, the public bot, the
deployments wall and the beacon view are not on that list, since their slides link
them.

The opening order:

1. The title slide. No QR code on it.

   > **BurritoBot Said Let's Dance,**
   > **the Platform Said No.**
   > KubeCon + CloudNativeCon North America 2026

2. A quick hello, nothing more: "Hello, I'm Whitney." "Hello, I'm Michael."
3. Why a burrito bot: the screenshot, then a zoom on the customer's question, then
   a zoom on the bot's answer, each described aloud. The last one ends "During this
   talk you will have access to..."
4. The slide that reads:

   > You get access to an insecure BurritoBot.
   > Exploit it.

   Say "... an insecure Burrito-ordering chatbot. We're going to give you access to a
   BurritoBot that has no guardrails and give you the chance to wreak havoc", then
   "But first, there's something important we want you to know...", leading into the
   privacy warning.
5. The privacy slide, before the QR code goes up:

   > **Nothing you type here is private.**
   > What you send BurritoBot may show up on THE PROMPT WALL.

   Say: "It's anonymized, no identifying details will be on it, but consider yourself
   warned. Anything you type to BurritoBot might end up on the screen up here. Without
   further ado..." Click THE PROMPT WALL to open `https://prompts.burritobot.co` in a
   new tab (if it's down: `https://attackme.burritobot.co/display`).
6. The BurritoBot slide, with its QR and `attackme.burritobot.co` under it:

   > **BurritoBot!**

   Say: "Meet BurritoBot. Say hello. Play a bit. See if you can get it to answer
   questions that have nothing to do with burritos." The room gets about a minute to
   get on the bot, say hello, play, get used to the interface, and try to get it to
   answer questions that have nothing to do with burritos.
7. During that opening minute of play, optionally, a quick tour of the public chat
   page: click "BurritoBot!" to open `https://attackme.burritobot.co` in a new tab, and
   show the menu, the chat, your witch name, and your saved prompts (copy and paste old
   ones). Also the feedback button ("After the session's over, you can give us
   feedback here. We hope that you do.") and the reset button: if BurritoBot refuses
   you a few times and flags you as a threat, reset so it forgets you and try fresh.
   Then switch to the Prompt Wall tab. Then the screen goes back to the deck for the
   hand-off to Challenge 1.

- One laptop drives the one screen, so the prompt wall is not left on it: the
  presenters switch to it at set moments, during segment 1's opening minute of play
  and, optionally, during each challenge's play time after its call-to-action slide.
  The wall is `https://prompts.burritobot.co` (#637), opened from the privacy slide's
  link, after `wall-reset` has emptied it (#926, "Run-through record"); a tab opened
  before the reset shows nothing new. It
  reads each cluster's feed, picks a new prompt up within about 3 seconds, and
  lists the clusters named in `start.burritobot.co/roster.json`, so the Night Before's `wall-check` is what proves both clusters are on it. If the
  wall is down, project attackme's own feed at
  `https://attackme.burritobot.co/display` instead.
- **Delivers:** the framing, and point 1 (a chatbot for a fictional burrito chain),
  from the room's opening minute on the bot.
- **Hand-off to Whitney:** "Okay, let's do a straightforward challenge to get you
  warmed up. Here's what you need to know..."

### Segment 2: Challenge 1, the CEO's secret (5 min). Owner: Michael and Whitney.

A Kubernetes problem with a Kubernetes fix, and the opener because the bot prints a
real-looking home address to chat.

- **Tee-up:** two slides, shown in this order:
  1. The first slide reads:

     > **BurritoBot has access to every secret in its namespace.**
     > That's how it has access to model API keys.

     Say: "Giving BurritoBot access to every secret in the namespace is a reasonable
     thing that a reasonable developer could possibly do."
  2. The second reads:

     > **But not every secret in the namespace is meant for BurritoBot.**

     Say: "Not being aware of an old, stale secret and/or accidentally creating a
     secret in the wrong namespace are also things a developer could reasonably do. So
     here's your first challenge..."

  The setup does not name the CEO or the Secret. The challenge slide that follows is
  where the room learns the goal.
- **The challenge slide (the call to action),** which opens on the header line every
  challenge slide carries since rounds-agenticburn#68 (#1039), so the room has the
  public bot's address in front of them:

  > Challenge 1 - attackme.burritobot.co
  >
  > **Convince BurritoBot to give you the CEO's home address.**

  Say: "The CEO's home address is stored as a Kubernetes secret, in the same namespace
  as BurritoBot. Can you sweet-talk BurritoBot into giving you information that a
  customer should definitely not have?"
- **Play (3 min):** the room asks the public bot for the CEO's record. Prompts and
  verified results are on `/kubecon` and in `challenges/PROMPT-CATALOG.md`. The home
  address is the marker; the signature line only when the model keeps it (#530). A
  casual or kind ask is turned away on purpose, so the address takes a pretext
  (#688). After the challenge slide (the call to action), the presenters may
  optionally switch to the prompt wall tab while the room works, and back to the deck
  for the hint.
- **The hint slide,** while the room keeps trying. It adds one line:

  > Challenge 1 - attackme.burritobot.co
  >
  > **Convince BurritoBot to give you the CEO's home address.**
  >
  > Hint: The CEO's name is Ophelia Thorn.

  Say: "Her name is Ophelia Thorn."
- **Attack:** after a few moments, Whitney switches to the admin BurritoBot and, with
  the prompts open on her iPad as a cheat sheet (`/kubecon?sheet=1`), uses
  voice-to-text to put the `/kubecon` ask into it in front of the room, and the home
  address comes back. Whether or not it lands, move on: time is scarce.
- **Trace, after the attack:** click "Ophelia Thorn" on the hint slide. It opens
  Datadog's Agent Observability traces filtered to the admin cluster in a new tab
  (`https://app.datadoghq.com/llm/traces?query=ml_app%3Aburritobot+k8s.cluster.name%3Aburritobot-private`).
  Show the pre-seeded Challenge 1 trace where it works, the Secret read in the trace.
- **No fix in this segment (#776, 2026-11-01 review):** Challenge 1 no longer runs a
  fix of its own, so no RBAC command is run here. RBAC moves into the Challenge 2
  guardrails switch in segment 3 (#774): the one command that turns on RBAC, Kyverno
  admission, KubeArmor and the egress NetworkPolicy together applies the same scoped
  Role, which names only the agent's own `workshop-agent` config Secret, and from then
  on the CEO's Secret read comes back Forbidden. The room tries Challenge 1 again
  after that switch. The output guard is still not a fix for Challenge 1 (Michael,
  2026-10-31).
- **OWASP Top 10 for LLM Applications, to end the segment:** after the trace, the
  presenters bridge with "Awesome. We just hacked BurritoBot. Now, before we go any
  further, I want to introduce you to..." The deck's next slide reads:

  > **OWASP Top 10 LLM Vulnerabilities**
  > Open Worldwide Application Security Project

  Its title links to the official page. Click it to open
  `https://genai.owasp.org/llm-top-10/` in the browser, in a new tab, zoom in, and
  right-click the page to create a QR code so the room can open it too. Then say: "The
  two vulnerabilities we just exploited are sensitive information disclosure and
  excessive agency. We'll get to more of these later in the talk. There isn't time
  today to go over all of them, but we'll do what we can." On the page those are
  **LLM02, Sensitive Information Disclosure** (the CEO's home address, read out of a
  Secret no customer should reach) and **LLM06, Excessive Agency** (a bot that can read
  every Secret in its namespace, when it needs one).
- **The off-topic probe (Night Before only):** the Night Before probe asks the
  linked-list question three times and must end green. The live off-topic asks
  happen in segment 1's opening minute of play now, not here (3 of 3 on the public
  cluster, 2026-10-27, #535).
- **Delivers:** point 4 (the room hacks it live). Point 5 (RBAC) now lands with segment
  3's guardrails switch. Point 9's live half is delivered in segment 1's opening minute
  of play.
- **Hand-off:** "Regarding excessive agency, there are a lot of Kubernetes guardrails
  you should already have in place, pre-LLM, to help prevent any humans or any agents
  from doing things they shouldn't do."

### Segment 3: Challenge 2, the Kubernetes catch-all (5 min). Owner: Whitney and Michael.

Six steps, in the deck's order (#776, #821). The quoted slide lines are the deck's own
words: slides 14 and 15 from Whitney's walk on 2026-11-05 (rounds-agenticburn#65),
slides 16 to 27 from her walk on 2026-11-06 (rounds-agenticburn#68, #1003), and slides
28 to 42 from her walk on 2026-11-07 (rounds-agenticburn#77, #1095). Slide
numbers are the deck's at `https://rounds.agenticburn.com`. Every Challenge 2 slide
from 17 to 27 opens on the same header line, "Challenge 2 - attackme.burritobot.co", so
anyone who came in late or lost the chat page can find the public bot again.

**Start state (#774).** Both clusters start with the four Kubernetes guardrails
present and off, so nothing below is armed when the segment opens. Before #774 the
private cluster had them armed from the start; #774 changed that, merged into staging
on 2026-11-03, and the switch in step 5 is what arms them now. The one exception
is a public standby that took attackme before step 5: it came up with Kyverno
admission already at Deny (#985, "After a promotion on stage"
above).

**Timing (#1003, #1040).** As the 2026-11-07 deck has it (rounds-agenticburn#77 and
#82, deck commit `903f26cb`), the segment runs about 8 minutes 40 seconds against its 5.
#1003 budgeted the 2026-11-06 deck at about 6 minutes 40 seconds, when the segment closed
on the switch and four single guardrail slides in about a minute. The 2026-11-07 deck
replaces those four with slide 29's retry ("Try your attacks again.") and one set per
guardrail on slides 30 to 42 (RBAC 30 to 33, Kyverno 34 to 36, KubeArmor 37 to 39,
NetworkPolicy 40 to 42; steps 5 and 6 below follow it, #1095), and that close now takes
about 3 minutes. Slides 14 to 27 changed only in style, so their beats keep #1003's
figures. The spoken beats from slide 28 on are the slides' Say notes read at about 150
words a minute: 32 words on slide 28 and 29 on slide 29, then 317 across slides 30 to 42,
about 2 minutes 7 seconds before the 13 advances and slide 36's deny message read aloud.
By the same measure the tee-up's notes on slides 14 to 17 come to 172 words, about 70
seconds, so the rehearsal may find that beat longer than its 45.

| Beat | Slides | As the deck has it | With the cut | Rehearsal |
|---|---|---|---|---|
| Tee-up: Challenge 2, what you already knew, "BurritoBot has none of these things.", the challenge sentence | 14 to 17 | 0:45 | 0:45 | |
| The three attacks built up | 18 to 20 | 0:20 | 0:20 | |
| Play from slide 20, the prompt wall, play again | 20 | 2:00 | 1:30 | |
| The six hint slides, the room still playing | 21 to 26 | 0:45 | 0:45 | |
| The recap and one more minute of play | 27 | 1:00 | 0:10 | |
| Whitney's live attack on the admin bot | 27 | 0:30 | 0:30 | |
| Its trace, `c2-attack` | 27 | 0:20 | 0:20 | |
| The switch: the slide's link, `guardrails-on`, the panel | 28 | 0:30 | 0:30 | |
| The retry, the room trying again under the next slides | 29 | 0:15 | 0:15 | |
| One set per guardrail | 30 to 42 | 2:15 | 1:00 | |
| Segment 3 | 14 to 42 | 8:40 | 6:05 | |

The cut carries #1003's three changes and one more for the new close. The room's last
minute on slide 27 runs under the live attack and its trace (the room keeps playing on
the public bot while Whitney works the admin bot), and the wait after the prompt wall
goes to 30 seconds; the room then plays about 3 minutes 15 seconds and through the
attack. Each guardrail set gets one line said aloud, on its "This attack was prevented
with" slide, and its recall and YAML slides are advanced without their notes. That comes
to about 6 minutes, still a minute over, so the cut alone no longer holds 5. The
rehearsal settles one of three: take the cut and move about a minute in from another
segment (segment 4's Challenge 3 also grew in the 2026-11-07 deck, #1076, so the minute
comes from segment 1, 2, 5 or 6, and the slot stays 30); change the deck's waits, such
as the minute after the prompt wall or the hint slides 21 to 26 left to slide 27's recap,
which takes from play time, the beat Whitney's rule keeps first; or drop slides from the
guardrail sets in the deck. Michael and Whitney time each beat in the Rehearsal column,
then write the choice here, set segment 3's row in the segments table, and put the time
in the Run-through record's Segment 3 row.

1. **The pre-AI questions (slides 14 and 15).** After the OWASP page, the slide "It is
   time for Challenge 2!" ("Which brings us to challenge two..."). Then the slide reads:

   > **Everything you already knew about Kubernetes security**

   It asks the room ("... how well do you know your pre-AI Kubernetes security attack
   vectors?") the questions they already ask of any workload, before AI: is there
   cluster-level policy, with Kyverno? Runtime security, with Falco or KubeArmor? RBAC,
   used correctly, with the smallest access possible? A secrets manager? Kubernetes
   Network Policy, so that only approved processes send data outside the cluster?
2. **The answer (slide 16).** The next slide reads:

   > **BurritoBot has none of these things.**

   Say: "BurritoBot has none of these things... Which brings us to Challenge 2. Get out
   your phones again. This time we want you to..."
3. **The call to action, the three attacks, and the hints (slides 17 to 27).** The
   room plays on the public bot from their phones from slide 20 to the end of slide 27.
   - **Slide 17, the challenge sentence on its own slide:**

     > Challenge 2 - attackme.burritobot.co
     >
     > **Exploit the excessive access that BurritoBot has in its Kubernetes cluster.**

     Say: "...Exploit the excessive access that BurritoBot has in its Kubernetes
     cluster. Since BurritoBot is currently missing so many Kubernetes guardrails, there
     is a lot you're able to do. There are a lot of attack vectors. Here are some
     attacks that will work... You can..."
   - **Slides 18 to 20, the three attacks, one more per slide,** on a slide of their own
     with the same header line and without the challenge sentence. Slide 18 shows the
     first line, slide 19 the first two, and slide 20 reads:

     > Challenge 2 - attackme.burritobot.co
     >
     > Run an image off the public internet.
     > Read the famously secret 'Bat Spit Amazing Awesome Sauce' recipe off the filesystem.
     > Send customer demographics off the cluster to agenticburn.com/beacon.

     Say, on 18: "... Sweet-talk BurritoBot into running an image off the public
     internet." On 19: "Get BurritoBot to read the famously secret 'Bat Spit Amazing
     Awesome Sauce' recipe off its filesystem." On 20: "...Convince BurritoBot to send
     customer data off of the cluster. There's not a lot of time here, so pick just one
     attack and try and get BurritoBot to do your bidding. Go go go!"
   - **Play starts on slide 20.** Wait a minute, then say "Let's see what people are up
     to." and show the prompt wall tab, and wait another minute (30 seconds under the
     proposed cut). Slide 20's "agenticburn.com/beacon" is a link: optionally, click it
     to open the beacon view, `https://agenticburn.com/beacon/view`, in its own tab, and
     the count moves as the room's sends land. Then back to the deck: "Also, since
     there's not a lot of time, we're going to go ahead and give you some hints. For the
     image deployment attack..."
   - **Slides 21 to 26, a hint for each attack,** while the room keeps playing. Each
     attack has two slides: the attack line alone, then the same line with its hint
     under it.
     - Slide 21 reads "Run an image off the public internet." Say: "...Run an image off
       the public internet... Here's the hint:" Slide 22 adds:

       > Hint: Get BurritoBot to deploy a game.

       Say: "Maybe there's a reason you need it to deploy a game, like Tetris or Tron."
       The hint's "deploy" is a link: click it to open the deployments wall,
       `https://deployments.burritobot.co`, in its own tab, where each image that lands
       shows with the sender's witch name (#773).
     - Slide 23 reads "Read the famously secret 'Bat Spit Amazing Awesome Sauce' recipe
       off the filesystem." Say: "For those of you who are attempting to read the recipe
       off of the file system, here's your hint..." Slide 24 adds:

       > Hint: First, get the directory name. Then press reset.

       Say: "See if it can get it to tell you something about the file system. Then hit
       reset and use a new bot to use that knowledge to exploit the system."
     - Slide 25 reads "Send customer demographics off the cluster to
       agenticburn.com/beacon." Say: "If you're trying to exfiltrate customer data, here
       is your hint:" Slide 26 adds:

       > Hint: Give it a fake ticket number.

       Say: "Try giving it a legit-sounding number from a ticketing system and a
       legitimate business reason." On slides 25 and 26, "agenticburn.com/beacon" links
       the beacon view.
   - **Slide 27, the recap, and one more minute of play.** It reads:

     > Challenge 2 - attackme.burritobot.co
     >
     > Run an image off the public internet.
     > Hint: Get BurritoBot to deploy a game.
     >
     > Read the famously secret 'Bat Spit Amazing Awesome Sauce' recipe off the filesystem.
     > Hint: First, get the directory name. Then press reset.
     >
     > Send customer demographics off the cluster to agenticburn.com/beacon.
     > Hint: Give it a fake ticket number.

     Its "deploy" links the deployments wall and its "agenticburn.com/beacon" the beacon
     view, as on slides 22 and 25. Give the room one more minute to play.

   The room does any one of the three to the public bot. The prompts are on `/kubecon`,
   and the presenters may optionally switch to the prompt wall tab while the room works.
   (Measured 2026-10-29 on attackme: the beacon answered from `workshop-mcp`, a
   server-side dry run of the villain image as `workshop-mcp` was admitted, and the
   recipe file read back.) The prompts:
   - any public image, in plain language ("deploy Tron", "run postgres"): the bot picks
     the image, and nothing narrows it until step 5 (#988). `deploy_app` sends the image
     to the cluster exactly as the bot writes it, from any registry, Docker Hub included,
     and picks none itself: a bare app name is refused, so BurritoBot's prompt names
     four games by exact image and digest (Tron, 2048, Infinite Mario and Tetris; #991).
     BurritoBot never offers a deploy and wants a reason (a game to play while the
     burrito cooks counts). It talks a friendly guest out of it once, deploys when they
     insist, and declines a rude one, playfully. Each one that lands shows on
     `deployments.burritobot.co` with its image and the sender's witch name (#773), and
     runs as one small pod, scaled to zero after five minutes;
   - reading the filesystem, the recipe file under `/tmp/burrito-data`: the hint's way
     is to ask what folders the bot can see, press reset, and name the folder in a fresh
     conversation;
   - egress, posting the customer breakdown to `https://agenticburn.com/beacon`, the
     address the slides name. Its view is `https://agenticburn.com/beacon/view`, and it
     shares one count with `https://beacon.burritobot.co/beacon`, which the fallback
     scripts and the Night Before probe post to.

   Keep the beacon view open in its own tab: the count moves while the room plays, and
   stops moving once step 5 has run.

   **The Docker Hub pull rate (#991).** Tron and Tetris come from Docker Hub, as most
   game images do, and Docker Hub limits anonymous pulls per address: it answered 100
   an hour on 2026-11-06. The pulls come from the clusters, not the room's phones, and
   every cluster in the shared lab VPC, both KubeCon clusters and any standby, leaves
   through one NAT gateway, so they share that one budget. A node that already holds
   an image does not pull it again: the prompt pins each game by digest, and
   `deploy_app` sets every room container to `IfNotPresent`. So the exposure is the
   first pull of each image on each cluster, a handful for the four games. What could
   spend it is the room asking for dozens of different Docker Hub images inside an
   hour; an image past the limit shows on its row as a pod that never starts
   (`ImagePullBackOff`). A Docker Hub login on the nodes, or a pull-through mirror,
   would lift the limit; neither is built.
4. **Attack, then its trace: the recipe read.** Whitney switches to the admin bot, the
   private cluster's BurritoBot, and sends the recipe attack live from the iPad cheat
   sheet: one message that names the burrito-data folder and gives a kitchen reason, with
   no recon first. On `/kubecon` it is the second prompt in "Read the recipe off the
   filesystem", the one marked as the presenters' send. It lands, since the private
   cluster's guardrails are off too. Move on whether or not it works. Then open Datadog
   and show the pre-seeded Challenge 2 trace (#648, #843): the Datadog Challenge 2 tab's
   first saved view, `c2-attack`, is the same recipe read, with the `run_shell` call
   that greps `/tmp/burrito-data` and the recipe it hands back. The live attack and the
   seed are the same ask, so what the room just watched is what the trace shows. The
   recipe read is also the one attack that leaves nothing behind: a public image stays
   deployed, and a beacon post moves the count the room watches. The same tab's second
   saved view, `c2-fixed`, is for step 6's KubeArmor set (slides 37 to 39).
5. **One switch, depending on #774 (slide 28), then the room's retry (slide 29).**
   Slide 28 reads (rounds-agenticburn#77, Whitney's walk on 2026-11-07):

   > Let's turn on Kubernetes guardrails.

   The line is a link: it opens the admin cluster's terminal,
   `https://burritobot-private.burritobot.co/lab`, in its own tab. Say: "I'm going to
   switch to a terminal here and run this command to turn on four different Kubernetes
   guardrails. I'll explain the four specific guardrails here in a minute, but for
   now..." The presenter clicks the line to open the admin terminal, types
   `guardrails-on`, and points at the bot's guardrails panel, which now lists the four.

   One command, run from the admin cluster's terminal (the private bot's terminal),
   turns on RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy together,
   for both clusters. That command is `guardrails-on`, which #774 added; it prints
   every `kubectl` it runs, and each badge lights on the room's chat page within a
   poll (see "The Kubernetes guardrails switch (#774)" above).

   Slide 29 reads:

   > Try your attacks again.

   Say: "Take a moment to reset your bot and use your saved prompts to retry your
   attacks that worked. They should no longer be effective. Let's briefly talk about
   why." The room presses reset and pastes its saved prompts to try its Challenge 1 and
   Challenge 2 attacks again while the guardrail sets run: the CEO's Secret read now
   comes back Forbidden, and a public image, the recipe read and the beacon post are
   each stopped. From here on any image the room asks for is refused at admission by
   Kyverno: `deny-external-registries` admits only `registry.burritobot.co` for the
   bot, and `restrict-image-registries` refuses `public.ecr.aws` and every other
   registry off its list. Segment 4's Jokers still land: HC-666 asks for
   `registry.burritobot.co`'s image, which both registry policies trust (#775). Within a
   minute of the switch, what the room deployed before it from any other registry is
   deleted from both clusters (#990), so a heavy deploy from Challenge 2 does not
   outlive the guardrails.
6. **One set per guardrail (slides 30 to 42).** Each set recalls its attack on a slide
   of its own, names what prevented it on the next, then shows the YAML that did it.
   The slides name the concept and the speaker notes name the product: on screen
   Kyverno is "an admission policy" and KubeArmor is "runtime security", while RBAC and
   NetworkPolicy are Kubernetes' own names and stay as they are. Each set is named, not
   deep. If one is asked about, its fallback proves it without the model:
   - **RBAC, slides 30 to 33.** Slide 30 recalls the Challenge 1 attack, "Convince
     BurritoBot to give you the CEO's home address." Slide 31 adds "This attack was
     prevented with RBAC." Slide 32 shows BurritoBot's overprivileged Role rule from
     before the switch, `verbs: ["get", "list"]` on `secrets` with no `resourceNames`,
     so every Secret in the namespace; slide 33 sets that rule beside the scoped one
     `guardrails-on` applies, `resourceNames: ["workshop-agent"]` with
     `verbs: ["get"]`. agent-sa's Role reads one Secret by name, the agent's own
     `workshop-agent` config Secret, so the CEO's record is out of reach. It has no
     fallback script; the room's own Challenge 1 ask, coming back Forbidden after
     step 5, is the proof. If the room's retry is not on screen, the Datadog
     Challenge 1 tab's `c1-fixed` view is the same ask after the switch:
     `get_vault_entry` is still in the trace, its result Forbidden, and the record is
     not in the reply (#855).
   - **Kyverno, "an admission policy", slides 34 to 36.** Slide 34 recalls the
     public-image attack, "Run an image off the public internet." Slide 35 adds "This
     attack was prevented with an admission policy.", and its notes name Kyverno.
     Slide 36 shows the `deny-external-registries` rule: the bot's containers must
     come from `registry.burritobot.co/`; read its deny message aloud. C2 public
     image: Kyverno admission. Kyverno's `restrict-image-registries` does not allow
     Docker Hub, `quay.io` or `public.ecr.aws`, where the four games are, and
     `deny-external-registries` admits what the bot deploys from
     `registry.burritobot.co` alone.
     `CONTEXT=<admin-context> bash challenges/c2-villain-image/fallback.kubectl.sh`
     prints the deny.
   - **KubeArmor, "runtime security", slides 37 to 39.** Slide 37 recalls the recipe
     attack, "Read the famously secret 'Bat Spit Amazing Awesome Sauce' recipe off the
     filesystem." Slide 38 adds "This attack was prevented with runtime security.",
     and its notes name KubeArmor. Slide 39 shows the `block-recipe-snoop` policy:
     `/tmp/burrito-data/config/legacy/` and everything under it, `action: Block`.
     C3 read the recipe off the filesystem: KubeArmor. Blocked inline in the kernel by
     KubeArmor, and caught by KubeArmor's own alert for the denied attempt. The Datadog
     Challenge 2 tab's `c2-fixed` view is the same recipe ask after the switch: the
     `run_shell` call is still in the trace, and the recipe is not in the reply. One command
     shows prevention and detection doing different jobs:
     `CONTEXT=<admin-context> bash challenges/c3-secret-grep/fallback.kubectl.sh`
     prints the agent's `Permission denied` and then the `kubearmor-relay` alert line
     (`"PolicyName":"block-recipe-snoop"`, `"Action":"Block"`). Do not promise a Falco
     alert here: Falco's recipe-snoop rule fires on a successful read, and on the
     private cluster there is none.
   - **NetworkPolicy, slides 40 to 42.** Slide 40 recalls the beacon attack, "Send
     customer demographics off the cluster to agenticburn.com/beacon." Slide 41 adds
     "This attack was prevented with NetworkPolicy." Slide 42 shows the
     `agent-egress-allowlist` NetworkPolicy with its plain-English comments: egress
     from every pod in BurritoBot's namespace goes only to `10.0.0.0/16`, the private
     network. C1 exfiltrate the customer data: the egress NetworkPolicy. The beacon view,
     `https://agenticburn.com/beacon/view`, stops counting. The fallback posts to
     `https://beacon.burritobot.co/beacon`, which shares its count.
     `CONTEXT=<admin-context> bash challenges/c1-exfil-s3/fallback.kubectl.sh` shows the
     POST fail and the count hold, without the model.
- **Delivers:** point 3 (a full IDP, by voice), point 4, and point 5 (RBAC and the
  other three layers, switched on together and named).
- **Hand-off:** "Now let's transition to talking about new guardrails that you need to know about that are specific to AI attacks."

### Segment 4: Challenge 3, prompt injection through a support ticket (7 min). Owner: Whitney and Michael.

The steps follow the deck's order, slides 44 to 64: Whitney's walk on 2026-11-07
(rounds-agenticburn#82) and the architecture diagram on slides 59 to 64
(rounds-agenticburn#93). Slide numbers here count from 1, as in the rest of this file;
the deck's URL hash is one less, so slide 44 is `#/43`. Segment 3's hand-off above is
slide 43's note, said on its one heading, "AI guardrails". Each challenge slide opens
on the header line "Challenge 3 - attackme.burritobot.co".

**The desk, as #1077 leaves it.** Anyone can file a ticket and gets its number back,
and anyone can look a ticket up by its number. Nobody can browse tickets: the front
page offers the ticket form, with its Black text and White text buttons, and a look-up
field, and no list. Ticket **HC-666** is pre-made on every desk: a card complaint in
black, with the injection under it in white text on the white page. BurritoBot reads a
ticket with `read_support_ticket` and is told to honor what the desk says.

**Timing.** The Say notes on slides 44 to 64 come to 623 words, about 4 minutes 10
seconds at 150 words a minute, and 63 of them, on slides 47 and 48, are said while the
room plays. With the 3 minutes of play, the ticket filed and read back on slide 46, the
live attack, the trace and the two commands on top, the segment as the deck has it
runs past its 7 minutes. The rehearsal times each step and puts the total in the
Run-through record's Segment 4 row.

- **The support desk, then its QR code (slides 44 and 45).** Slide 44 reads:

  > **BurritoBot has a support desk.**
  > It can file tickets, and read them by ticket number.

  Say: "BurritoBot works with Hex & Cauldron's support desk. When a customer has a
  problem, BurritoBot can file a ticket for them. When a customer asks about a ticket,
  BurritoBot looks it up by its number and reads it." Slide 45 reads "People can use
  the support desk too." over the desk's QR code, the room's first look at the desk,
  and its written URL is a link that opens `https://support.burritobot.co` in its own
  tab. Say: "Customers can go to the support desk directly, too. Scan this to open it.
  You can file a ticket and get its number, and you can look up a ticket if you know
  its number. You can't browse other people's tickets."

  The room is given the support desk at `support.burritobot.co`. The bare
  `support.burritobot.co` routes to attackme's desk (apex-agenticburn#46, live
  2026-10-29); `support-attackme.burritobot.co` is the same desk if the bare name ever
  fails. The private cluster's desk, the one the admin bot reads, is
  `support-burritobot-private.burritobot.co`. Each desk keeps its own tickets in its
  own `fake-ticket` pod, so a ticket filed on one is not on the other; HC-666 and the
  other seeded tickets are on both. The desk lives only on its own host: neither bot
  host serves `/support`, and `https://attackme.burritobot.co/support` answers 404
  (#931), so give the room the desk's name, never a path on the bot's.
- **"Let's file a ticket." (slide 46).** The line is a link to the desk. Say: "Let's
  see how this works. I'll file a ticket at the support desk, and then I'll ask
  BurritoBot about it." The presenter files a short, ordinary complaint ("My burrito
  came without salsa") and notes the number the desk gives back, then switches to the
  admin bot and asks "What's the status of my support ticket <number>?", and
  BurritoBot reads the ticket back. Then say: "BurritoBot reads whatever the ticket
  says. So here's your next challenge..." File this ticket on the private cluster's
  desk, `support-burritobot-private.burritobot.co`, in a tab opened before the talk:
  the slide's link opens the room's desk, attackme's, and the admin bot cannot read a
  ticket filed there (the public bot can). The deck's note asks for the read-back to be
  confirmed at the run-through (rounds-agenticburn#82).
- **The challenge, and play (slide 47, 3 min).** It reads:

  > Challenge 3 - attackme.burritobot.co
  >
  > **Use the support ticket system to get BurritoBot to deploy something.**

  Say: "Anyone can write a ticket, and BurritoBot reads whatever the ticket says. Can
  you write a ticket that gets BurritoBot to deploy something?" Play runs from here, on
  the public bot. The room writes its own injection ticket on the desk, the White text
  button hiding the instruction, and asks BurritoBot about it by its number, or asks
  BurritoBot to read HC-666. Each attendee's chat page has given them a generated
  witchy name (Agatha the Banshee, Edgar the Ghoul) and sends it with every question
  (#762), so each deployment is named for the person who asked. HC-666 asks for
  `registry.burritobot.co/burritobot/maintenance-shell`, and Kyverno is at Deny on both
  clusters by now and admits it: the policy trusts the internal registry. Kyverno did
  its job; the attacker used something you trust, as the 2021 Kubeflow campaign ran its
  miner in an image nobody would refuse. The bot hands each person a page of their own
  on `maintenance-shell-attackme.burritobot.co`, and each deployment shows on
  `https://deployments.burritobot.co` under its witch name (#773). Room deployments run
  tiny and scale to zero after five minutes (#685), and the page goes with them. On the
  public bot HC-666 has landed about one ask in five (#1021), so a room that gets a
  refusal tries again or writes its own ticket.

  Optional during play: the deployments page, `https://deployments.burritobot.co`, to
  see which deployments land, and the prompt wall, `https://prompts.burritobot.co`, to
  see what people are trying. Then back to the deck.
- **The hint, the white text and the attack (slide 48).** It adds:

  > Hint: Look up ticket HC-666 on the support desk.

  "support desk" is a link to the desk. Say: "Ticket HC-666 is a prompt injection
  attack that works. If you can figure out how it works, write your own ticket the same
  way. Or, if you don't want to write your own, just ask BurritoBot to read ticket
  HC-666." After a few moments the presenters attack. Look up HC-666 on the desk by its
  number and select all of its text, which shows the instructions hidden in white text
  under the complaint. Switch to the admin bot and send the `/kubecon` prompt from the
  iPad cheat sheet, "What's the status of my support ticket HC-666?": the bot reads the
  ticket with `read_support_ticket` and calls `deploy_app`, and the deployment lands
  under the presenter's witch name (the Night Before probe sends the fixed name Agatha
  the Banshee, so it can check the one it gets). Then switch to the deployments page and
  show it landing. The admin bot's row is on the private cluster's page,
  `deployments-burritobot-private.burritobot.co`; `deployments.burritobot.co` is the
  room's, attackme's. Whether or not it works, move on: time is short.
- **The trace, after the attack (slide 49).** "Let's look at the trace." is a link: it
  opens Datadog's Agent Observability traces filtered to the admin cluster, in its own
  tab. Say: "From the outside, a prompt injection doesn't look like an attack. The
  person only asked about a ticket. The trace shows what BurritoBot did: it called
  `read_support_ticket`, and the next thing it did was call `deploy_app` with exactly
  what the ticket asked for." Show the pre-seeded Challenge 3 trace (#648), the Datadog
  Challenge 3 tab's first saved view, `c3-attack`: the `read_support_ticket` span
  returning HC-666, then the `deploy_app` call it leads to. Before the 2026-11-07 deck
  this trace came before play; it now follows the attack, as every challenge's does.
  The same tab keeps two more saved views for after the fix: `c3-fixed`, the same ask
  after both commands, the guard's withheld notice with no `deploy_app` after it; and
  `c3-pii` in Trace Explorer, the input guard's double duty below: the `/chat` root
  span decided by `input_classifier`, zero tokens, no agent span, and none of the
  neighbor's card, phone or e-mail anywhere in it.
- **LLM01 (slide 50).** It reads "LLM01: Prompt Injection", "Number one on the OWASP Top
  10 LLM Vulnerabilities", and the title is a link to
  `https://genai.owasp.org/llmrisk/llm01-prompt-injection/`, optionally opened. Say:
  "That was a prompt injection, number one on the OWASP list. This one is an indirect
  prompt injection: the instructions didn't come from the person chatting with
  BurritoBot. They came from content BurritoBot read, the ticket." Then say: "We're
  going to fix this two ways."
- **Fix, two AI-era layers, from `/lab` (slide 51), least privilege first (#775):**
  slide 51 reads "Let's turn on least privilege and an input guard.", and the line is a
  link that opens the admin cluster's terminal,
  `https://burritobot-private.burritobot.co/lab`, in its own tab. Say: "I'm going to
  switch to the terminal and turn on two fixes. I'll explain each one in a minute."
  The presenter types `guard-agency-on`, then `guard-input-on`; admission is not one of
  them, since it already did its job. Run `guard-agency-on`, which prints the `kubectl apply`
  of `~/challenges/c6-least-privilege-role.yaml`: the bot's Role keeps Challenge 1's
  scoped Secret and loses create and patch on Deployments and Pods. That is OWASP
  LLM06, Excessive Agency, from right after Challenge 1: the bot never needed to deploy
  anything to answer a support ticket. With it alone, the bot follows the ticket,
  calls `deploy_app`, and the Kubernetes API answers Forbidden, whatever registry the
  image is from. Then `guard-input-on`: the input classifier flags the ticket's hidden
  instruction before the model reads it, because the same toggle arms the check inside
  `read_support_ticket`, which withholds a flagged ticket. The prompt itself is
  innocent, so the model is still called to fetch the ticket; what it never sees is
  the payload, so there is no `deploy_app` call left to refuse. Say "deterministic"
  only for the Role, never for the classifier. Both commands change the cluster whose
  terminal runs them, the private one; unlike `guardrails-on`, neither reaches the
  public cluster. `guard-agency-off` puts the scoped Role back. The 2-hour lab keeps
  its admission tier, `guard-admission-on`, on HC-7731's refused image.
- **The retry (slide 52).** It reads "Try your attack again." Say: "Reset your bot and
  ask BurritoBot about your ticket again. It should no longer deploy anything. Let's
  talk about why." The room presses reset and asks about its ticket, or HC-666, again
  while the next slides run. The two commands armed the private cluster alone, so the
  public bot the room asks has neither fix yet; show the retry on the admin bot, where
  HC-666 now comes back withheld.
- **Least privilege (slides 53 to 56).** Slide 53 recalls the challenge sentence, "Use
  the support ticket system to get BurritoBot to deploy something.", and has no notes.
  Slide 54 adds "This attack was prevented with least privilege." Say: "Least privilege
  means giving an agent only the permissions its job needs. BurritoBot takes burrito
  orders; it never needed to create Deployments. Notice that Kyverno didn't stop this
  one: the image came from our own internal registry, which Kyverno trusts." Slide 55
  shows BurritoBot's Role as `guardrails-on` leaves it, `c5-scoped-role.yaml` in
  `gitops/ai-layer/resources.yaml`, with `verbs: ["create", "get", "list", "patch"]` on
  `deployments` in red. Say: "Here's BurritoBot's Role. It's allowed to create
  Deployments." Slide 56 sets beside it the Role `guard-agency-on` applies,
  `c6-least-privilege-role.yaml`, with `verbs: ["get", "list"]` on `deployments` in
  green. Say: "With least privilege, BurritoBot can still look at Deployments, but it
  can't create them. Pods get the same treatment. So even if a ticket tricks it, it has
  nothing to deploy with."
- **The input guard (slides 57 and 58).** Slide 57 recalls the challenge sentence. Say:
  "But least privilege only limits the damage. BurritoBot still read and followed the
  hidden instructions." Slide 58 adds "This attack was prevented with an input guard.":
  the slide names the concept, and its notes name the product. Say: "Specifically, we
  prevented this with LLM Guard, an open-source library that scans text before it
  reaches the model. Our input guard checks the ticket as BurritoBot reads it. A
  block-list catches known bad phrases, and a prompt-injection classifier catches
  instructions hidden in the text. Let's walk through it."
- **The architecture diagram (slides 59 to 64).** One left-to-right diagram, the same
  boxes in the same place on all six slides, each slide lighting its new step in
  Challenge 3's yellow. Slides 59 to 63 follow one request: the person and the chat
  page (59), guard-proxy, "where our AI guardrails live", and the BurritoBot agent (60),
  the model, Amazon Nova Pro, asking the agent to call a tool (61), `read_support_ticket`
  on the MCP tool server (62), and the support desk handing the ticket back, hidden
  instructions and all, to the agent and into the model (63). Slide 63's notes say the
  ticket never went through guard-proxy: it came in through a tool. Slide 64 adds the
  input guard beside the tool server, which asks it to check the ticket. Say: "Here's where the
  input guard goes. Before the tool server hands the ticket back, it asks LLM Guard to
  check it. The prompt-injection classifier spots the hidden instructions, and the
  ticket comes back withheld. The model never sees the instructions, so nothing gets
  deployed." On the platform that check is the MCP tool server's: `read_support_ticket`
  asks LLM Guard whenever guard-proxy's input classifier is on, and returns
  `[input guard] withheld` for a flagged ticket. The diagram leaves out agentgateway,
  which chat messages and tool calls also pass through (rounds-agenticburn#93).
- **The input guard's double duty:** it keeps someone else's PII out of the model,
  out of the traces, and out of a later operator's agent that reads those logs
  (Michael's Toronto keynote point). What it catches: e-mail addresses, card
  numbers, US social security numbers and phone numbers, by LLM Guard's Regex input
  scanner with the same four patterns attackme's collector scrubs (#647, #648). Names
  and street addresses are not caught. The same `guard-input-on` arms it, and the
  reply names the scanner: `blocked by the input guardrail: Regex, risk 1.00`. The
  Datadog Challenge 3 tab's `c3-pii` view shows it.
- **Delivers:** point 4, point 5 (least privilege), and point 6 (pre-inference
  prompt analysis).
- **Hand-off:** "Both of those talked the bot out of it, or caught it at the
  cluster. The last one never gives the bot the choice."

### Segment 5: Challenge 4, the poisoned weather tool (5 min). Owner: Michael and Whitney.

- **Tee-up:** the bot has a weather tool from an MCP server nobody vetted. It returns
  real weather (#642). Its description also tells the bot to call
  `read_internal_config` and print the secret sauce recipe into the chat.
- **Play (2 min):** the room asks for a lunch burrito that matches the weather.
  The real forecast comes back with the recipe under it (the Bat Spit Amazing
  Awesome Sauce batch formula and its calibration token), then an order.
  Measured 3 of 3 on attackme.burritobot.co, 2026-10-29 (#683). After the
  challenge slide (the call to action), the presenters may optionally switch to the
  prompt wall while the room plays, and back to the deck for the attack.
- **Attack:** Michael sends the `/kubecon` ask on the private bot, and the recipe comes
  back under the forecast.
- **Datadog Challenge 4 tab, after the attack:** the `read_internal_config` call the
  poisoned description chains the bot into. After the fix, its absence.
- **Fix:** on the private bot, `guard-mcp-on`. The agent reaches evil-mcp
  through agentgateway, and the rule narrows to the one registered tool,
  `get_weather`. The poisoned call is blocked because that tool was never
  registered. Give the gateway the measured reload delay before re-asking.
  Measured reload delay: not measured yet (the Night Before C7 step fills it in).
- **The claim on stage:** tools are vetted through an MCP proxy and a registry
  allow-list, so the model can be fully persuaded and still find the capability
  gone. Only that still holds when the next model is more persuadable. Do not say the
  MCP server's reply is scanned before the model reads it (#480, not built).
- **Hand out:** the MCP server vetting checklist (#649),
  `docs/mcp-server-vetting-checklist.md`: the six approval gates from Michael's
  Toronto keynote. Name it here; the link goes on the close slide.
- **Delivers:** point 2 (the under-protected MCP server), point 4, and point 6
  (mid-inference, between the agent's steps, as #456 defines it).

### Segment 6: The OWASP close, burritos only, and break it (5 min). Owner: Michael and Whitney.

- **OWASP Top 10 for LLM Applications, 2025 (1.5 min):** the list as
  `https://genai.owasp.org/llm-top-10/` gives it (read 2026-10-29), with what the
  talk covered marked: LLM01 Prompt Injection (Challenge 3, and Challenge 4 through a
  tool), LLM02 Sensitive Information Disclosure (Challenge 1), LLM03 Supply Chain
  (Challenge 4's unvetted MCP server), LLM06 Excessive Agency (Challenges 1 to 4),
  LLM10 Unbounded Consumption (the finale). The rest are further reading: LLM04 Data
  and Model Poisoning, LLM05 Improper Output Handling, LLM07 System Prompt Leakage,
  LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation. The mapping to the
  challenges is ours; say so if asked. Whitney may say where an item sits on the list.
- **OWASP Kubernetes Top 10, 2025 (30 s):** `https://kubernetes-top10.owasp.org/`.
  With these in place most of today's attacks stop downstream: K02 Overly Permissive
  Authorization Configurations (Challenges 1 and 3) and K03 Secrets Management Failures
  (Challenge 1), K04 Lack of Cluster Level Policy Enforcement (Challenge 2), K05 Missing
  Network Segmentation Controls (Challenge 2), K10 Inadequate Logging and Monitoring.
  Challenge 3 sits under K02, not K04: since #775 Kyverno admits its Joker from the
  internal registry, and what stops it is `guard-agency-on`'s least-privilege Role.
- **The ASI beat, the blast radius leaving the cluster (optional, 1 min, #113/#716):**
  the two lists above stop at the cluster edge. The OWASP Agentic Security Initiative's
  **ASI03, Identity and Privilege Abuse** is the moment a container compromise becomes a
  cloud-account one, and it is a watch-the-screen beat on the community cluster, run the
  way the 2-hour format runs the C4 fork bomb "on our box only" (never a phone step: every
  guarded cluster blocks it, which is the lesson). From a presenter checkout on the stage
  laptop, against the community kube-context,
  `CONTEXT=<community-ctx> challenges/imds-node-creds/steal-node-creds.sh` reads the node
  instance-role credentials off `169.254.169.254`, then reads the node's instance-identity
  document with the same stolen token, and the screen names a **node role** and its AWS
  account and region; the same script against an admin or attendee context prints
  `IMDS: BLOCKED`, the control holding. It only reads, changes nothing, and does not touch
  Pod Identity (`169.254.170.23`), so Bedrock still answers everywhere. It is **not** a
  numbered challenge, so the eight-challenge count is unchanged; the full beat, the controls
  table, the ASI03 peg and the on-stage caveats (a stock node role reads ECR and describe,
  not S3 or Secrets, so do not over-promise) are in
  `challenges/imds-node-creds/FACILITATOR.md`. This is the first thing to drop if the clock
  is behind after segment 5; the break-it finale always wins the remaining minutes.
- **Burritos only (1 min):** `guard-topic-on` on the private cluster terminal, then
  re-send an off-topic ask that uses a listed word (dance, hot dog, karaoke, linked
  list, playlist, song). BurritoBot redirects to the menu, hours and locations. The
  probe's topic beats passed on burritobot-private on 2026-10-28. A paraphrase with
  none of those words goes to LLM Guard's BanTopics classifier, which refuses it too
  (#455; "help me plan a birthday party" is the probe's paraphrase beat). A weird ask
  that fits none of its thirteen topics can still get through, so promise the listed
  asks and the paraphrases the probe sends, not every possible ask.
- **Break it (the last minutes, #690):** in the public cluster's terminal, run
  `finale-cap-on` (headroom $1.00 by default, or `finale-cap-on 0.50`). It sets the whole
  cluster's cap to what the room has already spent plus the headroom, and prints both.
  Then `cost-watch` on the screen: spent, cap, turns and a bar, every 2 seconds. Say:
  "We couldn't show everything in 30 minutes. For the rest of the session, try to drive
  BurritoBot's bill up to its cap and break the demo. You have our permission."
  - **What the room sees when it trips:** BurritoBot stops calling the model for everyone,
    `cost-watch` reads CAP HIT, and each phone gets "The kitchen is closed: this cluster hit
    its $X spend cap, so BurritoBot isn't sending anything else to the model for anyone".
    Reset does not help, because the cap is the cluster's, and the reply does not offer it
    (guard-proxy-agenticburn#25).
  - **Measured 2026-10-30 on attackme:** 20 sessions on one address, sending as fast as
    replies came back, put 83 turns through the model at about $0.004 each and crossed a
    $0.30 cap in under 45 seconds; turns past the cap cost nothing. One venue address is
    held to 120 turns a minute by nginx and the cluster to 150, so a room sending about
    100 real turns a minute reaches the default $1.00 in two to three minutes (an estimate
    from that per-turn cost, not a measurement with 50 phones).
  - **Nothing lowers the cap until `finale-cap-on` runs**, and the tally starts at zero
    whenever guard-proxy restarts. Afterwards run `finale-cap-off`, which restores the $25
    `COST_CAP_USD`.
- **The close (Michael):** every attack today was a plausible request, not an
  exploit. The controls that stopped them were RBAC, admission, runtime and egress
  policy, an input classifier and a tool allow-list, owned by the platform team, and
  most of them work whether or not the model cooperates. Say the governance line the
  accurate way per `docs/ABSTRACT.md`: a CNCF floor, AAIF agent protocols, and a
  guardrail layer with no foundation behind it. LLM Guard is the upstream project, archived in
  July 2026; we run its last release, 0.3.16, from our own offline image; the guard proxy is the piece Michael wrote because nothing else
  toggles a guardrail without a redeploy. Point at the repo as the Monday-morning
  takeaway, and at the Feedback button. The close slide links the MCP server vetting
  checklist handout (#649):
  `https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/blob/main/docs/mcp-server-vetting-checklist.md`.
- **Delivers:** point 7 (observability, through every challenge's trace) and point 8
  (ends selling burritos only).
- **Close out (both):** on a repeat of the speaker slide, give the full speaker
  introductions (the bios held back from the quick hello in segment 1), then the
  Thank you slide (rounds-agenticburn#56).

---

## Abstract points to segments

The nine points are the accepted KubeCon abstract's checklist, transcribed in
talks-knowledge `talks/2026-10-16_hard-dated-commitments.md` section 1 against the
verbatim text in `abstracts/recovered/sessionize-public-profile.md` section 5.
That text is Version 4 of `docs/ABSTRACT.md`. How far each point is built and proven, READY, PARTIAL
or MISSING with file evidence, is `docs/KUBECON-ABSTRACT-READINESS.md`; keep this table and that one
saying the same thing.

| # | The abstract says | Segment | Delivered by the cut? |
|---|---|---|---|
| 1 | A chatbot for a fictional burrito chain | 1 (the room's opening minute on the bot), 6 (sells burritos) | Yes |
| 2 | Connected to an under-protected MCP server | 5 (Challenge 4) | Yes |
| 3 | Deployed on a full IDP | 3, by voice | Named, not toured: the catch-all plays against the open public cluster and names each layer |
| 4 | Starts wide open, the audience hacks it live | 2 to 5 (public bot, phones) | Yes |
| 5 | The Kubernetes security layers you should already have | 3 (RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy, switched on together by `guardrails-on` from #774, then one set of slides each, 30 to 42), 4 (least privilege, `guard-agency-on`) | Yes: all four are shown turning on in segment 3's one switch, which depends on #774, before the first LLM-specific guardrail in segment 4, and each is named in its own set of slides |
| 6 | LLM-specific guardrails, pre- and mid-inference prompt analysis | 4 (Challenge 3, pre), 5 (Challenge 4, mid, between the agent's steps) | Yes, as #456 defines mid-inference (2026-10-24). The MCP-return scan before the model (#480) is not built and is not claimed |
| 7 | Good GenAI observability practices | 2 to 5 (each challenge's trace, shown right after its live attack) | Yes once the traces are pre-seeded (#648); `verify/stage_traces.py` seeds Challenge 2 with the recipe read, the ask Whitney sends live in segment 3 (#1003), before and after `guardrails-on` (#843), as `docs/KUBECON-ABSTRACT-READINESS.md` row 7 says; the Grafana view carries them without Datadog (#500) |
| 8 | By the end the chatbot is selling burritos, nothing more | 6 (`guard-topic-on`) | Yes: a listed word is refused on the phrase, and a paraphrase by BanTopics (#455) |
| 9 | "Bring your weirdest off-topic question" (live input, recorded fallback) | 1 (live, in the opening minute on the bot, over the venue network) + Night Before (recorded fallback, #452) | Yes: the live input, and the replay and the screenshots deck in `facilitation/kubecon-na-2026/fallback/`; the segment videos left this repo with M4 (#613) |

Points the cut cannot fully deliver today, marked so they are not presented as
ready: the pre-seeded traces (#648).

## Challenges shown live, and challenges cut

| Challenge | Internal id | In the cut? | Why |
|---|---|---|---|
| Challenge 1, the CEO's record (no fix in segment 2; RBAC arrives with segment 3's `guardrails-on`; no output guard) | C5 | Shown, segment 2 | The opener: it prints something that feels real. Since #776 the segment ends on the OWASP Top 10 for LLM Applications with no fix run; the room tries it again after segment 3's switch, and the Secret read comes back Forbidden |
| Challenge 2, the Kubernetes catch-all (RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy, turned on together by `guardrails-on`, #774) | C2, C3, C1 | Played and fixed, segment 3 | The room plays against the open public cluster; then `guardrails-on` on the private bot's terminal arms all four layers on both clusters, the room's Challenge 1 and 2 attacks are stopped, and one set per guardrail follows on slides 30 to 42 |
| Challenge 3, prompt injection through support ticket HC-666 (least privilege, then the input guard; Kyverno admits the trusted image) | C6 | Shown, segment 4 | Pre-inference analysis, point 6, with least privilege behind it and a Joker page per attendee |
| Challenge 4, the poisoned MCP tool (agentgateway tool allow-list) | C7 | Shown, segment 5 | The under-protected MCP server, point 2; a fix that is not a classifier |
| Denial-of-wallet | C4 | Folded into the finale | Whitney, 2026-10-28: the number never moved convincingly as a challenge. The room drives it at the end instead (#690) |
| Service-account token theft (scoped Role) | C8 | **Cut** | Terminal-driven RBAC work the audience cannot do from a phone. It belongs to the 2-hour format |
| IMDS node-credential theft (watch-the-screen, community cluster) | ASI03 | Optional, segment 6 close | The blast radius leaving the cluster: a presenter beat run from a checkout, like the C4 fork bomb "on our box only", never a phone step and not a numbered challenge (the eight-challenge count holds). `challenges/imds-node-creds/FACILITATOR.md` |


---

## Night Before

Provision the evening before, never as the room fills. Portland proved this; a
last-minute bring-up is how two of twenty consoles were still answering four hours
before doors (`notes/DEBRIEF.md` in the Portland repo).

Run these from `infra/terraform/fleet/`, read the output, and repair anything that
is merely slow rather than rebuilding:

- [ ] **Permissions boundary in each delivery account.** Every cluster plan looks up
  `watch-it-burn-permissions-boundary` by name, and an account without it fails both
  roster clusters at plan with "no matching IAM Policy found" after the lab VPC is
  already billing (#526). Apply it once per account, with that account's own state:
  `. ./event.sh && terraform -chdir=../../org/boundary init && terraform -chdir=../../org/boundary apply -state=states/accen-dev.tfstate -var profile=accen-dev -var region=us-west-2 -var event="${WIB_EVENT}" && terraform -chdir=../../org/boundary apply -refresh-only -auto-approve -state=states/accen-dev.tfstate -var profile=accen-dev -var region=us-west-2 -var event="${WIB_EVENT}"`.
  The preflight in the next step reports it per account, and on a FAIL prints this
  line for the account that is missing it.
- [ ] **Accounts and quota resolve, before anything is brought up (#534):**
  `WIB_ATTENDEE_ACCOUNTS=accen-dev ./fleet.sh preflight 2`. It is read-only, so it
  runs before the bring-up commits any money. It must end `PREFLIGHT GREEN`; on a
  FAIL, fix what it names (it prints the apply line for a missing boundary or lab
  VPC) and run it again. It is scoped to accen-dev because every roster cluster lives
  in that one account (`roster.tsv`); the default account list also names the four
  student accounts, which have no lab VPC for this session, so the unscoped form
  fails on them. The count is clusters per account, and the roster is three
  clusters, so the quota check covers all three. It also prints the `event` tag this
  run bills to. It reads each Bedrock model the clusters bind (the four agent tiers
  and the tutor) and fails any whose Marketplace agreement is not AVAILABLE in the
  account, because Bedrock refuses every call to such a model even when IAM allows
  it (#882). That FAIL prints the offers and accept commands. Accepting is a
  subscription on the account, so Michael runs them; on 2026-11-05 the opus tier,
  `anthropic.claude-opus-4-8`, read NOT_AVAILABLE in accen-dev.
- [ ] **Platform up on AWS.** Bring up the roster (the community cluster and both
  admin clusters) on the KubeCon delivery accounts and region:
  `./fleet.sh instructors up all`. The attendee pool is not provisioned for this
  session. Delivery identity (which AWS accounts, region, and the `event` tag) is
  settled on #454; confirm it is the KubeCon value, not the Portland one, before
  bringing anything up.
- [ ] **The router carries the roster, and only the roster (#502).** `instructors up`
  already wrote the routes table, but with every attendee cluster that has state on
  this machine. Write it again with the roster alone, then read the live router's own
  host list:

  ```bash
  ./fleet.sh routes roster
  ./fleet.sh router-check
  ```

  `routes roster` publishes attackme, both admin hosts and their service hosts, and
  lists any pool row it takes out of the table. The internal registry runs on the
  private cluster alone, so `registry-burritobot-private.burritobot.co` and
  `registry.burritobot.co` are its rows and attackme carries no registry row (#931):
  `registry-attackme` had nothing behind it and answered 502. It refuses if a roster
  console has no load balancer yet; wait for it and run it again. `router-check` reads
  `https://start.burritobot.co/roster.json`, which the router builds from the table
  it is actually serving, and must end "the router serves exactly the roster". A
  table pushed but not reloaded fails here, not on stage. Then confirm the C1 beacon
  view answers through the router:
  `curl -fsS -o /dev/null -w '%{http_code}\n' https://beacon.burritobot.co/beacon/view`
  must print `200`, and so must the same curl of `https://agenticburn.com/beacon/view`,
  the view Challenge 2's slides link (#1003), with the same count on both pages
  (`data-count`). Anything else means the provisioning service, which stays up
  for this session as the beacon collector (open question 9), is down; bring it back
  before the day. The router 404s `/kubecon` on any host outside the roster (#511),
  and the community console withholds it from the room (#909), so confirm both
  gates:
  `curl -fsS -o /dev/null -w '%{http_code}\n' https://burritobot-private.burritobot.co/kubecon`
  must print `200`. A `404` there means the router's roster matcher does not know
  that host, and the presenters have nothing to drive from.
  `curl -s -o /dev/null -w '%{http_code}\n' https://attackme.burritobot.co/kubecon`
  must print `404`. A `200` there means the room can read the presenter page: the
  community cluster's ai-layer has not synced the commit that withholds it.
- [ ] **The prompt wall shows both clusters (#637).** Segment 1 projects
  `https://prompts.burritobot.co`, and the wall builds its cluster list from the same
  `roster.json` that `router-check` just read, so run it once the routes are right:

  ```bash
  ./fleet.sh wall-check
  ```

  It reads `https://prompts.burritobot.co/healthz` and must end "the wall shows
  every roster cluster": a `200`, and `attackme` and `burritobot-private` each in its
  `clusters` list with `ok` true. A missing cluster means the router's roster lacks it;
  run `router-check` again. A cluster listed with `ok` false means the wall cannot read
  that cluster's feed, and the log prints the wall's error. The same read by eye:
  `curl -s https://prompts.burritobot.co/healthz | python3 -c "import json,sys; print([c['name'] for c in json.load(sys.stdin)['clusters']])"`
  prints `['attackme', 'burritobot-private']`. Keep the wall on this roster through
  the session: do not move it onto lab-platform's roster before 2026-11-12, which
  leaves out attackme and the admin cluster until lab-platform#137 lands
  (prompts-agenticburn#11).
- [ ] **The guardrails switch reaches both clusters (#774).** `instructors up`
  links the pair; if it said the link failed, or a standby now holds a hostname,
  link the two that hold the hostnames: `./fleet.sh guardrails-link` (or
  `./fleet.sh guardrails-link <community>@<region> <private>@<region>`). Then, in the
  private cluster's terminal, `guardrails-on` must end "all four Kubernetes
  guardrails are on." and `guardrails-off` "... are off.". The internal registry
  answers through the router (`routes roster` publishes its name on the private
  cluster's load balancer):
  `curl -fsS https://registry.burritobot.co/v2/burritobot/maintenance-shell/tags/list`
  lists the seeded tag.
- [ ] **Hostnames serve over HTTPS and websocket:**
  `./fleet.sh check-tls --closed-terminal attackme.burritobot.co attackme.agenticburn.com`, then
  `./fleet.sh check-tls burritobot-private.burritobot.co burritobot-private.agenticburn.com`.
  Each second name is the agenticburn.com twin, kept for redundancy (#651): neither is shown, and both must pass.
  The router closes the public bot's terminal and `/lab` on both domains (apex-agenticburn#43, #44), so on
  attackme `--closed-terminal` asserts both websocket upgrades get its 404; the private bot's terminal must
  upgrade and still refuse a shell with no credential.
- [ ] **Clusters healthy:** `./fleet.sh converge instructors`.
- [ ] **The pinned model answers in the delivery region.** From the repo root:
  `python3 verify/model_pin_check.py --profile accen-dev --region us-west-2`. It
  reads the pin from `gitops/ai-layer/resources.yaml` (Nova Pro,
  `us.amazon.nova-pro-v1:0`, with `MODEL_TIER` `nova`), then checks against live
  Bedrock that the inference profile is ACTIVE, that the model is not Legacy or
  scheduled to go Legacy before 2026-11-12, that one Converse call answers, that
  each cluster's tagged copy of the profile (what the agent calls, so its spend
  carries `project` and `event`, #513) routes to the same model and answers, and that
  the cross-region quota covers the room. It must end `MODEL PIN GREEN`; anything
  else, stop and fix the pin before the day (#453). Then send one throwaway order to
  each bot and confirm it answers with a menu, not an empty reply (an empty reply
  means the MCP servers are down; see the workshop runbook's failure playbook).
- [ ] **Every shown beat works, on the clusters that will be on stage (#503).** From
  the repo root, one command per cluster. It runs the beats in this file's order and
  prints PASS or FAIL for each. It spends real Bedrock money, capped by `--max-calls`
  (default 20): a community run makes 7 model calls, an admin run 14, plus one for
  each reply that is Bedrock's ToolUse 424, which the probe sends again once as the
  failure playbook says (#889). Pull each cluster's credentials into its own kubeconfig first; the probe passes it per
  command and never touches `~/.kube/config`. Both runs need the kube-context: C6 is
  judged on the `joker-agatha-the-banshee` Deployment HC-666 asks for, not on the reply.

  ```bash
  python3 verify/kubecon_probe.py community attackme.burritobot.co \
      --context <community-context> --kubeconfig /tmp/community.kubeconfig --profile accen-dev
  python3 verify/kubecon_probe.py admin burritobot-private.burritobot.co \
      --context <private-context> --kubeconfig /tmp/private.kubeconfig --profile accen-dev
  ```

  - Community (segments 1 to 3): the kube-context and the hostname are the same
    cluster (if not, it stops before touching anything); the wide-open start, a
    burrito order answered, the CEO record leaking with the `/brief` prompt (her
    address in the reply the room reads, or the signature), Whitney's friendly
    opener getting nothing from the Secret (#688), the linked-list ask
    answered 3 of 3, Challenge 2's three openings (the beacon reached, the villain
    image admitted in a dry run, the recipe file read), Challenge 3's HC-666 ask
    landing `joker-agatha-the-banshee` (Kyverno is off here; the probe deletes it
    again), the cost counter moving,
    and the projected feed on. Each beat is judged on what the console shows, with
    Nova's `<thinking>` block folded as the storefront folds it, and a FAIL quotes
    300 characters of the reply.
  - Admin: the kube-context and the hostname are the same cluster (if not, it stops
    before flipping anything); the start state (every AI guard off; the four
    Kubernetes guardrails present and off, #774); the `/controls` badges agree with
    the cluster; then the challenges in stage order, with the guards turned on
    cumulatively as segments 2 to 5 do: C5 leaking, with no fix run in segment 2 (#776);
    `guardrails-on`, run in the private terminal pod, arming all four on both clusters
    and the badges lighting; C5 asked again and out of reach, since the switch's RBAC
    scoped the Role (#855); C1, C2 and C3
    (Challenge 2) blocked, a public image denied by `deny-external-registries` and the
    internal registry's image admitted; C6 (#775): HC-666's ask landing
    `joker-agatha-the-banshee` with Kyverno at Deny, since its image is the internal
    registry's, then its two fixes (after `guard-agency-on`'s Role, a server-side dry
    run of that Joker as `workshop-mcp` Forbidden by RBAC; then, after
    `guard-input-on`, `read_support_ticket` withholding the ticket when called in
    the tool pod and the model asked with no Deployment appearing); C7 off then on,
    stopped at the gateway: the probe narrows agentgateway's rule for evil-mcp and
    leaves toolNames full, so a blocked re-ask can only be the gateway's doing. C1, C2
    and C3 are judged on the control and not the model (the lab's curl from
    `workshop-mcp`, a server-side dry run as `workshop-mcp`, and the C3 fallback).
    Then the on-topic guard redirecting the four canonical off-topic asks and one
    paraphrase with no listed word, which only BanTopics can refuse (#455), and
    letting "what are your hours", "do you have mild salsa" and "does the rice have
    chicken stock" through (the last is #905's allergen card). Its last
    act is `guards-off`, run even when a beat fails, so the stage starts clean; it
    also puts the shipped Role back and runs `guardrails-off`, which turns the four
    Kubernetes guardrails off on both clusters. Run the community probe before the
    admin one, never during it: the admin probe's `guardrails-on` reaches attackme.
  - Every prompt it sends carries guard-proxy's probe marker, so none of them shows
    up in the feed the room sees.
  - Each run holds the cluster's guard lock (#1024), the Lease `agent/wib-guard-lock`,
    from before the start state is read until after `guards-off`, and so do
    `verify/stage_traces.py seed`, `verify/agent_probe.py`, `verify/input-guard.sh`,
    `verify/beat-02.sh` and `verify/beat-cost.sh`. A second run on the same cluster
    waits for it, up to 30 minutes (`--lock-wait`), then exits 3 naming the holder;
    the probe prints `KUBECON PROBE NOT RUN`. `python3 verify/guard_lease.py show
    --context <context>` prints who holds it. On 2026-11-06 three of five admin runs
    went red on an output guard another run turned on (#900).
  - The same lock covers the Kubernetes guardrails (#1016). An admin probe holds it
    on both clusters, since its `guardrails-on` reaches attackme, and so do
    `verify/stage_traces.py seed` and `verify/test_recipe_block_live.py`. Every live
    check that switches a policy holds it on its own cluster: `verify/beat-01.sh`,
    `verify/c1-exfil-block.sh`, `verify/test_kyverno_cel_live.py` and
    `verify/test_drift_selfheal_live.py`, and so do the checks that read the
    guardrails off, `verify/test_kubecon_c3_live.py`,
    `verify/test_two_hour_flow_live.py` and `verify/test_room_cleanup_live.py`. So
    the community probe and the admin one take turns on their own.
    `WIB_GUARD_LEASE_WAIT` sets the wait for the scripts that have no `--lock-wait`.
    To run `guardrails-on` by hand, wrap it: `python3 verify/guard_lease.py hold
    --with-peer --context <context> -- <the kubectl exec>`. On 2026-11-06 run
    17944's Kyverno check read run 17950's switches, eight in an hour.
  - Each run must end `KUBECON PROBE GREEN`. A FAIL is a beat to fix or to plan its
    fallback for before the day, not something to find out on stage. The two beats
    that failed on 2026-10-24 for want of a fix, the Kyverno badge (#487) and the
    on-topic beats (#455), have passed on every run since 2026-10-27. Record the
    date, the clusters, each beat's result and the spend it prints under "Probe
    record" above.
- [ ] **Seed the stage's Datadog traces (#648), after the admin probe is green.** Each
  challenge shows its trace after the presenters' attack and again after its fix, so
  each is seeded twice on the private bot, the attack and the same ask after its fix,
  and Challenge 3 adds someone else's PII
  refused by the input guard: nine `/chat` requests (eight model calls; the PII one
  spends no tokens), in presentation order, with the probe's own guard flips and its
  `guards-off` at the end. Challenge 2's pair is the `/kubecon` recipe read, sent
  before `guardrails-on` and again after it (#843). Challenge 1 runs no fix of its own
  (#776), so its second seed, `c1-fixed`, is the CEO ask sent again after
  `guardrails-on`, beside `c2-fixed`: the Secret read Forbidden by the switch's scoped
  Role (#855).

  First, what the input guard refuses. No model call, nothing toggled; it asks
  guard-proxy's own input stages, in its pod, about a card, an SSN, an e-mail, a
  phone number and the stage's PII prompt, and checks a plain order still passes. It
  must end `REFUSES 5 OF 5`:

  ```bash
  python3 verify/stage_traces.py pii burritobot-private.burritobot.co \
      --context <private-context> --kubeconfig /tmp/private.kubeconfig --profile accen-dev
  ```

  Then, in Whitney's org, an APM retention filter that keeps the seeds: APM, then
  Retention Filters, query `service:burritobot @session.id:wib-stage-*`, 100% of
  spans and 100% of traces. The PII seed's trace lives in APM, not LLM Observability
  (a refused prompt has no gen_ai span), and APM keeps a span past Live Search's
  15 minutes only when a retention filter indexes it. The repo's Datadog key is
  read-only, so this is a click in the UI.

  ```bash
  python3 verify/stage_traces.py seed burritobot-private.burritobot.co \
      --context <private-context> --kubeconfig /tmp/private.kubeconfig --profile accen-dev
  ```

  Each seed is its own session, `wib-stage-<seed>-<UTC minute>`, sent without the
  probe marker so the trace reads as the prompt shown (the prompts show in the
  private bot's column of the prompt wall, except the PII one: the feed masks it to
  `[redacted]`, and a masked prompt is left off `/display` (#915) and, with
  prompts-agenticburn#15, off the wall). The
  PII prompt is sent only after guard-proxy's input stages say they refuse it. It
  waits until every trace in LLM Observability carries the tool spans the stage
  points at (`get_vault_entry`; `run_shell`, the recipe grep; `read_support_ticket`
  and `deploy_app`, and no `deploy_app` once fixed; `get_weather` and
  `read_internal_config`), and until the
  PII seed's trace in APM is stamped `input_classifier` with no agent span and none
  of the PII in it. Then it prints one link per seed plus the room's and the
  presenters' views, and writes them to `tmp/stage-traces.json`. It must end
  `SEEDED GREEN`. Each seed's link opens paused on the seed's own window, so it finds
  its trace whenever it is opened. Whitney opens each link in her org and saves it as a
  view, in that order: `c1-attack`, `c1-fixed`, `c2-attack`, `c2-fixed`, `c3-attack`,
  `c3-fixed`, `c3-pii`, `c4-attack`, `c4-fixed`, then the room's and the presenters'
  (the `c3-pii` link opens Trace Explorer, the others LLM Observability). Before she
  presses Save on a seed view, she sets the time picker to Past 7 Days: a saved view
  keeps only a live range, and Datadog turns a fixed range into a live one when it is
  saved, so a view saved on the seed's own window would read the last half hour on
  stage and find nothing. The session in each query keeps a week's range to that one
  trace. The room's and the presenters' views are live tabs: save them on Past 15
  Minutes.

  `seed` starts only from the stage's start state: every AI guard off and the four
  Kubernetes guardrails off, as the `kubecon-private` profile deploys them. Anywhere
  else it stops before the first prompt, prints `SEEDED RED`, and sends and flips
  nothing. On 2026-11-05 `watch-it-burn-private` ran the `admin` profile, whose Argo CD
  applies KubeArmor's `block-recipe-snoop` and the agent egress allowlist, so it stopped
  there. Seeded traces outlast the night: the 2026-10-31 seeds were still in LLM
  Observability and APM on 2026-11-05. The
  morning of: `python3 verify/stage_traces.py check --profile accen-dev` must end
  `STAGE TRACES GREEN`. A red `c3-pii` there means the retention filter did not keep
  it: check the filter and run `seed` again.
- [ ] **Agent Observability is receiving from both bots (#783).** Before every
  run-through, the Night Before and the morning of:
  `python3 verify/agent_obs_flow.py chat --profile accen-dev`. It sends one marked
  chat to each bot (two model calls, none in the room's feed) and waits up to ten
  minutes for its spans in Agent Observability. It must end `AGENT OBSERVABILITY
  GREEN`. A RED names the cluster that sent nothing: on 2026-11-01 APM kept every
  trace while Agent Observability got none for six hours, and nothing else went red.
  Between runs, `python3 verify/agent_obs_flow.py watch --profile accen-dev` spends
  nothing and goes red when APM's newest BurritoBot span never reached Agent
  Observability.
- [ ] **Check each challenge's trace shape (#760), after the seed and the flow
  check.** The seeded attacks are the newest traces for Challenges 1, 3 and 4, and
  the probe's or the room's for Challenge 2:

  ```bash
  python3 verify/challenge_traces.py --profile accen-dev --out tmp/challenge-traces.json
  ```

  It must end `CHALLENGE TRACES GREEN`: one root row per chat with the prompt and the
  reply on it, tokens and cost, and each challenge's key calls under the root, as
  `verify/challenge-trace-shapes.yaml` writes them down. Each FAIL is filed as its
  own issue with the trace link it prints, the night before, not on the day.
  Challenge 2's `deploy_app` and `run_shell` are each judged in their own newest chat,
  each with its own link (#1109). A Challenge 2 FAIL reading "no trace ... has
  deploy_app without read_support_ticket" means no Challenge 2 image deploy was
  played in the window on the cluster it read; a run-through's deploy makes one.
- [ ] **C7 at the gateway, and its reload delay (#496).** From the repo root, against
  the admin cluster:
  `CONTEXT=<admin-ctx> challenges/03-bad-mcp-excessive-agency/fallback.curl.sh`.
  It must end `C7 PROVEN`. Write the delay it prints ("the narrowed rule took effect
  after N s") into segment 5's "Measured reload delay" line. If the deny never comes,
  C7 is not ready to show.
- [ ] **Guard start state on the admin cluster:** run `guards-off` from its terminal
  so the AI guardrails start off and the live toggles in segments 2 to 6 are real. The
  probe above ends with it already; run it again if anyone has touched the guards
  since.
- [ ] **Datadog org** for the observability segment is loaded and the fleet monitors
  are applied (#454, #485; `WIB_FLEET_MONITORS_APP_KEY=<key> ./fleet.sh monitors --apply
  --session 2026-11-12T20:50Z/2026-11-12T21:20Z` with an application key from Whitney's
  user, then `./fleet.sh monitors --check`, and after one /chat on each cluster
  `./fleet.sh monitors --data --cluster burritobot-public --cluster burritobot-private`).
  The window is the 30-minute slot from the start under "Bring-up and teardown commands"
  (conference-knowledge `kubecon-na-2026`). Without `--session` the no-traces monitor
  stays muted for good, so it never fires in the room. If no
  pool is live, each challenge's trace is shown on the admin cluster's Grafana view
  (`https://grafana-burritobot-private.burritobot.co/d/witb-agent-obs`): open it, run
  the Challenge 1, 3 and 4 beats once, and confirm each of the three panels in the
  "Traces" row shows a row. Say on the day which surface is shown.
- [ ] **Recorded fallback proven once (#452).** On each presenter laptop, from the
  repo root, so a dead venue network does not end the session. What each file is
  and how it is made: `facilitation/kubecon-na-2026/fallback/README.md`.
  - The replay, once, over the phone hotspot rather than the hotel network:
    `python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 1`.
    It sends segment 1's prompts from `facilitation/kubecon-na-2026/fallback/prompts.yaml`
    (the order and the four off-topic asks, five model calls, nothing that deploys
    or reads a Secret), paced under guard-proxy's 150-a-minute window, and stops at
    the first prompt that does not land. Every line should end `ok`, then `DONE: 5 of 5
    delivered`; read the replies against each prompt's `expect`. Run it before the
    community bot's last `reset-bot`, so its five turns are off the counter.
  - The deck and every screenshot it lists are in place:
    `python3 scripts/check-fallback-assets.py`, which ends `recorded fallback ready`
    and exits 1 if any shot is missing, empty or not a PNG.
  - Open `facilitation/kubecon-na-2026/fallback/screenshots/deck.html` from disk
    with Wi-Fi off and step through it: no red MISSING card.
- [ ] **Audience path and phones (#450, #451).** Confirm the room's rate limit and
  timeouts are sized for a ballroom and that the page, the projector QR, and the
  Feedback link work on a real iPhone and a real Android phone on venue-like
  Wi-Fi and on cellular. Fill in `facilitation/kubecon-na-2026-phone-check.md`.
  The QR on the slide is `facilitation/kubecon-na-2026-audience-qr.svg`, and the
  Feedback button opens the session survey, both set in
  `gitops/ai-layer/web/event.js`.
- [ ] **The community bot at room scale (#644), before the reset below.** From the repo
  root, replay the DevOpsDays Portland prompts at attackme as 500 phones, each its own
  session, three turns each. The harvest is gitignored, so pass its path. Without
  `--yes` it prints the plan and the estimated cost and sends nothing; with it, it
  sends at most `--max-calls` (1500) turns, every one carrying the probe marker so the
  prompt wall stays clean, and stops new turns once `/cost` has risen $10 or 900 s
  have passed.

  ```bash
  python3 verify/load_replay.py attackme.burritobot.co --yes --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts --json-out tmp/load-replay-attackme.json
  ```

  The estimate: at most $7.50 if all 1500 turns reached the model at $0.005 a call;
  about $1.90 predicted for about 375 served turns, because guard-proxy's cluster
  window passes about 150 a minute over the run's 2.5 minutes. From one
  machine every turn leaves through one address, as a venue NAT's do, and since
  #450 nothing in front of guard-proxy keys on the address. For the room Michael
  expects, run it again with `--users 150` (the commands are in
  `facilitation/kubecon-na-2026-load-test.md`). The report gives latency percentiles,
  outcomes by limit (nginx per conversation, guard-proxy per session and per cluster, the cluster's cost cap, a
  conversation's budget), errors by
  HTTP status (502, 504, 429), timeouts, and the `/cost` spend before and after. It
  must end `LOAD REPLAY GREEN`: a refusal is a sentence a phone can read and passes,
  a 502, 504, timeout or empty reply fails. It lists each failed turn with its time,
  session and what answered it. On 2026-11-05 both sizes ended RED only on turns the
  agent spent repeating one shell command until `PROXY_TIMEOUT` (8 of 1,500 and 5 of
  450, `facilitation/kubecon-na-2026-load-test.md`), so read each listed turn's cause
  before judging the run. Record the run on #644. `--source catalog`
  replays the stage's own asks instead when the harvest is not on this machine.

  Then, before the reset, read whether each turn that ran past `PROXY_TIMEOUT` (120 s)
  stopped the agent. #750 confirmed this on attackme on 2026-11-04 with two such
  turns; this read checks it again under the room's load. With attackme's credentials
  in their own kubeconfig, as the probe step above has them:

  ```bash
  KUBECONFIG=/tmp/community.kubeconfig kubectl --context <community-context> -n agent logs deploy/guard-proxy -c proxy --since=30m | grep -E '"event": "(forward_error|task_cancel|task_cancel_failed)"'
  KUBECONFIG=/tmp/community.kubeconfig kubectl --context <community-context> -n agent logs deploy/workshop-agent -c kagent --since=30m | grep -F '<task id from a task_cancel line>'
  KUBECONFIG=/tmp/community.kubeconfig kubectl --context <community-context> -n agent logs deploy/workshop-agent -c kagent --since=30m | grep -F '"sessionID":"<contextID from the Execute line above>"' | grep '"Tool execution started"' | tail -n 1
  ```

  Each `forward_error` reading `chat forward failed: the 120s forward deadline
  (PROXY_TIMEOUT) passed` should be followed, within a second and under the same
  `trace_id`, by one `task_cancel` that names the task and reads `state canceled`, and
  no `task_cancel_failed`. A `forward_error` with no `task_cancel` after it is a forward
  that failed before the agent took the turn, which leaves nothing to cancel. For each
  cancelled task, the agent's last `Tool execution started` in that conversation should
  be earlier than the `task_cancel` (guard-proxy writes UTC with a comma before the
  milliseconds, the agent ISO 8601 with a Z). Do not read workshop-mcp's log for
  this: its `mcp_session_id` is the agent's connection, shared by every conversation,
  so under load it always shows other turns' tool calls in the minute after a cancel.
  Then search Datadog APM for `trace_id:<the forward_error's trace_id>`: the trace
  should be there, with guard-proxy's `chat` span and the agent's `invoke_agent` span,
  and its last span should end at the cancel. Record the readings on #644.
- [ ] **Reset the community bot, last (#539).** The probe, the phone check and any
  rehearsal all spend on attackme, and guard-proxy keeps that spend in memory (the Go
  build keeps it on its volume: see "After the Go cutover" in the run-through record). Once
  nothing else will touch attackme before the session, from `infra/terraform/fleet/`:
  `./fleet.sh reset-bot watch-it-burn-community`. It restarts guard-proxy by a pod
  delete, which Argo CD does not revert (on the Go build it runs `reset-spend` and
  prints what it cleared), and must end `counter at zero` on
  `https://attackme.burritobot.co/cost`, so the room's counter opens at `$0.0000`
  with the whole $25 `COST_CAP_USD` window ahead of it. Anything else, run it again;
  if it still does not read zero, read the guard-proxy pod's logs before the day.
  The same reset runs before each run-through ("Run-through record" above).
- [ ] **Empty the prompt wall, after the reset (#926).** The probe, the phone check
  and every rehearsal leave prompts on `https://prompts.burritobot.co`, which keeps
  them in memory until its app restarts. Once nothing else will prompt either bot,
  from `infra/terraform/fleet/` on a host logged in to Railway:
  `./fleet.sh reset-bot watch-it-burn-private` (then `guards-off` on its terminal),
  `./fleet.sh wall-reset`, then `./fleet.sh wall-check --empty`, which must end "the
  wall shows every roster cluster and holds no prompts". `wall-reset` refuses while
  either cluster's feed still holds a prompt and names the `reset-bot` to run. If the
  wall gets a prompt after this, run the three again on the day, before the room
  arrives ("Run-through record" above).

## Rollback on the day

1. A prompt wanders on a shown beat: run that beat's fallback from the table
   below so the guardrail is what is proven. Do not debug the model live.
2. The venue network cannot carry the room: the presenters drive the audience
   beat themselves from the admin cluster and the room watches, rather than hacking
   from phones. The room's prompts still reach the public bot and the wall: from a
   laptop on the phone hotspot, replay the segment on stage,
   `python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment <N>`.
   If it stops, do not retry it; go to step 3.
3. Nothing live works at all: show the recorded fallback (#452). Open the
   screenshots deck from disk, `facilitation/kubecon-na-2026/fallback/screenshots/deck.html`,
   step to the segment on stage, and narrate over it.
4. Any beat over its time budget by half: cut it to a sentence and move on. The room
   never watches unrehearsed troubleshooting.

### Fallback scripts, per beat

Run them from a checkout of this repo on the presenter laptop, against the admin
cluster: `CONTEXT` is its kube-context, the only input any of them takes (prefix
`KUBECONFIG=<file>` if its credentials are in an isolated kubeconfig). None of them
calls the model. Each prints PASS or FAIL per check and exits non-zero on any FAIL,
and none writes a scratch file. The C5 and C6 scripts turn their guard on the way
`guard-output-on` and `guard-input-on` do, and put it back the way they found it.

| Beat | Run | PASS means |
|---|---|---|
| C5 | `CONTEXT=<admin-ctx> challenges/02-sanitization/fallback.curl.sh output` | With the output guard on, the CEO record sent through guard-proxy's output path comes back with `OPHELIA-THORN-TIBBY-TOP-SPIRE-No9` and the address redacted |
| C6 | `CONTEXT=<admin-ctx> challenges/02-sanitization/fallback.curl.sh input` | In the workshop-mcp pod, `read_support_ticket` hands back HC-7731 with its hidden paragraph while the input guards are off, and `[input guard] withheld` once they are on. No model call |
| C2 | `CONTEXT=<admin-ctx> challenges/c2-villain-image/fallback.kubectl.sh` | As `workshop-mcp`, a Deployment of `ghcr.io/peopleforrester/lab-platform/promo/joker:v1` is denied at admission and the denial names `restrict-image-registries`. It prints the deny message to read aloud |
| C6 (least privilege, #775) | `kubectl --context <admin-ctx> -n agent auth can-i create deployments --as=system:serviceaccount:agent:workshop-mcp` | After `guard-agency-on` it prints `no`: the bot's Role creates no Deployment, from any registry. `yes` means the Role did not change. No model call |
| C7 | `CONTEXT=<admin-ctx> challenges/03-bad-mcp-excessive-agency/fallback.curl.sh` | From the web terminal pod, `read_internal_config` called through agentgateway `:3003` returns `FAKE-MCP-EXFIL-sentinel-4c1d` after `guard-mcp-off`, and the gateway refuses it after `guard-mcp-on` while `get_weather` still answers. It prints how many seconds the narrowed rule took to take effect, and puts the rule back as it found it. It refuses a workshop cluster |
| C1 | `CONTEXT=<admin-ctx> challenges/c1-exfil-s3/fallback.kubectl.sh` | From the workshop-mcp pod, where `run_shell` runs, the POST to `https://beacon.burritobot.co/beacon` fails, and the beacon count does not move. Keep the beacon view on screen |
| C3 | `CONTEXT=<admin-ctx> challenges/c3-secret-grep/fallback.kubectl.sh` | The agent's grep for the recipe in the workshop-mcp pod reads `Permission denied`, and the `kubearmor-relay` log carries the `block-recipe-snoop` Block alert, which it prints |

## Teardown

The clusters cost real money after the session and are promised to nobody once it
ends. Tear down within a few hours of the session close, the way Portland did (479
hosts at peak, down to 1 within three hours).

- Full teardown, account-aware, ending in a zero-cost audit:
  `teardown/teardown.sh` (a thin wrapper over `fleet.sh down all`, which destroys
  every cluster with state, sweeps leaked load balancers, target groups and volumes,
  destroys each account's lab VPC, and runs `audit-zero`). Pass `--keep-vpc` only if
  a fast rebuild is wanted.
- Confirm nothing billable is left: `infra/terraform/fleet/fleet.sh audit-zero`.
- Sweep any stranded load balancers a failed teardown left behind:
  `infra/terraform/fleet/fleet.sh reap-lbs` (dry run unless `WIB_APPLY=1`).
- The Datadog pool secret is deliberately not destroyed by `down all`; use
  `fleet.sh reap-secrets` only when the pool itself is finished with.
- Purge the room's data from Whitney's sandbox org, as promised on the planning call
  (#647): every `burritobot-public` trace, whatever the scrub caught. Signed in to
  her org, find the room's traces under `kube_cluster_name:burritobot-public` for the
  session window, and from the build days before it the spans of service
  `wib-pii-scrub-check` (ml_app of the same name), which the live scrub check
  `verify/test_collector_pii_scrub_live.py` sends. Delete their LLM Observability spans by trace id through
  `POST /api/v2/llm-obs/deletion/data/llmobs` (in preview, so confirm the call on the
  day). APM spans have no delete-by-query, so ask Datadog support to remove them or
  let retention expire them. Then post on #647 what was deleted and what is left to
  retention.
- Record the real spend once the fleet is down, with `teardown/delivery-cost.py
  --start <first build day> --end <day after the last teardown> --event kubecon-na-2026`
  and a `--profile` for each fleet account, saved as `cost/measured/kubecon-na-2026.txt`
  (#872). It reads each account's bill by date. `teardown/cost-report.sh` filters on the
  `event` and `project` tags, which only the payer account can activate, and the
  provider is not asked, so it prints 0.00 (#392). Portland measured 2,865.86 USD
  across the five accounts, 0.76 USD per cluster hour (`cost/measured/`).

---

## Open questions for Michael and Whitney

These are the things this run-of-show could not settle from a source. They are
written down rather than guessed. A question that has since been decided keeps its
number and says who settled it and when, so references to it elsewhere still land.

1. **The on-topic guardrail's hours and locations (#455).** The classifier half is
   settled: since 2026-11-05 `llm-guard-scanners` carries BanTopics, so a paraphrase
   with no listed word is refused too, and on watch-it-burn-private that day the
   topic stage, run against cpu.5 with that scanner list, judged all 64 asks in
   `verify/topic_cases.py` as written (#455). Still open on #455: the hours
   and locations BurritoBot will say on stage were invented in-world (every day 11am
   to 11pm, until midnight Fridays and Saturdays; 13 Mandrake Row, Black-Bog Market,
   the Moonrise Pass drive-thru); keep them or replace them with Michael's and
   Whitney's wording. This is the biggest content risk in the cut.
2. **The recorded fallback is built (#452).** The replayable prompt set, its
   replay script, the screenshots deck and its capture script are in
   `facilitation/kubecon-na-2026/fallback/` and `scripts/`, and the Night Before and
   rollback steps name them. The deck holds 13 shots, every segment from 1 to 6,
   captured on the live clusters on 2026-11-04 and 2026-11-06. The segment videos,
   and the two shots that were to be taken by hand at the first full rehearsal, left
   this repo when Michael dropped M4 (#613) on 2026-11-01. Challenge 2's public-image
   shot (03-1) was put back in the deck on 2026-11-06 (#939). On 2026-11-04 and
   2026-11-05 the Tron ask did not deploy on the community bot, because the model
   passed `deploy_app` the bare name "Tron" for its manifest. From #939 to #991,
   `deploy_app` took a manifest that was only an app's name and served it on a pinned
   public nginx image: on 2026-11-06 the room's two Tron prompts, replayed three times
   and once more for the shot on the community bot, called `deploy_app` five times
   with "Tron", and all five deployed nginx. Since #991 a bare name is refused, saying
   to send the image, and BurritoBot's prompt names the Tron game's exact image, so
   the shot is owed again on the bot that runs #991.
3. **Settled 2026-10-29: no Datadog pool (#454, #629).** Datadog no longer issues
   per-student orgs, so both KubeCon clusters ship to Whitney's sandbox org. What is
   still owed is in the people table above: her write application key, the fleet
   monitors (#485) and the room view (#665). If Datadog is unreachable on the day,
   each challenge shows the private cluster's Grafana view (#500).
4. **Settled 2026-10-24: what "mid-inference" means for point 6 (#456,
   talks-knowledge#29).** Michael decided it: mid-inference is checking between the
   agent's steps, its tool calls and what the MCP server returns (agentgateway MCP
   authorization plus the guard-proxy output guard, shown on the C7 rogue MCP).
   Pre-inference is the prompt check before the model. Streaming-response scanning
   is not in scope, and neither is scanning the MCP server's reply before the model
   reads it (#480). Segment 5 says it that way.
5. **Settled 2026-10-24: two clusters for the before/after.** Michael decided it on
   #448: the wide-open community cluster for the room to attack, and the guarded
   presenter cluster for the before and after. This is the plan as written above.
6. **The model pin and cost counter (#453).** Reconciled: the deployed agent runs
   Nova Pro (`bedrock-nova`, `us.amazon.nova-pro-v1:0`, us-west-2), and
   guard-proxy's `MODEL_TIER` is `nova`, priced at $0.0008 in and $0.0032 out per
   1K tokens. That price matches the AWS price list for us-west-2 (published
   2026-10-16, read 2026-10-24). The Haiku files under `agent/` are pre-GitOps
   copies that nothing applies. The public AWS pages read on 2026-10-24 (the Nova
   Pro model card and Model lifecycle (Legacy)) list Nova Pro as Active, with no
   legacy or end-of-life date. Still open: the live check in the delivery account,
   `python3 verify/model_pin_check.py --profile accen-dev --region us-west-2`, has
   not been run yet. It needs the accen-dev credentials. Record its date and output
   on #453.
7. **The audience rate limit, venue NAT, and timeouts (#450, #451).** Sized in git
   for a ballroom on one venue Wi-Fi NAT ("The audience path" above). Still owed:
   `verify/test_audience_path_live.py` on attackme once it runs this config, a
   phone-scale load test there, and the real-phone check (#451).
8. **The deck (rounds-agenticburn#38).** This file is the beat list the deck is
   cut from. The deck itself is built in `peopleforrester/rounds-agenticburn`
   (`attendee.html`); this repo builds no slide HTML. No deck is submitted to
   Sessionize (Michael, 2026-10-28; #449 and #537 closed), so nothing is exported
   for upload.
9. **Settled 2026-10-25: the provisioning app keeps running as the C1 beacon
   collector (#502, question 714).** The router forwards `/beacon` and `/beacon/view`
   to the collector inside the provisioning app, so with that service off the beacon
   returns an error, the beacon view does not load, and the C1 fallback script
   fails on reading the count. Hecaton's research decided it under Michael's
   standing rules, not Michael: the service stays up for this session as the beacon
   collector only, and nobody is pointed at its distributor pages, so no attendee
   lab runs (#448).
