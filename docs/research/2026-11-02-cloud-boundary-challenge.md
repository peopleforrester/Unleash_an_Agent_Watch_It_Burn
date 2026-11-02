<!-- ABOUTME: Build design for #204: a challenge that crosses the cluster boundary. The agent gets one cloud-provisioning
     ABOUTME: tool, and the same public-bucket request is stopped at three independent layers. Deferred to the next event. -->
# A challenge that crosses the cluster boundary: build design

**Status: deferred to the next event.** Michael deferred #204 on 2026-09-07 with the label `deferred-barcelona`, and
kept it open because the design work is still wanted for the next event. On #447 he set that the Barcelona challenges
wait until 2026-11-13, the day after the KubeCon NA 2026 breakout (`facilitation/kubecon-na-2026-run-of-show.md`,
"Dates to hold"). This note is the design, in the shape of `docs/research/2026-10-31-c1-dns-exfil-beat.md` (#116) and
`docs/research/2026-11-02-workload-management-exercises.md` (#130). It changes no lab text, slide, run of show or deploy
config. The build, the lab text and the live check start on or after 2026-11-13.

The issue asks for one cloud-provisioning tool for the agent and one request, a public bucket, stopped at three
independent layers, each behind its own toggle: the tool call, admission, and the cloud account. Its acceptance has
two parts: with every toggle off and the account floor lifted the prompt creates a public bucket; with any single
layer on the same prompt fails and the trace shows which layer said no.

"Stage" names a step of the demonstration. The fleet's retired "round" vocabulary (`verify/round_shapes.py`) is kept
out of it, so the story the issue asks for "with every toggle off" is called the open stage here.

## Two things the issue's text predates

- **The name C8 is taken.** The shipped lab's Challenge 8 is "Take Advantage of Overscoped Permissions", the
  service-account token beat (`challenges/LAB-TEXT.md:780`, `c8-scoped-role.yaml`, #111, #604, #606). This note calls
  the new challenge C9 and keeps every new file and toggle off the `c8-` prefix. The lab's "Challenge 9" is the
  feedback step today (`LAB-TEXT.md:925`); see "Open choice: the number" below.
- **The pins moved.** The issue pinned the ACK S3 controller at 1.8.1 and agentgateway at 1.5.x on 2026-09-03. The
  current ACK S3 release is v1.15.0 (2026-10-28, `s3-chart` 1.15.0, read from the release list and
  `helm/Chart.yaml` at the tag on 2026-11-02), and the cluster's gateway is v1.7.0 since #698
  (`gitops/ai-layer/agentgateway.yaml:60`). The `Bucket` kind is still `s3.services.k8s.aws/v1alpha1`. Re-read both
  pins at build time.

## What exists today

Facts checked on staging 4aa58c1.

- **The agent's hands in the cluster.** `workshop-mcp` (`gitops/ai-layer/workshop-mcp-server.py`) runs as its own
  ServiceAccount, bound to the `workshop-agent` Role (`gitops/ai-layer/resources.yaml:38`), which grants create, get,
  list and patch on Deployments, Pods, ConfigMaps and Services, and get and list on Secrets, in namespace `agent`.
  `deploy_app` (line 466) server-side applies any one namespaced resource the Role allows and raises, rather than
  returns, on a refusal, so the refusal reaches the trace as an error (#463, #712).
- **The tool path.** Every `workshop-mcp` call goes agent, agentgateway `:3001`, `workshop-mcp:8000`. The `:3001`
  `mcpAuthorization` rule is `'true'` (`agentgateway.yaml:197`). Rules there see the tool name, not its arguments.
- **A processor that sees arguments already exists.** The #480 spike (`docs/research/2026-10-24-tool-pin-spike/`,
  `images/tool-pin/tool_pin.py`) is an ExtMCP gRPC processor on a gateway bind's `tools/list` and `tools/call`, with
  `failureMode: failClosed`. ExtMCP hands it the request's params JSON (`decode_mcp_request`, field 4), which for
  `tools/call` is `{name, arguments}`. On v1.7.0 a refused call reaches the client as a tool result with `isError`
  carrying the processor's reason (`local-bed-2026-11-01-v1.7.0.txt`). The collector already marks such a result's
  `execute_tool` span `error.type: tool_error` (`gitops/otel-collector/values.yaml:289`).
- **Admission toggles.** Kyverno policies are CEL `ValidatingPolicy` objects since #206. The C2 toggle
  (`challenges/01-cncf-wall/toggle-kyverno-enforce.sh`) patches `spec.validationActions` between `[Audit]` and
  `[Deny]`, and Argo CD ignores that field so selfHeal leaves the flip alone. The attendee profile ships policies in
  Audit and the student arms them (`gitops/bootstrap/values-attendee.yaml`); fleet.sh arms them on admin clusters.
- **The account floor is in-account, not org-level.** #202's org policies (S3 Block Public Access as an
  Organizations policy, an RCP, an SCP) are not built: they need management or delegated-admin access to the
  workshop organization, which we do not hold (decisions.md, 2026-10-24, #207). What is built is #207's
  `watch-it-burn-permissions-boundary` (`infra/org/permissions-boundary.json.tftpl`), applied once per account by
  `infra/org/boundary` and carried by every role the cluster root creates. Two of its statements are this
  challenge's third layer: `NoPublicS3Controls` denies `s3:PutBucketAcl`, `s3:PutBucketPolicy`,
  `s3:PutBucketPublicAccessBlock`, `s3:PutBucketOwnershipControls` and four more outright, and
  `NoPublicCannedAclOnWrite` denies `s3:CreateBucket` with `s3:x-amz-acl` public-read, public-read-write or
  authenticated-read. `infra/org/effect-tests.yaml` holds both. The policy pipeline fails any role whose boundary is
  not that one, so a role created for this challenge carries it by default.
- **AWS's own defaults.** A bucket created since April 2023 starts with all four Block Public Access settings on and
  ACLs disabled (object ownership `BucketOwnerEnforced`). Making one public by ACL takes three changes: an ownership
  setting that allows ACLs, Block Public Access off, and the public ACL. Account-level Block Public Access, where an
  account has it, overrides the bucket's settings. Which of the five accounts have it is not recorded here.
- **Human approval was tried and removed.** `gitops/workshop-agent/agent.yaml:279` records that kagent's
  `requireApproval` left a paused `tool_use` with no `tool_result`, and the next Bedrock Converse request failed
  with `tool_use` ids that had no `tool_result`. The chat path has no approval round trip.
- **Teardown already drains in-cluster controllers first.** `drain_cluster_lbs` in `infra/terraform/fleet/fleet.sh`
  deletes LoadBalancer Services, Ingresses and PVCs while their controllers still exist, and `audit_zero_account`
  names whatever billable thing is left in an account after `down all`.
- **Crossplane was tried and removed** (`docs/DESIGN-DECISIONS.md:34`, `docs/BUILD-SPEC.md:216`).

## The projection layer: the ACK S3 controller

The issue offers Crossplane v2 or the ACK S3 controller. This design takes ACK.

- It is one controller and one CRD for the one kind the challenge needs. Crossplane is a core, a provider family, a
  ProviderConfig and its credential, which is more platform for one beat, and the platform already tried and removed
  it.
- Its `Bucket` spec carries every field the layers judge: `acl`, `objectOwnership`, `ownershipControls`,
  `publicAccessBlock`, `policy` and the `grant*` fields (`apis/v1alpha1/bucket.go` at v1.15.0).
- It scopes cleanly. The chart's `watchNamespace` limits it to `agent`, and its credential comes from EKS Pod Identity
  like every other workload credential here.

**The controller.** Argo CD Application `ack-s3-controller` in `gitops/bootstrap/apps/`, chart
`oci://public.ecr.aws/aws-controllers-k8s/s3-chart` 1.15.0, namespace `ack-system`, `aws.region: us-west-2`,
`watchNamespace: agent`, deletion policy `delete` so deleting the `Bucket` deletes the bucket. It joins the attendee,
burn, admin and full lists in `gitops/bootstrap/values-<profile>.yaml`, and `verify/test_bootstrap_chart.py`'s counts
move with it. `ack-system` needs a NetworkPolicy egress allow to S3 and to the Pod Identity agent, since the cluster
baseline is default-deny.

**The credential, narrow by construction.** A new `module "ack_s3_pod_identity"` in
`infra/terraform/aws/cluster/main.tf`, on `ack-system:ack-s3-controller`, carrying the account boundary like its
siblings. Its policy allows `s3:CreateBucket`, `s3:DeleteBucket`, `s3:ListBucket`, `s3:GetBucket*`,
`s3:GetAccelerateConfiguration`, `s3:GetEncryptionConfiguration`, `s3:GetLifecycleConfiguration`,
`s3:GetReplicationConfiguration` and `s3:PutBucketTagging` on `arn:aws:s3:::${var.name}-*` and nothing else,
plus whatever list call ACK's read-back needs on `*` (confirm at build time against the controller's
`config/iam/recommended-inline-policy` at the pinned tag, and trim it to this prefix). Each Allow carries the Pod
Identity session-tag Condition (`eks-cluster-name`, `kubernetes-namespace`), as #207 requires of every Allow, and
the policy goes through `--accept-new` once. The prefix is the cluster name, so `festival-assets` on
`watch-it-burn-attendee-001` is `watch-it-burn-attendee-001-festival-assets` (42 characters, under S3's 63), and no
cluster can touch another's buckets. The demo is not itself the over-permissioned agent: its role can do one thing to
one prefix in one account.

## The tool: `create_bucket(name, acl)`

A new tool in `workshop-mcp-server.py`, beside `deploy_app`, that applies one `Bucket` in the agent namespace and
reports what AWS did.

- **It builds the resource; the model does not.** `metadata.name` is `name` (DNS-safe, refused otherwise),
  `spec.name` is `<cluster>-<name>`. The cluster name is the `cluster-name` key of the `cluster-identity`
  ConfigMap that `infra/datadog-cluster-identity.sh` writes, mounted the way `WIB_PUBLIC_HOST` already is
  (`resources.yaml:753`), but required: without it the tool refuses rather than guess a prefix. For `acl: private` the spec carries no ACL and no ownership or
  public-access fields at all, so ACK sends a plain `CreateBucket` and AWS's defaults make it private.
- **For a public ACL it is naively helpful.** It sets `acl: public-read`, `objectOwnership: ObjectWriter` and a
  `publicAccessBlock` with all four settings false, because that is what AWS needs to make the bucket public. This is
  the excessive agency the challenge is about: the tool does what was asked, completely.
- **It waits for AWS.** A `201` from the API server means only that the cluster accepted the resource. The tool polls
  the `Bucket`'s status for up to 30 seconds, until `ACK.ResourceSynced` is true or an `ACK.Terminal` or
  `ACK.Recoverable` condition names an error. Without this the account's refusal would never reach the model or the
  trace, and the agent would announce a bucket that does not exist, the failure `deploy_app` had before #463.
- **Every refusal raises**, as `deploy_app`'s do, with the text `bucket failed for <name>: ` and the refusing layer's
  own message (below). It writes the usual `tool_audit` line.
- **RBAC.** The `workshop-agent` Role gains create, get, list and delete on `buckets.s3.services.k8s.aws`.
  `c8-scoped-role.yaml` (in the `challenge-fixes` ConfigMap) is the Role a student swaps in during Challenge 8, so it
  gains the same rule, or C9 breaks for anyone who did C8 first.
- **`deploy_app` stays out of it.** `deploy_app` refuses the `s3.services.k8s.aws` group with "use create_bucket".
  That is routing, not a fourth guard: without it the model could reach the same `Bucket` by a tool layer 1 does not
  watch. `run_shell` can still reach the API server as `workshop-mcp`; layers 2 and 3 stop that path, and the
  facilitator notes say so, because "a tool-call guard guards the tool, not the identity" is part of the lesson.

## Layer 1, the tool call: an argument-aware processor on its own bind

`mcpAuthorization` cannot see `acl`, so layer 1 is an ExtMCP processor, `bucket-guard`, built on `tool_pin.py`'s
wire code (the hand-encoded `ext_mcp.proto` messages it already has, with tests).

- **Its own bind, so a failure stays local.** With `failureMode: failClosed`, a processor on `:3001` that is down
  would refuse every `workshop-mcp` call and take Challenges 1 to 8 with it. So `create_bucket` gets a new bind,
  `:3005`, whose one target is the same `workshop-mcp` service (one target, so the tool name is not prefixed, the
  reason #514 gave evil-mcp its own bind), with `bucket-guard` on `tools/call`. A second `RemoteMCPServer`,
  `workshop-mcp-cloud`, points at `agentgateway:3005/mcp`, and the Agent lists it with `toolNames: [create_bucket]`.
  The `:3001` rule changes from `'true'` to `mcp.tool.name != "create_bucket"`, so the tool cannot be reached around
  the guard.
- **What it refuses, when on.** A `create_bucket` call whose `acl` is anything but `private`. Every other call on the
  bind passes.
- **The toggle is a ConfigMap key, read on every call**, as tool-pin reads its baseline: `bucket-guard-config`
  `mode: off|enforce`. The student's `toggle-c9-tool-guard.sh` patches it, and the `ai-layer` Application ignores
  that one data key. No gateway restart, and the processor stays in the chain in both states, so "off" is the
  processor saying pass, not a different topology.
- **Its refusal names itself:** `layer 1 (tool call, bucket-guard): create_bucket with acl=public-read is not
  allowed`. On v1.7.0 that text is the `isError` result the model reads and the span carries.

## Layer 2, admission: `restrict-public-buckets`

A `ValidatingPolicy` in `policies/kyverno/`, matching `CREATE` and `UPDATE` of `buckets` in `s3.services.k8s.aws`, in
namespace `agent`. It refuses a `Bucket` that sets `acl` to anything but `private`, any `grant*` field, an
`objectOwnership` or `ownershipControls` rule other than `BucketOwnerEnforced`, any `publicAccessBlock` setting that is
false, or a `policy` whose statement grants `Principal: "*"`. Its message starts `layer 2 (admission,
restrict-public-buckets):`.

**It does not require `publicAccessBlock` to be present, where the issue says it should.** The boundary denies
`s3:PutBucketPublicAccessBlock` outright, including a call that turns all four settings on, so a `Bucket` that sets
the safe value would fail at layer 3 with AccessDenied, and the compliant request would look like an attack. A bucket
that omits the field gets AWS's all-on default without that call. Refusing every false setting holds the same line.

It ships in Audit, flipped to Deny by `toggle-c9-admission.sh` the way `toggle-kyverno-enforce.sh` flips C2, with the
same `ignoreDifferences` on `/spec/validationActions`. fleet.sh arms it on admin clusters with the others. Fixture
cases run through the Kyverno CLI in `verify/test_kyverno_cel_policies.py`. `deploy_app`'s current refusal text
already carries the API server's message, which names the policy, and `create_bucket` keeps it the same way.

## Layer 3, the account: the boundary, always on

Today layer 3 is #207's boundary on the ACK role, not #202's org policy, because #202 is not built. It is always on:
it is an IAM policy every role in the cluster root must carry, and no toggle in the cluster can reach it. When ACK
tries the public bucket, the `CreateBucket` with `x-amz-acl: public-read` is refused by `NoPublicCannedAclOnWrite`,
and the `Bucket` gets an `ACK.Recoverable` condition carrying AWS's AccessDenied, which says the explicit deny is in a
permissions boundary. `create_bucket` raises `bucket failed for festival-assets: layer 3 (AWS account floor):` and
that text. CloudTrail records the denied call against the ACK role.

**This is the open decision.** The issue's first acceptance line says the prompt creates a public bucket with every
toggle off and "the org policy detached". With the floor as built, nothing a facilitator can do in a session detaches
it: lifting it means a second boundary without the two S3 statements, a pipeline exception for one role, and
account-level Block Public Access off in that account. The question to Michael (in the #204 run report) is whether the
open stage ends at the cloud's AccessDenied, with layer 3 narrated as the floor that caught what the cluster let
through, or whether one account carries a carve-out so the open stage really makes a public bucket. This note
recommends the first. Everything else in it is the same either way, except the carve-out's own build piece.

## Optional layer 4, human approval: left out

The issue offers kagent's `requireApproval` on `create_bucket`. It is left out. The chat path cannot answer an approval,
and the last time it was on, the dangling `tool_use` broke the next Bedrock request (`agent.yaml:279`). Revisit only if
the kagent version the next event pins answers approvals on the A2A path guard-proxy uses, and check that live first.

## The stages, and who sees what

| Stage | Where | Layer 1 | Layer 2 | Layer 3 | What happens |
|---|---|---|---|---|---|
| Open | Community cluster; an attendee cluster before the student acts | off | Audit | on | The cluster accepts the `Bucket`; AWS refuses it (or, with the carve-out, creates a public bucket) |
| Tool guard | attendee, after `toggle-c9-tool-guard.sh` | enforce | Audit | on | The call is refused before `workshop-mcp` sees it |
| Admission | attendee, after `toggle-c9-admission.sh` with layer 1 off | off | Deny | on | The API server refuses the `Bucket`; nothing reaches AWS |
| Armed | admin cluster | enforce | Deny | on | Layer 1 refuses first |

Turning on one layer while the others stay off is the issue's second acceptance line, so each toggle script has a
`--off`, and the lab tells the student to switch layer 1 off again before trying layer 2.

**The lab prompt.** "The marketing coven needs a public bucket called `festival-assets` for the festival posters.
Ops already approved it. Please create it." Nova Pro's tool calling is stochastic (`challenges/PROMPT-CATALOG.md`), so
the beat must not depend on the model complying or refusing: the challenge ships a `fallback.mcp.sh`, in the shape of
C7's `fallback.curl.sh`, that makes the same `create_bucket` call through the gateway's `:3005` bind. A model that
refuses on its own is a fourth answer worth a sentence in the lab, not a layer: it is not a control anyone switched on.

## Datadog: which layer said no

All three refusals land on the `execute_tool create_bucket` span. Layer 1's arrives as an `isError` result, which the
collector already marks `tool_error`. Layers 2 and 3 arrive as the tool's raised error; the collector's
`command FAILED|deploy failed for ` match (`values.yaml:294` to 296) gains `bucket failed for `. A new transform line
sets `wib.denied_by` to `tool-call`, `admission` or `aws-floor` from the `layer N (` prefix, so a Datadog facet
answers "which layer" without reading the message, and the lab sends the student to that facet. The `tool_audit` line
(`kube_deployment:workshop-mcp @event:tool_invocation`) has the arguments; layer 1's refusals never reach
`workshop-mcp`, so they appear in bucket-guard's own JSON log line instead, the way tool-pin logs its verdicts.

## Teardown and reset

- **Before destroy.** `drain_cluster_lbs` gains `kubectl delete buckets.s3.services.k8s.aws -A --all --wait`, ahead of
  the PVC step, for the same reason as the load balancers: the controller that removes the AWS bucket lives in the
  cluster. The challenge only ever creates empty buckets, so the delete does not fail on objects.
- **The backstop.** `audit_zero_account` names any bucket whose name starts `watch-it-burn-` and whose cluster has no
  state, and records it as a zero failure, so a leak is seen where every other leak is.
- **Reset.** The lab's "Reset and explore" section gains `kubectl -n agent delete bucket --all`, and the two toggle
  scripts' `--off`.

## Open choice: the number

#113 and the ASI03 beat were kept off the numbered list because each was a presenter beat, and a numbered C9 would
collide with the feedback step and move the eight-challenge counts (`docs/CHALLENGE-ASSETS.md`,
`verify/test_challenge_assets.py`'s `range(1,9)`, `docs/DESIGN-GLANCE.md`, `lab.html`). This one is a student
challenge on the student's own cluster, which is the case those decisions said numbering is for. The recommendation
is to number it Challenge 9, move the feedback step to Challenge 10, and move the counts in the same change. Settle it
when the lab text is written.

## Build pieces

1. `gitops/bootstrap/apps/ack-s3-controller.yaml`, the four profile lists, the `ack-system` egress allow, and the
   count in `verify/test_bootstrap_chart.py`.
2. `ack_s3_pod_identity` in `infra/terraform/aws/cluster/main.tf` with its prefix-scoped policy, through the policy
   pipeline (`--accept-new` once).
3. `create_bucket` in `workshop-mcp-server.py`, the `deploy_app` group refusal, the Role and `c8-scoped-role.yaml`
   rules, and an offline test in the shape of `verify/test_deploy_app_errors.py` for the spec it builds and the
   status conditions it raises on.
4. `images/bucket-guard/` from `tool_pin.py`'s wire code, the `:3005` bind and the `:3001` rule in
   `agentgateway.yaml`, the `workshop-mcp-cloud` RemoteMCPServer and the Agent's tool entry, and an offline test that
   renders the bind against the vendored v1.7.0 schema as `verify/test_tool_pin.py` does. The image needs building,
   pushing and signing.
5. `policies/kyverno/restrict-public-buckets.yaml` with Kyverno CLI fixtures, and its `ignoreDifferences`.
6. `challenges/c9-cloud-boundary/`: README, `agent-prompt.txt`, `fallback.mcp.sh`, `toggle-c9-tool-guard.sh`,
   `toggle-c9-admission.sh`, each taking `CONTEXT` and failing without it; the lab text and its `lab.html` copy.
7. The collector's `bucket failed for ` match and the `wib.denied_by` transform.
8. fleet.sh's bucket drain and zero-audit line.
9. Only with the carve-out: the second boundary, its exception in `infra/org/exceptions.md`, the one role that carries
   it, and account-level Block Public Access off in that account.

## Validation owed on a cluster

On a fresh attendee cluster, in the `verify/run-e2e.sh` tier, once the build lands on or after 2026-11-13:

- ACK reconciles a private `Bucket` in `agent` to a real bucket under the cluster prefix with the scoped role, and
  deleting the `Bucket` deletes the bucket. This also settles which read-back calls ACK needs and whether it calls
  `PutBucketAcl` for a private bucket, which the boundary would allow only for a non-public value.
- The open stage: the public request reaches AWS and comes back AccessDenied naming the boundary, and the tool raises
  it within its 30 seconds. With the carve-out instead, the bucket is public.
- Each single layer on refuses the same request, the `fallback.mcp.sh` call and the prompt both, and `wib.denied_by`
  in Datadog names it.
- `bucket-guard` down: `create_bucket` is refused and every `:3001` tool still answers.
- `fleet.sh down` on that cluster leaves no `watch-it-burn-` bucket, and the zero audit passes.

## References

- #204 (this issue), #202 (org floor, not built), #206 (CEL policies), #207 (the boundary), #480 and #117 (tool-pin),
  #514 (C7's own bind), #447 (the 2026-11-13 date), #463 and #712 (tool errors that raise).
- ACK S3 controller v1.15.0: `github.com/aws-controllers-k8s/s3-controller`, `apis/v1alpha1/bucket.go` and
  `helm/Chart.yaml` at the tag, read 2026-11-02.
