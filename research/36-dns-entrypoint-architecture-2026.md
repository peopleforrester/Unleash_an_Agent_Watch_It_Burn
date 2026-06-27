<!-- ABOUTME: Research spike on the optimal DNS/URL entry-point architecture for the 250-attendee workshop fleet. -->
<!-- ABOUTME: Web-researched 2026-06-27 across four angles; synthesizes a recommended architecture vs our constraints. -->

# Research Spike 36: DNS / URL Entry-Point Architecture for the Workshop Fleet

- **created:** 2026-06-27
- **topic:** attendee-access / DNS / edge architecture
- **status:** fresh
- **builds on:** `docs/attendee-access-design.md`, `docs/MASTER-RECREATION-SPEC.md` Part X, the fleet-quota-wall finding
- **question:** revisit the optimal architecture for the various DNS/URL entry points for a ~250-attendee, per-attendee-EKS-cluster workshop. What is current (2026) best practice, and where does our deadline-driven design diverge from it?

All claims below were web-verified on 2026-06-27 against the primary sources cited inline in the four angle sections.

---

## TL;DR (the verdict up front)

1. **Keep the pattern. It is correct.** A single wildcard cert terminated at one central reverse proxy that host-routes `*.agenticburn.com` to ephemeral backends is the 2026 industry-standard hands-on-lab architecture. Instruqt and Play-with-Docker ship exactly this; the SaaS multi-tenant playbook recommends exactly this. Our Railway/Caddy + single-wildcard router is validation, not a redesign signal. Do NOT move to per-cluster certs or per-cluster public DNS.

2. **Change one thing: stop giving each cluster its own public LoadBalancer.** That single choice is the entire source of the ALB/NLB-per-Region=50 quota wall we were about to file increases against, plus the 250-LB cost and the 250-line `routes.map`. Every surveyed cloud lab (AWS, GCP, Microsoft, Killercoda, KodeKloud) exposes ZERO public endpoints per attendee and reaches the backend through a brokered terminal or a shared edge. Because all clusters in an account already share ONE lab VPC and each is a single node with VPC-routable pod IPs, one shared per-account edge can reach all 50 clusters without a per-cluster LB. This collapses ~250 LBs to ~5 and removes the quota wall (and the planned quota increases) entirely.

3. **Move DNS + cert to Route 53 + ACM if you want the bulletproof, zero-toil path.** One wildcard ACM cert is free on ALB/NLB/CloudFront, DNS-validated, auto-renewing, with NO Let's Encrypt rate limits and NO Namecheap IP-allowlist pain. Keep Namecheap as the registrar; delegate only the event subdomain's NS to Route 53. If you stay on Railway/LE, at minimum delegate `_acme-challenge` to Route 53. Either way, pre-issue the wildcard days ahead and bake it in.

4. **Keep cross-account reachability public.** A central proxy host-routing to 5 per-account public edges (not 250 backends) is the right tradeoff for a disposable, multi-account, high-churn lab. Skip PrivateLink / Transit Gateway / VPC peering; they add per-GB and per-hour cost plus CIDR coordination for isolation that synthetic-data demo clusters do not need.

5. **The in-browser terminal needs no per-cluster LB.** ttyd/wetty is HTTP + a WebSocket upgrade, which ALB, CloudFront, and Caddy all carry natively on the shared edge.

The single highest-value action: **collapse to one shared edge per account.** Everything else is keep-what-you-have or a low-cost DNS/cert cleanup.

---

## Where our current design stands vs best practice

| Dimension | What we do today | Best-practice verdict |
|---|---|---|
| Public entry point | One central Railway/Caddy wildcard router, single wildcard cert, host-routes to backends | CORRECT. The dominant 2026 lab pattern (Instruqt, PWD). Keep. |
| Per-cluster exposure | One public AWS LoadBalancer per cluster (the `console` Service) | CHANGE. This is the quota wall + cost + management driver. No surveyed lab does this. |
| TLS | One wildcard at the edge, HTTP to backends | CORRECT for synthetic-data disposable clusters. Keep edge-terminate. |
| Cert issuance | Let's Encrypt via the Railway edge; we hit the Namecheap IP-allowlist pain on DNS-01 | IMPROVE. Prefer ACM + Route 53 (free, auto-renew, no rate limit) or delegate `_acme-challenge` to Route 53. |
| DNS | One static Namecheap wildcard record | OK as-is; Route 53 unlocks cleaner ACM + external-dns automation if you want it. |
| Per-attendee naming | Host-based subdomains under the wildcard | CORRECT. Host-based beats path-based (no path-rewrite breakage in agent UIs). Keep. |
| Cross-account reach | Central proxy dials public per-cluster LB hostnames | KEEP PUBLIC, but dial 5 per-account edges, not 250 backends. Skip private networking. |

---

## The recommended optimal architecture

Three tiers, with the one substantive change in tier 2.

```
                          attendees on conference WiFi
                                     │  443, one stable hostname
                                     ▼
TIER 1  (global edge)   ONE central reverse proxy + ONE wildcard cert (*.agenticburn.com)
                        (today: Railway/Caddy. Optionally: one CloudFront distribution + ACM.)
                        host-routes a-<id>.<acct>.agenticburn.com  ->  the right per-account edge
                                     │
                  ┌──────────────┬───┴───────────┬──────────────┐
                  ▼              ▼                ▼              ▼  (5 accounts)
TIER 2  (per-account edge)  ONE shared edge per account  =  1 ALB (or NLB) + 1 router (Envoy/Caddy)
                        in the shared lab VPC. host-routes a-<id>.* to that cluster's services,
                        reached OVER THE SHARED VPC (NodePort on the node's VPC IP, or an in-VPC
                        endpoint). NO public LB per cluster. 50 clusters -> 1 LB.
                                     │  (all 50 clusters share this VPC; pods/nodes are VPC-routable)
                  ┌──────────────┬───┴───────────┬──────────────┐
                  ▼              ▼                ▼              ▼  (50 clusters/account)
TIER 3  (cluster)       each cluster exposes chat-ui / web-terminal / grafana / argocd
                        on a stable in-VPC address (NodePort or ClusterIP via a tiny ingress),
                        NOT a public LoadBalancer.
```

### Why this is the right shape

- **It kills the quota wall.** LB-per-Region (ALB L-53DA6B97 = 50, NLB L-69A177A2 = 50, both non-scaling past ~100 even when raised) is consumed by per-cluster LBs. One shared edge per account uses 1 LB, so the wall is gone and the planned ALB/NLB quota increases are unnecessary (Angle B and D).
- **It uses what we already have.** All clusters in an account already provision into ONE shared lab VPC (the cost-saving decision), and VPC-CNI gives pods and nodes real VPC IPs. So a single router in that VPC can reach any cluster's workload directly over the VPC. We do not need to add shared-VPC infrastructure; it exists.
- **It matches the cloud-lab broker model** (AWS/GCP/Microsoft expose nothing per attendee; Angle A) without a full broker rebuild: the per-account router is the broker.

### The independent-cluster nuance (important)

Angle D's clean answer for collapsing LBs is the AWS Load Balancer Controller `IngressGroup` (many Ingresses merged onto one ALB). That assumes ONE cluster with many namespaces, or one LB controller managing the ALB. Our model is 50 INDEPENDENT clusters per account, each with its own control plane and its own LB controller, so they cannot natively share one ALB via IngressGroup (each cluster's controller would fight over the same ALB).

The adaptation that fits our independent-cluster model: **one router per account, not one Ingress-group across clusters.** The per-account edge is a single ALB (or NLB) in front of a small Envoy/Caddy router (it can live in any one cluster in that account, or a tiny dedicated router cluster). That router holds the host table and forwards `a-<id>.*` to each cluster's service reached over the shared VPC. Reaching the per-cluster service options, cheapest first:

- **NodePort on the single node's VPC IP** (each cluster is one node): zero LB, the node IP is VPC-routable, the harvester already knows the node. The router targets `<node-VPC-IP>:<nodeport>`. Simplest and LB-free.
- **A per-cluster internal endpoint** the router resolves (pod IP via a known selector, or a headless Service the harvester reads). More moving parts than NodePort.
- **One internal NLB per cluster** reached privately: clean but reintroduces a per-cluster LB (still counts against the quota), so it defeats the purpose. Avoid.

NodePort-over-the-shared-VPC is the recommended tier-3 mechanism: it is the LB-free way to make every cluster reachable from the per-account router.

### Tier 1 options (the global edge)

Keep the current Railway/Caddy router, OR move it to one CloudFront distribution with a wildcard ACM cert in front of the 5 per-account ALBs. CloudFront adds managed TLS, WAF/DDoS, and WebSocket support and almost certainly lands in the always-free tier for a one-day, 250-seat event (Angle D). CloudFront does not by itself solve LB fan-out, so add it for operability, not to fix quotas. The Railway/Caddy edge is account-agnostic and needs zero Route 53 API calls, so it remains a perfectly good tier-1 if you do not want CloudFront.

### DNS + cert (tiers cut across)

- **Best:** move the `agenticburn.com` (or an `event.agenticburn.com`) zone to Route 53, keep Namecheap as registrar (delegate the subdomain NS). Issue one wildcard ACM cert per terminating account (ACM public certs cannot be shared cross-account, but re-issuing the same wildcard in each account is free). external-dns + ACM DNS-01 then automate create/teardown.
- **Minimum change:** keep the one static Namecheap wildcard record (zero Route 53 API calls, sidesteps the 5 rps throttle) and keep the single LE wildcard, but delegate `_acme-challenge.agenticburn.com` to Route 53 or acme-dns so issuance never depends on Namecheap's whitelisted-IP API.
- **Naming:** host-based, single-label under the wildcard, e.g. `a-<id>.agenticburn.com` or `a-<id>.<acct>.agenticburn.com`. Not path-based.
- **Pre-issue days ahead. Do not opt into 6-day or 45-day LE profiles for a one-day event.** A 90-day LE or 198-day ACM wildcard pre-issued and staged (plus a spare in a second account/Region) is the bulletproof posture.

---

## Angle A: How established lab/workshop platforms do entry points

### Per-platform findings

**Instruqt.** The single public entry point is Instruqt's own web proxy. Learner traffic hits a wildcard subdomain `https://[HOSTNAME]-[PORT][PROTOCOL]-[PARTICIPANT_ID].env.play.instruqt.com`; the proxy parses that subdomain to route to the sandbox, terminates TLS at the edge (one wildcard cert), and accepts any non-expired (even self-signed) backend cert. Raw sandbox endpoints never get their own public DNS/cert. This is the same architecture as our Caddy router, productized. Instruqt powered the KubeCon EU 2025 hands-on workshops. (Verified 2026-06-27: Instruqt Networking docs; KubeCon EU 2025 recap.)

**Killercoda (and retired Katacoda).** Browser-based real Linux/Kubernetes in isolated ephemeral container namespaces with strict network policies, auto-scaled on demand. No public per-cluster URL; the in-browser terminal is the broker. Killercoda is the de-facto Katacoda successor, cited in CNCF's 2026 Kubernetes learning resources. (Verified 2026-06-27: Killercoda creators; CNCF top resources 2026.)

**KodeKloud.** Rancher k3s clusters on sandbox VMs via an in-browser terminal (~30 min/lab). No raw public cluster URL; reaching an in-lab service goes through a "View Port" proxy feature, not a per-user DNS name. (Verified 2026-06-27: KodeKloud public playgrounds; community-faq.)

**AWS Workshop Studio + Event Engine.** No per-attendee public URL at all. Attendees join at `catalog.workshops.aws/join` with an access code and are handed a temporary AWS account + keys + console link. They reach resources through the console and CLI; the platform is just the credential broker; accounts auto-deprovision. (Verified 2026-06-27: catalog.workshops.aws; Event Engine access docs.)

**Google Cloud Skills Boost / Qwiklabs.** Same credential-broker model. Each lab provisions a fresh GCP project + temporary IAM; the pane shows an "Open Google Cloud console" button + creds. Entry is Google's own console, not a platform-proxied per-user hostname. (Verified 2026-06-27: Qwiklabs credentials; Tour of GCP Hands-on Labs.)

**Microsoft Learn sandboxes.** Browser-based, no public URL. A temporary isolated subscription/resource group; the attendee works through Azure Cloud Shell (authenticated browser terminal, per-session host, 20-min idle timeout). (Verified 2026-06-27: Azure Cloud Shell overview; Azure Sandbox guide.)

**Strigo.** Each attendee gets their own lab via an in-browser terminal/desktop; lab web services surface through embedded "Web Interfaces / Webview" panes rather than raw public URLs. The Strigo session link is the single entry point. (Verified 2026-06-27: Strigo use-your-lab; Strigo web interfaces.)

**Play with Kubernetes / Play with Docker.** Everything under one domain. The in-browser terminal is a websocket/xterm.js terminal into Docker-in-Docker backends (no public backend URL). For HTTP services, PWD uses a central proxy with backend identity encoded in a wildcard subdomain: `ip<ip>-<session_id>-<port>.direct.labs.play-with-docker.com`. Same encode-in-subdomain + central-proxy pattern as Instruqt. (Verified 2026-06-27: Introducing Play with Kubernetes; play-with-docker README.)

**CNCF event tooling.** KubeCon hands-on labs run on these brokered platforms, not raw per-attendee public cluster URLs (Instruqt at KubeCon EU 2025; Killercoda CNCF-recommended). (Verified 2026-06-27.)

### Dominant pattern and why

Across every platform, the lab platform is the only public endpoint and brokers into ephemeral backends. None give each backend its own public DNS + cert. Two implementations: (1) a terminal/console broker with zero backend public URLs (AWS, GCP, Microsoft, Killercoda, KodeKloud, Strigo, PWD terminal); (2) a single central reverse proxy with one wildcard cert and backend identity encoded in the subdomain (Instruqt, PWD HTTP ports), used specifically to expose in-backend HTTP services (a UI, Grafana, ArgoCD). One wildcard avoids per-attendee ACME issuance, keeps the cluster endpoint private, gives one place for auth/routing/observability, and survives backend churn.

### Applicable to us + recommendations

Our Railway/Caddy wildcard router is the same architecture Instruqt and PWD ship; we are on the dominant pattern. The cloud-vendor labs sidestep the LB quota wall by exposing nothing per attendee and brokering through credentials + a terminal, which is the most relevant escape for our ALB/NLB-per-Region=50 cap. TLS lenience at the proxy means backends never need real certs. Recommendations: keep the single-wildcard central proxy; eliminate the per-cluster LB and reach clusters through one shared path; prefer a brokered in-browser terminal over any public kubectl/API endpoint; terminate TLS only at the edge; pre-generate and validate the full route map before the event and fail loud on a missing route.

---

## Angle B: Kubernetes and DNS routing patterns at fleet scale

### external-dns to Route 53

Record capacity is a non-issue (10,000 records/zone default). The wall is the Route 53 API rate limit: 5 requests/sec/account, and `ChangeResourceRecordSets` is serialized per zone (`PriorRequestNotComplete`). Running an external-dns per cluster against one shared zone multiplies pressure against that 5 rps budget and is the documented throttling failure mode. Mitigation: a single centralized external-dns with TXT ownership + batched changes, or (preferred) one static wildcard. (Verified 2026-06-27: AWS Route 53 Quotas; external-dns issue #2598; DEV "Scaling DNS in Multi-Cluster Kubernetes with ExternalDNS".)

### Host-based vs path-based

Host-based (`a-<id>.agenticburn.com`) gives clean tenant isolation, independent SNI, no app-side path rewriting, and is the standard SaaS multi-tenant pattern; a single wildcard cert + single wildcard DNS record cover all 250 with zero per-tenant toil. Path-based (`/a/<id>`) inherits path-rewrite pain (relative links, redirects, cookies, WebSocket upgrade paths) that breaks agent UIs. Host-based wins. (Verified 2026-06-27: AWS "Tenant routing strategies for SaaS"; AWS Amplify wildcard guidance.)

### Central shared ingress vs one LB per cluster

One LB per cluster does not scale past ~50/account (ALB and NLB per Region both default 50). A central shared proxy collapses LB count to ~1 and removes the quota wall completely; a 250 to 1 reduction. The shared-ingress "expose multiple services behind a single IP" idiom is documented best practice. (Verified 2026-06-27: AWS ALB/NLB Quotas; Solo.io Kubernetes Ingress guide.)

### Gateway API (2026)

Gateway API is GA and the strategic direction (v1.4 GA 2025-10-06; v1.5 stable 2026-02-27). Ingress is in maintenance; ingress-nginx is EOL 2026-03-31. AWS LB Controller reached GA with Gateway API support 2026-03. But for a disposable lab the right call is still a single shared host-routing proxy, not Gateway API in each cluster: per-cluster Gateways each provision an LB and do not change the LB-per-Region math. Use Gateway API only when consolidating fan-out inside AWS. (Verified 2026-06-27: kubernetes.io Gateway API v1.4/v1.5; gateway-api releases; OneUptime Ingress-vs-Gateway-API; InfoQ AWS LB Controller GA.)

### Cross-cluster/account reachability

Public LB endpoints (today) need zero cross-account plumbing, work uniformly across 5 accounts, tear down trivially; secure with TLS + `loadBalancerSourceRanges`. VPC peering is point-to-point and CIDR-conflict-prone across 250 ephemeral VPCs. Transit Gateway adds $0.02/GB + per-attachment hourly cost. PrivateLink is $0.01/hr/AZ/endpoint + $0.01/GB, one endpoint per consumed service (250 services = real money + churn). For a disposable, multi-account, high-churn lab, public LB endpoints + a public central proxy is the correct tradeoff. (Verified 2026-06-27: AWS "Expose EKS pods through cross-account LB"; OneUptime VPC/PrivateLink/TGW cost guides; AWS EKS Best Practices.)

### Central wildcard proxy vs AWS-native

The wildcard DNS + one TLS-terminating reverse proxy doing Host-header fan-out is textbook multi-tenant SaaS, with Caddy explicitly named. It is an anti-pattern only at HA-critical scale (single point of failure); for a 60-minute 250-seat disposable workshop a single well-sized proxy is the recommended shape (replicate for HA, do not abandon the pattern). The AWS-native equivalent is one shared ALB + wildcard ACM + host rules (100-rule ceiling) or one NLB fronting in-cluster Envoy/Gateway, which keeps everything in-account but reintroduces the per-ALB rule cap and couples to one account. The Caddy approach is account-agnostic and needs zero Route 53 API calls. (Verified 2026-06-27: AWS "Tenant routing strategies"; Skeptrune wildcard TLS; DCHost multi-tenant SaaS.)

### Comparison table

| Pattern | Scales to 250? | LB quota impact | DNS toil | Cross-account reach | Verdict |
|---|---|---|---|---|---|
| LB per cluster + per-service external-dns | No | Hits 50/account, no headroom | High (250 records + 5 rps throttle) | Per-cluster public LBs | Avoid |
| Central proxy + single wildcard DNS (today) | Yes | ~1 LB equiv; quota irrelevant | Minimal (one static wildcard) | Public LBs, account-agnostic | Recommended; keep |
| One shared in-AWS ALB + wildcard ACM + host rules | Yes (<=100 rules/ALB) | 1 ALB/account | Low (one Route 53 alias) | Same-account only | Good AWS-native alt |
| One shared NLB -> in-cluster Envoy/Gateway | Yes | 1 NLB | Low | In-cluster; public NLB cross-account | Strong if consolidating in AWS |
| Gateway API per cluster | No | Same as LB-per-cluster | Same | Per-cluster | Right tech, wrong layer |
| Private connectivity (TGW/PrivateLink/peering) | Painfully | Reduces public LBs, adds endpoints | Plus CIDR coordination | Yes, privately | Overkill for disposable lab |

---

## Angle C: TLS and certificate strategy at scale

### Let's Encrypt rate limits (exact, verified 2026-06-27 at letsencrypt.org/docs/rate-limits)

- Certificates per Registered Domain: **50 per 7 days** (eTLD+1, so everything under `agenticburn.com` shares one bucket).
- Duplicate certificates (identical SAN set): 5 per 7 days (does not bite 250 distinct names).
- Authorization failures per identifier: 5 per account per hour.
- New Orders per Account: 300 per 3 hours (refill 1 per 36s). New Accounts per IP: 10 per 3 hours. Identifiers per cert: 100.
- ARI-coordinated renewals are exempt from all rate limits.

**Which limit 250 per-host certs would breach: Certificates per Registered Domain (50/week), by 5x.** That is exactly why per-cluster issuance was correctly rejected. The move to shorter lifetimes did not change these numbers (renewals are exempt).

### Single wildcard cert

One `*.agenticburn.com` covers every `a-<id>.agenticburn.com` with one issuance (1 of the 50/week bucket; renewals ARI-exempt). Wildcards require DNS-01 (HTTP-01/TLS-ALPN-01 cannot issue them). Wildcard matches exactly one label, so keep attendee hostnames single-label under the apex. One wildcard at a central terminating proxy is the clean answer and is essentially what we run today. (Verified 2026-06-27: LE challenge-types.)

### ACM + Route 53

ACM public certs are $0 on ALB/NLB/CloudFront/API Gateway. Wildcard + Route 53 DNS validation auto-creates the record, auto-validates, and auto-renews; no LE rate limits. ACM public certs are 198-day as of 2026-03-15 with auto-renew. Quota 2,500 certs/Region (irrelevant; one wildcard needed). **ACM does NOT support cross-account sharing of public certs**, but re-issuing the same free wildcard per account is a non-problem; CloudFront needs the cert in us-east-1, ALB/NLB in us-west-2. (Verified 2026-06-27: ACM pricing/FAQ/DNS-validation/limits; repost cross-account.)

### Namecheap DNS-01 and the escape

Namecheap's API requires the caller IP whitelisted on every call and propagation can take ~60 min, which makes automated DNS-01 painful. The standard escape is to delegate only the challenge record: a one-time `CNAME _acme-challenge.agenticburn.com -> <Route 53 or acme-dns target>`; the ACME client writes the TXT in the delegated zone. LE also shipped DNS-PERSIST-01 (2026-02-18) for delegation-friendly validation. Cleanest of all: move the zone (or just `_acme-challenge`) to Route 53 and let ACM validate automatically. For a single wildcard issued once, even raw Namecheap DNS-01 is tolerable. (Verified 2026-06-27: Namecheap API FAQ; lego namecheap; LE challenge-types; LE DNS-PERSIST-01.)

### Edge-terminate vs end-to-end

The browser requirement is satisfied entirely by the one valid public wildcard at the edge; conference WiFi/captive portals/browsers reject self-signed, and the public trust lives at the edge. Edge-terminate + HTTP to backends is acceptable here: the lab secrets are synthetic and clusters live hours. If the proxy-to-backend hop crosses the public internet and you want encryption anyway, use one shared self-signed/private-CA backend cert (edge `insecure_skip_verify` or trusts that one CA), not public per-host certs. Optional, not required. (Verified 2026-06-27: LE challenge-types context.)

### Short-lived cert trends

LE 6-day certs are GA (2026-01-15, opt-in, ARI-required). The 45-day default transition is in progress (tlsserver profile 45-day opt-in 2026-05-13; classic default 64-day 2027-02-10, 45-day 2028-02-16). ARI is the 2026 renewal best practice. For a 2-hour event none of this matters; a 90-day or 198-day wildcard issued days ahead outlives the workshop. Do NOT opt into 6-day/45-day profiles for this. (Verified 2026-06-27: LE 6day-and-ip GA; LE 90-to-45; LE rate-limits-45-day.)

### Recommendations

Keep one wildcard at one central edge, pre-issued and baked in. Prefer ACM + Route 53 (free, DNS-validated, auto-renew, no rate limit, no Namecheap pain) if the edge is an AWS-integrated service. If staying on Railway/LE, issue the single wildcard via DNS-01 and remove Namecheap from the loop by delegating `_acme-challenge` to Route 53/acme-dns. Keep edge-terminate + HTTP to backends. Ignore the short-lived trends; pick the longest convenient lifetime, pre-issue, stage a spare in a second account/Region, and validate end-to-end on conference-like WiFi ahead of time.

---

## Angle D: AWS-native edge and quota economics

### ALB vs NLB economics + quotas (verified 2026-06-27)

ALB $0.0225/hr + $0.008/LCU-hr; NLB $0.0225/hr + $0.006/NLCU-hr. At workshop traffic both are base-hour-dominated; LCU/NLCU is rounding error. The binding constraint is quota, not dollars (250 LBs ~ $7.50/hr, under $200 even for a full day). ALB quotas: per Region 50 (adjustable), rules per ALB 100 (adjustable), **target groups per ALB 100 (NOT adjustable)**, targets per ALB 1,000, certs per ALB 25, target groups per Region (shared) 3,000. NLB: per Region 50 (adjustable), targets 3,000, certs 25.

**Can one shared ALB host-route to 250 backends?** Rules (100, adjustable) are not the wall; **target groups per ALB (100, not adjustable)** is. With 4 services/attendee, 50 attendees = 200 TGs > 100. Fix: one TG per cluster, let an in-cluster proxy split the 4 services; then 50 clusters = 50 TGs and fits one ALB/account. Raising ALB-per-Region to 100 only buys headroom to ~100 clusters/account, so it is the wrong lever.

### Shared ALB per account (IngressGroup)

The AWS LB Controller `IngressGroup` (annotation `alb.ingress.kubernetes.io/group.name`) merges Ingresses onto one ALB. Per 50-cluster account with one TG/cluster: 1 LB (vs 50), 50 of 100 TGs, ~50-200 rules (raise rules), one wildcard ACM cert, 1 listener. **Hard caveat: an ALB lives in one VPC and IP target groups can only register IPs in the ALB's VPC or a peered VPC.** So this requires the 50 clusters in one shared VPC (which we have). NOTE the independent-cluster nuance in the synthesis above: IngressGroup assumes one LB controller, so our adaptation is one router per account rather than one Ingress-group across 50 independent clusters. (Verified 2026-06-27: AWS ingress-sharing blog; EKS ALB ingress docs; ALB target-group docs.)

### CloudFront

US/EU $0.085/GB (first 10 TB), HTTPS $0.0100/10k req; **always-free 1 TB + 10M req/month**, so a one-day 250-seat event is ~$0 to a few dollars. WebSocket supported (10-min idle). Quotas: alternate domain names/distribution 100 (a single wildcard CNAME covers all 250), origins 100, cache behaviors 75, distributions/account 500, 1 cert/distribution. Right pattern: CloudFront -> one (or 5) shared ALB origin(s) doing host routing, adding edge TLS/WAF/WebSocket; it does NOT itself solve LB fan-out. Do not route 250 hostnames to 250 origins in one distribution (75-behavior cap). (Verified 2026-06-27: CloudFront pricing/quotas.)

### API Gateway / VPC Lattice

API Gateway HTTP API: $1.00/M req (1M/mo free), routes/integrations 300, custom domains 120, VPC links 10, **30s integration timeout breaks long-lived WebSocket terminals** (needs a separate WebSocket API). Poor fit. VPC Lattice (~$0.025/hr/service + $0.10/M req): service-mesh across VPCs/accounts, not a public edge, per-service hourly billing across 250 services adds cost for no benefit. Skip both. (Verified 2026-06-27: API Gateway pricing/quotas; Lattice pricing.)

### Route 53 vs Namecheap

Route 53 $0.50/zone/month (first 25), $0.40/M queries, alias to AWS free (first 1B/mo). A single zone + wildcard ALIAS is ~$0.50 for the event month + pennies. Moving the event subdomain to Route 53 (keep Namecheap registrar, delegate NS) unlocks ACM DNS-01 + external-dns automation; Namecheap has no first-class ACM/external-dns integration. For a torn-down-and-rebuilt fleet, Route 53 + external-dns is operationally simpler at negligible cost. (Verified 2026-06-27: Route 53 pricing.)

### Cross-account reach for a central edge

Public path (recommended): each account self-contained with its own shared edge + wildcard subdomain; the central proxy host-routes to 5 per-account public edges, not 250 backends. Zero private plumbing, per-account independent teardown. PrivateLink ~$21.90/mo per 3-AZ endpoint before data, one per consumed service. Transit Gateway $0.05/hr/attachment + $0.02/GB. A central private path is not worth it for a one-day disposable workshop. (Verified 2026-06-27: PrivateLink/TGW pricing.)

### In-browser terminal

ttyd/wetty is HTTP + WebSocket upgrade, which ALB supports natively, so the terminal rides the same shared edge as chat-UI/Grafana/ArgoCD on its own hostname; CloudFront also carries WebSocket. No per-cluster public LB for the terminal. The only requirement is a websocket-capable reverse proxy in the path, one shared component. (Verified 2026-06-27: CloudFront quotas.)

### Cost-and-quota comparison (per 50-cluster account; verified 2026-06-27)

| Option | Public LBs/acct | Certs | Hard quota wall | Edge cost (1-day) | Op complexity |
|---|---|---|---|---|---|
| One LB per cluster (today) | 50 | 1 wildcard | ALB/NLB per Region = 50 | ~$0.03/hr x LBs | High (250 LBs/names) |
| Shared ALB per account (IngressGroup) | 1 | 1 wildcard | Target Groups per ALB = 100 (not adjustable) -> 1 TG/cluster | ~$0.03/hr x5 | Medium (needs shared VPC) |
| CloudFront -> shared ALB(s) | 1 ALB + 1 distro | 1 wildcard ACM | avoided via wildcard CNAME + ALB host-routing | ~$0 (free tier) | Medium (adds edge TLS/WAF/WS) |
| Central proxy only (Railway/Caddy) | depends on layer beneath | 1 wildcard at proxy | inherits the LB layer feeding it | Railway flat | Low at edge; pushes fan-out down |

### Recommendations

Collapse to one shared edge per account (drop ~250 LBs to ~5; the quota bump becomes unnecessary), respecting the non-adjustable 100-TG-per-ALB cap with one TG per cluster + in-cluster service split, and using the shared lab VPC so the edge can reach the clusters. Use one wildcard ACM cert per terminating account. Move the event subdomain DNS to Route 53. Keep the cross-account edge public; skip PrivateLink/TGW. Add CloudFront only for a managed global edge (free tier, TLS/WAF/WebSocket); it does not fix quotas. The in-browser terminal needs no dedicated LB.

---

## Decision points for Michael

These are the choices this spike surfaces; none are forced, the current design works, but each is an improvement with a cost.

1. **Adopt the one-shared-edge-per-account change?** Biggest win (kills the quota wall, drops ~250 LBs to ~5, removes the planned ALB/NLB quota increases). Cost: build the per-account router (NodePort-over-shared-VPC is the LB-free tier-3 mechanism) and stop putting a public LB on the per-cluster `console` Service. This is the one substantive architectural change.
2. **Move DNS + cert to Route 53 + ACM, or just delegate `_acme-challenge`?** Route 53 + ACM is the zero-toil, no-rate-limit, no-Namecheap-pain path (~$0.50 for the event month). The minimum-change alternative is a static Namecheap wildcard + LE wildcard with `_acme-challenge` delegated to Route 53. Either removes the Namecheap IP-allowlist pain we already hit.
3. **Add CloudFront at tier 1, or keep Railway/Caddy?** CloudFront buys managed TLS/WAF/WebSocket in the free tier; Railway/Caddy is account-agnostic and already works. Low stakes either way.
4. **Consider the full broker model for the terminal** (expose nothing per attendee; reach the cluster only through a proxied in-browser terminal, the AWS/GCP/MS pattern). Most quota-proof and most secure on conference WiFi, but the largest build. Worth it only if you want zero public per-attendee surface.

Recommended default: do #1 (shared edge per account) and #2 (Route 53 + ACM), keep tier 1 as Railway/Caddy for now (#3 = no), and note #4 as a future direction. That keeps the validated central-proxy + single-wildcard pattern, removes the only real scaling wall, and cleans up the cert path, without a full broker rebuild before the event.
