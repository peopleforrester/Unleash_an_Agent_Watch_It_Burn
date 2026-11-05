<!-- ABOUTME: Build design for #116 / #723, the C1 two-stage DNS-exfil beat: the L3/L4 egress policy holds the HTTPS
     beacon, the DNS allow stays open beside it, and an FQDN-aware control closes it. Deferred to the next event. -->
# C1 two-stage DNS-exfil beat: build design

**Status: deferred to the next event.** Michael deferred #116 on 2026-09-07 with the label `deferred-barcelona`, and
kept it open because the design work is still wanted for the next event (Question 575 in `decisions.md`; the #116 row
in `docs/research/2026-08-28-challenge-currency-review.md`). This note is that design. It changes no lab text, slide,
run of show or deploy config. Portland narrates the DNS stage on a slide and does not run it.

The note is written at the altitude of `docs/beacon-collector-spec.md`: it names the channel, the components to build
and the checks that prove them. It does not specify how the agent's tool produces the lookups. That piece is written
at build time, inside the lab, under the same review as the existing C1 `run_shell` beat.

"Stage" names a step of the demonstration. The fleet's retired "round" vocabulary (`verify/round_shapes.py`) is kept
out of it.

## What exists today

C1 part 2 is the outbound beacon (`challenges/c1-exfil-s3/README.md`, `agent-prompt.txt` part 2). The agent is talked
into calling `get_marketing_intel` (`gitops/ai-layer/workshop-mcp-server.py:190`) and sending the result to
`https://agenticburn.com/beacon` through `run_shell`. The beacon is the stateful collector in
`docs/beacon-collector-spec.md`.

- **Stage 1, egress open.** On the Community cluster, or an attendee cluster before the student applies the control,
  the POST reaches the beacon and the count moves.
- **Stage 2, egress policy applied.** On an admin cluster, or an attendee cluster once the student applies it,
  `policies/network-policies/per-namespace/agent-egress-allowlist.yaml` holds the POST. Since #108 its `podSelector`
  is `{}`, so it covers the whole `agent` namespace, the `workshop-mcp` pod where `run_shell` runs included.
  Bedrock still answers because it is reached in-VPC on `10.0.0.0/16:443`. `verify/c1-exfil-block.sh` checks this
  stage live.

The tool image is `images/workshop-mcp/Dockerfile`: `python:3.12-slim` with `curl` and `ca-certificates` from apt and
nothing else. `dnsutils` is absent, so `dig` and `nslookup` are not in the pod.

## The gap the beat shows

The egress allowlist is CIDR and port. It permits `10.0.0.0/16:443`, the service CIDR `172.20.0.0/16:443` and the
Pod Identity endpoint `169.254.170.23/32:80`. `policies/network-policies/per-namespace/agent-allow-dns.yaml` adds
UDP and TCP 53 to the `kube-system` namespace for every pod in `agent`, because the pods resolve Bedrock and
in-cluster service names through it.

NetworkPolicy rules match addresses and ports, and a DNS query name is outside the fields they match. CoreDNS forwards names it does not serve to
an upstream resolver, and that resolver walks to whichever authoritative server owns the zone. A query name that
carries data therefore travels from the pod to that server with stage 2's policy still enforced. This is the
textbook DNS-tunnel class, and the Kubernetes and Red Hat sources in the references both say NetworkPolicy alone
does not stop exfiltration.

The cluster enforces NetworkPolicy through VPC-CNI: `enableNetworkPolicy = "true"` sits in the `vpc-cni` addon
configuration at `infra/terraform/aws/cluster/main.tf:332`. That engine works at L3/L4 and has no DNS-aware rule
type.

## Stage 2b: same request, a different door

The student keeps the stage 2 policy on. The agent receives the same social-engineering request as stage 2, and the
tool sends the intel out through name lookups. The beacon count stays still. The DNS collector's view fills with the
same marketing data. The room sees an enforced, green policy and the data leaving anyway.

## The DNS collector (build spec)

A sibling of the beacon collector, owned by us and pointed at by our own disposable clusters.

- **Zone.** A subdomain of `agenticburn.com` delegated to the collector. The delegation is a registrar change on
  Michael's side, the same kind of hand-off as the beacon's apex repoint.
- **Ingest.** An authoritative nameserver for that zone. It answers each query so the caller sees success, and
  appends a record per query to the provisioning app's `/data` volume: timestamp, source address, query name.
- **View.** `GET /dns/view` on the provisioning service, beside `/beacon/view`: a total count, the last ~50 records,
  and the reassembled payload, auto-refreshing for a projector.
- **Reset.** A clear action between rehearsal runs, as the beacon has.
- **Hosting.** UDP and TCP 53 must reach it from the internet. Where it runs (the provisioning host or a small
  dedicated one) is settled at build time.

## The fix: FQDN-aware egress over a locked resolver

Holding stage 2b takes two things together: an egress decision that knows names, and a resolver that will not relay
arbitrary names upstream. These are the options for that build. Choosing among them is a fleet networking decision
and stays open here.

- **A. Cilium `toFQDNs`.** Cilium's DNS-aware policy proxies the pod's lookups, allows only listed names, and opens
  egress only to the addresses those names return. The cost is the CNI: the fleet runs VPC-CNI's own enforcement
  (`main.tf:332`), so this means Cilium as primary CNI or chained over VPC-CNI, across the fleet, with every policy
  under `policies/network-policies/` and every other beat retested on it.
- **B. Forced egress proxy.** All `agent` egress goes through a forward proxy or egress gateway that enforces an FQDN
  allowlist at L7, and the NetworkPolicy drops direct 443 and 53 so the proxy is the only path out. The CNI stays as
  it is. The cost is a new always-on component and a resolver for the names the proxy itself needs.
- **C. Resolver lockdown.** CoreDNS forwards only the zones the lab uses (AWS and Bedrock, in-cluster names, the
  collector for the demo) and refuses recursion for everything else, or NodeLocal DNSCache does the same with an
  allowlist. C pairs with A or B; on its own it closes the relay and leaves egress decisions at L3/L4.

**Where the fix runs (question 1077, #860, 2026-11-05).** The community cluster never carries the fix. It stays the
stage 1 cluster, egress open, on the bare burn profile, which gains no Istio and no proxy. The fix is built for
attendee and admin clusters, which run Istio ambient, so B is built once, on the mesh. A later breakout profile
that wants the full fix on its community cluster makes that choice in its own issue.

## As built: option B over floor C (#861)

The #724 decision (question 1009) chose B over floor C. #861 carried its four build items, and this is what was
built for them. Nothing in it uses the mesh.

- **The proxy.** `egress-proxy` runs in `agent` from `gitops/ai-layer/egress_proxy.py`, a standard-library CONNECT
  proxy on the pinned workshop-mcp image. It opens a tunnel only to a hostname on `ALLOWED_HOSTS` and port 443, and
  it refuses any other name before it looks the name up. Each decision is one JSON line in its log.
  `agent-allow-egress-proxy` admits this pod alone to 443 and to kube-dns.
- **The weather feed (item 2).** `ALLOWED_HOSTS` is `geocoding-api.open-meteo.com` and `api.open-meteo.com`, the
  two hosts `weather_feed.py` calls. The feed sets `HTTPS_PROXY`, and `agent-allow-weather-feed-egress` now points
  it at the proxy on 3128 instead of 443 to anywhere. No pod in `agent` but the proxy has a direct path out on 443,
  in the stage 2 file and in the fix (item 1).
- **The locked resolver (item 1).** `agent-dns` is CoreDNS in `agent` (`gitops/agent-dns`). It answers
  `cluster.local` and `bedrock-runtime.us-west-2.amazonaws.com` through kube-dns, and sends every other name to the
  VPC resolver at 169.254.169.253. The Kyverno MutatingPolicy `agent-dns-resolver` points every new `agent` pod at
  it (nameserver 172.20.0.53), except agent-dns and egress-proxy, whose labels are on the egressLabels list.
  Stage 2's `agent-allow-dns` still admits 53 to kube-system and to the VPC resolver, so stage 2b leaks. The fix,
  `c1-dns-lock.yaml` in `challenge-fixes`, replaces that policy: only agent-dns may reach a DNS server, and only
  kube-dns. Every other name then fails inside the cluster, and no other pod can send a query anywhere.
- **Bedrock (item 3).** Bedrock keeps the in-VPC `10.0.0.0/16:443` allow and does not go through the proxy. That
  CIDR reaches no public host, and its PrivateLink endpoint is the VPC's only interface endpoint, so the resolver
  needs that one AWS name. Routing every model call through the proxy would add a hop and a failure point to each
  turn and close no path. The Pod Identity allow at `169.254.170.23:80` stays.
- **Istio 1.30.4 (item 4).** The 1.30 documentation has no ambient egress page. The page was added on 2026-09-17
  and first ships with the 1.31 docs. The 1.30 waypoint page does document binding a `ServiceEntry` to a waypoint
  through `istio.io/use-waypoint`. The private cluster has no Gateway API CRDs, which a waypoint needs, and the
  burn profile has no Istio at all (#860). So the proxy is a plain Deployment, and the pin does not have to support
  the pattern.
- **Profiles.** `agent-dns` is listed on attendee, admin, full and local-inference. The admin profile's armed set
  (`policies/network-policies`) is the fixed state. The KubeCon and burn profiles do not list it, so the fix is not
  for those clusters, and applying `c1-dns-lock.yaml` there would cut every lookup. The proxy is part of ai-layer
  and runs on every profile.

`verify/test_egress_lock.py` holds the stage 2 and fixed sets, the Corefile and the allowlist.
`verify/test_egress_proxy.py` runs the proxy. `verify/test_agent_dns_mutation.py` runs the mutation through the
Kyverno CLI, and `verify/test_egress_proxy_e2e.py` runs the weather feed through the proxy against Open-Meteo.
`verify/test_c1_dns_lock_live.py` builds these pieces in a scratch namespace on a cluster and checks the three
assertions below. A name that gets an authoritative answer from example.com stands in for the DNS collector,
which is not built yet (#726).

## Build pieces and cost

| Piece | Size | Notes |
|---|---|---|
| Stage 2b tool behaviour | small | Written at build time inside the lab; the image already has Python, so no package is added |
| DNS collector, view, reset | medium | Sibling of the beacon collector |
| Zone delegation | one hand-off | Michael, at the registrar |
| FQDN control | A: large, B: medium, C: small | The open decision above |

## Validation owed on a cluster

Nothing here has run on a cluster. When the build is scheduled it gets a live check in the `verify/run-e2e.sh` tier,
taking `<host> <kube-context>` the way `verify/c1-exfil-block.sh` does, with the cluster named explicitly on every
call. It asserts three things:

1. With the stage 2 policy applied, the beacon count holds and the DNS collector records the stage 2b request.
2. With the chosen FQDN control applied, the DNS collector records nothing new for the same request.
3. With that control applied, Bedrock and in-cluster resolution still work, so BurritoBot still answers.

Option A also needs a Cilium cluster to run on. Dated facts here (CNI support on EKS, versions) are re-checked when
the build starts.

## References

- `policies/network-policies/per-namespace/agent-egress-allowlist.yaml`: the L3/L4 allowlist, namespace-wide since #108.
- `policies/network-policies/per-namespace/agent-allow-dns.yaml`: the port 53 allow to `kube-system`.
- `gitops/ai-layer/workshop-mcp-server.py:190`: `get_marketing_intel`.
- `images/workshop-mcp/Dockerfile`: the tool image, `curl` and `ca-certificates` only.
- `infra/terraform/aws/cluster/main.tf:332`: VPC-CNI with `enableNetworkPolicy = "true"`.
- `docs/beacon-collector-spec.md`: the HTTPS collector the DNS collector sits beside.
- `verify/c1-exfil-block.sh`: the live stage 2 check the new one parallels.
- Kubernetes website issue on NetworkPolicy and exfiltration: https://github.com/kubernetes/website/issues/54997
- Red Hat, a guide to Kubernetes egress network policies:
  https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies
