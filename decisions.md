# Decisions Log

Append-only audit trail of approvals, amendments, backward steps, and conditional-skip
rationales for the lifecycle. See [[state-persistence]] for the schema.

Note: this repo already keeps a rich technical decision + verification log at
`docs/DECISION-LOG.md` (PRD approvals/amendments, the model-refusal rerun evidence, the
Nova A/B). That remains the detailed record. This file carries lifecycle phase-transition
entries from init-state forward.

## 2026-07-05 · init · state persistence initialized

init-state migrated the pre-lifecycle `PROJECT_STATE.md` to the lifecycle schema (header
prepended, 812-line body preserved). Deduced Phase 1.3 (PRD 35 sealed at
2026-07-03T19:59:22Z, sha256 5e110e425e70; Phase 2 M1 pending). Prior lifecycle events
(PRD 35 approval / amendment / re-approval) are recorded in `docs/DECISION-LOG.md` and are
not re-imported here.

## 2026-07-07 · skip · §4.6-d (per-cluster model tier) deferred

Michael deferred §4.6-d (per-cluster tier -> Agent modelConfig patch), the last of PRD 35 M1's
sub-pieces. It is a CONDITIONAL skip with a recorded reason (not a silent drop):

- "Nova everywhere" is the gitops default, so per-cluster tier only serves the OPTIONAL cost-race
  demo, which is not currently wanted.
- Both viable implementations wrangle ArgoCD reconciliation: (a) live-patch = suspend the ai-layer
  app's selfHeal, patch the Agent modelConfig, bounce the pod; (b) the PRD-preferred "overlay" =
  patch the ai-layer ArgoCD Application's kustomize.patches per cluster, which the app-of-apps parent
  reverts unless given ignoreDifferences. Neither is friction-free, so the PRD's "not a live patch"
  preference did not survive contact with the shared-gitops + app-of-apps + selfHeal architecture.
- The tier column stays plumbed (roster + dry-run show it) but is inert until this lands.

Consequence: PRD 35 M1 is COMPLETE at 4 of 5 sub-pieces (IMDS pin, §4.6 core, AWS root relocation,
provider dispatch — all on main). Revisit §4.6-d only if the cost-race demo is wanted; the live-patch
route is the recommended implementation, and a one-line PRD note would capture that the overlay
preference is impractical here. The sealed PRD 35 body is unchanged (this is a documented deferral in
the audit log, not a plan amendment).

## 2026-09-03T18:20:00Z · 2.2 · Rejected approaches for rolling a proxy.py change

### REJECTED: Per-generator `options: disableNameSuffixHash: false` on `guard-proxy-src`
**Why:** kustomize v5.8.1 lets the top-level `generatorOptions` win over a per-generator
`options:` block. Confirmed with a minimal two-generator build: one generator asking for a
hash and one not both produced unsuffixed names. The field is accepted and silently has no
effect, which is worse than an error.
**Status:** Permanent for kustomize v5.x as shipped in kubectl v1.37.
**Do not suggest:** moving the `options:` key, reordering the generators, or setting
`disableNameSuffixHash: false` on the generator alone. All three hit the same precedence.

### REJECTED: Drop the global `generatorOptions.disableNameSuffixHash`
**Why:** It would hash every generated ConfigMap in the ai-layer bundle, not just the
proxy source, days before Portland. Kustomize rewrites the references it owns, but the
blast radius covers `evil-mcp-src`, `workshop-mcp-src`, `chat-ui-src` and the rest, and the
stable names are relied on by `agent/gateway/guard-proxy/guard-proxy.yaml` and by the
`kubectl create configmap` line documented in it.
**Status:** Revisit between events, when a wider rename can be tested on one cluster first.
**Do not suggest:** doing it as part of a security fix. The two changes have nothing to do
with each other and bundling them makes both harder to revert.

### REJECTED: `kubectl rollout restart` across the fleet
**Why:** The fleet's admission policy rejects direct mutation by a non-ArgoCD principal, and
it is right to. Eleven of thirteen clusters refused; `r1-1` and `r1-2` accepted, which is
itself worth a look since the policy is evidently not uniform.
**Status:** Permanent. Changes travel through Git.
**Do not suggest:** a one-off restart to "just get it live", including via a Job or a
scaled-to-zero-and-back. The policy exists so the running state matches the repo.

**Chosen:** a `checksum/proxy-py` annotation on the guard-proxy pod template, bumped in the
same commit as a proxy.py change, with `verify/test_proxy_checksum.py` failing when the two
disagree. Keeps the stable ConfigMap names, makes the rollout automatic once the annotation
moves, and turns a forgotten bump into a red test instead of a silent no-op in the room.

## 2026-09-06T13:30:00Z · 2.2 · Supersedes "Drop the global generatorOptions.disableNameSuffixHash" (rejected 2026-09-03)

The 2026-09-03 rejection was conditional: "Revisit between events, when a wider rename can be tested
on one cluster first." The condition changed on 2026-09-06: the owner directed that every fix be wired
so it needs no manual step, four freshly rebuilt clusters exist to prove the rename on before Sunday's
full rebuild, and the one runtime reliance the rejection named (`agent/gateway/guard-proxy/guard-proxy.yaml`)
is a hand-apply manifest nothing in gitops, infra or verify applies. The hash is now ON for the whole
ai-layer bundle; `verify/test_ai_layer_rollout.py` asserts it, and asserts that editing lab.html changes
the console pod template. The `checksum/proxy-py` annotation and its test stay: `/controls` reports that
checksum in the room, which is a different job from rolling the pod. Issue #252.

## 2026-09-17T15:40:00Z · 1.2 · Gitea is not part of this IDP, and the reason was never written down

Asked why the IDP has no Gitea. It has none, and searching this repo for "gitea" returns nothing at
all: not a manifest, not a note, not a rejection. The absence was undocumented, which is the actual
defect here. A decision nobody recorded gets re-litigated, and this one had already reached the point
of being asked.

**What is true.** The sister project (`events/Packt-agentic-devops`) does run Gitea, at
`solution/platform/1-foundation/gitea`, beside openbao, argo-rollouts and argo-workflows. Its own
ABOUTME states the purpose exactly:

> in-cluster Gitea installed at PROVISIONING time, so ArgoCD can source the platform manifests from
> inside the cluster instead of from GitHub

The port commit that founded this platform (`6880677`, "Port KubeAuto IDP foundation") brought **zero**
Gitea files.

### REJECTED: add Gitea to the Watch It Burn IDP

**Why:** it solves a problem this workshop does not have. Gitea exists in the sister project because
its students sync the platform from **inside** the cluster, editing manifests in an in-cluster git
service as a teaching beat. Our Argo CD sources directly from GitHub through the `witb-repo` secret
and a `gh` token, and no challenge asks a student to commit anything. Adding Gitea would add a
StatefulSet, a database, a credential and a sync path that nothing in the eight challenges exercises,
on a platform already at 38 Applications that must build in 15 to 25 minutes, 50 times over.

**Status:** Revisit when a challenge genuinely needs in-cluster git. The obvious candidate is a
supply-chain or GitOps-tampering beat, where the student modifies a manifest and watches Argo CD or
the drift policy react. That is a real workshop idea and Gitea would be the right way to build it. It
does not exist today.

**Do not suggest:** adding Gitea "for completeness" or because the sister repo has it; mirroring the
GitHub repo into the cluster purely to remove the GitHub dependency (the token path works and is one
secret); or treating its absence as an oversight from the port. The port was manifests-only by
design, and the same mechanism is why `kubeauto-unicorn-party:2.0.2` did not come across either: its
content lived inside an image in a foreign ECR registry rather than in a manifest.

## 2026-10-05T00:00:00Z · 1.3 · Component repos, the guard-proxy rewrite, and the upstream mirror

Five decisions from Michael, taken one at a time on 2026-10-05, closing the open questions on #411,
#412 and #416.

**Component repos (#411).** guard-proxy and the LLM Guard offline image each get their own repo,
wired back here as git submodules (submodules chosen 2026-09-24):

| Component | Repo | Visibility |
|---|---|---|
| guard-proxy | `peopleforrester/guard-proxy-agenticburn` | public |
| LLM Guard offline image | `peopleforrester/llm-guard-cpu-offline` | public |

Both public, matching this repo and the images, which are already anonymously pullable. Neither holds
a secret: the cosign signing key lives in mrf-secrets.

**guard-proxy is rewritten in Go (#412).** Michael's reasoning: it is going to become a product
quickly, and Go has better libraries for this than Rust. This reverses the recommendation in the
2026-09-22 research synthesis, which was to keep it in Python as the workshop's demo object; that
recommendation assumed it stayed a teaching prop, and it does not.

The rewrite also folds in what LiteLLM does better. The research established that LiteLLM's
pre-call budget reservation (estimate the request's maximum cost, reserve it, reject before the
provider is called) is a stronger mechanism than guard-proxy's post-hoc metering, which blocks only
the next request. That gap analysis is the first deliverable of the rewrite, ahead of any Go code.

**Upstream mirror (#416).** `peopleforrester/llm-guard-upstream-mirror`, private. A backup so builds
survive if Protect AI deletes the archived repo; it invites nothing and promises nothing. The public
offering is `llm-guard-cpu-offline`. Forking and maintaining the library (decision B) stays declined
on the cost measured in the 2026-09-22 research.

## 2026-10-11T00:00:00Z · 1.2 · PRD #412 open questions answered

Michael answered the five open questions in `prds/412-guard-proxy-go-rewrite.md`, one at a time:

1. Token counting is exact, via Bedrock `CountTokens`, with no estimator fallback: a request whose
   count cannot be produced is refused.
2. Budget state persists across restarts in an embedded store (SQLite or bbolt), so a restart cannot
   reset a budget. Still no Postgres.
3. The workshop apparatus (live prompt feed, `/controls`, `/toggle`) ships in the product. Design
   consequence recorded in the PRD: the prompt feed is off by default and the admin API is
   authenticated, because the feed streams user prompts.
4. The code fast-edit loop is retired. Code reaches a cluster only as a signed, digest-pinned image;
   behavior still changes live through the YAML config and the toggles.
5. License is Apache-2.0. `proxy.py` keeps its MIT notice, because its LICENSE names Michael Forrester
   and Whitney Lee as holders and relicensing it would need both. The Go code is new and is
   Apache-2.0 from its first commit.

The plan as a whole still needs approval (1.3) before any Go is written.

## 2026-10-10T23:36:09Z · 1.3 · PRD #412 approved: guard-proxy rewritten in Go

Approved-by: Michael@2026-10-10T23:36:09Z
Plan: `prds/412-guard-proxy-go-rewrite.md` (sha256:3a5aa82f1a71f5c30360c684aa873704df14374e9468b63e50bc7d5fd118ac73)

Approved as written, after Michael answered its five open questions one at a time and the known bugs
on the new proxy's path were classified (#382 and #320 deferred against a Python baseline, #333 a
prerequisite for M7). The plan is now read-only; changes go through an amendment.

Work starts at M0: a black-box HTTP conformance suite that must pass against the Python proxy before
any Go is written. It lives in guard-proxy-agenticburn, beside the implementation it constrains.

## 2026-10-11T00:29:21Z · 2.1 · PRD #412 M0 complete: conformance suite pinned to proxy.py

The suite lives in guard-proxy-agenticburn `conformance/`, beside the code it constrains. It runs
any implementation as a subprocess through `GUARD_PROXY_CMD` against real local fakes for the agent
and the LLM Guard API, and asserts only client-observable behavior. Result: 163 tests green against
proxy.py, CI green on c72cc28, promoted to that repo's main.

Proof that it constrains anything: `mutation_check.py` breaks proxy.py 16 ways (fail-open default,
case-sensitive block-list, ignored classifier verdict, scrub gaps, cap and rate-limit off-by-ones,
session-blind budget, wrong price, probe in feed, no retries, CORS echo, credential forwarding).
All 16 are caught. The first run let the cost-cap off-by-one escape; the boundary tests that close
it were added, and a budget-cap mutant with them.

Scope clarifications, within the sealed plan rather than amendments:
- Telemetry assertions are deferred to M5, whose acceptance is already a recorded Python baseline.
  The Python proxy only emits spans under the OTel SDK the cluster injects, so the harness cannot
  observe them without reproducing that injection.
- `/controls` is covered for the no-credentials case only. proxy.py hardcodes the API host; the Go
  implementation adds an endpoint override and the suite extends then.

Defects found while pinning behavior are asserted as they stand (tests ending `_today`) and filed on
guard-proxy-agenticburn: #1 (a failed reasoning-only retry writes two responses and drops the usable
reply), #2 (raw `<thinking></thinking>` tags reach the student), #3 (retry tokens are never metered,
so `/cost` and both caps undercount), #4 (feed moderation misses capitalized terms). Per the
fix-shared-bugs rule these sit on the Go proxy's path. #3 bears directly on the M3 claim that a
single request cannot exceed the cap, so it must be fixed in both implementations before M3 is
accepted. #1, #2 and #4 can be fixed in either order, as long as proxy.py and its `_today` test
change together.

## 2026-10-14T00:00:00Z · 2.2 · PRD #412 M1 complete: Go skeleton passes the pass-through conformance subset

guard-proxy-agenticburn 1874403, CI green (run 38490687225), promoted. "Pass-through cases" is now a
pytest marker, `passthrough`, on 22 tests: /guards seeding, the GET passthrough and its 502s, A2A
forwarding with every guard off, agent failures as 502 with a `forward_error` ERROR log, and OPTIONS
as 501. Each later milestone widens the selection; proxy.py always runs all 163. Choices made inside
the contract, each recorded so a later milestone does not re-derive it:
- Go 1.27.2 rather than the PRD's 1.27.1: 1.27.2 (2026-10-08) carries `net/http` security fixes. An
  upward patch, so no amendment is needed.
- The agent URL is required. proxy.py defaults to a workshop hostname; the manifests set AGENT_URL
  explicitly (resources.yaml), so nothing deployed depends on the default.
- `PROXY_TIMEOUT` becomes a total deadline (`http.Client.Timeout`). urllib's is per socket operation.
- Routes later milestones build (/chat, /cost, /prompts, /controls, /toggle) answer 501 instead of
  being forwarded to the agent as A2A traffic. `/healthz` is new and is answered locally.
- Log timestamps are RFC 3339 UTC; proxy.py writes Python's local `formatTime`. Keys and level names
  match, including WARNING.
- Licensing: Apache-2.0 in `LICENSE` for the Go code. proxy.py and `conformance/` keep MIT, moved to
  `LICENSE-MIT`, because both were committed under the MIT notice naming Michael and Whitney.
- The upstream hop is a rebuilt request on `http.Client`, not `httputil.ReverseProxy`, because the
  reference sends only the body and a JSON Content-Type.

Also closed #415 (all items done or tracked on #412 and llm-coding-workflow#182) and corrected the
state file, which still said the cosign key existed only on netcup after mrf-secrets#4 had closed.

## 2026-10-14T21:40:00Z · 2.2 · PRD #412 M2 complete on the A2A path; /chat guard cases wait for /chat

guard-proxy-agenticburn 0679083, CI green (run 38640241252), promoted. A second marker, `guards`,
covers the 22 guard cases on the A2A path: the block-list, the LLM Guard classifier, the output guard
over artifacts, agent history and status, and fail-closed or fail-open for each failure mode. The Go
build runs `-m "passthrough or guards"`, 44 tests; proxy.py still runs all 163. Choices made inside
the contract:
- **Scope.** The guard cases on `/chat` (test_chat_path.py) and the live-toggle case need the `/chat`
  route and `/toggle`, which carry per-call cost, retries and toggles from M3 and M4. They join when
  those routes do. The guard logic is shared, so they exercise the same code. Consequence: the PRD's
  "M0 through M2 is the minimum to replace the Python in the workshop" does not hold. The workshop
  needs `/chat` and `/toggle`, so the earliest replacement point is M4.
- **The output guard calls LLM Guard's `/analyze/output`, as proxy.py does.** The PRD's milestone
  says "regex output"; the regex is LLM Guard's Regex scanner, server side. A regex guard inside the
  proxy would be a new guard rather than parity, and no conformance case asks for one.
- `llm_guard.url` (or `LLM_GUARD_URL`) is required, like the agent URL; the manifests set it.
- `PROXY_FAIL_CLOSED` accepts only true or false. proxy.py treats any other value as false, so a typo
  turned fail-closed off.
- A scanner failure logs `guard_error` at WARNING. proxy.py fails, open or closed, without a log line.
- `LLM_GUARD_TOKEN` is environment only, never in the YAML; with no token no Authorization header is
  sent, instead of `Bearer ` with nothing after it.
- Guards are concrete types (a Blocklist, an LLM Guard client) rather than the PRD's Go interface.
  The interface arrives with a second implementation (Bedrock ApplyGuardrail), when its shape is known.

Correction to the prior entry: its timestamp `2026-10-14T00:00:00Z` is a placeholder. The M1 record
was committed at 2026-10-14T00:35:44Z (152485f).

## 2026-10-15T18:10:00Z · 3.3 · main fast-forwarded to 49ff76c with the CI gate skipped

On Michael's instruction, main was fast-forwarded over cd529d9 (Backstage dependency refresh) and the
guard-proxy M0 to M2 commits. No workflow covers these paths (both are path-filtered), so CI never ran.
Verified locally on 49ff76c: guard-proxy `go test ./...`, the conformance suite against proxy.py and
the Go build; Backstage on Node 24 `yarn install --immutable`, `yarn tsc`, `yarn test`,
`yarn build:backend`; and `verify/test_proxy_checksum.py`, `test_image_pins.py`, `test_readme_current.py`.

## 2026-10-24T02:04:41Z · 2.2 · PRD #412 stays as sealed; guard-proxy#3 fixed ahead of M3

Michael reviewed the two points raised at M2 and wants no change: no `/prd-amend` for the claim that
M0 to M2 can replace proxy.py (the earliest real replacement point remains M4, as recorded on
2026-10-14), and the output guard keeps calling LLM Guard /analyze/output rather than an in-proxy regex.

guard-proxy#3 fixed in proxy.py (ccdda73). Each self-heal attempt is metered as it returns, including a
first attempt whose retry fails. /cost `requests` now counts model calls rather than turns, and a
/chat turn's input_tokens, output_tokens and cost_usd cover every attempt. Rejected: metering only on
success, because a failed retry's first attempt was still billed.

## 2026-10-24T04:50:43Z · 2.2 · Per-agent tool audit trail ported from the sister repo (#190)

`gitops/ai-layer/tool_audit.py` writes a `pre` and a `post` JSON line per workshop-mcp tool call, tagged
`agent_identity` from the `X-Agent-Identity` header the Agent CR sets with `headersFrom`. Only the hook
was ported; the sister's permission block (`bypassPermissions`) was not. Two departures from the sister's
`audit.sh`, both deliberate:

### REJECTED: logging the tool result, as the sister logs `tool_response`
**Why:** Our results are the leaked values (the recipe, the CEO's record, the sentinels), and every
container log also goes to Datadog (`containerCollectAll`), outside the span redaction the observability
act teaches. The record keeps the arguments, clipped, and the result's size.
**Do not suggest:** adding the result "for completeness". Attribution needs who, what and in what order,
and the arguments carry the attack.

### REJECTED: auditing inside evil-mcp-shim
**Why:** The shim stays dark for the reason recorded on #18 (PROGRESS.md, 2026-06-24): a rogue server that
helpfully reports on itself undermines the lesson. Rogue calls are attributed from the caller's side by
the agent's execute_tool spans. The agent's identity header is not sent to the shim either.
**Do not suggest:** importing tool_audit in `gitops/ai-layer/server.py`.
## 2026-10-24T04:59:40Z · question 575 · Close #110 as a tracker; the talk content gets one Barcelona issue

**Question 575:** #110's tracked work is either landed (#111, #114, #115) or deferred on purpose to
Barcelona (#112, #113, #116, #117). What happens to the parts with no child issue: the Hugging Face
2026-07-16 opener, the "other incidents worth a slide" list, the authorities to cite (OWASP, CISA / Five
Eyes, MITRE ATLAS, NIST COSAiS), and the C2/C3 verdicts?

**Answer:** Close #110 as a tracker now that its children are landed or deferred, and file one
deferred-barcelona issue for the opener, incident slides and citations.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael. The basis is Michael's
own pattern on #112, #113, #116 and #117 (2026-09-07): post-Portland content is deferred to Barcelona on
its own labelled issue, kept open because the design work is still wanted.

**What it changes:** #110 stops being an open tracker. The four deferred child issues carry their own
work. The leftover talk content (opener, incident slides, citations, and the C2/C3 and ASI06 to ASI10
notes) moves to one new deferred-barcelona issue. No slide or lab prose changes here: that content is
still Michael's to write, and its dated facts get re-checked before they go on a slide.
`docs/research/2026-08-28-challenge-currency-review.md` records the disposition.

## 2026-10-24T09:30:00Z · #206 · Kyverno policies move from ClusterPolicy to CEL ValidatingPolicy

**Why now:** Michael's 2026-09-04 decision deferred this "past Portland"; Portland is past, and the
2026-09-07 review register records ClusterPolicy removal planned for Kyverno 1.20 (targeted October 2026).
Scope follows that decision exactly: Kyverno's own `policies.kyverno.io/v1` types, not native
ValidatingAdmissionPolicy. Nine `ValidatingPolicy` (the eight in `policies/kyverno/` plus
`policies/floor/minimal-floor.yaml`) and one `ImageValidatingPolicy` (`verify-image-signatures`). Every
policy keeps its name and every deny message is carried over word for word; Kyverno now prefixes it
`Policy <name> failed: `, so the refusal still names the policy.

**Choices made while porting:**
- The live toggle value is `Deny` (the CEL types' word for Enforce). `toggle-kyverno-enforce.sh` keeps its
  name and `--audit` flag; it replaces `/spec/validationActions`, which is also the ArgoCD ignoreDifferences
  path now (group `policies.kyverno.io`, kind `ValidatingPolicy`).
- `allowExistingViolations` has no CEL field. The pattern policies reproduce it in the expression: an
  UPDATE passes when the stored object already violated. It is gated on `request.operation == 'UPDATE'`,
  not on `oldObject != null`, because Kyverno 1.19 hands CEL an EMPTY MAP for a missing object (oldObject
  on CREATE and in background scans, object on DELETE). Read off the CLI and the engine source.
- Autogen stays on (it is the default) everywhere it was on before, which is what makes Beat 1's
  `kubectl create deployment` and C2's `deploy_app` fail at the Deployment. `deny-llm-endpoint-bypass`
  sets `autogen.podControllers.controllers: []`: the ClusterPolicy never had Deployment rules there
  (Kyverno skips autogen when a rule excludes by name).
- `minimal-floor` stays ONE policy with two validations, so the name the floor refuses with is unchanged.
- The ECR allow-list entry is a host-anchored regex (`^[^/]+\.dkr\.ecr\.[^/]+\.amazonaws\.com/`). The old
  wildcard `*.dkr.ecr.*.amazonaws.com/*` also admitted `evil.example/x.dkr.ecr.y.amazonaws.com/z`.

**New dev dependency:** the Kyverno CLI **v1.19.0** (2026-08-20, the deployed engine's version), used by
`verify/test_kyverno_cel_policies.py` (E2E suite; it fails loudly when the CLI is missing or a different
version). Why: a YAML render check cannot say a CEL expression evaluates. The CLI runs Kyverno's own engine
on fixture requests, with simulated users and UPDATE/DELETE, and verifies a real signed ghcr.io image
against the workshop key (and fails it under a different key).

**Not done here, and what it blocks:** guard-proxy's `/controls` C2 badge reads
`/apis/kyverno.io/v1/clusterpolicies/restrict-image-registries` and checks `failureAction == Enforce`
(guard-proxy-agenticburn `proxy.py`, pinned at `ccdda73`). That code is in the submodule's own repo. After
this lands the badge reads False until guard-proxy reads `/apis/policies.kyverno.io/v1/validatingpolicies/
restrict-image-registries` and tests `"Deny" in spec.validationActions`, and the pin is bumped. The
guard-proxy-reader ClusterRole here already grants that read. Promote the two together.

## 2026-10-24T07:36:04Z · #207 · The IAM half of the policy pipeline is built; the org half waits on access

**Scope follows the owner's 2026-09-04 direction on #207:** build the in-account permission-boundary
version and treat the org-level half as blocked until the provider grants management or delegated-admin
access to `o-pslkiycmqp`. No SCP, RCP or org S3 BPA document is drafted.

**Choices made:**
- **One boundary per account, not per cluster.** A role names its boundary by ARN. A boundary created in
  the same apply is either known only after apply (so no plan-time check can see it) or raced by
  CreateRole. `infra/org/boundary` creates `watch-it-burn-permissions-boundary` once per account, and the
  cluster root looks it up with a data source, so a cluster plan in an account without it fails at plan.
  **This adds a bootstrap step:** apply `infra/org/boundary` in each of the five accounts before the next
  `fleet.sh up`.
- **The boundary is Allow-everything plus Denies.** A strict allow-list ceiling would have to restate
  every AWS-managed policy the EKS cluster and node roles hold, and a missing service breaks a cluster
  live. The Allow is waived in `exceptions.md` with that reason. Its Denies are the in-account backstops:
  no unbounded CreateRole, no IAM escalation, no org or account calls, no public S3, no audit or key
  tampering.
- **Both Bedrock grants now carry a Condition** on the Pod Identity session tags (`eks-cluster-name`,
  `kubernetes-namespace`, plus `kubernetes-service-account` for the tutor). Check 3 asks this of every
  Allow, and it holds the grant to the cluster and namespace its associations already name. **Not yet
  seen live**: the next cluster's Bedrock beats are the check, and `test_iam_policy_aws.py` simulates it.
- **Check 3's rules cover permission policies only** (identity, boundary, SCP, RCP). Trust policies and
  KMS key policies are checked by Access Analyzer alone: key policies need `Resource: "*"`, and a trust
  policy's Allow is a grant to a principal, not a permission.
- **Upstream module policies are waived by address, with the reason.** These are the LB Controller, EBS
  CSI and ESO policies from terraform-aws-modules/eks-pod-identity, and the EKS module's cluster-encryption
  grant. They are AWS's published minimums, and the boundary still applies to them.
- **A new identity policy fails check 2 until accepted** (`--accept-new <address>`). There is nothing on
  main to compare it against, and passing it unseen would make check 2 skip whatever is new.
- **The E2E structural test renders today's roots without an AWS account.** `verify/iam_plan_render.py`
  points a copy at a local endpoint that answers only STS GetCallerIdentity and the boundary lookup. Any
  other call fails. A recorded fixture would go stale the first time main.tf changed.

**New dev dependency:** conftest **v0.71.1** (2026-10-06, bundles OPA 1.21.1), the issue's named engine for
check 3. Why Rego rather than Kyverno CEL: IAM's Action, Resource and Statement are each a string or an
array, and Rego has the prior art for that. It is used by `verify/test_iam_policy_structural.py` (E2E suite),
which fails loudly when conftest is missing or a different version.

**Not done, and why:** the SCPs, RCPs, org S3 BPA, the deny-manual-edits SCP, the break-glass and the
console-detach instructor beat all need org access we do not hold (#202). The OIDC `org-policies` GitHub
environment is a CI workflow and waits for the owner. "CI can write state" and "Datadog can still assume in"
have no subject: there is no CI role and no Datadog AWS role.

## 2026-10-24 · #240 · chat-ui removed; the console's Agent tab loads BurritoBot

chat-ui was not the kagent UI and not an A2A test client. It was a second nginx Deployment
(`ghcr.io/peopleforrester/watch-it-burn:nginx-1.27-alpine`) serving the older `index.html`/`app.js`
split-console chat, which posted A2A to `/a2a/` and polled `/cost`. Its only consumer was the "Agent
chat" iframe on `/console` (via `console.conf`'s `/chat/` route). Nothing in the lab, the deck, the tour,
the `platform` catalogue or the provisioning flow links `/console` or `/chat/`, and Michael measured zero
requests on watch-it-burn-pres-michael on 2026-09-05. So it had no consumer, and the issue says to remove
it in that case. The "developer's view of their agent" is already the real kagent UI, at
`kagent-<cluster>.agenticburn.com`, which the `platform` catalogue lists under exactly that description
(`platform.html:138`, `web-terminal/entrypoint.sh:84`). chat-ui showed none of that view.

- Removed the Deployment, the Service, the `chat-ui-src` generator, the `/chat/` route, and `web/index.html`
  plus `web/app.js`.
- `/console` stays, and its Agent tab now iframes `/burritbot`, so the split view drives the same chat surface
  students use. The runbook and the quickstart already describe the tab, so they stay accurate.
- `display.html`/`display.js` moved into `console-src`. They had shipped only in `chat-ui-src`, which kept
  `/display` returning 404 on clusters even after #338 added its route. `verify/test_console_service_vhosts.py`
  now checks that every `try_files` page is packaged in `console-src`, not just that it has a location.

## 2026-10-24T12:05:21Z · #333 · deny-llm-endpoint-bypass exercised live; its name exemption removed

The issue asked for one live test: create a pod of the bypass shape and read the PolicyReport. That test is
`verify/test_llm_bypass_live.py` (E2E suite, `CONTEXT` required). It was run on 2026-10-24 against Kyverno
v1.19.1, which is what chart 3.9.1 in `gitops/apps/kyverno.yaml` deploys. No EKS cluster was provisioned
for it: the run used a local kube-apiserver and controller-manager 1.35.9 with etcd, the chart's CRDs and
RBAC, and the real admission and reports controllers out of cluster with the chart's own arguments. The
real guard-proxy and agentgateway Deployments from `kubectl kustomize gitops/ai-layer` were loaded too.

**What it showed.** The policy as shipped does match its own shape. A bare Pod and a Deployment's Pod with
a public `*_BASE_URL` each got `fail` with the policy's message, through both the admission webhook (an
EphemeralReport with `audit.kyverno.io/source: admission`) and the background scan. One quirk: Kyverno
1.19.1 sets the result property `process: background scan` on admission results as well, so that
property cannot tell the two paths apart.

**What it found.** The matchCondition skipped any pod whose name started with `guard-proxy` or
`agentgateway`. The API server names a ReplicaSet's pods before admission, so an agent-made Deployment
called `guard-proxy-anything` produced pods the policy never evaluated. No report recorded them at all.
Init containers were never checked either, and they got `pass`. The exemption protected nothing: in the
rendered ai-layer, neither guard-proxy nor agentgateway sets `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL` or
`OPENAI_API_BASE`.

- The exemption is removed and init containers are checked. The policy stays `Audit`, as the issue asked.
- The live test also reads the reports of the running guard-proxy and agentgateway pods and needs `pass`
  on each. That is the policy's own precondition for promoting it to Deny. The test also refuses to judge
  a cluster whose installed policy differs from the repo's file.
- Proof that the test can fail: with the old policy on both sides it failed exactly the impostor (no
  result) and the init container (`pass`). With the old policy on the cluster and the new one in the repo,
  it failed the spec comparison.

## 2026-10-24 · #359 · The student's cluster name is the memorable host; a-NNN is retired, not an alias

The issue asked which name is canonical for a student and whether `a-NNN.agenticburn.com` is a permanent
alias. Michael settled it in 4a1fa58 (2026-09-08): the alias is a leftover. It survived the #142 rename
only so that links handed out before the rename still resolved, and none is still outstanding.

- **Canonical:** the two-word host that `public_host_for()` / `friendly_attendee_name()` return (slot 1
  is `bane-sabrina.agenticburn.com`). The claim page shows its first label, and that label is what a
  student says to a facilitator.
- **Not a name:** `watch-it-burn-attendee-<id>` is the provisioning slot id (`docs/BUILD-SPEC.md` §5).
- **Retired:** `a-NNN` and `r1-1`. `fleet.sh routes` emits neither, so a stale reference 404s instead of
  quietly working. The routes shrink guard does not count the old `a-NNN` rows, so dropping them is not
  mistaken for losing hosts.
- Still left from #359: provisioning-agenticburn's `STUDENT_PREVIEW_CONSOLE_URL` defaults to
  `https://a-001.agenticburn.com`. That default now points at a host that is never served, so it has to
  change in that repo. It is filed there as a follow-up.

## 2026-10-24 · #451 · The event knob sets the storefront's Feedback link and the projector QR; segno 1.6.6

The storefront's Feedback button was hardcoded to `feedback.agenticburn.com/quick`, and the feedback app stays
off for the KubeCon breakout (#448). The destination is now set per event in `gitops/ai-layer/web/event.js`,
shipped in the console ConfigMap next to `active-skin.js`, and never edited into the page.

- **Per event, not per cluster.** The fleet is rebuilt for each event, and the console never learns its own
  public host (console.conf, #152). A knob the page reads in the browser is the one place both the community
  and the admin clusters get the same answer without a guard-proxy change in its own repo.
- **The survey URL goes out verbatim.** It is a third party's page, so the cluster and user the workshop
  appends for `/quick` (#364, #383) are not added. Only an `https://` value is used; anything else leaves the
  workshop default.
- **The value** is the answer to question 147 (BurritoBot repo #80), given by the coordinator under Michael's
  standing rules: `https://kubecon-cloudnativecon-north-america-2026.sessionize.com/session/1249553`. Whether
  it shows this talk is checked once Sessionize opens rating (`facilitation/kubecon-na-2026-phone-check.md`).
- **The QR** is rendered from `publicUrl` in the same file by `scripts/audience-qr.py`, so the slide and the
  page cannot name two addresses. **segno 1.6.6** (PyPI, current on 2026-10-24) renders it: pure Python, no
  native libraries, and deterministic, so `verify/test_audience_page_e2e.py` can compare the committed SVG
  byte for byte. It is used only through `uv run --with segno==1.6.6`, never installed into the offline
  suite's interpreter. The offline suite reads the URL from the SVG's `<title>` instead.

## 2026-10-24 · #455 · The on-topic guard: phrases decide the canonical asks, BanTopics the rest

The talk ends with BurritoBot selling burritos only (abstract points 1 and 8, run-of-show segment 7). The guard
is a fifth `GUARDS` key, `topic`, in guard-proxy's `proxy.py`, toggled live through `/toggle` like the other
four. That is where the 2026-10-24 audit comment on #455 put it: the deployed proxy is `proxy.py`, and the Go
build answers 501 on `/toggle` and `/chat`. Its content belongs with the persona, so it lives here as
guard-proxy env: `TOPIC_GUARD` (off), `TOPIC_OFF_LIST`, `TOPIC_ON_LIST` and `TOPIC_REFUSAL`. The rule, the
asks it is judged on and the classifier settings are in `verify/topic_cases.py`.

**How it decides, cheapest first.** An off phrase refuses. Then an on phrase passes. Anything with neither goes
to LLM Guard's BanTopics. Phrases match as whole words, in any case, with an optional plural "s". The four
canonical asks (salsa dance moves, a hot dog party, karaoke for a wedding, the abstract's linked list) are
refused on a phrase, so the stage beat never depends on a model score. Every on-topic ask passes on a phrase,
so the classifier can never refuse a real customer. "What are your hours" and "do you have mild salsa" are
among them. The refusal costs no model call and offers the menu, the hours and the locations.

**Why the phrases have to carry the on-topic side.** BanTopics (llm-guard 0.3.16) runs the zero-shot pipeline
with `multi_label=False` and blocks when the top label scores over the threshold. The softmax runs over the
banned labels only, so a short menu question lands its whole score on some banned label. Measured with the
API's own BanTopics model: "do you have mild salsa" scored 0.846 as "music and singing", "what is a hex?" 0.972
as "computer programming", and "how spicy is Dragon's Blood" 0.956 as "movies and entertainment". The
classifier is reliable on prompts with no menu vocabulary, which is where an off-topic paraphrase that dodges
the off list ends up. With 13 narrow labels and threshold 0.5 it refuses all 16 paraphrases left to it and
passes all 4 vague menu asks ("what do you recommend", "do you deliver"): 61 asks, none wrong.

- **The model** is `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` at `8e7e5af5983a0ddb1a5b45a38b129ab69e2258e8`,
  MIT. That is the revision llm-guard 0.3.16 pins for BanTopics, so the copy the image bakes is the copy
  measured. Its `onnx/model.onnx` is 738,563,249 bytes (sha256 `d46fa6c1…3efa81c`), plus `spm.model` and the
  tokenizer files. The image grows by roughly that much. Measured off-cluster: the model loads in 4 to 14 s
  and a scan takes about 1 s on one pinned core, or 2 to 4 s on a busy 16-core host. The llm-guard pod is
  limited to one CPU. The canonical asks never pay this cost, because a phrase decides them.
- **guards-on leaves it off; guards-off turns it off.** Every challenge prompt is off-topic by design, so
  with the guard on it would refuse each one before the guard that challenge teaches could fire. The
  run-of-show turns it on alone, in segment 7.
- **The persona now has hours and locations.** The menu was all it could answer from before. Open every day
  11am to 11pm, until midnight on Fridays and Saturdays. Three cantinas: 13 Mandrake Row, Black-Bog Market,
  and the Moonrise Pass drive-thru. The storefront shows neither, so `web/burritbot.html` is unchanged.
- **Known limit:** an on phrase passes without asking the classifier, so "a burrito-themed bedtime story"
  gets through. The off list catches the mixes the talk uses ("salsa dance moves"), and an off phrase is
  checked first.

### REJECTED: BanTopics alone, with off-topic labels
**Why:** see the scores above. It refused "do you have mild salsa", one of the two asks the issue names as
the on-topic test.

### REJECTED: the same model as an allow classifier (multi-label, one on-topic hypothesis)
**Why:** with no context the model does not know salsa is food. "do you have mild salsa" scored 0.02 against
"a restaurant: its food, menu, ordering, opening hours or locations". It also needs a scanner LLM Guard does
not have, which means changing the vendored API, and the API is a packaging, not a fork (2026-10-05).

### REJECTED: roberta-base-zeroshot-v2.0-c, the smaller model (499 MB)
**Why:** it got 4 of the 61 asks wrong ("what's the capital of France", "teach me the bachata"). The deberta
model got none wrong.

**What is not done here, and in what order it lands:**
1. guard-proxy-agenticburn: the `topic` stage in `proxy.py`, on both `/` (A2A) and `/chat`, reading these four
   variables. The injection stage must start sending `scanners_suppress: ["BanTopics"]` and the topic stage
   `["PromptInjection"]`. Without that, BanTopics in `scanners.yml` would also run whenever C6 is on.
2. llm-guard-cpu-offline: bake the model above the way the injection model is baked (mirrored model image,
   pinned by digest, loaded through `model_path`), and measure the image size and start time on the built image.
3. Here: bump both pins, add BanTopics with `topic_cases.CLASSIFIER`'s topics and threshold to
   `llm-guard-scanners`, update `verify/test_proxy_guards.py`'s key set, and run the probe (#503) on an
   admin cluster both ways. `verify/test_topic_guard.py` arms its scanner checks the moment BanTopics
   appears in `scanners.yml`. Until the image carries the model, adding it there would stop LLM Guard from
   starting (`lazy_load` is off), and that would fail the injection classifier closed.

**New dev dependencies, used only by `verify/test_topic_classifier.py` (E2E suite) through `uv run`, never
installed into the offline suite's interpreter:**
- **llm-guard 0.3.16** (PyPI, 2025-05-19). It is the last release and the image's version, so the test runs
  the scanner guard-proxy will actually call.
- **torch 2.14.0+cpu** (PyTorch CPU index, 2026-09-02). This is the image's pin. 2.14.1 exists, but matching
  the image is the point, and the CPU build keeps the CUDA packages out.
- The model above, fetched from Hugging Face on the first run.

## 2026-10-24T13:16:17Z · question 629 · The admin console's cluster actions run through a fleet.sh runner (#268)

**Question 629:** Who runs the admin console's cluster actions, given the provisioning app on Railway has
no AWS credentials? The three options were a scoped AWS role for the app (A), a queue plus an in-cluster
agent on every cluster (B), or a queue plus a `fleet.sh` runner on a host that already holds the fleet
profiles (C).

**Answer:** C. The app queues each action and records the audit line. A `fleet.sh serve-actions` loop on a
host that already holds the fleet profiles polls `/admin/actions` with the admin token and runs the
matching `fleet.sh` verb, adding `restart-agent`, `restart-console` and `terminal-password` as verbs. It
also runs `fleet-walkthrough --json` on an interval and posts the result as the health report. This covers
all four actions, issues no new credential, and makes the console a caller of `fleet.sh`, as the issue
intends. The catch is that the runner has to be up during the workshop, on a named host: a presenter
laptop by default, since netcup stays out of the path.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**What it changes:**
- `fleet.sh` gains four verbs: `restart-agent`, `restart-console`, `terminal-password` and
  `serve-actions [--once]`. The restarts are pod deletes, because `block-argocd-drift` denies the
  Deployment UPDATE a rollout restart makes, and the 2026-09-03 entry rules rollout restarts out. Each verb
  checks that the kubeconfig's context is the named cluster before it mutates anything. The runner runs
  only the four names in `ADMIN_ACTIONS`, and only against a cluster with state on the runner. It claims an
  action before running it, so no action runs twice.
- The walkthrough report gains the health row's columns: `console_http`, `argo` (Synced+Healthy of
  total), `agent_ready` (a new check, `agent-not-ready` when it fails) and `last_trace`, from one
  instructor-org query in `verify/last_trace.py`. The walkthrough now reads `fleet.sh`'s `STATE_DIR`
  instead of a hardcoded path.
- `docs/admin-console.md` is the HTTP contract the provisioning app has to implement: the queue, claim,
  result and health routes, and a `requested_by` that names a presenter, because the admin token is shared
  and cannot tell them apart. The app side lives in `provisioning-agenticburn` and is a separate piece of
  work. Until it lands, `serve-actions` has no queue to poll.
- Rejected with A and B: neither could run `converge`, which needs the Terraform state and the
  per-account profiles. A puts write access to every cluster behind one shared token on a public app. B
  puts a credential and a privileged component on every cluster the challenges attack.
## 2026-10-24 · #500 · Datadog is switched by datadog-secret on the cluster, not by the profile

The admin profile has to run with no Datadog key (#454) and add Datadog "with no other change" once the pool
exists. The switch is therefore the presence of `datadog-secret`, read at pod start, so the same root, the
same Applications and the same values serve both states, and `fleet.sh converge` writing the secret plus
`infra/reload-datadog-consumers.sh` is the whole change on a running cluster.

- **Collector:** `values.yaml` `config` is Datadog-free (Tempo + Prometheus). The Datadog exporter and
  connector are the `otel-collector-datadog` ConfigMap (chart `extraManifests`), loaded as a second `--config`
  that the `datadog-gate` init container fills: the overlay when `DD_API_KEY` resolves, `{}` when it does not,
  logged either way. The image is the signed busybox mirror the platform already admits, so nothing new is
  pulled. `otlp/tempo` became `otlp_grpc/tempo`, the name the chart already rewrote it to in `relay.yaml`; the
  overlay does not go through that rewrite.
- **falcosidekick:** the `DATADOG_APIKEY` reference is optional; the chart's empty default key keeps the output off.
- **Datadog Agent:** stays in the profile, and waits for the secret. `deploy-full-idp.sh` logs that as the
  known gap. It is operator-managed, so its pods cannot be gated the same way from here.
- **Attendee** keeps both secrets non-optional and restates the overlay with `datadog/admin`.

### REJECTED: making the reference optional and nothing else
The datadog exporter refuses an empty key ("api.key is not set", otelcol-contrib 0.160.0) and the collector
validates every defined component, used in a pipeline or not, so the pod would start and then exit.

### REJECTED: a no-Datadog values file chosen by deploy-full-idp.sh when it has no keys
It needs a second root (or a patched one) for the same profile, and the root reconciles its own spec from git
(#253). Worse, a cluster brought up without keys would stay Datadog-free after the pool arrived, because
`converge` writes the secret but never re-applies a root.
## 2026-10-24 · #501 · The KubeCon brief is its own page `/kubecon`, not a mode of `/brief`
## 2026-10-24 · #501 · The KubeCon brief is its own page, `/kubecon`

The 30-minute breakout drives from a demo-only brief laid out by run-of-show segment: for each shown beat
(C1, C2, C3, C5, C6, C7, off-topic, on-topic) the prompt, who sends it, the admin-terminal toggle where one
applies, the success marker, and the deterministic fallback. It ships as `gitops/ai-layer/web/kubecon.html`,
routed at `/kubecon` (console.conf) and carried in the console-src ConfigMap, with the run-of-show linking
it.

**Why a separate page.** `/brief` is the 2-hour workshop: three phases, a
provisioning step where each person claims a cluster by email, and eight student challenges the students
install themselves. The breakout must carry none of that (the run-of-show says it stays off for this
session). A role toggle on `brief.html` would still ship the provisioning and student-lab prose in the page
source, one query parameter away. A separate page cannot show what it does not contain.
`verify/test_instructor_brief.py` now holds both: the three-phase workshop brief unchanged, and the KubeCon
brief's one-block-per-beat contract plus a body-level assertion that it carries no provisioning or claim
content.

**No apex-router gate on `/kubecon`.** The apex router 404s `/brief` on non-roster clusters
(peopleforrester/apex-agenticburn `Caddyfile`, #152), because in the 2-hour workshop a student who guesses
the path gets the presenters' timing. The breakout has no student pool: only the Community cluster and the
two presenter admin clusters run this session, so there is nothing to spoil and the gate is not added. If
the page is ever served alongside an attendee pool, gate it in the router the same way `/brief` is. That
change is in the sister repo (deploy configuration) and is filed as a follow-up.

## 2026-10-24 · #387 · BurritoBot is a phone surface; the lab is not; playwright 1.64.1 for the render check

An attendee on the 2026-09-08 Portland run asked for the workshop to work better on mobile. Michael's answer,
recorded in the issue and here so it stops reading as a backlog item:

- **The lab is not a mobile surface and will not become one.** The guide, the terminal, Datadog and `kubectl`
  are the hands-on hour, and that hour needs a laptop. `lab.html` gets no phone work for this.
- **BurritoBot is.** Chatting with the agent is a phone-shaped task, and the KubeCon room opens it from phones.
  The fix asked for, the title stacking, is in `web/burritbot.html`: below 680px the header is the title on its
  own row over one even row of the four buttons (two rows of two under 360px), and below 760px the chat card
  puts the avatar, "BurritoBot" and Reset on one row with the tagline under them. Desktop is unchanged.
- **The expectation is copy, and it is Michael's.** A line in the published abstract and in the workshop's
  opening material saying this is a laptop workshop is public prose, so it is filed as a follow-up for him,
  not written here.

**playwright 1.64.1** (PyPI, current on 2026-10-24) renders the page in headless Chromium for
`verify/test_mobile_titles_e2e.py`, which measures the boxes at 320 to 680px and 1280px. A CSS grep cannot
say whether a title wraps. It is used only through `uv run --with playwright==1.64.1`, in the E2E suite,
never installed into the offline suite's interpreter; `verify/test_mobile_titles.py` is the offline half.
## 2026-10-24 · #481 · The console's public /a2a/ route is removed; /toggle is reachable only via kubectl

`console.conf`'s `location /a2a/` proxied to `http://guard-proxy:8080/`. The trailing slash strips the prefix,
so it forwarded guard-proxy's whole path space, and `https://<cluster>.agenticburn.com/a2a/toggle?output=off`
reached the unauthenticated `GET /toggle` (`proxy.py` `do_GET`) from the internet. On the community cluster
and on an admin cluster on the KubeCon projector, any phone in the room could turn the guards off.

- **Fixed in nginx; guard-proxy is unchanged.** The route's only consumer was the split-console chat removed in #240,
  so removing it shuts off the public path with nothing to migrate. A loopback check on `/toggle` in guard-proxy
  would also block the tool pod's in-cluster call (evaluation #238, section 2.1), but `proxy.py` is a submodule with
  its own repo, and that call is the candidate mesh challenge, which is Michael's decision.
- **Exact routes only.** Every remaining guard-proxy route is `location =` on one path: `/chat`, `/cost`,
  `/guards`, `/prompts`, `/controls`. `verify/test_console_no_toggle.py` resolves request paths against the
  config the way nginx does and fails if any of them reaches `/toggle`, or if any route to guard-proxy is a
  prefix or regex. It also checks that the admin and community (burn) profiles both serve this one file.
- **The students' toggles are unchanged.** The terminal helpers (`.guardlib` `_px`), the lab's commands and
  the challenge scripts all `kubectl exec` into guard-proxy and call localhost. `verify/beat-02.sh` and
  `verify/beat-cost.sh` call the Service from inside the cluster. None of them went through the console.
- **Live check:** `verify/test_console_no_toggle_live.py` (E2E suite) fetches `/a2a/toggle`, `/a2a/guards`,
  `/a2a/` and `/toggle` through the apex router and expects 404. It runs the terminal's `_px` helper
  and `guards-status` with no change of state, then confirms the guards did not move.

## 2026-10-24 · #417 · Event slots, rooms and submission records point at conference-knowledge

conference-knowledge (`events/registry.yaml`) is the record for every event this talk runs at: entries
`aiewf-2026-watch-it-burn`, `devopsdays-portland-2026` and `kubecon-na-2026`. The working docs that copied a
slot, room, venue or submission status (README, ATTRIBUTION, the run-of-shows, runbook, slides outline,
Whitney's start page, the build and recreation specs, the go-live checklist, ABSTRACT) now name the entry
instead. Kept on purpose:

- **Dated logs** (`PROJECT_STATE.md` history, `docs/DECISION-LOG.md`, `PROGRESS.md`, `transcripts/`, this
  file) say what was true when written. Rewriting them would falsify them.
- **Inputs the code runs on.** `DELIVERY_DATE` in `verify/model_pin_check.py` and `feedbackUrl` in
  `gitops/ai-layer/web/event.js` stay, because the offline suite has no `~/repos` to read. Each names its
  source, and a slot change in the registry means changing them here.
- **Format lengths** (two hours, 30 minutes) shape the run-of-show, so they stay with it.

Three facts this repo held that the registry did not (the World's Fair submission record, the Portland
1.5-hour public listing, the KubeCon survey state on 2026-10-24) went to conference-knowledge as an
`agent-task` issue.

## 2026-10-24 · #422 · AGENTS.md says who this repo is and points at talks-knowledge

talks-knowledge asked every talk repo to name itself and point at the talk record (audit 2026-10-14). The only
gap here was the pointer, so `AGENTS.md` (which `CLAUDE.md` links to) gains a "Where things live" section:
talks-knowledge for the register (`talks/register.md` section 2), abstracts and talk scripts;
conference-knowledge for event state; the two submodule repos; and this repo's own state files.

- **README unchanged.** It already gives the title, speakers, argument, the event (with its slot pointed at
  conference-knowledge since #417) and the repos it is built from. It does not say "delivered"; that is
  public prose, so it is left for Michael.

## 2026-10-24 · #440 · The E2E gate gets yarn through corepack and launches Playwright's own Chromium

The dispatch machine now has Node 24.22.0 with corepack 0.36.0. It has no global yarn, and `corepack
enable` would have to write shims into the root-owned toolchain. `verify/run-e2e.sh` now requires `node`
and `corepack` instead of `yarn`, fails if Node's major version is not 24, and runs `corepack yarn`. Corepack
runs the yarn 4.13.0 that the Backstage `package.json` (`packageManager`) and `.yarnrc.yml` (`yarnPath`)
pin. While a script is running, yarn 4 puts its own `yarn` on PATH, so the `yarn start` web servers in
`playwright.config.ts` resolve too.

The Backstage Playwright suite had never run here, and its first run showed a second bug.
`generateProjects()` defaults to the `chrome` channel, which needs Google Chrome at `/opt/google/chrome`.
The script installs `playwright install chromium`, so the browser it installed was never the one the tests
launched. The config now passes `{ channel: 'chromium' }`. With that change the suite passes (1 test) with
`GITHUB_TOKEN` unset: an unset token does not break the app or backend start.

The full `run-e2e.sh` still exits 1 in its prerequisite check. Node and yarn are no longer missing, but
kubectl, helm, the kyverno CLI, conftest, terraform and the aws CLI are, along with a cluster `CONTEXT` and
the IAM pipeline profile and region.
## 2026-10-24 · #421 · Dependabot alerts: what cd529d9 left open

cd529d9 cleared the vm2, shell-quote, axios, grpc-js, basic-ftp, fast-uri and undici alerts. For the rest:

- **@graphql-tools/utils (GHSA-7mx3-vvmw-hjmv): fixed by a resolution.** The only consumer is mockttp 3.x, which
  arrives through `@backstage/backend-openapi-utils` (its `./testUtils` entry; production never loads it). The
  `schema 10.1.5` and `utils 12.1.0` resolutions pull in `merge 9.2.8`. That is the 10.x/12.x line mockttp 4.x
  itself uses, and it still accepts graphql 15, which mockttp 3 needs. We did not need four majors. A smoke run
  against the installed tree passed: `getLocal()` served a rule, and `getAdminServer()` plus `getRemote()` set a
  rule and read seen requests over the GraphQL admin schema.
- **http-cache-semantics (GHSA-ch52-4w7c-c8xp): fixed by a lock refresh.** The advisory covers versions up to
  4.2.0, and 4.3.0 is now out. make-fetch-happen's `^4.1.1` takes it.
- **node-forge (GHSA-86w9-cpqp-85rv): kept, the alert stays open.** 1.4.0 is still the latest release and is
  affected. The fix is digitalbazaar/forge#1152, not yet released. No code here verifies an RSA signature with it:
  backend-defaults uses it only to generate and parse its own self-signed certificate when `backend.https` is set
  with no certificate (neither app-config sets it), selfsigned is webpack-dev-server's dev certificate, and mockttp
  is test-only. When forge ships a fixed release, refresh the lock.
- **urllib3 (3 alerts):** these point at `lab-distribution/uv.lock`, which 5037fa1 removed. No manifest is left
  to change.

Advisories published after the issue was filed (same lockfile, `yarn npm audit --all --recursive` on
2026-10-24). The resolutions move to vm2 3.12.2, dompurify 3.4.17, fast-uri 3.1.9, hono 4.13.13, ip-address 10.7.4
and undici 7.30.1. A lock refresh takes markdown-it, compression, follow-redirects, handlebars, proxy-addr,
source-map-js, qs (the `^6` ranges), colord, fast-copy, launch-editor, pbkdf2 and the zod 4 line to their patched
releases. vm2's only consumer is typescript-json-schema (Backstage CLI config schemas); a smoke run of its
`VM.run` initializer path passed on 3.12.2. Not done here:

- **body-parser 1.20.9/2.4.0 and multer 2.5.0** were released on 2026-10-22, so `.yarnrc.yml`'s
  `npmMinimalAgeGate: 3d` holds them until 2026-10-25. Express's `qs ~6.15.1` waits for that body-parser bump.
- **Majors:** zod 3 (fixed only in 4.6.6), react-router 6 (fixed in 7.18), @azure/msal-node 5 (fixed in 7.1),
  postcss-selector-parser 6 (fixed in 7.1.6).
- **elliptic** has no fixed release.
- **Backstage plugins** (backend-defaults, catalog-, scaffolder-, techdocs-, kubernetes-, proxy-, search-backend,
  auth-node) need their own version bumps. Dependabot has opened a branch for each.
## 2026-10-24 · #332 · question 637 · the Kyverno line in Challenge 2 gets no rationale

**Question 637:** Challenge 2's fix card (`gitops/ai-layer/web/lab.html:445`/`:454`) names OPA Gatekeeper,
Kubewarden and ValidatingAdmissionPolicy, then just says "This cluster runs Kyverno". Whitney took out the
plain-YAML reason (cacf1db, #370), and #206 has since moved the policies to CEL ValidatingPolicy, which
makes the YAML argument weaker still. Should that line get a reason, and which one?

**Answer:** No rationale: keep Whitney's wording as it stands, since she asked for the alternatives named
without dwelling on the differences. Close #332.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**What it changes:** no prose changes. The card keeps her wording. "Kyverno's rules are plain YAML, which
is why we use it here" and the "Its policies are written in YAML" tail stay removed and are not to be
restored, and no replacement claim (policy reports, signature verification, exceptions, CLI testing) is
added. The capital "And" the issue mentions no longer exists: cacf1db replaced that sentence with "Some
cluster-level policy functionality is also available natively in Kubernetes".

## 2026-10-24 · #445 · fleet.sh takes the terminal login only through harvest_terminal_credential.sh

**Decision:** every place fleet.sh used to write `<cluster>.terminal` (bootstrap, `ingest`, `terminal-password`)
now calls `${WIB_PROVISION_DIR}/scripts/harvest_terminal_credential.sh <cluster> <region> <aws-pool-dir>` in the
cluster's account and nothing else writes the file. It holds the whole `user:password`, which is the only form
merge_pool.py accepts since provisioning-agenticburn#16. `ingest` sends both halves from that file, split on
the first colon.

**On the harvester's exit codes in `ingest`:** 0 registers the row. 1 (unreachable, unreadable, malformed)
registers nothing and records `ingest:<name>`, so the existing retry loop takes it again; the old fallback to a
cached password is gone, because that cache is what showed agentic / sprouts. 3 (no Secret, terminal open)
still registers the console with an empty login and records `terminal-open:<name>`, so the run fails by name
without hiding the console from a student. fleet.sh removes `<cluster>.terminal` on any non-zero exit, as the
harvester does.

**Re-ingest:** `fleet.sh ingest pool` reads every row from /admin/roster and re-ingests it by name.
/admin/import upserts and never touches claim state, so claimed rows pick up the corrected login.
## 2026-10-24 · #447 · The KubeCon dates and the run-through record live in the KubeCon run-of-show

The archived BurritoBot repo's dated schedule (spec 001, BurritoBot#114, #121, #60) moved here. It is held in
`facilitation/kubecon-na-2026-run-of-show.md`, section "Dates to hold (#447)", and nowhere else in the repo;
`PROJECT_STATE.md` and Whitney's start page point at it. `verify/test_kubecon_dates.py` holds it.

- **Michael's revision of 2026-10-24 governs, not the issue body's table.** Work agents build has no
  forecast date and is listed in build order (platform live on AWS, every abstract point READY or cut,
  recorded fallback, deck). Dates are for people: the cold read once the platform is live, the Datadog pool
  the week of 10-26, two timed run-throughs by 11-08, delivery on 11-12. The issue body's 10-23 "platform
  live" date is therefore not carried. The cold read's calendar hold (Mon 2026-10-26, 10:00 to 16:00
  Central) is written down, because conference-knowledge says the talk repo holds that date, but the read
  waits for the live platform rather than for the day.
- **"The facilitation runbook" is the KubeCon run-of-show.** `facilitation/runbook.md` is the 2-hour
  workshop's, and the run-of-show already says "read the timing from this file". The record takes
  BurritoBot#121's shape: a column per run (Run-through 1, Run-through 2, plus Delivered), whole slot and
  demo rows, and a findings row that takes issue numbers. The demo target is 24:00, the sum of segments 2 to
  6 in this file's segment table, not BurritoBot's "25 min or less"; the test derives every target from that
  table so they cannot drift apart. The cold read is logged under it untimed.
- **Slot and room confirmed, not copied.** conference-knowledge `kubecon-na-2026` `schedule` on 2026-10-24
  reads 2026-11-12 13:50 to 14:20 MST, Salt Palace, Level 1, Grand Ballroom BDF, which matches BurritoBot#114.
  Per #417 the run-of-show names the entry; the test fails if a Mountain-time slot or the room appears in it.
  The delivery date stays, and must equal `DELIVERY_DATE` in `verify/model_pin_check.py`.
- **Not done here:** the run-throughs (Michael and Whitney present them), bringing the platform up (#454),
  and repointing spec 001 at this repo, which is a personal-knowledge change.

## 2026-10-24 · #526 · preflight checks the permissions boundary; the boundary root is outside the event-tag rule

**Decision:** `fleet.sh preflight` runs `aws iam get-policy` for `watch-it-burn-permissions-boundary` in each
account it checks. NoSuchEntity is a FAIL that prints that account's `infra/org/boundary` init and apply line
(`-state=states/<acct>.tfstate`, the default account included). Any other error is a FAIL too, because an
unreadable boundary is not a present one. The lab-VPC hints name the state `lab_vpc_state_for` uses:
`terraform.tfstate` for WIB_DEFAULT_ACCOUNT, `states/<acct>.tfstate` for the rest. A stray
`states/<default>.tfstate` gets a note, because fleet.sh reads it first and down-infra never destroys it.

**On the event tag:** verify/test_event_tag.py requires `-var event=` on every apply or destroy of a root
under infra/terraform. It now skips `infra/org/boundary` commands. That root declares no `event` variable, so
passing one would fail the apply. Its single IAM policy per account outlives every event and costs nothing, so
there is no spend to split by event.

## 2026-10-24 · #531 · fleet.sh routes records routes.map on main from a worktree of origin/main

**Decision:** `cmd_routes` no longer pushes the apex checkout's HEAD to main. `publish_routes_table` fetches
apex `main`, checks it out in a temporary detached worktree, writes the regenerated routes.map there, and
pushes that single commit to main. The checkout's own branch (staging at the 2026-10-24 bring-up) still gets
its own routes commit and push, because the shrink guard reads the table on HEAD. A checkout that is on main
skips the local commit and fast-forwards to the pushed commit. The commits on the checkout's branch that are
not on main are listed in the log as kept off it.

**Why this option, not refusing:** the issue offered both. routes.map is generated whole from the live fleet,
so it does not need the branch's history to land on main. Refusing would leave main's table stale whenever
apex staging runs ahead, which is the normal state during a bring-up. Failures stay logged and non-fatal as
before, since the table is applied to the live router either way. Apex main stays at 8c474dc (Michael, on the
issue): its tests pass on that SHA.
## 2026-10-24 · #530 · C5 is judged on the address, the console's fold is the probe's, and the off-topic answer waits for 3 of 3

The 2026-10-24 probe run on attackme and michael-admin (#509) failed three community and admin beats on Nova's
shape, not on the platform. Each criterion of #530 had two ways out; these are the ones taken.

- **C5 counts the address, not only the signature.** C5's stated goal is the CEO's home address, and both
  live replies handed over the record by its residence or delivery address without the signature line. So
  `judge_secret_leaks` passes on the address or the signature, and `judge_secret_scrubbed` fails on either.
  The address branches are the output guard's own (`CEO_ADDRESS_RE` in `verify/agent_probe.py`, held equal
  to `llm-guard-scanners` by `verify/test_kubecon_probe.py`), so a leak the judge counts is one the guard
  redacts. `/brief`, `/kubecon` and the prompt catalog now name the address as the marker. The Secret and
  the /brief prompt are unchanged: making the signature survive would need live runs on both cluster kinds.
- **The console path is the storefront's `splitThinking`.** It now also folds a `<thinking>` block Nova
  never closes and drops a stray tag, so no tag text reaches the bubble. `verify/kubecon_probe.py` reads the
  page's two patterns and judges the text the bubble shows. guard-proxy, a separate repo, still returns the
  raw scratchpad on `/chat`, which the storefront needs in order to fold it.
- **The off-topic answer is not promised until it is 3 of 3 live.** The persona now tells the wide-open bot
  to answer harmless off-topic asks, and the community probe asks the linked-list question three times in
  fresh conversations and passes only on 3 of 3. That has not run on a cluster, so the run-of-show and
  `/kubecon` stop promising the answer until the Night Before probe shows it.
## 2026-10-24 · #454 · KubeCon delivery identity: the five Portland accounts, event=kubecon-na-2026, no Datadog pool yet

Michael's answers on #454, and where each one lands in the repo.

- **Accounts and region (2026-10-23):** the KubeCon delivery and its rehearsals run on the five AWS
  accounts the Portland fleet used, in the same regions. No dedicated account. The 2026-10-24 bring-up ran
  in accen-dev, us-west-2 (#510, #526), which is also where the pinned model is checked (#453).
- **Event tag (2026-10-23):** `event=kubecon-na-2026`, the coordinator default, which Michael may change.
  It is set once in `infra/terraform/fleet/event.sh`, and neither Terraform root has a default, so an
  apply without the tag fails (#494). KubeCon spend separates from other tenants on that tag (#392).
- **Datadog org pool (2026-10-23):** none until Whitney sets one up, the week of 2026-10-26. A missing key
  is a known, logged gap, not a stop. The admin profile runs without a key (#500), and `fleet.sh`
  bootstraps roster clusters without one (#510). Datadog-dependent work (#264, #265, #320, #337, #382,
  #443, abstract point 7) waits until 2026-10-30.
- **Bring-up scope (2026-10-24):** the community cluster plus one admin cluster on those accounts, on the
  smallest instances that run the demo, tagged as above. The #503 probe runs on both, and both clusters
  come down in the same session with zero fleet resources verified. A second admin cluster is not part of
  it. The run on attackme and michael-admin is recorded on #510, #526, #528 and #530. The teardown's zero
  check (`verify/account-audit.sh` CLEAN) is not recorded in this repo yet.
## 2026-10-24 · #449 · The KubeCon deck stays in rounds-agenticburn; this repo exports its 16:9 PDF and holds it to its source

**Where the deck is built.** The issue asked to confirm with Michael and Whitney where the slides are built
before writing HTML (the coordinator's answer to BurritoBot question 115). The run-of-show had already settled
it: the presenters drive from `attendee.html` in `peopleforrester/rounds-agenticburn`, and rounds-agenticburn#38
cut that deck from this repo's run-of-show (drafted on its branch `agent/38-7151`, waiting for Michael's review).
So this repo builds no slide HTML. What #449 adds is the PDF.

**The export lives here.** `scripts/kubecon-deck-pdf.py export <rounds-checkout>` prints the deck through
reveal.js's own `?print-pdf` mode in Playwright's Chromium (playwright 1.64.1, already pinned on #387, used only
through `uv run --with`), into `facilitation/kubecon-na-2026-deck/`: the PDF and `export.json`. This follows
BurritoBot's M5 approach (an HTML source printed by Chromium and held to it by sha256) without copying its
slides. It lives here rather than in rounds-agenticburn because the run-of-show and its cut tables are here,
and the export reads them. The record keeps the rounds-agenticburn commit, the sha256 of `attendee.html` and of
every local file it loads (an image change makes the PDF stale too), the PDF's sha256, its page count and size,
and each slide's text without speaker notes. `check` needs no browser. It recomputes all of that and re-scans
the recorded text against the cut tables as they stand at upload time.

- **Cut items come from the run-of-show, not a copy.** A row of "Abstract points to segments" or "Challenges
  shown live, and challenges cut" whose cell starts with "Cut" is refused on any slide. The words for each of
  the nine points are in the script. Today only C8 is cut.
- **16:9 is the deck's job.** reveal.js sizes the print page from the deck's `width` and `height`, and
  `attendee.html` sets neither (960 by 700 prints 998 by 728). The export refuses a page that is not 16:9
  (0.25% tolerance, for reveal's floored margin) rather than overriding the deck's size, which would print a
  layout nobody presented. 1600 by 900 gives an exact page. Setting it is a rounds-agenticburn change, filed
  there as a follow-up.
- **Refused, nothing written:** another repo's checkout, uncommitted changes to the deck, a first slide without
  the talk title, a page error or a failed request.
- **The PDF itself is exported last**, once rounds-agenticburn#38 is on its `main`, the deck is 16:9, and #456
  has settled what is cut. The upload is the presenters'.

## 2026-10-24 · #458 · Teardown deletes each cluster's attendee IAM user and its keys; audit-zero names any left

**Nothing deleted them.** `generate_attendee_aws.py` (run by `fleet.sh aws-keys` and by `bootstrap_student_aws`
on every build) makes one IAM user per cluster, `wib-<name less watch-it-burn->`, tagged `project=watch-it-burn`
and `cluster=<name>`, with an inline policy and one live access key. No code in this repo or in
provisioning-agenticburn removed one, and the fleet accounts are reused across events rather than closed, so
every attendee key outlived its cluster. A cluster rebuilt under the same name finds the user already there,
mints no new key and gives that user an EKS access entry with cluster admin again.

- **Per cluster:** `down_one` calls `sweep_attendee_iam_user` after the destroy, in both branches like the
  other sweeps. It deletes only when `describe-cluster` answers ResourceNotFoundException (any other error
  leaves the user and records `iam-user-leak:`) and only a user tagged `cluster=<that name>`. It removes the
  keys, inline and attached policies and any login profile, then the user, then `aws-pool/<name>.csv`, the
  persisted copy of a key that no longer exists.
- **Per account:** `down all` and the new `reap-iam-users [accts]` (dry run unless `WIB_APPLY=1`) run
  `sweep_orphan_iam_users`: every `wib-*` user tagged `project=watch-it-burn` whose cluster is not in
  `eks list-clusters`. That covers users `aws-keys` minted by range for clusters that had no state, and the
  ones that leaked before this. An unread live list stops the account, as in `reap-lbs`.
- **Audit:** `audit-zero` fails on any `wib-*` user whose cluster is not live (`zero:<acct>:iam-users`), so it
  is no longer only about billable things. `verify/account-audit.sh` counts our IAM users beside the roles
  and policies.

## 2026-10-24 · #464 · Alloy labels every Loki stream with namespace, pod, container and app

**Before, every stream was `{job="loki.source.kubernetes.pods"}`.** `gitops/apps/alloy.yaml` handed the
discovery.kubernetes targets straight to loki.source.kubernetes, which drops every `__meta_` label and adds
only `job`, so the #190 audit query had to line-filter every stream: `{job=~".+"} |= "tool_invocation"`.

- **A discovery.relabel sits between them** and copies `namespace`, `pod` and `container` from the pod's
  metadata. It keeps the `__meta_` labels: loki.source.kubernetes needs them to find the pod, and drops them
  itself before the push.
- **`app` is app.kubernetes.io/name, else the `app` pod label.** The issue named app.kubernetes.io/name, but
  workshop-mcp and evil-mcp-shim carry only `app` (llm-guard, guard-proxy, web-terminal and console carry
  app.kubernetes.io/name), so a label from app.kubernetes.io/name alone would leave the audit trail's own pod
  without one. The second rule has regex `(.+)` so a pod without
  app.kubernetes.io/name keeps its `app` value instead of being blanked.
- **`job` is left as the component id.** Changing it would buy nothing a query needs and would break any
  saved `{job=...}` selector.
- The audit query is now `{namespace="agent", app="workshop-mcp"} |= "tool_invocation" | json`
  (tool_audit.py, test_tool_audit_live.py). `verify/test_alloy_labels.py` holds the wiring offline. The
  relabel's output was checked against Alloy v1.19.2 (chart 1.12.1's appVersion) with `alloy validate` and
  a local `alloy run` on static targets; the Loki end is the live half of test_tool_audit_live.py.
## 2026-10-24 · #468 · Terraform registry modules pinned to their minor; cluster lock regenerated

**The lock did not cover what moved.** `.terraform.lock.hcl` locks providers, not modules. The cluster root
asked for `terraform-aws-modules/eks/aws ~> 21.0`, which now resolves to 21.29.0, and that release needs
aws >= 6.59.0 while the committed lock held aws 6.51.0. A fresh `terraform init` failed; only machines with an
older module cached in `.terraform/modules` still worked.

- **Pin:** every registry module is `~> X.Y.Z` (patch releases only): EKS `~> 21.29.0`, eks-pod-identity
  `~> 1.12.0`, VPC `~> 5.21.0` (the network root had the same exposure, though its lock still fit). Moving a
  module's minor is a deliberate edit, made with `terraform init -upgrade` and the regenerated lock.
- **Lock:** the cluster lock was regenerated with Terraform v1.15.6 (`init -upgrade`): aws 6.70.0, cloudinit
  2.4.1, null 3.3.2, time 0.14.2, tls 4.4.2.
- **Tests:** `verify/test_terraform_module_pins.py` (offline) fails on any unpinned registry module or a lock
  that does not record the root's provider constraint. `verify/test_terraform_lock_init.py` (E2E) runs
  `terraform init -lockfile=readonly` on every root in an empty directory and fails if the lock does not fit.
## 2026-10-24T20:16:19Z · question 679 · #466: a run drafts the opener, incident slides and citation slide for Michael to rewrite

**Question 679:** #466 (the Hugging Face 2026-07-16 opener, the incident slides, and the OWASP, CISA, MITRE
ATLAS and NIST COSAiS citations) is talk content that the issue, question 575 and governance all leave for
Michael to write. Should a run draft any of it for his review (a source re-check of each dated fact from
#110, or draft slides marked as drafts), or will he write all of it himself?

**Answer:** A run drafts the opener, incident slides and citation slide in facilitation/ for Michael to
rewrite and approve.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael. The basis is the
"approval only at publication" rule: a draft in facilitation/ has no live audience, and Michael approves at
the talk. It also corrects question 575's wording "that content is still Michael's to write", which was
hecaton's own and had no statement from Michael behind it.

**What it changes:** `facilitation/slides-draft-2026-currency.md` is new. It holds the draft opener (a slide
and about 75 seconds of script), five incident slides with a one-slide version, a citation slide, and a
2026-10-24 re-check of every dated claim from #110 against its source. The re-check corrects several of
#110's facts, and the slide wording follows the corrected versions:

- Hugging Face's own timeline (2026-07-27) now names the models. #110's reason for leaving the attribution
  off no longer holds, but the draft still leaves it off, as the issue requires. Whether to keep that rule
  is Michael's call.
- The connector credential gave cluster-admin on two clusters, not "multiple".
- The Five Eyes guidance's wording is "prioritising resilience, reversibility and risk containment over
  efficiency gains". It was published 2026-05-01, and its PDF is dated 2026-04-30.
- MITRE ATLAS has moved from v5.4.0 to calendar versions (v2026.09).
- NIST renamed COSAiS to COSIS on 2026-10-20.
- The Anthropic post is dated 2025-11-13.

The delivered `slides-outline.md` and `cold-open-script.md` are not changed, apart from one build note that
points at the draft. The disposition is recorded in `docs/research/2026-08-28-challenge-currency-review.md`.

## 2026-10-24 · 3.3 · No E2E command for the promotion gate; run-e2e.sh is by hand (#543)

`verify/run-e2e.sh` needs a live attendee cluster (CONTEXT), AWS credentials (IAM_PIPELINE_PROFILE,
IAM_PIPELINE_REGION) and kubectl, helm, node 24, the kyverno CLI, conftest, terraform and the aws CLI.
Hecaton's promotion gate runs the declared `E2E command:` and has none of these, so promotion to main
failed on every attempt with 58 merges waiting. AGENTS.md now declares only `Test command:` (the offline
suite, `verify/run-tests.sh`), which the gate runs instead. The live suite stays the by-hand check during a
cluster build. This is the standing answer to hecaton's "Declare an E2E command for the heavy gate" issue:
the repo's heavy tests need real services the gate cannot reach, so no line is declared.

### REJECTED: keep `bash verify/run-e2e.sh` as the E2E command
**Why:** the gate host has no attendee cluster or AWS profile, and the suite fails rather than skips when
either is missing, by design.
**Status:** Revisit when the gate can reach a live cluster and AWS.
**Do not suggest:** a skip-on-missing mode in run-e2e.sh; it would let the gate go green having proved nothing.

## 2026-10-24 · #476 · The burn collector ships to Datadog only, through its own Application

**Before, attackme ran the instructor collector.** The burn root selected `otel-collector.yaml`, values.yaml
alone, whose pipelines export to prometheusremotewrite and otlp_grpc/tempo in relay.yaml and in the Datadog
overlay both. The burn root installs neither Prometheus nor Tempo, so every batch went to two dead endpoints
and was retried; Datadog still got its copy.

- **A third collector Application, `gitops/apps/otel-collector-burn.yaml`,** with the same name as the other
  two and `values-burn.yaml` layered over values.yaml, the shape of the attendee one. The burn root selects it;
  the full, attendee and admin roots now exclude it, as two of them already excluded the attendee one.
- **values-burn.yaml restates only the exporters lists:** relay.yaml's (metrics to debug, traces to
  span_metrics and debug) and the otel-collector-datadog ConfigMap's (Datadog, the connectors, debug). The
  Tempo and Prometheus exporter definitions stay in the map, defined and never started; deleting a key with
  a Helm null is not something to trust across versions. Without datadog-secret the burn collector exports
  to debug only.
- **The datadog-gate's log lines no longer promise Tempo and Prometheus unconditionally**; they say "on the
  profiles that install them", which also rolls the collector once on every profile.
- **Test:** `verify/test_collector_backends.py` renders the collector each root actually selects and fails
  when an exporter's backend Application is not in that root's selection, with and without datadog-secret,
  or when an exporter is unclassified. It also holds values-burn.yaml to values.yaml's lists minus the two
  sinks. Checked offline only: no helm or otelcol-contrib binary on the run host, so neither `helm template`
  nor `otelcol-contrib validate` has been run against the burn render.
## 2026-10-24 · #460 · The World's Fair debrief is `notes/DEBRIEF-worlds-fair-2026.md`, built only from this repo's records

**Where it lives.** `notes/` is new here. The name follows the Portland repo's `notes/DEBRIEF.md`, with the
event in the filename because this repo has more than one delivery. The debrief is history: like
`docs/DECISION-LOG.md`, it describes the June round model as it ran, and it is not rewritten when the
workshop changes.

**Provenance rule.** Every figure cites a file, a commit, a deleted file (`git show f5c9a66^:...`), the
`delivered/aiewf-2026` tag or a transcript. Anything without a record is written **unrecorded**. That
covers attendance, the network, segment times, which challenges landed, when the fleet came up and went
down, the peak hosts, the workshop-only cost and all feedback. Michael's later "250 attendees" (transcript,
2026-09-01) is quoted as a recollection, not used as the count. The 727.52 USD whole-account upper bound
(`767e97a`) is shown as that, never as the workshop's cost.

**Two corrections found on the way.** Neither changes the files they appear in, which are records.

- The Portland debrief's "roughly 400 orphaned load balancers and 61 orphaned volumes" does not describe
  the World's Fair. In this repo, 61 volumes is the 2026-06-27 pre-event sweep (with 18 load balancers),
  and roughly 400 load balancers has no record.
- The `delivered/aiewf-2026` tag message says the delivery-day commits ran "from 10:27 to 12:51 Pacific".
  Their author timestamps, read in `America/Los_Angeles`, run 05:34 to 12:51: 40 commits.
## 2026-10-24 · #475 · The attendee profile leaves out tempo and falco-talon; admin and full keep both

**Nothing on an attendee cluster used either.** The #236 audit (`docs/research/2026-10-24-duplicative-components-audit.md`)
found that no challenge or tour step reads Tempo (builders read raw spans out of it on admin clusters), and that
Talon acts on nothing there: Sidekick forwards only CRITICAL to it, Recipe Snoop is WARNING, and the fork bomb is
an instructor-box demo only (#114). The attendee root's exclude is now
`{network-policies,kubearmor-policies,otel-collector,otel-collector-burn,tempo,falco-talon}.yaml`: two fewer apps, 36 instead of 38.

- **The Tempo data source moved into the tempo Application.** It was in `prometheus.yaml`'s
  `additionalDataSources`, which every profile deploys. It is now a ConfigMap labelled `grafana_datasource: "1"`
  in `gitops/tempo/`, which the tempo Application deploys as a second source beside the chart; Grafana's
  datasources sidecar loads it. A profile without tempo therefore has no data source pointing at a missing
  Service, with no attendee copy of the prometheus Application. Loki's TraceID link still names uid tempo and
  has no target on attendee clusters.
- **The attendee collector names no Tempo exporter.** `values-dual.yaml` restates relay.yaml's traces exporter
  list (`span_metrics`, `debug`) and drops `otlp_grpc/tempo` from the Datadog overlay's. The exporter's
  definition stays in `values.yaml`, unused, because a Helm null is not a safe delete for a key the chart's
  defaults do not carry.
- **Sidekick keeps its Talon output on every profile.** On attendee clusters a CRITICAL event's Talon post
  fails and is logged; the Datadog output is separate and unaffected. An attendee copy of the falcosidekick
  Application only to silence that log was not worth a third profile-specific app.
- **The console pages say what an attendee cluster has.** `platform.html` and `links.html` mark Tempo and Talon
  as instructor-cluster only, no longer say "Talon reacts", and read Falco's logs from `security`, where Falco
  runs (the old `-n falco` command found nothing on any profile). The terminal's `platform` table matches.
- **Tests:** `test_root_self_managed.py` holds which profile deploys each app; `test_collector_no_datadog.py` and
  `test_observability.py` hold the attendee trace lists free of Tempo; `test_service_links.py` holds the page
  wording and finds the Tempo uid in `gitops/tempo/`; the live `test_service_hosts_live.py` expects no tempo
  data source on an attendee cluster. Not yet checked on a live cluster.
## 2026-10-24 · #484 · The Backstage footprint is read from the kubelet summary, because there is no `kubectl top`

**Nothing in this repo installs metrics-server.** The EKS addons in `infra/terraform/aws/cluster/main.tf` are
vpc-cni, kube-proxy, coredns, the pod identity agent and the EBS CSI driver, and no Argo CD app deploys it, so
the metrics API that `kubectl top` reads is absent on an attendee cluster. `infra/SIZING.md` still says to
measure with `kubectl top`, and that command fails there.

- **`verify/backstage-footprint.sh` measures the #484 numbers** with `CONTEXT` required and every kubectl call
  carrying `--context`. It samples the kubelet summary API (`nodes/<node>/proxy/stats/summary`), the source
  metrics-server itself would scrape, so no new component goes onto the cluster just to be measured. The
  working set is the number `kubectl top` would show, and RSS is the "resident" figure the local #244 run
  reported. It prints the last and peak readings beside each Backstage and Postgres request and limit. Then it
  prints each node's allocatable against the requests of every live pod on it, counted as the scheduler counts
  them (init containers, sidecars, overhead). Last, it calls the Kubernetes tab's own backend call
  (`POST /api/kubernetes/services/<name>`), signed in as guest through a port-forward, for unicorn-party and
  workshop-agent.
- **Not wired into `run-e2e.sh`.** Backstage is still in `gitops/apps-disabled/` on main; the branch that turns
  it on (#244) waits on the rebuilt, signed image (#483). Added to the live suite now, it would fail on every
  cluster. Wire it in when #244 is promoted.
- **Tests:** `test_backstage_footprint.py` runs the arithmetic on fixed kubelet, pod, node and tab responses, and
  checks that the script refuses to run without `CONTEXT`. The script was smoke-run against a stub kubectl and a
  mock Backstage (pass, an empty tab, an unreachable portal), not yet against a cluster.
## 2026-10-24 · #470 · A test that nothing escapes the IAM policy pipeline, org policies included

#207's org half still has no SCP to put through the pipeline (it waits on org access, #202), so the test holds
the route one must take rather than one already taken. `verify/test_iam_policy_coverage.py` (offline) fails when:

- a Terraform root outside `pipeline.ROOTS` gains an `aws_iam_*`, `aws_organizations_*` or policy resource, an
  `aws_iam_policy_document` data source, or a module input whose name asks for IAM (`iam`, `polic`, `role`,
  `permissions_boundary`, `flow_log`);
- a resource carries a document `extract()` does not read: an IAM-shaped type it was not taught, or an inline
  resource policy (`aws_vpc_endpoint.policy`, `aws_sqs_queue.policy` and the like);
- an SCP or RCP stops reaching check 1 under its own Access Analyzer type, or check 3 in `pipeline.py` and
  `iam.rego` alike, or an Organizations policy type with no check stops failing the run;
- the boundary stops denying, or check 4 stops asking about, any org-policy write.

**Choices made:**
- **`pipeline.ROOTS` names the roots in one place.** The CLI's `--suite` choices and `iam_plan_render.ROOTS`
  read from it, and the test holds `effect-tests.yaml`'s suites to the same set, so a new org-policy root must
  join all four.
- **Five boundary effect cases added** next to `organizations:DetachPolicy`: AttachPolicy, CreatePolicy,
  UpdatePolicy, DeletePolicy and DisablePolicyType, each `explicitDeny`. They run in `test_iam_policy_aws.py`
  (E2E), which has not yet run them against AWS.
