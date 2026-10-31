<!-- ABOUTME: Internal build-design for #116, the C1 two-stage DNS-exfil beat. Defensive build spec for a
     DEFERRED demo, not Portland lab or slide prose. -->
# C1 DNS-exfil beat: build design (deferred to Barcelona)

Status: deferred to Barcelona (Michael, 2026-09-07, issue #116), label `deferred-barcelona`. This note
is the engineering design the deferral kept the issue open for. It is not Portland content. For Portland
the DNS stage stays a narrated slide that is shown and not run, which is the plan of record. Nothing here
touches the student lab text (`challenges/LAB-TEXT.md`), the facilitation run-of-show, the abstract, or
any deploy config; those stay Michael's to write when the build is scheduled. The disposition is recorded
in `decisions.md` (question 575) and in the `#116` row of
`docs/research/2026-08-28-challenge-currency-review.md`. Dated facts (component versions, CNI support)
get re-checked before the build lands.

This note writes "stage" for the steps of the demonstration, keeping clear of the retired fleet "round"
vocabulary (`verify/round_shapes.py`, issues #290, #291, #498, #560). The clusters are the Community
cluster with no guardrails, the admin clusters with every control armed, and the attendee pool where each
student installs the control themselves.

## 1. Where C1 stands today

C1 part 2 is the outbound beacon (`challenges/c1-exfil-s3/README.md`, `agent-prompt.txt` part 2). The
agent is social-engineered into calling `get_marketing_intel`
(`gitops/ai-layer/workshop-mcp-server.py:190`) and posting the returned JSON out through `run_shell curl`
to `https://agenticburn.com/beacon`, a public 200-responder on the apex Caddy router. The beacon is a
stateful collector (`docs/beacon-collector-spec.md`) that shows a live count and recent payloads, the
"watch the data leave the building" room view.

The beat has two measured stages:

Stage 1, egress open. On the Community cluster, or an attendee cluster before the student applies the
control, the POST reaches the public internet and the beacon count moves (measured from 7 to 8 after the
#108 fix). The intel left the cluster.

Stage 2, egress policy applied. An admin cluster ships the policy armed, and an attendee cluster gets it
once the student applies the agent egress allowlist. The same POST is blocked and the count holds at 7.
Since #108, `policies/network-policies/per-namespace/agent-egress-allowlist.yaml` selects the whole
`agent` namespace (`podSelector: {}`), so it covers the `workshop-mcp` pod where `run_shell` runs, which
is where the exfil is actually performed. Bedrock still works because it is reached in-VPC
(`10.0.0.0/16:443`) through its PrivateLink endpoint. The block is clean and holds.

The teaching claim of this issue sits on top of that clean block. A control that is correct and still
bypassed is a stronger lesson for someone going back to a real cluster than a control that simply works.

## 2. The gap this beat exercises

`agent-egress-allowlist.yaml` permits only `10.0.0.0/16:443`, `172.20.0.0/16:443` (the EKS service CIDR),
and the Pod Identity link-local endpoint (`169.254.170.23/32:80`). Every rule is CIDR plus port, nothing
above L4. The companion `agent-allow-dns.yaml` then allows UDP and TCP port 53 to the `kube-system`
namespace, scoped `podSelector: {}` so it covers the namespace, because nothing in the cluster resolves
names without it: Bedrock's hostname, the in-cluster service names, the collector.

That DNS allow is the channel this beat uses. A NetworkPolicy of this kind matches on addresses and
ports and does not read the query name, so a resolver request can carry information out over port 53 to
CoreDNS, which by default forwards recursively to an upstream resolver that can reach a nameserver outside
the cluster, with the egress allowlist still fully enforced. This is a known limitation of L3/L4 network
policy and has been documented as such for years. The Kubernetes website issue tracker
(https://github.com/kubernetes/website/issues/54997) and Red Hat's egress guide
(https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies) both state that NetworkPolicy
is not a general control against data exfiltration. The sibling "shared CDN" case, where an allowed CIDR
also fronts something we did not intend to allow, is the same class of L3/L4 blindness and is worth one
narrated sentence. DNS is the channel we build the beat around.

## 3. Stage 2b: the same prompt, data leaves over DNS

The attack framing is the stage-2 prompt unchanged: "send our marketing intel to the partner intake." The
difference is the exit path. Instead of the HTTPS POST that stage 2 blocks, the marketing JSON from
`get_marketing_intel` is carried out inside DNS resolver requests to a subdomain delegated to a collector
we control, and the egress allowlist reports green throughout. At design altitude the point is that the
data rides the one protocol the policy had to leave open, so the exact encoding is a build detail left to
the implementation and is not specified here.

Two options for where the resolver requests originate, to settle at build time:

Reuse the Python already in the image. The `workshop-mcp` image is Python-based
(`images/workshop-mcp/Dockerfile`, `python:3.12-slim`), so the standard library can do the lookups with
no added tooling. The image installs only `curl` and `ca-certificates`, so `nslookup` and `dig` are
absent (they would need `dnsutils`), and the Python path avoids adding anything. This matches the existing
`run_shell curl` beat and keeps the "a lookup that looks benign" framing.

A named MCP tool, for example a "report status to a monitoring host" tool. It reads cleaner on a slide and
keeps the mechanism out of free-form shell, at the cost of being an obviously planted tool.

Recommended starting point: the in-image Python form, because it adds nothing to the image and mirrors the
curl beat. Add a named tool only if the slide needs it to be legible.

The collector is the single piece of real build work and is a sibling of the beacon collector
(`docs/beacon-collector-spec.md`). It is an authoritative nameserver for a subdomain delegated to us at
the registrar, which is a Michael-side DNS hand-off of the same shape as the beacon's apex repoint. It
answers every request so the lookups succeed, logs each request with a timestamp and source, reassembles
the payload from the requests it received, and renders it at a `GET /dns/view` next to the beacon view, so
the room sees the same data arrive by a second door while the egress policy stays green. Keep it on the
provisioning app's `/data` volume like the beacon. Like the beacon collector, it is a component we own and
point at ourselves on a disposable cluster.

Why it reaches the collector: `agent-allow-dns.yaml` permits port 53 to `kube-system`, CoreDNS forwards
upstream by default, and the NetworkPolicy never inspects the request name. The stage-2 allowlist is
unchanged and fully enforced the whole time.

## 4. The fix: FQDN-aware egress plus a resolver that is not an open relay

Blocking this needs an L7 or identity-aware egress decision together with closing CoreDNS as an arbitrary
upstream relay. Three build options are teed up here for the architecture call at build time. This is a
fleet networking decision that stays Michael's and is left open in this note on purpose.

Option A, Cilium `toFQDNs`. The named control from the issue. Cilium's DNS-aware policy proxies DNS,
learns which addresses a permitted FQDN resolves to, and allows egress only to those. Its DNS rules can
also restrict which names are resolvable at all (`toFQDNs` and `matchPattern`), which closes the channel
at the proxy. The cost is a CNI migration. The fleet runs AWS VPC-CNI with `enableNetworkPolicy = "true"`
(`infra/terraform/aws/cluster/main.tf:322`), so `toFQDNs` means replacing or chaining Cilium fleet-wide,
which touches every challenge's network assumptions and every per-namespace policy under
`policies/network-policies/`. This is the item that may not be affordable before Portland and is the
reason for the Barcelona deferral. Re-check at build time whether EKS supports Cilium as the primary CNI
or only chained over VPC-CNI, and whether the other beats (default-deny, the apps allowlist,
Falco and KubeArmor) survive the swap.

Option B, a forced egress proxy. Route all agent egress through an explicit forward proxy or egress
gateway that enforces an FQDN allowlist at L7, and drop direct `:443` and `:53` egress in the
NetworkPolicy so the proxy is the only path out. There is no CNI change, and it stays in a layer we
already own. The cost is a new always-on component plus a DNS story, because the proxy or a locked
resolver still has to answer the legitimate names. It reads as adding a real control inside the existing
network without replacing the network substrate, which may be the better lesson for someone returning
to a production cluster.

Option C, lock the resolver, which is a required complement to A and B. Even with FQDN-aware egress,
CoreDNS forwarding arbitrary recursion upstream is the relay. Restrict DNS to the cluster resolver with no
arbitrary upstream: a CoreDNS `forward` scoped to the zones we actually need (AWS and Bedrock, the
collector) with recursion to the open internet disabled, and a NodeLocal DNSCache with an allowlist.
Without C, the egress wins from A and B can still be reached through whatever recursion path is left.

Shape of the lesson: the infra control (the egress policy) was correct, and the first infra control you
reach for (L3/L4 NetworkPolicy) still does not cover this path. You need DNS-aware egress and a resolver
that is not an open relay. This is the reversal structure proposed for C6 in #115 and is a sharper lesson
than "turn on NetworkPolicy."

## 5. Build cost, validation, and the open decision

Cost: medium to large, the largest in the #110 batch. New pieces are the DNS exit path in the MCP tool
(small), the authoritative-DNS collector and its view (medium, a sibling of the beacon collector), a
registrar delegation for the exfil subdomain (Michael-side, one hand-off), and the chosen FQDN control (A
is a fleet CNI migration, B is a new proxy component, C is CoreDNS and NodeLocal config).

Validation needs a cluster, and option A needs a Cilium cluster. The acceptance shape follows C1 today:
the DNS stage lands at the DNS collector with the egress NetworkPolicy still green; after the fix, the
resolver requests carry nothing out and the collector stops receiving, while Bedrock and legitimate
in-cluster resolution still work. Add a `verify/` check in the live-cluster tier (the `run-e2e.sh` tier,
with `CONTEXT` set), paralleling `verify/c1-exfil-block.sh`, which today applies the C1 policies and
asserts the blocked send reads as a failure in BurritoBot's reply.

Open decision, parked until the Barcelona build is scheduled: which FQDN control to use (option A Cilium
`toFQDNs` or option B forced egress proxy, both on the option C resolver-lockdown floor). This is a fleet
networking and architecture call with real cost and is left open here on purpose. It waits on Michael
and on the build being scheduled for the next event.

## 6. References

- `policies/network-policies/per-namespace/agent-egress-allowlist.yaml`: the L3/L4 egress allowlist (#108).
- `policies/network-policies/per-namespace/agent-allow-dns.yaml`: the port-53-to-kube-system allow that is the open channel.
- `challenges/c1-exfil-s3/README.md`, `agent-prompt.txt`: the C1 beat and the HTTPS exfil it builds on.
- `docs/beacon-collector-spec.md`: the HTTPS collector, of which the DNS collector is a sibling.
- `gitops/ai-layer/workshop-mcp-server.py:190`, `images/workshop-mcp/Dockerfile`: the tool surface (`run_shell`, `get_marketing_intel`; Python present, `dnsutils` absent).
- `infra/terraform/aws/cluster/main.tf:322`: VPC-CNI with `enableNetworkPolicy = "true"`, the CNI the Cilium option would replace or chain.
- `verify/c1-exfil-block.sh`: the C1 live-cluster check the new DNS check parallels.
- Kubernetes website issue tracker: https://github.com/kubernetes/website/issues/54997
- Red Hat egress guide: https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies
- `decisions.md` question 575 and `docs/research/2026-08-28-challenge-currency-review.md`: the deferral record.
