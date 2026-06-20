<!-- ABOUTME: Doc-accuracy spike verifying the six mechanism claims in STACK-WALKTHROUGH.md and -->
<!-- ABOUTME: governance-map.md against current primary sources, with per-claim CONFIRMED / NEEDS-CORRECTION. -->

# Mechanism verification, June 2026

## Verification Method

Each claim from `docs/STACK-WALKTHROUGH.md` and `facilitation/governance-map.md` was
checked against primary documentation (vendor docs, project docs, project repositories)
retrieved live via web search and fetch. Training data was not relied on for version
numbers, field names, schema, or defaults. Verdicts are CONFIRMED or NEEDS-CORRECTION,
each with the source URL used.

- Verifier: research spike, web sources only (no live cluster probe).
- Date of verification: 2026-06-20.
- Sources are the official docs / repos cited inline per claim.

---

## Claim 1: VPC-CNI L3/L4 NetworkPolicy default-deny egress blocks S3 PutObject (internet) while Bedrock works via a VPC endpoint (PrivateLink, in-VPC)

Verdict: CONFIRMED (with one nuance to state out loud).

- Bedrock supports AWS PrivateLink interface VPC endpoints. Service names include
  `com.amazonaws.region.bedrock` and `com.amazonaws.region.bedrock-runtime`. Traffic stays
  on the AWS network with no internet/NAT gateway; AWS places an endpoint ENI in each
  enabled subnet. Source: https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html
- Kubernetes NetworkPolicies with the VPC CNI operate at OSI layers 3 and 4 (IP address and
  port), namespace-scoped, with implicit default-deny on any traffic not explicitly allowed.
  Source: https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html

Nuance: the L3/L4 split works because the Bedrock VPC endpoint ENI has an in-VPC private IP
that an egress allow rule (CIDR or selector) can permit, while S3 reached over the public
internet falls under the implicit deny. NetworkPolicy egress rules match CIDRs/ports, NOT
DNS names; there is no L7 awareness. So the doc's phrasing is accurate as long as it is
understood the allow targets the endpoint's IP range, not a hostname. If the cluster instead
used an S3 gateway endpoint, S3 would also become in-VPC reachable, so the "S3 blocked"
behavior depends on S3 being reached over the internet path, not via an S3 VPC endpoint.

## Claim 2: kubelet podPidsLimit (cgroup pids.max) refuses forks inline as the real fork-bomb block; on EKS AL2023 delivered via nodeadm KubeletConfiguration

Verdict: CONFIRMED.

- `podPidsLimit` is a kubelet configuration field (equivalently the `--pod-max-pids` flag)
  that caps the number of PIDs/processes per pod; it maps onto the pod cgroup `pids.max`
  and the kernel refuses new forks once the limit is hit. Source:
  https://kubernetes.io/docs/concepts/policy/pid-limiting/ and
  https://oneuptime.com/blog/post/2026-02-09-kubelet-maxpods-podpidslimit/view
- On EKS AL2023 the legacy `bootstrap.sh` is gone; node configuration is delivered through
  `nodeadm` `NodeConfig`, which carries a `spec.kubelet.config` `KubeletConfiguration` block
  (where `podPidsLimit` is set) and merges into `/etc/kubernetes/kubelet/config.json`.
  Source: https://awslabs.github.io/amazon-eks-ami/nodeadm/doc/examples/

Note: the block is per-pod cgroup `pids.max` enforcement at fork time. That is the correct
characterization. Worth distinguishing from the node-level `--max-pids` SystemReserved knob
if the doc ever needs that precision.

## Claim 3: Istio ambient mTLS certs are SPIFFE SVIDs (spiffe://cluster.local/ns/<ns>/sa/<sa>)

Verdict: CONFIRMED.

- Istio identities are SPIFFE IDs in the form `spiffe://cluster.local/ns/<namespace>/sa/<serviceaccount>`.
  The X.509 cert is an X.509-SVID with the SPIFFE ID in the SAN; it is used for mTLS. In
  ambient mode, ztunnel requests the per-pod service-account-identity certificate from istiod
  (the Istio CA) and manages rotation. Sources:
  https://istio.io/latest/docs/concepts/security/ (identity/SPIFFE) and
  the ambient ztunnel cert behavior described at
  https://oneuptime.com/blog/post/2026-02-24-how-to-handle-certificate-management-in-ambient-mode/view

The doc's statement that the mTLS certs ARE SPIFFE identities, and that adding Istio ambient
STRICT delivers the SPIFFE identity layer, is accurate.

## Claim 4: Kyverno v1.18 registry-allowlist (validate image pattern) + verifyImages cosign keyless (Fulcio/Rekor), incl. failureAction placement

Verdict: CONFIRMED, with a placement nuance to get exactly right.

- Kyverno verifies cosign keyless signatures using Fulcio (ephemeral cert) and Rekor
  (transparency log). The keyless attestor schema is:
  `verifyImages[].attestors[].entries[].keyless` with `subject`/`subjectRegExp`,
  `issuer`/`issuerRegExp`, and `rekor.url`. Source:
  https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/
- A registry/image-pattern allowlist is a normal `validate` rule (pattern match over
  `image`), separate from `verifyImages`. Source:
  https://kyverno.io/docs/policy-types/cluster-policy/validate/

failureAction placement (the part to be precise about): in modern Kyverno (1.18 line), the
old `spec.validationFailureAction` is deprecated in favor of a per-rule field.
- For a `validate` rule the field is `spec.rules[].validate.failureAction` (Audit | Enforce),
  which matches the STACK-WALKTHROUGH table row ("rule-level `validate.failureAction`").
- For a `verifyImages` rule the field is `spec.rules[].verifyImages[].failureAction`
  (it lives inside the `verifyImages` entry, NOT under `validate`, and NOT at spec level).
  Source: https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/

So both doc references are correct provided the verify-image policy puts `failureAction`
inside the `verifyImages` block (not under `validate`). The walkthrough's verifyImages row
says "(Audit)" which is consistent. Keep [verify-at-build] on the exact 1.18 schema since
Kyverno is also introducing the newer `ImageValidatingPolicy` type
(https://kyverno.io/docs/policy-types/image-validating-policy/); confirm the deployed
policy uses the ClusterPolicy `verifyImages` form, not the new CRD, or update the doc to name
whichever is shipped.

## Claim 5: Falco Talon kubernetes:terminate kills the pod on a matched rule; Falcosidekick forwards to :2803

Verdict: CONFIRMED.

- Falco Talon is the falcosecurity response engine; the actionner that kills a pod is named
  exactly `kubernetes:terminate`, with parameters `grace_period_seconds`, `ignore_daemonsets`,
  `ignore_statefulsets`, `ignore_standalone_pods`, `min_healthy_replicas`. Source:
  https://docs.falco-talon.org/docs/actionners/list/
- Falcosidekick forwards events to Talon at port 2803; the documented wiring is
  `falcosidekick.config.talon.address=http://falco-talon:2803`, and 2803 is Talon's default
  listen port. Source: https://github.com/falcosecurity/falco-talon

Both the action name and the port are accurate as written.

## Claim 6: OTel content-capture puts a scrubbed value into a trace span; a collector redaction/attributes processor scrubs before export

Verdict: CONFIRMED.

- The OpenTelemetry Collector handles sensitive data in flight via processors between
  receivers and exporters. The `attributes` processor can `delete`/`update`/`hash` specific
  attributes; the `redaction` processor deletes span/log/metric attributes not on an allow
  list and masks values matching a blocked-value list (regex). These run before export to a
  backend. Sources: https://opentelemetry.io/docs/security/handling-sensitive-data/ and
  https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/redactionprocessor/README.md

The doc's "second sink" framing (content-capture lands the sentinel in a span; symmetric
collector-side redaction is the fix) is accurate. The governance-map's "content-capture
default OFF" is correct in spirit: instrumentation libraries gate sensitive content capture
behind opt-in settings (for example `OTEL_INSTRUMENTATION_*_CAPTURE_CONTENT` style flags and
GenAI content-capture being off by default), so capture has to be deliberately enabled to
create the leak. Source: https://opentelemetry.io/docs/security/config-best-practices/

---

## Summary of corrections / nuance

- No claim was found false. All six are CONFIRMED against primary sources.
- Claim 1: state that the egress allow targets the Bedrock endpoint ENI IP range, not a
  hostname; NetworkPolicy is L3/L4 with no DNS/L7 awareness. The "S3 blocked" result assumes
  S3 is reached over the public internet, not via an S3 VPC/gateway endpoint.
- Claim 4: keep `failureAction` inside the `verifyImages` block for the image-verify policy
  (not under `validate`, not at spec level). Confirm the shipped policy uses ClusterPolicy
  `verifyImages` and not the newer `ImageValidatingPolicy` CRD. Leave [verify-at-build].
- Claims 2, 3, 5, 6: accurate as written; minor precision notes recorded above.
