# Go-Live Checklist

ABOUTME: The complete remaining work to run the workshop, grouped by priority.
ABOUTME: P0 = the workshop cannot run without it; P1 = the demo will not land right; P2 = polish.

**Delivery: DevOpsDays Portland 2026, Tuesday September 8, 1:00 to 3:00 PM Pacific, Room 327.**

Updated 2026-09-02. Check items off here as they land; "done" detail goes to PROGRESS.md.
The header used to read "~4 days out" against the June AI Engineer World's Fair date, which is done;
countdowns rot, so this file names the delivery date instead of a distance from it.

## Already done (so we don't re-litigate)

- AI layer validated end-to-end on a live cluster: guard-proxy -> agentgateway -> kagent -> Bedrock
  (via the VPC endpoint), cost recorded. C1 egress holds (agent -> S3/internet denied).
- Datadog primary pipeline: UST, spans, datadog/connector, gen_ai semconv (token + cost), Falco -> DD.
- Provisioning distributor LIVE (provisioning.agenticburn.com): admin exception (Michael/Whitney) +
  attendee claim flow, tested.
- Datadog trial pool (22 orgs) staged in Secrets Manager; 2 pulled out and labeled (instructor +
  admin-attendee).
- Whitney's 4 experiment clusters provisioned + bootstrapped (branch-per-cluster).
- fleet.sh auto-bootstraps the IDP on provision.
- accen-dev EC2 vCPU quota raised to 800. Decks (walkthrough 60-min, rounds) updated.

---

## P0 — the workshop cannot run without these

### 0. Morning-of verification (run these three, read the output)

These exist because "Argo CD says Synced" does not mean a cluster carries every fix: ConfigMap content
arrives via Argo CD, guard-proxy env only via a live patch, images only when a pod is cycled, and the
terminal credential is a bootstrap Secret.

```bash
# a) every cluster carries every shipped fix (19 checks, one line per cluster)
for c in $(aws eks list-clusters --region us-west-2 --profile accen-dev --query 'clusters[]' --output text); do
    verify/fleet-drift-audit.sh "$c"; done

# b) the prompts still land on the live model (green/yellow/red per beat)
python3 verify/agent_probe.py michael-round3.agenticburn.com --context <ctx> --profile accen-dev

# c) hostnames, TLS and websockets
infra/terraform/fleet/check-tls.sh michael-round1.agenticburn.com michael-round2.agenticburn.com
```

- [ ] Drift audit clean on every cluster (expected values are documented in the script header).
- [ ] Probe reports no **red** beats. Yellow on C5 or C7 is Nova being inconsistent, not a broken cluster:
      re-run, and if it declines twice use the ranked fallbacks in `challenges/PROMPT-CATALOG.md`.
- [ ] Guards left **off** on the Round 3 / attendee clusters so students see the weakness first.

```bash
# d) are the Datadog orgs still alive? (trial orgs expire in ~14 days)
AWS_PROFILE=accen-dev verify/datadog-pool-check.sh
```

```bash
# e) standing hygiene: advisories, pinned versions, orphaned AWS resources, slot-id leaks
WIB_PROBE_EMAIL=<an address that already holds a claim> verify/fleet-hygiene.sh
```

- [ ] `HYGIENE CLEAN`. This replaces four checks that used to be run by hand and therefore were not
      run consistently. It reports open Dependabot alerts, prints every pinned chart version for
      comparison against the projects' own advisory pages, surveys all five accounts for load
      balancers, target groups and volumes tagged for a cluster that no longer exists (#157), and
      RENDERS the claim page to confirm the internal slot id is not shown to a student.
- [ ] Orphans found? `WIB_APPLY=1 infra/terraform/fleet/fleet.sh reap-lbs` deletes them. The survey
      is always dry-run; deleting is a separate deliberate act.

- [ ] Every cluster reports `api=200 org_read=200`.

```bash
# f) THE ONE THAT MATTERS MOST: drive a real browser against every cluster
uv run --with playwright python verify/browser-smoke.py
uv run --with playwright python verify/browser-smoke.py hexhen-zelda sorcerizo-glinda   # student clusters
```

- [ ] `BROWSER SMOKE CLEAN` on every cluster. **Run this before any demo, and after any web change.**
      On 2026-09-03 two workshop-breaking bugs reached a live demo and neither was visible to curl: an
      Origin check that 403'd every browser (curl sends no Origin, so every probe passed), and a round
      banner telling students on fully-guarded clusters "NO GUARDRAILS, nothing is watching" (the DOM was
      wrong while the HTTP response was perfect). Both live in what the browser does with the response.
      The smoke test sends a real prompt through the page's own fetch, reads the rendered banner, checks
      an actual answer arrived outside `<thinking>`, and confirms Send is on screen.
- [ ] **Hard-refresh before trusting a manual check** (Cmd-Shift-R). A cached page against a fixed
      cluster looks identical to a broken one; this cost a wrong diagnosis on 2026-09-03.
- [ ] **Whitney opens her Datadog org in a browser before doors.** The check above proves the KEYS work;
      it cannot prove a human can log in, and a Datadog trial can end for the web UI while keys still
      validate. That is the exact shape of her 2026-08-29 report on a fleet whose keys were all fine.

### 1. The 5-account fleet for ~250 attendee clusters
- [x] Confirm the other 4 AWS accounts exist and we have CLI access (a profile each). Verified
      2026-09-02: all 5 profiles resolve to their pinned account ids via `preflight.sh`.
- [x] Quota increases on each of the 4 accounts (us-west-2), all adjustable, file now. **Granted and
      verified live 2026-09-02 on all 5 accounts: vCPU 800, ALB 100, NLB 100, EKS 100.** Proven against
      accen-dev's live resources + AWS docs on 2026-06-26 (see DECISION-LOG):
      - EC2 vCPU "Running On-Demand Standard Instances" (L-1216C47A): 800 (accen-dev already 800; ~2-min auto-approve).
        The code is `L-1216C47A`; this file carried `L-1216C47` until 2026-09-02, which returns
        `NoSuchResourceException` from `service-quotas` and reads as "no such quota" rather than a typo.
      - **Application Load Balancers per Region (L-53DA6B97): 50 -> 100.** Each full cluster = 1 internet-facing ALB;
        50 clusters is at the wall, 60 is over the default 50.
      - **Network Load Balancers per Region (L-69A177A2): 50 -> 100.** Each full cluster = 1 internal NLB; same wall.
      - Elastic IPs: NO increase needed. Internet-facing ALB IPs are AWS-managed and do not count; only the one
        shared-VPC NAT gateway counts (1 of 5). Confirmed: 9 EIPs visible in accen-dev under a quota of 5.
- [x] `lab-vpc` applied once per account (5 shared VPCs total, each with the Bedrock endpoint).
      Re-applied to the 4 student accounts 2026-09-02: the 2026-06-27 teardown-to-zero destroyed them
      and they were never rebuilt. Pre-seeded rather than built on the day, because the VPC is the one
      fleet dependency with no in-cluster fallback and it costs ~$1.56/account/day to leave standing
      (one NAT gateway + the Bedrock endpoint's two ENIs).
      **Verify with `preflight.sh`, not by looking for the state file.** `terraform destroy` leaves the
      state file behind with `resources=0` and no outputs, so the old file-existence check reported
      PREFLIGHT GREEN across four accounts that had no VPC at all. The check now reads the `vpc_id`
      output and confirms that VPC still exists in the account.
- [ ] Cross-account fan-out in `fleet.sh` (`up-fleet`): run all 5 accounts' pools concurrently so 250
      come up in one ~30-min window, not five serial batches.
- [ ] A real dry-run before the day: at minimum 50 in one account end-to-end, ideally a 10-cluster
      cross-account smoke.

### 2. The real attendee pool (the committed pool.csv is a placeholder)
- [ ] Per-attendee AWS keys: scoped IAM users/keys for ~250 attendees (or a per-cluster-scoped scheme).
- [ ] Merge the attendee Datadog accounts with the AWS keys into the real pool (`merge_pool.py`). The new
      DevOpsDays Portland pool (60 orgs, expires 2026-09-18, tested 60/60 on 2026-09-05) is staged in Secrets Manager (`watch-it-burn/datadog-pool`
      + `watch-it-burn/datadog-pool-2`, split because one secret caps at 64 KB); `merge_pool` reads both.
      Merge once the per-attendee AWS keys exist. (Old expired trial pool replaced 2026-06-26.)
- [ ] Deploy the real pool to the distributor (Railway), replacing the placeholder seed.
- [ ] Per-cluster Datadog secret wiring: each attendee cluster's ESO points at that attendee's DD
      account (`distribute_datadog_keys.py`), so metrics land in the right org.
- [ ] End-to-end attendee test: email at the URL -> cluster URL + working chat + Datadog metrics flowing.

### 3. Attendee access at the door
- [ ] start.agenticburn.com / QR index reachable and points at the provisioning page.
- [ ] Provisioning page tested under light concurrency (it is single-worker today; confirm it holds).

---

## P1 — demo correctness (the rounds and challenges must land)

- [x] **R1 true burn**: R1 (burn) clusters run `podPidsLimit=-1`. The fork-bomb validation this line used
      to demand is **no longer a delivery gate**: the fork bomb was retired as a beat (#114) because Nova
      refuses it in chat. C4 is now denial-of-wallet, verified live 2026-08-29 (spend froze at the cap, the
      blocked request cost zero). The PID cap is still deployed and still demonstrable from a terminal.
- [x] **C7 MCP authorization enforcement**: the kagent `toolNames` allow-list is the ratified mechanism and
      the `guard-mcp-on` toggle is live. Measured on Nova 2026-08-30: the sentinel leaks 4/5 with the guard
      off and never appears with it on (`challenges/PROMPT-CATALOG.md`).
- [ ] **Model-tier override** live-validate on the haiku/sonnet/opus instructor clusters (the cost race).
      NOTE: the workshop default is now **Nova Pro**, and `MODEL_TIER` on the guard-proxy must match the
      bound ModelConfig or the counter prices the wrong model. Argo CD `ignoreDifferences` excludes that env
      block, so it is a live `kubectl set env` behind a Kyverno flip; see docs/GOTCHAS-FLEET-AND-DELIVERY.md.
      Mechanism is in code (ignoreDifferences + setup-instructor-cluster.sh patch), not yet validated live.
- [ ] **C1/C3/C4 runbooks** packaged: attendee + facilitator instructions. Defenses are validated; the
      delivery wrappers (beat.md-style) and the C3 bait-file plant script do not exist yet.
- [x] **whitney-att Datadog split** (done 2026-06-26): the attendee cluster reports to its own org
      (`ai-eng-wf-062626-01-002`) via the `whitney-attendee` branch ESO -> `watch-it-burn/datadog-admin-attendee`;
      r2/r3 stay on the instructor org (`...-01-001`). Verified live (attendee secret api-key tail `79de0a`).
      The 250-attendee fleet's per-attendee split is `distribute_datadog_keys.py`, still pending the AWS keys.
- [ ] **The 9 instructor clusters** for live delivery: provision + bootstrap per round
      (`fleet.sh instructors up`, now auto-bootstrapping), once the accounts are ready.

---

## P2 — observability polish (ROADMAP)

- [ ] #27 UST / Service Map / log-trace correlation: live acceptance on a real cluster.
- [ ] #28 platform-component UST: `tags.datadoghq.com/*` pod annotations on ArgoCD, Kyverno, Falco,
      cert-manager, Istio ambient (completes the Service Map). Gated on #27.
- [ ] #33 dashboards: verify the OOTB integration dashboards import, scaffold `infra/terraform/dashboards/`,
      and build the 4 custom story dashboards (cost, model-tier race, tool-call heatmap, guardrail timeline).
- [ ] gen_ai semconv final verify: confirm the live ADK spans carry `gen_ai.provider.name` (vs `gen_ai.system`)
      and the dashboard query matches.

---

## Deferred (explicitly, unless time allows)

- Pre-recorded asciinema fallback segments (Michael deferred).
- Kyverno `validationFailureAction` -> rule-level `failureAction` migration (deprecated but works on 1.18.1).
- Istio ambient waypoint for L7 mTLS in the exfil challenge (#25).
- AWS Load Balancer Controller -> ip-target NLB + activating the party-app ALB Ingresses (console NLB is
  fine via the in-tree annotation; the controller install is in deploy-full-idp.sh).

---

## The critical path

P0 is the gate. The two genuinely large remaining pieces are the **5-account 250-cluster fleet** and the
**real attendee pool** (per-attendee AWS + the Datadog merge + per-cluster wiring). Everything in P1 is
smaller and parallelizable. Start the 4 accounts' quota requests today; they have lead time the rest
does not.
