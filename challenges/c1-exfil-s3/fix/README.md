<!-- ABOUTME: The C1 stage-2b fix config (#727): a forced egress proxy over a locked resolver, which holds the
     DNS-exfil beat. Config only; the live validation is owed under verify/run-e2e.sh and tracked by #728. -->
# C1 stage-2b fix: forced egress proxy over a locked resolver

This directory holds the config for the fix stage of Challenge 1's two-stage DNS-exfil beat. The beat and
its stages are described in `../../../docs/research/2026-10-31-c1-dns-exfil-beat.md`. The control was chosen
by question 1009 (`#724`, `decisions.md` 2026-11-04): option B, a forced egress proxy enforcing a hostname
allowlist, on top of floor C, a locked DNS resolver. Question 1077 (`#860`) settled that the community
cluster never carries the fix, so this config is for the attendee and admin clusters, which run Istio
ambient.

This is config. Nothing here has run on a cluster. The live validation needs a cluster and is tracked by
`#728`; the owed live check is named at the end of this file.

## What the beat shows, and what the fix holds

Stage 2 applies the L3/L4 egress allowlist. It holds the direct HTTPS beacon. Stage 2b sends the same
marketing demographics out as labels in a DNS query name under a delegated subdomain of `agenticburn.com`
(`../dns-exfil.py`). The allowlist does not see it, because a NetworkPolicy matches addresses and ports and
a query name is outside those fields. The fix closes that door and keeps Bedrock, in-cluster resolution and
C7's weather working.

## The three pieces

1. `resolver-lockdown.yaml` (floor C). A CoreDNS Corefile with no catch-all `forward .`. CoreDNS serves
   in-cluster names and forwards only `amazonaws.com` and `open-meteo.com` to the VPC resolver. Every other
   name, the exfil collector's zone included, finds no upstream and comes back SERVFAIL without leaving the
   cluster. This is what stops the label-encoded lookups.
2. `egress-waypoint.yaml` (option B). An Istio ambient egress waypoint, a `ServiceEntry` for the two
   Open-Meteo hosts, and an `AuthorizationPolicy` that admits only those hosts, by the TLS SNI. Any other
   external name steered to the waypoint is refused.
3. `agent-egress-fqdn.yaml`. The NetworkPolicy deltas that make the waypoint the only public-443 path: the
   weather feed's direct `TCP 443` to anywhere is dropped, and the waypoint pod is the one workload granted
   a public 443. The stage-2 L3/L4 allowlist (`agent-egress-allowlist`), the DNS allow (`agent-allow-dns`)
   and the other companions are left as they are.

## Apply order

The resolver lock and the waypoint go first, then the NetworkPolicy deltas, so the waypoint path exists
before the weather feed's direct door is shut.

```
kubectl apply -f resolver-lockdown.yaml
kubectl -n kube-system rollout restart deployment/coredns
kubectl apply -f egress-waypoint.yaml
kubectl apply -f agent-egress-fqdn.yaml
```

## Why Bedrock and DNS allows stay intact

Bedrock is reached as `bedrock-runtime.<region>.amazonaws.com`, which the VPC resolver answers with the
in-VPC PrivateLink ENI inside `10.0.0.0/16`. It is reached in-VPC, so it keeps its L3/L4 allow and does not
pass through the waypoint. The DNS allow already points at the cluster resolver in `kube-system`; floor C
locks that resolver, so the allow needs no change. Forwarding `amazonaws.com` and `open-meteo.com` is not an
exfil path, because a name under either zone reaches that zone's own authoritative servers, which the
attacker does not run.

## Checked on the pinned Istio (`#959`)

On 2026-11-06, on `watch-it-burn-private` (Istio 1.30.4), in a scratch namespace removed afterwards:

- The ambient egress pattern works on 1.30.4, so it needs no Istio upgrade. istiod programmed the
  waypoint, ztunnel steered each `ServiceEntry` host to it, and both Open-Meteo hosts answered 200.
- The Gateway API CRDs are installed by the `gateway-api` Application (`gitops/bootstrap/apps/gateway-api.yaml`)
  on every profile that installs Istio. istiod creates the `istio-waypoint` GatewayClass from them.
- The waypoint pod carries `gateway.networking.k8s.io/gateway-name`, the label `agent-allow-egress-waypoint`
  selects, and not `istio.io/gateway-name`.
- The allowlist matches the TLS SNI. A rule on `operation.hosts` refused the Open-Meteo hosts too, because
  `hosts` matches HTTP only and the waypoint passes this TLS through. With the SNI rule, `example.com`,
  steered to the same waypoint, was refused and Open-Meteo was admitted.

## The weather feed is in the mesh, and the waypoint reaches istiod (`#980`)

ztunnel steers only an enrolled pod's traffic to the waypoint; a pod outside the mesh reached `example.com`
directly. So the weather-feed pod template in `gitops/ai-layer/resources.yaml` carries
`istio.io/dataplane-mode: ambient`, beside the console and guard-proxy (`#471`). On 2026-11-06, on
`watch-it-burn-private`, in a scratch namespace with no mesh label of its own, under the stage-2 egress
policies and this fix's three files, removed afterwards:

- A weather-feed pod enrolled by its own label reached both Open-Meteo hosts (200 each), through the waypoint by
  ztunnel's log, and reached neither `example.com` nor `www.wikipedia.org`.
- The same pod without the label reached neither Open-Meteo host. Without the enrolment, this fix would end C7's
  live weather.
- A pod standing in for workshop-mcp, under the stage-2 allowlist and not enrolled, reached no public host. It
  needs no enrolment for the fix to hold it, and enrolled it gained the waypoint's route to Open-Meteo, so
  workshop-mcp and workshop-agent stay out of the mesh.
- The waypoint itself needs istiod. It is an Envoy that takes its config and certificates from istiod on TCP
  15012, and the stage-2 allowlist admits 443 alone. It connected at start, in the window before the VPC CNI
  applies a new pod's policies, and when istiod closed the stream 30 minutes later every redial timed out.
  `agent-allow-egress-waypoint` now also admits istiod on 15012; with it the waypoint reconnected within a
  second, and a pod wearing the waypoint's label reached istiod on 15012 and on no other istiod port.

## Owed at build time (before this is applied live, `#728`)

- Pin the resolver lock through the `coredns` addon's `configuration_values`
  (`infra/terraform/aws/cluster/main.tf:324`), so the managed addon keeps it rather than reverting a
  ConfigMap edit.

## Owed live check

Under the `verify/run-e2e.sh` tier, a new script paralleling `verify/c1-exfil-block.sh` (built by `#728`)
asserts, on a fresh attendee cluster: with this fix applied, the DNS collector records nothing new for the
same stage-2b request, while the beacon stays held and Bedrock and in-cluster resolution still answer so
BurritoBot still replies. That is the check that the DNS exfil no longer reaches the collector.
