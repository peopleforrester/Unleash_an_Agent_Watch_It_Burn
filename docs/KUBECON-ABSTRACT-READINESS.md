<!-- ABOUTME: Readiness of this repo's platform against the accepted KubeCon NA 2026 abstract (Sessionize
     ABOUTME: 1249553): one row per point, READY, PARTIAL or MISSING, with file evidence. Kept current to delivery. -->

# KubeCon NA 2026 Abstract Readiness (Sessionize 1249553)

The breakout is held to its accepted text. That is Version 4 in `docs/ABSTRACT.md`, copied verbatim from
talks-knowledge `abstracts/recovered/sessionize-public-profile.md` section 5. It is not held to the archived
BurritoBot repo's CFP draft. The nine points and what "ready" means for each come from the checklist in
talks-knowledge `talks/2026-10-16_hard-dated-commitments.md` section 1. That note was read at talks-knowledge
`e1642bc` (2026-10-24), because the main clone this run was given (`5a9af49`) does not carry it.

The beats each point is delivered in are in `facilitation/kubecon-na-2026-run-of-show.md` ("Abstract points
to segments"). This file says how far each point is built and proven. The run-of-show says when it is shown.

**Assessed:** `staging` at `c724652` (2026-10-24 21:06 CEST), plus `e810736`, which adds only the #454 record
to `decisions.md` and `PROJECT_STATE.md`. Issue states were read through `gh` the same evening.

## Legend

- **READY:** everything this repo builds for the point is on `staging`. Nothing is left but the Night Before
  run on the clusters that will be on stage.
- **PARTIAL:** some of it is on `staging`. The rest is named in the row with its issue, and with its branch
  where a fix is built but not yet promoted.
- **MISSING:** nothing on `staging` delivers the point.

The **Live** column is kept apart from the status on purpose. A point is only ready to deliver once it has
run green on a live cluster: `verify/kubecon_probe.py` ending `KUBECON PROBE GREEN` on the community cluster
and on each admin cluster.

## Verdict, 2026-10-24

**Not ready to deliver.** 6 READY, 3 PARTIAL, 0 MISSING. Points 6, 8 and 9 still have build left. No point
has run green on a live cluster yet. The first bring-up (2026-10-24: attackme and michael-admin in
accen-dev, us-west-2) ran the probe: 4 PASS and 2 FAIL on attackme, 11 PASS and 12 FAIL on michael-admin's
second run, about $0.05 of Bedrock in all. Its per-beat results are the 2026-10-24 entry of the run-of-show's
"Probe record" (#509). Its findings (#510, #526, #528, #529, #530) are fixed on `staging` and not yet proven
live.

## The nine points

| # | The abstract says | Ready means | Status | Evidence on `staging` | Open | Live |
|---|---|---|---|---|---|---|
| 1 | "a chatbot for a fictional burrito chain" | The bot runs and answers as the burrito chain | READY | `gitops/ai-layer/resources.yaml`: the workshop-agent persona is BurritoBot for Hex & Cauldron, a burrito cantina, with a fixed menu, plain-word mapping ("chicken = Cluck-a-cadabra"), and hours and locations (#455). The storefront is `gitops/ai-layer/web/burritbot.html`, and it folds Nova's `<thinking>` block out of the reply (#530) | The hours and locations were invented in-world. Michael and Whitney keep them or replace them (run-of-show open question 1). The secret recipe and the CEO record are demo props for the leak beats and do not replace the menu | 2026-10-24 community probe: the failures #530 recorded were C5 and the off-topic ask, not the order beat |
| 2 | "connected to an under-protected MCP server" | The MCP server is in the demo and is the weak point | READY | `gitops/ai-layer/resources.yaml`: evil-mcp, the look-alike MCP server, is wired with its full rogue toolset until `guard-mcp-on`; a poisoned `get_weather` description chains the agent into `read_internal_config`. The legitimate tools are `gitops/ai-layer/workshop-mcp-server.py`. The beat is `challenges/03-bad-mcp-excessive-agency/` (`agent-prompt.txt`, `evil-mcp-shim/`, `toggle-mcp-authz-on.sh`). Shown as C7 in run-of-show segment 5 | The run-of-show lists no C7 fallback for the admin cluster. #496 adds one (see row 6) | 2026-10-24 michael-admin: with the allow-list open the poisoned description did not chain (FAIL); after `guard-mcp-on` the agent tried the rogue tool and was denied (PASS) |
| 3 | "deploy on a full IDP (internal developer platform)" | The platform is up on the demo cluster, not a laptop-only stand-in | READY | `gitops/bootstrap/admin/app-of-apps-admin.yaml` syncs every Application in `gitops/apps/` except the attendee collector overlay: Argo CD app-of-apps, Kyverno, NetworkPolicies, KubeArmor, Falco, Prometheus, Grafana and Tempo, External Secrets, cert-manager, the AI layer. Roster in `infra/terraform/fleet/roster.tsv`, brought up by `infra/terraform/fleet/fleet.sh`. Toured in run-of-show segment 3 | Backstage is in `gitops/apps-disabled/` and off the KubeCon build list. Michael's audit of 2026-10-24 on #244 says point 3 is deliverable without it; #394 is in the same position. Name no fixed component count on stage | michael-admin brought up 2026-10-24 (#526, #528). Its `converge` result and the teardown's zero check are not recorded (#454) |
| 4 | "It starts wide open, and we let the audience hack it live" | An audience path exists (QR or URL), and the open state can be reset between rehearsals | READY | The community row in `infra/terraform/fleet/roster.tsv` boots `gitops/bootstrap/burn/app-of-apps-burn.yaml`: no Kyverno, no NetworkPolicies, no KubeArmor policy, no Falco. The audience URL is `https://attackme.agenticburn.com/` in `gitops/ai-layer/web/event.js`. The projector QR is `facilitation/kubecon-na-2026-audience-qr.svg`, rendered by `scripts/audience-qr.py`. Reset: every bring-up is a fresh cluster from `fleet.sh instructors up all`, torn down by `teardown/teardown.sh`. Between two run-throughs on one bring-up, `./fleet.sh reset-bot watch-it-burn-community` (`infra/terraform/fleet/fleet.sh`, #539) restarts guard-proxy by a pod delete, which leaves the spec Argo CD owns alone, so its in-memory cost counter, the `COST_CAP_USD` tally and the projected feed start again from zero. It fails unless attackme's public `/cost` then reads $0 over 0 requests. `verify/test_reset_bot.sh` holds the verb and the run-of-show steps: last on the Night Before, and before each run-through ("Run-through record") | The reset has not run on a live cluster yet; its first use is the next bring-up's Night Before or run-through 1. The room hacks, per Michael's two-cluster decision of 2026-10-24 (#448) | attackme up 2026-10-24. The phone check is row 9. `reset-bot` not yet run live |
| 5 | "the relevant Kubernetes security layers you should already have" | Shown before the LLM-specific layer | READY | Run-of-show segment 4 (C1, C2, C3) comes before segment 5 (the AI guardrails). Each control has a fallback that proves it without the model: `challenges/c1-exfil-s3/fallback.kubectl.sh` (egress NetworkPolicy), `challenges/c2-villain-image/fallback.kubectl.sh` (Kyverno registry allow-list), `challenges/c3-secret-grep/fallback.kubectl.sh` (KubeArmor block and alert). The admin profile arms all three from the first minute | #487: the `/controls` Kyverno badge can never light, because the pinned guard-proxy reads the retired ClusterPolicy. The probe expects that FAIL. On 2026-10-24 require-resource-limits denied the C2 dry run first about one try in four; since #529 the probe's Deployment carries limits, so only `restrict-image-registries` can deny it, not yet proven live | 2026-10-24 michael-admin: C1 and C3 PASS; C2 FAIL, denied by require-resource-limits (#529); the Kyverno badge FAIL (#487, expected) |
| 6 | "LLM-specific guardrails, like pre- and mid-inference prompt analysis" | Both points of analysis are on and visibly change the outcome | PARTIAL | Michael decided the meaning on 2026-10-24 (#456). **Pre-inference** is the prompt check before the model: `INPUT_BLOCKLIST` and `INPUT_CLASSIFIER` in `gitops/ai-layer/resources.yaml`, `challenges/02-sanitization/toggle-input-guard-on.sh`, `toggle-input-classifier-on.sh`, and `fallback.curl.sh input` (C6). **Mid-inference** is the check between the agent's steps, on its tool calls and on what the MCP server returns before that reaches the model again. Its output-guard half is on `staging`: `OUTPUT_GUARD`, `challenges/02-sanitization/toggle-output-guard-on.sh` and `fallback.curl.sh output` (C5) | Its agentgateway half is not on `staging`. There the agent dials evil-mcp directly, and the in-path C7 control is kagent's `toolNames` allow-list (the `gitops/ai-layer/resources.yaml` comment). #496 routes evil-mcp through agentgateway and flips an `mcpAuthorization` rule live, with a fallback. It is built on `agent/496-7224` (`0d32213`) and not promoted. Streaming-response scanning is out of scope; do not claim it on stage | 2026-10-24 michael-admin: C6 landed and was then blocked (PASS); C5 leaked with the input guard on but the judge then needed the signature (FAIL, fixed by #530), and was redacted once the output guard was on (PASS) |
| 7 | "good GenAI observability practices" | The traces or dashboard are shown on stage | READY | Without a Datadog pool, segment 6 runs on the admin cluster's Grafana view, `observability-idp/grafana/dashboards/agent-observability.yaml` (uid `witb-agent-obs`). Its "Segment 6" row has one panel per beat (C6, C5, C7). It reads Tempo and needs no Datadog key (#500, closed). With a pool, segment 6 runs on Datadog Agent Observability | No Datadog pool yet. Whitney loads one the week of 2026-10-26, and Datadog-dependent work waits until 2026-10-30 (`decisions.md`, the #454 entry, at `e810736`). Decide on the night before which surface is shown | Not yet shown on a live cluster. The Night Before step confirms each panel shows a row |
| 8 | "By the end the chatbot is selling burritos. Nothing more." | The off-topic and hostile prompts from step 4 are refused at the end | PARTIAL | This repo's half of the on-topic guard (#455): `TOPIC_GUARD` (off at the start), `TOPIC_OFF_LIST`, `TOPIC_ON_LIST` and `TOPIC_REFUSAL` in `gitops/ai-layer/resources.yaml`; `guard-topic-on` and `guard-topic-off` in `gitops/ai-layer/web-terminal/entrypoint.sh`; the rule and the asks it is judged on in `verify/topic_cases.py`, held by `verify/test_topic_guard.py` | The guard itself is not built: the topic stage in `proxy.py` (guard-proxy-agenticburn, `gitops/ai-layer/guard-proxy`) and the BanTopics model in the offline LLM Guard image (llm-guard-cpu-offline, `images/llm-guard`). Until both land and their pins are bumped, `guard-topic-on` exits 1 and segment 7 cannot be shown. If they do not land, point 8 is cut with Whitney's agreement (run-of-show open question 1) | Not shown. The probe's on-topic beats are expected to FAIL (#455) |
| 9 | "Bring your weirdest off-topic question." | The live audience input works over the venue network, with a recorded fallback | PARTIAL | The live path is the community bot through the apex router (run-of-show "The one platform"; #502 keeps it up). The persona tells the wide-open bot to answer harmless off-topic asks (`gitops/ai-layer/resources.yaml`, #530). The real-device record is `facilitation/kubecon-na-2026-phone-check.md` | **Ballroom sizing (#450):** `staging` has `RATE_LIMIT_RPM` 120 and one cluster-wide window. The per-session and per-address limits, the 300/min ceiling and the ordered timeouts are built on `agent/450-7088` (`36e42a7`) and not promoted. **Phones (#451):** the phone check is not filled in. **The answer:** the bot turned the linked-list ask away on 2026-10-24 (#530); it is not promised until the community probe's off-topic beat is 3 of 3. **Recorded fallback (#452):** none on `staging`. The prompt set, the replay script, the asset manifest and the screenshots viewer are on `agent/452-7091` (`0023ac3`), not promoted. The segment videos and screenshots wait for the first full rehearsal, and where the videos are kept is Michael's call on #452 | Off-topic answer failed live 2026-10-24 (#530). Venue network not tried |

## Spend control

The accepted text does not mention spend. The archived BurritoBot CFP draft promised token-based rate limiting
(BurritoBot#58), and the accepted text dropped it. If the deck mentions spend control, this repo covers it: the
C4 budget cap (`COST_CAP_USD` 25 with `guard-budget-on`) and the live cost counter priced at `MODEL_TIER` nova,
both in `gitops/ai-layer/resources.yaml`. The counter's pricing is checked against the pin by
`verify/model_pin_check.py` (#453). In the cut, C4 is narrated during segment 2 and is not its own beat.

## The scope calls from talks-knowledge#29

The BurritoBot assessment sent four scope calls to Michael and Whitney through talks-knowledge#29. That issue is
closed. talks-knowledge recorded the first three answers in its hard-dated note (`e1642bc`, 2026-10-24),
which still lists the fourth as open. This repo now answers all four:

| Call | Answer in this repo | Settled by |
|---|---|---|
| Is there an MCP server? | Yes, evil-mcp, shown as C7 (row 2) | The platform's design, and C7 is in the cut (#448) |
| What "full IDP" means on stage | The admin profile's Argo CD applications, toured in segment 3, without Backstage (row 3) | Michael, 2026-10-24, on #244. talks-knowledge's note says "full IDP includes Backstage", which this supersedes |
| Who hacks, the room or the presenters | The room, from phones, on the community cluster (row 4) | Michael, 2026-10-24, on #448 (two clusters) |
| What counts as mid-inference | Between the agent's steps: agentgateway MCP authorization plus the output guard, on C7 (row 6) | Michael, 2026-10-24, on #456 |

## Keeping this current

Update a row when its evidence changes on `staging`: a fix is promoted, a probe run is recorded, or a point is
cut with Whitney's agreement. Then add a line below. The run-of-show's "Abstract points to segments" table
must say the same thing. `verify/test_kubecon_abstract_readiness.py` holds the structure: nine rows in order,
a legend status on each, a tally that matches, each quote found in the accepted text, and cited paths that exist.

| Date | `staging` | READY | PARTIAL | MISSING | What changed |
|---|---|---|---|---|---|
| 2026-10-24 | `c724652` | 6 | 3 | 0 | First assessment (#456) |
| 2026-10-25 | `aec93e3` | 6 | 3 | 0 | The 2026-10-24 probe run's per-beat results recorded in the run-of-show's "Probe record"; Live column for rows 2, 5 and 6 filled from it (#509) |
| 2026-10-25 | `54e613e` | 6 | 3 | 0 | Row 4: a written reset between two run-throughs on one bring-up, `fleet.sh reset-bot`, in the run-of-show's Night Before and run-through record (#539) |
