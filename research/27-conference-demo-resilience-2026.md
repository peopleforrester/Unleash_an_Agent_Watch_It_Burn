<!-- ABOUTME: Research spike on live cloud/Kubernetes/AI demo failure modes at conferences and a resilience playbook tailored to this workshop. -->
# Conference Demo Resilience: Failure Modes and a Resilience Playbook

## Verification Method

Web research conducted 2026-06-21. Sources are AWS primary documentation, AWS Builder Center /
re:Post knowledge articles, event-networking and live-coding-demo writeups, and the asciinema
project docs. Each load-bearing technical claim is tagged CONFIRMED (verified against a primary
source cited below) or UNCERTAIN (experiential best-practice, common knowledge in the demo-engineering
community, or an inference I made). Much of a demo-resilience playbook is judgement and operational
experience rather than documented fact, so most of the playbook sections carry UNCERTAIN
(best-practice) tags by design. Dollar figures, quota values, and API specifics that change over time
must be re-checked against the live account at build time.

Cross-references to this repo's own prior spikes:
- `research/25-eks-quotas-shared-vpc-topology-2026.md` (EKS / EC2 vCPU quotas, the 60-cluster topology)
- `research/24-datadog-hybrid-impl-sizing-2026.md` (Datadog hybrid + local fallback sizing)
- `cost/README.md` (the live Bedrock cost counter implemented in the guard proxy)
- `facilitation/runbook.md`, `docs/BUILD-SPEC.md` (run-of-show, per-segment recorded fallback)

### Sources

- https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html
- https://docs.aws.amazon.com/general/latest/gr/bedrock.html
- https://repost.aws/knowledge-center/bedrock-throttling-error
- https://www.repost.aws/articles/ARfUsSkaWeSLiWZbv0OVSG1Q/tpm-rpm-quota-monitoring-dashboard-for-amazon-bedrock
- https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/prov-throughput.html
- https://aws.amazon.com/bedrock/pricing/
- https://docs.aws.amazon.com/eks/latest/best-practices/known_limits_and_service_quotas.html
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html
- https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/
- https://docs.aws.amazon.com/cost-management/latest/userguide/manage-ad.html
- https://www.ticketfairy.com/blog/event-wi-fi-networking-in-2026-building-a-reliable-infrastructure-for-seamless-connectivity
- https://blog.doubleslash.de/en/software-technologien/10-tipps-damit-deine-live-coding-demo-garantiert-schief-geht
- https://docs.asciinema.org/getting-started/
- https://cloudlabs.ai/solutions/hands-on-gtm

---

## Our risk surface (the things this playbook is tailored to)

1. The demo agent calls AWS Bedrock (Claude) over the internet. Any network failure breaks the live
   agent path, not just the slides or the UI. This is the single most exposed dependency.
2. Roughly 60 independent EKS clusters in a shared VPC, one AWS account (accen-dev, <ACCOUNT_ID>),
   region us-west-2, for a 2-hour intermittent lab.
3. Observability flows to Datadog (primary) over the network, with Grafana / Tempo local fallback.
4. Attendees self-drive their own cluster via a chat UI and kubectl, with per-student Datadog orgs
   (about 60).
5. A 2-hour hard time box (Day 1, 2:20 to 4:20pm, Track 5) with multiple beats: three CNCF-control
   attacks, AI-guardrail toggles, and a model-tier cost comparison.

---

## 1. Top failure modes

Likelihood and impact are on a Low / Medium / High scale and are my assessment (UNCERTAIN) for a
San Francisco conference workshop with this specific architecture. They are calibrated by where this
demo concentrates risk (an over-the-internet agent path plus 60 live clusters), not generic.

### 1.1 Conference WiFi / bandwidth saturation
- **Likelihood: High. Impact: High.** This is the textbook conference-demo killer. Conference WiFi is
  oversubscribed in popular sessions, and a workshop where about 60 attendees simultaneously open a
  chat UI, stream kubectl, and load per-student Datadog dashboards is exactly the load pattern that
  saturates it. UNCERTAIN (best-practice); the general unreliability of conference WiFi is widely
  documented (doubleslash live-coding writeup; event-networking 2026 writeup).
- **Why it is worse for us:** our agent path is not local. Every agent turn is a round trip to Bedrock
  over that same congested link. WiFi degradation does not just slow the UI, it stalls the live agent.
- **Mitigations:**
  - Do not present the agent over attendee WiFi for the facilitator-driven beats. Drive the on-stage
    demo from a wired uplink or a dedicated cellular hotspot reserved for the presenter laptop
    (Section 2, uplink backup). UNCERTAIN (best-practice).
  - Pre-record every beat as an asciinema cast so the on-screen story never depends on the link
    (Section 2). CONFIRMED the repo already scaffolds per-segment recordings (`docs/BUILD-SPEC.md`,
    Phase 9; `facilitation/runbook.md`).
  - For attendee self-drive, keep the chat UI and terminal lightweight (text, not video). Push heavy
    dashboards to "look at this on the projector" rather than 60 simultaneous Datadog loads.
  - Have attendees who can tether to cellular do so, to take load off the room WiFi. UNCERTAIN.

### 1.2 DNS resolution failure
- **Likelihood: Medium. Impact: High.** Captive portals, split-horizon resolvers, and overloaded
  conference DNS frequently break name resolution even when raw connectivity is fine. The demo uses a
  custom domain (`agenticburn.com`, per `infra/dns/`), Bedrock regional endpoints, EKS API endpoints,
  and Datadog intake hosts, all resolved by name. UNCERTAIN (best-practice).
- **Mitigations:**
  - The repo already has a DNS test (`verify/test_dns.py`); run it from the venue network during
    setup, not just from the build box. CONFIRMED the test exists.
  - Pre-resolve and pin the small set of critical hostnames in `/etc/hosts` on the presenter laptop
    as a fallback (Bedrock runtime endpoint, EKS API for the demo clusters, Datadog intake, the demo
    domain). Treat this as a documented, reversible step, not a permanent change. UNCERTAIN.
  - Carry a known-good public resolver config (for example 1.1.1.1 / 8.8.8.8) ready to apply on the
    presenter machine if the venue resolver is the problem. UNCERTAIN (best-practice).

### 1.3 Cloud API rate limits and throttling, Bedrock especially
- **Likelihood: High. Impact: High.** This is the most underestimated risk for this specific demo. When
  account quotas are exceeded, Bedrock returns a 429 ThrottlingException ("Too many tokens, please wait
  before trying again"). CONFIRMED (repost.aws throttling article; quotas docs).
- **The mechanism that bites us:** Bedrock charges requests against per-minute token quotas (TPM) and
  per-minute request quotas (RPM), and reserves tokens at the START of a request equal to
  `input tokens + max_tokens`, then reconciles at the end. CONFIRMED (quotas / token-burndown docs).
  A large `max_tokens` reserves a large block up front even if the reply is short, so it eats the TPM
  quota faster than the visible output suggests.
- **Why our demo is high-risk:** the entire premise is hammering the agent ("watch it burn"). On
  Clusters 1 and 2 the agent is intentionally driven hard. With about 60 attendees each driving an
  agent on Cluster 3, the account-level Bedrock quota in us-west-2 is a shared pool across all of them.
  The default on-demand quotas (commonly cited around 1,000 RPM and a six-figure TPM for a Claude
  model, but account-specific and region-specific) can be exhausted by aggregated attendee load.
  UNCERTAIN on the exact default numbers; CONFIRMED that quotas are account- and region-scoped and
  that aggregate load draws from one pool.
- **Mitigations (in priority order):**
  - **Pre-check the live applied quota.** Read the actual TPM / RPM for the chosen Claude model in the
    Service Quotas console for us-west-2 on the accen-dev account, do not trust the documented default.
    AWS may have auto-raised it, or it may still be low. CONFIRMED (quotas docs say applied quotas vary
    by account history). This is a build-time pre-flight item.
  - **Request a quota increase well ahead of the event.** Bedrock model quota increases go through
    Service Quotas and can take days, so file early. CONFIRMED (quota-increase path documented). The
    increase is region-specific (us-west-2).
  - **Use a cross-region inference profile.** Calling a `us.anthropic.*` cross-region profile can reach
    up to double the in-region quota and absorbs traffic bursts by routing to multiple US regions.
    CONFIRMED (cross-region-inference docs: "up to double the default in-region quotas"). From us-west-2
    (Oregon), routing targets include us-east-1 and us-west-2. CONFIRMED. This is the single highest-leverage
    throttling mitigation for an aggregated-attendee burst and should be the default invocation path.
  - **Cap `max_tokens` deliberately** on the demo agent so each request reserves less of the TPM pool.
    CONFIRMED that reducing max_tokens lowers the initial reservation (throttling troubleshooting).
  - **Exponential backoff with jitter** on the agent's Bedrock client, so a transient 429 self-heals
    instead of cascading into visible failure. CONFIRMED (standard throttling guidance).
  - **The cheap input block-list helps here too:** the guard proxy's `BLOCK_LIST` rejects destructive
    intent before the LLM call, which on Cluster 3 both tells the cost story and reduces Bedrock load.
    CONFIRMED in repo (`cost/README.md`).
  - Consider Provisioned Throughput only if a quota increase is denied or insufficient. It guarantees
    capacity via purchased model units but is billed hourly for a 1-month minimum commitment whether
    used or not, so for a 2-hour event it is an expensive insurance policy, not a default. CONFIRMED
    (prov-throughput / pricing docs; 1-month minimum). UNCERTAIN whether it is worth it here; my read is
    a quota increase plus cross-region inference is the better fit for a one-off 2-hour window.

### 1.4 Region capacity and latency (us-west-2)
- **Likelihood: Low to Medium. Impact: Medium to High.** Two distinct risks. (a) EC2 capacity:
  spinning up about 60 clusters' worth of nodes at once can hit `InsufficientInstanceCapacity` for a
  given instance type in a given AZ, especially if provisioning is bunched right before doors.
  UNCERTAIN (capacity is real but episodic). (b) Latency: us-west-2 is geographically close to a San
  Francisco venue, which is good for agent round-trip latency. CONFIRMED region choice is favorable.
- **Mitigations:**
  - Pre-provision well before doors (Section 4 decision) so capacity errors surface with time to react,
    not on stage. UNCERTAIN (best-practice).
  - Spread node groups across multiple AZs in the shared VPC and allow a small set of instance types
    rather than pinning one, so a single-type capacity gap does not block a cluster. UNCERTAIN.
  - For agent latency, the cross-region inference profile and a us-west-2 primary keep round trips short.

### 1.5 Cost spike / runaway spend
- **Likelihood: Medium. Impact: High.** The demo's own theme is "wasted tokens are the new DoS," so it
  deliberately generates spend, and 60 attendees plus about 60 live clusters multiply both Bedrock and
  EC2 cost. A stuck agent loop or a cluster that is not torn down is a real money leak. UNCERTAIN
  (likelihood); CONFIRMED that the demo intentionally drives spend (`README.md`, `cost/README.md`).
- **Mitigations:**
  - **AWS Budgets with a budget action as a kill switch.** When a threshold is breached, AWS Budgets can
    automatically apply a deny IAM policy or stop instances, no Lambda required. CONFIRMED (cost-anomaly /
    budgets writeups). Set a hard budget for the event day on accen-dev.
  - **AWS Cost Anomaly Detection** to catch an unexpected spike within hours rather than on the invoice.
    CONFIRMED (AWS Cost Anomaly Detection docs). Note it is detect-and-alert, not auto-stop; pair it with
    a Budget action for the actual stop. CONFIRMED.
  - **The live cost counter** already implemented in the guard proxy gives an on-screen, per-cluster
    running estimate so a runaway is visible in seconds, not hours. CONFIRMED in repo (`cost/README.md`).
    Authoritative post-hoc cost still comes from Cost Explorer via `teardown/cost-report.sh`.
  - **Per-attendee guardrails:** cap `max_tokens`, keep node sizes modest (the repo's 60-cluster sizing
    work lands on t3-family nodes), and ensure teardown actually runs (Section 4 decision). CONFIRMED
    sizing context in `research/25`.

### 1.6 Attendee self-provisioning chaos and support load
- **Likelihood: High. Impact: Medium.** About 60 people self-driving clusters and per-student Datadog
  orgs will produce a long tail of "mine isn't working," wrong-URL, expired-token, and "I deleted
  something" issues, all arriving in the first 15 minutes. Hands-on lab providers explicitly pre-provision
  environments with built-in cost controls precisely because live self-provisioning at scale does not
  hold up. UNCERTAIN (best-practice; cloudlabs hands-on writeup).
- **Mitigations:**
  - **Pre-provision everything before doors.** Attendees should claim a ready cluster, not create one.
    This is the most important single decision for support load (Section 4). UNCERTAIN (best-practice).
  - A claim/check-in mechanism (one cluster per attendee, pre-baked) with a printed or on-screen
    quickstart. The repo already has `access/quickstart.md`. CONFIRMED it exists.
  - A spare pool of pre-provisioned clusters beyond the headcount, because some die (the fork-bomb beat
    is designed to kill them) and some attendees will brick theirs. CONFIRMED the demo expects clusters
    to die (`README.md`: "We keep spares").
  - Co-facilitator(s) working the room as live support while the presenter drives the main thread.
    UNCERTAIN (best-practice). Whitney is co-presenting (`facilitation/`), so define who owns support.
  - A single "if you are stuck, watch the projector" fallback so a broken attendee environment never
    blocks the shared narrative.

### 1.7 Time overrun
- **Likelihood: High. Impact: Medium.** A 2-hour hard box with three attacks times two clusters, plus
  attendee free-play, plus AI-guardrail toggles, plus a model-tier cost comparison, is a lot of beats.
  Live troubleshooting is the usual cause of overrun. UNCERTAIN (best-practice). The repo's own notes
  flag the regroup as "the part to protect" (`research/25` / BUILD-SPEC).
- **Mitigations:**
  - A per-beat time budget written into the run-of-show, with a hard "cut to recording" rule if a beat
    runs over (Section 2 toggle). UNCERTAIN.
  - Pre-recorded casts let a beat be shown in fixed time regardless of live conditions. CONFIRMED scaffold.
  - Identify droppable beats in advance (for example the optional OTel trace re-leak trap is already
    marked optional in BUILD-SPEC). CONFIRMED it is marked optional.
  - Protect the governance-map regroup at the end; it is the takeaway. Do not let setup chaos eat it.

### 1.8 Laptop / display / adapter / clicker failure
- **Likelihood: Medium. Impact: High.** A dead adapter or a laptop that will not mirror to the Moscone
  projector ends the demo before it starts. UNCERTAIN (best-practice; common live-event failure).
- **Mitigations:**
  - Carry multiple display adapters (USB-C to HDMI and to the venue's connector), a spare cable, and a
    backup clicker with fresh batteries. UNCERTAIN.
  - A second laptop that can run the recorded casts and the slides, fully synced, as a hot spare.
    UNCERTAIN (best-practice).
  - Test the actual projector and resolution during the setup window, not at 2:20pm. Set terminal font
    large enough to read from the back of the room. UNCERTAIN.

### 1.9 Secrets / key distribution at scale
- **Likelihood: Medium. Impact: Medium to High.** Getting per-attendee cluster credentials, chat-UI
  access, and per-student Datadog org access to about 60 people without leaking anything and without a
  20-minute scramble is a real logistics problem. UNCERTAIN (best-practice).
- **Mitigations:**
  - Pre-generate per-attendee access bundles and distribute via a claim mechanism (a code on a card, a
    per-seat URL), not a shared secret read aloud. UNCERTAIN.
  - All planted secrets in the clusters are already synthetic with a `FAKE-` prefix, so a leaked demo
    secret is harmless by design. CONFIRMED (`README.md` Safety section). Keep that invariant.
  - Real credentials (AWS, Datadog admin) live only on facilitator machines, never on attendee paths.
    Follow the repo's env-vault discipline. UNCERTAIN that it is wired here; CONFIRMED the global rule.
  - Scope per-attendee kube access to their own namespace/cluster only (the repo already runs the
    fallback as the scoped `agent-sa` ServiceAccount). CONFIRMED in `beats/01-cncf-wall/fallback.kubectl.sh`.

### 1.10 Clock skew / certificate issues
- **Likelihood: Low. Impact: Medium to High.** TLS to Bedrock, EKS, and Datadog fails if the presenter
  laptop clock is skewed, and cert-manager-issued certs in the platform can expire or be not-yet-valid
  if a cluster's clock is off. A captive portal can also interpose on TLS. UNCERTAIN (best-practice).
- **Mitigations:**
  - Verify NTP / system clock on the presenter laptop and demo machines during setup. UNCERTAIN.
  - Sanity-check that platform certs (cert-manager, any demo TLS) are valid for the event window before
    doors; re-issue if a long-lived cluster has drifted. UNCERTAIN.
  - If a captive portal interposes on TLS, the cellular hotspot uplink (Section 2) bypasses it.

---

## 2. Resilience playbook

All of Section 2 is UNCERTAIN (best-practice) unless a specific item is tagged CONFIRMED against this
repo's existing assets or an AWS primary source.

### 2.1 What to pre-record vs run live
- **Pre-record (asciinema cast per beat):** every beat that depends on the over-the-internet agent path
  or on a cluster surviving. That is all three CNCF-control attacks on Clusters 1 and 2 (the fork bomb
  literally kills the cluster), the AI-guardrail toggles, and the model-tier cost comparison.
  asciinema casts are lightweight terminal recordings that replay in a real terminal or embed in slides,
  with no network dependency at playback. CONFIRMED (asciinema docs; repo scaffolds per-segment casts).
- **Run live (when conditions allow):** the attendee self-drive portion on Cluster 3, because the value
  there is the attendee doing it, not the facilitator. But gate it behind a working pre-flight
  (Section 3) and keep a recording ready if the room network fails.
- **Rule of thumb:** the narrative must be fully tellable from recordings alone. Live is the upgrade,
  not the dependency. This is the central lesson from live-coding-demo retrospectives. UNCERTAIN
  (best-practice; doubleslash writeup, satirically: "a plan B is not necessary" is the wrong attitude).

### 2.2 Local / offline fallbacks already in the repo
- `beats/01-cncf-wall/fallback.kubectl.sh` proves all three CNCF walls without the agent, running as the
  scoped `agent-sa` so outcomes match the live demo. CONFIRMED in repo.
- `beats/02-sanitization/fallback.curl.sh` drives both sanitization guards with curl, proving the
  guardrail (not the model) is what fires, in both input and output directions. CONFIRMED in repo. Note
  the `verify-at-build` comments in that file: the gateway reject-status and the LLM Guard
  `/analyze/output` envelope must be confirmed against the live services before relying on the asserts.
- `beats/03-bad-mcp-excessive-agency/fallback.curl.sh` covers the MCP excessive-agency beat. CONFIRMED.
- These are model-independent by design, so they survive a Bedrock outage or throttle entirely. That is
  the key property: the fallbacks prove the controls without ever calling the model. CONFIRMED.
- Observability fallback: Datadog is primary over the network; Grafana / Tempo / Loki / Prometheus /
  OpenTelemetry are the local in-cluster fallback. If Datadog intake is unreachable, the story is still
  visible on the local Grafana. CONFIRMED (`README.md` stack; `research/24`).

### 2.3 Hotspot / uplink backup
- Reserve a dedicated cellular hotspot (or two, on different carriers) for the presenter laptop, kept
  off the attendee WiFi. The agent path and the on-stage demo run over this, not the room. UNCERTAIN
  (best-practice). Multi-layer event networks (separate staff vs attendee links) exist for exactly this
  reason. UNCERTAIN (event-networking 2026 writeup).
- Pre-test the hotspot from inside the venue if possible; SF convention centers can have poor indoor
  cellular. If indoor cellular is weak, the recorded casts become the primary path, not the backup.
- Know the venue's wired-uplink option (if Moscone offers a hardline for presenters, request it ahead).

### 2.4 Pre-provisioning before doors
- Provision all attendee clusters plus a spare pool before doors open, never during the session.
  CONFIRMED this is the repo's intent (spares expected). Decision on the exact window is in Section 4.
- Run the full verify harness against the provisioned fleet before doors (`verify/run-all.sh`).
  CONFIRMED the harness exists and takes an explicit kube-context per the repo's context-safety rules.
- Confirm Bedrock reachability and quota headroom from the venue network during the setup window
  (Section 3), because a quota that was fine yesterday on the build box can be exhausted by a rehearsal.

### 2.5 Per-beat live-vs-recorded toggle
- Build an explicit toggle so each beat can be flipped between live and recorded without re-cutting the
  flow. Mechanically this can be as simple as a presenter script where each beat has two entries
  (a live command block and an `asciinema play <cast>` block) and a single decision at the top of the
  beat. UNCERTAIN (best-practice). The repo already states "Pre-recorded fallback per segment" as a
  design invariant. CONFIRMED (BUILD-SPEC).
- Decision rule for the toggle: if the pre-flight (Section 3) for that beat passed within the last N
  minutes and the network is healthy, go live; otherwise play the cast. The default under any doubt is
  the cast.

### 2.6 Bedrock rate-limit / quota pre-checks
- Before doors: read the live applied TPM / RPM for the chosen Claude model in Service Quotas
  (us-west-2, accen-dev). CONFIRMED (quotas docs). A re:Post article documents building a TPM/RPM quota
  monitoring dashboard from CloudWatch; a lighter version (a CloudWatch alarm on Bedrock throttle count)
  is enough for event day. CONFIRMED (re:Post TPM/RPM dashboard article).
- Confirm the cross-region inference profile is the configured invocation path and that it works from
  the venue. CONFIRMED cross-region is the right lever.
- Smoke-test one agent turn end to end from the venue network during setup, and watch for a 429.

### 2.7 Cost cap / kill switch
- AWS Budgets with a budget action (deny-IAM-policy or stop-instances) as the hard stop. CONFIRMED.
- AWS Cost Anomaly Detection as the early-warning. CONFIRMED.
- The live in-proxy cost counter as the human-visible, second-by-second signal. CONFIRMED (repo).
- A manual kill path: a one-command script that scales the agent deployments to zero across the demo
  clusters, so a runaway can be stopped in seconds without waiting for a budget threshold. The repo's
  context-safety rules require an explicit `--context` on every kubectl call; the kill script must take
  the context explicitly and never fall back to current-context. CONFIRMED (repo CLAUDE.md). UNCERTAIN
  whether such a script exists yet; if not, it is worth adding (Section 4).

### 2.8 Dry-run protocol
- A full dress rehearsal on the real account in us-west-2, over a constrained network (tether the build
  box to a phone to simulate venue conditions), running every beat live once and every cast once.
  UNCERTAIN (best-practice).
- The rehearsal must exercise the aggregate-load case at least in miniature: drive several agents at
  once to see whether the Bedrock quota throttles, because a single-user rehearsal will not surface the
  60-attendee throttling risk (Section 1.3). UNCERTAIN but important.
- Rehearse the failure path on purpose: kill the network mid-beat and confirm the toggle to the cast is
  smooth and the recordings actually play on the presenter machine offline.
- Run the verify harness and the fallback scripts end to end as part of the rehearsal, not just the
  happy path. CONFIRMED the harness and fallbacks exist.

---

## 3. Pre-flight checklist (morning of the event)

Run this from the VENUE network on the actual presenter machine, not from the build box. All items
UNCERTAIN (best-practice) unless tagged.

Connectivity and DNS
- [ ] Presenter laptop on the reserved uplink (wired or hotspot), NOT attendee WiFi.
- [ ] `verify/test_dns.py` passes from the venue network. CONFIRMED test exists.
- [ ] Critical hostnames resolve: Bedrock runtime endpoint (us-west-2), EKS API endpoints, Datadog
      intake, the demo domain. `/etc/hosts` fallback ready if resolution is flaky.
- [ ] System clock / NTP correct on presenter and demo machines (TLS depends on it).

Bedrock
- [ ] Live applied TPM / RPM read in Service Quotas for the chosen Claude model, us-west-2. CONFIRMED path.
- [ ] Quota-increase request confirmed APPROVED (must have been filed days earlier). CONFIRMED process.
- [ ] Cross-region inference profile confirmed as the invocation path and reachable from venue. CONFIRMED lever.
- [ ] One live agent turn smoke-tested end to end, no 429.
- [ ] `max_tokens` cap confirmed set on the demo agent.
- [ ] CloudWatch alarm on Bedrock throttle count armed. CONFIRMED feasible.

Clusters and platform
- [ ] All attendee clusters provisioned and healthy; spare pool provisioned beyond headcount. CONFIRMED intent.
- [ ] `verify/run-all.sh` green against the fleet (explicit `--context` per cluster). CONFIRMED harness + rule.
- [ ] Platform certs (cert-manager / demo TLS) valid for the event window.
- [ ] Per-attendee access bundles ready and the claim mechanism tested.
- [ ] Planted secrets confirmed synthetic (`FAKE-` prefix). CONFIRMED invariant.

Cost guardrails
- [ ] Event-day AWS Budget set with a budget ACTION (kill switch) on accen-dev. CONFIRMED feasible.
- [ ] Cost Anomaly Detection monitor active. CONFIRMED feasible.
- [ ] Live cost counter rendering on the demo UI. CONFIRMED implemented.
- [ ] Manual "scale agents to zero" kill script tested with explicit context.

Fallbacks and recordings
- [ ] Every beat's asciinema cast present and plays OFFLINE on the presenter machine. CONFIRMED scaffold.
- [ ] `fallback.kubectl.sh` and both `fallback.curl.sh` run green against a live cluster. CONFIRMED exist.
- [ ] `verify-at-build` asserts in the fallback curl script confirmed against live services. CONFIRMED TODO in repo.
- [ ] Grafana / Tempo local observability up as the Datadog fallback. CONFIRMED stack.
- [ ] Per-beat live-vs-recorded toggle decision sheet in hand. CONFIRMED design invariant.

Hardware and room
- [ ] Projector tested at the real resolution; terminal font large enough for the back row.
- [ ] Two display adapters, spare cable, backup clicker (batteries).
- [ ] Hot-spare laptop synced with slides and casts.
- [ ] Co-facilitator support roles assigned (who drives, who works the room).

---

## 4. Specific decisions this forces for us

These are the calls that have to be made and committed before the event. My recommendation is given;
the decision is Michael's.

1. **Provision-before-doors window.** Decide when the fleet of about 60 clusters plus spares is built
   and the verify harness is run, with enough slack to catch `InsufficientInstanceCapacity` and re-try
   in a different AZ or instance type. Recommendation: provision the evening before and re-verify the
   morning of, not in the setup window before a 2:20pm slot. CONFIRMED capacity errors are episodic and
   need react time (Section 1.4).

2. **Does the agent get an offline / echo fallback?** Right now the model-free fallbacks
   (`fallback.kubectl.sh`, `fallback.curl.sh`) prove the CONTROLS without the agent, which is the right
   call and already built. CONFIRMED. The open question is whether the AGENT itself needs a degraded
   "echo" mode for the parts of the story that are specifically about the agent's behavior. Per the
   repo's no-mock-modes rule, a fake agent response is not acceptable; the honest fallback is the
   pre-recorded cast of a real agent run, not a stub. Recommendation: NO synthetic agent; rely on the
   recorded casts for the agent-narrative beats and the model-free scripts for the control beats. This
   needs an explicit decision because it determines what happens on stage if Bedrock is throttled.

3. **Bedrock quota request.** Decide the target TPM / RPM and FILE THE INCREASE NOW (days of lead time).
   CONFIRMED the process is slow. Decision inputs: estimated aggregate tokens across about 60 attendees
   on Cluster 3 plus the facilitator-driven hammering on Clusters 1 and 2. Recommendation: file a
   generous increase for the chosen Claude model in us-west-2 AND adopt the cross-region inference
   profile as the default path (up to double in-region quota, CONFIRMED). Re-check the applied value at
   pre-flight. Do NOT default to Provisioned Throughput for a 2-hour event (1-month minimum commitment,
   CONFIRMED), keep it only as a denial-of-quota backstop.

4. **Per-attendee cost guardrails.** Decide the per-agent `max_tokens` cap, the node size for the
   per-student clusters (the repo's sizing work points at t3-family; CONFIRMED in `research/25`), and the
   event-day AWS Budget threshold plus the budget ACTION that fires at it. CONFIRMED budget actions can
   auto-deny or auto-stop. Recommendation: set a hard event-day budget with a stop-instances/deny action,
   cap max_tokens conservatively, and confirm `teardown.sh` actually removes attendee resources after the
   session so spend stops at the door. CONFIRMED teardown is planned (BUILD-SPEC Phase 9).

5. **Live-vs-recorded default and the toggle owner.** Decide the default posture (recommendation:
   recorded is the default, live is the upgrade gated on a passing pre-flight) and WHO makes the
   live-or-cast call per beat in the moment. With Whitney co-presenting, assign it explicitly so it is
   not negotiated on stage. UNCERTAIN (operational).

6. **Manual kill switch exists or gets built.** Decide whether to add a one-command "scale all demo
   agents to zero" script (explicit `--context`, no current-context fallback, per repo rule) as a fast
   manual stop independent of the AWS Budget threshold. Recommendation: build it; a budget action can lag,
   and a stuck loop on stage needs a sub-minute stop. UNCERTAIN whether one exists today.

7. **Aggregate-load rehearsal.** Decide to run at least a miniature multi-agent load test before the
   event so the 60-attendee Bedrock throttling risk is surfaced in rehearsal, not on stage. A
   single-user dry run will not reveal it. Recommendation: yes, drive several agents at once during the
   dress rehearsal and watch for 429s. UNCERTAIN (best-practice) but directly de-risks the highest
   technical risk (Section 1.3).
