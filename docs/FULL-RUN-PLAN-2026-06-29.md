<!-- ABOUTME: Go-live provisioning runbook for the full workshop run: 250 student + 9 instructor + 2 -->
<!-- ABOUTME: personal (Michael/Whitney) clusters, with the exact command sequence, capacity, and timing. -->

# Full Run Plan: 2026-06-29 Workshop

The complete provisioning runbook to stand the whole fleet up for the live workshop and tear it down after. Workshop slot: Day 1, 2:20 to 4:20pm, Track 5.

## 1. Cluster inventory (261 total)

| Group | Count | Names | Account(s) | Profile | Datadog org |
|---|---|---|---|---|---|
| Students (attendees) | 250 | `watch-it-burn-attendee-001..250` (50/account, disjoint ranges) | all 5 (50 each) | full | own pool org |
| Instructors R1 (burn) | 3 | `watch-it-burn-burn-1/2/3` | `WIB_ACCOUNT_R1` | burn (pid cap off, fork-bombable) | n/a (R1 has no Datadog) |
| Instructors R2 (wall) | 3 | `watch-it-burn-wall-1/2/3` | `WIB_ACCOUNT_R2` | full | instructor org |
| Instructors R3 (tiers) | 3 | `watch-it-burn-haiku/sonnet/opus` | `WIB_ACCOUNT_R3` | full | instructor org |
| Personal (Michael) | 1 | `watch-it-burn-attendee-michael` | accen-dev | full | own org |
| Personal (Whitney) | 1 | `watch-it-burn-attendee-whitney` | accen-dev | full | own org |

up-fleet numbers the 250 globally by account range: accen-dev 001-050, student31 051-100, student32 101-150, student33 151-200, student34 201-250.

Michael and Whitney are also `ADMIN_EMAILS` in the provisioning app, so they additionally get instructor-cluster access (all 9 instructor clusters + both Datadog orgs) through `admin_access.html`. The two personal clusters above are their own R3 "your own cluster" to drive hands-on.

## 2. Per-account capacity (must stay under quota)

Quotas verified 2026-06-28: EKS clusters/Region 100, NLB/Region 100, vCPU 800 (=100 t3.2xlarge), EKS TGs 3000, gp3 50 TiB (bump to 100 pending), all in every account.

Recommended placement (spread instructors off the central account for blast-radius isolation):

| Account | Students | Instructors | Personal | Total clusters | NLBs | vCPU | gp3 (est) |
|---|---|---|---|---|---|---|---|
| accen-dev | 50 | 0 | 2 | 52 | 52 | 416 | ~12 TiB |
| aws1-student31 | 50 | 3 (R1 burn) | 0 | 53 | 53 | 424 | ~12 TiB |
| aws1-student32 | 50 | 3 (R2 wall) | 0 | 53 | 53 | 424 | ~12 TiB |
| aws1-student33 | 50 | 3 (R3 tiers) | 0 | 53 | 53 | 424 | ~12 TiB |
| aws1-student34 | 50 | 0 | 0 | 50 | 50 | 400 | ~11 TiB |

Every column is comfortably under the per-account quota (worst case 53 of 100 clusters, 53 of 100 NLBs, 424 of 800 vCPU, ~12 of 50 TiB gp3). A single fresh run fits in the current 50 TiB gp3 without the pending bump; the bump is insurance against orphan accumulation across repeated provision/teardown cycles. Alternative placement: leave all 9 instructors in accen-dev (default `WIB_ACCOUNT_R*=accen-dev`), making accen-dev 61 clusters, still under 100. The spread above is preferred.

## 3. Pre-flight gates (all must be green before provisioning)

1. **Code on `staging`, clean.** Every cluster bootstraps from `staging`; all of the 2026-06-27 fixes are there (corrected block-argocd-drift, recipe-sentinel beat-2, argocd-managed-app, fleet.sh prof fix).
2. **Quotas at target.** ALB/NLB/vCPU confirmed 2026-06-28; gp3 bump filed (pending, not blocking).
3. **Datadog pool fresh.** ~300 trial orgs in Secrets Manager (`watch-it-burn/datadog-pool` + `-pool-2`). Trial orgs expire ~14 days after creation, so confirm they are still valid; if any lapsed, re-mint before the run.
4. **lab VPCs applied.** They were destroyed in the 2026-06-27 teardown, so they must be re-applied per account FIRST (step 4.1 below).
5. **P0 attendee-experience items** that gate the live run (these gate the demo, not provisioning): B1 BurritoBot frontend wired and served, B5 web terminal, B11 round-cluster setup, B2 BurritoBot system prompt. Decide which are must-have vs nice-to-have for this run.

## 4. Provisioning sequence

All commands run from the repo root with explicit `AWS_PROFILE`/`KUBECONFIG` per the kube-safety rule. fleet.sh handles isolation internally.

### 4.1 Re-apply the 5 lab VPCs (foundation; ~5 to 10 min)

```bash
terraform -chdir=infra/terraform/lab-vpc init
terraform -chdir=infra/terraform/lab-vpc apply -auto-approve -var profile=accen-dev -var region=us-west-2
for a in aws1-student31 aws1-student32 aws1-student33 aws1-student34; do
  terraform -chdir=infra/terraform/lab-vpc apply -auto-approve \
    -state=states/$a.tfstate -var profile=$a -var region=us-west-2
done
```

### 4.2 Provision the 250 students (longest pole; ~3 to 4 hr, all accounts concurrent)

```bash
infra/terraform/fleet/fleet.sh up-fleet 50      # 50 in each of the 5 accounts, auto-bootstraps full IDP
```

Run this in the background (it is hours long); watch the per-cluster logs under `infra/terraform/fleet/logs/`. MAX_PARALLEL=8 per account pool, 5 accounts concurrent.

### 4.3 Provision the 9 instructor clusters (~30 min)

```bash
WIB_ACCOUNT_R1=aws1-student31 WIB_ACCOUNT_R2=aws1-student32 WIB_ACCOUNT_R3=aws1-student33 \
  infra/terraform/fleet/fleet.sh instructors up
```

R1 auto-provisions with `pod_pids_limit=-1` (fork-bombable) + burn profile; R2/R3 full. The tier MODEL for haiku/sonnet/opus is set per cluster in the gitops kagent ModelConfig, not by fleet.sh.

### 4.4 Provision Michael + Whitney personal R3 clusters (~25 min, in accen-dev)

```bash
infra/terraform/fleet/fleet.sh up watch-it-burn-attendee-michael watch-it-burn-attendee-whitney
```

### 4.5 Converge + verify health

```bash
infra/terraform/fleet/fleet.sh health 50         # the 250 students: every ArgoCD app Synced+Healthy, no broken pods
# instructor + personal health: run the same per-cluster check against their names
```

If Datadog is empty on any cluster, run `infra/reinstrument-app-pods.sh` / `infra/reload-datadog-consumers.sh` (pod-delete, respects block-argocd-drift). ai-layer is already sync-wave 3, so this should be rare.

### 4.6 Credentials + access distribution

```bash
WIB_APPLY=1 WIB_ACCESS_ENTRIES=1 infra/terraform/fleet/fleet.sh aws-keys 50   # per-cluster scoped IAM user+key
infra/terraform/fleet/fleet.sh harvest 50 > /tmp/pool-aws.csv                  # console NLB / grafana / argocd per cluster
uv run --with boto3 python lab-distribution/scripts/merge_pool.py \
  --aws /tmp/pool-aws.csv --out lab-distribution/pool.csv                       # join with the Datadog pool
```

Then regenerate the apex `routes.map` from the harvest output (one `a-<id>.agenticburn.com  http://<cluster-LB>` per line, plus the facilitator hosts `burn`/`wall`/`haiku`/`sonnet`/`opus` to the instructor LBs), deploy the Railway distributor + apex router (Railpack), and confirm the wildcard cert is live (Railway-issued, no Route 53/ACM).

### 4.7 Final acceptance

- One sample student cluster: `verify/run-all.sh <ctx> agent` green (beat-01/02/cost; beat-03 on the fallback gate).
- The access path end to end on conference-like WiFi: `a-001.agenticburn.com` resolves, console opens, `kubectl get pods` works, BurritoBot responds, the Datadog dashboard loads.
- The facilitator URLs resolve to the right instructor clusters.

## 5. Timing recommendation

A full run from zero to converged is ~3 to 4 hours (the 250-student provision + bootstrap is the pole; instructors and personal clusters overlap). For a 2:20pm Jun 29 slot:

- **Preferred: provision the afternoon/evening of Jun 28, verify health, hold overnight, re-verify Jun 29 morning.** This buys a real fix window if provisioning hits issues. Overnight cost for ~261 clusters is roughly $2,000 (nodes + EKS control planes for ~18h); acceptable for a flagship event, and `fleet.sh reap` can trim unclaimed clusters once the room size is known.
- **Fallback: provision Jun 29 morning** (start by ~8am for the 2:20pm slot). Saves the overnight cost but compresses the fix window; only choose this if provisioning was already rehearsed clean.

Do a full dress-rehearsal run before the real one regardless, so the ~3 to 4 hour timing and the convergence rate are measured, not estimated.

## 6. Teardown after the workshop

`fleet.sh down-fleet 50` (students) + `instructors down` + `down watch-it-burn-attendee-michael watch-it-burn-attendee-whitney`, then the orphan sweep across all accounts (LBs/TGs/EBS/EIPs the in-cluster controllers leave), then `terraform destroy` the 5 lab VPCs (revoke + delete the orphaned EKS security groups first, they block the VPC delete). Target: every account at zero. See the 2026-06-27 teardown entry in `docs/DECISION-LOG.md`.

## 7. Decisions to lock before the run

1. **Instructor placement:** spread R1/R2/R3 to student31/32/33 (recommended, in this plan), or keep all 9 in accen-dev (simpler, 61 clusters in one account, still under quota).
2. **Michael/Whitney clusters:** confirm one personal R3 cluster each (this plan), names `watch-it-burn-attendee-michael` / `-whitney`, in accen-dev. Or a different placement/count.
3. **Timing:** provision Jun 28 evening + hold overnight (recommended), or Jun 29 morning.
4. **P0 must-haves:** which of B1/B5/B11/B2 must be done before the run vs deferred. These gate the attendee experience, not provisioning.
