<!-- ABOUTME: Demo-URL DNS for the workshop on agenticburn.com (Namecheap). Cluster URLs now; student -->
<!-- ABOUTME: provisioning deferred. Records are written post-provision via set-demo-dns.py (--apply). -->

# Demo DNS (agenticburn.com)

The workshop's facilitator-driven cluster URLs live on **agenticburn.com** (Namecheap). Student
self-provisioning DNS is **deferred**; this covers the demo/instructor clusters only.

## URL scheme (CNAME -> the cluster's AWS LoadBalancer hostname)

| URL | Points at |
|---|---|
| `burn.agenticburn.com` | the active Cluster 1 (no-guardrails) spare; repoint as spares rotate |
| `wall.agenticburn.com` | Cluster 2 (CNCF controls on) |
| `haiku.agenticburn.com` | instructor Cluster 3, Haiku tier |
| `sonnet.agenticburn.com` | instructor Cluster 3, Sonnet tier |
| `opus.agenticburn.com` | instructor Cluster 3, Opus tier |

Each is a CNAME to the EKS LoadBalancer hostname (an AWS `*.elb.<region>.amazonaws.com` name), which
only exists after the cluster is provisioned. Until then there is nothing to point at.

## How to write the records (post-provision, with Michael's go)

```bash
# dry-run (default): prints the exact record set, changes nothing
python3 infra/dns/set-demo-dns.py burn=<lb-host> wall=<lb-host> haiku=<lb-host>
# write it (mutation; only with Michael's explicit go, per the namecheap-api rule)
python3 infra/dns/set-demo-dns.py --apply burn=<lb-host> ...
```

The tool reads the current records first and **merges**, so the existing parking/apex records survive
(`setHosts` replaces the whole record set, so a naive write would wipe them). Credentials come from
`~/secrets/dns/namecheap.env`; nothing is hardcoded.

## Gotchas / verify-at-build

- **IP allowlist:** the `ClientIp` must be a Namecheap-whitelisted IP that matches where the call runs
  (the netcup VPS `152.53.192.39` and Michael's laptop are whitelisted). Run from there.
- **TLS:** once a URL resolves to the LB, issue certs with cert-manager + Let's Encrypt (HTTP-01 per
  host is simplest; DNS-01 via a Namecheap webhook solver is the wildcard option). Not wired yet.
- **Mutation safety:** `--apply` changes live DNS; per the namecheap-api rule it needs explicit go.
- **Tag the LB too:** when the demo Service is exposed as `type: LoadBalancer`, add the
  `aws-load-balancer-additional-resource-tags: project=watch-it-burn,...` annotation so the ELB is
  tagged ours in the shared account. See `infra/TAGGING.md` (the full naming/tagging convention).
