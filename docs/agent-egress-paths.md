<!-- ABOUTME: Every egress path the agent namespace keeps once Challenge 1's egress allowlist is on, and for each one
     whether it is closed or accepted, why, and what would close it (#1412, from rounds-agenticburn#154). -->
# Agent egress: what stays open beside the allowlist

The deck's Challenge 1 slide (#/41) shows `agent-egress-allowlist` as an excerpt. That policy is one of several that
select pods in the `agent` namespace, and NetworkPolicy allows add up: a pod may send whatever any policy selecting it
admits. So the answer to "what can still leave the agent namespace?" is the union of every path below, of
which the allowlist is one part. The 2026-11-08 audience review (rounds-agenticburn#154) asked for that answer; this file is it
(#1412).

This is read from the repo as of 2026-11-12. The run that wrote it had no cluster access, so nothing here was read live
except where a line says so.

## When these policies are on

- **Admin cluster** (`admin` profile, watch-it-burn-private): Argo CD's `network-policies` app keeps the six
  `policies/network-policies/per-namespace/agent-*.yaml` files applied.
- **Attendee cluster**, after the student runs `kubectl apply -f ~/challenges/c1-network-policy.yaml`: the same six,
  shipped as one manifest in the `challenge-fixes` ConfigMap (`gitops/ai-layer/resources.yaml`).
- **Community cluster** (`burn` profile, watch-it-burn-community): none of them. Egress from `agent` is open on purpose;
  it is C1's stage 1. `guardrails-on` applies the six there for the length of a demo.

Two more policies select single pods in `agent` and stay on with or without the six: `platform-console-egress` on
every profile, and `agent-allow-desk-relay-egress` on the private cluster alone. They are listed below too, because
the room's question is about the whole namespace.

## Short answer for the room

The allowlist admits the cluster's own network: the VPC on 443 for Bedrock, the service network on 443 for the
Kubernetes API, and the node's Pod Identity endpoint for the agent's AWS credentials. Beside it sit allows for DNS,
for telemetry to our own collector, for the kagent control plane, and for three platform pods (the weather feed, the
console and the support-desk relay) that reach fixed hosts of ours or Open-Meteo's. None of those reaches a server the
attacker runs over HTTPS. Two doors stay open and we know about both. DNS is the next stage of this same attack: a
query name can carry the data to a nameserver the attacker owns, and the fix (a resolver that forwards only the zones
we use, plus an egress proxy that admits only named hosts) is built as config and has not run live. The kagent allow
admits the whole `kagent` namespace, where kagent's own tool server, with a shell tool, runs with open egress; that
is open for this talk and narrowing it is filed as #1414.

## Every path, one row each

| Path | Policy | Where data can go through it | Status |
|---|---|---|---|
| VPC, `10.0.0.0/16` TCP 443 | `agent-egress-allowlist` | Bedrock's PrivateLink endpoint, the API server's ENIs, and any pod or internal load balancer in the VPC listening on 443 | Accepted |
| Service network, `172.20.0.0/16` TCP 443 | `agent-egress-allowlist` | The Kubernetes API (`kubernetes.default`, 172.20.0.1) and any ClusterIP Service on port 443 | Accepted |
| Pod Identity, `169.254.170.23/32` TCP 80 | `agent-egress-allowlist` | The node-local agent that hands a pod its own AWS credentials | Accepted |
| DNS, UDP and TCP 53 to `kube-system` | `agent-allow-dns` | CoreDNS, which forwards any name it does not serve upstream, so a query name reaches the zone's own nameserver | Open by design: C1 stage 2b, deferred |
| OTLP, TCP 4317 and 4318 to `monitoring` | `agent-allow-otel-egress` | The OpenTelemetry Collector, which exports to the workshop's own Datadog org and in-cluster stores | Accepted |
| Every port to the `kagent` namespace | `agent-allow-kagent-egress` | kagent's controller and Postgres, which the agent needs, and also kagent-tools and grafana-mcp, which it does not | Open for KubeCon NA 2026, closing filed as #1414 |
| Weather feed, TCP 443 to any address | `agent-allow-weather-feed-egress` | Open-Meteo's two API hosts, with a city name the caller supplies | Accepted; closed by the C1 fix |
| Any pod to any pod in `agent` | `agent-allow-intra-namespace` | Other `agent` pods, and through them only what those pods' own egress admits | Accepted |
| Console, everything | `platform-console-egress` | Fixed in-cluster upstreams named in `console.conf` | Accepted |
| Desk relay, TCP 443 to any address (private cluster) | `agent-allow-desk-relay-egress` | The public support desk at `DESK_PUBLIC_URL` | Accepted |

## Why each one is closed or accepted

### VPC on 443

The agent reaches Bedrock at `bedrock-runtime.<region>.amazonaws.com`, which the VPC resolver answers with the
interface endpoint's in-VPC address, so the rule names the VPC CIDR and not the internet. It holds only while the VPC
has no S3 endpoint: an S3 gateway or interface endpoint would make S3 look in-VPC and reopen C1's own exfil. The
caveat sits in `agent-egress-allowlist.yaml` and in `infra/terraform/aws/network/main.tf`.

The CIDR also covers every pod address, since VPC-CNI gives pods VPC addresses, and any internal load balancer. A
pod in another namespace that listens on 443 and forwards to a host of the caller's choosing would be a relay. The
repo installs none that does so; reading the live list is part of #1414.

### Service network on 443

The pods dial the Kubernetes API at its ClusterIP, which sits in the service CIDR rather than the VPC. The
`kubearmor-gate` Job in `agent` needs it, and without it the whole AI layer stops syncing (caught on
watch-it-burn-r2-1, 2026-08-28). What a pod may do with the API is decided by its ServiceAccount's RBAC and by Kyverno
(`policies/kyverno/restrict-agent-spawned-workloads.yaml`), not by the network. Other Services on 443 are admission
webhooks; the live list is read under #1414.

### Pod Identity on port 80

A pod in `agent` fetches its own AWS credentials here; without it the Bedrock call fails. The endpoint is link-local
and answers only for the calling pod's ServiceAccount. Holding the credentials opens no new network path: S3 is still
a public host that the allowlist does not admit. The instance metadata service, a different link-local address, is
denied to `agent` by `policies/cluster-network-policies/agent-deny-imds.yaml` on every profile but `burn`.

### DNS

The pods resolve Bedrock, the collector and in-cluster names through CoreDNS, so the namespace needs port 53 to
`kube-system`. NetworkPolicy matches addresses and ports, and a query name is neither, so data spelled into a name
travels from CoreDNS to whichever nameserver owns the zone. That is C1 stage 2b
(`docs/research/2026-10-31-c1-dns-exfil-beat.md`, `challenges/c1-exfil-s3/dns-exfil.py`).

Michael deferred the beat to the next event on 2026-09-07 (#116); at KubeCon NA 2026 a slide narrates it. The fix
is in `challenges/c1-exfil-s3/fix/`: `resolver-lockdown.yaml` makes CoreDNS forward only `amazonaws.com` and
`open-meteo.com`, so any other name comes back SERVFAIL without leaving the cluster, and `egress-waypoint.yaml` with
`agent-egress-fqdn.yaml` makes an Istio egress waypoint, admitting Open-Meteo alone by TLS SNI, the one public 443
path. It is config, applied on no cluster; the live check is #728.

### OTLP to the collector

The agent layer sends its traces and logs to the OpenTelemetry Collector in `monitoring`. The sender chooses what a
span says, not where the collector sends it: the exporters are fixed in `gitops/otel-collector/` and write to the
workshop's own Datadog org and in-cluster stores. Data written into a span lands where only the workshop's own
accounts can read it.

### The kagent namespace

The agent needs `kagent-controller` on 8083 (`KAGENT_URL`) and `kagent-postgresql` on 5432 (found live 2026-06-26,
recorded in `agent-allow-kagent-egress.yaml`). The rule names the whole namespace on every port, and that namespace
also runs kagent's own tool server. kagent chart 0.10.1 (`gitops/bootstrap/apps/kagent.yaml`) bundles kagent-tools
0.2.1, Service `kagent-tools` on 8084, and the repo sets neither of its read-only switches. At that version, by its
upstream source, the server registers a `shell` tool ("Execute shell commands") unless it runs read-only, and its
chart binds cluster-admin unless `rbac.readOnly` is set. No NetworkPolicy in this repo selects a pod in `kagent`, so
that pod's egress is open. A pod in `agent` such as `workshop-mcp`, where `run_shell` runs `curl`, could call that tool
over MCP and have it make the HTTPS request the allowlist refused.

That chain is read from the upstream sources at those tags and from the 2026-11-06 evaluation in #987, which found
kagent-tools installed on both clusters with a shell tool among 124. It has not been exercised on a cluster. #987
records Michael's decision to leave the kagent-tools install unchanged before the talk, and notes that its chart
defaults are broader than the workshop's guardrails assume. So the path stays open for KubeCon NA 2026. Closing it
(narrowing the allow to the controller's 8083 and Postgres's 5432, running kagent-tools read-only, or giving `kagent` an
egress policy of its own) is #1414, with the live checks it needs.

### The weather feed

C7's `get_weather` returns a real reading because the `weather-feed` pod reaches Open-Meteo. Open-Meteo's addresses are
not fixed and a NetworkPolicy cannot name a host, so the rule is TCP 443 to any address for that pod. What keeps it
narrow is the pod: `gitops/ai-layer/weather_feed.py` builds its two URLs itself
(`geocoding-api.open-meteo.com` and `api.open-meteo.com`) and takes only a city name of at most 100 characters from
the caller. Data spelled into a city name reaches Open-Meteo, a third party the attacker does not run. Kyverno's
`egressLabels` list carries the pod's label, so the agent cannot start a pod that wears it. The C1 fix closes the
direct door: `agent-egress-fqdn.yaml` replaces this policy with an empty egress list and sends the feed through the
waypoint.

### Pod to pod inside `agent`

The chat path is in-namespace (guard-proxy, agentgateway, the agent, workshop-mcp), so every pod may reach every other
on any port. That is not a way out by itself. It is one only through an `agent` pod whose own egress is wider, and
those are the weather feed, the console and the desk relay, each of which reaches fixed hosts. Every `agent` pod can
also reach guard-proxy's `/toggle`; that is a question for the guard controls and is recorded in
`docs/research/2026-10-24-istio-ambient-evaluation.md` (#238).

### The console

The console is the front door for every `<service>-<cluster>` host, so it keeps all egress whatever a student applies
(#233). The agent's own pods do not wear its label, and Kyverno refuses an agent-made pod that does. Every
`proxy_pass` in `gitops/ai-layer/console.conf` names a fixed in-cluster Service (guard-proxy, the web terminal, the
collector, fake-ticket, maintenance-shell, the registry, Grafana, Argo CD, Backstage), so an `agent` pod that calls
the console reaches only those.

### The desk relay (private cluster)

On watch-it-burn-private, `desk-relay` carries workshop-mcp's ticket reads and deploy reports to the public support
desk (#1158). Its rule is TCP 443 to any address, since the desk's router address is not this repo's. `desk_relay.py`
builds every URL from `DESK_PUBLIC_URL`, the workshop's own desk, and Kyverno's `egressLabels` list carries its label.

## Not yet read on a cluster

- That a pod in `agent` reaches `kagent-tools:8084` and that its `tools/list` names `shell` (#1414).
- The live list of Services and pods listening on 443 in the service CIDR and the VPC (#1414).
- The C1 DNS fix end to end (#728).
