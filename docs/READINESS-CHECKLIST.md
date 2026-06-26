# Watch It Burn — Readiness Checklist

Are we ready to run the workshop? Status per item, grounded in the actual repo + live cluster state
(`watch-it-burn-attendee-1002`) as of 2026-06-26. Legend: ✅ done · 🔄 in progress / pending external ·
⬜ gap (not built).

The headline gaps are at the bottom under **"Must fix before ready."**

---

## 1. Workshop logistics
- 🔄 Slot cut to **60 minutes** (was 120). Walkthrough deck recut; run-of-show fits 60 min.
- 🔄 **250 attendees** (was 50), planned as **5 AWS accounts × ~50 clusters**. Pending: Michael acquiring the 4 extra accounts.
- ✅ Default model **Sonnet 4.6** (`bedrock-sonnet`), verified live; Haiku/Opus defined for the optional tier demo.

## 2. Provisioning & fleet
- ✅ Cluster provisioning is Terraform (`infra/terraform/cluster`), driven by `fleet.sh` (per-cluster state, parallel).
- ✅ `fleet.sh instructors up|down [round]` encodes the 9 instructor clusters + round→account split.
- ✅ Bootstrap: `deploy-full-idp.sh full|burn` (ArgoCD app-of-apps; `full` and `burn` profiles both exist).
- ⬜ **Per-account `lab-vpc`** apply for the 5-account model (each account needs its own VPC; `fleet.sh` prints the apply line but it is not automated).
- ⬜ **Attendee fleet across 5 accounts** (the `up <count>` path is single-account today).
- ⬜ **`aws-pool.csv` emit** (provision → IAM user/keys → CSV → `merge_pool.py`). Not built.

## 3. Rounds (instructor clusters)
- ✅ R1 bootstrap profile `burn` (`app-of-apps-burn.yaml`, no guardrail stack).
- ✅ R2/R3 bootstrap profile `full`.
- ⬜ **Per-round instructor setup script** (one command: provision + bootstrap + set the round's toggle state). Today bootstrap and toggles are separate manual steps. This is the "easily set up for instructors" gap you flagged.
  - R1: full install via `burn` (guardrails off) — partially covered by `deploy-full-idp.sh burn`.
  - R2: `full` + enable infra toggles (Kyverno enforce, NetworkPolicy, Falco, PID) — no single script sets this state.
  - R3: `full` + AI guards off (attendee flips them) — no single script asserts this state.

## 4. Challenges (C1–C7) — attack / defense / fallback / packaged
| # | Challenge | Attack prompt | Defense + toggle | Fallback | Packaged? |
|---|---|---|---|---|---|
| C1 | Exfil to S3 | ⬜ | substrate built (egress, customer-stream, Istio); ⬜ NetworkPolicy enable toggle | ⬜ | ⬜ **not packaged** |
| C2 | Malicious deploy | ✅ `challenges/01-cncf-wall/agent-prompt.txt` | ✅ `toggle-kyverno-enforce.sh` | ✅ `fallback.kubectl.sh` | ✅ |
| C3 | Planted-secret grep | ⬜ (breadcrumb files exist) | planted-file exists; ⬜ Falco filesystem-snoop rule + enable toggle | ⬜ | ⬜ **not packaged** |
| C4 | Fork bomb | ⬜ | PID-limit defense built/validated; ⬜ packaged attack + Round-1 placement | ⬜ | ⬜ **not packaged** |
| C5 | Output guard | ✅ `challenges/02-sanitization/agent-prompt-exfil.txt` | ✅ `toggle-output-guard-on.sh` | ✅ `fallback.curl.sh` | ✅ |
| C6 | Input guard | ✅ `agent-prompt-injection.txt` | ✅ `toggle-input-guard-on.sh` + `toggle-input-classifier-on.sh` | ✅ | ✅ |
| C7 | Rogue MCP | ✅ `challenges/03-bad-mcp-excessive-agency/agent-prompt.txt` | ✅ `toggle-mcp-authz-on.sh` (agentgateway) + `evil-mcp-shim/` | ✅ `fallback.curl.sh` | ✅ ([SPIKE] enforcement on OSS v1.3.0) |

## 5. AI layer
- ✅ kagent (ADK) agent on Bedrock Sonnet 4.6; live-verified end to end.
- ✅ **agentgateway** deployed and in the live path (guard-proxy → agentgateway → workshop-agent); tracing fixed (`config.tracing`, schema-correct, in the manifest).
- ✅ guard-proxy + LLM Guard (input/output); CLIENT span + JSON logging (PRD #27 M2).
- ✅ workshop-mcp + evil-mcp-shim.
- 🔄 agentgateway `mcpAuthorization` enforcement on OSS v1.3.0 is the beat-3 spike (kagent `toolNames` allowlist is the recorded fallback).

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
1. ✅ **C1, C3, C4 packaged as challenges** — `challenges/c1-exfil-s3/`, `challenges/c3-secret-grep/`, `challenges/c4-fork-bomb/` (attack prompt + README + fallback against the existing defenses).
2. ✅ **Per-round instructor setup script** — `infra/setup-instructor-cluster.sh <name> <round>`: bootstrap (`burn`/`full`) + set the round toggle state (R1 none, R2 Kyverno Enforce, R3 infra-on + AI-off with the flip commands printed).
3. ✅ **Per-round toggles**: the only runtime toggle is Kyverno Audit→Enforce; C1 egress / C3 Falco / C4 PID are profile-based (on in `full`, absent in `burn`), documented in each challenge README. Not a gap.
4. 🔄 **Multi-account fleet** (skipped by request): per-account VPC, attendee account targeting, `aws-pool.csv` emit, per-cluster Datadog secret naming, `routes.map` auto-population. Pending the 4 accounts.
5. 🔄 **Observability finish** (skipped by request): Service Map edge confirmation, log/trace pivot, LLM Observability (#20 M7), weaver live-check. (`witb_cost_usd` retired; cost is now the standard `gen_ai.client.cost`.)
