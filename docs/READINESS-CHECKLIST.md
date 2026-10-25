# Watch It Burn — Readiness Checklist

Are we ready to run the workshop? Status per item, grounded in the actual repo + live cluster state
(`watch-it-burn-attendee-1002`) as of 2026-06-26. Legend: ✅ done · 🔄 in progress / pending external ·
⬜ gap (not built).

The headline gaps are at the bottom under **"Must fix before ready."**

---

## 1. Workshop logistics
- ✅ Slot is **120 minutes** (DevOpsDays Portland, verified against pretalx 2026-08-23). The August
  run-of-show (`docs/RUN-OF-SHOW-2026-08.md`, now retired) was rebuilt around it (#123). The live run of
  show is `/brief`: Phase 1 the whole room attacks the Community cluster, Phase 2 everyone claims a
  cluster, Phase 3 the tour and the eight challenges on their own cluster.
- 🔄 **250 attendees** (was 50), planned as **5 AWS accounts × ~50 clusters**. Pending: Michael acquiring the 4 extra accounts.
- ✅ Default model **Amazon Nova Pro** (`bedrock-nova`, `us.amazon.nova-pro-v1:0`): the model that complies
  AND executes the attack beats. Haiku/Sonnet/Opus remain defined for the optional cost-race tier demo.
  The guard-proxy's `MODEL_TIER` must match the bound ModelConfig or the cost counter prices the wrong
  model (caught live 2026-08-30, ~4x over); `verify/test_cost_tier_matches_model.py` now fails the build
  on a mismatch.

## 2. Provisioning & fleet
- ✅ Cluster provisioning is Terraform (`infra/terraform/aws/cluster`), driven by `fleet.sh` (per-cluster state, parallel).
- ✅ `fleet.sh instructors up|down [role|owner]` builds the roster in `infra/terraform/fleet/roster.tsv`:
  the Community cluster and one admin cluster per presenter, all in `WIB_DEFAULT_ACCOUNT`.
- ✅ Bootstrap: `deploy-full-idp.sh burn|attendee|admin|full` (ArgoCD app-of-apps, one root per profile).
- ⬜ **Per-account `lab-vpc`** apply for the 5-account model (each account needs its own VPC; `fleet.sh` prints the apply line but it is not automated).
- ⬜ **Attendee fleet across 5 accounts** (the `up <count>` path is single-account today).
- ⬜ **`aws-pool.csv` emit** (provision → IAM user/keys → CSV → `merge_pool.py`). Not built.

## 3. Cluster roles (Community, admin, attendee)
- ✅ Community bootstrap profile `burn` (`app-of-apps-burn.yaml`, no guardrail stack; the roster gives it `pod_pids_limit=-1`).
- ✅ Admin bootstrap profile `admin` (`app-of-apps-admin.yaml`, every challenge control armed).
- ✅ Attendee bootstrap profile `attendee` (`app-of-apps-attendee.yaml`: the C1 and C3 controls omitted,
  Kyverno in Audit, so the student installs each control).
- ✅ **One-command roster setup**: `fleet.sh instructors up [role|owner]` provisions, bootstraps the profile
  the roster names, and flips Kyverno to Deny on `admin` (`arm_infra_guardrails`). The guard-proxy guards
  start off on every profile. `infra/setup-instructor-cluster.sh <roster-cluster-name>` bootstraps and arms
  one roster cluster that was provisioned bare, asking `fleet.sh` for its role and profile (#560).

## 4. Challenges (C1–C7) — attack / defense / fallback / packaged
| # | Challenge | Attack prompt | Defense + toggle | Fallback | Packaged? |
|---|---|---|---|---|---|
| C1 | Exfil to S3 | ⬜ | substrate built (egress, customer-stream, Istio); ⬜ NetworkPolicy enable toggle | ⬜ | ⬜ **not packaged** |
| C2 | Malicious deploy | ✅ `challenges/01-cncf-wall/agent-prompt.txt` | ✅ `toggle-kyverno-enforce.sh` | ✅ `challenges/c2-villain-image/fallback.kubectl.sh` | ✅ |
| C3 | Planted-secret grep | ⬜ (breadcrumb files exist) | planted-file exists; ⬜ Falco filesystem-snoop rule + enable toggle | ⬜ | ⬜ **not packaged** |
| C4 | Denial-of-wallet | ✅ `challenges/c4-denial-of-wallet/agent-prompt.txt` | ✅ gateway budget cap, runtime `guard-budget-on` toggle | ✅ verified live 2026-08-29 (froze at the cap, zero-cost block) | ✅ |
| ~~C4 old~~ | ~~Fork bomb~~ | retired as a beat (#114): Nova refuses it in chat. PID-cap defence still deployed, terminal-only | | | n/a |
| C5 | Output guard | ✅ `challenges/02-sanitization/agent-prompt-exfil.txt` | ✅ `toggle-output-guard-on.sh` | ✅ `fallback.curl.sh output` | ✅ |
| C6 | Input guard | ✅ `agent-prompt-injection.txt` | ✅ `toggle-input-guard-on.sh` + `toggle-input-classifier-on.sh` | ✅ `fallback.curl.sh input` | ✅ |
| C7 | Rogue MCP | ✅ `challenges/03-bad-mcp-excessive-agency/agent-prompt.txt` | ✅ `toggle-mcp-authz-on.sh` (kagent `toolNames` on the `evil-mcp` entry: ON = `[get_weather]`) + `evil-mcp-shim/` | ✅ `fallback.curl.sh` | ✅ (toggle verified live 2026-06-26, `FACILITATOR.md`) |

## 5. AI layer
- ✅ kagent (ADK) agent on Bedrock Sonnet 4.6; live-verified end to end.
- ✅ **agentgateway** deployed and in the live path (guard-proxy → agentgateway → workshop-agent); tracing fixed (`config.tracing`, schema-correct, in the manifest).
- ✅ guard-proxy + LLM Guard (input/output); CLIENT span + JSON logging (PRD #27 M2).
- ✅ workshop-mcp + evil-mcp-shim.
- ✅ On a workshop cluster C7's control is the kagent `toolNames` allowlist (`toggle-mcp-authz-on.sh`). `evil-mcp` goes through agentgateway on its own bind, :3003 (#514), whose `mcpAuthorization` rule stays `'true'` there; on an admin cluster `guard-mcp-on` narrows that rule instead and it is the control (#496, #516). The design is weighed in `docs/research/2026-10-24-agentgateway-evaluation.md`.

## 6. Observability
- ✅ OTel Collector → Datadog; guard-proxy, agentgateway, kagent spans all in Datadog (verified, queries cited in `DECISION-LOG.md`).
- ✅ Full chain connected in one trace (guard-proxy → agentgateway → kagent → workshop-mcp).
- 🔄 **Service Map edge** in `service_dependencies` API: data is present; the dependency graph is propagating (10–30 min lag). Re-confirm.
- 🔄 **Log/trace pivot** (#27): needs a guard-decision event to produce a correlated log (guard-proxy only logs on guard events). Untested.
- 🔄 **LLM Observability** (#20 M7): gen_ai waterfall / `gen_ai.request.model` / content capture not yet confirmed in the LLM Obs product view.
- ✅ Datadog per-cluster distribution: ESO fan-out to datadog/monitoring/security; `distribute_datadog_keys.py` loader.
- ✅ Weaver `registry check` in CI; ⬜ `live-check` terminal acceptance.
- ✅ Live cost meter `witb_cost_usd` at guard-proxy; ⬜ scraped into Datadog as one number (known scrape gap).

## 7. Distribution & access
- ✅ `lab-distribution` Railway app (attendee assignment from the pool).
- ✅ Apex router (`agenticburn.com` wildcard) + `rounds`/`walkthrough`/`provisioning`/`start` routes.
- ✅ `start.agenticburn.com` instructor index (URL inventory + live cost/prompt view).
- ⬜ **`routes.map` auto-population** (cluster LB hostname → host) at provision time. Manual today.
- 🔄 Per-cluster Datadog secret naming for the 5-account model (single `watch-it-burn/datadog` collides when 50 clusters share an account).

## 8. Decks & instructor materials
- ✅ Rounds & Challenges deck (`rounds.agenticburn.com`) — current.
- ✅ Walkthrough run-of-show (`walkthrough.agenticburn.com`) — recut for 60 min + Sonnet + full stack.
- ✅ `facilitation/runbook.md`, governance map, self-assessment (in repo).

---

## Must fix before ready (the gaps)
1. ✅ **C1, C3, C4 packaged as challenges** — `challenges/c1-exfil-s3/`, `challenges/c3-secret-grep/`, `challenges/c4-denial-of-wallet/` (attack prompt + README + fallback against the existing defenses).
2. ✅ **One-command roster setup**: `fleet.sh instructors up [role|owner]` (section 3).
3. ✅ **Challenge controls by cluster**: `admin` arms the C1 NetworkPolicy, the C3 KubeArmor policy and
   Kyverno Deny from the start; `attendee` starts without them and the student applies each one (and flips
   `restrict-image-registries` to Deny for C2); `burn` has none, and no Kyverno to flip. Documented in each
   challenge README and in `challenges/LAB-TEXT.md`. Not a gap.
4. 🔄 **Multi-account fleet** (skipped by request): per-account VPC, attendee account targeting, `aws-pool.csv` emit, per-cluster Datadog secret naming, `routes.map` auto-population. Pending the 4 accounts.
5. 🔄 **Observability finish** (skipped by request): Service Map edge confirmation, log/trace pivot, LLM Observability (#20 M7), weaver live-check. (`witb_cost_usd` retired; cost is now the standard `gen_ai.client.cost`.)
