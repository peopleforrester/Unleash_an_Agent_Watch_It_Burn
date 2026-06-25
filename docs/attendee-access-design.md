<!-- ABOUTME: Design spec for attendee access + credential distribution — how every attendee reaches a -->
<!-- ABOUTME: web/chat interface for Clusters 1/2/3 and gets AWS + Datadog credentials keyed off email. -->

# Design Spec — Attendee Access & Credential Distribution

**Status:** Draft for review (Michael + Whitney)
**Priority:** High — gates the live workshop; the access path is the largest remaining delivery gap.
**Last updated:** 2026-06-23

This is a design spec, not a PRD. PRDs are Whitney's; where this touches the observability work it
**coordinates with and consumes** [Issue #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)
(the observability meta-PRD) but does not modify it.

---

## Scope

How a person in the room reaches a working web/chat interface for Clusters 1, 2, and 3, and how they
receive the credentials they need (AWS for `kubectl`, Datadog for their observability view), keyed off
their **email**.

**Out of scope — owned elsewhere:**

- **Per-attendee Datadog trial-org provisioning** — owned by the observability meta-PRD's Milestone 8
  ("Attendee accounts & credentials … per-attendee org provisioning"; per-attendee trial orgs confirmed
  2026-06-22). This spec **consumes** the Datadog keys that work produces and distributes them; it does
  not mint them.
- **Cluster provisioning / the fleet** — `infra/terraform/` + `fleet.sh`. This spec assumes a cluster
  exists and reads its LoadBalancer hostname.
- **The beats / agent logic** — unchanged; this spec only makes the existing `chat-ui` (and an optional
  terminal) reachable.

---

## Problem

The platform and the beats are built and live-validated, but **no attendee can reach any of it through a
browser today.** From the manifests:

1. **The chat UI exists but is not exposed.** `gitops/ai-layer/web/` + the `chat-ui` Deployment/Service
   are real (A2A to the guard-proxy, live cost counter), but the Service is **ClusterIP with no Ingress
   or LoadBalancer** — there is no URL to open.
2. **The web terminal does not exist.** `access/quickstart.md` promises "a web terminal loads in your
   browser, already connected to your cluster" as the *main* path. There is **no ttyd/wetty/gotty
   manifest** anywhere. The promise is unmet.
3. **There is no per-attendee URL scheme.** `infra/dns/` defines only ~5 *facilitator* URLs
   (`burn`, `wall`, `haiku`, `sonnet`, `opus`.agenticburn.com), written post-provision; student
   self-provisioning DNS is explicitly deferred. N attendee Cluster-3s have nowhere to resolve to.
4. **The distributor hands out only AWS keys, and its copy is stale.** `lab-distribution/` claims a
   cluster by email and shows AWS access/secret keys — but it still carries KCD-Texas content (clones
   `KCD_Texas_2026_Workshop`, links the KodeKloud course, references `spec/BUILD-SPEC.md`, keeps a
   `/browser` path). It distributes **no Datadog keys and no cluster URL.**
5. **No TLS story.** `infra/dns/README.md`: "TLS … Not wired yet." Conference WiFi + browsers make
   HTTPS effectively mandatory.

Net: Clusters 1, 2, and 3 are not yet intuitively reachable, and the web/chat interface is not wired up
for **any** cluster, let alone each.

---

## Goals

- **Every cluster the attendee touches has a reachable, HTTPS web/chat interface**: Cluster 1, Cluster 2,
  each attendee's own Cluster 3, and the instructor tier clusters.
- **One intuitive front door per person.** Enter email once → land on a single page with: cluster URL(s),
  AWS keys + the two setup commands, and Datadog dashboard link + keys. Re-entering the same email is
  idempotent.
- **The three-cluster journey is obvious.** Clusters 1 and 2 are *shared facilitator URLs the room
  watches/drives*; Cluster 3 is *your own link that does everything in-browser*. The attendee never has
  to reason about which is which.
- **Distribution keys off email** (already the model) and hands out AWS + Datadog credentials together.
- **Scales to N** (working N = 60) without per-cluster TLS/DNS toil or Let's Encrypt rate-limit breakage.
- **Teardown-clean and public-safe**: no real key in git, prefix-scoped, removable to $0 after the event.

---

## The attendee experience (the intuitiveness requirement)

The journey is three reach-points, each a single click:

| Cluster | Who drives it | How the attendee reaches it | Setup required of them |
|---|---|---|---|
| **Cluster 1** (no guardrails) | Facilitator; room attacks via chat | Open the shared **`burn.agenticburn.com`** (chat UI only, no kubectl) | None — just open the link on screen |
| **Cluster 2** (CNCF controls) | Facilitator narrates | Open the shared **`wall.agenticburn.com`** | None |
| **Cluster 3** (their own) | The attendee | Open **their own** `a-<id>.agenticburn.com` from the success page | None in-browser; AWS/Datadog keys only for the optional terminal/`kubectl` path |
| Instructor C3 tiers | Facilitators (closing demo) | `haiku` / `sonnet` / `opus`.agenticburn.com | None |

Single front door: scan the door QR → enter email → **success page** shows, in order:

1. **Your cluster** — a big button *Open your workshop console* → `https://a-<id>.agenticburn.com`
   (chat on one side, web terminal on the other, live cost counter on top).
2. **Your observability** — *Open your Datadog dashboard* (the per-attendee trial org, pre-filtered to
   their cluster) + their Datadog API/app keys in copy-friendly blocks.
3. **For the terminal / `kubectl` path** — AWS access key + secret key, and the two commands
   (`aws configure`; `aws eks update-kubeconfig --name <cluster> --region us-west-2`).

The same content is emailed (idempotent re-send) so a lost tab is recoverable. **Clusters 1 and 2 are
not personal** — the attendee just looks where the facilitator points; no per-person link for those.

---

## Architecture

### Exposure model (the core decision) — RECOMMENDED: one central TLS-terminating router

The hard part is N independent clusters, each with its own EKS LoadBalancer, all needing HTTPS on
`*.agenticburn.com`. Two shapes:

- **Option A — per-cluster Ingress + per-host cert.** Each cluster runs an Ingress (AWS LB Controller →
  ALB) for `chat-ui`, a DNS record `a-<id>.agenticburn.com → that ALB`, and a cert-manager HTTP-01 cert
  per host. **Rejected as the default:** ~60 ALBs (cost), 60 DNS records, and 60 certs **exceeds Let's
  Encrypt's ~50 certs/registered-domain/week limit** — it will rate-limit mid-setup.

- **Option B — central reverse-proxy/router with ONE wildcard cert (RECOMMENDED).** A single small
  always-on router (Caddy or nginx) holds one **wildcard cert `*.agenticburn.com`** (DNS-01 via the
  Namecheap API, which we already use). DNS is **one wildcard record** `*.agenticburn.com → the router`.
  The router maps `a-<id>.agenticburn.com → that attendee's cluster LoadBalancer hostname` from a table
  the provisioner emits. Each cluster exposes `chat-ui` (and the terminal) via a plain HTTP
  LoadBalancer/NodePort — **no per-cluster cert, no per-cluster DNS.** One cert, one DNS record, TLS
  centralized. `burn`/`wall`/tier hosts route the same way.

  - **Host: Railway** (decision 4). Railway terminates the wildcard TLS at its edge (Railway-managed
    cert via `_acme-challenge` CNAME delegation — no DNS-01 work for us, no whitelisted IP, netcup out
    of the path). The router is a small app (Node/Go reverse proxy, or Caddy with a static map) that
    reads the `Host` header and proxies `a-<id>` → that attendee's cluster LB, `burn`/`wall`/tiers →
    the facilitator cluster LBs, from a generated `routes.json` the provisioner emits. It also serves a
    landing page at the apex (`agenticburn.com`). Reloading the map (spare rotation, new clusters) is a
    redeploy or a hot-reload, no DNS change.

### Repository structure for Railway apps

All Railway services live under a top-level **`railway/`** parent, one subfolder per service (matching
the railway-cli "one linked directory per service" rule). Proposed:

```
railway/
  walkthrough/   # the deck (moved from tech-walkthrough/) — service watch-it-burn-walkthrough,
                 #   domain walkthrough.agenticburn.com
  apex/          # the apex landing page + the wildcard router — service watch-it-burn-apex,
                 #   domains agenticburn.com + *.agenticburn.com
```

Each subfolder is self-contained (Dockerfile + `railway.json` + README) and linked to its own Railway
service from its own directory. `tech-walkthrough/` has been moved to `railway/walkthrough/` and
re-linked (the deployed service was unaffected; still serving). `railway/apex/` is the new service.
`walkthrough.agenticburn.com` is a specific record and keeps winning over the new wildcard, so the two
coexist.

### Per-cluster web/chat wiring (this is "wired up for EACH cluster")

Add to the deployable set so every cluster that needs a face has one:

- **`chat-ui` exposure**: add a `Service type: LoadBalancer` (or NodePort behind the router) for
  `chat-ui`, tagged `aws-load-balancer-additional-resource-tags: project=watch-it-burn,…` (per
  `infra/TAGGING.md`). Applies to C1, C2, every C3, and the instructor tiers.
- **Web terminal** (decision below): if kept, a `ttyd` (or `wetty`) Deployment/Service per cluster,
  pre-authenticated to that cluster's API via an in-cluster ServiceAccount, exposed alongside `chat-ui`
  on the same host under `/terminal`. Single host per attendee, path-routed: `/` = chat, `/terminal` =
  shell. This is what makes `access/quickstart.md`'s promise true.
- **Cluster 1 specifics**: chat UI only, **no terminal** (the point is one-shot death via chat); the
  router points `burn` at the active spare and is repointed as spares rotate (one map edit, no DNS churn).

### DNS / TLS

- **DNS:** one wildcard `*.agenticburn.com → router` (keep the apex/parking records via the existing
  read-then-merge `set-demo-dns.py`). Per-attendee hostnames need **no** individual DNS record.
- **TLS:** one wildcard cert on the router via **DNS-01** (Namecheap), renewed centrally. No HTTP-01,
  no rate-limit exposure.

---

## Credential distribution (keyed off email)

Extend the existing `lab-distribution/` Flask app (already idempotent-by-email, atomic claim from a
pool). Changes:

### Pool schema (`pool.csv`) — extend from `name,access_key,secret_key,region`

```
name,region,access_key,secret_key,console_url,
datadog_org,datadog_email,datadog_password,datadog_api_key,datadog_app_key,datadog_site,datadog_dashboard_url
```

- `console_url` = `https://a-<id>.agenticburn.com` (the attendee's chat+terminal front door).
- **Two distinct Datadog credential needs** (don't conflate them):
  - `datadog_email` + `datadog_password` — let the **attendee log into the Datadog UI** to see their org's dashboard/traces.
  - `datadog_api_key` + `datadog_app_key` (+ `datadog_site`) — go into **their cluster's** Datadog Agent / OTel exporter config so telemetry ships to *their* org.
  - `datadog_dashboard_url` — the per-org view, pre-filtered to their cluster.
- The real pool is generated by the provisioning step and dropped in at deploy (still gitignored; only
  the `AKIAEXAMPLE` placeholder ships).

### Datadog trial-org provisioning (the concrete tool, from Tara)

The per-attendee Datadog trial orgs are minted with Datadog's own learning-center tooling, NOT hand-created:

- Clone `github.com/DataDog/learning-center-lambdas`; requires the **1Password CLI** (`OP_ACCOUNT=datadog.1password.com`).
- `scripts/generate_accounts_csv.sh <pool-name> <count> --stage prod` wraps `provision_org_pool.sh` and
  writes `<pool-name>-accounts.csv` with: `orgName, orgId, datadogEmail, password, apiKey, appKey,
  datadogUserId, expirationDate, poolName, parentOrg`. (`--stage prod` so org names aren't `dev`-suffixed.)
- **Column mapping → our `pool.csv`:** `orgName→datadog_org`, `datadogEmail→datadog_email`,
  `password→datadog_password`, `apiKey→datadog_api_key`, `appKey→datadog_app_key`; `datadog_site` =
  `datadoghq.com` (US1 — the `…@ddtraining.datadoghq.com` handles are US1); `datadog_dashboard_url`
  constructed per org. A small adapter joins this CSV to the AWS-cluster pool by row → the distributor `pool.csv`.
- **Expiry is the binding timing constraint:** trial orgs expire **~14 days** after creation (the sample
  `AWS-Hackathon-0226` pool's epochs were 2026-03-05 — already dead). **Provision the pool within ~10 days
  of the event**, not earlier, or accounts lapse mid-workshop.
- **Credential handling:** the generated CSV holds live secrets — it lives in the secrets vault
  (`~/secrets/`), gitignored, **never committed**. Only the schema + placeholder ship in-repo
  (see `~/.claude/rules/env-vault.md`).
- **Ownership seam:** Whitney's observability Milestone 8 owns the *decision* to use per-attendee orgs;
  this is the *mechanism* + the handoff format the distributor consumes. Coordinate, don't duplicate.

### What the success page + email show (attendee-priority order)

1. **Open your workshop console** → `console_url` (primary; most attendees never need anything else).
2. **Open your Datadog dashboard** → `datadog_dashboard_url`, with the **login** (`datadog_email` /
   `datadog_password`) to view their org; plus `datadog_api_key` / `datadog_app_key` / `datadog_site`
   in triple-click-friendly blocks (for their cluster's Agent/exporter).
3. **Terminal / kubectl path** → AWS access + secret keys and the two commands
   (`aws configure`; `aws eks update-kubeconfig --name <name> --region <region>`; then `kubectl get nodes`).

### Distributor fixes (stale KCD-Texas content — correctness bugs)

- Email/commands clone **`KCD_Texas_2026_Workshop`** and reference **`spec/BUILD-SPEC.md`** and the
  **KodeKloud course** — all wrong for this workshop. Replace with the Watch It Burn flow: the attendee
  uses the **chat UI** to drive the kagent agent (not Claude Code locally); the repo path is
  `docs/BUILD-SPEC.md`. Remove the inherited **`/browser`** (KodeKloud) path — Watch It Burn is EKS-only.
- Keep `ADMIN_TOKEN` / `RESEND_API_KEY` env-only (no hardcoding); keep Resend optional.

---

## Decisions (RESOLVED 2026-06-23, Michael)

1. **Exposure model — Option B, central wildcard router.** ✅
2. **Web terminal — BUILD it, Cloud-Shell style** (KodeKloud/Katacoda feel): a split console, left pane
   = instructions, right pane = tabs {Terminal, Agent chat}, cost counter on top. The terminal is a
   `ttyd` pod auto-authenticated to the attendee's own cluster (scoped in-cluster ServiceAccount; shell
   opens with `kubectl` already working, no login). `access/quickstart.md` stays true. C1/C2 stay
   chat-only.
3. **Datadog — pre-provisioned per-attendee trial orgs**; login (email+password), api/app keys, and
   dashboard URL land in the pool. **Mechanism (from Tara):** Datadog's learning-center tooling —
   `generate_accounts_csv.sh` from `DataDog/learning-center-lambdas` (needs the 1Password CLI). Orgs
   expire ~14 days → mint near the event. See "Datadog trial-org provisioning" above. M8 owns the
   decision; this consumes the output.
4. **Router host — Railway** (NOT netcup; netcup is Michael's private box and stays out of the path
   entirely). Railway **supports wildcard custom domains** and issues the wildcard cert via an
   **`_acme-challenge` CNAME delegated to Railway's side** — so the Namecheap-IP-allowlist problem
   that motivated netcup **does not apply**: Railway handles DNS-01 itself, no whitelisted IP needed.
   Adding `*.agenticburn.com` to the router service yields two CNAMEs (wildcard + `_acme-challenge`) and
   one ownership TXT; we set those once at Namecheap (administrative, one-time, from laptop or netcup —
   **not** traffic). Railway is preferred for persistence; AWS would be torn down. Attendee traffic:
   browser → Railway edge (wildcard TLS) → router app → each cluster's public LB. **netcup carries
   nothing.** (Caveat: single-level wildcard only — `a-<id>`, `burn`, `wall`, tiers all fit.)
5. **AWS credentials — long-lived per-attendee IAM keys**, scoped to one cluster, deleted at teardown.

### Current DNS state (verified 2026-06-23)

- `agenticburn.com` (apex) and `www` → Namecheap **parking page** (unused; NOT the walkthrough).
- `walkthrough.agenticburn.com` → the Railway deck. **A specific record beats the wildcard**, so this
  keeps working untouched when the wildcard is added.
- `*.agenticburn.com` → **nothing yet** — adding the wildcard is a clean, single new record.
- The router owns the **wildcard** (`a-<id>`, `burn`, `wall`, tier hosts). We do **not** need to hand it
  "all of agenticburn.com": the apex can stay parked (or later redirect to the walkthrough) — the
  wildcard + the existing `walkthrough` record coexist with zero conflict.

### Attendee console layout (the Cloud-Shell experience)

```
┌─────────────────────────────────────────────────────────────┐
│  🔥 Watch It Burn — your cluster        cost: $0.0000  ▲      │
├──────────────────────────────┬──────────────────────────────┤
│  INSTRUCTIONS (current beat)  │  [ Terminal ] [ Agent chat ]  │
│  rendered beat.md             │  ttyd, auto-authed to YOUR    │
│  steps, what to try           │  cluster (kubectl just works) │
│                               │  / agent chat (A2A + cost)    │
└──────────────────────────────┴──────────────────────────────┘
```

- **Left:** the current beat's instructions (rendered `challenges/<n>/beat.md`).
- **Right, tabbed:** **Terminal** (`ttyd`, scoped SA, kubeconfig pre-set to the in-cluster context) and
  **Agent chat** (the existing `chat-ui`, A2A to the guard-proxy). Cost counter pinned on top.
- **Build difficulty: medium, no unknowns.** `ttyd` is the standard tool for exactly this; the split
  console is a small static frontend; the auto-auth is a ServiceAccount token + in-cluster KUBECONFIG.
  Work = console UI + `ttyd` Deployment/SA/RBAC per cluster + router wiring.

---

## Build phases (MVP-first; each verifiable on its own)

- **Phase 1 — One cluster reachable over HTTPS.** Stand up the central router with the wildcard DNS-01
  cert; expose `chat-ui` on one real cluster; prove `https://a-001.agenticburn.com` opens the chat UI
  with the live cost counter. *Verify:* a browser on conference-like WiFi loads it over HTTPS and gets an
  agent reply.
- **Phase 2 — Facilitator URLs through the router.** Route `burn` / `wall` (and tier hosts) through the
  same router to the facilitator cluster LBs; prove repointing a spare is a one-line map reload.
  *Verify:* `burn` opens C1's chat UI; repoint to a second spare with no DNS change.
- **Phase 3 — Web terminal (if decision 2 = build).** Add `ttyd` per cluster under `/terminal`, scoped
  SA. *Verify:* `a-001.agenticburn.com/terminal` gives a shell that runs `kubectl get nodes` on that
  cluster.
- **Phase 4 — Distributor v2.** Extend `pool.csv` + success page + email to emit `console_url` + Datadog
  keys + dashboard; fix the stale KCD content; idempotent-by-email end-to-end. *Verify:* enter an email →
  success page shows console link, Datadog link/keys, AWS keys; re-enter → identical assignment.
- **Phase 5 — Fleet-scale routing.** The provisioner emits `routes.json` + the pool for N clusters;
  router loads N routes; spot-check a sample of `a-<id>` hosts. *Verify:* 10 sampled attendee URLs each
  open their own cluster's chat UI. (Couples to the deferred fleet/quota work.)

Phases 1–4 are buildable on a single cluster now; only Phase 5 needs the full fleet, so this work does
not block on the EC2 vCPU quota.

---

## Acceptance criteria

- [ ] An attendee enters their email once and reaches a working, **HTTPS** chat UI for **their own
      Cluster 3** with no manual setup.
- [ ] **Clusters 1 and 2** are reachable as shared facilitator URLs (`burn` / `wall`) over HTTPS through
      the same router; repointing a Cluster-1 spare needs no DNS change.
- [ ] The success page + email deliver **AWS** keys (+ the two `kubectl` setup commands) **and** Datadog
      keys + dashboard URL, all triple-click-selectable, idempotent by email.
- [ ] TLS is one wildcard cert (DNS-01); **no per-cluster cert**, no Let's Encrypt rate-limit risk at N.
- [ ] `access/quickstart.md` matches reality (terminal exists if promised; otherwise the promise is
      removed).
- [ ] No real credential in git; LBs/keys tagged `project=watch-it-burn`; everything removable to $0.

---

## Risks & mitigations

- **Conference WiFi can't carry N browser sessions** → the runbook's "single facilitator path, room
  watches" contingency already exists; the router + shared `burn`/`wall` URLs make the watch-only path
  first-class.
- **Let's Encrypt rate limits** → avoided entirely by the single wildcard cert (decision 1 = B).
- **Router is a single point of failure** → it only fronts a disposable 2-hour lab; keep a warm spare
  config and the raw `*.elb…` hostnames as a documented fallback.
- **Key leakage** → per-attendee keys scoped to one cluster, long-lived only for the session, deleted at
  teardown; pool gitignored; success page served over HTTPS only.
- **Coupling to deferred fleet/quota** → Phases 1–4 are buildable on a single cluster now; only Phase 5
  needs the full fleet.
