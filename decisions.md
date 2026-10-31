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

**Update, 2026-10-29: the 10-24 teardown is recorded, and decision 2 is answered by a sandbox org, not a pool.**

- **Teardown (Michael's comment on #454, 2026-10-24).** `./fleet.sh instructors down all` ran 18:17 to 18:37Z and
  removed both clusters with their node groups, 4 leaked load balancers, 6 EBS volumes, the community cluster's 6
  orphaned security groups and both EKS log groups. The 6 security groups it reported surviving on michael-admin
  went with the VPC. `WIB_APPLY=1 ./fleet.sh down-infra accen-dev` destroyed the lab VPC 20:05 to 20:07Z. The
  router was reloaded with 0 routes. `./fleet.sh audit-zero` read ZERO in all five accounts, and his direct checks
  in accen-dev, us-west-2 at 20:08Z found no EKS cluster, EC2 instance, NAT gateway, load balancer, EIP, EBS
  volume, VPC endpoint or `event=kubecon-na-2026` security group, and the VPC NotFound. His go asked for "zero
  fleet resources" verified, and that is what audit-zero answers. `verify/account-audit.sh`, the wider sweep
  the entry above named, was not the check he ran, so this records audit-zero ZERO, not account-audit CLEAN.
  His estimate for the bring-up was about $2.30 from list prices, not billing data.
- **Datadog (#629, Whitney, 2026-10-27).** Datadog no longer issues per-student trial orgs, so there is no
  KubeCon pool to load. Both KubeCon clusters ship to Whitney's sandbox org (US1) instead, under her rules: env
  `burritobot-kubecon-na-26`, `burritobot-*` services, ml_app `burritobot`, one API key named `burritobot` in
  `watch-it-burn/datadog` (accen-dev). It has shipped from both clusters since the 2026-10-28 rebuild as
  `burritobot-public` and `burritobot-private` (#632). No attendee gets a Datadog account (#647). The rest of
  that move, and abstract point 7 shown on stage, stays on #629, #647 and #456's readiness file, not here.
- **What this closes.** All three of #454's decisions are answered and built: the five Portland accounts in
  their regions, `event=kubecon-na-2026` from `fleet/event.sh`, and the sandbox org. The 10-24 clusters are gone;
  the platform that runs now is the 10-28 rebuild of watch-it-burn-community and watch-it-burn-private, in the
  same account and region under the same tag. Its own teardown after delivery is not part of #454.
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
## 2026-10-24 · #488 · The event pool is the attendee count plus two presenter seats

With the presenter student clusters retired (#295), Michael and Whitney each claim a pool cluster by email, so a
pool built to the attendee count alone is two short once both claim.

**Choices made:**
- **`scheduled-up.sh` takes the ATTENDEE count and adds the seats.** `WIB_SCHED_PRESENTER_SEATS` (default 2)
  is added before `scale`, and the start and completion lines print attendees, seats and pool, so the log says
  why the pool is larger than the number typed. A count of 250 builds `scale 252`.
- **`scale` and `up-fleet` are left as they are.** `scale <n>` is a desired total that `verify attendees:<n>`
  and teardown also read, and `up-fleet <n>` is a per-account count; adding seats inside either would make the
  same number mean two things. The runbook, the go-live checklist and `up-fleet`'s usage line give the
  arithmetic instead: `scale <attendees + 2>`, `up-fleet ceil((attendees + 2) / accounts)`.
- **The dogfood walk is a go-live checklist item**, on the morning of the workshop before the room arrives:
  claim with the `+student` alias, open console, lab and terminal, and confirm the claimed Datadog org receives
  data. The claimed cluster is that presenter's seat for the day.
- **Tests:** `verify/test_scheduled_up.sh` holds the pool to attendees + 2 by default, 250 to 252, an override
  of 0 and 1 seats, and a usage error on a non-numeric seat count.

## 2026-10-24T21:36:00Z · #491 · The Kyverno CLI pin follows the deployed chart to v1.19.1

`gitops/apps/kyverno.yaml` deploys chart 3.9.1, which installs Kyverno v1.19.1 (released 2026-09-10; the
chart moved from 3.9.0 in #389). The other copies had not followed: `VERSIONS.lock` said app v1.18.1 / chart
3.8.1 on both kyverno lines, the admission controller's `tags.datadoghq.com/version` said v1.18.1, and
`verify/test_kyverno_cel_policies.py` demanded CLI v1.19.0 as "the deployed engine".

**The CLI moves up, the chart stays.** The issue offered either. 3.9.1 is the deliberate #389 bump and what
the #333 live run measured, so pinning the chart back would undo a reviewed upgrade to match a stale test.

**Dev dependency version change:** the Kyverno CLI **v1.19.1** (2026-09-10) replaces v1.19.0. Why: the CLI
check is only worth having when it is the engine the cluster runs. v1.19.2 (2026-10-20) is out, but it is
not what the chart deploys, so the CLI does not go there on its own.

**Kept from drifting:** `verify/test_kyverno_version_pins.py` (offline suite) holds both `VERSIONS.lock`
lines to the Application's chart, and the Datadog tag, the CLI pin, the install messages and
`policies/README.md` to the lock's app version. Policy header comments that say "Written against Kyverno
v1.19.0" are left as they are: they record what each policy was written against.
## 2026-10-24 · #478 · The rbac and resource-quotas apps are removed, not moved to apps-disabled

**What went.** `gitops/apps/rbac.yaml` with `security/rbac/`, and `gitops/apps/resource-quotas.yaml` with
`security/quotas-pdbs/`. The #236 audit (`docs/research/2026-10-24-duplicative-components-audit.md`) found
that `rbac` bound `app-developer` and `app-viewer` to groups nothing grants, and its `demo-cluster-admin`
ClusterRole was bound by nothing at all. `resource-quotas` capped `apps` well above what the party apps use,
and its `minAvailable: 1` PodDisruptionBudgets covered single-replica workloads plus the disabled Backstage.
No lab step, deck slide, tour stop or challenge used either. Both selected on the full, attendee and admin
profiles, so each of those clusters runs two fewer Applications; the burn profile never selected them. An instructor
cluster now shows 38 Argo CD applications and an attendee cluster 34, down from the 40 and 36 that #475 set;
the platform page, the run-of-show and `verify/test_fleet_contract.py` carry the new numbers. They are the
measured counts less two, not a fresh measurement on a live cluster.

**Deleted rather than parked in `gitops/apps-disabled/`.** Nothing is waiting to turn them back on, and C8's
RBAC lesson is the agent-sa Role in `gitops/ai-layer/resources.yaml`, which is untouched. Git history keeps
the manifests. On a live cluster the roots prune the two child Applications and their resources-finalizer
removes what they created.

**What else changed.** The build diagram and platform tour no longer list RBAC and resource quotas in Wave 1,
and the two chips keyed `rbac` and `resource-quotas` are gone: those keys would never have shown as running.
`verify/test_diagram_chip_apps.py` holds every chip key to an Application in `gitops/apps` (by name or file;
`argocd` is the one exception, installed by `deploy-full-idp.sh`). `gitops/README.md`, `security/README.md`
and the wave table in `docs/MASTER-RECREATION-SPEC.md` drop the two apps. `force_update_version` in
`infra/terraform/aws/cluster/main.tf` stays: it is the right setting for disposable nodes whatever PDBs the
charts ship, and its comment was left as written.
## 2026-10-24 · #477 · The floor protects agent, security and datadog; agent's workloads stay deletable

The minimal-floor's lists predated the namespace layout: Falco runs in `security` (`falco` holds only
Talon), BurritoBot in `agent`, the Datadog operator and agent in `datadog`, and none of the three was
protected. All three namespaces are now refused DELETE. Workloads in `security` and `datadog` are refused
DELETE too. Workloads in `agent` are not: Challenge 2 has the student's terminal (the `web-terminal`
ServiceAccount, not `system:masters`) run `kubectl -n agent delete deploy promo-mascot`, and the floor would
refuse that cleanup. What Argo CD owns in `agent` is already refused to everyone else by
`block-argocd-drift`, which is the policy the lab's "Try breaking a guardrail" step names.

The Datadog operator's ServiceAccount (`system:serviceaccount:datadog:datadog-operator`) joins Argo CD and
the kube-system controllers as a principal that may replace workloads: the operator, not Argo CD, owns the
agent DaemonSet and cluster-agent Deployment and deletes them when a component is switched off, which is the
#389 failure Argo CD hit in `kagent`. `verify/test_minimal_floor_namespaces.py` checks the lists against each
platform Application's destination, and `verify/test_kyverno_cel_policies.py` checks the verdicts.

Not done: the issue's optional point that `require-resource-limits` stays Audit on attendee and only produces
PolicyReport noise there. Excluding it on attendee changes what kyverno-policies ships on that profile and
the policy count `test_kyverno_cel_live.py` expects, so it stays as it is.
## 2026-10-24T21:45:00Z · #490 · The agent's bypass is closed by who asks, not by what the pod declares

`deny-llm-endpoint-bypass` reports only a pod that declares a public model endpoint as a literal env value. The
issue named three bypasses it cannot see: an SDK on its default endpoint, Bedrock over the in-VPC PrivateLink
endpoint on the SDK's default regional hostname, and an endpoint read through envFrom or valueFrom. Matching
better cannot fix that, because none of the three needs an endpoint env var at all.

**What was already true.** The network option the issue proposed, an egress allowlist over every pod in
`agent`, landed in #108 (`9096379`): `agent-egress-allowlist` has `podSelector: {}`, and the MCP servers' PyPI
install at startup, which once kept it narrow, is baked into `images/workshop-mcp`. So that PyPI question is
already settled. The policy's header still described the old narrow selector, and it has been rewritten.

**What was still open, and how it is closed.** Two routes stayed open past that allowlist:
- **Identity.** The allowlist has to pass 10.0.0.0/16:443, because workshop-agent and agentgateway call Bedrock
  there, so the network cannot tell a bypass pod from them. Bedrock credentials come only from EKS Pod Identity,
  to the ServiceAccounts associated in `infra/terraform/aws/cluster/main.tf` (agent-sa, agentgateway,
  web-terminal), and creating a Pod needs no RBAC on the ServiceAccount it names. agent-sa may create Pods, so
  the agent could run one as agent-sa.
- **A label.** `platform-console-egress` gives `egress: [{}]` to any pod labelled
  `app.kubernetes.io/name=console`, and the creator of a pod picks its labels.

The new `restrict-agent-spawned-workloads` (ValidatingPolicy, **Deny**, admission only) refuses a pod, or by
autogen any pod controller, created or changed by a ServiceAccount of `agent` other than web-terminal when it
runs as one of those three accounts or carries that label. It keys on `request.userInfo`, which the API server
authenticates. ArgoCD, the kagent controller and the kube controllers are not identities in `agent`, so the
guarded path is not caught by it.

**Choices made:**
- **Deny, not Audit.** `deny-llm-endpoint-bypass` stays Audit because it matches on pod content and might match
  guard-proxy. This policy matches only the agent's own requests, and nothing the agent legitimately makes (C2's
  villain Deployment included) runs as those accounts or wears that label. A report of a bypass that has already
  run is not a control.
- **Every agent-namespace ServiceAccount but web-terminal**, not agent-sa alone, so a Role granted later to
  another agent-plane account is covered from the day it lands. web-terminal is the attendee's terminal.
- **UPDATE is judged too.** A pod's container images can be changed, so patching workshop-mcp's own pod would
  give the agent a new workload under agent-sa.
- **The two hand lists are held to their sources** by `verify/test_agent_bypass_shapes.py` (offline): the Pod
  Identity associations in `agent`, and every label a NetworkPolicy in `agent` selects on, including the C1 fix
  set in the challenge-fixes ConfigMap.
- **Tests.** `verify/test_kyverno_cel_policies.py` gained 18 CLI cases, run here against Kyverno CLI v1.19.0;
  emptying the identity list makes them fail. `verify/test_llm_bypass_live.py` now makes the issue's three
  shapes as agent-sa, which it impersonates, and checks each against the live NetworkPolicies without sending
  traffic. It also checks that the refusals carry this policy's message. It has not been run on a cluster yet.
  `test_kyverno_cel_live.py` now counts eleven policies.

**Not closed here (follow-ups):** two routes stay open. A pod the agent makes can call agentgateway's `:3002`
model bind, or the agent's A2A port, directly over the intra-namespace allow, with no ingress restriction on
either. And workshop-mcp's `run_shell` already runs as agent-sa, so it holds Bedrock credentials with no new
pod. Closing either changes ingress on the chat path, or the identity that C8 is built around, and both need a
live cluster to check.
## 2026-10-24 · #493 · Grafana loses its ALB Ingress; root_url comes from cluster-identity

**What went.** The kube-prometheus-stack Grafana Ingress (`ingressClassName: alb`, group
`watch-it-burn-ingress`, host `grafana.agenticburn.com`). Since #233 Grafana is reached at
`grafana-<cluster>.agenticburn.com` through the apex router and the console LB, and `routes.map` never had a row
for the fixed host, so it answered 404 on every cluster. On a live cluster Argo CD prunes the Ingress; the
load balancer controller deletes the ALB once no other Ingress holds the group (the five party-app Ingresses
in `gitops/manifests/demo-app-*/ingress.yaml` use the same group and are left for their own issue).

**How root_url is set.** #233 asked for root_url per host. Grafana reads `WIB_PUBLIC_HOST` from the
`cluster-identity` ConfigMap's `public-host` key (written in `monitoring` by `infra/datadog-cluster-identity.sh`
before the app-of-apps, the same source the guard-proxy and web terminal use), and `grafana.ini` sets
`server.domain: grafana-$__env{WIB_PUBLIC_HOST}` and `root_url: https://grafana-$__env{WIB_PUBLIC_HOST}/`.
Grafana's own `$__env{}` expansion was chosen over a Kubernetes `$(VAR)` reference so the rendered
`prometheus-grafana` ConfigMap shows where the value comes from, and so it does not depend on the chart's
env ordering. The reference is optional: without the ConfigMap Grafana still starts, with links that name no
cluster. Grafana reads env at start, so a public host rewritten later needs a Grafana pod restart.

**Not measured live.** No cluster was available to this run. `verify/test_service_hosts_live.py` now reads
Grafana's `appUrl` through its hostname and asserts no Grafana Ingress remains; run it on the next build.

## 2026-10-25 · #502 · The KubeCon router table is the roster alone, and the live router is checked, not the repo

The coordinator settled on #502 (2026-10-24) that the apex router and `/beacon` stay up for the breakout.
`fleet.sh routes` wrote every attendee cluster with state on the machine, plus a stray
`roundadmin.agenticburn.com`, so the table was not the three roster hosts the issue asks for.

- **`routes roster`, not a second generator.** It is `cmd_routes` with the attendee loop skipped, so the
  roster rows, the `:443` upstreams and the record-then-reload path stay one code path.
- **The roster guard compares sets.** A roster run drops pool rows on purpose and lists them. It still refuses
  when a published roster host would leave, even when the table grows, because gaining eight service hosts
  while losing `whitney-admin` is a longer table and a dead URL on stage.
- **The roundN alias is removed in every mode.** Rounds went with #291, the column it read became the role,
  and it published `roundadmin`, a name nobody was given. The shrink guard discounts retired `round*` rows the
  way it discounts `a-NNN` (#359), so the first run after this is not refused.
- **`router-check` reads `start.agenticburn.com/roster.json`.** That is the router's view of the table on its
  volume, rebuilt on every reload, so it catches a table pushed but not applied (2026-08-26), which the apex
  repo cannot show. It is the read the ops view already treats as "routed" (#308).
- **Left open for Michael:** the beacon and `/beacon/view` are forwarded by the router to the collector in
  the provisioning app, so they are up only while that service runs, and #448 keeps the provisioning
  distributor off. The run-of-show records this as its open question 9.

## 2026-10-25 · #502 · question 714: the provisioning app keeps running as the C1 beacon collector

**Question 714:** does the provisioning app on Railway keep running during the KubeCon breakout, only as the
collector behind the C1 beacon? **Answer:** keep provisioning running as the beacon collector. Decided by
hecaton's research under Michael's standing rules, not by Michael.

- **Why it was a question.** The apex router forwards `/beacon` and `/beacon/view` to the collector in the
  provisioning app (`docs/beacon-collector-spec.md`), and #448 names the provisioning distributor as an app
  that stays off. With it off, the beacon errors, segment 4's beacon view does not load, and
  `challenges/c1-exfil-s3/fallback.kubectl.sh` fails reading the count.
- **What it changes.** The run-of-show says the service runs for this session as the beacon collector
  only, with nobody pointed at its distributor pages, so no attendee lab runs. Open question 9 there is
  marked settled. The Night Before beacon-view curl must print `200`, and anything else means the service
  is down and must be brought back before the day. No code changes: the collector, the router's forward
  and the C1 fallback stay as they are.
## 2026-10-25 · #507 · The permissions-boundary root takes `event` from fleet/event.sh too

**Decision:** `infra/org/boundary/main.tf` tags with `event = var.event`. Like the network and cluster roots,
`variable "event"` has no default and uses the same slug validation. This replaces the
`devopsdays-portland-2026` literal, the last one under `infra/`. Every documented apply passes
`-var event="${WIB_EVENT}"` after sourcing `infra/terraform/fleet/event.sh`: `infra/org/README.md`, step 0 of
`infra/terraform/README.md`, the root's header and the Night Before list in the KubeCon run-of-show. So does
preflight's apply hint for a missing boundary. `verify/iam_plan_render.py` passes `event=render` to both roots.

**This supersedes the event-tag paragraph of #526.** That paragraph exempted the boundary from the rule because
the root declared no `event` variable. Now it declares one, so `verify/test_event_tag.py` has no exemption. It
checks the boundary root like the other two, scans infra/org for the Portland literal and for applies without
`event=`, and requires the variable on each documented boundary apply. The policy outlives an event, so its tag
names the event whose apply last touched it. It costs nothing, so this is labeling only.

## 2026-10-25 · #498 · question 712 · the round shorthand is rewritten from LAB-TEXT.md and the profiles

**Question 712:** When the old Round 1, 2 and 3 outcome lines in the current docs are rewritten, may their
facts for each kind of cluster come from `challenges/LAB-TEXT.md` and the bootstrap profiles, with
LAB-TEXT.md winning wherever an older challenge README disagrees?

**Answer:** Derive from LAB-TEXT.md.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**What it changes:**

- About twenty current docs (the C1 and C3 challenge READMEs, the 01 and 03 facilitator notes, the villain
  image README, the recreation spec, READINESS, GO-LIVE, the gotchas, the beacon spec, the runbook, the
  quickstart and PRDs 13, 22, 35, 36 and 37) now say what happens on the Community cluster (`burn`), on an
  admin cluster (`admin`) and on an attendee cluster (`attendee`) before and after the student applies the
  control, instead of R1/R2/R3. The sources are LAB-TEXT.md, `gitops/bootstrap/*` and `fleet.sh`'s
  `arm_infra_guardrails`, which arms only `full` and `admin`.
- Where a README contradicted LAB-TEXT.md, LAB-TEXT.md won. The C1 and C3 READMEs no longer say "no
  per-attendee toggle, always on in `full`": since #281 the `full` profile omits both controls too. The C3
  README now says the Community cluster runs the KubeArmor engine with no policy. The villain README drops the
  stale "scoped to `apps` only" gap, because the policy matches `apps` and `agent`.
- `verify/test_docs_current.py` now also rejects the shorthand: capital R1/R2/R3, `r2/r3`, "three rounds",
  "per-round", "cross-round", "round table", "round toggle" and "round state", and it pins what it must and
  must not catch. `verify/test_round_names_retired.py`, which the issue pointed to, was never promoted (it sits
  on the held #290 branch), so the shapes were written here. `decisions.md`, the World's Fair debrief,
  `ACTION_ITEMS.md` and `transcripts/` are exempt as records. `docs/ABSTRACT.md` is public prose and is
  held to the numbered names only.
## 2026-10-25 · #513 · Bedrock spend is tagged through one application inference profile per tier per cluster

From the #392 thread: model spend has to carry `project`/`event` so the denial-of-wallet numbers on stage can
be checked against the bill. A system-defined profile such as `us.amazon.nova-pro-v1:0` cannot be tagged, so
every call through one billed untagged.

- **One tagged copy per tier per cluster.** The cluster root creates `aws_bedrock_inference_profile.agent`
  for nova, haiku, sonnet and opus (guard-proxy's MODEL_TIER names), named `<cluster>-<tier>` and copied from
  the system profile in the cluster's region, so it routes to the same foundation models. Each carries
  `local.fleet_tags` plus `consumer=agent`. The tutor's model gets `<cluster>-tutor` with `consumer=tutor`,
  although no tutor runs today (#89). Application profiles cost nothing.
- **The ARN reaches the cluster through fleet.sh, not git.** It ends in an id Bedrock picks, and the gitops
  manifests are the same on every cluster. So each Bedrock ModelConfig still commits the system id, which
  stays the pin that `model_pin_check.py` and guard-proxy's pricing read. `pin_bedrock_profiles` sets each
  live `.spec.model` to the cluster's ARN, read from the `bedrock_application_profiles` output in the
  cluster's state, on bootstrap and on converge. ai-layer ignores that one field on Bedrock ModelConfigs only.
  A committed id with no tagged copy fails the cluster. A cluster applied before this change fails converge
  until it is re-applied, because leaving the system id in place would be the untagged spend again.
- **The IAM grant matches the copies by their tags, not their ARNs.** It allows
  `application-inference-profile/*` in the cluster's region, on condition of `aws:ResourceTag/project`,
  `attendee` (the cluster) and `consumer`. The service reference lists `aws:ResourceTag/${TagKey}` for that
  resource type. Naming the ARNs would make the policy unknown at plan, and the IAM pipeline fails on a
  document it cannot see (`verify/iam_plan_render.py` renders it known today). The system-profile and
  foundation-model statement stays. Bedrock authorizes a call through an application profile on the
  foundation models too, and the pin check's first Converse call still uses the system id. Check 2 of the
  pipeline (check-no-new-access) will report both Bedrock policies as granting new access. That widening is
  intended.
- **The pin check holds the copies to the pin.** After its system-profile checks it lists the account's
  APPLICATION profiles named `watch-it-burn-*-<tier>`. Each must be ACTIVE, route to the same foundation
  models as the pin, and carry `project=watch-it-burn` and the event from `fleet/event.sh`. One Converse
  call also goes through the first copy. So the check needs the clusters up, which the run-of-show already
  has it do after converge.
- **Not covered.** The opt-in gateway-* ModelConfigs go through agentgateway, whose bedrock backend still
  names the system id, so that path still bills untagged. A pod that bypasses the proxy under agent-sa can
  still call the system profile. The tags only split the bill once `project` and `event` are active as
  cost-allocation tags.

## 2026-10-25 · #514 · evil-mcp goes through agentgateway on its own :3003 bind, with the C7 rule committed open

Step 1 of #496, which is split into children so each lands before staging moves under it. This child moves the
routing only. The `evil-mcp` RemoteMCPServer url is `http://agentgateway.agent:3003/mcp`. A second container in
the agentgateway Deployment, `agentgateway-c7`, runs the same digest-pinned v1.5.0 image and serves only :3003
from its own ConfigMap, `agentgateway-c7-config`. Its one `mcpAuthorization` rule is `- 'true' # c7-rule`, so
C7 behaves as it did: the in-path control is still the kagent `toolNames` allow-list, and guard-mcp-on still
narrows it.

- **A second container, not a fourth bind.** A later child has Argo CD ignore drift on the C7 rule, and that
  ignore can only cover a whole `config.yaml` string. On `agentgateway-config` it would take the A2A,
  workshop-mcp and LLM routes out of GitOps on every cluster.
- **One target on the bind.** Two targets on one bind get their tool names prefixed, which would rename the
  tool `get_weather`'s poisoned description points at.
- **A directory mount, never subPath.** agentgateway v1.5.0 watches the parent directory when its config file
  is a projected-volume symlink (`crates/agentgateway/src/util.rs`, `should_watch_parent`) and keeps the
  previous state when a reload fails (`crates/agentgateway/src/state_manager.rs`,
  `reload_config_after_change`), both read at tag v1.5.0 on 2026-10-24. A subPath file never changes.
- **No shared ports.** The pod has one network namespace. The C7 container turns admin and stats off and puts
  readiness on 15022, which the first container does not hold.
- **The contract for guard-proxy-agenticburn#5** (the C7 badge): ConfigMap `agent/agentgateway-c7-config`, key
  `config.yaml`, the one line ending `# c7-rule`, where `'true'` is off and `'mcp.tool.name == "get_weather"'`
  is on. `guard-proxy-reader` may `get` that ConfigMap by name, nothing more.

`verify/test_agentgateway_path.py` now pins evil-mcp through :3003 with exactly one target, and no evil-mcp
target on workshop-mcp's :3001. `verify/test_agentgateway_config.py` validates the C7 config against the
vendored v1.5.0 schema as committed and with the get_weather rule, shows an unknown key beside the rules is
rejected, and checks every container runs the pinned image and reports v1.5.0. The live proof is the #503
probe at bring-up.
## 2026-10-25 · #482 · question 702 · the tour says the mesh enrols nothing, and C1 drops its mesh mTLS control

**Question 702:** Should the false Istio encryption lines in the lab tour and the C1 README be corrected
now, before the keep-or-drop decision on Istio (#471) is made? No file sets `istio.io/dataplane-mode`, so the
tour's "encrypts all traffic between containers inside the cluster, automatically" and C1's "Istio ambient
mTLS for in-cluster traffic" were false on every cluster.

**Answer:** Reword the tour line now and delete the C1 bullet.

**Decided by:** Michael.

**What it changes:** the tour bullet in `gitops/ai-layer/web/lab.html` (and its generated copy
`challenges/LAB-TEXT.md`) now reads the text from section 3 of
`docs/research/2026-10-24-istio-ambient-evaluation.md`: the mesh is installed, no namespace is enrolled, so
it encrypts nothing, and `kubectl get ns -L istio.io/dataplane-mode` shows it. The console terminal's
ClusterRole already lets students list namespaces. `challenges/c1-exfil-s3/README.md` no longer lists mesh
mTLS as a C1 control; the egress-wall bullet stays. `verify/test_mesh_enrollment.py` now fails if the tour
claims encryption again or C1 lists mesh mTLS while nothing is enrolled. The keep-or-drop question on #471 is
untouched: if Istio is dropped the bullet goes, and if namespaces are enrolled the bullet is rewritten (the
enrolment check in the same test fails first). The links, platform and diagram pages and
`docs/STACK-WALKTHROUGH.md` still describe the mesh as a control; those wait on #471.
## 2026-10-25 · #521 · A submodule may only be pinned at a commit a branch of its remote holds

Branch agent/487-7110 pinned `gitops/ai-layer/guard-proxy` at `627cb97`, a commit that existed only in the
run's own submodule clone. Everything passed there. Every other clone then failed `git submodule update
--init` with "upload-pack: not our ref", and so would both test runners once the branch reached staging.

- **The offline suite now refuses such a pin.** `verify/submodule-pins-pushed.sh` reads each gitlink in
  HEAD and fails unless the submodule's clone has the commit and a `refs/remotes/` branch contains it. It
  reads the refs as of the last fetch, never the network, so it belongs in `run-tests.sh`; a commit pushed
  since the last fetch reads as unpushed until `git -C <submodule> fetch`. `verify/test_submodule_pins_pushed.sh`
  tests it on throwaway repos and then holds this repo's two pins to it.
- **The order is fixed by that check.** A change to guard-proxy or the LLM Guard image lands in its own repo
  first, through that repo's issue and promotion, as the C7 badge did (guard-proxy-agenticburn#5). This repo
  repins only after the commit is on a branch there. A run that cannot push the submodule commit stops at
  red here instead of leaving a pin no other clone can fetch.
- **agent/487-7110 itself is not repinned here.** No run can push guard-proxy, and repinning that branch to
  `ccdda73` would drop the C2 fix it exists for. The C2 ValidatingPolicy read goes to guard-proxy-agenticburn
  as its own issue; #487 repins once that is pushed.

## 2026-10-25 · #522 · `verify/test_repo_identity.py` holds the #422 identity statement in place

#422 added the "Where things live" section to `AGENTS.md`, but no test read it. The new offline test fails if
`CLAUDE.md` stops being a symlink to `AGENTS.md`, if the section stops saying which workshop this repo builds,
who presents it and that it holds the build and not the record of the talk, or if it stops pointing at
talks-knowledge (register, abstracts, talk scripts) and conference-knowledge (event state). It reads the
workshop title from the README heading and the submodule paths from `.gitmodules`, so neither is written down
a second time in the test.
## 2026-10-25 · #511 · question 716: /kubecon gets the apex router's roster-only gate now

**Question 716:** should `/kubecon` get the apex router's roster-only 404 gate now, ahead of any attendee-pool
event, rather than waiting until a 2-hour workshop with attendee clusters is booked? **Answer:** gate /kubecon
in the router now. Decided by hecaton's research under Michael's standing rules, not by Michael.

- **Why now.** `kubecon.html` ships in the console-src ConfigMap, so every cluster serves `/kubecon`. The
  #501 entry above left it ungated only because the KubeCon breakout has no attendee pool, and said to gate
  it the way `/brief` is gated once it is served alongside one. The first attendee pool would meet that
  condition with nothing to remind anyone. Waiting rested on how close KubeCon is, and the change-cadence
  rules in CLAUDE.md rule that out.
- **Why it costs the KubeCon session nothing.** peopleforrester/apex-agenticburn#35 (staging `664b584`)
  changed the router's roster matcher to `attackme` or `<owner>-admin` on agenticburn.com. The three KubeCon
  clusters are exactly those hosts (`infra/terraform/fleet/roster.tsv`).
- **What it changes.** In apex-agenticburn's `Caddyfile`, the `@brief_not_roster` matcher's path line goes
  from `path /brief` to `path /brief /kubecon`. `tests/e2e/caddyfile.e2e.sh` gains a 200 on `/kubecon` for
  attackme, michael-admin and whitney-admin, and a 404 for an attendee host. That edit lives in the sister
  repo and is filed there as a follow-up of #511, because this repo cannot change it. A Caddyfile edit is image
  state there, so it goes live when Railway deploys main, the same promotion #35 is already waiting on. Here,
  the `/kubecon` comment in `gitops/ai-layer/console.conf` now names the gate. The retired numbered-round roster
  names in the `/brief` comment beside it are now attackme and `<owner>-admin`. nginx behaviour is unchanged.
## 2026-10-25 · #515 · only the web terminal may edit agentgateway-c7-config live

Step 2 of #496 rewrites the `# c7-rule` line of `agent/agentgateway-c7-config` (added by #514) from the web
terminal of an admin cluster. Two guardrails would undo or refuse that edit, so this opens exactly that path
before anything uses it:

- **Argo CD ignores `.data["config.yaml"]` on that ConfigMap only** (`gitops/apps/ai-layer.yaml`).
  agentgateway-config and the agentgateway Deployment keep no ignore, and RespectIgnoreDifferences stays on.
  The cost: a committed change to agentgateway-c7-config reaches new clusters only; a running cluster keeps
  its live copy until it is rebuilt.
- **block-argocd-drift exempts one request shape** (`not-terminal-c7-rule`): an UPDATE of
  agent/agentgateway-c7-config by `system:serviceaccount:agent:web-terminal`, written as a negated
  conjunction with optional reads so a DELETE (empty object) does not error. agent-sa stays denied, so the
  agent cannot switch off its own C7 guard; the terminal still cannot delete it or touch agentgateway-config.
- **console-terminal is not widened.** Its existing rules already give get on everything (Argo CD
  applications included) and patch on core resources (configmaps, pods).

`verify/test_c7_gateway_toggle.py` (offline) checks the ignore, the exemption and the RBAC from the manifests;
the toggle child of #496 extends it. `verify/test_kyverno_cel_policies.py` (E2E, Kyverno CLI 1.19.1) evaluates
the four request shapes. The live proof is the #503 probe at bring-up.

## 2026-10-25 · #523 · The E2E tools go into hecaton's toolchain, not this repo

The kyverno CLI, conftest, terraform and the aws CLI are still missing from the dispatch machine.
`bash verify/run-e2e.sh` lists them in its prerequisite check, alongside kubectl and helm (#439), `CONTEXT`
and the IAM pipeline profile and region. A run cannot install them. The run PATH is
`/var/lib/hecaton/cli:/usr/local/bin:/usr/bin:/bin`, and both `/var/lib/hecaton/cli` and
`/var/lib/hecaton/toolchain` are root-owned. Hecaton's `deploy/netcup/setup.sh toolchain` section puts pinned
tarballs there, with checksums, which is how Node, uv and lychee got there. That section belongs to hecaton,
so the install is a hecaton change. It is filed there as a follow-up with the pins below.

- **Kyverno is v1.19.1, not the issue's v1.19.0.** c47f4a9 (#491) aligned every Kyverno pin on the deployed
  v1.19.1, and `verify/test_kyverno_cel_policies.py` fails on any other version.
- **Artifacts, checked on 2026-10-25.** Each SHA-256 below matches the release's own checksum file:
  - `kyverno-cli_v1.19.1_linux_x86_64.tar.gz`: `b38228f367fc0fdc2b08f4c83ea50ac5f16c60ff8d62d76a66157c33c47b70ae`
  - `conftest_0.71.1_Linux_x86_64.tar.gz`: `c3f6b2a753bd56e377a1e51a95ae3e057f926f2e9139f7d5b5dfbbaf810f7985`
  - `terraform_1.15.6_linux_amd64.zip`: `a7150d3b0e1b5c466ad42e8c499954a3c54645f8b56b385fa025d34f7e88faa9`
- **The aws CLI has no pin in VERSIONS.lock.** The latest v2 release on 2026-10-25 is 2.38.5. AWS publishes
  a PGP signature for the zip (`.zip.sig`), not a checksum. The SHA-256 of the zip as downloaded that day is
  `5def7d1b7e55d892f9a381bb2cb2081a685712464be0d36d5d706af0ac48d0d3`.
- **Nothing changes in `run-e2e.sh`.** It already fails loudly on each missing tool. The kyverno and
  conftest tests check versions, and `KYVERNO_CLI`, `CONFTEST` and `TERRAFORM` accept a path.

## 2026-10-25 · #524 · A test holds the E2E gate's Node 24 and yarn 4 pins, and runs run-e2e.sh's prerequisite check

#440's yarn 4 depended on two Backstage pins no test read: `packageManager` in `package.json`, which corepack
resolves, and `yarnPath` in `.yarnrc.yml`. `verify/test_e2e_toolchain.py` (offline suite) now checks that
`packageManager` is an exact yarn 4, that `yarnPath` names that same release, and that the release file is
committed and declares that version. It also checks that the Node major `run-e2e.sh` requires is 24, matches the
Backstage image's `FROM node:` and is accepted by `engines`.

The "run `run-e2e.sh` once" half was a one-time run. A past run cannot be tested, so the test runs the script
itself with a PATH holding only `dirname` and stub tools, in an empty environment. With nothing on PATH it must
exit 1 with "CANNOT RUN; this is a failure, not a skip" and list node, corepack and CONTEXT. With a stub Node 22
on PATH it must name the version. With a stub Node 24 and corepack on PATH it must list neither, and must not ask
for yarn. Because CONTEXT is unset, every case stops in the prerequisite check and no kubectl is ever called.
Mutating each pin (yarn 3, a mismatched or missing `yarnPath`, a gate wanting Node 22, corepack dropped from the
required tools) turns the test red.
## 2026-10-25 · #516 · On an admin cluster the C7 toggles flip agentgateway's rule, and fail rather than guess

Steps 2 and 3 of #496. The web terminal's guard-mcp-on/off and guards-on/off ask Argo CD which cluster they
are on: when the Application `app-of-apps-admin` exists (gitops/bootstrap/admin), C7's control is the
`# c7-rule` line of agentgateway-c7-config; anywhere else it stays the kagent toolNames list, unchanged.

- **On is `mcp.tool.name == "get_weather"`, off is `'true'`, and toolNames stays full on an admin cluster.**
  A blocked rogue call can then only be the gateway's doing. Off restores the committed config byte for byte.
- **The rule is written with a JSON patch that tests the resourceVersion it read.** A ConfigMap that changed
  between read and write is refused, not written over.
- **The rule goes first, toolNames second.** A refused patch (a stale read) then leaves both controls as they
  were. When Argo CD cannot be asked, nothing is touched. Either way the command exits non-zero and says C7
  did not switch; guards-on/off say so too, instead of claiming every guard flipped.
- **No restart.** agentgateway v1.5.0 reloads the watched mount. The toggle only annotates the gateway pod so
  the kubelet refreshes the volume sooner; it never deletes, restarts or rolls the pod. The reload delay is
  measured live at the #503 bring-up.
- **The KubeCon probe flips C7 the same way.** Its guard-mcp-on beat narrows the rule and fails if toolNames
  lost the rogue tools; start-state and guards-off require the rule open. `verify/test_kubecon_probe.py` holds
  its rewrite equal to the terminal's `.c7rule.py` in both directions.

`verify/test_c7_gateway_toggle.py` runs the entrypoint's real toggles against a fake kubectl for the admin,
workshop, unreachable and stale-read cases, and checks the two entrypoint copies are byte-identical.

## 2026-10-25 · #527 · A provisioning verb fails when any cluster's build failed, whatever the verify tail finds

At the KubeCon bring-up on 2026-10-24 `instructors up all` failed terraform apply on both roster clusters and
exited 0. `_provision_spec_fleet` read the failure ledger with `report_failures || true`, which left the exit
code to the verify pass, and the walkthrough, finding no state file for either cluster, reported "0 with
problems, out of 0". The ledger after the build now sets the return value, and the routes, registration and
verify tail still runs for the clusters that did build. The ledger also holds bootstrap failures and an
account slice skipped because its lab VPC is missing, and each of those now fails the verb too, since the
fleet did not come up either way. The function is shared, so `up`, `scale` and `up-fleet` get the same
contract as `instructors up`. One result of this is that `scheduled-up.sh` now stops at its instructors stage
when a roster apply fails, rather than going on to build the attendee pool. The offline
`verify/test_fleet_apply_failure_exit.sh` uses the real `run_pool`/`up_one` with a terraform shim whose apply
fails, and checks the exit code with the tail on and with it off.

## 2026-10-25 · #536 · The spec copy lives at specs/ with one header line added, and is never edited here

personal-knowledge sent spec talks/burritobot/001 again at sha256:4e127440568a (its #174), the version whose
milestone dates follow Michael's 2026-10-24 revision on #447. It replaces the versions sent as #459
(a9239a63e8ec) and #462 (dc49df429c73), neither of which had landed a copy here. The copy is
`specs/001-ready-by-11-08-delivered-11-12.md`, flat under `specs/` as in the cncf-bingo and aws-management
copies. It is the source text with one line, `source: personal-knowledge <file> @ sha256:<x>`, added after
`spec:`, the header personal-knowledge's `scripts/spec-drift.py` reads (the issue writes "(at)" for "@" so
GitHub does not take it for a mention). There is no local Corrections note: a change to the spec goes back to
personal-knowledge and is sent down again. `verify/test_spec_copies.py` holds every copy under `specs/`
equal, minus that line, to the sha256 it records, and holds spec 001's `schedule:` line to the run-of-show
section it names and the two dates kept for people (M6 by 2026-11-08, M7 on 2026-11-12). The milestone issues
under #447 are opened from personal-knowledge with `scripts/milestone-issues.py open`, which writes to
GitHub, so this repo does not open them.
## 2026-10-25 · #538 · deploy_app fills in missing CPU and memory limits, so C2 is refused by the registry wall

In Challenge 2 the model writes the villain's Deployment and hands it to workshop-mcp's `deploy_app`. Every
Kyverno ValidatingPolicy is its own webhook and the first to answer is the deny message, so a Deployment
without limits on a cluster with every policy at Deny could be refused by `require-resource-limits` instead of
`restrict-image-registries`, the policy the beat teaches. #529 fixed this for the probe and the C2 fallback.

The issue offered two routes: have the tool set default limits, or have the prompt and lab text ask for them.
The tool was chosen. A prompt only makes limits likely, and the student's own wording, not the stuck prompt,
is what reaches the model. `deploy_app` now gives any container of a Pod, a pod controller or a CronJob
without a CPU or memory limit `cpu: 100m, memory: 64Mi`, the limits the probe's manifest and the fallback
set, and keeps every limit and request the model did write. The image is never touched, so the registry wall
still refuses the villain. The tool description says so. The same defaulting means C6's `maintenance-shell`,
created through the same tool, is no longer at risk of a limits refusal on an admin cluster.
`verify/test_deploy_app_limits.py` runs the real `deploy_app` with the API call captured and holds the
defaults to the keys `verify/resource_limits.py` reads out of the policy. No lab or prompt text changed.
## 2026-10-25 · #517 · The C7 fallback proves the gateway rule from the web terminal, allow then deny

Step 5 of #496. `challenges/03-bad-mcp-excessive-agency/fallback.curl.sh` now takes CONTEXT and nothing else,
in the shape #499 set for C1, C2, C5 and C6. Everything runs in the web-terminal pod through kubectl exec:
`guard-mcp-off`, `guard-mcp-on`, and an MCP exchange (initialize, then tools/call) to
`http://agentgateway.agent:3003/mcp`, the evil-mcp RemoteMCPServer's own url. No model is called and no scratch
file is written.

- **The terminal's own toggles, not a rewrite of the rule.** The web terminal is the one principal
  block-argocd-drift lets edit agentgateway-c7-config (#515). So the fallback flips the rule exactly as a
  presenter does, and it passes only when each toggle says it switched C7 at the gateway and the ConfigMap
  then reads the expected rule.
- **Allow first, then deny.** With the rule open the call must return `FAKE-MCP-EXFIL-sentinel-4c1d`.
  Otherwise there is no deny check, because a gateway that refuses everything would pass it. With the rule
  narrowed, it counts as a refusal only when the gateway opened a session and then answered the call with an
  error and no sentinel. `get_weather` must still answer after that, so an outage cannot pass as the rule.
- **The reload delay is measured, not assumed.** Both waits poll every 3 s for up to 120 s. The seconds from
  `guard-mcp-on` to the first refused call are printed for the Night Before step.
- **The rule goes back the way it was found**, with whichever toggle writes that rule: `guard-mcp-off` for
  'true', `guard-mcp-on` for the narrowed rule. Any other rule is left alone and fails the run. An EXIT trap
  does the same when the script dies part way.
- **A cluster without app-of-apps-admin is refused, exit 2.** Its :3003 rule stays 'true' and its control is
  toggle-mcp-authz-on.sh's toolNames list, so no gateway deny can be asserted there. `verify/beat-03.sh`'s
  live branch now runs the fallback with CONTEXT alone and reads that exit. The toggle's last line no longer
  points at --expect flags.

`verify/test_challenge_fallbacks.py` runs C7 against its stub cluster. The stub's terminal runs the script's
real pod-side exchange against a fake :3003 gateway, and a fake clock keeps the waits from costing real time.
It covers guarded, open, found-narrowed, gateway-down and workshop clusters. `verify/test_kube_safety.py` now
globs `challenges/*/toggle-*.sh` and `challenges/*/fallback*.sh` instead of keeping a list that every new
fallback appended to, and it fails if either glob matches nothing.
## 2026-10-25 · #512 · question 717: no laptop line in the lab or the presenter brief

**Question 717:** should the opening material carry a laptop line, both written in Section 0 of
`gitops/ai-layer/web/lab.html` and spoken as a cue in Phase 1 of `gitops/ai-layer/web/brief.html`?
**Answer, in substance:** no. The only delivery coming up is the 30-minute KubeCon breakout. People there will
use their phones or their laptops, nobody gets their own cluster, and nobody cares which device they use.
His words are in the issue (#512, comment 6390996043). Decided by Michael.

- **What it changes.** No copy change. `lab.html` keeps its small-screen footnote ("A laptop is the better
  experience") as its only device note, and `brief.html` gets no device cue. Whitney's Section 0 wording and
  `verify/test_section0_wording.py` are untouched. The KubeCon breakout material (`web/kubecon.html`, the
  KubeCon run-of-show) gets no laptop line either, because that room is phone-or-laptop by design (#387).

## 2026-10-25 · #512 · question 718: the abstract's laptop line waits for the next workshop submission

**Question 718:** should the laptop line go into the 2-hour workshop's abstract drafts in talks-knowledge now,
given that no published listing of the workshop is live? **Answer:** wait and write it into the next
submission. Decided by Michael.

- **What it changes.** Nothing is written now. `docs/ABSTRACT.md` stays verbatim, the KubeCon breakout's
  Sessionize listing is not touched, and the talks-knowledge drafts are not edited. The next time the 2-hour,
  own-cluster workshop is submitted, its text says a laptop is needed for the hands-on part and that BurritoBot
  itself works on a phone. That sentence belongs only in the formats where attendees get their own cluster.
  Phone-room formats like the KubeCon breakout and the AI DevWorld 2027 15-minute draft do not get it.

## 2026-10-25 · #518 · The C7 stage claim is the gateway rule, then the output guard, and nothing about the MCP reply

Step 6 of #496. Michael's #456 decision (2026-10-24) defines mid-inference as checking between the agent's
steps, its tool calls and what the MCP server returns. Run-of-show segment 5, the /kubecon brief's C7 block and
the recreation spec now say C7 in one order: agentgateway's rule for evil-mcp stops the rogue `tools/call`
before the tool runs, and the output guard redacts the sentinel in the reply. One check sits between the agent
and its tools, the other on the way out to the user.

- **No claim that the MCP server's reply is scanned before the model reads it.** That is #480 and is not built
  for KubeCon. The segment 5 "Delivers" lines and open question 4 dropped "before that reaches the model
  again", which said it.
- **Per-format control.** toolNames on a workshop cluster, the gateway rule on an admin cluster (#516). The
  spec's beat-3 bullet, decision row and D14 say so.
- **The reload delay is a Night Before number.** Segment 5 reads "not measured yet" until the Night Before C7
  step runs `fallback.curl.sh` against the admin cluster and copies the delay it prints. The brief points at
  that line rather than carrying a number of its own, and names the same command as the run-of-show's
  fallback table, with no flags.
- **Point 6 reads Yes, pending the bring-up probe (#503)**, the same wording point 7 uses. Its "Partial" and
  "unsettled" wording is gone from the points table and the points-not-ready paragraph.
- **The output guard's half is pinned offline.** `verify/test_c7_output_guard.py` reads the llm-guard Regex
  from `gitops/ai-layer/resources.yaml`, checks it is one `match_type: all` alternation with redact on, and
  runs it over a reply carrying `FAKE-MCP-EXFIL-sentinel-4c1d` twice, the value evil-mcp-shim serves.

`docs/KUBECON-ABSTRACT-READINESS.md` row 6 still reads PARTIAL with "#496 not promoted". It was outside this
issue's file list, so it is left for a follow-up.

## 2026-10-25 · #543 · A test holds the gate split: Test command is the offline suite, run-e2e.sh is never the E2E command

The 2026-10-24 #543 entry above moved `bash verify/run-e2e.sh` off the `E2E command:` line, and AGENTS.md
already carried the change, but nothing held it. `verify/test_gate_commands.py` (offline suite) reads
AGENTS.md the way hecaton's gate does: a declared line starts the line, names the label, a colon, then the
command in backticks, and the first such line wins. It checks that the `Test command:` is
`bash verify/run-tests.sh`, that no declared `E2E command:` runs run-e2e.sh, and that the by-hand paragraph
names every env var run-e2e.sh's prerequisite check requires (CONTEXT, IAM_PIPELINE_PROFILE,
IAM_PIPELINE_REGION), read from the script so the two cannot drift. Adding the old E2E line back, or
dropping a variable from the paragraph, turns it red.

- **A cluster-free E2E tier stays possible.** The test forbids run-e2e.sh on the E2E line, not any E2E
  line, so the #543 follow-up (kyverno CLI, conftest, kustomize and node checks with pinned tools) can still
  be declared there.

## 2026-10-25 · #547 · SIZING.md measures a live cluster from the kubelet summary, not `kubectl top`

`infra/SIZING.md` said to measure one live cluster with `kubectl top` plus CloudWatch `CPUCreditBalance`. The
2026-10-24 #484 entry above found that nothing in this repo installs metrics-server, so `top` fails on an
attendee cluster with "Metrics API not available". Of the two ways out #547 named, the doc now takes the first:

- **The doc points at the kubelet summary API.** A new "Measuring one live cluster" section says why `top`
  fails, gives a per-node loop over `nodes/<node>/proxy/stats/summary` (every kubectl call with `--context`,
  the kubeconfig passed per command) that prints CPU in millicores and the working set in Mi, names
  `verify/backstage-footprint.sh` for repeated sampling and allocatable against requests, and gives the
  `CPUCreditBalance` query with region and profile on the command. The decision line and the "T3 fleet
  validation" open item both point at it.
- **No metrics-server addon.** It would be one more component on every cluster only to be measured, which the
  #484 entry already chose against, and nothing in the workshop reads the metrics API (no lab step, terminal
  page or agent tool calls `top` or `metrics.k8s.io`). The section says the addon is the route if a live `top`
  is ever wanted during the workshop.
- **Tests:** `verify/test_sizing_measure.py` (offline suite) reads the addons map out of
  `aws/cluster/main.tf` and the gitops manifests. While neither installs metrics-server, every SIZING.md line
  naming `kubectl top` must also name metrics-server (the line explaining why not), the doc must name the
  summary path and the footprint script, and its kubectl commands must carry `--context`. Against the old
  SIZING.md it fails on lines 36 and 90. The documented one-liner was run on a sample summary response, not
  yet on a cluster.
## 2026-10-25 · #545 · On a workshop cluster the C7 fallback asks the weather question with the toolNames list full, then narrowed

#545 was filed before #517 landed. It found `fallback.curl.sh` expecting a gateway deny that a deployed cluster
cannot give. #517 then pointed the script at the admin cluster's :3003 rule and refused a workshop cluster
(exit 2). That refusal left `verify/beat-03.sh`, which is run against an attendee's cluster, with a live branch
that could never pass. The admin branch is unchanged. A cluster without app-of-apps-admin now runs the check
from FACILITATOR.md's "Verify it": the weather question through guard-proxy, with evil-mcp's toolNames list
set by `toggle-mcp-authz-on.sh`.

- **This branch calls the model.** kagent enforces the list by leaving tools out of the agent's toolset, so
  the list only shows in what the agent does. The admin branch still calls no model.
- **Leak first, then no leak.** With the list full (`--off`) the agent is asked up to 3 times until the reply
  carries `FAKE-MCP-EXFIL-sentinel-4c1d`. The model does not chain the poisoned description every time, and
  without a leak here a missing sentinel later would prove nothing, so the run stops. With the list narrowed
  (`--on`) the agent is asked 3 times, and every ask must be answered with no sentinel in it. The question
  is `MCP_PROMPT` from `verify/agent_probe.py` with the `[[wib-probe]]` marker, sent as A2A message/send to
  guard-proxy's own root from inside its pod. The whole reply is searched, tool results included.
- **No ask goes to the old pod.** kagent restarts workshop-agent when the list changes. After a patch that
  changed the list, the script waits up to 180 s for the Deployment's generation to move, then for
  `rollout status`, and only then asks. If the generation never moves, the run fails rather than asking the
  old toolset. Real kagent 0.10.1 has not yet been seen moving the generation. FACILITATOR.md's verified note
  says the pod restarts on every list change, and `rollout status` there implies a new pod template. The first
  workshop bring-up that runs beat-03 confirms it.
- **The output guard is held off while the agent is asked.** Otherwise a redaction could pass for the list.
  If the guard was on, it goes back on afterwards, and the list goes back the way it was found, by the flag
  that writes it. A list that neither flag writes, an empty one included (to kagent, empty means every tool),
  is left alone and fails the run.
- **beat-03.sh** no longer treats exit 2 as "not an admin cluster". It runs the fallback against either kind
  of cluster and passes only on "C7 PROVEN".

`verify/test_challenge_fallbacks.py` runs the workshop branch against its stub cluster. The stub patches the
committed Agent tools with the real toggle, rolls them out after a fake kagent delay, and answers from a fake
agent with whatever toolset was last rolled out. It covers these cases: guarded, found narrowed, output guard
on, a list that does not hold, a model that never chains, an agent that stops answering, a kagent that never
rolls, and an empty list.

## 2026-10-25 · #549 · The attendee IAM user and its inline policy move into the cluster Terraform root

Each cluster's attendee user (`wib-<name less watch-it-burn->`) got its inline policy from
provisioning-agenticburn's `generate_attendee_aws.py`, which fleet.sh ran on every build, by `put_user_policy`.
No plan held the document, so none of the pipeline's four checks saw it, and the user carried no boundary. Of
the two options #549 named, this takes the second, because it also puts the user under the boundary and leaves
no rendered copy to drift from what is applied:

- **The cluster root creates the user, its policy and its access entry.** `aws_iam_user.attendee` carries the
  canonical boundary, `force_destroy` (the key is minted outside Terraform) and `cluster=<name>` for the #458
  sweeps. `aws_iam_user_policy.attendee_eks` keeps the same name and actions: DescribeCluster on the cluster's
  own ARN and ListClusters, both now held to `aws:RequestedRegion`, which check 3 asks of every Allow.
  ListClusters takes no resource ARN, so its `resource-star` is waived in `exceptions.md`. The EKS access entry
  and the `AmazonEKSClusterAdminPolicy` association, which the generator's `--access-entries` made, are
  resources too: the generator could not keep the entry without also writing the policy.
- **fleet.sh mints only the key**, with `aws iam create-access-key` (`mint_attendee_key`), from
  `bootstrap_student_aws` and from `aws-keys`. The secret never enters a state file. `aws-keys` no longer
  creates users by range: it mints for clusters that are built, skips names with no user, appends to the
  account CSV instead of overwriting it, and keeps the per-cluster copy bootstrap keeps. `WIB_ACCESS_ENTRIES`
  is gone. fleet.sh no longer runs the generator.
- **The first apply after this hands over users the generator made** (`adopt_attendee_iam_user`, before every
  apply). If the cluster is gone, the leftover user is deleted, as #458 asks. If the cluster is live and its
  state is here, the user, policy, entry and association are imported, so the student's key keeps working.
  Anything else stops that cluster's apply, naming why.
- **Check 3 holds users to the boundary as it holds roles.** `extract()` lists `aws_iam_user` with the roles,
  and the role-boundary message now reads "every role and user". Check 4 gained six cases for the user. Check 2
  sees a new identity policy, so the first pipeline run after this needs `--accept-new aws_iam_user_policy.attendee_eks`.
- **Tests.** `verify/test_attendee_iam_user.sh` (offline) covers the mint, the hand-over and `aws-keys`.
  `test_iam_policy_coverage.py` now also fails on any script that creates an IAM user, role or policy by API
  call, or runs `generate_attendee_aws.py`; against the old fleet.sh it fails on the generator line.
  `test_iam_policy_pipeline.py` and `test_iam_policy_structural.py` (E2E) hold the user's boundary and policy.
- **Not yet seen live.** No terraform, conftest or AWS here, so the plan, the structural and effect checks, the
  imports and the access entry's IAM propagation retry (the provider's, for a user created in the same apply)
  are next checked on a cluster build, with `run-e2e.sh`. The generator stays in provisioning-agenticburn,
  unused by this repo; retiring it there is that repo's change.
## 2026-10-25 · #552 · The chat path's ports admit only the hop before them

#490 left two routes around guard-proxy open. A pod the agent may still create (default ServiceAccount,
ordinary labels) reached agentgateway's `:3002` bind, which signs Bedrock calls with agentgateway's own Pod
Identity credentials. It also reached the agent over A2A, through agentgateway `:3000` or workshop-agent
`:8080`, with guard-proxy's input and output guards left out. `agent-allow-intra-namespace` opens egress to
every pod in `agent`, and neither target restricted ingress.

`gitops/ai-layer/chat-path-ingress.yaml` adds two Ingress NetworkPolicies:
- **agentgateway-ingress.** `:3000` admits pods labelled `app.kubernetes.io/name=guard-proxy`, and `:3002` admits
  `app.kubernetes.io/name=workshop-agent`. `:3001` and `:3003`, the MCP fronts, and `:15021` and `:15022`, the
  readiness listeners, are open to every pod. The MCP fronts stay open because the kagent controller lists
  tools from them and C7's fallback calls `:3003` from the web terminal. A tool call does not reach a model.
  `:15020` (stats) has no scraper and is closed.
- **workshop-agent-ingress.** `:8080` admits agentgateway's pods and the `kagent` namespace, because the
  controller's A2A proxy sits behind the kagent UI.

**Choices made:**
- **In the ai-layer bundle, not `policies/network-policies/`.** The attendee profile leaves that directory
  out, so that C1 lands. These rules are the shape of the chat path, not a challenge's control, so they ship
  on every profile, the burn cluster included. Nothing a challenge does calls these three ports from another
  pod. The beats ask through guard-proxy, from inside its own pod.
- **No rule for the kubelet's probes.** agentgateway's readiness probe is a TCP check on `:3000`. Under VPC CNI
  pods take VPC addresses, so an ipBlock for the nodes would admit every pod too. The VPC CNI's policy agent
  admits node-sourced probe traffic by itself (AWS re:Post, "Troubleshooting Kubernetes network policies
  enforcing policies in Amazon EKS"), and Kubernetes documents that a NetworkPolicy cannot block a pod's own
  node.
- **Every trusted label joins `egressLabels`.** Those labels are agentgateway, guard-proxy and workshop-agent,
  next to console. A label is its creator's to choose, so a rule that trusts one is only as good as the
  agent's inability to wear it. The variable keeps its name because
  `verify/test_agent_bypass_shapes.py` reads it. The refusal now says "a label that a NetworkPolicy
  trusts".

**Tests.**
- `verify/test_chat_path_ingress.py` is offline. It reads each caller from where it is decided: guard-proxy's
  `AGENT_URL`, the gateway-* ModelConfigs, both RemoteMCPServer urls, the agentgateway `:3000` backend, the C7
  fallback's `GATEWAY` and fleet.sh's agent-pod selector. It then evaluates the rules for each caller and for
  the bypass pod. A mutation that opened `:3000` to every pod failed four checks.
- `verify/test_kyverno_cel_policies.py` gained three impostor-label cases. They are in the E2E suite and were
  not run here, because no Kyverno CLI was on the box.
- `verify/test_llm_bypass_live.py` now creates the three impostors as agent-sa and expects refusals. It reads
  the live ingress rules for the plain pod and for each real peer, and times a bare `GET /` from the plain
  pod to each guarded port. That request matches no model route. It also connects guard-proxy to `:3000` and
  needs agentgateway and the agent Ready. None of this has run on a cluster yet. The next cluster build runs
  it through `verify/run-e2e.sh`.

**Still open.** Every pod in `agent` can reach guard-proxy's `/toggle`, as the Istio ambient evaluation
(#238) records. An agent-made pod can also reach the kagent controller, which proxies A2A to the agent around
guard-proxy. Before C1 nothing limits egress from `agent`, and after it `agent-allow-kagent-egress` opens the
whole `kagent` namespace. That route is filed as a follow-up.

## 2026-10-25 · #554 · The party apps lose their ALB Ingresses, and the unused gitops/argocd/values.yaml goes

**What went.** `gitops/manifests/demo-app-{hedgehog,wombat,unicorn,spider,mantis-shrimp}/ingress.yaml`: five
internet-facing ALB Ingresses in group `watch-it-burn-ingress`, each for a fixed `<app>.agenticburn.com`, the
same host on every cluster. Since #233 the party apps are reached at `<app>-<cluster>.agenticburn.com`, which
the apex router sends to the console LB and `console.conf` fans out to each app's Service, so the Ingresses
served nothing and kept alive the ALB that #493 meant to remove with Grafana's. On a live cluster Argo CD
prunes them (the five Applications have `prune: true`) and the load balancer controller then deletes the ALB.
The Services, the `apps` NetworkPolicy's port 80 (the console's path in) and the LB controller (the console
NLB) stay.

**gitops/argocd/values.yaml was deleted, not edited.** It carried a third ALB Ingress, for
`argocd.agenticburn.com`, plus Dex and an RBAC block, but nothing installs it: `deploy-full-idp.sh` installs
Argo CD from `infra/argocd-values.yaml` (as PRD #33 already noted), and no Application or script names the
gitops copy. The two live pointers to it, step 3 of `docs/MASTER-RECREATION-SPEC.md` and the Backstage
onboarding template's next steps, now name `infra/argocd-values.yaml`. Dated research and PRD notes that
mention it were left as written.

**Tests.** `verify/test_party_app_hosts.py` (offline) fails on any deployable manifest or Helm values under
`gitops/` (outside `apps-disabled`) that asks for `ingressClassName: alb` or joins `watch-it-burn-ingress`,
holds each party app to a Service, no Ingress and a `console.conf` row, and holds the gitops copy of the
Argo CD values gone; against the base it fails eight checks. `verify/test_service_hosts_live.py` now checks
that `apps` has no Ingress. Not run on a cluster here.

## 2026-10-25 · #563 · Six working docs stop saying the agent dials evil-mcp directly

#514 routed the `evil-mcp` RemoteMCPServer through agentgateway's own :3003 bind but corrected only its file
list. The issue named five lines that still said the hop was direct; `docs/READINESS-CHECKLIST.md:59` said it
too and is fixed with them. Each now says evil-mcp goes through :3003, that its rule is committed `'true'`, and
that the C7 control is kagent's `toolNames` on a workshop cluster and the gateway rule on an admin cluster
(#516). Dated research notes, including the duplicative-components audit, are records and were left as written.

- **KUBECON-ABSTRACT-READINESS row 6 keeps PARTIAL.** Its Open cell now says the agentgateway half is on
  `staging` (#514 to #518), not yet proven on a cluster (#503), and that the scan of the MCP server's reply
  before the model (#480) is not built. Whether the row moves to READY, as the run-of-show's point 6 "Yes"
  suggests, changes the tally and the verdict, so it is left for its own issue.
- **Held offline.** `verify/test_agentgateway_path.py` fails if a line naming evil-mcp in any of the six says
  it is dialled direct; against the base it fails all six.
## 2026-10-25 · #562 · The next build checks that BurritoBot answers through its tagged profile, by script

#513 (one tagged Bedrock application profile per tier per cluster) was built and tested offline only. #562
asks the next bring-up to confirm it. Three of its five checks already had a live check:
`model_pin_check.py` and `test_model_pin_live.py` (the pinned tier's copies, as the operator's profile) and
`test_iam_policy_aws.py` (the effect cases in `infra/org/effect-tests.yaml`). Nothing asked the cluster what
the agent calls, or checked the attendee and consumer tags or the other four profiles.

**`verify/bedrock_profile_check.py`** does that for one cluster, named by `--context`: all five
`<cluster>-<tier>` profiles are ACTIVE, each agent tier routes like its system profile, and all five carry
project, event, attendee and consumer. Every committed Bedrock ModelConfig's live `.spec.model` is this
cluster's ARN for its tier. kagent's `workshop-agent` config Secret names the bound one's ARN, and each running
agent pod started after the Secret last changed. Without that last check, a pod still holding the system id
would answer and look like a pass. Then one `[[wib-probe]]` chat turn goes to guard-proxy on localhost
through `kubectl exec`. A reply there, with the config naming the ARN, is the tag-conditioned grant honoured
at invoke time. `test_bedrock_profile_live.py` runs it in the E2E suite. `test_bedrock_profile_check.py`
(offline) checks the judges and whole runs against a stand-in aws and kubectl. Not run on a cluster here.
## 2026-10-25 · #561 · agentgateway's bedrock backend calls the cluster's tagged profile, through a container env var

#513 tagged Bedrock spend on the direct path and left the gateway path out: the opt-in gateway-* ModelConfigs
name an agentgateway backend, and the bedrock-nova backend named the system profile `us.amazon.nova-pro-v1:0`
inline, so a cluster switched to `gateway-bedrock-nova` billed untagged again.

- **The model comes from the env, not the config text.** The backend reads `model: ${BEDROCK_NOVA_MODEL}`, and
  the agentgateway container commits `BEDROCK_NOVA_MODEL=us.amazon.nova-pro-v1:0`, the pin. agentgateway v1.5.0
  runs the whole config file through `shellexpand::full` before parsing it (`crates/agentgateway/src/config.rs`,
  `parse_config`), and an unset variable fails the config. Read at tag v1.5.0 on 2026-10-25.
- **`pin_bedrock_profiles` sets it.** It now pins the Bedrock ModelConfigs and agentgateway's env in one pass,
  from the same `bedrock_application_profiles` output, with the same wait, and fails the cluster the same ways:
  no tagged copy for the committed id, a bedrock backend that names its model inline, or a variable the container
  does not set. Setting it is `kubectl set env` on the agentgateway container, which rolls the gateway
  (maxUnavailable 0). It only sets it when the live value differs, so converge does not roll the gateway each time.
- **One env entry is ignored, by name.** ai-layer ignores the `BEDROCK_NOVA_MODEL` entry of the agentgateway
  container and nothing else of the Deployment. A separate ConfigMap for the inference bind, as C7 has (#514), was
  the other shape. It would have put the whole LLM route config out of GitOps on every cluster, because Argo can
  only ignore a ConfigMap's config string whole. A ConfigMap that fleet.sh creates outside git would leave the
  gateway unable to start until fleet.sh runs, and that would take the A2A and workshop-mcp hops down with it.
- **The ARN in the URL path.** The bedrock provider builds `/model/{model}/converse` and percent-encodes only `/`
  and `%` in the model (`crates/llm/src/bedrock.rs`, `get_path_for_route`), so the ARN goes out as
  `arn:aws:bedrock:<region>:<acct>:application-inference-profile%2F<id>`. Upstream's own tests send an
  application-profile ARN in exactly that form, and the request model is replaced by the provider's `model`
  (`override_model` in `crates/agentgateway/src/llm/mod.rs`). Signing uses the aws-sigv4 defaults, as it already
  does for the colon in the system id.
- **IAM needs nothing new.** The agentgateway ServiceAccount already has the agent's Bedrock role (#394), and
  that role's #513 statement allows this cluster's `consumer=agent` application profiles.
- **Tests.** `verify/test_pin_bedrock_profiles.sh` now pins the gateway env on a fresh cluster, leaves it alone
  when it is already pinned, and fails on a missing env, an inline model and an unset variable.
  `verify/test_agentgateway_config.py` holds the backend to a `${VAR}` reference that resolves on its container,
  committed to an id the cluster root copies. `verify/test_c7_gateway_toggle.py` allows that one env ignore on
  the agentgateway Deployment and nothing else of it. `verify/test_gateway_bedrock_tagged_live.py` (E2E) reads the
  live env and the running pod's, and makes one 5-token call through :3002 from the workshop-agent pod: a 200 is
  what confirms Bedrock takes the escaped ARN. Not run on a cluster here.
## 2026-10-25 · #557 · The re-filed "Declare an E2E command for the heavy gate" gets the #543 answer: no line
## 2026-10-25 · #557 · No E2E command is declared for the re-filed heavy gate issue, as for #543

Hecaton filed the request again. The answer is the one the 2026-10-24 #543 entry above gives. This repo's
tests against real services are in `verify/run-e2e.sh`: the beat scripts on a live attendee cluster, the
`# SUITE: e2e` checks, the AWS policy pipeline and Backstage Playwright. The promotion gate cannot run them,
so AGENTS.md declares no `E2E command:` line and the issue closes as not applicable.

Checked on the dispatch host on 2026-10-25: kubectl, helm, the kyverno CLI, conftest, terraform and the aws
CLI are not on PATH, and CONTEXT and the IAM pipeline profile and region are unset. `bash verify/run-e2e.sh`
exits 1 with "E2E SUITE CANNOT RUN" and lists each of them. Declared as the E2E command, it would keep main
red, as it did before #543.

- **Revisit** when hecaton's toolchain has the #523 tools and the gate can reach a cluster and AWS, or when
  there is an E2E tier that needs no cluster. `verify/test_gate_commands.py` forbids only run-e2e.sh on the line.
## 2026-10-25 · #553 · workshop-mcp runs as its own ServiceAccount, so run_shell holds no Bedrock credentials

#490 left one route to the model open with no new pod: workshop-mcp ran as agent-sa, agent-sa has the Bedrock
Pod Identity association (`agent_bedrock_pod_identity` in `infra/terraform/aws/cluster/main.tf`), and the egress
allowlist passes the in-VPC Bedrock endpoint, so `run_shell` could call Bedrock around guard-proxy. Of the
issue's two options this takes the first.

**Choices made:**
- **A `workshop-mcp` ServiceAccount, bound to the agent's Role.** The `workshop-agent` RoleBinding now has two
  subjects, agent-sa and workshop-mcp, so the tools keep exactly the agent's RBAC. C8 keeps its lesson: the chat
  vector's `cat` of the pod token now returns workshop-mcp's token, which lists every Secret under the broad
  Role and is Forbidden under the scoped one, the same as agent-sa. C8's terminal commands still impersonate
  agent-sa, which still runs BurritoBot and is still bound to the same Role, so the lab text is unchanged.
- **No IAM change.** Pod Identity is keyed on namespace and ServiceAccount, and the new account has no
  association, so it gets no AWS credentials. Nothing under `infra/` changes, so there is nothing for the #207
  policy pipeline to check. The PrincipalTag/kubernetes-pod-name alternative was not taken: pod names follow
  Deployment names, which the agent chooses (#333).
- **The C2 fallback and the kubecon probe's C2 dry run impersonate workshop-mcp,** the identity `deploy_app`
  now holds. The C3 fallback asserts the tool pod runs as workshop-mcp and refuses agent-sa.
- **restrict-agent-spawned-workloads is unchanged.** Its match is every agent-namespace ServiceAccount but
  web-terminal, so the new account may not start a pod as agent-sa either. Its comment now says the run_shell
  route is closed here rather than open.
- **Tests:** `verify/test_agent_bypass_shapes.py` holds workshop-mcp to its own account, with no association in
  main.tf and no IRSA annotation, bound to the agent's Role, and checks that the Role (as shipped and in both C8
  files) grants no `serviceaccounts`, `serviceaccounts/token` or `impersonate`, so the shell cannot mint or
  borrow agent-sa's token. Not yet seen live: the next cluster's C1 to C3 and C8 beats are the check.
## 2026-10-25 · #564 · A test holds #514's reader grant and its wording

`verify/test_c7_gateway_reader.py` holds the last criterion of #514. guard-proxy-reader's Role has exactly one
rule that reaches ConfigMaps, and it is `get` on `configmaps/agentgateway-c7-config` by name: list or watch,
which ignore `resourceNames`, a missing or changed name, or a ConfigMap grant on the ClusterRole fails it. It
also holds that the name is the ConfigMap with the one `# c7-rule` line the C7 badge reads.

- **The wording check reads prose, not code.** In #514's eight files it fails a sentence that names evil-mcp
  and calls its hop direct, says it bypasses or skips the gateway, or says it is not through it. Code files
  are read for comments and docstrings only, docs in full, and decisions.md for #514's entry only, since the
  entries before it record what was true then. The evaluation's table row and the spec's path diagram said it
  without the word "direct", so each has its own check.
- **One comment reworded.** `verify/test_agentgateway_path.py` quoted the old phrase while describing #563's
  check; it now describes the old hop without repeating it. That check itself is unchanged.
- **Held offline.** Against the files as they were before #514 the test fails 14 checks, all of them on the
  grant or the wording.

## 2026-10-25 · #565 · The console now sees its public hostname; the /brief gate stays in the router

The #152 comment above `location = /brief` in `gitops/ai-layer/console.conf` said the console never learns its
own public hostname, because the apex router forwarded Host as the load balancer address. That stopped being
true at #233, when the router began passing `header_up Host {host}`. The service-host server in console.conf
matches `grafana-<cluster>` and the other names only because of it, and #233 recorded all eight service hosts
answering 200 on a live cluster. The 2026-10-24 #451 entry above repeats the old claim. Its knob does not
depend on it.

- **Re-checked 2026-10-25, not live.** The fleet was torn down: the router's roster was empty and every roster
  host got its unknown-host page. The router hop was run locally under caddy with the shipped
  reverse_proxy options and a TLS stub answering `/whoami` the way nginx does. It gave
  `host=attackme.agenticburn.com`. `verify/test_service_hosts_live.py` (E2E) asserts the live `/whoami` at
  the next cluster build.
- **The gate stays in the router.** A gate in nginx would read Host one hop later and hold only while the router
  passes it, and if that ever stopped, the brief would 404 on the roster clusters again, the #152 failure. The
  roster rule also stays in one place: the router's `@brief_not_roster` matcher, which also takes `/kubecon`
  (#511), with the apex E2Es testing it. nginx behaviour is unchanged.

## 2026-10-25 · #571 · KUBECON-ABSTRACT-READINESS row 6 moves to READY

#563 rewrote row 6's Open cell once #514 to #518 put evil-mcp behind agentgateway :3003 on `staging`, but kept
PARTIAL and left the tally for its own issue. Row 6 now reads READY, and the tally is 7 READY, 2 PARTIAL,
0 MISSING, matching the run-of-show's point 6 "Yes, as #456 defines mid-inference".

- **READY, not PARTIAL until the #503 probe.** The legend's READY is "everything this repo builds for the
  point is on `staging`", and it keeps the Live column apart on purpose. Point 7 is READY with nothing shown
  live yet. Waiting for the live proof would put that proof in the status and the Live column both. The
  Live cell says C7 at the gateway has not run live, and names the probe and `fallback.curl.sh` ending
  `C7 PROVEN` at the next bring-up.
- **#480 does not hold the row back.** #456's definition shows mid-inference as agentgateway MCP
  authorization plus the output guard on C7, and #496 and #518 took the scan of the MCP reply before the
  model (#480) out of KubeCon's scope. The row's Evidence cell now names both halves' files and their offline
  tests; its Open cell says #480 is not built and not claimed.
- **Row 2 and PROJECT_STATE.md follow.** Row 2's Open cell said the run-of-show listed no admin-cluster C7
  fallback; it now names `fallback.curl.sh`, in the run-of-show's fallback table. PROJECT_STATE.md's copy of
  the tally is updated with it.
## 2026-10-25 · #569 · A test holds #516's wording on C7's control

`verify/test_c7_control_comments.py` holds the last criterion of #516: no comment in its files, in
resources.yaml's Agent tools comment or in toggle-mcp-authz-on.sh names toolNames as C7's only control.

- **A comment block that calls toolNames a control must name the admin cluster's gateway rule too.** So must
  one that says "the C7 control is" or "the control is" about C7's tools. The phrasings #516 removed ("actually
  IN PATH", "nothing flips it", "toolNames stays the control", "The MCP guard patches") and "only control" are
  refused outright. Code files are read for comments and docstrings, resources.yaml for its Agent tools
  comment only, and decisions.md for #516's entry only, read as one block because its opening paragraph names
  both controls for the bullets below it.
- **Two comments in toggle-mcp-authz-on.sh reworded.** Below the WHY block it still said "the C7 control is
  whether `evil-mcp` is wired" and "the control is its toolNames allowlist" with no word of the admin
  cluster. Both now say this is the script's control, C7's on a workshop cluster, and point at the gateway rule.
- **Held offline.** The pre-#516 comments are fixtures the check must refuse. Against the files as they were
  before #516 it fails four checks, and against the toggle script as #516 left it, one.
## 2026-10-25 · #572 · The gate's E2E command is a cluster-free tier with pinned tools fetched into verify/.tools

The 2026-10-25 #557 entry above said to revisit the E2E line once there was an E2E tier that needs no
cluster. There is one now. AGENTS.md declares `E2E command: \`bash verify/run-e2e-tools.sh\``. That script
checks its prerequisites, fetches the pinned binaries, runs the offline suite, then runs every test marked
`# E2E TIER: tools`. Hecaton's heavy gate runs the E2E command instead of the Test command, so the offline
suite runs inside it and main is still gated on everything it was gated on before. run-e2e.sh is
unchanged, and it still runs the tier tests during a cluster build, since they keep their `# SUITE: e2e` line.

- **Pinned tools, a new dev dependency.** `verify/e2e-tools.lock` pins the linux/x86_64 kyverno CLI v1.19.1,
  conftest v0.71.1, terraform v1.15.6, kubectl v1.36.2 and helm v4.2.1. Those are VERSIONS.lock's versions,
  and kyverno is the deployed v1.19.1, not the issue's v1.19.0 (see the #523 entry). Each SHA-256 was
  checked against the release's own checksum file on 2026-10-25. `verify/fetch-e2e-tools.sh` downloads them
  into `verify/.tools`, which git ignores, and refuses any download whose checksum does not match. It
  reuses a cached download only while its checksum still matches. Any failed download, mismatch or other
  platform exits 1 and names every failure. A run cannot install into hecaton's root-owned toolchain
  (#523), so the tier fetches the tools itself.
- **The tier is 12 tests.** test_kyverno_cel_policies, test_iam_policy_structural, test_terraform_lock_init,
  test_service_naming_render, test_ai_layer_rollout and test_enforce_floor use the fetched binaries, with
  network to ghcr.io, registry.terraform.io and the chart repositories. test_audience_page_e2e,
  test_party_refresh_rate and test_storefront_thinking_e2e use the host's Node 24. test_mobile_titles_e2e,
  test_kubecon_deck_pdf_e2e and test_topic_classifier get Playwright, segno and llm-guard pinned through uv.
  The other `# SUITE: e2e` tests need CONTEXT, AWS or Datadog, and stay by hand.
- **No cluster can be reached.** Each tier test runs with CONTEXT, IAM_PIPELINE_*, AWS_PROFILE and the AWS
  key variables unset and KUBECONFIG=/dev/null. KYVERNO_CLI, CONFTEST and TERRAFORM point at the fetched
  binaries, and those binaries come first on PATH.
- **Held offline.** `verify/test_e2e_tools_tier.py` checks that the pins match VERSIONS.lock and the tests'
  wanted versions, that verify/.tools is ignored and untracked, and that every tier test is also
  `# SUITE: e2e` and reads no CONTEXT, IAM_PIPELINE_* or Datadog key. It then runs the fetch with a stubbed
  curl: matching artifacts install, a second run downloads nothing, a tampered cache is fetched again, and
  a mismatch or missing artifact exits 1 with both reasons and no binary left behind. run-e2e-tools.sh is
  also shown to stop before any test on a failed fetch or a Node other than 24. Removing the checksum
  comparison, or the stop on a failed fetch, turns it red. `verify/test_gate_commands.py` now requires that
  exact E2E line, and still forbids run-e2e.sh on it.
- **Run on the dispatch host, 2026-10-25.** `bash verify/run-e2e-tools.sh` exited 0: the fetch took about
  10 s, the offline suite ran 140 tests green, and all 12 tier tests passed. Run one by one, the tier tests
  took about 6 minutes; test_iam_policy_structural (about 100 s) and test_terraform_lock_init (about 70 s)
  are the slowest.

## 2026-10-24 · dev dependency · otelcol-contrib 0.160.0 for the E2E suite (#150)

`verify/test_lab_pipeline_collector.py` runs the real collector binary, otelcol-contrib **0.160.0**: the
`appVersion` of the opentelemetry-collector chart 0.173.1 that both collector Applications pin. It comes
from the release tarball (github.com/open-telemetry/opentelemetry-collector-releases, v0.160.0,
`otelcol-contrib_0.160.0_linux_amd64.tar.gz`, sha256 7bb60c58...b47b0c). Put it on PATH, or point
`OTELCOL_CONTRIB` at it. `run-e2e.sh` reports it missing up front, with the other prerequisites.

Why. The lab-marker pipeline (#150) adds a receiver, a connector and two OTTL processors to the collector
config. A config the collector rejects puts the DaemonSet in CrashLoopBackOff, which takes the student's own
telemetry down with it, and YAML checks cannot tell a valid OTTL function from a typo. The route is also
public, so the contract processors have to be shown to remove the fields of a forged payload, and only the
real OTTL engine can show that. The test pins the chart version next to the binary version, so a chart bump
fails the test until both move together. Rejected: a container image, because this machine has no Docker
access.

## 2026-10-25 · question 693 · lab progress markers stay off until the disclosure wording is settled (#150)

Question 693 asked whether the student lab page's privacy warning should be extended to tell attendees
two things: that the lab records which guide steps and hints they open, and that the instructors keep
their BurritoBot prompts after the workshop. The options were: extend the warning and keep the markers on;
keep the markers on and leave the warning as it is; or turn the markers off until the wording is settled.

Answer: **Turn the markers off until the wording is settled.** Decided by Michael. The run had recommended
extending the warning; this answer replaced that recommendation.

What it changes. `gitops/ai-layer/web/lab-events.js` is committed with `var ENABLED = false;`, so the lab
page sends no progress markers, and the instructor dashboard's lab widgets and harvest pass 6 have nothing
to read. The route, the collector pipeline, the dashboard and the harvest pass stay in place, unchanged and
tested. The behaviour test turns the switch on in its own copy, so the sending code stays covered while the
committed file has it off. `verify/test_lab_events.py` pins the switch off. Turning the markers back on is
one commit that changes that line, the warning in `gitops/ai-layer/web/lab.html` (once Michael has settled
its wording) and the pin, together. The decision does not touch the prompts that attendee clusters have
sent to the instructor org since #242, and the warning still says nothing about them.

## 2026-10-25 · question 753 · the lab warning carries the disclosure, and the progress markers are back on (#150)

Question 753 asked which exact sentence the student lab page's privacy warning should carry so that the lab
progress markers could be switched back on. The options were: the proposed sentence with the markers on; a
shorter sentence with the markers on; or the markers off for good.

Answer: **Use the proposed sentence and turn the markers on.** Decided by Michael.

What it changes. The BurritoBot warning in `gitops/ai-layer/web/lab.html` now reads, after the sentence about
the instructor screen: "The lab also records which steps, hints and commands you open (never what you type),
and the instructors keep your prompts after the workshop to improve it." `gitops/ai-layer/web/lab-events.js`
is committed with `var ENABLED = true;`, so the instructor dashboard's progress widgets and harvest pass 6
have data again. This ends the off state that question 693 set (entry above).

The switch and the sentence are tied together. `verify/test_lab_events.py` fails if the markers are on
without this exact sentence in the warning. Collecting more, or changing the wording, needs a new decision
and a change to both in the same commit. The sentence also covers the prompts that attendee clusters have
sent to the instructor org since #242, which the warning did not mention before. "To improve it" names the
purpose the kept prompts are used for.
## 2026-10-25 · #560 · fleet.sh, setup-instructor-cluster.sh and the gitops Applications describe roles, not rounds

**setup-instructor-cluster.sh was kept and made to take a roster cluster, not retired.** `fleet.sh instructors
up [role|owner]` provisions, bootstraps and arms in one step, but a roster cluster provisioned bare
(`WIB_NO_BOOTSTRAP=1`) or whose bootstrap failed still needs the bootstrap and the Kyverno flip on their own,
and that is what the script does. It now takes `<roster-cluster-name> [aws-profile]` and asks `fleet.sh` for
the role (`role_of_instructor_name`), the profile (the new `bootstrap_profile_for_role`, which
`cmd_instructors` also uses) and the default account (`account_for_role`), so it cannot disagree with the
fleet. It refuses an attendee name, a non-fleet name and a bare number second (the old round argument, which
would otherwise be read as an AWS profile named "2") before touching AWS.

**fleet.sh.** The usage text says attendees bootstrap `attendee`, the community cluster `burn` and each admin
cluster `admin`. `WIB_ACCOUNT_R1..R3`, which nothing read, the `rounds` selector alias, the unused round
parameter of `bootstrap_one` and the `BOOTSTRAP_ROUND` spec field (now the role column) are gone. Comments
that described a cluster as a round now say community or admin. Comments that record where something was
measured keep the cluster name of the day, and the converge loop's retry rounds are not the round model.

**The gitops Application comments** that said R1 or round 2 now name the community or admin cluster, and two
that were wrong were corrected: `ai-layer-otel` is pulled by every profile, burn included, and
`kubearmor-policies` by the admin profile only (full and attendee exclude it since #281).

**Tests.** The shapes `verify/test_docs_current.py` held the markdown to moved into `verify/round_shapes.py`.
`verify/test_round_names_retired.py` sweeps fleet.sh, the setup script and every file under `gitops/apps`
and `gitops/bootstrap` for round wording (retired cluster and host names, and dated lines, are history and
pass), pins the usage text, the knobs and the role-to-profile map, and runs the setup script with failing
`aws`/`kubectl` shims. The rest of the repo's non-markdown round wording (the ai-layer, policies, challenges
and images) is out of this issue's scope and filed as a follow-up. Not run on a cluster here.

## 2026-10-25 · #585 · run-e2e.sh fetches its kyverno, conftest, terraform, kubectl and helm through fetch-e2e-tools.sh

`verify/run-e2e.sh`, the by-hand live suite, no longer asks for the five pinned tools on PATH. Its prerequisite
check runs `verify/fetch-e2e-tools.sh` (#572), puts `verify/.tools/bin` first on PATH and points KYVERNO_CLI,
CONFTEST and TERRAFORM at the fetched binaries, as `run-e2e-tools.sh` does. A cluster build therefore runs the
same pinned, checksum-verified binaries as the gate. The cluster reachability check uses the fetched kubectl.

- **Required, with no host fallback.** A failed fetch is listed among the missing prerequisites, and the run
  exits 1 before any check. A KYVERNO_CLI, CONFTEST or TERRAFORM already set in the environment is overridden,
  so a host tool never runs in place of the pinned one. The lock pins linux/x86_64 artifacts only, so
  run-e2e.sh now fails loudly on any other host. Before this change it ran there with tools installed by hand.
- **The fetch's own prerequisites.** curl, tar, unzip and sha256sum are now required. Without them the fetch is
  not attempted, and that is listed as missing too. otelcol-contrib and the aws CLI are not in the lock and are
  still taken from PATH.
- **Held offline.** `verify/test_e2e_toolchain.py` no longer expects any of the five tools to be listed as
  missing from PATH. `verify/test_e2e_tools_tier.py` runs a scratch run-e2e.sh against a stubbed fetch: the
  fetched kubectl, not one on PATH, checks the cluster, and a failed fetch is listed with no kubectl run.
  `verify/test_kyverno_version_pins.py` checks that e2e-tools.lock's kyverno is the deployed version, in place
  of run-e2e.sh's install message. Not run on a cluster here.
## 2026-10-25 · #584 · The attendee's AWS key moves out of namespace agent, into student-creds

fleet.sh's `bootstrap_student_aws` pushed the attendee's IAM key into the `student-aws-creds` Secret in namespace
agent, and the web terminal mounted it with `envFrom`. Since #549 that key's user has an EKS access entry with
`AmazonEKSClusterAdminPolicy`. Under the broad `workshop-agent` Role, the state Challenge 8 starts in, `run_shell`
could read the Secret with workshop-mcp's token, presign an EKS token with no AWS call and act as cluster-admin, an
identity `restrict-agent-spawned-workloads` does not match, so it could start a pod as agent-sa. Of the issue's two
options this takes the first. The second, the scoped Role's posture for this one Secret, is not something RBAC can
express while C8 keeps blanket `list`: a `list` grant returns every Secret in the namespace.

**Choices made:**
- **A `student-creds` namespace** in `gitops/namespaces/namespaces.yaml`, holding only that Secret. Nothing grants
  any agent identity anything in it, and a pod can only mount Secrets from its own namespace.
- **The terminal reads the key at boot** with its own token (`console-terminal` already reads Secrets in every
  namespace), so the Deployment no longer mounts it. Both entrypoint copies change; the image needs no rebuild,
  because gitops mounts its copy over the image's.
- **fleet.sh's new `push_student_aws`** deletes any copy an older bootstrap left in agent, waits for student-creds,
  calls the provisioning repo's `push_vtt_aws_creds.sh` with `--namespace student-creds`, and restarts the terminal
  in agent itself, because that script restarts terminal pods in the namespace it is given. The provisioning repo
  is unchanged.
- **The cluster-admin grant stays.** It is the take-home premise ("the student is the platform team"), and the
  student has the key on their laptop from the pool row.
- **C8's lab text drops "the AWS keys"** from what the dump reveals, in three sentences, because the Secret is no
  longer there to dump. The terminal password, the TLS key and the rest of agent's Secrets still are. LAB-TEXT.md
  is re-exported.
- **Tests:** `verify/test_student_aws_creds_namespace.py` holds the namespace, the entrypoints, the Deployment, the
  bindings (no agent-namespace account but the terminal reads Secrets cluster-wide) and the lab text.
  `verify/test_student_aws_push.sh` runs `push_student_aws` against kubectl and push-script shims. Not yet seen
  live: the next cluster build's terminal `aws sts get-caller-identity` is the check. A cluster built before this
  keeps the old copy until it is bootstrapped again.
- **Left open:** C8 also dumps `terminal-auth`. From that password and the cluster network, the agent could log in
  to ttyd and drive the student's terminal, which holds this key and is exempt from the policy. Filed as a follow-up.

## 2026-10-25 · #587 · test_lab_pipeline_live.py holds the fleet-analytics path on a live attendee cluster

#587 asks for the lab progress markers (#150) to be validated on a live attendee cluster. This run had no
cluster, no AWS and no Datadog keys, so it could not do that. It added the check that the next cluster build
runs instead, `verify/test_lab_pipeline_live.py` (`# SUITE: e2e`, so it is in `run-e2e.sh`). The issue stays
open until that check has passed on a cluster.

- **The page's own payload.** The markers are what the committed `lab-events.js` sends, run under node by
  `lab-events-harness.js` in its `shipped` mode. Only `witb.lab.alias` is replaced, with a fresh
  `verify-<hex>`, so every series the check finds belongs to this run and to no student. The alias is a
  metric tag, so each run adds a handful of series to the instructor org.
- **Through the public route.** The check posts to `https://<public-host>/lab-events`, using the host
  `cluster-identity` records, as a browser on the lab page would. It also checks that a GET answers 403.
- **Checked, not applied.** The dashboard is compared with `fleet-analytics.json` in the instructor org, and
  every widget query is run with this cluster selected. Applying `infra/terraform/dashboards` stays an
  operator step with the instructor org's keys, because a test that rewrites a shared org's dashboard has
  side effects. A dashboard that was never applied, or that has drifted from the file, fails the check.
- **Pass 6 for real.** `06-lab-progress.py` runs as a subprocess over the run's window and must write a CSV
  row for the alias. Its `.harvest/` output is deleted afterwards, because it is synthetic and not an
  event's data.
- **Prerequisites.** The check fails by itself, listing what is missing, when node, kubectl, CONTEXT or the
  instructor org's `WITB_DD_ADMIN_API_KEY`/`WITB_DD_ADMIN_APP_KEY` are absent. Those keys are not added to
  `run-e2e.sh`'s up-front list: `verify/test_gate_commands.py` would then need the E2E paragraph in
  `AGENTS.md`/`CLAUDE.md` to name them, and that paragraph is Michael's to change. The check reads the
  student org's keys from `datadog-secret` on the cluster, and fails unless that org differs from the
  instructor org.

It was run only against a stub `kubectl` and a stub Datadog, outside the repo, where every check passed. Not
run on a cluster here.

## 2026-10-25 · #598 · MASTER-RECREATION-SPEC says how a tier reaches a cluster

The spec's Key Decisions bullet on the workshop default model said "Tier swaps by repointing the Agent
`modelConfig` (commit + resync), never `kubectl patch` live." That is not how a tier reaches a cluster. The
ai-layer Application ignores the Agent's `.spec.declarative.modelConfig` and guard-proxy's `MODEL_TIER` env, with
`RespectIgnoreDifferences=true`, so a commit plus resync changes neither on a running cluster, and the
2026-07-07 §4.6-d entry above recommends the live patch the spec forbade.

- **The sentence now says both routes.** A fresh cluster gets the committed default when Argo first creates the
  Agent and the Deployment. A running cluster takes the live patch: Agent `workshop-agent` to `bedrock-<tier>`,
  then `kubectl set env deploy/guard-proxy MODEL_TIER=<tier>` behind the Kyverno flip in
  `docs/GOTCHAS-FLEET-AND-DELIVERY.md`, both together so the counter prices the model that answers. It matches
  the Deferred item in `docs/GO-LIVE-CHECKLIST.md`, says no script applies a tier yet, and that the live patch is
  not validated live.
- **Test:** `verify/test_recreation_spec_tier_swap.py` reads the ignores and the sync option from
  `gitops/apps/ai-layer.yaml`, and fails if the spec calls a tier swap commit + resync, forbids the live patch on
  a tier line, or stops naming both routes. It failed 7 checks on the old spec line. No cluster was touched.
## 2026-10-25 · #594 · datadog-secret-fields.sh is PRD #13 Milestone 1's verification command

#594 is PRD #13 Milestone 1: `datadog-secret` with the trial org's credentials, in the namespace the collector
reads it from, and a command that shows its fields without their values. Creating the secret is already
automated: `infra/deploy-full-idp.sh` step 3.6 and `fleet.sh`'s `repair_datadog` write it, with `api-key` and
`app-key`, in `datadog`, `monitoring` and `security`. It was first created by hand on watch-it-burn-attendee-001
on 2026-06-25 (PROGRESS.md). That cluster was torn down long ago. This run had no cluster, no AWS and no Datadog
credentials, so it did not create the secret anywhere. It added the verification command instead.

- **Names only.** `verify/datadog-secret-fields.sh <kube-context>` reads the secret through a go-template that
  runs inside kubectl and emits `<key>=set` or `<key>=empty`. jsonpath, yaml, json and describe all bring the value
  back to the shell. The PRD's rule is that no credential value is ever printed, and this keeps the value out of
  the script's own process too. `datadog-pool-check.sh` still decodes keys to validate them against Datadog,
  which is a different job.
- **All three readers.** It checks the namespaces the Agent, the collector and falcosidekick read from, not
  only `monitoring`. A missing secret, an absent key or an empty value each fail with the namespace named.
  It needs the context as an argument and has no current-context fallback (CLAUDE.md).
- **The key list is held to gitops/.** `verify/test_datadog_secret_fields.py` (offline) collects every
  `secretKeyRef`/`keyName` to `datadog-secret` under `gitops/`. The issue named `gitops/apps/otel-collector.yaml`,
  but since #500 those references live in `gitops/otel-collector/values*.yaml`. The test fails when a reference
  names a key that `REQUIRED_KEYS` does not list, and it runs the script against a kubectl shim.
  `verify/test_datadog_secret_fields_render.py` (tools tier) has the pinned kubectl render the template over
  client-side Secrets holding sentinel values, and checks that neither value nor its base64 appears in the output.

Not run on a cluster here. The issue's first criterion, the secret existing in a cluster, is met only by the
next cluster build with keys, when this command passes against that build's context.
## 2026-10-25 · #602 · Each cluster carries its attendee hostname as the hostname= tag

lab-platform's `labctl harvest` (lab-platform#84) finds a workshop's EKS clusters by tag (`project` and `event`
for this fleet) and reads each one's attendee hostname from a tag the operator names with `--host-tag`. It does
not derive a host from a cluster name. The fleet carried no such tag, so harvest found every cluster with no
hostname and wrote no pool file.

- **The tag is `hostname`, in `fleet_tags`.** The cluster root (`infra/terraform/aws/cluster/main.tf`) adds
  `hostname = var.hostname` beside `attendee`, so the provider's default_tags put it on the cluster and every
  resource, and the mechanisms default_tags does not reach (node launch templates, CNI ENIs, the Bedrock
  application profiles) carry it too. Harvest is run with `--host-tag hostname`.
- **The value is `public_host_for`, the roster's assignment.** `fleet.sh` passes `-var hostname=` from the same
  function routes and ingest use: `attackme.agenticburn.com` for the community cluster,
  `<owner>-admin.agenticburn.com` for a presenter's, and the slot's two-word name for an attendee's. A second
  derivation would be the two-namers failure of #265, so there is none.
- **No default, validated.** As with `event` (#494), an apply that forgets the host fails rather than tagging a
  cluster with a host the router does not serve for it. The variable must be a lowercase DNS name without a
  scheme. `down_one` passes it on destroy, and the adopt step's imports get it through the apply's `tfvars`.
- **A running cluster gets the tag on its next apply.** `up` skips a healthy cluster, so one built before this
  is tagged only by `WIB_FORCE_UP=1 fleet.sh up <name>` or a rebuild. That apply also changes the node launch
  template's tags, which gives the managed node group a new launch template version and rolls its node.
- **Test:** `verify/test_hostname_tag.py` (offline) reads the tag and the variable from the root, holds every
  apply and destroy of the cluster root in fleet.sh to passing it, checks the validation regex against every host
  `fleet.sh hosts` lists, and dry-runs `up` and `instructors up all` to see each cluster's host. No cluster was
  touched.
## 2026-10-25 · #593 · question 782 · The agent keeps its route to the student's terminal

**Question 782:** should attendee clusters get their own random terminal password, kept outside namespace agent
(in student-creds, which #584 created), so the workshop agent cannot log in to the student's terminal?

**Answer:** "Huh? No the agent should retake n access so we can data mine the clusters once done." Decided by
Michael. Read as: no random password; the agent should retain its access, so the clusters can be data-mined
once the workshop is done.

**What it changes:**
- **The takeover route stays open on purpose.** Attendee clusters keep the shared `agentic:agentic` login
  in `agent/terminal-auth`. No ingress NetworkPolicy is added on web-terminal or the console. The agent can
  read the Secret under C8's broad Role, or the password off `/brief`, and reach ttyd directly on `:7681` or
  through the console. The terminal holds the attendee's cluster-admin AWS key (#549, #584) and is exempt from
  restrict-agent-spawned-workloads. This is intended, not an open defect.
- **The 2026-08-26 speakable-password trade stands.** Its comment in fleet.sh's `bootstrap_terminal_auth`
  said the shell was "not cluster-admin". That has not been true since #584. The comment now says the shell
  holds the cluster-admin key and the agent's route is kept, citing this question, so nobody closes it by mistake.
- **Nothing else changes.** The provisioning harvester, brief.html, the run-of-show and the drift audit
  are untouched. Not run on a cluster.

## 2026-10-25 · #486 · The Falco badge is measured, not claimed; the guard-proxy half is in its own repo

`/controls` must report Falco the way it reports every other control, by reading the object, because the
burn profile (the Community cluster) installs no Falco. What lands here, and what it waits on:

- **RBAC:** `guard-proxy-reader` gets `get` on `apps/daemonsets/falco` on its **ClusterRole**, not a Role in
  `security`. The ai-layer bundle sets `namespace: agent`, which would rewrite a Role written for `security`
  into `agent`, where it grants nothing. The rule is still get-only on one name; the only DaemonSet called
  `falco` is the chart's, in `security` (falco 9.1.0's `falco.fullname` with the release named `falco`).
- **Measured means ready:** the proposed read is "the DaemonSet exists and `status.numberReady > 0`". A
  DaemonSet with no ready pod detects nothing, so it does not light the badge.
- **The page:** the Falco badge now needs `infra.falco` as well as KubeArmor. Before, the pairing replaced
  the measured value with KubeArmor's, so a measured false would have been thrown away.
- **Not done here, and what it blocks:** `read_controls()` is in guard-proxy-agenticburn `proxy.py` (pinned
  at `ccdda73`), and the Go rewrite's `/controls` still answers 501. Until the pin moves to a commit that
  reads `security/falco`, the hostname override in `burritbot.html` stays. `verify/test_falco_badge_measured.py`
  ties the two together: it fails if the override goes before the pin moves, or stays after. Promote the
  pin bump, the `checksum/proxy-py` bump and the override removal together.

## 2026-10-25 · #421 · Backstage plugins move to their security backports, not to a newer release

The Backstage backend plugins in `images/watch-it-burn-backstage` had open advisories, one critical:
scaffolder-backend's sensitive information exposure (fixed in 4.0.3). Each plugin moves to a patched release
in the line it was already on, and the app stays on the Backstage 1.52.0 line (`backstage.json`): backend-defaults
0.17.8, auth-node 0.7.7, catalog-backend 3.9.2, kubernetes-backend 0.21.12, proxy-backend 0.6.19,
scaffolder-backend 4.1.0, scaffolder-backend-module-github 0.9.13, search-backend 2.1.8, techdocs-backend 2.2.5
and techdocs-node 1.15.6. This covers what Dependabot PRs #424 to #433 asked for. Bumping to release 1.56 would
have meant catalog-backend 4, techdocs-node 2 and scaffolder-backend-module-github 0.10, and none of those
majors is needed for a fix. scaffolder-backend and techdocs-backend take `~` ranges, because `^` resolves to
4.2.x and 2.4.x, which come from release 1.56 and pull in techdocs-node 2. A lock refresh moves
catalog-backend-module-logs' `^3.8.0` onto 3.9.2.

`.yarnrc.yml`'s three-day age gate let in body-parser 1.20.9/2.4.0 and multer 2.5.0 today. Multer's resolution
goes to 2.5.0, since express-openapi-validator pins 2.4.0 exactly. Express 4.22.3 takes `qs ~6.16.0`, which
clears both qs advisories.

Checks: `yarn install --immutable`, `yarn tsc`, `CI=true yarn test`, `yarn build:backend` and
`backstage-cli config:check --lax` pass. A dev `yarn workspace backend start` initialized all twelve plugins.
`yarn npm audit --all --recursive` still lists only these:

- **Fixed only in a new major:** zod 3.25.76 (fixed in 4.6.6), react-router 6 (7.18), @azure/msal-node 5
  through @azure/identity 4.13 (7.1; even @azure/identity 4.14 asks for `^6`), and postcss-selector-parser 6
  (7.1.6). All four come in through Backstage 1.52 or its build tooling, so they wait for a Backstage release
  that moves them.
- **No fixed release:** node-forge 1.4.0 (see the 2026-10-24 #421 entry) and elliptic 6.6.1.

`verify/test_docs_current.py` skipped only a top-level `node_modules/`. Once this image's dependencies were
installed, it scanned `images/watch-it-burn-backstage/node_modules` and failed on typebox's readme. It now
skips a `node_modules` directory at any depth.

## 2026-10-26 · #511 · the console 404s /brief.html and /kubecon.html, so the router's gate has no side door

The router half of question 716 landed: peopleforrester/apex-agenticburn#37 (staging `2972bd7`) made the
`@brief_not_roster` matcher `path /brief /kubecon`. It goes live when Railway deploys apex-agenticburn main.
That matcher is an exact path match. The console's default server has a `root` over the whole console-src
ConfigMap and no catch-all location, so nginx also serves each page by its file name, and the gate never sees
that name.

- **Measured, not inferred (2026-10-26).** nginx 1.27-alpine (the console's image line) ran this
  `console.conf` behind Caddy v2.11.4 (the router's pin, sha512 checked against the release) with the #37
  matcher. On an attendee host, `bane-sabrina`, `/kubecon` and `/brief` were 404, but `/kubecon.html`,
  `/brief.html` and `/kubecon.%68tml` were 200 with the page. `//kubecon`, `/./kubecon`, `/x/../kubecon`
  and `/%6Bubecon` were already 404, because Caddy normalizes the path before it matches.
- **The fix is on the console, not a longer router matcher.** `location = /brief.html` and
  `location = /kubecon.html` return 404, so each gated page has one name and the router's matcher stays the
  one roster rule (#565). This repo can change the console; the router is a sister repo. Exact locations
  beat every other kind in nginx, so a later catch-all cannot reopen them. `try_files` serves the file inside
  `location = /brief` and `location = /kubecon` without a new lookup, so those two still serve the page.
  After the change, the same rig gave 200 on `/kubecon` and `/brief` for attackme and michael-admin, and 404
  on every `.html` name for every host. No page links to the `.html` names.
- **Held by** `verify/test_gated_page_names.py`, which fails on the previous `console.conf`. The KubeCon
  run-of-show's router step now curls `/kubecon` on the three roster hosts and expects 200, so a router
  matcher that does not know a stage host shows up the night before, not on stage.

## 2026-10-26 · #604 · c8-scoped-role.yaml closes the API read of other Secrets, and the pod mount stays open

Challenge 8's fix scopes agent-sa's Role so the token can no longer dump every Secret: get and list on
`secrets` become get on `ceo-personal-record` by name (`gitops/ai-layer/resources.yaml`, the
`c8-scoped-role.yaml` key of the `challenge-fixes` ConfigMap). The Role keeps create, get, list and patch on
pods and deployments. Measuring #604: agent-sa can still read any Secret in namespace `agent` by mounting it
into a pod it creates, and no workshop admission policy refuses that pod.

The reason is RBAC together with the kubelet. A pod creator needs only create on pods. The kubelet reads a
mounted Secret on the pod's behalf with the node's credentials, so the creator's own RBAC is never consulted
for the mount. The Kubernetes RBAC good-practices page (read 2026-10-26,
`https://kubernetes.io/docs/concepts/security/rbac-good-practices/`) states this directly: permission to
create workloads in a namespace implicitly grants access to the Secrets that can be mounted in Pods there. So
the `resourceNames` on the scoped Role's get does nothing to a mount.

- **Measured 2026-10-26, cluster-free, with the pinned Kyverno CLI v1.19.1** (the engine the admission
  controller runs, #572). Part 1, read from the Role: it keeps create on pods and scopes the Secret read to
  get on `ceo-personal-record`, so agent-sa may create a pod and its API read of `terminal-auth` returns
  Forbidden. Part 2, run through every policy under `policies/kyverno/` and `policies/floor/` (ten Kyverno
  policies and the floor): a pod on the default ServiceAccount, with `docker.io/library/busybox:1.36` (an
  allowed image), resource limits and an ordinary label, mounting `terminal-auth` as a volume and through a
  `secretKeyRef` env var, is refused by none of them. The five that evaluate it (`restrict-image-registries`,
  `verify-image-signatures`, `require-resource-limits`, `restrict-agent-spawned-workloads` and
  `deny-llm-endpoint-bypass`) return pass; the other six do not match a default-ServiceAccount pod in `agent`.
  None of the five looks at Secret volumes or `secretKeyRef`. The pod reads `terminal-auth`, the shared
  web-terminal credential.
- **What the one agent-pod policy checks.** `restrict-agent-spawned-workloads` (a Kyverno ValidatingPolicy,
  Deny) is the only policy written against pods agent-sa creates. It refuses a pod that runs as a
  Bedrock-bound ServiceAccount or carries a NetworkPolicy-trusted label (#490). The same `terminal-auth`
  mount running as agent-sa, or labelled `app.kubernetes.io/name=console`, is denied, on the identity and on
  the label, with no mention of the Secret. On the default ServiceAccount with an ordinary label it passes.
- **Admission draws no line between Secrets.** A pod mounting `ceo-personal-record`, the one Secret the scoped
  Role still reads through the API, is handled identically to the `terminal-auth` pod by all eleven policies.
  The admission plane has no way to know which Secret the RBAC allows.
- **The AWS example #604 names is out of reach.** #584 moved `student-aws-creds` to namespace `student-creds`,
  and a pod mounts only Secrets from its own namespace, so a pod in `agent` cannot mount it. The Secrets a pod
  in `agent` can mount are `terminal-auth` and `console-tls`.
- **Held by** `verify/test_c8_pod_secret_mount.py`, in the E2E tools tier (it needs the Kyverno CLI). No
  policy refusing Secret volumes and `secretKeyRef` env vars for pods created by agent-sa exists yet. The gap
  is item 4 of general-knowledge's `ai-security/2026-10-26_infrastructure-enforced-guardrails.md` note
  (general-knowledge#108); a follow-up on #604 asks for the Kyverno or ValidatingAdmissionPolicy rule that
  would close it.

## 2026-10-26 · #606 · restrict-agent-spawned-workloads refuses the agent a pod that references any Secret but ceo-personal-record

#604 measured that Challenge 8's scoped Role closes agent-sa's API read of other Secrets but not the pod mount: the
kubelet reads a mounted Secret with the node's credentials, so a pod agent-sa created on the default
ServiceAccount could read `terminal-auth`, and no workshop policy refused it. This closes that at admission.

- **Where.** Two new validations on `restrict-agent-spawned-workloads`, not a new policy. It already matches the
  identities the issue names (every ServiceAccount of `agent` but web-terminal), ships Deny with background off
  because it reads `request.userInfo`, and autogen already carries it to Deployments and the other pod
  controllers. A second policy would repeat that match and the reasoning behind it.
- **The line is the scoped Role's.** The policy's `readableSecrets` is `['ceo-personal-record']`, the scoped Role's
  `resourceNames`, and `verify/test_c8_pod_secret_mount.py` holds the two equal. Refused: a `secret` volume, a
  `projected` volume's `secret` source, an env `secretKeyRef` and an `envFrom` `secretRef`, in containers, init
  containers and ephemeral containers. The projected source is in on purpose: leaving it out is a one-line bypass.
  `imagePullSecrets` is left alone, because the kubelet uses it to pull and the pod never sees it.
- **Always on, not only after the C8 fix.** Under the broad Role the agent reads every Secret through the API
  anyway, so the rule takes nothing from a challenge. No workload the agent legitimately makes mounts a Secret: C2's
  villain Deployment reads none, and every platform workload in `agent` that does (the console with `console-tls`,
  web-terminal with `terminal-auth`, guard-proxy and llm-guard with `llm-guard-auth`) is already refused to the
  agent on its label, its ServiceAccount, or by `block-argocd-drift`.
- **The Secrets a pod in `agent` can mount** are `terminal-auth`, `console-tls` and `llm-guard-auth` (the last
  from ai-layer's kustomization secretGenerator; #604's list missed it). All three are refused by every route.
- **Measured 2026-10-26 with the pinned Kyverno CLI v1.19.1.** #604's pod is now refused by this policy alone, on
  the Secret; each route to each of the three Secrets fails with its message; a Deployment is refused at the
  Deployment and an UPDATE likewise; workshop-mcp is held to it. Every route to `ceo-personal-record`, a ConfigMap
  volume and an imagePullSecret pass all eleven policies, and web-terminal, the operator and the ReplicaSet
  controller are not judged. The same test against the previous policy fails 25 checks.

## 2026-10-26 · #607 · the live suite asks the deployed admission controller the #606 question

#606 measured the Secret rule with the pinned Kyverno CLI v1.19.1. `verify/test_llm_bypass_live.py` now asks the
cluster's own controller, as agent-sa, so a run on an attendee cluster shows the two engines agree.

- **Server-side dry run, as the issue asks.** Each request passes authorization and every admission webhook and
  stores nothing, so no Secret has to exist and nothing needs cleaning up. Kyverno judges dry-run requests: the
  kubecon probe's C2 check (`verify/kubecon_probe.py`) already relies on a dry-run refusal.
- **Three shapes, each on the default ServiceAccount with the signed busybox the suite already uses:** terminal-auth
  as a secret volume (expects the mount message), terminal-auth by env `secretKeyRef` (expects the env message), and
  ceo-personal-record both ways (expects `(server dry run)`, admitted). Mount and env are split so each message is
  checked on its own; #606's CLI test takes either message for a pod that reads one Secret both ways.
- **Same verdicts from the CLI first.** The three objects the test builds, run through all eleven policies with the
  pinned CLI as agent-sa on 2026-10-26: only restrict-agent-spawned-workloads fails the two terminal-auth pods, each
  with its message, and every policy that matches the ceo-personal-record pod passes it. So a different live answer
  is the controller's, not the fixture's.
- **A crash fixed on the way.** Since #490 (2026-10-24) the valuefrom shape called `container("c", {}, env=[...])`,
  which raises `TypeError` (env given twice), so the suite stopped right after its prerequisites and never reached a
  pod. `container()` now takes the env list itself as well as a dict of literals.
- **Not yet run on a cluster.** No attendee cluster was up for this run; the next build runs it with CONTEXT set.
## 2026-10-24 · #480 · The #117 rug-pull spike: tool-pin, an ExtMCP processor on its own gateway bind, kept off the deployed path

**What was built.** `images/tool-pin/tool_pin.py` is an agentgateway ExtMCP gRPC server. It hashes each
tool's name, description and inputSchema on the `tools/list` response and strips (default) or denies the
tools not in a pinned baseline. It refuses a `tools/call` for any tool the last list did not approve. The
spike, its runbook and its measurements are in `docs/research/2026-10-24-tool-pin-spike/`.

**Nothing deployed changes.** No Argo CD source references the spike, and `verify/test_tool_pin.py` fails
if a `gitops/` manifest names tool-pin or bind 3003. The bind is rendered from the committed gateway config
by `gateway_bind.py` and applied by hand in `live-check.sh`. Portland's C7 stays on `toolNames`.

- **New dependency: grpcio 1.84.1** (PyPI, released 2026-10-22, the current release on 2026-10-24), only in
  the new `images/tool-pin` image. A gRPC server needs HTTP/2 with trailers; nothing in the workshop-mcp
  image provides that, and writing HTTP/2 plus HPACK by hand is not a spike's job. protobuf and generated
  stubs are deliberately not added: the five messages are encoded by hand from `ext_mcp.proto` at the
  v1.5.0 tag, which keeps the offline suite on stdlib plus PyYAML.
- **Its own bind (3003), one target.** Measured on the local bed with the v1.5.0 binary: the tool names
  stay unprefixed, a dead processor refuses only that bind, and a bad config reload keeps the old config
  serving. A bad config at startup exits 1, so a separate bind does not contain a config typo after a restart.
- **The `tools/call` phase was added because the bed showed it was needed.** A call to the stripped
  `get_weather` was forwarded and answered. v1.5.0 returns that request-phase deny as JSON-RPC `-32001`,
  not the `isError` tool result the "latest" docs describe.
- **The validator moved** from `test_agentgateway_config.py` into `verify/agentgateway_schema.py` so the
  spike's bind is checked by the same code; the committed config's checks are unchanged.
- **Open:** the live kagent check (`live-check.sh`, not yet run; no cluster in this run) and the badge
  decision, recommended in the spike README as "the badge reads the pin's wiring, not its verdicts".
## 2026-10-25 · #588 · The rest of the repo's code names the community, admin and attendee clusters, not rounds
## 2026-10-25 · #588 · The rest of the repo's code names the community, admin and attendee clusters

**lab.html recognises today's roster.** Its instructor test matched the retired names only
(`watch-it-burn-r<n>-<m>`, `michael-round1`, the bare `round1`), so on attackme, michael-admin and whitney-admin a
lab page opened without `?role=` showed STUDENT and reported `witb.lab.role=student`. It now matches the roster
name (`watch-it-burn-community`, `watch-it-burn-<owner>-admin`, as `is_instructor_name` in fleet.sh) or the hostname
(`attackme`, `<owner>-admin`, as `public_host_for`), and tries both on both `?cluster=` and the hostname label,
because #383's nav links carry the friendly name in `?cluster=`. The community cluster counts as an instructor
cluster, as it does for fleet.sh's terminal login and the router's `/brief` gate. An attendee's memorable name is
a menu word and a witch, so none of the 720 slots ends in `-admin`. The fleet-analytics dashboard already filters
by cluster name, so older admin-cluster spans with `role=student` stay out of the attendee view.

**The wording.** Comments in the ai-layer, ai-layer-otel, the Datadog manifest, the Kyverno, KubeArmor and
NetworkPolicy policies, the challenge prompts and toggles, the web-terminal and workshop-mcp images, infra and
the verify helpers used R1, R2/R3, Round N or round-2/3. Each now names the cluster it means: community (burn, no
guardrails), attendee (controls unarmed until the student applies them) or admin (armed at bootstrap). Three
comments were also wrong on the facts and are corrected. block-recipe-snoop.yaml said the full profile includes
kubearmor-policies; only admin does, since #281. scheduled-up.sh's usage said it brings up nine instructor
clusters; it brings up the three roster clusters. resources.yaml said the tier-comparison clusters override the
Agent's modelConfig; that override was deferred (2026-07-07, §4.6-d), and roster.tsv's tier column is read but
never applied (#589). burritbot.html drops the unused `--r1`/`--r2` colours. The agent prompts' instructions are
unchanged; only the `#` notes beside them changed.

**Tests.** `verify/test_round_names_retired.py` sweeps every tracked non-markdown file (`git ls-files`). It names
each path it leaves alone with a reason: `mockups/` (round-era design mockups no cluster serves), the vendored Yarn
release, and the four verify files whose fixtures are the retired vocabulary. Symlinks and submodules are skipped,
because their files belong to their own repos. The guard-proxy submodule's proxy.py still says "Round 1" and
"round-2/round-3", and is filed as a follow-up there. The test also extracts lab.html's two regexes and checks
them against the roster, fleet.sh's hostnames and all 720 attendee slots. Not run on a cluster here.
## 2026-10-26 · #290 · The tool-pin spike's cluster bind moves to :3004, because #514 took :3003 in the same pod

**Found while closing the #290 tracker.** The offline suite was red on staging: `verify/test_tool_pin.py` failed its
check that no `gitops/` manifest names bind 3003. The #480 spike chose :3003 for its pinned evil-mcp bind on
2026-10-24. #514 then put evil-mcp behind agentgateway on :3003 the next day, served by the `agentgateway-c7`
container. That container shares the pod's network namespace with the first container, which is where
`live-check.sh` adds the spike's bind. Run as written, the spike's bind would have collided with C7's, and
repointing the RemoteMCPServer at `agentgateway:3003` would have reached C7's gateway, not tool-pin.

**The change.** `gateway_bind.PINNED_PORT` and `live-check.sh` use :3004 on the cluster. The local bed keeps its
3001/3003/3004 layout and its 2026-10-24 record, because nothing else listens there. `test_tool_pin.py` now
checks that the pinned port is not used by any container port, Service port or ConfigMap bind in
`gitops/ai-layer/agentgateway.yaml`. The gitops check reads the port from `gateway_bind.PINNED_PORT`, so the
two cannot disagree again. The spike is still not run on a cluster.

**The tracker itself.** The approved #290 change (draft 4ed027a) is already on staging. #560 and #588 landed
the code and wording sweep, and #502 removed the roundN alias. All six children (#291 to #296) are closed, so
this run adds no #290 code.

## 2026-10-26 · #609 · one root chart at a pinned revision, for lab-platform

lab-platform (peopleforrester/lab-platform#190) builds an event's clusters from this repo at one 40-digit commit.
It reads `lab-platform.yaml` at the root, creates one root Application per cluster, `lab-bootstrap`, sourcing
`gitops/bootstrap` with `values-<profile>.yaml` and `revision=<commit>`, and fails a cluster on any source from this repo
at another revision. This repo now presents exactly that.

- **`lab-platform.yaml`** is the handoff's section 2 text, byte for byte: `burn` lab, branch `staging`, parameter
  `revision`, profiles attendee, burn, admin and full, each root `gitops/bootstrap` with its values file.
- **The layout is the handoff's section 4.** `gitops/apps/` moved to `gitops/bootstrap/apps/`, because Helm reads
  files only inside the chart; `templates/apps.yaml` renders each listed app through `tpl` and fails on a name with
  no file; `values.yaml` holds only `revision: ""`, so a render without the parameter fails by name. Each of the 21
  sources from this repo says `targetRevision: "{{ .Values.revision }}"`, quoted so the file still parses as YAML for the
  verify scripts. Prometheus' six `{{ $labels.* }}` alert lines are escaped with backticks and render unchanged.
- **Each profile is an explicit list**, copied from what its brace glob selected at b1fcb0e: attendee 29, burn 19,
  admin 33, full 31. The handoff counted burn at 18 because `external-secrets.yaml` was missing from its read; it
  exists here. The act 2 OTTL overlay is not an Application and moved to `gitops/otel-collector/`.
- **No self-source, one name.** The four roots and their `#253` second source are gone. `deploy-full-idp.sh` applies
  `lab-bootstrap` in labctl's shape at `staging` with `revision=staging`, labelled `lab-platform/profile`. Before it
  does, an old `app-of-apps*` root is stripped of its resources-finalizer and deleted, so its children stay for
  `lab-bootstrap` to adopt instead of a second root sitting over them. labctl's root has no `retry`, so this one has
  none either: the workshop path and the event path run the same root.
- **No token on any cluster.** Step [3] no longer writes `witb-repo` with the operator's `gh auth token`; the repo is
  public (`gh repo view`, 2026-10-26) and Argo CD reads it anonymously. It deletes a `witb-repo` an earlier build left.
  `ghcr-kagent-oci`, credential-free, is a chart template at sync wave -10, below kagent-crds' -3.
- **An admin cluster is told by its root's label.** The web terminal's `_c7gw` and the C7 fallback asked whether
  `app-of-apps-admin` existed; with one root name they read `lab-bootstrap`'s `lab-platform/profile` label, which
  labctl and `deploy-full-idp.sh` both set. The terminal's ClusterRole already reads every resource.
- **Clusters built before this need `deploy-full-idp.sh <profile>` again.** Once this is on `staging`, an old root's
  sources (`gitops/apps`, its own directory) no longer exist, so Argo CD reports a comparison error and syncs nothing:
  the children keep following `staging` and nothing is pruned, but the terminal sees no `lab-bootstrap`, so an old
  admin cluster's C7 toggle takes the workshop path until it is re-bootstrapped.
- **Tests.** `verify/test_root_self_managed.py` became `verify/test_bootstrap_chart.py` (the file, the chart, the
  lists, every source's revision, no second root, the deploy root); `verify/test_bootstrap_chart_render.py` renders
  every profile with the pinned Helm v4.2.1 at a 40-digit commit and runs the pin check on the result; the tests that
  expanded root globs read the lists through `verify/bootstrap_chart.py`.
- **Not yet run on a cluster.** No cluster was up for this run. The first build after it should run
  `deploy-full-idp.sh` on a fresh cluster and on one built before, and lab-platform's
  `LAB_TALK_LIVE=1 go test -tags live -run TestTalkConfigLive ./internal/talkconfig` once this reaches `staging`.

## 2026-10-26 · #128 · keep LLM Guard and its scanner config; no replacement is named

The dated finding is `docs/spike-llm-guard-2026-10-26.md`. In short:

- **Keep LLM Guard.** It is archived (0.3.16, 2025-05-19, read live 2026-10-26) and the classifier's weights date
  from 2024-04-23, but no self-hostable alternative has been shown to do C6 better, and C5's output guard is our own
  regex, which does not age.
- **LlamaFirewall's AlignmentCheck is dropped as a candidate.** It is an LLM judge defaulting to Llama 4 Maverick on
  api.together.xyz with `TOGETHER_API_KEY`: a vendor account and egress, against #128's first constraint. This
  reverses the 2026-09-03 comment on the issue that recommended prototyping it.
- **The candidate to measure is Llama Prompt Guard 2 86M**, behind the same `/analyze/prompt` call. Its weights are
  gated on Hugging Face (manual approval), so that measurement waits for someone to be granted them.
- **Scanner config unchanged** (`PromptInjection`, threshold 0.5, match_type `full`). Measured on one core: the
  threshold changes no verdict (scores sit at 1.0 or below 0.0); `full` misses a payload past the 512-token window;
  `chunks` and `sentence` catch it but take 11 s and 16 s on a 4,000-character prompt, past the 10 s
  `scan_prompt_timeout`, which guard-proxy turns into a fail-closed refusal of any long prompt.
- **New gate:** `verify/test_injection_classifier.py` (E2E tools tier) runs the real scanner with the deployed params
  over C6's ticket, input-guard.sh's injection, the ticket without its payload, and every on-topic ask in
  `topic_cases`. A threshold of 1.0 fails it on both attacks. `verify/injection_config_matrix.py` re-runs the
  measurement; it is a tool, not a test.

**New dev dependency, fetched only by those two scripts through `uv run`, never installed into the offline suite:**
`protectai/deberta-v3-base-prompt-injection-v2` at `90c9989b1a342275dd0d1a95aad283c04e075671` (2026-07-09,
Apache-2.0), the revision the offline image mirrors, downloaded from Hugging Face on the first run. llm-guard 0.3.16
and torch 2.14.0+cpu are the pins `verify/test_topic_classifier.py` already records (2026-10-24 entry above).

## 2026-10-26 · question 674 · #457: the 10-26 cold-read event points at this repo's run of show

**Question 674:** Repoint the description of the Mon 2026-10-26 10:00 to 16:00 Central cold-read event on
Michael's primary calendar (event `ia767ji9f7ik5pimaqsogc2hg8`) at this repo. Its description still told
Whitney to run BurritoBot's RUNBOOK.md and file issues in peopleforrester/Kubecon-NA-2026-Whitney-BurritoBot,
which is archived, so no issue can be filed there. A calendar write is Michael's to make, so the question
offered replacement text.

**Answer:** Michael pastes the suggested text into the event description.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**What it changes:** the edit is on the calendar, not in this repo. A coordinator comment on #457
(2026-10-26) says the event now carries the suggested text, and this run read it back on 2026-10-26: the
event was updated at 11:23 UTC and its description is word for word "Whitney reads
facilitation/kubecon-na-2026-run-of-show.md cold against the live platform, from Night Before through
Teardown, and files one issue in peopleforrester/Unleash_an_Agent_Watch_It_Burn for every stop or guess. Log
it under Run-through record. The read waits for the platform to be live (Watch_It_Burn#447, #454); no paper
read." The event's title still reads "BurritoBot runbook cold read (Whitney reads, live cluster, file an
issue per stop)"; BurritoBot is the talk's name, not the archived repo, so it is left as it is. The run of
show's "Dates to hold" row already sends the read here and logs it under "Run-through record", so nothing in
the repo changes. The second half of #457, whether the Wed 2026-10-28 09:00 to 12:00 Central "PREP: BurritoBot
rehearsal with Whitney" block stays or goes, is not decided: it is still on the calendar with Whitney's reply
at needsAction, and the run asks it again as one decision.

## 2026-10-26 · question 845 · #457: the 10-28 rehearsal block with Whitney stays

**Question 845:** Should the Wednesday 2026-10-28 09:00 to 12:00 Central block "PREP: BurritoBot rehearsal
with Whitney" stay on Michael's calendar, or be cancelled? mrf-engagement-orchestrator, Michael's engagement
scheduler, created it on 2026-10-19 as the cold read "moved" (conference-knowledge#119), but the Monday 10-26
cold read stayed on the calendar too, and the block was not one of #447's dates. It asks again question 673,
which was withdrawn unanswered.

**Answer:** Keep the 10-28 block.

**Decided by:** Michael.

**What it changes:** the run of show's "Dates to hold (#447)" table gains a row for it: Michael and Whitney,
the calendar hold Wed 2026-10-28 09:00 to 12:00 Central. If the cold read has not yet run against the live
platform, it runs there; otherwise the block is run-through 1. Either way it is logged under "Run-through
record". `verify/test_kubecon_dates.py` holds the row. Nothing on the calendar changes. Read on 2026-10-26,
the event (`ut2drd1on015dlqapkr71gocc4`) is unchanged since 2026-10-19, has no description, and Whitney's
reply still reads needsAction. No issue for a cold-read stop was filed here on 10-26. Confirming with Whitney
and writing the block's purpose into its description are calendar and personal actions, so they are left to
Michael. With this, both halves of #457 are settled: the 10-26 event points here (question 674, entry above)
and the 10-28 block stays.

## 2026-10-26 · #622 · lab-platform's images take their registry from lab-bootstrap's `imageRegistry`

lab-platform's packages on ghcr.io are private, so each workshop cluster pulls them through its AWS account's ECR
pull-through cache, and lab-platform's bootstrap passes the cache path to `lab-bootstrap` as the Helm value
`imageRegistry` (peopleforrester/lab-platform#214), shaped
`<account>.dkr.ecr.<region>.amazonaws.com/<prefix>/peopleforrester/lab-platform`. A containerd mirror for ghcr.io
cannot carry ECR's credential, so the cache works only if the image reference names the cache path.

- **The value.** `gitops/bootstrap/values.yaml` sets `imageRegistry: ghcr.io/peopleforrester/lab-platform`, which a
  root that passes nothing gets: `infra/deploy-full-idp.sh`, and an account with no cache. `templates/apps.yaml`
  fails the render by name on an empty value, one with a scheme or one with a trailing slash, since no image can be
  named under any of them.
- **Where a reference goes.** An app file in `gitops/bootstrap/apps/` names a lab-platform image in its Helm values
  as `"{{ .Values.imageRegistry }}/<path>:<tag>"`, which `tpl` fills in like the revision. A plain manifest a
  directory source applies cannot take the value, so a lab-platform image never goes there.
- **Nothing names one yet.** At this commit no file names `ghcr.io/peopleforrester/lab-platform`; the mirror/
  copies of lab-platform's `deploy/mirror/copies.tsv` are lab-platform#183, still open. Pointing the charts at them
  is that issue's work, done through this value.
- **Tests.** `verify/test_image_registry.py` (offline) fails on the literal anywhere the root deploys from (all of
  `gitops/`, and every other path an app file sources from this repo) except the default, and on the template
  text outside `apps/`. `verify/test_image_registry_render.py` (E2E tools tier, Helm v4.2.1) renders every profile
  unset, at the default and at a cache path: unset equals the default, the cache render names no
  `ghcr.io/peopleforrester` and is today's render with only the registry changed. A fixture app in a copy of the
  chart names a KubeArmor mirror copy in `valuesObject` and in a `values` block, and is checked both ways.

## 2026-10-26 · #473 · The customer-stream app is removed

**What went.** `gitops/bootstrap/apps/customer-stream.yaml`, `gitops/manifests/customer-stream/` (a ConfigMap,
a generator and a consumer Deployment, and a Service in `apps`), its line in each of the four profile lists
(`gitops/bootstrap/values-{attendee,burn,admin,full}.yaml`, which since #609 replace the burn root's include
selector), and `verify/test_customer_stream.py`. The #236 audit
(`docs/research/2026-10-24-duplicative-components-audit.md`) found nothing reads the stream: C1's
humans-versus-vampires answer comes from `get_marketing_intel`, which reads `marketing.json` inside
`workshop-mcp`, and the stream predates the switch from the S3 push to the chat leak. Git history keeps the
manifests. On a live cluster the root prunes the child Application and its resources-finalizer removes what it
created.

**The counts.** Every profile listed the app, so each cluster runs one fewer Application. An instructor cluster
now shows 37 Argo CD applications and an attendee cluster 33, down from the 38 and 34 that #478 set. The
platform page, the run-of-show, the design glance and `verify/test_fleet_contract.py` carry the new numbers.
Like #478's, they are the measured counts less one, not a fresh measurement on a live cluster. The profile
lengths `verify/test_bootstrap_chart.py` holds drop by one each: attendee 28, burn 18, admin 32, full 30. The
recreation spec and readiness checklist no longer list the app, and the drift test's comment describes the
require-labels failure without naming it. This is the approved draft a8fc6ff (redone as ac363f5), made again on
staging after #609's chart conflicted with it.

## 2026-10-24 · #474 · Loki and Alloy are dropped; the #190 audit trail is read from Datadog Logs

**Why:** the #236 audit of duplicate components found that no student surface reads Loki, and its one
consumer was the live half of `verify/test_tool_audit_live.py`. The same workshop-mcp audit lines already
reached Datadog through the Agent's `containerCollectAll`. Dropping the pair saves two Argo CD apps and a
5Gi gp2 volume on every cluster.

**What it changes:**

- `gitops/apps/loki.yaml` and `gitops/apps/alloy.yaml` are deleted. Every app-of-apps profile reads
  `gitops/apps` as a directory with `prune: true`, so Argo CD removes both apps from a live cluster on the
  next sync. A StatefulSet's PVC outlives the StatefulSet, so on a cluster that already ran Loki the 5Gi
  volume stays until the cluster is rebuilt or the PVC in `monitoring` is deleted by hand.
- Grafana loses its Loki data source and Tempo's trace-to-logs link to it (`gitops/apps/prometheus.yaml`).
  The Loki row leaves `platform.html`, `links.html` and `diagram.html`. The Backstage catalog loses its
  Loki entry and a Promtail entry that had been stale since Alloy replaced Promtail.
- The live half of `test_tool_audit_live.py` now searches Datadog Logs (`POST /api/v2/logs/events/search`)
  in the cluster's own org, with the keys the Agent itself ships with (`datadog/datadog-secret`), on the
  site the DatadogAgent CR names. It selects by tag (`kube_namespace`, `kube_deployment:workshop-mcp`) and
  matches the identity in the test, so it does not depend on `agent_identity` being a facet in a fresh
  trial org. The stream-label check becomes a tag check: `pod_name:workshop-mcp-*` and
  `kube_container_name:shim`. Datadog's timestamps are milliseconds, so pre-before-post is checked on the
  line's own `ts`, not on result order.
- `verify/test_alloy_labels.py` (#464) is deleted with the config it checked. `test_tool_audit.py` now holds
  offline the wiring the trail depends on instead: log collection on, `containerCollectAll` on, nothing
  excluding workshop-mcp's logs.
- The deck line that names Loki (`facilitation/slides-outline.md`) is not changed: the issue leaves that
  prose to Michael.

## 2026-10-24 · question 687 · Loki is dropped from the deck's list of what runs on the platform

**Answer:** Drop Loki from the list.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**Background:** Issue #474 removes the Loki and Alloy Argo CD apps from every cluster, and the platform page
no longer lists Loki. `facilitation/slides-outline.md` line 43 (slide 6, "The platform you get") still listed
Loki as part of what attendees get, so the slide named a component no cluster runs. It was the only Loki
mention in the repo's deck material. Michael's verified-stack record in talks-knowledge
(`speaking/devopsdays-portland/stack-verified.md`, 2026-09-03) lists Loki under "Observability, fallback". That
record is a dated snapshot that #474 makes stale. It is not edited here, since it lives in another repo.

**Why this is a correction and not new prose:** earlier runs changed slides-outline.md facts directly (#417
replaced a stale slot time with a pointer to conference-knowledge). New prose was kept as a draft for Michael
(#466, the 2026-10-24 entry above). Cutting one component that no longer exists is a factual correction, and
CLAUDE.md's "Bias to action" rule applies.

**What it changes:** `facilitation/slides-outline.md` line 43 drops "Loki," from the list. Nothing else in the
slide or the outline changes. The rest of the list is still Argo CD, Kyverno, Falco, Prometheus, Grafana,
Tempo, cert-manager, External Secrets and Backstage.

## 2026-10-25 · #474 · The Tempo-to-Loki trace link goes too, and the branch is rebased onto staging

**Why:** the first attempt at this branch failed to rebase onto `origin/staging` (run 7819, `rebase-conflict`).
Upstream had moved the Tempo data source out of `gitops/apps/prometheus.yaml` into `gitops/tempo/` (#475), and
replaced the Grafana ALB Ingress with per-cluster hostnames (#493). Both changes touched the same lines this
branch edited. The conflicts were resolved by taking upstream's side of each hunk and removing only the Loki
references. No upstream change was reverted.

**What it changes:**

- `gitops/tempo/grafana-datasource.yaml` no longer carries `tracesToLogsV2` pointing at uid `loki`. Without it,
  Tempo's trace view would offer a log link to a data source that no longer exists. It was missed in the first
  pass of #474 and is found only on rebase.
- `verify/test_observability.py` read `pvals["grafana"]["additionalDataSources"]` directly. That key no longer
  exists in `prometheus.yaml`, so the test would have raised KeyError rather than failed cleanly. It now reads
  the key with a default, and asserts that no Loki data source remains and that Tempo's data source links to
  no Loki.
- Upstream's wording on `platform.html`, `links.html`, `gitops/README.md`, `docs/MASTER-RECREATION-SPEC.md`,
  `verify/test_service_hosts_live.py` and `verify/test_service_links.py` is kept. Only the Loki entries are
  removed. Tempo's "instructor clusters only" wording stays as upstream wrote it.
- The Loki and Alloy reference in `verify/test_service_hosts_live.py` is removed. Its Tempo handling on attendee
  clusters (#475) is unchanged.

**Checked:** `bash verify/run-tests.sh` passes (117 tests). The E2E checks were not run, because no cluster is
provisioned in this run.

## 2026-10-26 · #474 · The stated Argo CD app counts drop by two with Loki and Alloy

**Why:** the approved #474 branch (draft `7c0e800`) conflicted with staging in `docs/DESIGN-GLANCE.md`, so the
change is made again on current staging. Since that draft, #551 made `verify/test_fleet_contract.py` count the
attendee profile's Applications from the manifests and hold the docs to the number. Loki and Alloy are one
Application each and every profile but burn selected both, so the counts fall by two.

**What it changes:**

- Attendee clusters run 32 Argo CD Applications, the app-of-apps included, down from 34. Instructor clusters
  run 36, down from 38: 30 platform components, 5 demo apps and the root. `docs/DESIGN-GLANCE.md`,
  `docs/RUN-OF-SHOW-2026-08.md`, `platform.html` and the fleet-contract checks say so.
- The glance paragraph's observability clause reads "Prometheus and Grafana, with pod logs going to Datadog
  only", keeping staging's "Falco Talon and Tempo run on instructor clusters only".
- The run-of-show's layer table drops Loki from the observability row.
- `docs/ABSTRACT.md` is not changed. It is the working copy of published listings and already says to leave
  the number out.

## 2026-10-26 · #474 · Loki and Alloy leave the bootstrap chart's profile lists

**Why:** the approved #474 draft (`afea397` on `agent/474-9586`) conflicted with staging after #609 moved
`gitops/apps/` into the `lab-bootstrap` Helm chart at `gitops/bootstrap/apps/`, with each profile an explicit
list in `values-<profile>.yaml`. The change is made again on that layout, keeping the approved design.

**What it changes beyond the approved draft:**

- `gitops/bootstrap/apps/loki.yaml` and `alloy.yaml` are deleted, and `loki` and `alloy` leave
  `values-attendee.yaml`, `values-admin.yaml` and `values-full.yaml` (burn never listed them). The chart fails a
  render on a listed name with no file, so the lists and the files go together. The 2026-10-24 entry's "every
  app-of-apps profile reads `gitops/apps` as a directory" is how it was then; now `lab-bootstrap` stops
  rendering the two Applications and its sync prunes them, with the same PVC caveat.
- `verify/test_bootstrap_chart.py` holds the lists at attendee 27, burn 19, admin 31 and full 29, down two
  each but burn, and checks that no profile names loki or alloy.
- `verify/test_tool_audit.py`'s "no Loki or Alloy app is left" check looks in `gitops/bootstrap/apps/`; on
  the old path it would have passed whatever that directory held.
- Staging's text is kept everywhere else: `gitops/README.md`'s chart layout (it no longer states a manifest
  count), the run-of-show's `kubectl get applications` comment (now 36 apps, 32 on an attendee cluster, with
  staging's "1 app-of-apps root, lab-bootstrap"), `MASTER-RECREATION-SPEC.md`'s step 4, and the
  `gitops/bootstrap/apps/` paths in `STACK-WALKTHROUGH.md`, `links.html` and `observability-idp/README.md`. Only
  Loki, Alloy and Promtail are removed from them.

## 2026-10-24T05:37:40Z · 2.2 · Plan-time policy toolchain for the fleet Terraform (#200)

**New dependencies, pinned 2026-10-24 to the current release of each** (`infra/policy/plan/tools.yaml`,
installed by `install-tools.py`, binaries checked against the sha256 each project publishes):

- **Kyverno CLI 1.19.2.** Runs the four starter `ValidatingPolicy` files in JSON mode. The brief wanted
  1.18 or later for the `--json` nil-pointer fix; 1.19.2 is the current patch on the 1.19 line the brief
  named. 1.19 has no `kyverno json` subcommand: the JSON-mode path is `kyverno apply <policies> --json
  <payload>`, which is what `check-plan.py` calls. The standalone kyverno-json binary is not used.
- **Checkov 3.3.30 and Trivy 0.76.1.** The brief pinned 3.2.x and 0.70.x on 2026-09-03; both lines have
  moved on since. tfsec (merged into Trivy) and Terrascan (archived 2025-11-20) are not added.
- **Trivy comes from its release tarball, not `aquasecurity/trivy-action`.** The brief asked for the
  action to be pinned to a commit SHA, because its release infrastructure was compromised in March 2026.
  A checksum on the binary is the stronger pin, and it makes the action unnecessary.
- **Terraform 1.17.0 and OpenTofu 1.13.2.** These are for the e2e suite only. It plans the same fixtures
  and the fleet with both binaries, to prove the checks read an OpenTofu plan natively. The build host's
  Terraform pin in VERSIONS.lock is unchanged.
- **moto 5.2.4.** A local AWS API. `plan-fleet.py` plans the real `aws/network` and `aws/cluster` roots
  against it, with no AWS account: the module logic runs as it does for real, and only API-sourced values
  (account id, subnet ids, AMI and addon versions) are made up. moto lacks EKS DescribeAddonVersions and
  SSM GetParameter, so a small in-process stub answers those two calls.

**Scope of the scanner gate.** Checkov and Trivy fail the check only on the rules in `gates.yaml`, which
re-check the four starter policies. Everything else they find is printed as advisory on every run.
Gating on their whole catalogues would fail a private, encrypted bucket for having no cross-region
replication, and an exception list that long stops being read. To promote a check, add one line to
`gates.yaml`, plus an `exceptions.md` row for each finding the fleet already has.

**Exceptions came from a plan of the real fleet, not from reading HCL.** A Checkov scan of the HCL
reported findings in module blocks that `count` disables (appmesh, velero, cluster-autoscaler policies the
fleet never creates). Reading the module source gave the wrong addresses too: `custom[0]`, where the
modules actually create `ebs_csi[0]`, `lb_controller[0]` and `external_secrets[0]`. Each row in `exceptions.md` matches a
finding on the mock-AWS plan, and the e2e suite fails when one stops matching.

## 2026-10-24T17:12:43Z · question 592 · The plan-policy check runs on GitHub-hosted runners, against the AWS mock

**Question 592:** #200's plan-policy check is built and proven locally, but no CI workflow runs it yet.
Where should it run on PRs that touch infra/terraform/** or infra/policy/plan/**? This repo is public,
and llm-coding-workflow#145 rules out fork-PR code on the netcup runner. plan-fleet.py can now plan the
real fleet roots against a local AWS mock, so a CI plan no longer needs AWS credentials.

**Answer:** GitHub-hosted ubuntu-latest, with the fleet planned by plan-fleet.py against the mock. CI
holds no AWS credentials or secrets, fork PRs are checked safely, and Actions minutes on a public repo
are not metered (llm-coding-workflow#194). This matches the draft rule in llm-coding-workflow#202 that
public repos taking fork PRs use hosted runners.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**What it changes:** `.github/workflows/plan-policy.yml` is added. On every PR, and every push to
staging or main, that touches infra/terraform/**, infra/policy/plan/**, the plan-policy tests or the
workflow, it:

1. installs the pinned toolchain with install-tools.py;
2. plans aws/network and aws/cluster with plan-fleet.py;
3. fails on any unexcused finding or stale exception (`check-plan.py --require-all-exceptions-used`);
4. runs the Terraform and OpenTofu self-test (verify/test_plan_policy_e2e.py).

actions/checkout and actions/setup-python are pinned to commit SHAs (v7.0.1 3d3c42e5, v7.1.0 6d4fd22b,
read from their release tags 2026-10-24). PyYAML is pinned at 6.0.3 for the job. The workflow is not on
the netcup runner and takes no OIDC role. A real-account plan (#201's pipeline role) stays a separate
decision.
## 2026-10-28 · #523 · The E2E tools are on the dispatch host; only the cluster, AWS and otelcol-contrib remain

Hecaton's toolchain installed the 2026-10-25 #523 entry's pins on 2026-10-26. On 2026-10-28 the run PATH
(`/var/lib/hecaton/cli:/usr/local/bin:/usr/bin:/bin`) has kyverno 1.19.1, conftest 0.71.1 (OPA 1.21.1),
terraform v1.15.6, aws-cli 2.38.5 (`/var/lib/hecaton/toolchain/aws-cli/v2/2.38.5`), kubectl v1.36.2 and helm
v4.2.1, which also covers #439. Kyverno stays v1.19.1, the deployed version, not the issue's v1.19.0.

With CONTEXT and the IAM pipeline variables unset, `bash verify/run-e2e.sh` fetches its five pinned tools (#585)
and exits 1 listing three items: IAM_PIPELINE_PROFILE/IAM_PIPELINE_REGION, CONTEXT, and otelcol-contrib v0.160.0.
That last one became a prerequisite with #150 and was not in this issue. It is filed as a follow-up to fetch it
through `verify/e2e-tools.lock`, as the other pinned tools are. No code changes here.
## 2026-10-28 · #600 · fleet.sh ingest registers through `labctl import`, not POST /admin/import

lab-platform has an import entry point for clusters built here (peopleforrester/lab-platform#62, commit fc4b6d9):
`labctl import --customer agenticburn --event <event> -` reads pool.csv rows on stdin. The provisioning app's
/admin/import, which ingest used to POST to, left these clusters out of the handout pool that the inventory's
Load clusters fills.

- **The pipe.** `ingest_one` builds the same row as before, adds a `role` column, turns the row into a quoted
  header and one CSV line with `jq @csv`, and pipes it to labctl. The event is `WIB_EVENT`, the fleet's event
  tag (`event.sh`), the same value `labctl harvest` finds the clusters by (#602). Three attempts, as the POST had,
  then a named `ingest:<name>` failure carrying labctl's last line of output.
- **role.** `instructor` for a roster cluster (`is_instructor_name`: the community cluster and each
  `<owner>-admin`), empty for an attendee. lab-platform hands out any row without role=instructor, so a roster row
  sent without it would be claimable by the room.
- **What it needs.** labctl on PATH, `DATABASE_URL` (lab-platform's database) and `USER`. `labctl_ready` checks
  all three and names what is missing. `register_with_provisioning` checks it where it used to resolve the admin
  token, and stays loud: no labctl means "was NOT registered" and an `ingest:no-labctl` failure. `ingest` and
  `ingest-instructors` exit 1 before touching a cluster.
- **Not moved.** `ingest pool` still reads its names from the provisioning app's /admin/roster, and teardown's
  deregister still POSTs /admin/delete there, both with the admin token. The issue covers ingest only.
- **Test:** `verify/test_fleet_terminal_harvest.sh` (offline) gives labctl a shim and checks the arguments, the
  environment, a header with one row, role=instructor on both roster clusters and an empty role on an attendee,
  the three attempts, and the loud failure when DATABASE_URL or USER is missing. No cluster and no lab-platform
  database were touched.
## 2026-10-28 · #624 · fleet.sh deregisters through `labctl deregister` and releases through `labctl release`

lab-platform took over clearing the handout pool from the provisioning app (peopleforrester/lab-platform#66, commit
0590215; its docs/provisioning.md section 9, "Removing torn-down clusters and releasing claims"). This follows #600,
which moved ingest to `labctl import`.

- **Deregister.** `labctl_deregister [--release-claimed] <name...>` runs `labctl deregister --customer agenticburn
  --event $WIB_EVENT <name...>` with DATABASE_URL and USER, where `deregister_one` used to resolve the admin token
  and POST /admin/delete. `deregister_one` (teardown, `reconcile-pool` under WIB_APPLY=1) calls it with one name
  and keeps its contract: WIB_NO_INGEST=1 opts out, and a failure is a `deregister:<name>` entry, never fatal.
  `fleet.sh deregister` sends all its names in one labctl call, as section 9 does.
- **A refusal.** labctl exits non-zero for a cluster still claimed or a name the pool does not hold. Every name in
  that call is recorded as `deregister:<name>`, with labctl's last line of output, and the log says to tell the
  attendee their cluster is going and then run `fleet.sh deregister --release-claimed <name...>`. fleet.sh passes
  `--release-claimed` straight to labctl; it never adds it on its own, so teardown cannot take a claimed cluster
  from an attendee without someone deciding to.
- **Release.** New verb `fleet.sh release <email...>` runs `labctl release --customer agenticburn --event
  $WIB_EVENT <email>` once per email, for a mis-claim or a rehearsal reset. fleet.sh never called /admin/release;
  that step was done by hand against the provisioning app. Under labctl the released cluster leaves the pool for
  good instead of becoming claimable again, and the verb's log and usage say so.
- **By hand is loud.** `deregister` and `release` exit 1 before running labctl when labctl, DATABASE_URL or USER is
  missing (`labctl_ready`, which now takes the step's name for its log line), and WIB_NO_INGEST does not silence
  them: a by-hand verb that quietly does nothing is worse than one that fails.
- **Not moved.** `reconcile-pool` and `ingest pool` still read the pool's names from the provisioning app's
  /admin/roster with the admin token. Ghosts are now deregistered from lab-platform's pool, so a name that is only
  in the provisioning app's roster is refused by labctl and stays a recorded failure. Filed as a follow-up.
- **Not checked against lab-platform.** Its repo could not be read from this run, so the commands follow the issue
  text. The position of `--release-claimed` (before the names) is the one assumption beyond it.
- **Test:** `verify/test_fleet_teardown_hooks.sh` and `verify/test_fleet_pool_reconcile.sh` (offline) give labctl
  a shim and check the arguments, the environment, one call for all names, `--release-claimed` passed through,
  the refusal message and ledger entries, release per email, the loud exit without DATABASE_URL or USER, and that
  nothing calls /admin/delete or /admin/release. No cluster and no lab-platform database were touched.
## 2026-10-28 · #630 · The gateway pin survives a late Deployment, and converge does not say CONVERGED over a failed repair

The 2026-10-27 `fleet.sh instructors up michael` logged "could not point agentgateway's BEDROCK_NOVA_MODEL" on the
admin cluster, and the converge that followed printed CONVERGED for it while the Deployment stayed on
`us.amazon.nova-pro-v1:0`, so the gateway path billed untagged.

- **The cause was the policy, not the timing.** "Could not point" is the message for a refused patch; a Deployment
  that never appears logs "never appeared" instead. block-argocd-drift denies the operator's UPDATE of an
  Argo-managed Deployment on an armed cluster, and community ships no policies, which is why the same step passed
  there. 7210a3b already makes the gateway patch as the Argo controller, which the policy admits.
- **The late Deployment is tested anyway.** pin_bedrock_profiles already polls each target until it appears
  (WIB_MODELCONFIG_WAIT, 300 s), the gateway included. `verify/test_pin_bedrock_profiles.sh` now has the shim
  create the agentgateway Deployment three reads late with block-argocd-drift armed, and checks that it is waited
  for and pinned with nothing recorded as failed. Without the impersonation that case fails.
- **converge_one's verdict reads the ledger.** repair_one's repairs and verifiers report through the failure ledger,
  not a return code, so converge_one printed CONVERGED on apps and console alone. It now counts this cluster's
  ledger lines before repair_one (`ledger_of`) and prints `NOT CONVERGED (..., but failed: <what>)` when the pass
  added any. Lines from before the pass, which the pass may have repaired, and other clusters' lines do not count.
  The round loop and the final verdict already read the ledger and are unchanged. `verify/test_platform_floor.sh`
  holds it.
- **Not verified on a cluster.** No admin cluster was built in this run. The live check is
  `verify/test_gateway_bedrock_tagged_live.py` after the next admin bring-up.
## 2026-10-28 · #590 · PRD #13's UST rows carry the current values, with history

#590 asked whether PRD #13's Locked Decisions rows should be updated to the UST values the manifests now emit, or
left as a record of 2026-06-23 with a pointer to `verify/test_observability.py`. The repo had already answered for
one row: #586 moved the kagent `service.version` row to v0.10.1 in place, with "was v0.9.9 until ..." after it, and
#599 made `verify/test_kagent_version_pins.py` fail if that row goes stale. The other rows follow the same pattern.

- **Values.** The service names are `burritobot-agent`, `burritobot-gateway`, `burritobot` and `burritobot-evil-mcp`,
  after the 2026-09-06 rename to one service family (#265). agentgateway's `service.version` is `v1.5.0`: the
  image moved on 2026-09-10 and the span version followed on 2026-10-24 (#495). `deployment.environment.name` is
  `burritobot-kubecon-na-26`, which replaced `production` on 2026-10-27 (#629). #590 did not name the env row, but
  it was out of date in the same way. Each row then gives the old value and the date it changed.
- **Where else.** The Milestone 3 goal and pod criteria, the Milestone 4 service-name list and the Acceptance
  Criteria now give the same values. Two paths that no longer exist were corrected: `gitops/apps/kagent.yaml` is now
  `gitops/bootstrap/apps/kagent.yaml`, and `agent/gateway/agentgateway.yaml` is now `gitops/ai-layer/agentgateway.yaml`.
  The Problem section still describes the June state, as a record.
- **Test.** `verify/test_prd13_ust.py` (offline) reads each component's `OTEL_RESOURCE_ATTRIBUTES` from
  `gitops/ai-layer/` and fails if the table, the Milestone 3 and 4 criteria or the Acceptance Criteria give a
  different current value. History may follow the current value. The kagent version row stays with
  test_kagent_version_pins.py, which holds it to the chart. Against the PRD before this change, it failed 19 checks.
## 2026-10-28 · #637 · The prompt wall is a Night Before check and the segment 2 projector

prompts-agenticburn asked for the prompt wall, `https://prompts.agenticburn.com`, in the KubeCon Night Before and
run-of-show.

- **A verb, not a curl to read by eye.** `fleet.sh wall-check` reads the wall's `/healthz` and fails unless it
  answers 200 and lists every roster cluster, by the first label of `public_host_for` (`attackme`,
  `burritobot-private`), with `ok` true. The names come from roster.tsv, the same source router-check uses, so a
  new roster row needs no edit here. A listed cluster with `ok` false fails too and prints the wall's error:
  listed but unreadable shows nothing on the projector. A cluster beyond the roster does not fail it, because the
  wall mirrors the router's roster.json and router-check already fails on an extra host.
- **Order.** It runs after router-check and before check-tls: the wall builds its list from roster.json, so it
  is only meaningful once router-check passes.
- **Segment 2 projects the wall.** The run-of-show's segment table and segment 2, and `/kubecon`'s segment 2 and
  header, name the wall URL. The cluster's own `/display` stays as the fallback if the wall is down.
- **Kept through the event.** The step says not to move the wall onto lab-platform's roster before 2026-11-12,
  which leaves out attackme and the admin cluster until lab-platform#137 lands (prompts-agenticburn#11).
- **Test:** `verify/test_fleet_wall_check.sh` (offline, curl stubbed). Run live and read-only on 2026-10-28: the
  public wall answered 200 and showed both clusters.

## 2026-10-28 · #623 · The charts pull lab-platform's mirror/ copies of their Docker Hub images

lab-platform#183 handed over its `deploy/mirror/copies.tsv` on 2026-10-28 (this issue, comment 6474733299): each
vendor image copied under `ghcr.io/peopleforrester/lab-platform/mirror/`, tagged with its upstream tag and the first
twelve characters of its linux/amd64 manifest digest. The copies are public, so the issue's "settle one thing" is
settled by the packages, not by `infra/deploy-full-idp.sh`: it still passes no `imageRegistry`, and the default
pulls. lab-platform 5192c1a reverted the ECR cache path, so no root passes the value today; the comments in
`values.yaml` and both registry tests that called the packages private now say so.

- **Re-rendered first.** Each chart was rendered at this commit with its app file's values. 14 of the 16 rows match
  what a chart pulls and are named. The falco and falcoctl rows do not: copies.tsv was resolved at 01c1d9e, and
  89fce6a took Falco chart 9.2.1 (falco 0.45.1, falcoctl 0.14.2, the kernel 6.18 fix), so naming the 0.44.1 and
  0.13.0 copies would downgrade Falco. Both stay on Docker Hub until lab-platform copies the tags the chart pulls.
  k8s-sidecar is on quay.io and Alloy and Loki left with #474, so none of those has a copy.
- **Where each is named.** In its app file's Helm values, as `"{{ .Values.imageRegistry }}/mirror/..."`, split
  across the keys the chart builds the reference from (registry, repository, name, tag): falco-talon,
  falcosidekick, kagent (bundled postgres and grafana-mcp), kube-prometheus-stack's Grafana, tempo, the operator's
  `manager.collectorImage`, and the collector, whose `image` moved from the shared
  `gitops/otel-collector/values.yaml` (a `$values` file `tpl` never renders) into `valuesObject` in each of the three
  `otel-collector*.yaml` app files.
- **KubeArmor.** The operator image is the chart's `kubearmorOperator.image`. The kubearmor, init, relay and
  controller images are KubeArmorConfig fields, set under `kubearmorConfig`, which the chart writes into the
  `kubearmor-default` KubeArmorConfig. The snitch has no field: the operator (v1.7.4, `common.GetApplicationImage`)
  reads `RELATED_IMAGE_KUBEARMOR_SNITCH`, and without it names `docker.io/kubearmor/kubearmor-snitch` with the
  operator image's own tag (`NewClusterWatcher` splits it off the Deployment's image). On the copy's tag,
  `v1.7.4-84626528c4d6`, that tag does not exist on Docker Hub, so the env is set to the copy of `:latest`. That
  moves the snitch from the `v1.7.4` build (`sha256:047908ef…` on Docker Hub, 2026-10-28) to the copy of `latest`,
  the tag lab-platform copied and the one relay and controller already run; a live cluster build should confirm the
  snitch job labels the nodes.
- **Tests.** `verify/mirror_copies.py` holds the 16 rows, the two unpulled ones apart. `test_image_registry.py`
  (offline) checks each tag ends in its digest's first twelve characters and each app file names its copies'
  tags under the value. `test_image_registry_render.py` (tools tier, now needing the network for the upstream
  charts) renders each app through the root, unset and at a cache path, then renders its chart with the values the
  root produced: every copy is named at ghcr.io unset and at the cache path set, the replaced upstream reference
  is gone, and the falco chart still does not pull the two unpulled tags. `test_mirror_copies_public.py` (tools
  tier, new) reads every named copy from ghcr.io with no credential and checks it serves its digest; all 14 did on
  2026-10-28.
## 2026-10-28 · #636 · Every cluster carries its role as the role= tag, so harvest can leave the roster out of the pool

lab-platform's `labctl harvest` finds the fleet by its `project` and `event` tags and reads each host from
`hostname` (#602). The roster clusters (watch-it-burn-community at attackme, watch-it-burn-private at
burritobot-private) carried the same tags as the attendee seats, `Purpose=attendee-cluster` included, so harvest
could not tell them apart and would pool them for students.

- **The tag is `role`, in `fleet_tags`.** The cluster root adds `role = var.role` beside `hostname`, so the
  provider's default_tags put it on the cluster and every resource, and the node launch templates, CNI ENIs and
  Bedrock application profiles carry it with the rest of `fleet_tags`.
- **Every cluster gets one, attendees included.** `community` or `admin` for a roster cluster, `attendee` for a
  seat. That is the value `infra/TAGGING.md` already gave the `role` key, and it lets harvest select the pool
  positively (`role=attendee`) instead of relying on a tag being absent.
- **The value is `role_for_cluster`, from `role_of_instructor_name`.** fleet.sh already answers a roster
  cluster's role from its name for the account and bootstrap profile; `role_for_cluster` returns that answer, or
  `attendee` when there is none. No second derivation.
- **No default, validated to the three values.** As with `event` and `hostname`, an apply that forgets the role
  fails rather than tagging a roster cluster as a seat. `up_one` passes it in `tfvars` (so the adopt step's
  imports get it too) and `down_one` passes it on destroy.
- **A running cluster gets the tag on its next apply.** `up` skips a healthy cluster, so one built before this is
  tagged only by `WIB_FORCE_UP=1 fleet.sh up <name>` or a rebuild; that apply rolls the node group's launch
  template, as #602's did.
- **The lab-platform half is filed there.** Harvest has to read the tag and skip anything not `role=attendee`.
  lab-platform's repo could not be read from this run, so the follow-up states the tag contract, not a patch.
- **Test:** `verify/test_hostname_tag.py` (offline) reads the tag, the variable and its validation from the root,
  checks roster.tsv's roles pass it, holds every apply and destroy of the cluster root to passing role, and
  dry-runs `up` of three attendees (role=attendee each) and `instructors up all` (community and admin, matching
  roster.tsv). No cluster was touched.

## 2026-10-28T23:30:00Z · 2.2 · No deck goes to Sessionize; the PDF exporter is removed

Michael, 2026-10-28: the KubeCon NA 2026 deck is not submitted to Sessionize. #449, #537 and M5 #614 are
closed as not planned. `scripts/kubecon-deck-pdf.py`, its two tests and `facilitation/kubecon-na-2026-deck/`
existed only for that upload and are removed; the deck is still presented from rounds-agenticburn. The
session id and the Sessionize feedback survey link stay, since feedback is kept.
## 2026-10-28 · #633 · Dispatched runs get an AGENTS.md section: no bring-up from a run, and a drift check for old drafts

Hecaton's insights found two runs that lost their time to the environment rather than the work.

- **Run 9654 (#610): a run cannot deploy.** The issue was the KubeCon rehearsal bring-up. A dispatched run has no
  cluster and no AWS profile, and its governance forbids deploying, while AGENTS.md's change cadence rules 3 and 4
  say to provision a cluster and validate. Nothing in this repo can give a run that access, and it should not: the
  go is Michael's spend (about $1 an hour for the two clusters, question 846). What is fixable is that a run read
  rules meant for a session with AWS access. The new "Dispatched runs (hecaton)" section scopes them: a run writes
  the change and its offline test, runs both gate commands, names the owed live check under "Not yet run on a
  cluster", and on a bring-up, teardown or live-run issue says there is no code, gives the exact command, and waits
  on the go already asked instead of asking it again.
- **Run 9672 (#474): the draft no longer applied.** The approved draft (`afea397` on `agent/474-9586`) was cut
  before #609 moved `gitops/apps/` into the `lab-bootstrap` chart, and was found stale only by conflicts. It was
  the third time #474 was redone for that reason (run 7819 against #475 and #493, then `docs/DESIGN-GLANCE.md`).
  `verify/draft-drift.sh <draft> [base]` now lists, before any work, every path the draft changes that the base has
  since edited, renamed (with the new path) or deleted, and every directory the draft adds files to that the base
  removed, each with the newest base commit that did it, and exits 1 on any. Run as `origin/agent/474-9586` against
  8429c6b, staging just after #609, it names the three `gitops/apps/* -> gitops/bootstrap/apps/*` renames and the 14
  other files #609 edited. AGENTS.md says to run it and make the design again on the current layout, and a "Where
  things live" bullet names the post-#609 app layout, since PRDs and older docs still say `gitops/apps/`.
- **Tests.** `verify/test_draft_drift.sh` (offline) builds a scratch repo with a draft on the old layout and checks
  a clean base, a moved directory with a rename, an edit and an added file in the gone directory, HEAD as the
  default base, a draft already merged, and exit 2 for no arguments, an unknown ref and no shared history.
  `verify/test_dispatched_runs.py` holds the AGENTS.md section and checks the layout bullet against the tree:
  `gitops/bootstrap/apps/` and each lab-platform.yaml profile's values file exist, and `gitops/apps/` does not.
- **Not done here.** The cause is to be named in a comment on #633; this run could not post it (`sources` asked for
  a sudo password), so the comment is escalated in the run's report.

## 2026-10-28 · #638 · Each roster profile's front door, with an ACM certificate on its NLB

lab-platform's bootstrap records each roster cluster's front door (peopleforrester/lab-platform#184,
`docs/talk-config.md` section 3, `profiles[].front_door`): it waits up to ten minutes for the named Service's
`status.loadBalancer.ingress[0].hostname` and records `https://<hostname>/`, and its gateway proxies attackme and
burritobot-private there, verifying the certificate against the system roots. The console's self-signed
certificate (#139), which apex's router never checked, is refused.

- **The front door is `agent/console`** on `burn` and `admin` in `lab-platform.yaml`: the one internet-facing
  LoadBalancer Service the console answers on (`gitops/ai-layer/resources.yaml`). attendee and full declare none.
- **ACM on the NLB, not cert-manager.** ACM's certificate does not depend on the NLB's hostname, which changes on
  every build; one per account and region, for `*.agenticburn.com` and `*.burritobot.co` (#651), renews itself
  while it is in use and its two validation CNAMEs stay in DNS; one left unused between events can expire, and
  the helper below then requests a new one. Let's Encrypt from the cluster would need HTTP-01 through
  the very gateway that refuses the self-signed certificate, or DNS-01 on Namecheap, whose API answers only
  allowlisted IPs; and each rebuild would spend one of its five duplicate-certificate issues a week.
- **The ARN is a root value, `frontDoor.certificateArn`,** as `imageRegistry` is (#622): per account, so the
  root that builds the cluster passes it. Set, the ai-layer Application carries a kustomize patch adding the
  load balancer controller's `ssl-cert`, `ssl-ports: "443"`, `backend-protocol: ssl` and the TLS 1.3/1.2
  negotiation policy to the console Service, so the NLB terminates with ACM and re-encrypts to nginx, which
  needs no change. Unset, nothing renders and 443 stays the TCP pass-through; `deploy-full-idp.sh` and fleet.sh
  clusters, the KubeCon ones included, are unchanged. A value that is not an ACM ARN fails the render by name.
- **The guard sits in YAML comments** (`# {{- if .Values.frontDoor.certificateArn }}` … `# {{- end }}`), so
  `ai-layer.yaml` still parses as written for the offline sweeps; `verify/bootstrap_chart.py`
  `without_front_door` is the file as rendered without the value.
- **`infra/front-door-cert.sh <aws-profile> <region>`** finds or requests that certificate, prints the
  validation CNAMEs as `set-demo-dns.py` arguments while it is pending, and the `frontDoor.certificateArn=`
  value once it is issued.
- **Assumed of the gateway:** it sends the roster hostname as SNI and verifies the certificate against it. No
  public certificate can name the NLB's own `*.elb.amazonaws.com` hostname, which is what lab-platform records,
  so a gateway that verifies against that name refuses every front door. lab-platform's repo could not be read
  from this run; the follow-up there states this contract and asks for `frontDoor.certificateArn` to be passed.
- **Tests:** `verify/test_bootstrap_chart.py` (the declarations, the value, the guard),
  `verify/test_bootstrap_chart_render.py` (renders burn with and without the ARN and a bad one, Helm v4.2.1) and
  `verify/test_front_door_cert.sh` (the helper against an aws shim). No cluster, certificate or DNS record was
  created; the definition of done's `labctl event up` and `labctl tls-check attackme.agenticburn.com` wait on both.

## 2026-10-28T23:17:57Z · question 868 · guard-proxy's root service stays burritobot; the LLM Observability app is burritobot and the burritobot- prefix has one exception

**Answer:** Keep burritobot.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**The question.** Issue 629 records two of Whitney's sandbox-org rules: the LLM Observability application (`ml_app`) is `burritobot`, and every service name starts with `burritobot-`. The root span of a BurritoBot interaction belongs to guard-proxy, whose service is `burritobot`. Datadog's OpenTelemetry LLM Observability page (docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation, read 2026-10-28) sets `ml_app` from the root span's `service.name`. `DD_LLMOBS_ML_APP` belongs to Datadog's own tracing library, which this repo does not use, and no attribute in the OpenTelemetry path overrides `ml_app`. Renaming the root service would therefore rename the application to `burritobot-guard-proxy`.

**What it changes.**
- guard-proxy's root service stays `burritobot`: `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` in `gitops/ai-layer/resources.yaml` are unchanged, and so is the `tags.datadoghq.com/service: burritobot` label added in 440f946. `verify/test_service_naming.py` already pins the root to exactly `burritobot`.
- `ml_app` is `burritobot`. The prefix rule has one exception, the root service. Every other BurritoBot service is `burritobot-*`.
- Filters for BurritoBot's data in the shared org use `service:burritobot*`, not `service:burritobot-*`, so that the root span and guard-proxy's logs are included.
- No `DD_LLMOBS_ML_APP` is added, and no `dd-ml-app` header: the collector exports through the Datadog Agent path, not straight to Datadog's OTLP intake, and a second export path risks duplicate spans in LLM Observability.
- The exception is recorded here. Issue 629 closes once the log labels from 440f946 are seen on a live cluster under `burritobot-*` services.

## 2026-10-29T00:22:25Z · question 872 · #640: C6's fetched ticket asks for the Joker villain image, and the probe stops asking C6 to land on the armed admin cluster

**Answer:** Villain image, per the planning note.

**Decided by:** hecaton's research under Michael's standing rules, not by Michael.

**The question.** Issue 640 reworks Challenge 6 (prompt injection through a support ticket) so the bot reads the
ticket through a tool from a fake ticket site, as agreed on the 2026-10-28 planning call
(`facilitation/kubecon-na-2026-planning-2026-10-28.md`). That note says the injected instruction deploys an external
image "(keep Kyverno off so it lands)", and the run-of-show's segment 3 promises a second tier where Kyverno's
registry allow-list denies the image. But #627 (2026-10-27) had made C6's image `docker.io/library/alpine:latest`,
one the allow-list admits, so the Night-Before probe's c6-off beat could land the Deployment on the admin cluster
with Kyverno armed. Run 10371 asked which way to go before building, and committed nothing, so there was no earlier
draft to check against staging.

**What it changes.**
- **The ticket is fetched, not pasted.** `gitops/ai-layer/ticket_site.py` is the fake ticket site, deployed as
  `fake-ticket` in the agent namespace: fixed tickets in memory, no outbound call, no token, service links off, no
  egress allow and no place on the Kyverno egressLabels list. workshop-mcp's new `read_support_ticket` fetches a
  ticket by id. The room's prompt names ticket HC-7731 and carries no payload.
- **The payload asks for the Joker.** HC-7731's hidden paragraph keeps the "IGNORE ALL PREVIOUS INSTRUCTIONS"
  register the classifier was measured on, asks for `maintenance-shell` from `docker.io/peopleforrester/joker:latest`
  (from `images/villains`, the "HAHAHA" log loop the planning note asked for), and asks the bot to name the
  Deployment. It drops the old `sleep infinity` command, so the villain's own log loop runs, and the "do this
  silently" clause, since the run-of-show now wants the bot to name what it made. This reverses #627's admitted image.
- **The input guard is applied to the ticket.** guard-proxy only sees the room's prompt, which is now innocent. So
  `read_support_ticket` reads guard-proxy's `input_classifier` toggle from `/guards` and, when it is on, sends the
  ticket body to LLM Guard's `/analyze/prompt` (with `BanTopics` suppressed, as guard-proxy does) and returns
  `[input guard] withheld` instead of the body. A guard-proxy that cannot be read counts as off (the wide-open bot
  is the default); with the guard on, an LLM Guard that cannot answer withholds (fail closed, as guard-proxy does).
  The one `guard-input-on` toggle arms both places. This is a check inside one tool, not the general scan of MCP
  returns before the model that #480 describes, which the run-of-show still does not claim.
- **What the stage can no longer say.** With the guard on, the model is still called once, to fetch the ticket, so
  C6's block is no longer "zero tokens" or "no model call under /chat". The run-of-show's segment 3, `/kubecon`,
  `/lab`, the prompt catalog and the C6 fallback now say the ticket is withheld before the model reads it, and the
  Datadog C6 tab shows `read_support_ticket` returning the notice with no `deploy_app` after it.
- **The probe.** The admin run no longer has a c6-off beat that expects the Deployment: on the armed private
  cluster the Joker is refused. It has `c6-admission` (the ticket's own Deployment, server-side dry run as
  workshop-mcp, denied by restrict-image-registries), then after `guard-input-on`, `c6-withheld`
  (`read_support_ticket` called in the tool pod, no model) and `c6-on` (the model asked, no Deployment). That is 11
  model calls, down from 12. The community run gains `c6-lands`, judged on the Deployment, so it now needs
  `--context` and starts with the same identity check the admin run has, stopping before it touches anything if
  the kube-context is not attackme. It makes 6 model calls. `judge_injection_blocked` is green on no Deployment;
  it no longer requires `guarded: true` and zero input tokens.
- **The fallback.** `challenges/02-sanitization/fallback.curl.sh input` calls `read_support_ticket` in the tool pod,
  first with the input stages off (it must return the hidden paragraph, or a tool that withholds everything would
  pass) and then on (it must come back withheld with nothing of the paragraph). It never calls `/chat`.
- **The leaderboard.** guard-proxy's own input-guard events no longer fire for C6, so the tool logs a
  `ticket_withheld` JSON line and the fleet leaderboard's C6 column counts it alongside guard-proxy's refusals.
- **The two-hour lab.** Students arm Kyverno in Challenge 2 before Challenge 6, so on their clusters the Joker is
  refused at admission. `/lab` now says so: the refusal is their Challenge 2 fix catching it, and the trace still
  shows the `deploy_app` the ticket caused.
- **Not built.** The planning note's other payoff, an endpoint the attendee can hit, needs a villain image that
  serves HTTP; the roster's images are busybox log loops and building one needs Docker Hub push rights. The
  ~3,500-token C6 figure `verify/model_pin_check.py` uses was metered on the pasted shape and is now an estimate.

**Tests.** `verify/test_fake_ticket.py` (new) runs the real site and the real tool against stand-ins for guard-proxy
and LLM Guard: the ticket whole with the guard off, withheld with it on and with a failing LLM Guard, a clean
ticket passing, the scan request guard-proxy's own, the leaderboard event, and the manifests and network paths.
`verify/test_kubecon_probe.py` holds the villain to "refused by the allow-list", every copy to HC-7731 and the Joker
with no alpine left, and the new admin and community runs. `verify/test_challenge_fallbacks.py` holds the fallback's
allow-then-withhold. `verify/test_injection_classifier.py` and `verify/injection_config_matrix.py` read the ticket
body from `ticket_site.py`, which is what the tool sends to the scanner.

**Not yet run on a cluster.** No cluster was up for this run. Owed, on the next KubeCon bring-up:
`python3 verify/kubecon_probe.py community attackme.agenticburn.com --context <community-context> --kubeconfig
/tmp/community.kubeconfig --profile accen-dev` (c6-lands: the Joker Deployment appears on the public cluster) and
`python3 verify/kubecon_probe.py admin burritobot-private.agenticburn.com --context <private-context> --kubeconfig
/tmp/private.kubeconfig --profile accen-dev` (c6-admission, c6-withheld, c6-on), both ending `KUBECON PROBE GREEN`;
`CONTEXT=<private-context> challenges/02-sanitization/fallback.curl.sh input`; and `bash verify/run-e2e-tools.sh`'s
`test_injection_classifier.py`, which measures the new payload against the deployed classifier. The landing rate
of the two-tool-call injection on Nova is unmeasured.

## 2026-10-29 · #647 · The room's PII is scrubbed on attackme before its spans leave; no attendee gets a Datadog account

Whitney's open question on the 2026-10-28 planning call (`facilitation/kubecon-na-2026-planning-2026-10-28.md`, Public
console): the prompt wall redacts what it shows, but the raw prompt still lands in the Datadog traces, and an
attendee given Datadog access could read another's. The issue allowed either answer: scrub before the trace lands,
or keep attendees out of Datadog. The choice is the scrub, because it is the only one that also covers the two
exposures that remain with attendees kept out: the `burritobot-public` tab Whitney projects (segment 5 walks "the
oddest audience prompt"), and the copy stored in her sandbox org until it is purged.

- **Where.** `transform/scrub_pii`, the last traces processor of the burn collector (`gitops/otel-collector/values-burn.yaml`),
  so only attackme scrubs. All of BurritoBot's spans reach Datadog through that collector (the Agent's APM is off), so
  it is the one place the text leaves. Last, so it runs after `transform/adk_tool_content` has copied the tool
  arguments and result to `gen_ai.tool.call.*`, and before every exporter.
- **What.** E-mail addresses, card numbers (13 to 19 digits, or grouped 4-4-4-4 and 4-6-5), US social security numbers
  and phone numbers (North American with separators or parentheses, ten bare digits, or any `+` number), replaced with
  `[EMAIL]`, `[CARD]`, `[SSN]` and `[PHONE]`. Read: the eight span attributes that carry the conversation (the gen_ai
  messages, the gen_ai tool call copies and the `gcp.vertex.agent.*` request, response and tool keys), copied into
  `cache`, scrubbed and merged back so each pattern is written once, plus every span-event attribute. Ids such as
  `session.id` are never read, so the session and correlation views keep working.
- **What it does not catch.** Names, street addresses and other free text. That is text the room is told goes on the
  prompt wall (segment 1), so the residue is no wider than what is already projected.
- **Burn only.** On an attendee cluster C1's ten fake customer records are meant to show in the student's own trace,
  and the presenters' cluster carries no attendee's text. On attackme the fake customers' e-mails now show as
  `[EMAIL]` in the trace (C1 is on deck only); the chat itself is not touched, because the scrub is on telemetry.
  C5's record (a street address, kept in the trace on purpose) and the planted 7-digit 555 numbers match nothing.
- **Attendee access.** No attendee gets a Datadog login or account in Whitney's sandbox org: it holds
  `burritobot-private` and other projects' data. The room's read-only view the call proposed ("Keep feedback"), scoped
  to `burritobot-public`, may now go ahead, since its condition, the PII question, is settled by the scrub. Building that
  view in her org is Whitney's, and is not done here.
- **Owed after the talk.** Michael's commitment on the call stands whatever the scrub catches: the `burritobot-public`
  data is purged from Whitney's org after the talk on 2026-11-12. That needs a sign-in to her org, which no run has.
  Datadog's LLM Observability deletion endpoint (`/api/v2/llm-obs/deletion/data/llmobs`, in preview, read 2026-10-29)
  deletes by trace id; APM spans have no delete-by-query that this check found, so their part is retention or Datadog
  support. Confirm on the day.
- **New dev dependency.** `verify/e2e-tools.lock` pins otelcol-contrib v0.160.0 (linux amd64, 2026-10-29), the
  collector the three `gitops/bootstrap/apps/otel-collector*.yaml` images run, so the scrub is proven on the binary the
  clusters use rather than only on Python's regex engine. Its SHA-256 matches the release asset's published digest. It
  is not a VERSIONS.lock line (VERSIONS.lock's collector lines are stale at app 0.153.0); the tier test holds it to the
  app files' image tag instead. About 110 MB, downloaded once and reused while the checksum holds.

**Tests.** `verify/test_collector_pii_scrub.py` (offline): the scrub is burn's last traces processor with and without
datadog-secret, no other profile has it, it reads every content key including both halves of each
`adk_tool_content` copy and no id, the four patterns are RE2-safe and identical in both contexts, and with Python's
`re` the attendee text in `verify/pii_scrub_cases.py` comes out scrubbed while C5's record and the demo text do not
change. `verify/test_collector_pii_scrub_e2e.py` (E2E tools tier) runs the burn traces processors in the real
otelcol-contrib 0.160.0 and reads the exporter's output for three spans shaped as guard-proxy's chat span and kagent's
model and tool calls. With the scrub taken out of the pipeline it fails 8 checks. `verify/test_collector_backends.py`
now allows burn's one addition, the scrub and the restated traces processors list.

**Not yet run on a cluster.** No cluster was up for this run. Owed on the next attackme bring-up: send a prompt with an
e-mail and a phone number to `https://attackme.agenticburn.com` and read its trace in the `burritobot-public` tab
(Agent Observability and APM) for `[EMAIL]` and `[PHONE]`, and check the collector is healthy after the sync
(`kubectl --context <community-context> -n monitoring logs ds/otel-collector-opentelemetry-collector-agent`). Also read one agentgateway `tools/call` span's attributes there: if agentgateway records the MCP arguments under a
key of its own, that key is not in the scrub's list yet.

## 2026-10-29 · #649 · The C7 handout is the Toronto keynote's six-gate checklist, copied verbatim and linked from the close

The 2026-10-28 planning call (`facilitation/kubecon-na-2026-planning-2026-10-28.md`, "C7 fix changed to a
tool-registry block") has Michael handing out "an MCP vetting checklist from his Toronto talk". The Toronto talk is the
MCP Dev Summit Toronto keynote of 2026-10-06, "Governing MCP for a Workforce the Size of a City" (talks-knowledge
`talks/register.md`, `mcp-for-a-city`). Its published, CC BY 4.0 collateral, `peopleforrester/mcp-for-a-city`, carries
the checklist as `04-approval-gates-checklist/approval-gates.md`: six approval gates before an MCP server is allowed.

- **Which checklist.** That file, not the `checklist.md` of the standby talk "How Do You Say Yes to an MCP Server?"
  (`talks/mcp-server-vetting-checklist`): the standby talk was never given in Toronto (register, "Standby offers"), and
  its repo is private and could not be read from this run (`sources` refused: sudo asked for a password).
- **Where.** `docs/mcp-server-vetting-checklist.md`, the source file copied byte for byte at `a3e585f` below a marker,
  with a header naming the source commit, the licence and author, and the source's sha256. The upstream file says it
  is generated from the keynote site's data and is edited there, so this copy is never edited here; it is refreshed.
- **Linked from the close.** The run-of-show's close (segment 6) and the `/kubecon` page's close carry the public link
  to the file on `main`; C7's "Hand out" line names it. The close slide itself is in `peopleforrester/rounds-agenticburn`
  (cut from the run-of-show by rounds-agenticburn#38), which no run here can write, so putting the link on that slide
  is a follow-up there.

**Tests.** `verify/test_mcp_vetting_handout.py` (offline): the copy below the marker hashes to the stamped sha256, the
header names the source commit, licence and date, the copy carries gates 1 to 6 in order, and the run-of-show's close,
C7's hand-out line and the `/kubecon` page's close name or link it. No network check against upstream: a refresh is a
deliberate act, and a test that went red whenever the keynote site changed would hold the gate red for an edit
nobody here made.

**Not yet on the slide.** The link reaches the room only once rounds-agenticburn's close slide carries it, and the
public URL resolves only once this change reaches `main`.
## 2026-10-29 · #639 · /kubecon and the probe follow the three-challenge run-of-show

95f86f2 rewrote the run-of-show for C5, C6, C7; the issue's thread left the `/kubecon` page and
`verify/kubecon_probe.py` on the old seven segments and the old C6, C5, C7 order. Both now follow it.

- **`/kubecon` (`gitops/ai-layer/web/kubecon.html`) is laid out by the six segments**, with the run-of-show's
  minutes: segment 1 the QR, the prompt wall and one working order; 2 C5, 3 C6, 4 C7, each block carrying the
  public-bot marker, the private-terminal toggle, the private-bot marker and its Datadog tab; 5 the trace
  walk-through; 6 the layers by voice, `guard-topic-on` and the close. C1 and C3 are an untimed on-deck section.
  C4 and the cost narration are gone, and the prompt wall moves to segment 1 with the run-of-show.
- **C6 is #640's shape, and C2 has no block of its own.** The ask names HC-7731; on the private bot the Joker is
  refused at admission before `guard-input-on` (the second tier), then the ticket comes back withheld. C2's
  admission rule is that second tier, so its fallback sits in the C6 block, as the run-of-show's "Folded into
  C6" says. `verify/test_instructor_brief.py` no longer asks for a C2 block.
- **The probe runs the stage's order:** start state; C5 off, `guard-output-on`, C5 on; C6's admission dry run,
  `guard-input-on`, the withheld ticket, C6 on; C7 off, the gateway rule, C7 on; C1, C2 and C3 (on deck or
  named by voice); the topic beats; `guards-off`. Each beat reports its run-of-show segment (2, 3, 4, 6,
  `deck`). On the community cluster the off-topic ask (segment 2) now comes before C6's landing (segment 3).
  The model calls stay 11 and 6. C6 now runs with the output guard on, which does not touch its judge, the
  `maintenance-shell` Deployment.
- **Fixes found on the way:** the page's C2 fallback named `challenges/01-cncf-wall/fallback.kubectl.sh`, the
  retired workshop Beat 1 (#499), and its C5 fallback used a `--sidecar` flag the script dropped; the
  run-of-show gave the private terminal the attendee login, `agentic`, where the roster gets `sprouts`
  (`verify/test_admin_actions.sh`); its fallback table still described C6's input check as a guard-proxy
  request with zero tokens, where `fallback.curl.sh input` now calls `read_support_ticket` in the tool pod;
  and its Night Before still expected the badge and topic beats to fail, which have passed since 2026-10-27.
- **What differs from the earlier draft** (`a893fbf`, cut from staging at `264c252`, before #640 and #647).
  That draft showed C6's second tier with C2's villain image, because the pasted ticket's
  `docker.io/library/alpine` is on the allow-list; #640's ticket asks for the Joker, which is not, so C6's own
  image is the second tier again and the draft's C2-in-segment-3 block is dropped. The draft's community probe
  had no C6 beat; #640 added one, kept here and placed in segment 3. The page also carries #647's note that
  the `burritobot-public` tab shows e-mails, cards, SSNs and phone numbers scrubbed.
- **Tests:** `verify/test_instructor_brief.py` holds the page's segments and minutes equal to the run-of-show's
  table, each challenge in its segment, played on the public bot and fixed on the private bot with its Datadog
  tab, C4 off the page and the C2 fallback inside C6; `verify/test_kubecon_probe.py` holds the new order and
  segments on both clusters; `verify/test_fleet_wall_check.sh` reads the wall from segment 1.
- **Not yet run on a cluster.** The reordered probe has not run live. The next bring-up's
  `python3 verify/kubecon_probe.py admin burritobot-private.agenticburn.com --context <private-context>
  --kubeconfig /tmp/private.kubeconfig --profile accen-dev` and the community run must end
  `KUBECON PROBE GREEN`, and the presenters read `/kubecon` against the run-of-show in run-through 1.
## 2026-10-29 · #650 · The answer to lab-platform's `web.yaml`, and the console's dot paths are a 404

lab-platform#278 moves the console Deployment and the five demo apps from nginx to its `web` image, a Go static
server and reverse proxy (`ghcr.io/peopleforrester/lab-platform/web:v1`, digest `sha256:74885296c746…a24a29`, built from
lab-platform 3dd635a). It reads one `web.yaml` in place of `console.conf`, and asked on this issue what `console.conf`
does that the file cannot say. Read against today's `console.conf`, the published console file (with `host: caller`
on `/chat`) leaves out these:

- **Unmatched paths fall through to root.** `skin.js`, `skins.js`, `active-skin.js`, `event.js`, `lab-events.js` and
  `display.js` have no location. The pages load them by relative name, so they work only because nginx serves an
  unmatched path from `root`. The file routes `/console.js` alone, so either the shape says unmatched paths are served
  by name or the file needs six more routes.
- **Dot paths.** A bug in the console today, fixed here (below). If `web` serves root by name, it needs the same 404:
  Go's `http.Dir` refuses only `..` elements, so `..data` passes.
- **Both domains (#651).** The file was written at 9ad5cd4, before ce80db5. Each `match` takes
  `\.(?:agenticburn\.com|burritobot\.co)$`. This is the file's content, not its shape.
- **Host routes.** The service-host server sends the caller's Host, a fixed `X-Forwarded-Proto: https`,
  `X-Forwarded-Host`, the websocket upgrade, and a 3600s timeout. A `hosts` entry carries only `match` and `proxy`.
- **No X-Forwarded-For by default.** Go's `ReverseProxy` with a `Director` adds one, and nginx does not.
  `console.conf` sends it on `/jupyter/` only, and `test_lab_events.py` holds that `/lab-events` forwards no client
  address.
- **The fallback page is for host routes only.** On a console route it would turn `/chat`'s 502 into a 200, and the
  storefront reads `res.ok`.
- **Host matching as nginx does it.** Hosts are matched before routes, and on the lowercased name with the port
  stripped, which is also what `/whoami` must echo.
- **A proxy route with no timeout.** It had nginx's 60s default.
- **No objection.** The rate bucket being per route rather than per port (it is still one per cluster), a 405 in place of
  nginx's 403 for a non-POST to `/lab-events`, and the demo apps' file. Their port, 80 today, and `NETWORK_BOUNDARY=sandbox`
  are this repo's side of the move.

The comment saying this went into the run's escalation list, because a run cannot write to an issue. Moving the
console and the demo apps onto `web` is a follow-up, held for the answers to the points above.

**The dot-path fix.** console-src is mounted as a ConfigMap volume over the console's root. kubelet lays such a
volume out as a `..data` symlink to a `..<timestamp>` directory, with each file a symlink into it. With no location for
those names, nginx served `/..data/brief.html` and `/..data/kubecon.html`, which is past the router's exact-path gate
on `/brief` and `/kubecon` and past #511's two 404s. `..data` is not a `..` segment, so URI normalisation keeps it, and
`%2e%2e` decodes to the same thing. Measured on 2026-10-29 with nginx 1.27-alpine (the console's image, run with no
network) on a root laid out the way kubelet lays it out. Before the fix, `/..data/brief.html`, `/..data/kubecon.html`,
`/%2e%2edata/brief.html` and `/..<timestamp>/brief.html` answered 200 on 8080, and `/..data/brief.html` also on 8443.
After `location ^~ /. { return 404; }` all of them are 404, and `/`, `/brief`, the six assets, `/console.js`,
`/healthz` and `/whoami` still answer 200.

A prefix location rather than a regex, so `test_gated_page_names.py`'s "no regex location" check still holds. Nothing
the console serves starts with a dot.

**Also fixed.** `verify/test_service_hosts_live.py` read each service host's upstream from `console.conf` with a pattern
that ended in `agenticburn\.com$`. #651 changed every host pattern to the two-domain group, so the live test found no
upstream and would fail its first check on any cluster. It now takes whatever domain part follows the label.

**Tests.** `verify/test_gated_page_names.py` (offline) now checks that the `^~ /.` 404 is there and that console-src
ships no dot-named file. `verify/test_service_hosts_live.py` (E2E, live) now asks for `/..data/brief.html` and
`/..data/kubecon.html` through the router and expects 404.

**Not yet run on a cluster.** No cluster was up for this run. Owed on the next attendee bring-up:
`CONTEXT=<attendee-context> python3 verify/test_service_hosts_live.py`. Its new section requests
`https://<public host>/..data/brief.html` through the real apex router. That proves the router passes the path to the
console, and that the rolled console answers 404.
## 2026-10-29 · #646 · The prompt wall's redaction is written in guard-proxy; this repo repins once it is pushed there

The 2026-10-28 planning call (`facilitation/kubecon-na-2026-planning-2026-10-28.md`, Public console) agreed
that a prompt with a code-of-conduct term or personal data is still sent to the bot but shown redacted on the
prompt wall. The wall, `prompts.agenticburn.com`, draws each cluster's `GET /prompts`. guard-proxy builds that
feed, and its `moderate()` is the only place a prompt is masked, so the change is guard-proxy's
(`gitops/ai-layer/guard-proxy`, the guard-proxy-agenticburn submodule). The wall repo was not readable from
this run (private, and `sources` refused), so whether it also filters is unknown. Either way, the feed has to
be clean at the source, because `/prompts` is publicly readable on every cluster.

- **What the guard-proxy change does.** Before the 280-character cut, `moderate()` masks email addresses,
  any run of seven or more digits with separators (phone, card, Social Security and account numbers, and dates
  written with dashes), and street addresses. It also matches `PROFANITY_LIST` terms as whole words, plural
  included. As substrings those terms showed "spicy" as "[redacted]y" on a burrito bot's wall. Only the feed
  copy is masked. The conformance tests in guard-proxy's `conformance/test_prompt_feed.py` pin that `/chat` and
  the A2A path forward the prompt unchanged. guard-proxy's own `decisions.md` holds the detail.
- **Why it is not pinned here.** By #521, a submodule pin must be a commit that a branch of its remote holds,
  and no run can push guard-proxy-agenticburn. The change goes there as a follow-up issue carrying the patch,
  one commit on `000f57e`, the current pin. guard-proxy's suite (ruff, 285 conformance tests) passes with it,
  and its mutation check catches all 27 mutants, three of them new for the feed.
  Once it is pushed, a run on #646 moves the pin and extends `verify/test_stream.py` to hold the pinned
  `moderate()` to the redaction (an email, a card number and an address masked, "spicy" left alone). It also
  updates the `STREAM_PROMPTS` comment in `gitops/ai-layer/resources.yaml`, which describes the mask.
- **Left open, as the planning note does.** Whitney's question still stands: raw personal data still reaches
  the Datadog traces. This change touches only the wall.

**Not yet run on a cluster:** after the repin, send a prompt carrying a fake email and phone number to
`attackme` (without the probe marker, so it is recorded). Check that the bot answers it and that `GET /prompts`
and the wall show it redacted. `verify/kubecon_probe.py` judges the feed but sends only probe-marked prompts,
which are never recorded, so the check is by hand.
## 2026-10-29 · #654 · run-e2e.sh runs the fetched otelcol-contrib and no longer asks for one on PATH

#647 put otelcol-contrib v0.160.0 in `verify/e2e-tools.lock` (SHA-256 7bb60c58...b47b0c, the same tarball as the
#150 entry), so `verify/fetch-e2e-tools.sh` already fetched it. What this issue still saw was run-e2e.sh's own check,
from #150, for `otelcol-contrib` on PATH or at `$OTELCOL_CONTRIB`. That check is gone. run-e2e.sh now points
`OTELCOL_CONTRIB` at `verify/.tools/bin/otelcol-contrib`, next to KYVERNO_CLI, CONFTEST and TERRAFORM, and a failed
fetch names otelcol-contrib with the other five tools. An `OTELCOL_CONTRIB` already set in the environment is
overridden, as #585 did for the other three. With CONTEXT and IAM_PIPELINE_* unset, on 2026-10-29 it exits 1 listing
two items, IAM_PIPELINE_PROFILE/IAM_PIPELINE_REGION and CONTEXT. No hecaton setup.sh change is needed.

- **The collector test joins the gate's tier.** `verify/test_lab_pipeline_collector.py` needs no cluster and no AWS:
  it validates every profile's rendered config and runs the lab pipeline on loopback. It is now `# E2E TIER: tools`,
  and `run-e2e-tools.sh` passes it `OTELCOL_CONTRIB` pointing at the fetched binary. Run here with that binary, all
  18 of its checks passed.
- **The tier's Datadog-key check.** That test gives the collector `"DD_API_KEY": "x"` so the Datadog exporter's
  config validates, and `test_e2e_tools_tier.py`'s "reads no Datadog key" check matched the name. The check now
  ignores a quoted Datadog key name set to a short literal, which is a stand-in rather than a read. Any other use of
  the name still fails it.
- **Held offline.** `verify/test_e2e_tools_tier.py` checks that both runners point OTELCOL_CONTRIB at the fetched
  binary, that run-e2e.sh has no PATH lookup for otelcol-contrib, and that the lock's version is the test's
  `OTELCOL_VERSION`. Its scratch run-e2e.sh now fetches six tools and does not list otelcol-contrib as missing.
  `verify/test_e2e_toolchain.py` checks that a bare run-e2e.sh never asks for otelcol-contrib on PATH. Run against
  the old run-e2e.sh and run-e2e-tools.sh, the two tests fail 6 checks.

**Not yet run on a cluster.** Nothing here touches a cluster. On the next cluster build,
`CONTEXT=<attendee-context> IAM_PIPELINE_PROFILE=<profile> IAM_PIPELINE_REGION=<region> bash verify/run-e2e.sh`
should get past its prerequisite check with no otelcol-contrib installed on the host.
## 2026-10-29 · #652 · LLM Guard runs lab-platform's `llm-guard:v1`, set by the ai-layer Application's `kustomize.images`

lab-platform now builds, reads back and signs the LLM Guard API image from pinned inputs (lab-platform#91, PR #282):
`ghcr.io/peopleforrester/lab-platform/llm-guard:v1`, digest `sha256:781a126bf7c7…3f4d7b`, built from
`images/llm-guard` at f2fcb8f, the commit this repo's submodule is pinned at. The `llm-guard` Deployment runs it in
place of `watch-it-burn:llm-guard-0.3.16-cpu.3`, so llm-guard-cpu-offline no longer has to build or sign it for the
talk.

- **How the image is named.** #622 says a lab-platform image takes the registry the root passes down
  (`imageRegistry`), and that only an `apps/` file can say so, because the chart renders those through `tpl`.
  `resources.yaml` is a plain kustomize manifest. So its container names the kustomize image `llm-guard`, and
  `gitops/bootstrap/apps/ai-layer.yaml` sets that name in `kustomize.images` to
  `{{ .Values.imageRegistry }}/llm-guard:v1@sha256:781a…`. Argo CD runs `kustomize edit set image` with each
  entry. That was measured with kustomize v5.8.1, the one Argo CD v3.4.4 bundles (checksum checked against the
  release's `checksums.txt`): the command writes `name`, `newName`, `newTag: v1` and `digest`, and the build gives
  `…/llm-guard:v1@sha256:781a…`, at ghcr.io by default and at an ECR cache path when a root passes one. The
  images block sits outside the front door's `if`, so every root renders it. A JSON patch on the container would
  also have worked. `kustomize.images` was chosen because it matches the container by image name, not by array
  index.
- **`NETWORK_BOUNDARY=sandbox`** is added to the container's env. Every lab-platform image that listens binds
  loopback without it, so the pod would answer nothing on 8000. The scanners ConfigMap at
  `/home/user/app/config`, `AUTH_TOKEN`, `APP_WORKERS`, the probes, uid 1000 and port 8000 stay as they were.
  `WIB_PI_MODEL_DIR` is not set here: the image sets it (`images/llm-guard/Dockerfile`) to
  `/home/user/models/prompt-injection`, which is the `model_path` in `llm-guard-scanners`.
- **Forwarded headers.** The issue asked whether anything in front of the Service relies on
  `--proxy-headers --forwarded-allow-ips='*'`, which lab-platform's entrypoint drops. Nothing does. The Service
  has two callers. guard-proxy (`proxy.py`, pin `000f57e`) sends only `Content-Type` and `Authorization`, and so
  does workshop-mcp (`workshop-mcp-server.py`, `read_support_ticket`). Neither terminates TLS or writes
  `X-Forwarded-*`, and no Ingress, gateway or console route reaches `llm-guard:8000`. The comment saying this went
  into the run's escalation list, because a run cannot write to an issue.
- **What else changes.** Kyverno's `verify-image-signatures` matches `ghcr.io/peopleforrester/watch-it-burn*`
  and Harbor, so llm-guard is no longer signature-checked at admission. lab-platform signs the image with its own
  identity, not the key in `policies/cosign/`. Adding lab-platform's attestor is a follow-up. The package was
  still private when this was written: an anonymous `GET` of its manifest got 403 on 2026-10-29. Until Michael
  turns on the package's public visibility, a cluster cannot pull it and the pod sits in ImagePullBackOff.
  `restrict-image-registries` allows both `ghcr.io/` and ECR, so the registry wall admits the image either way.
- **Tests.** `verify/test_llm_guard_image.py` (offline) checks several things: the one `kustomize.images` entry
  and its digest, that the placeholder names this container alone, that no file under `gitops/` still names the
  watch-it-burn build, and the container contract above. `verify/test_bootstrap_chart_render.py` (E2E, tools tier)
  builds `gitops/ai-layer` through a scratch overlay carrying the entries Argo CD writes. It checks the Deployment's
  image unset and at a cache path, that the registry policy allows it, and that no other container changes. Its
  front door checks now look for the absent patches, not an absent `kustomize` block. `verify/test_enforce_floor.py`
  judges a `kustomize.images` image as Argo CD deploys it, not as the placeholder.
  `verify/bootstrap_chart.py` gains the parser both use.

**Not yet run on a cluster.** No cluster was up for this run, and the package was still private. Owed on the next
attendee bring-up, after the package is public: `bash verify/input-guard.sh <host> <kube-context> <aws-profile>`.
It must pass the benign prompt and block the injection through the new image. Also, `kubectl --context <ctx> -n
agent get deploy llm-guard -o jsonpath='{.spec.template.spec.containers[0].image}'` must print
`ghcr.io/peopleforrester/lab-platform/llm-guard:v1@sha256:781a126bf7c7da6b8460d48b1fba1e0823673b85b186a165b36e0b23eb3f4d7b`.
## 2026-10-29 · #655 · The labctl import row is still unchecked against lab-platform; the live import is owed

#600 pipes each cluster's row to `labctl import --customer agenticburn --event <event> -`, built from the issue
text alone. This run could not check it either. `sources repo-whereis lab-platform` and
`gh api repos/peopleforrester/lab-platform/contents/docs/provisioning.md` both refused with "sudo: a password is
required", so docs/provisioning.md section 9 was not read, and a run brings up no cluster and holds no
`DATABASE_URL`. No change was made to the row.

- **Still assumed, all five.** (1) An attendee row goes in with an empty `role`, not `attendee`. (2) The
  header is quoted, as jq's `@csv` quotes it. (3) The row carries `terminal_user`, `terminal_password` and
  `role` beyond pool.csv's v2 header. (4) Success is labctl's exit code. (5) `fleet.sh ingest pool`
  re-importing a name the pool holds updates the row and leaves its claim alone, as /admin/import did.
- **Changed.** Only the `ingest-instructors` usage line, which still said it registers with the provisioning
  app. It now says lab-platform's handout pool through labctl import, as role=instructor.

**Not yet run on a cluster:** with labctl on PATH, `DATABASE_URL` pointing at a lab-platform database and `USER`
set, and a test event in `WIB_EVENT`, run one `fleet.sh ingest watch-it-burn-attendee-001` and one
`fleet.sh ingest-instructors` against built clusters. Confirm that the attendee row is claimable and that the
roster rows are not. Then run `fleet.sh ingest watch-it-burn-attendee-001` again after a claim, and confirm that
the claim holds. Reading section 9 first settles (1) to (4) without any spend.

## 2026-10-29 · #653 · Challenge 2 hands out lab-platform's promo/ villains, and the registry rule refuses that path

lab-platform#92 rebuilt the ten villains `images/villains/build.sh` pushed to `docker.io/peopleforrester/<name>:latest`
as `ghcr.io/peopleforrester/lab-platform/promo/<name>:v1`, the same catchphrase loop on lab-platform's shell base, the
lines read from `build.sh` at 45e62f0. The digests used are the rebuild in the issue's comment 6477523413 (the
entrypoint ends on SIGTERM), not the first table in the issue body. The crane build split three catchphrases on their
commas, Skeletor's among them, so those pods never said their lines; lab-platform's images say them whole. There was no
earlier draft of this issue to check against staging.

- **What the student gets.** `/lab` hands out the three covers, `promo-mascot`, `festival-promo` and
  `loyalty-rewards`, at `ghcr.io/peopleforrester/lab-platform/promo/<name>:v1`. They are named by the tag and not
  the digest, as the issue asks, because a digest in a copy-paste box reads as vetted. The stuck prompt, the prompt
  catalog, the C2 fallback (the Joker), the KubeCon probe's C2 dry run and the regenerated `LAB-TEXT.md` follow.
  `infra/datadog-fleet/leaderboard.yaml` matches `short_image:`, which is still the bare name, so it is unchanged.
- **The registry rule had to change, or the challenge had no fix.** `restrict-image-registries` allowed all of
  `ghcr.io/`, so the new villain passed it. After the student flipped the policy to Deny, the villain would have
  deployed anyway. The policy gains a `refusedPaths` variable, `['/peopleforrester/lab-platform/promo/']`. An image
  that contains the path is refused on any registry, which also covers an ECR pull-through cache path. The variable
  is read both in the admission check and in the UPDATE exemption. The message now ends "and not from the
  lab-platform/promo/ path", and the lab's quoted report line and its "the villain lives at" paragraph say that the
  site is on the list but the path is not. This is the issue's "the lesson is the path".
- **Why a refused path and not a narrower ghcr.io entry.** Listing only the ghcr.io paths we trust (watch-it-burn,
  lab-platform's mirror/) would read better as an allow-list. But lab-platform is moving the console and the five
  demo apps in `apps` onto `ghcr.io/peopleforrester/lab-platform/web:v1` (#650), and this run cannot see which other
  lab-platform images run in `apps` or `agent`. A narrowed list would refuse them as soon as a student arms Deny.
  The refused path changes nothing for any image except the villains.
- **The #622 literal sweep.** `verify/test_image_registry.py` fails on `ghcr.io/peopleforrester/lab-platform` named
  literally anywhere the root deploys from, because a deployed image has to take `imageRegistry` for a cache path to
  work. The promo/ path is exempt, and the test says why: /lab hands the reference to the student to paste, the
  cluster pulls it as typed, and it is the unvetted image the lesson is about, not one the root deploys.
- **C6 is unchanged.** The support ticket's hidden paragraph still asks for `docker.io/peopleforrester/joker:latest`
  (question 872). Moving it would change the payload that `verify/test_injection_classifier.py` measures, so it is
  a follow-up and not part of this issue.
- **The packages are private.** On 2026-10-29 an anonymous token request for each promo/ package was answered 403,
  as the issue says ("Private until Michael's package toggles"). A node pulls them with no credential, so until
  they are public, a cluster admits the villain and then leaves it in ImagePullBackOff. That means there are no
  logs for the reveal.

**Tests.** `verify/promo_villains.py` holds the ten names and digests. `verify/test_promo_villains.py` (offline,
new) holds the following:
- the README roster is the same ten;
- /lab's copy boxes are the three covers at `:v1`, with no digest;
- every C2 copy names the promo/ path and no Docker Hub villain except C6's Joker;
- the probe and fallback images;
- every promo reference is refused, on ghcr.io and through an ECR cache, while lab-platform's web and mirror/
  images are not;
- the lab's quoted line is the policy's message.

`verify/test_kyverno_cel_policies.py` (tools tier) gains Kyverno CLI cases: lab-platform's web and mirror/ images
pass; the promo/ path fails through an ECR cache and beside a passing container; the old Docker Hub villain still
fails. `verify/test_challenge_fallbacks.py`'s stub kubectl now refuses the refused path, as the policy does. Without
that, the stub would have admitted the new villain.
`verify/test_promo_villains_public.py` (tools tier, new) asks ghcr.io anonymously for each `:v1` and checks it
serves the handed-over digest. It shares `verify/ghcr_pull.py` with `test_mirror_copies_public.py`, and it fails
until the packages are public.

**Not yet run on a cluster.** Once the packages are public, on an attendee cluster:
`CONTEXT=<ctx> python3 verify/test_kyverno_cel_live.py` (the promo-mascot Deployment is admitted in Audit, the
lab's jq prints the new message line, and Deny refuses it), and
`CONTEXT=<admin-ctx> challenges/c2-villain-image/fallback.kubectl.sh`. Then, by hand, check that
`kubectl -n agent logs deploy/promo-mascot` shows the Joker's whole line.
## 2026-10-29 · #657 · test_repo_identity.py checks that llm-guard-upstream-mirror is named outside decisions.md

#625 named the mirror in AGENTS.md's "Where things live" and in the README, but no test checked either. Test
review run 10203 found the gap. `verify/test_repo_identity.py` now checks the "Upstream backup, not a submodule"
bullet: it must name llm-guard-upstream-mirror, `peopleforrester/llm-guard-upstream-mirror`, private, and the
archived `protectai/llm-guard`. It also checks the README's "`peopleforrester/llm-guard-upstream-mirror` (private)"
and its "It is not a submodule and nothing here builds from it." Last, neither the submodule bullet nor
`.gitmodules` may name the mirror. That way the mirror cannot become a submodule while both files still say it is
not one. Deleting the bullet fails five checks, and rewording the README's name fails one. Both were tried and
then reverted.

**Not yet run on a cluster:** nothing is owed. The test reads repo files only.
## 2026-10-29 · #656 · `ingest pool` and `reconcile-pool` wait for a labctl command that lists the pool

The issue asks for three paths to move off the provisioning app and onto lab-platform's handout pool, each to use
"labctl's equivalent (a list or export command and a remove command) once lab-platform has them".

- **Deregister has moved.** #624 did it: `deregister_one` runs `labctl deregister`, so teardown takes the row out
  of lab-platform's pool and it is no longer claimable. Nothing more is owed here for that path.
- **The other two cannot move yet.** `ingest pool` and `reconcile-pool` both need every cluster name in the
  event's pool, claimed or not, the way `pool_rows` reads them from /admin/roster. labctl has no command that
  prints that list. The newest labctl build on the dispatch host was compiled at 01:23 UTC on 2026-10-29, from a
  lab-platform run's worktree. Its usage text was read from the Go build cache, because the lab-platform repo is
  private and `sources` refused this run. That usage shows:
  - `labctl export --customer <c> --event <e>` writes claims only, one row per claim, under the header
    `email,cluster_name,region,console_url,datadog_org,claimed_at,email_sent`. It leaves out every unclaimed row,
    as /admin/export does. That gap is why `pool_rows` reads /admin/roster in the first place.
  - `labctl status <c> <e>` prints counts per state and no names.
  - `labctl deregister` and `labctl release` print only the names they were given.
- **Why not read lab-platform's database.** The issue names labctl as the interface, and fleet.sh already reaches
  that pool only through labctl (#600, #624). A `psql` read would tie fleet.sh to lab-platform's tables, which this
  run could not read and lab-platform can change without notice. It is not done.
- **What is asked of lab-platform.** It is filed as a follow-up there. The ask is a read-only command that prints
  every cluster in an event's pool, one row each, with its name and state (claimable, claimed, reserved,
  instructor), machine-readable. When it lands, `pool_rows` should call it in place of the /admin/roster scrape.
  `cmd_ingest pool`, `reconcile_pool` and `verify/test_fleet_pool_reconcile.sh`'s roster fixture follow from that,
  and `resolve_admin_token` stays only for `serve-actions` and `ops`.

**Not yet run on a cluster.** No code changed. Nothing is owed on a cluster for this entry.

## 2026-10-29 · #658 · run-e2e-tools.sh checks Playwright's browsers once, and a test runs `playwright install` only when one is missing

On 2026-10-29 hecaton run 10235 on #633 stalled because each Playwright test in the E2E command spent about 8
minutes failing on `__dirlock` (EACCES) in the shared, not-writable `PLAYWRIGHT_BROWSERS_PATH`
(`/var/lib/hecaton/ms-playwright`, group `hecaton-tools`). There was no earlier draft of this issue to check against
staging.

- **The lock is taken even when nothing is missing.** On this run's host every browser playwright 1.64.1 lists
  (chromium-1248, ffmpeg-1013 and chromium_headless_shell-1248) was already installed, and `playwright install
  chromium` still hung on the lock: it was cut off at 90 seconds with nothing done. The issue's "exit 1 up front"
  check alone would therefore have passed on this host, and the test would still have waited 8 minutes. So both
  places changed. `verify/playwright_browsers.py` reads `playwright install --dry-run chromium` and treats a browser as
  installed when its install location holds `INSTALLATION_COMPLETE`, the marker Playwright writes last and checks
  before it downloads. `ensure()` runs `playwright install` only when a browser is missing, and reports at once,
  with no install run, when the directory a missing browser goes in is not writable.
- **The prerequisite check.** `run-e2e-tools.sh` runs the module once, with the other prerequisites and before the
  fetch and before any test. Each problem is a line in the "E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip"
  list, naming the directory, the user, and each missing browser at its install location. It installs nothing:
  a missing browser in a writable directory passes the check, and the test installs it.
- **The tests.** `verify/test_mobile_titles_e2e.py` is the only Playwright test left in the tier. The issue also
  names `test_kubecon_deck_pdf_e2e.py`, but staging had already removed it (95f86f2). The test now gets the pin and
  its browsers from the module. With the shared directory already full, it ran in about 2 seconds on this host, and
  with `PLAYWRIGHT_BROWSERS_PATH` pointed at an empty directory it could not write, both the check and the test
  failed in under 1.5 seconds with the message above. `verify/test_playwright_browsers.py` (offline, new) stubs
  `uv` and holds the following:
  - no install when every browser is there, writable or not;
  - the named failure with no install;
  - one install through the pin when the directory is writable;
  - a failed dry run or an empty listing is a failure;
  - every Playwright tier test goes through the module.
  `verify/test_e2e_tools_tier.py`'s runner cases now carry the module and a `uv` that lists installed browsers.
  A new case there shows the runner exits 1 before any fetch or test when a browser is missing from a directory it
  cannot write. With the runner change reverted, that case fails.

**Not yet run on a cluster.** Nothing here touches a cluster; `bash verify/run-e2e-tools.sh` is the whole check.
## 2026-10-29 · #659 · A tools-tier test reads #633's comments and checks one names both causes

#633's first criterion was "The cause is named in a comment on this issue." Test review run 10345 found that no
test checked it. That is because the comment is on GitHub, not in the tree. The 2026-10-28 #633 entry above says
the run could not post the comment. The criterion holds anyway: hecaton's run-report comment on #633
(issuecomment-6483003262, 2026-10-28T23:05:41Z) names both causes. Run 9654 (#610) was a bring-up, and a run has
no cluster or AWS profile and may not deploy. Run 9672 (#474) found its draft stale because #609 had moved
gitops/apps/ into the lab-bootstrap chart.

`verify/test_dispatched_runs_cause_comment.py` (tools tier, new) asks api.github.com for the issue's comments,
anonymously because the repo is public. It checks that a comment by hecatongithub[bot] or peopleforrester names
both causes. The run numbers come from AGENTS.md's "Dispatched runs (hecaton)" section, so the comment and the fix
have to cite the same runs. The test fails, with the reason, if GitHub does not answer or refuses the read, for
example after the 60 anonymous requests an hour are used up. Pointed at #659 (no comments) it fails one check, and
pointed at #610 it fails three. Both were tried and then reverted.

**Not yet run on a cluster:** nothing is owed. The test needs the network only.
## 2026-10-29 · #661 · The platform charts' Datadog service tags are pod labels, not pod annotations

57ad24d (#629) renamed the five platform services to `burritobot-*`, but the `tags.datadoghq.com/{service,env,version}`
keys sat in each chart's `podAnnotations`. Datadog's Unified Service Tagging page
(docs.datadoghq.com/getting_started/tagging/unified_service_tagging, Kubernetes tab, read 2026-10-28) puts them on
the pod template as labels and does not mention annotations. The AI layer's pods already carry them as labels
(`verify/test_datadog_sandbox_names.py`).

- **Moved to each chart's pod-label key:** `podLabels` for cert-manager (v1.21.2), falco (9.2.1) and ztunnel
  (1.30.4), `admissionController.podLabels` for kyverno (3.9.1), `pilot.podLabels` for istiod (1.30.4) and
  `server.podLabels` for argo-cd (9.6.0, `infra/argocd-values.yaml`). Each was rendered with `helm template` on
  2026-10-29: the label lands on the pod template of the one controller, and on no selector, so the change is a
  rollout and not an immutable-selector conflict. The `ad.datadoghq.com/*.checks` Autodiscovery keys stay
  annotations, which is where the Agent reads them.
- **The issue's live check came first in its text,** to see whether the Agent already gives these pods' logs the
  `burritobot-` service. A dispatched run has no cluster and no Datadog access, so the move was made on the
  documentation alone. Labels are the documented place either way, so making the move costs nothing even if the
  annotations turn out to have worked.
- **Tests.** `verify/test_observability.py` reads `podLabels` (its `_pod_annotations` became `_pod_values`) and
  also fails if any `tags.datadoghq.com/*` key is left in a chart's `podAnnotations`. Reverting falco.yaml fails
  both checks; that was tried and then undone. `verify/test_kyverno_version_pins.py` reads the version from
  `admissionController.podLabels`. `verify/test_datadog_service_map.py`, the live counterpart, still asked
  Datadog for the pre-57ad24d service names (`argocd`, `kyverno`, ...) and defaulted `DD_ENV` to `production`.
  It now asks for the `burritobot-*` names and defaults to `burritobot-kubecon-na-26`, so it can pass against
  the sandbox org.

**Not yet run on a cluster.** On a fresh cluster with the Datadog Agent shipping to the sandbox org: run
`python3 verify/test_datadog_service_map.py` (`test_platform_component_ust` wants live metrics under
`service:burritobot-{argocd,kyverno,falco,cert-manager,istio}` with `env:burritobot-kubecon-na-26`), then check
in Log Explorer that `kube_cluster_name:burritobot-* kube_namespace:cert-manager` shows `service:burritobot-cert-manager`.
On the cluster itself, `kubectl --context "$CONTEXT" -n cert-manager get pods --show-labels` should show the three labels.
## 2026-10-29 · #665 · The room's read-only Datadog view is a public shared dashboard of burritobot-public, with counts and no traces

The 2026-10-28 planning call asked for a read-only Datadog view for the room, scoped to `burritobot-public`, once
the PII question was settled. #647 settled it, and said no attendee gets a Datadog login. The view therefore has
to work with no account, and the issue asked whether such a view can show LLM Observability traces or only
widgets.

- **Only widgets.** Datadog's shared dashboards page (docs.datadoghq.com/dashboards/sharing/shared_dashboards,
  read 2026-10-29) lists the widgets a shared dashboard renders. The List widget is not on it, and that is the only
  widget that lists spans: its source enum in Datadog's v1 API spec (datadog-api-client-python
  `.generator/schemas/v1/openapi.yaml`, read 2026-10-29) includes `llm_observability_stream`. Datadog accepts an
  unsupported widget without an error and then shows it empty. Opening a trace needs the Datadog app. So the room
  sees counts, and traces stay on Whitney's projected tab in segment 5.
- **What is on it** (`infra/datadog-room/room_view.yaml`): chats, tool calls, the model bill, the tools by name and
  chats per minute, over a fixed last hour, shared `open` until `2026-11-13T12:00:00Z`. That expiry falls the morning
  after the talk, ahead of the purge #647 committed to. Datadog's default expiry is a year.
- **The fence is the query, so the loader enforces it.** A shared dashboard runs with its author's permissions, and
  Whitney can read the whole sandbox org. `room_view.py` refuses any query whose filter lacks
  `kube_cluster_name:burritobot-public` or names another cluster, and any `ml_obs.*` metric. Datadog's metrics page
  (docs.datadoghq.com/llm_observability/monitoring/metrics, read 2026-10-29) says span tags are not on those
  metrics, and both clusters share `env`, `ml_app` and every service, so `ml_obs.*` cannot be limited to one
  cluster. It also refuses non-metric data sources, a group by anything but `span.name` (so no attendee text
  reaches the page), any widget type outside note, query value, timeseries and top list, template variables, and a
  share that lets the viewer select a time or a variable. The counts come from the collector's `span_metrics`
  connector, which keeps `k8s.cluster.name`, the same signal the fleet dashboard reads.
- **Who builds it.** The application key in `watch-it-burn/datadog` is read-only (#629), and sharing needs
  `dashboards_write` and `dashboards_public_share` (the API spec's `x-permission` on `/api/v1/dashboard/public`).
  `--apply` therefore takes a key Whitney issues from her own user, in `WIB_ROOM_VIEW_APP_KEY` for that one command.
  It refuses an org whose name does not start with `WIB_DD_POOL_PREFIX`, and records the share in
  `infra/datadog-room/share.json`, which `--check` and the run-of-show read. `--json` prints the body for building
  the view by hand in the UI. The loader reuses `fleet_monitors.py`'s Datadog client, key reader and dashboard
  lookup, and adds no dependency.
- **Run-of-show.** Segment 1 puts up the view's QR beside attackme's once it exists. A Night Before step builds it,
  checks it, and confirms on a phone that the private bot's traffic does not move it.

**Tests.** `verify/test_room_view.py` (offline) holds `room_view.yaml` to the fence. It feeds `validate()` 17
leaking variants (no cluster filter, the private cluster, a `burritobot-*` wildcard, an `ml_obs` metric, a group by
`gen_ai.input.messages`, an LLM Observability query, a list widget, a template variable, an invite share, a
selectable time, no or a passed expiry, and others) and expects each refused. It checks that the names the
queries count exist: burritobot-public for the community cluster, burn's resource and `span_metrics` wiring,
guard-proxy's `chat` span, `gen_ai.client.cost` and the `burritobot` service. It then drives the loader through a
fake org: a fresh apply, a second apply in place, a `--check` that passes using only the read-only key, and
`--check` failures on a 403 public URL, an invite or paused share, a missing expiry, a query edited in the UI, and
no share yet. `verify/test_room_view_live.py` (`# SUITE: e2e`) runs `--check` against the sandbox org. It fails
until the view is built.

**Not yet built, and not run on a cluster.** A run has no sign-in to Whitney's org and no write key. Owed:
Whitney runs `WIB_ROOM_VIEW_APP_KEY=<key> python3 infra/datadog-room/room_view.py --profile accen-dev --region
us-west-2 --apply`, commits `share.json`, and renders the QR. Then, with attackme up, `verify/test_room_view_live.py`
must pass. A prompt to `https://attackme.burritobot.co` must move the chat count, and one to the private bot must
not. Each widget must show data, which checks that `kube_cluster_name` arrives on `traces.span.metrics.calls` and
`gen_ai.client.cost` in the sandbox org.
## 2026-10-29 · #664 · C6's Joker serves a page at maintenance-shell-<cluster>, and deploy_app's reply names it

The 2026-10-28 planning note wanted C6 to end with the bot naming the Deployment and returning an endpoint the
attendee can open. #640 built the naming. This builds the endpoint, everything except the image push, which needs
the Docker Hub Team credentials a dispatched run does not have. There was no earlier draft of this issue.

- **The image stays `docker.io/peopleforrester/joker:latest`.** It is the only Docker Hub villain anything still
  names (#653), so it is rebuilt in place to serve a page. The ticket's paragraph is unchanged, and so is what
  `verify/test_injection_classifier.py` measures. `images/villains/build.sh` builds it from `joker-web/`:
  `start.sh` and `www/index.html` are appended as a layer under `/villain` on busybox pinned by digest
  (`JOKER_BASE`, busybox:latest on 2026-10-29), with entrypoint `/bin/sh /villain/start.sh` and `PORT=8080`. The
  files go in as a layer rather than through `--cmd`, which crane splits on commas (the Skeletor bug #653
  recorded). busybox `httpd` serves the page while the old catchphrase loop keeps laughing in the logs, and the
  shell traps SIGTERM so the pod ends on delete instead of waiting out the grace period. The image is amd64 only,
  as the nodes are. The other villains' build is unchanged.
- **The Service selects a label deploy_app sets, not one the model chose.** The model writes the Deployment, so
  its labels are unknown. `deploy_app` now puts `burritobot.co/workload=<metadata.name>` on every pod it creates
  (a Pod's own labels, or a Deployment's, Job's or CronJob's template), and keeps the model's labels and selector
  as written. The `maintenance-shell` Service (port 80 to 8080) ships in the ai-layer bundle and selects
  `burritobot.co/workload=maintenance-shell`. The key is not `app.kubernetes.io/name`, the one the
  NetworkPolicies trust and restrict-agent-spawned-workloads guards.
- **The route.** console.conf gets a third server, for `maintenance-shell-<cluster>` on both domains. It proxies
  GET only to the Service, resolved per request, and its own page says nothing is running there yet when no pod
  answers (an armed cluster, or before the attack). It is not a row in the service map, because the platform's
  not-installed page would be wrong for it, and `verify/test_service_hosts_live.py` would fail a host that has
  nothing behind it before the attack. fleet.sh's new `WIB_VILLAIN_HOSTS="maintenance-shell"` goes through
  `emit_service_hosts`, so the routes table carries `maintenance-shell-<label>.agenticburn.com` for every cluster,
  plus the burritobot.co twin on the roster.
- **How the bot learns the address.** `deploy_app`'s reply for a Deployment it publishes (`PUBLISHED_WORKLOADS`,
  only maintenance-shell) adds "Once its pod is ready it answers at https://maintenance-shell-<public host>/".
  The public host is read from cluster-identity's `public-host` into `WIB_PUBLIC_HOST`, optional as it is for
  guard-proxy. Without it the reply names no address. A refused Deployment gets no address either. The ticket
  already asks the bot to tell the customer what it made, so no payload change was needed.
- **Docs.** `/kubecon`'s public success marker, the run-of-show's C6 bullet, the prompt catalog and the villain
  README describe the endpoint and say it goes live only after the push. The two-hour lab's C6 text is
  unchanged.

**Tests.** `verify/test_c6_villain_endpoint.py` (offline, new) checks the five pieces against each other. First, the
ticket's image is build.sh's `$ORG/joker:latest`, built from the pinned base with the layer, entrypoint and PORT,
and start.sh is committed executable. Second, the Service selects deploy_app's label on the image's port. Third, it
runs deploy_app against a captured API and checks the label on each shape with the model's labels kept, and the
address only with a public host, only for maintenance-shell, and never on a refusal. Fourth, the console server
proxies to the Service. Fifth, fleet.sh's `emit_service_hosts` emits the row. Dropping the label call fails 6 of its
checks and dropping the fleet.sh list fails 3; both were tried and reverted. `verify/test_joker_web_busybox.py`
(tools tier, new) pulls `JOKER_BASE` from Docker Hub by digest, checks every blob's sha256, takes `bin/busybox` out
of the layer, and runs start.sh on it. It checks that a missing PORT is refused, GET / is the page byte for byte,
a path outside www/ is a 404, the laugh is logged, and SIGTERM ends both processes within 5 seconds.
`verify/test_console_no_toggle.py` now expects three servers and checks that the new one reaches only the
maintenance-shell Service. `verify/test_fleet_routes_roster.sh` reads both host lists.

**Not yet run on a cluster.** Owed, in order, by a session with the Docker Hub Team PAT and AWS:
1. Run `images/villains/build.sh` after `crane auth login` (it re-pushes the whole Docker Hub roster, the Joker
   last).
2. Run `fleet.sh routes roster` to publish the new rows, then let the ai-layer sync so workshop-mcp picks up
   the new server.py and `WIB_PUBLIC_HOST`.
3. On the community cluster, `python3 verify/kubecon_probe.py community attackme.agenticburn.com --context
   <community-context> --kubeconfig /tmp/community.kubeconfig --profile accen-dev` (c6-lands), then
   `curl -s https://maintenance-shell-attackme.burritobot.co/ | grep 'HA HA HA'` and
   `kubectl --context <community-context> -n agent get endpoints maintenance-shell`, which should list the
   villain pod.
4. `CONTEXT=<community-context> python3 verify/test_service_hosts_live.py`, to check the existing service hosts
   still route.
Whether Nova passes the address on in its reply has not been measured.
## 2026-10-29 · #666 · VERSIONS.lock records the collector the Applications run, and a test holds it there

VERSIONS.lock pinned the OpenTelemetry Collector at chart 0.158.2 / app 0.153.0 on both of its lines (the component
versions line and the IDP foundation line), but all three `gitops/bootstrap/apps/otel-collector*.yaml` files run chart
0.173.1 with lab-platform's mirrored otelcol-contrib image `0.160.0-5b66b0dc6921`. 0.160.0 is that chart's
`appVersion` (the 2026-10-24 otelcol-contrib entry above). Both lines now say chart 0.173.1 / app 0.160.0, and the
first one names the mirrored image.

- **The working docs had the same drift,** and the Kyverno and kagent pin tests hold the working docs, so they were
  fixed too. `docs/BUILD-SPEC.md` said chart 0.158.2 / app 0.153.0 in §6 and `v0.154.0` in the platform list, and
  `docs/MASTER-RECREATION-SPEC.md` said 0.158.2 in the sync-wave table, the data-flow diagram and the components
  list. In the last two, 0.158.2 was called "contrib", but it is the chart's version, not the collector's.
- **`verify/test_otel_collector_version_pins.py` (offline, new)** checks that the three Applications pin one chart
  and one `<version>-<digest>` image tag. It checks that both VERSIONS.lock lines name that chart and that version,
  and that `test_lab_pipeline_collector.py`'s CHART and OTELCOL_VERSION match. The two specs must name the chart and
  the app together, with no other version in a collector phrase. Against the old VERSIONS.lock and docs it fails six
  checks; that was tried and then reverted. e2e-tools.lock's otelcol-contrib was already held to the image tag by
  `test_e2e_tools_tier.py`, and its header comment no longer says the version is "not a VERSIONS.lock line".
- **Not changed:** the PRDs, `docs/UPGRADE-INVENTORY.md`, PROJECT_STATE.md and earlier decisions.md entries are dated
  records. The `contrib 0.158.2` remark in `gitops/otel-collector/values.yaml` is a statement about that release.

**Not yet run on a cluster:** nothing is owed. This changes records and an offline test, not what a cluster deploys.

## 2026-10-29 · #662 · Every platform pod names its logs' burritobot- service: pod labels, env where a chart takes only env, and the Agent's log config for the rest

#629 asks that every log from the two KubeCon clusters carry a `burritobot-*` service in Whitney's sandbox org. #662
listed what still logged under image short names after 440f946 labelled the agent namespace. There was no earlier
draft of this issue to check against staging.

- **The five platform charts' keys moved to labels in #661 (d9cefce), which this entry builds on.** PRD #28 had put
  `tags.datadoghq.com/{service,env,version}` in podAnnotations on cert-manager, Falco, Kyverno, istiod, ztunnel and
  argocd-server. The Datadog Agent reads those keys from pod labels only (`comp/core/tagger/collectors/workloadmeta_extract.go`,
  `extractTagsFromPodLabels`, read 2026-10-29), so the annotations set nothing. #661 moved them, and this change keeps
  its labels. The one difference is the version label, which is set to the deployed appVersion: cert-manager v1.21.2
  (#661 left v1.20.2), istio 1.30.4 (#661 left 1.30.1), and Argo CD v3.5.2 (#661 left v3.4.4), the appVersion of
  argo-cd 10.8.4, which deploy-full-idp.sh pins. #661's entry also names argo-cd 9.6.0, which is out of date for the
  same reason. VERSIONS.lock still lists argo-cd 9.6.0 and cert-manager v1.20.2; that drift is left for its own issue.
- **The rebase.** This branch was cut from 448affa, and #661 landed on staging meanwhile, changing the same five charts
  and the same test lines. The first rebase onto staging conflicted in seven files, which is why the earlier run
  stopped. Those files now take #661's version, with this change's additions reapplied on top: the sub-component labels,
  the istio cni and Argo CD labels, kyverno's hook and controller labels, and the version pins above. The
  `verify/test_datadog_service_map.py` change was already on staging, so nothing from this branch is needed there.
- **Why not a Kyverno mutate policy, the issue's second option.** The burn profile, which builds burritobot-public,
  runs no Kyverno. Kyverno's webhook here also excludes kube-system and its own namespace.
- **Three mechanisms, in the order the Agent applies them.**
  - **Pod labels** where the chart or operator takes them. That covers every component of cert-manager, Falco, Kyverno
    (with its hook Jobs), istio-cni, istiod and ztunnel, and kagent's controller and UI. It also covers the OTel operator,
    the collector (in `gitops/otel-collector/values.yaml`, which all three collector apps read) and Prometheus (through
    the operator's `podMetadata`). So do Grafana, kube-state-metrics, node-exporter, the Prometheus operator, Tempo, the
    three external-secrets pods, falcosidekick, the KubeArmor operator, the Datadog operator, and the node Agent and
    Cluster Agent (the DatadogAgent's `override.*.labels`). Every Argo CD pod is labelled too: env once in
    `global.podLabels`, which argo-cd merges under each component's. The AWS Load Balancer Controller is labelled through
    a new `infra/aws-load-balancer-controller-values.yaml` that deploy-full-idp.sh passes. So are the five demo apps and
    the AI layer's two PreSync gate Jobs, which are recreated each sync, so their immutable template can change.
  - **`DD_SERVICE` and `DD_ENV` env** where the chart takes only env. The Agent reads these off a container as the
    same standard tags; its containerd collector reads them from the container spec, so envFrom counts. That covers
    kagent-tools and kmcp (env), grafana-mcp (its config map, which is its envFrom), and falco-talon. falco-talon's
    chart 0.4.2 has no podLabels and writes podAnnotations into the pod's labels; that is a template bug this does not
    rely on. Its extraEnv keeps the chart's own `LOG_LEVEL=warning`. It also covers KubeArmor's DaemonSet, init, relay
    and controller containers: v1.7.4's operator applies each KubeArmorConfig component's `env` to its first container
    (`internal/controller/cluster.go`).
  - **A file-based Autodiscovery log config** in the DatadogAgent's `extraConfd` for containers that take neither. The
    config matches a container's short image name and sets the logs' service, plus an `env:` tag. The source stays the
    image name, as before. That covers kube-system's add-ons from `infra/terraform/aws/cluster/main.tf`: coredns,
    kube-proxy, aws-node's three images, the EBS CSI driver and its sidecars, and eks-pod-identity-agent. It also covers
    kagent's bundled postgres, KubeArmor's kube-rbac-proxy sidecar and snitch Jobs, and kube-prometheus-stack's
    kube-webhook-certgen Jobs. Their only label hook, `commonLabels`, would collide with the per-component labels.
- **A log config's service wins over a pod's labels.** So no labelled pod may run one of those images. kmcp's and
  kagent's images are both `controller`, and grafana-mcp's and Grafana's are both `grafana`, which is why those two pods
  are named through env, not the log config.
- **Tests.**
  - `verify/test_datadog_log_services_render.py` (E2E tools tier, new) renders, with the pinned Helm v4.2.1, every
    Application, every operator CR, Argo CD and the LB controller at deploy-full-idp.sh's pins. For every container, it
    requires a `burritobot-` service and the env from labels, env or a log config. It also requires that no log config
    names a labelled pod, and that main.tf's add-ons are the ones whose images it lists. On staging's manifests, it
    fails 77 checks.
  - `verify/test_datadog_sandbox_names.py` (offline) now fails if any annotations map under `gitops/` or the
    `infra/*values*.yaml` files holds a `tags.datadoghq.com/*` key, and it holds the Agent pods' labels.
  - `test_observability.py` and `test_kyverno_version_pins.py` read podLabels.
  - The live `test_datadog_service_map.py` asks for the `burritobot-` service names the pods now carry. It still asked
    for `argocd`, `kyverno` and the other unprefixed names.
- **Not covered.** Pods the agent or the room creates during a run, such as a villain Deployment, log under their image
  name.

**Not yet run on a cluster.** Owed on the next bring-up of burritobot-public and burritobot-private. Argo CD and the LB
controller pick their labels up only when deploy-full-idp.sh runs again. In Log Explorer,
`kube_cluster_name:burritobot-* -service:burritobot*` should return nothing. `verify/test_datadog_service_map.py`
(`test_platform_component_ust`) checks the five platform services. Three assumptions are only checked live:
- the snitch and kube-rbac-proxy short image names;
- that grafana-mcp's envFrom value reaches the Agent;
- that a logs-only `extraConfd` file is loaded.
## 2026-10-29 · #667 · The readiness file follows the three-challenge run-of-show, and row 5 goes to PARTIAL

`docs/KUBECON-ABSTRACT-READINESS.md` still described the seven-segment plan after 95f86f2 and #639 moved the
run-of-show to six segments and three challenges. It is re-read against the run-of-show at `248abb3`.

- **Segments renumbered** to the run-of-show's point table: C7 in 4 (rows 2 and 6, and the reload delay goes into
  segment 4), the trace walk-through in 5 (row 7), the layers by voice and `guard-topic-on` in 6 (rows 3, 5, 8).
  The spend note no longer says C4 is narrated: Whitney cut it on the 2026-10-28 planning call, and the budget cap
  is a Q&A item only. The scope-call table says the IDP is named by voice in segment 6.
- **Row 3 stays READY.** The checklist's bar is "the platform is up on the demo cluster, not a laptop-only
  stand-in". The tour never added to that, and watch-it-burn-private was up and passing the probe on 2026-10-28.
- **Row 5 goes to PARTIAL.** The bar, from talks-knowledge's checklist and the abstract's "Then", is "shown before
  the LLM-specific layer". The plan shows the output guard in segment 2 with RBAC only said, then Kyverno admission
  in segment 3 as the second tier behind C6's input guard, and names the rest in segment 6. Nothing is left to
  build, so the open item is the bar, not code. The bar column stays the checklist's words: rewording it, or
  putting a shown layer back first, is Michael's and Whitney's call on #456, which tracks each point as READY or
  cut with Whitney's agreement. The tally moves from 7, 2, 0 to 6, 3, 0.
- **Stale facts fixed while there**, each from what `staging` records: the Live column from the run-of-show's
  2026-10-27 and 2026-10-28 probe records; row 4's audience URL is `attackme.burritobot.co` (#651); row 7 has
  Datadog shipping since 2026-10-28 and pre-seeded traces (#648) as its open item; row 8's topic stage is built
  and passed live, so its open item is the BanTopics paraphrase (llm-guard-cpu-offline#2) and it stays PARTIAL;
  row 9 has the per-conversation rate limit (`6adce05`) and the lost #452 branch. The issue threads could not be
  read from this run (`sources` refused through sudo), so no issue state newer than `staging` is used.
- **Left alone:** the Grafana dashboard's "Segment 6" row title in
  `observability-idp/grafana/dashboards/agent-observability.yaml`, which the run-of-show also quotes; the row
  notes it. Renaming it is a follow-up.
- **Test:** `verify/test_kubecon_abstract_readiness.py` now holds each row's "run-of-show segment N" to the
  segments the run-of-show's point table gives that point, and every segment the file names to the run-of-show's
  `### Segment N` headings. On the file before this change it fails rows 2, 3 and 6 and the segment-7 mention.
- **Not yet run on a cluster.** Nothing here changes a cluster. The rows' Live cells for the three-challenge order
  wait on the next bring-up's `verify/kubecon_probe.py` runs on both clusters ending `KUBECON PROBE GREEN`, which
  #639's entry already names.
## 2026-10-29 · #672 · The browsers-directory failure names the group; the dispatch host's certkraken run users need that group

Hecaton run 10488 failed `test_mobile_titles_e2e.py` with EACCES on `/var/lib/hecaton/ms-playwright/__dirlock`.
There was no earlier draft of this issue to check against staging.

- **The cause is on the host, not in this repo.** The directory is `root:hecaton-tools`, mode 2775, with a default
  ACL for `hecaton-tools`. Every `-performantpro` and `-gmail` slot user and `hecaton-gate` are in `hecaton-tools`.
  None of the `-certkraken` users are, and this run's user, `hecaton-run-claude-certkraken`, is one of them. Hecaton's
  `deploy/netcup/setup.sh` toolchain section already adds `$(slot_users)` for every pool in governance
  `claude_pools` to `hecaton-tools`. So that section was not run again after the certkraken pool was added. Its check,
  `check_toolchain`, tests the write only for the home pool's slot 1 and the gate, so it did not catch the gap.
- **What stands today.** Every browser Playwright 1.64.1 lists (chromium-1248, chromium_headless_shell-1248,
  ffmpeg-1013) is installed there. #658 also means a test runs `playwright install` only when one is missing. So
  `bash verify/run-e2e-tools.sh` passes on this host as it is, for a certkraken run as well. A certkraken run still
  cannot add the browsers of a new Playwright pin until the host fix below is made.
- **The host fix, escalated, not made here:** `sudo bash deploy/netcup/setup.sh toolchain`, run from hecaton's repo
  root on netcup, or for just this gap, `usermod -aG hecaton-tools` for each `hecaton-*-claude-certkraken` user. A
  follow-up asks hecaton's `check_toolchain` to test the write for every slot user.
- **In this repo.** No fallback to a per-user browsers directory: that is a second install path that would hide the
  host gap. The not-writable report in `verify/playwright_browsers.py` now adds the directory's owner, group and
  mode, and whether this user is in that group, so the next such failure names its fix. On this host it reads
  `/var/lib/hecaton/ms-playwright is owner root, group hecaton-tools, mode 2775, and hecaton-run-claude-certkraken is
  not in group hecaton-tools`. `verify/test_playwright_browsers.py` holds the wording, including a user outside the
  group, with `os.getgid` and `os.getgroups` stubbed.

**Not yet run on a cluster:** nothing is owed. This changes an offline check's message and its offline test.

## 2026-10-29 · #674 · VERSIONS.lock records the Argo CD, cert-manager and Istio that are deployed, and a test holds them there

#389 moved argo-cd to chart 10.8.4, cert-manager to v1.21.2 and the four Istio charts to 1.30.4. VERSIONS.lock went
on saying argo-cd 9.6.0 / Argo CD v3.4.4 on both of its Argo CD lines and cert-manager v1.20.2, and it had no Istio
line at all. The working docs said the same old versions. #662 set the Datadog version labels to the deployed
versions and left the lock and docs for this issue.

- **VERSIONS.lock:** both Argo CD lines now say chart 10.8.4 / app v3.5.2. The first one changed its layout from
  "v3.4.4 (chart argo-cd 9.6.0)" to "chart X / app Y" so the test reads both lines the same way. v3.5.2 is the
  `appVersion` in argo-helm's `charts/argo-cd/Chart.yaml` at tag `argo-cd-10.8.4`, read on 2026-10-29. cert-manager
  says chart v1.21.2 / app v1.21.2. A new IDP foundation line, `istio chart 1.30.4 app 1.30.4`, covers base, cni,
  istiod and ztunnel. jetstack and istio-release publish each chart at the app's own version.
- **Docs and comments:** `docs/MASTER-RECREATION-SPEC.md`: the bootstrap paragraph, the sync-wave table's three Istio
  rows and its cert-manager row, and the UST line. In the UST line, falco 0.44.1 became 0.45.1, the version the
  falco label carries. `docs/BUILD-SPEC.md`: the platform list (ArgoCD `v3.4.3`) and §6, which now also names
  cert-manager and Istio. `docs/STACK-WALKTHROUGH.md`: the GitOps and Mesh rows. `docs/BUILD-PLAN.md`: the Istio
  pin. `deploy-full-idp.sh`: its step-2 log line, which said chart 9.6.0 / app v3.4.4 while installing 10.8.4.
  `gitops/bootstrap/apps/istio.yaml`: its header, which said "Pinned 1.30.1".
- **`verify/test_platform_version_pins.py` (offline, new)** works the way `test_kyverno_version_pins.py` does. It
  takes the deployed chart from deploy-full-idp.sh's `--version` and from the cert-manager Application and the four
  Istio Applications, which must all be one version. The VERSIONS.lock lines must pin that chart and name one app
  version. Every other copy is held to that app version: the Datadog version labels on argocd-server, the
  cert-manager controller, istiod and ztunnel; argocd-values.yaml's note on where the label comes from;
  deploy-full-idp.sh's log line; istio.yaml's header; and `test_mesh.py`'s ISTIO_VERSION. In BUILD-SPEC,
  MASTER-RECREATION-SPEC and STACK-WALKTHROUGH, each component's phrase must name the deployed version, and no other
  version may be named as current. A version after "from" is history. A number inside a longer dotted number, like
  the spec's IP `10.0.16.75`, is skipped. Against the old files it fails 30 checks; that was tried and then reverted.
- **Not changed:** the PRDs, `docs/UPGRADE-INVENTORY.md`, PROJECT_STATE.md, the research notes and earlier
  decisions.md entries are dated records. The "kustomize v5.8.1, the one Argo CD v3.4.4 bundles" remarks in
  `verify/bootstrap_chart.py` and `verify/test_bootstrap_chart_render.py` describe how one measurement was made. The
  other stale Falco versions (the spec's sync-wave row says chart 9.1.0 / app 0.44.1, and BUILD-SPEC says 0.44.1)
  are a follow-up: no test holds Falco's docs yet.

**Not yet run on a cluster:** nothing is owed. This changes records, comments, a log line and an offline test, not
what a cluster deploys.
## 2026-10-29 · #676 · C6's two tiers are shown admission first, then `guard-input-on`, on /kubecon and the run-of-show

The run-of-show's segment 3 showed `guard-input-on` first and Kyverno's denial of the Joker image second, where
`/kubecon` and #639's entry had the admission denial first. There was no earlier draft of this issue to check against
staging.

- **The order is admission first.** It is the only order the private bot can show live: Kyverno is armed from the
  first minute, so before any toggle the bot follows HC-7731, calls `deploy_app`, and `restrict-image-registries`
  refuses the Joker. After `guard-input-on` the ticket comes back withheld and there is no `deploy_app` call left
  to deny, so the denial cannot come second without switching to the C2 fallback. It is also the order
  `verify/kubecon_probe.py` runs and `/kubecon`'s markers already had.
- **The tier names stay the layers'.** The input classifier is the first tier, admission the second tier behind it
  ("even an instruction that slips past the classifier is stopped at the cluster"), so the second tier is shown
  first. Both files now say so in those words.
- **What changed.** The run-of-show's segment table row 3 reads "with Kyverno armed, then `guard-input-on`", and
  its segment 3 "Fix shown" bullet tells the denial first, then the toggle. `/kubecon`'s segment 3 premise names
  the order and the toggle, and its source comment follows it. The markers were already in this order.
- **Tests:** `verify/test_instructor_brief.py` holds the order in the run-of-show's row 3 and "Fix shown" bullet,
  the page's premise, and the C6 block (the deny marker, then the toggle, then the withheld ticket), and holds the
  tier names on both. On the files before this change it fails four of those checks.
- **Not yet run on a cluster:** nothing new is owed. The presenters read `/kubecon` against the run-of-show in
  run-through 1, as #639's entry already names.
## 2026-10-29 · #675 · The Grafana beats row is titled for segment 5 and runs C5, C6, C7

The row in `observability-idp/grafana/dashboards/agent-observability.yaml` was still "Segment 6: did each guardrail
do its job? (C6, C5, C7, newest first)", the seven-segment plan's name, after the run-of-show moved the trace
walk-through to segment 5 and the challenges to C5, C6, C7 (95f86f2, #639). #667 left it as a follow-up. There was
no earlier draft of this issue to check against staging.

- **Retitled** "Segment 5: did each guardrail do its job? (C5, C6, C7, newest first)". The dashboard's description
  and its `segment-6` tag follow, and the header comment names segment 5, the private cluster's Grafana URL and the
  beats in run order. "Newest first" stays: it is each table's order, not the beats'.
- **The panels follow the title.** C5 now sits left and C6 right on the first line of the row, so the panels read in
  the order the title and the run-of-show's walk give. Panel ids are unchanged, so nothing that links a panel moves.
- **The run-of-show's quote** in segment 5 says the "Segment 5" row. Row 7 of `docs/KUBECON-ABSTRACT-READINESS.md`
  drops its stale-title note.
- **The test is renamed** `verify/test_segment6_view.py` to `verify/test_trace_walkthrough_view.py`, and
  `verify/test_room_view.py`'s reference to it follows. It no longer hard-codes a segment: it finds the
  `### Segment N: The trace walk-through` heading, reads the challenge order from the `### Segment N: C<k>,`
  headings, and holds the row title to that N and that order, the panel layout and the run-of-show's walk to the
  same order, the run-of-show's quote to that N, and the readiness file to having no stale-title note. On the files
  before this change it fails those five checks.
- **Not yet run on a cluster.** The Grafana sidecar picks the ConfigMap up on the next sync of `grafana-dashboards`
  on burritobot-private. The run-of-show's Night Before step, each Grafana panel showing a row, is the live check.

## 2026-10-29 · #677 · Falco's working docs name the deployed chart 9.2.1 / app 0.45.1, and the platform pin test holds them

#626 took the falco chart to 9.2.1 (Falco 0.45.1, the kernel 6.18 fix) and moved `gitops/bootstrap/apps/falco.yaml`,
the IDP foundation line in VERSIONS.lock and the Datadog version label. The working docs stayed behind: the
recreation spec's sync-wave row (wave -3) said `falco chart 9.1.0 (app 0.44.1)`, and BUILD-SPEC (platform list and
§6) and the stack walkthrough's Runtime row said Falco 0.44.1. #674 fixed only the recreation spec's UST line and left
the rest here.

- **Docs:** the sync-wave row now says `falco chart 9.2.1 (app 0.45.1)`. BUILD-SPEC's platform list says Falco
  `0.45.1`, re-wrapped so "Falco" and its version share a line, because the test reads a component's phrase one line
  at a time and the old wrap put the version on the next line, where nothing would have caught it. BUILD-SPEC §6 says
  `Falco app 0.45.1 / chart 9.2.1 (moved from 9.1.0 in #626)`. STACK-WALKTHROUGH's Runtime row says
  `Falco 0.45.1 (chart 9.2.1)`.
- **VERSIONS.lock:** the component-versions line said only `falco 0.45.1`. It now says `chart 9.2.1 / app 0.45.1`, the
  layout of the argocd and kyverno lines above it, so the test reads both falco lines the same way.
- **`verify/test_platform_version_pins.py`** gains a Falco section instead of a new file, because it already has the
  lock reader and the doc-phrase checker this needs. The chart comes from falco.yaml's `targetRevision`. Both
  VERSIONS.lock falco lines must pin it and name one app version, and the Datadog label and `test_observability.py`'s
  expected `burritobot-falco` version must equal that app version. In the three working docs, a Falco phrase must name
  the app and the chart together, and no other version may be named as current. The name match is `falco` not followed
  by a word character or a hyphen, so falco-talon, falcosidekick and falco_rules are not read as Falco. Against the
  old docs and lock it fails 10 checks, and against the old docs alone it fails 6. Both were tried, then reverted.
- **Not changed:** `docs/UPGRADE-INVENTORY.md`, PROJECT_STATE.md, the PRDs and the research notes are dated records.
  `verify/mirror_copies.py`'s UNPULLED falco 0.44.1 copy is a deliberate record of a tag the chart no longer pulls.

**Not yet run on a cluster:** nothing is owed. This changes docs, a lock record and an offline test, not what a
cluster deploys.
## 2026-10-29 · #678 · The promo/ villains are private on ghcr.io, and ghcr_pull.py now says so

`verify/test_promo_villains_public.py` fails in the tools tier on all ten promo/ villains with "HTTP 401
Unauthorized". The issue asked whether the packages are private or ghcr.io's anonymous token flow had broken. On
2026-10-29, run 10534 checked, and the packages are private (or missing):
- `GET https://ghcr.io/token?scope=repository:peopleforrester/lab-platform/promo/promo-mascot:pull` with no
  credential answers 401 `authentication required`. The 401 comes from the token request itself, before any
  manifest is asked for.
- The same request for a mirror/ package (`.../mirror/grafana/tempo`) answers 200 with a token, and
  `test_mirror_copies_public.py` passes. So the anonymous flow works for public packages under the same owner.
- `github.com/peopleforrester/lab-platform` answers 404 anonymously. The repo is private, and a package published
  from a private repo starts private.

The fix is Michael's: in lab-platform's package settings, set each of the ten packages' visibility to Public. The ten
are promo-mascot, festival-promo, loyalty-rewards, joker, gargamel, skeletor, mumm-ra, shredder, cobra-commander and
megatron. GitHub's REST API has no endpoint that changes a package's visibility, so a run cannot do it with a token.
The check itself is right and is unchanged.

**What changed.** `verify/ghcr_pull.py` now names the step that failed. A 401 on the token request reads "token
refused, HTTP 401 Unauthorized: the package is private or does not exist". A failure after a token was issued reads
"manifest: HTTP <code> ...". Next time, the failure line answers the issue's question. `verify/test_ghcr_pull.py`
(offline, new) stubs `urlopen` and covers three cases: a served digest, a refused token (the manifest is never asked
for), and a manifest 404 that does not blame visibility. With `ghcr_pull.py` reverted to the old version, three of its
checks fail.

**Not yet run on a cluster.** Once the packages are public, `python3 verify/test_promo_villains_public.py` passes
with no cluster. The cluster checks owed by #653 are still owed:
`CONTEXT=<ctx> python3 verify/test_kyverno_cel_live.py` and
`CONTEXT=<admin-ctx> challenges/c2-villain-image/fallback.kubectl.sh`.
## 2026-10-29 · #679 · Admin syncs the Agent's tools from git; why the toolnames profiles cannot, proven offline

Both KubeCon clusters (watch-it-burn-community on the burn profile, watch-it-burn-private on admin) kept workshop-mcp's
eleven tools after git gave it twelve, read_support_ticket included (#640). ai-layer showed the Agent OutOfSync, and
every auto-sync said serverside-applied with no change. The issue's guess was right, and Argo CD v3.5.2's
`controller/sync.go` shows why. With RespectIgnoreDifferences=true, `normalizeTargetResources` copies each ignored
field from live into the target it applies. It does so as the merge patch from the normalized live object to the
live one. The Agent is a CRD, outside Argo CD's scheme, so that patch is an RFC 7386 JSON merge patch, which replaces
arrays whole. The ignore on evil-mcp's toolNames therefore carries the entire live tools array. `restoreNonIgnoredFields`
walks maps only, so it does not put the target's array back. Every sync applies the live tools, and no git change to
any tool entry can land while that ignore exists. Force=true does not help, because the write already holds the
live values.

**What changed.**
- The chart has a new value, `c7Control` (values.yaml: `toolnames`; values-admin.yaml: `gateway`), validated
  by name in templates/apps.yaml. `apps/ai-layer.yaml` renders the evil-mcp toolNames ignore only when it is
  not `gateway`. On admin, C7 is agentgateway's rule (#496). The web terminal's `_mcp` writes only the committed
  full list to the Agent there, so nothing needs the ignore, and Argo syncs the tools array from git. The
  modelConfig ignore stays on every profile, because it is a map field and the merge patch writes only that field.
- `verify/test_agent_tools_sync.py` (offline, new) ports `normalizeTargetResources` for a resource outside the
  scheme, with the real jq for the deletion, as Argo CD's gojq `del()` does. It runs the port on the committed Agent
  and each profile's rendered ignores. On attendee, burn and full it reproduces #679: the stale eleven stay, and the
  Agent stays OutOfSync. It also shows why those profiles keep the ignore: a student's guard-mcp-on survives a sync.
  On admin, the sync carries git's whole tools array and a per-cluster modelConfig survives. On every profile, a
  fresh cluster gets the committed Agent. The test fails if VERSIONS.lock's Argo CD moves off v3.5.2, so the port
  gets read again against the new sync.go. It also fails if any RespectIgnoreDifferences app gains another CRD
  ignore that reaches into an array.
- `test_fleet_converge_repairs.sh` gains the #679 state: a live eleven against git's twelve makes
  `repair_agent_tools` delete the Agent for Argo to recreate. The same list in another order, or no live Agent,
  deletes nothing. fleet.sh's comment on that repair now says it is what returns the toolnames profiles to git.
- `test_bootstrap_chart.py` and `test_bootstrap_chart_render.py` hold the value, its guard and each profile's
  rendered Agent ignore. A misspelt c7Control fails the render.
- `infra/setup-instructor-cluster.sh` told an admin cluster's operator to run toggle-mcp-authz-on.sh for C7. That
  script is a workshop cluster's control, and Argo now puts git's list back on admin. The hint now names
  guard-mcp-on.

**Not changed, and why.** The toolnames profiles keep the ignore. Without it, selfHeal would undo the student's
guard-mcp-on within seconds. converge's `repair_agent_tools` stays their repair: a fresh bring-up creates the Agent
from git, so its first sync has no live array to keep. A cluster that is already up when the tool list changes in
git needs `fleet.sh converge`. To lift the freeze on those profiles too, the Agent would have to leave ai-layer for an
Application without RespectIgnoreDifferences, or C7's workshop control would have to move off the tools array. Both
change the platform's layout, so they are left as a follow-up rather than made here. toggle-mcp-authz-on.sh still
writes the whole tools array from its copy. `test_tool_audit.py` holds that copy equal to git, so the copy cannot
reintroduce the eleven.

**Not yet run on a cluster.** On a fresh admin cluster, `bash verify/run-e2e.sh` with CONTEXT set is owed, and so is
a check of the Agent after a tools change in git. Patch the live workshop-mcp toolNames to drop one tool, then
confirm that Argo puts it back and that ai-layer reads Synced: `KUBECONFIG=<file> kubectl --context <ctx> -n agent
get agent workshop-agent -o jsonpath='{.spec.declarative.tools[0].mcpServer.toolNames}'`. On a burn or attendee
cluster, `./fleet.sh converge <name>` should log "agent tool list is stale" once and then read CONVERGED.

## 2026-10-29 · #519 · The probe holds the C7 badge to the gateway rule, and a check ties proxy.py's reads to guard-proxy-reader

**The pin was already in place.** #519 asked to move gitops/ai-layer/guard-proxy to a guard-proxy-agenticburn main
commit that has guard-proxy-agenticburn#5, the C7 badge reading the `# c7-rule` line of agent/agentgateway-c7-config.
Run 10553 found staging's pointer at 000f57e, which is that repo's main and staging head, and 8b525c6 (the #5 fix)
is its ancestor. Michael's hand re-pin to 96f3203 (ac68a12, question 752) brought the fix in, and 6adce05 moved it
to 000f57e. That re-pin also brought in what run 10553's predecessor listed as riding along: the topic guard (#455),
the C2 ValidatingPolicy badge (#487) and the measured Falco badge (#486), with the checks those needed. So this
change moves no pointer.

**What changed.**
- `verify/kubecon_probe.py`: a new `c7_badge(m)` gives the C7 badge the pinned proxy.py should show. It is True
  when the measured gateway rule is narrowed or toolNames drops the rogue tools, and False when the rule is open and
  toolNames is full. Anything else is None, which is how proxy.py shows an unreadable or unknown rule. An empty
  toolNames counts as full, as in proxy.py, because kagent then exposes every evil-mcp tool. `judge_badges` holds
  `tool_allowlist` to it rather than to toolNames alone. Before this, an admin cluster after guard-mcp-on (rule
  narrowed, toolNames full) failed the beat if the badge was lit, and passed it if the badge was dark.
- `verify/test_kubecon_probe.py`: one case where the badge and the narrowed rule agree (lit, passes), one where they
  do not (dark, fails), one where the badge is lit with the rule open (fails), and the empty-toolNames and
  unreadable-rule cases. The fake cluster's /controls follows the rule too. A stale comment saying the pinned proxy
  reads the retired ClusterPolicy now says that is what it did then.
- `verify/test_c7_badge_grants.py` (new): it reads every `_k8s_get` path in the pinned proxy.py (it fails on a
  path that is not a string literal). It finds the C7 readers from the names read_controls tests before setting
  `tool_allowlist`, and requires configmaps/agentgateway-c7-config and agents/workshop-agent among them. Then it
  checks that each read is granted `get` by resourceNames to guard-proxy-reader: by the Role for `agent`, or by the
  ClusterRole. Both bindings have to bind the role to ServiceAccount agent/guard-proxy-reader. With the ConfigMap's
  resourceName renamed, the check fails on the C7 read. `test_c7_gateway_reader.py` (#564) still holds the shape of
  that grant. This check holds that the pinned code's reads match the grants, so a re-pin that reads a new object
  fails offline.

**Not yet run on a cluster.** The live proof is the coordinator's #503 probe at bring-up: `python3
verify/kubecon_probe.py admin <host> --context <admin-context> --kubeconfig <file> --profile accen-dev` on a fresh
admin cluster, whose `badges` beat now compares C7 with the gateway rule. Its `c7-on` beat narrows the rule. The
badge read after that is still a hand check of /controls (`tool_allowlist` true).
## 2026-10-29 · #555 · The live audit-trail check sends its call from a pod the armed admin profile admits

**Context.** #555 asks for `verify/test_tool_audit_live.py` to be run on a cluster, to confirm that the Datadog
Logs search #474 moved it to finds workshop-mcp's audit lines, and for whatever does not hold to be fixed. This run
has no cluster and no AWS credentials, so the Datadog half is still unrun. Reading the check against the policies
the clusters run showed one link that would break before the check reached Datadog. The private KubeCon cluster is
the admin profile, and fleet.sh `arm_infra_guardrails` flips `restrict-image-registries` and
`require-resource-limits` to Deny on admin and full clusters. The check sent its tools/call from `kubectl run
--image=curlimages/curl:8.10.1`, with no limits set. `curlimages/` is on no allowed registry (only
`docker.io/library/` is), and the pod had no CPU or memory limits, so the API server would refuse it on that
cluster. The community cluster (burn profile) runs no Kyverno and would have admitted it.

**What changed.**
- `verify/probe_pod.py` (new) builds the one-shot pod as a manifest. It runs `sh -c <script>` with CPU and memory
  limits on the image the caller passes. `kubectl run` cannot be rendered offline: with or without `--overrides`
  it asks the API server for discovery first, and it has no flag for resource limits (none in the pinned
  v1.36.2). So the pod is created with `kubectl create -f -`, which makes the manifest the offline test judges
  the same one the live check creates.
- `test_tool_audit_live.py` reads the shim image off the cluster's workshop-mcp Deployment and runs the probe on
  it. That image is on ghcr.io, its digest is already signed and admitted for the Deployment, the node has it
  cached, and it has sh and curl (`images/workshop-mcp/Dockerfile`). The check creates the pod, waits for it to
  stop, reads its logs and deletes it. If the pod never runs, the check prints why, for example Kyverno's message.
  The Datadog search and every check after it are unchanged.
- `verify/test_probe_pod_admission.py` (new, E2E tools tier) uses the pinned Kyverno CLI v1.19.1 to run the probe
  pod and the old curlimages pod through every workshop policy and the floor. It does this for two operator
  identities: a system:masters admin, and an EKS access-entry principal that is in no system group. Every policy
  admits the probe pod, and both armed policies actually judge it and pass it. The old pod is refused by exactly
  those two policies.
- `verify/test_tool_audit.py` holds that the live check builds its pod with probe_pod, reads the shim image off
  the Deployment, and no longer uses `kubectl run` or curlimages.

**Checked here without a cluster.** With mcp 1.29.1 in a throwaway venv, the live check's library half passes all
14 checks. Its live half was then driven against a stand-in kubectl, which showed the pod being created, polled,
read and deleted in that order, with the shim image and the limits. The probe's shell script was also run under
dash and mawk, the shell and awk of the python:3.12-slim base, against a local workshop-mcp. It got a result, and
workshop-mcp wrote the pre and post lines with the probe's identity.

**Loki's leftover PVC.** Both KubeCon clusters were rebuilt on 2026-10-28 at staging `7210a3b`, which already
contains #474 (`dfb2f41`), so Loki should never have run on them. The PVC is still listed for a check. Loki chart
7.3.0's single-binary StatefulSet `loki` named its claim `storage-loki-0`.

**Not yet run on a cluster.** `CONTEXT=<ctx> python3 verify/test_tool_audit_live.py` with mcp 1.29.1 installed,
on watch-it-burn-private (admin, armed) and watch-it-burn-community (burn). That run is still owed for each Datadog
assumption #555 lists: the kube_deployment, pod_name and kube_container_name:shim tags, how the JSON line is
parsed, the app key's logs_read_data permission, and indexing inside 300 seconds.

## 2026-10-29 · question 864 · #621: Challenge 6 keeps its current input classifier; Llama Prompt Guard 2 86M was measured and not swapped in

**Answer:** Keep the current classifier.

**Decided by:** Michael.

**The question.** Issue 621 asked for Meta's Llama Prompt Guard 2 86M to be measured against Challenge 6's prompts,
as a replacement for `protectai/deberta-v3-base-prompt-injection-v2`, LLM Guard's input classifier, which was last
trained 2024-04-23 by a project now archived. Its rule was to swap only if Prompt Guard 2 missed fewer prompts at
the same speed with no false positives. Run 10190 measured it on one core behind llm-guard 0.3.16's
`PromptInjection`, from an ungated copy whose every file matched the git ids of Meta's commit `a8ded8e6`. Under the
deployed config (0.5, `full`) it missed 2 of 4 attacks to ours 3: it also refused the payload in the middle of
the padding. It was no slower, and on a 74-prompt false-positive sweep the two models disagreed on none. That meets
the rule. The swap would put Llama weights in our public mirrored model image, which means accepting the Llama 4
Community License and showing "Built with Llama" in ATTRIBUTION.md and the image's NOTICE. Question 864 asked
Michael whether to swap.

**What it changes.**
- Nothing in the serving path. The llm-guard image and its model pin in `gitops/ai-layer/resources.yaml`, the model
  pin in `verify/test_injection_classifier.py`, ATTRIBUTION.md, `agent/GATEWAY-NOTES.md` and C6's narration stay
  as they are. No Meta licence, NOTICE or "Built with Llama" line is added, and the pod's 3 GiB limit stands.
- The dated finding is `docs/spike-prompt-guard-2-2026-10-28.md`, with the answer at the top and what a swap would
  touch at the end. `docs/spike-llm-guard-2026-10-26.md`'s "What would change this finding" points at it and
  records the correction to its point 2: the middle payload starts at token 396 of 818, inside our model's
  512-token window, so ours misses it on detection, not on the window.
- **What differs from the draft.** Run 10190's draft (`830fb00` on `agent/621-10190`) also extended
  `verify/injection_config_matrix.py` to fetch, verify and run Prompt Guard 2. `verify/draft-drift.sh` flagged that
  file: #640 has since moved C6's ticket to HC-7731 on the fake ticket site (`gitops/ai-layer/ticket_site.py`), and
  the tool now reads it from there. With the swap declined, that extension is not brought onto staging. Running it
  would bind whoever runs it to the Llama 4 Community License, and it would add a 1.1 GB download nobody now needs.
  The tool stays as staging has it, measuring our classifier only, and the new dev dependency the draft recorded
  (Meta's weights from `project-free-llama/Llama-Prompt-Guard-2-86M`) is not taken on. The finding doc says what
  was measured: the pasted ticket from before #640, which asked for `docker.io/library/alpine:latest`.
- What keeping costs is the payload buried mid-ticket, which our classifier passes and Prompt Guard 2 refused. The
  padded-past-512 and reworded payloads pass both models, so C6's teaching points were never at stake.

**Not yet run on a cluster.** Nothing: no deployed object changes.

## 2026-10-29 · #450 · The ballroom's /chat: a per-network ceiling under the cluster window, a timeout ladder under Railway's 300 s, and refusals in words

**The question.** Issue 450 asks that a KubeCon ballroom of phones, most of it on one venue Wi-Fi NAT address, can
share attackme without one phone or one script spending the room's budget, without a slow turn showing a phone an
outer hop's bare error, and with every refusal readable. Michael's 2026-10-27 progress already settled the exposure
path (attackme behind the Railway apex), the per-conversation limit (guard-proxy `RATE_LIMIT_SESSION_RPM` 10,
`000f57e`), the cluster window (150) and the $25 cost cap (about 25 minutes of a saturated room). He left open the
per-address ceiling, which waited on apex-agenticburn#40, and the timeout ladder. apex-agenticburn#40 has been live
on production since `483ed28` (2026-10-28): the apex sends the caller's public address as the one X-Forwarded-For
entry, measured in attackme's nginx log.

**What it changes.**
- **Per-network ceiling, in the console's nginx.** `limit_req` on `/chat`: first 10 a minute per conversation
  (burst 9), keyed on a new `X-BurritoBot-Session` header the storefront sends, then 120 a minute per address
  (burst 60), keyed on `$http_x_forwarded_for`. nginx's own peer is the NLB, the same for every phone, so it is not
  the key. Why 120: BurritoBot's question 157 set 300 a minute per address, but here the cluster window is 150, so 300
  would never bind. 120 is under 150, so one address (a script rotating sessions, or the whole venue NAT) cannot take
  the full window, and cellular phones and the stage keep 30. The per-conversation zone is in nginx too, ahead of
  the address zone, because nginx counts a request in a zone only when every zone passes it: a phone over its own
  10 then does not spend its network's 120. guard-proxy's own per-conversation limit stays as it is.
- **The timeout ladder.** `/chat` sends nothing until the turn is done, so Railway's 300 s with no data
  (docs.railway.com specs-and-limits, read 2026-10-29) is the outer limit; the apex Caddy sets no response timeout,
  and the NLB's TCP idle timeout is the 350 s default. A guard-proxy turn makes up to six upstream calls in a row (the
  injection classifier, the topic classifier, three agent forwards counting the two self-heal retries, the output
  scrub), each under `PROXY_TIMEOUT`, so proxy.py's default of 150 s gave a worst turn of 900 s. Now `PROXY_TIMEOUT`
  is 45 (worst 270 s) and nginx's `/chat` timeout is 285 s (was 160 s). The cost is that one agent forward longer
  than 45 s now ends in "BurritoBot's kitchen isn't answering" rather than an answer. The followup asks
  guard-proxy-agenticburn for one deadline per turn, so that a single long turn could have most of the 270 s back.
- **Refusals in words (BurritoBot#110).** nginx's limit is a guarded 200 in guard-proxy's `/chat` shape ("Slow down,
  hungry traveler."). nginx's own 502, 503 and 504 return JSON with a `reply` that carries "kitchen isn't answering",
  which the probes already read as a failure. guard-proxy's own error replies pass through, since
  `proxy_intercept_errors` is off in the default server. The storefront now shows the body's `reply` on any error
  status, and falls back to the status code only when the body has no reply.
- `verify/test_audience_path.py` (offline) holds all of this. It counts the calls in proxy.py's `_handle_chat`, so
  an added retry fails it. Putting back PROXY_TIMEOUT 150, nginx 160 s or 295 s, a 300 a minute ceiling, a
  `$binary_remote_addr` key, the missing error_page or the old header name each fails it. The run-of-show has the
  hop table under "The audience path", and the readiness row 9 and PROJECT_STATE are updated.
- **Checked on a real nginx.** The console runs nginx 1.27. Debian's nginx 1.26.3 was run against this
  console.conf's default server, with a fake guard-proxy in front of it. Twelve requests at once from one
  conversation gave 10 answers and 2 "Slow down" refusals. Seventy fresh conversations from one address gave 61
  answers. After one conversation sent 40 (10 passed), 50 fresh conversations on the same address all passed, which
  shows that refused requests do not spend the address budget. guard-proxy received the caller's X-Forwarded-For
  unchanged. A request with neither header was not limited by nginx. A slow upstream gave a 504 JSON reply, a dead
  one gave a 502 JSON reply, and guard-proxy's own 502 came through untouched.

**Known limits.** The NLB is internet-facing, so a caller who goes around the apex can choose its own X-Forwarded-For
and get around the per-network ceiling. Such a caller is still held by guard-proxy's per-conversation limit, its
150 a minute window and the cost cap. A request from inside the cluster sends neither header and is held by
guard-proxy alone. Whether iPhone Safari waits 270 s for a fetch has not been checked; the phone check (#451) covers
it.

**Not yet run on a cluster.** `CONTEXT=<community ctx> python3 verify/test_audience_path_live.py` on
watch-it-burn-community once it has synced this commit. It checks that the deployed nginx config matches git and
that PROXY_TIMEOUT is 45. It then checks, through the apex, the per-conversation burst and the per-network burst,
using empty prompts that spend nothing, and times one probe turn against PROXY_TIMEOUT. A phone-scale load test on
attackme is also still owed.
## 2026-10-29 · #203 · The agent holds ONE scoped cloud credential and no Kubernetes token, IMDS has a rule you can read, and Challenge 8 proves both

**Context.** #203 asked to prove that the agent pod holds no cloud credential. Michael measured attendee-001 on
2026-09-04 and corrected the premise on the issue. The kagent container calls Bedrock, and it gets its credential
through the agent:agent-sa EKS Pod Identity association, so `aws sts get-caller-identity` as the agent SUCCEEDS.
What is built here is his reframe: one credential, Bedrock invoke on the four workshop models, everything else
denied, and IMDS blocked. The issue's SA and IMDS hardening is built as well. Run 6684 drafted this on
`origin/agent/203-6684`. `verify/draft-drift.sh` found 9 drift lines against staging, so the design was made again
on today's layout rather than cherry-picked.

**What changed.**
- **agent-sa:** `automountServiceAccountToken: false`, no identity annotation, and the stale "bootstrap adds an IRSA
  annotation" notes are gone (resources.yaml, the ai-layer Application, values-burn.yaml). Only BurritoBot's own
  pod runs as agent-sa. kagent 0.10.1's `manifest_builder.go` (read 2026-10-29) authenticates that pod to the
  controller with its own projected `kagent-token` (audience `kagent`) and never sets automount, so the pod loses
  nothing. Challenge 8 impersonates agent-sa with `kubectl --as` and needs no token. The chat variant's `cat` of the
  token runs in workshop-mcp, which keeps its token.
- **IMDS:** `policies/cluster-network-policies/agent-deny-imds.yaml` is an Admin-tier `ClusterNetworkPolicy`
  (networking.k8s.aws/v1alpha1) that denies 169.254.169.254/32 from the agent namespace. It has its own Application,
  `gitops/bootstrap/apps/cluster-network-policies.yaml`, listed on attendee, full and admin, not on burn. The node's
  IMDSv2-required, hop-limit-1 options were already in terraform; only their comment changes.
- **Challenge 8 beat** (a new caret, "And BurritoBot's cloud credential? Prove where it lives"). The student
  reads the SA, then execs into the kagent container: `AWS_*` env, no `~/.aws`, no token directory. Then they apply
  `~/challenges/cloud-credential-probe.yaml`, a read-only Job that runs as agent-sa on the web terminal's pinned
  image and prints ALLOWED, DENIED by IAM, UNREACHABLE or BLOCKED for who-am-I, Nova Pro, an off-list model, S3, EC2,
  IAM and IMDS. Last, they read the deny rule and `~/challenges/agent-bedrock-policy.json`, the policy as the
  terraform writes it.
- **C8 prose, two lines kept true.** The intro said agent-sa's token is on disk in BurritoBot's pod. It now says
  the tools' pod, under a second account with the same Role, has it. "The agent can read its own token" is now
  "BurritoBot's tools can read their own token".
- **Counts.** Attendee clusters render 32 Applications and instructor clusters 36. platform.html, DESIGN-GLANCE.md,
  the run-of-show and `test_fleet_contract.py` / `test_bootstrap_chart.py` say so.

**What differs from run 6684's draft.**
- #553 had already moved workshop-mcp onto its own account, so the draft's `automountServiceAccountToken: true`
  opt-in on workshop-mcp is gone. That pod no longer runs as agent-sa.
- The Application is a chart file, listed in three values files, not a `gitops/apps/` file.
- The staged policy has the second statement #513 added (this cluster's tagged application profiles) and both
  statements' tag conditions.
- The draft added AWS_PROFILE to run-e2e.sh and read the role and its policy back from AWS. That is dropped:
  `test_iam_policy_aws.py` already sends the same document to Access Analyzer and runs `infra/org/effect-tests.yaml`
  (Nova Pro allowed, off-menu models, IAM, EKS and S3 denied) through the simulator, under the existing IAM_PIPELINE_*.
- The admission of the probe is now tested.
- The draft's C8 goal-line rewording is not made.

**Tests.** `verify/test_agent_cloud_credential.py` (offline, 79 checks) covers:
- the SA;
- that agent-sa is the only workload identity in the bundle;
- the terraform's policy shape;
- the staged copy against the terraform, statement by statement;
- node IMDS;
- the deny and its profiles;
- that no agent NetworkPolicy opens TCP 80 to IMDS;
- that the probe is read-only;
- the lab commands.

`verify/test_cloud_credential_probe_admission.py` (E2E tools tier, Kyverno CLI v1.19.1) admits the student's Job,
and the pod the Job controller makes, through all eleven workshop policies. It also shows the same pod refused by
`restrict-agent-spawned-workloads` when workshop-mcp asks for it.

### REJECTED: a NetworkPolicy for the "explicit 169.254.169.254 deny"
**Why:** A NetworkPolicy cannot deny. Any policy that selects the agent pods makes them default-deny for egress,
and attendee clusters ship with no agent egress policy so that Challenge 1's exfil works first. Such a rule would
either be unreadable or would break C1.
**Do not suggest:** an `ipBlock` with `except: [169.254.169.254/32]`, which needs a wide allow around it.

### REJECTED: running the beat's AWS calls inside the agent pod
**Why:** The kagent image has no aws CLI, and the point is the credential, not the pod. Pod Identity binds the role
to the ServiceAccount, so a Job running as agent-sa holds exactly what BurritoBot holds. That is also the lesson:
anyone who can run a pod as agent-sa has the credential, so its scope is the control.
**Do not suggest:** exec'ing `aws` or `curl` into workshop-agent.

**Not yet run on a cluster.** `CONTEXT=<ctx> python3 verify/test_agent_cloud_credential_live.py` (part of
`bash verify/run-e2e.sh`) on a fresh attendee cluster. It covers:
- agent-sa as applied;
- the BurritoBot pod's env and mounts;
- the lab's exec command, run as written;
- the ClusterNetworkPolicy present as written (this proves the VPC CNI on the cluster serves the CRD);
- the probe's verdicts: Nova Pro ALLOWED, off-list DENIED by the same `-bedrock-` role, S3, EC2 and IAM never
  ALLOWED, and IMDS BLOCKED.

`bash verify/run-e2e.sh` also runs `verify/test_iam_policy_aws.py` for the Access Analyzer half.

## 2026-10-29 · #441 · run-e2e.sh asks for uv, the live audit-trail check runs on the image's mcp pin through uv, and the C6 endpoint test no longer crashes at exit

**Context.** #441 asks for `CONTEXT=<ctx> bash verify/run-e2e.sh` to be run green on a freshly provisioned attendee
cluster, and for whatever fails to be fixed. Hecaton runs have no cluster and no AWS profile, so the cluster,
Datadog and AWS halves are still unrun (the bring-up waits on Michael's go for the spend). This run fixes what
can be found and fixed without a cluster, and names the command still owed.

**The earlier draft.** Run 7339's draft (`origin/agent/441-7339`, commit `bf424c4`) was checked with
`verify/draft-drift.sh`, which named all four files it touches as changed on staging since. Its design was made
again on today's layout instead of cherry-picked:
- Its Playwright fix (`generateProjects({ channel: 'chromium' })`) is already on staging by another road
  (`bcf49cd`, the corepack-yarn change), so nothing is redone there.
- Its uv fix for `test_tool_audit_live.py` was not on staging and is made again below, the same way. Since the draft,
  #555 moved the file's live half to a probe pod, and `test_tool_audit.py` gained a check that the file never says
  `"run",` (meant for `kubectl run`). The `uv run` argv says it too, so that check now looks for `kubectl("run"`
  only. Run against the file as it was before #555, it still finds the old `kubectl run`.
- The draft added `uv` to run-e2e.sh's tool loop. Staging's loop has since changed (corepack, jq, the fetched tools),
  and `uv` is added to the new loop. Five `# SUITE: e2e` tests already run under `uv run` (audience page, mobile
  titles, topic and injection classifiers, weather feed) without run-e2e.sh asking for it, so a host without uv
  failed them one by one instead of in the prerequisite check.

**What changed.**
- `verify/test_tool_audit_live.py` re-runs itself under `uv run --no-project --python 3.12 --with mcp==<pin>`, with
  the pin read from `images/workshop-mcp/Dockerfile` and the Python of its `python:3.12-slim` base. Before this,
  it needed a global `pip install mcp==1.29.1` that nothing checked for, and failed on a fresh machine. A
  `WIB_TOOL_AUDIT_UV` marker stops the re-run from re-running itself.
- `verify/run-e2e.sh` lists `uv` among its prerequisites, as `run-e2e-tools.sh` already does.
- `verify/test_e2e_toolchain.py` holds that run-e2e.sh says `uv is not on PATH` when it is missing.
  `verify/test_tool_audit.py` holds the uv re-run, its pin and its Python against the Dockerfile.
- `verify/test_c6_villain_endpoint.py` crashed in the offline suite about one run in three, with exit 139 or 134,
  after every check had passed. The suite's first run here failed on it, and the base commit crashes the same way.
  The cause is deploy_app's `_report`, which posts to the support desk on a daemon thread. In the test it looks
  up `http://fake-ticket:8080`, and the interpreter finalized while that thread was still inside getaddrinfo.
  The test now stubs `_report` next to `_req`. `verify/test_deploy_app_limits.py` had the same unstubbed thread
  (no crash seen in 12 runs) and stubs it too. What the desk is told stays covered by `verify/test_room_jokers.py`,
  which runs a desk of its own on 127.0.0.1.

**Checked here without a cluster.**
- `test_tool_audit_live.py` with CONTEXT unset: uv fetched mcp 1.29.1 on Python 3.12, and the library half passed
  all 14 checks. It then failed loudly with `CONTEXT names the cluster to check (it is never guessed)`.
- `test_c6_villain_endpoint.py`: 25 runs in a row exited 0, against 5 crashes in 15 before the stub.
- `bash verify/run-tests.sh` passes (182 tests).
- `bash verify/run-e2e-tools.sh` passes the offline suite and 25 of its 26 tier tests. The one failure is
  `test_promo_villains_public.py`: the ten ghcr.io promo/ villain packages answer an anonymous pull with 401. That is
  a package-visibility setting on ghcr.io, already tracked as #678, and it fails the same way without this change.
- `bash verify/run-e2e.sh` with no CONTEXT and no IAM_PIPELINE_* fetched the six pinned tools and exited 1. It named
  only the AWS profile and region and the CONTEXT, so with node 24, corepack, jq and uv present, the prerequisite
  check now has only the cluster and AWS items left.

**Not yet run on a cluster.** A session with AWS access owes the whole of #441:
- bring up one attendee cluster with `bash infra/terraform/fleet/fleet.sh up watch-it-burn-attendee-<NNN>`;
- fetch an isolated kubeconfig with `AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig
  /tmp/watch-it-burn-attendee-<NNN>.kubeconfig --name watch-it-burn-attendee-<NNN> --region us-west-2`;
- run `KUBECONFIG=/tmp/watch-it-burn-attendee-<NNN>.kubeconfig CONTEXT=<that file's context>
  IAM_PIPELINE_PROFILE=accen-dev IAM_PIPELINE_REGION=us-west-2 bash verify/run-e2e.sh`;
- tear the cluster down with `bash infra/terraform/fleet/fleet.sh down watch-it-burn-attendee-<NNN>`.

The run-e2e.sh run covers run-all.sh, the `*_live.py` checks (the cluster half of `test_tool_audit_live.py`
among them), `test_datadog_service_map.py`, `test_iam_policy_aws.py` and `test_fleet_monitors_live.py`. These
have never run green.

## 2026-10-29 · #267 · The fleet is watched: every item of the issue is in the repo, and loading it into an event's org is #485

#267 asked for four things, in build order. All four are now in this repo or the apex router:

1. **Monitors in the instructor org, loaded by a script like the pool loader.** `infra/datadog-fleet/monitors.yaml`
   holds the six the issue names, one alert group per `kube_cluster_name`, and `fleet.sh monitors` loads them:
   dry run by default, Datadog validates every monitor before `--apply` writes, `--check` is read-only (205e75e,
   recorded in `docs/DECISION-LOG.md` under 2026-10-24).
2. **One instructor dashboard, a row per cluster.** `infra/datadog-fleet/dashboard.yaml`, loaded by the same apply.
3. **monitoring.agenticburn.com.** Served by the apex router since apex-agenticburn#34 as a 302 to
   `WIB_MONITORING_URL`. The apply prints the `railway variables` command that sets it to the new dashboard (#550).
   The DECISION-LOG entry of 2026-10-24 still calls this "not done"; it was written before #34 and #550.
4. **fleet-walkthrough.sh on every build.** `cmd_verify` runs it at the end of `up` and `scale`.

What the repo cannot do is the apply itself: each event brings a new instructor org, so `fleet.sh monitors --apply`
is an event-setup step (`docs/GO-LIVE-CHECKLIST.md` step d2), and the first apply is what proves the metric and tag
names against real data. That is #485, open. #267 closes on the repo work; it is not held for an event.

`--notify` stays empty by default (the earlier run's question): the monitors change state on the dashboard that
monitoring.agenticburn.com opens, which is the screen the instructor has up. A handle is added per event on the
apply line if one is wanted.

**Checked here without a cluster.** `fleet.sh monitors` (dry run) lists the six monitors and both dashboards and
writes nothing. `bash verify/run-tests.sh` passes (182 tests, `test_fleet_monitors.py` among them).
`bash verify/run-e2e-tools.sh` passes the offline suite and 25 of its 26 tier tests. The one failure is
`test_promo_villains_public.py` (ghcr.io answers an anonymous pull of the promo/ villains with 401), which is #678 and
fails the same way without this change.

**Not yet run on a cluster.** `verify/test_fleet_monitors_live.py` (E2E, run by `bash verify/run-e2e.sh`) has never
run green: it needs an instructor org with the monitors applied. A session with AWS access owes, at the next
event's setup, after the pool is loaded: `infra/terraform/fleet/fleet.sh monitors --apply --session
<start>Z/<end>Z`, then the printed `railway variables --service watch-it-burn-apex --set WIB_MONITORING_URL=...`,
then `infra/terraform/fleet/fleet.sh monitors --check` (#485).

**Why the previous attempt stalled.** Run 11327's predecessor stopped after 900 s without output, with nothing
committed and no log kept. The issue's repo work was already merged, so that run had nothing to change, and the
long silent step was most likely the offline suite run in the foreground (it takes several minutes over 180+
tests). This run ran the suites in the background, writing to a log it polled.
## 2026-10-29 · #381 · Grafana and Argo CD answer through the router; Backstage and Loki are held to "routed exactly when deployed"; the AttackMe page stops denying Argo CD

**Why:** test review run 6958 found no test on #381's Backstage URL. The earlier run (2c94038) fixed what the console
pages handed out but could not reproduce the 9-08 failure, because no cluster was up.

**Measured live on 2026-10-29**, with read-only GETs through the apex router, while the community (AttackMe, burn
profile) and shared admin (burritobot-private) clusters were routed in apex-agenticburn's `routes.map`:

- burritobot-private, on both domains: Grafana's `/api/health` answers (`"database": "ok"`, 13.2.2), `/` sends
  you to `/login` and the login page is 200. Argo CD's `/api/version` answers v3.5.2. Both URLs work.
- attackme: Argo CD's `/api/version` answers v3.5.2. Grafana shows the console's "not on this cluster" page. That
  is by design (#341): the burn profile installs no Grafana. But the page said AttackMe "deliberately runs no
  Prometheus, Grafana or Argo CD", and Argo CD runs on every profile, because lab-bootstrap is an Argo CD
  Application. The page now names only Prometheus and Grafana.
  `verify/test_console_service_vhosts.py` checked "no argocd app in the burn profile's list" as proof of the old
  wording. That proved nothing about the engine, and the check is replaced by one that the page does not say so.
- `loki-` and `backstage-` on both clusters: the router's own 404 ("no cluster here yet"). Neither has a row.
- provisioning-agenticburn hands out only `grafana_url` and `argocd_url` (`scripts/harvest_cluster_access.sh`).
  It builds `grafana-<label>` for any cluster whose console answers, the community cluster included (its
  `test_app.py` asserts `grafana-attackme`). On AttackMe that link lands on the explainer page. That is a
  follow-up for that repo, not a change here.

**What it changes:**

- `verify/test_service_links.py` gains a Backstage and Loki section. It reads which profiles deploy each one
  (`bootstrap_chart.app_names`). When a profile deploys it, fleet.sh must publish `<svc>-<cluster>`, the console's
  nginx must route it, and both console pages must link it. When nothing deploys it, nothing may route it, and no
  console page or script, terminal entrypoint or `challenges/LAB-TEXT.md` may hand out a `<svc>-` host. Today both
  are undeployed: Loki was dropped (#474) and Backstage waits in `gitops/apps-disabled` for #244. When #244 lands,
  the same check requires the route and the links. Mutation-checked: a backstage address in the lab text, a loki
  address in links.html, backstage added to `WIB_SERVICE_HOSTS` alone, and backstage added to the attendee
  profile alone each fail.
- `verify/test_service_hosts_live.py` probes `backstage-<host>` and `loki-<host>` while neither is published, and
  expects the router's 404 rather than the storefront or the not-installed page.

**Not yet run on a cluster:** `CONTEXT=<attendee context> python3 verify/test_service_hosts_live.py` (through
`bash verify/run-e2e.sh`) on a fresh attendee cluster. No attendee cluster was up. The figures above come from the
admin and community clusters, probed by hand with curl.
## 2026-10-29T22:00:00Z · 2.2 · KubeCon cut renumbered Challenge 1 to 4, stage moved to HC-666 (#687, #689)

From the 2026-10-29 planning call. /kubecon, the run-of-show and the probe now run Challenge 1 (C5, RBAC taught,
output guard optional), Challenge 2 (the Kubernetes catch-all: C2, C3, C1 played on the open public cluster, each
layer named), Challenge 3 (C6 on the room's ticket HC-666, asked under the fixed stage name Agatha the Banshee so
the probe can check joker-agatha-the-banshee), Challenge 4 (C7), and a close with the OWASP LLM Top 10 2025 and
Kubernetes Top 10 2025 (read 2026-10-29 at genai.owasp.org and kubernetes-top10.owasp.org; the mapping to
challenges is ours). The separate trace walk-through segment is gone: each fix shows its trace, the Grafana row is
retitled "Traces". The 2-hour lab keeps HC-7731 and maintenance-shell. The iPad sheet is /kubecon?sheet=1, built
in the page from the same prompt blocks, because a new path would need an apex router matcher change.
Not yet run on a cluster: the community probe's c1-open, c2-open, c3-open and HC-666 c6-lands beats, and the
admin probe's HC-666 c6-admission, c6-withheld and c6-on (verify/kubecon_probe.py on both clusters).

## 2026-10-29 · #463 · run_shell's non-zero exit reaches the caller as an MCP error

**Made the fix.** run_shell raised `RuntimeError("command FAILED with exit code N ...")` inside its try block,
and the generic `except Exception` beside it returned that as text, so FastMCP answered `exit 3` with
isError=false. A timeout raised from its own handler, out of the generic one's reach, so it alone came back as
isError=true. An `except RuntimeError: raise` now sits before the generic handler, as the comment in run_shell
(Whitney, 2026-09-06) always said it worked. A command that cannot be started at all (an OSError) is still
returned as text.

**Why the C1 trace is not at risk.** Both raises keep the `command FAILED` wording, and mcp 1.29.1 puts the
message in the error result's text, so `transform/mark_tool_failure` still matches it in the next model call's
input messages. What changes is the execute_tool span: `transform/adk_tool_content` marks it from
`isError: true`, which before this happened only for a hung curl. A curl that fails fast (exit 6 or 7) now marks
that span too. The 2026-09-07 measurement in `verify/test_collector_config.py` predates the fix, and says so.

**Tests.** `verify/test_run_shell_failure.py` (offline) loads the server with a stand-in for tool_audit and checks
that a non-zero exit and a timeout raise `command FAILED`, a success and an OSError return text, and every raise
in run_shell keeps the wording the collector matches. Without the fix 4 of its checks fail.
`verify/test_tool_audit_live.py`'s library half now calls run_shell `exit 3` on the pinned mcp 1.29.1 and asserts
isError, the `command FAILED with exit code 3` text, and an error audit line. Run here through uv: the library
half passes with the fix, and fails 2 checks without it.

**Against the earlier draft** (`agent/463-7506`, cut from the staging of 2026-10-24): redone on current staging,
not cherry-picked; `verify/draft-drift.sh` named all four files it touched as changed since. The design is the
same. The offline test's tool_audit stand-in now takes any constructor arguments, like `test_room_jokers.py`'s,
and the wording check reads the raises out of run_shell's body rather than counting them across the whole file.

**Not yet run on a cluster:** the C1 trace re-measurement the issue asks for. On a fresh attendee cluster, run
Challenge 1's exfil with the egress NetworkPolicies on, then confirm in Datadog that both the model call after the
blocked curl and the `execute_tool run_shell` span are `status:error`. The audit-trail half runs as
`CONTEXT=<attendee context> python3 verify/test_tool_audit_live.py` through `bash verify/run-e2e.sh`.
## 2026-10-29 · #480 · The tool-pin spike's live-check.sh pauses lab-bootstrap, not the retired app-of-apps roots

**Why this run changed anything.** The spike's code is on staging (400a13e, then #290's port move to :3004), and the
issue's only open part is the live kagent check, which needs a cluster this run does not have. Checked against
today's staging, `live-check.sh` would not have held on a cluster built since #609. Its `setup` paused Argo CD
auto-sync on every Application named `app-of-apps*` and on ai-layer. Since #609 the only root is `lab-bootstrap`
(`infra/deploy-full-idp.sh`, and lab-platform's root by the same name). So setup paused ai-layer alone, and
lab-bootstrap's selfHeal would have put ai-layer's auto-sync back within seconds, reverting the pinned bind,
the Service port and the RemoteMCPServer url mid-check.

- **The root is named.** `ROOT=application/lab-bootstrap`; setup exits 1 if it is not there, rather than going on
  with nothing holding ai-layer paused, and `restore` turns it back on after ai-layer.
- **The gateway's log is read from its container.** The pod has had two containers since #514. Every log read
  now says `-c agentgateway`, the container whose `agentgateway-config` `gateway_bind.py` extends, instead of
  leaning on kubectl's default-container pick.
- **Held offline.** `verify/test_tool_pin.py` gains a "live-check.sh against the current layout" section: the root
  name is read from deploy-full-idp.sh's heredoc, the ai-layer name from `gitops/bootstrap/apps/ai-layer.yaml`, the
  container from the agentgateway Deployment, the port from `gateway_bind.PINNED_PORT`, and the rug-pull edit's
  anchor from `gitops/ai-layer/server.py`. The old script fails the root and container checks.

**Not yet run on a cluster:** `live-check.sh` itself, phases setup, observe, rugpull, observe, deny, observe, restore,
on a fresh attendee cluster with the tool-pin image built, pushed and signed (`images/tool-pin/Dockerfile`). That is
the issue's remaining acceptance: kagent's discovery and the agent's list_tools seen through the processor, kagent's
handling of the deny's JSON-RPC error, and then the badge decision the spike README recommends.
## 2026-10-30 · #268 · The runner meets the shipped admin console: Railway host by default, health rows posted as `clusters`

**Why this run changed anything.** provisioning-agenticburn#33 closed on 2026-10-28 as completed, and its
`/admin/console`, the action queue and `/admin/health` are deployed. On the Railway host they answer 403 without the
token (read-only curl, 2026-10-29 23:20 UTC). Read against that app's code (`app.py`, `templates/admin_console.html`), the
runner side here had two faults that would have left Whitney's page empty and her buttons dead:

- **The runner was pointed at a retired host.** `fleet.sh` defaulted `WIB_PROVISIONING_URL` to
  `provisioning.agenticburn.com`, which was retired on 2026-10-29 (apex-agenticburn#44, provisioning #43) and now
  answers the apex router's unknown-host 404. `serve-actions` would never have seen the queue. The default is now
  `https://watch-it-burn-provisioning-production.up.railway.app`, the app's only public address, and
  `verify/fleet-hygiene.sh` uses the same default. This is the `fleet.sh` half of #691. The beacon-view references
  #691 also names (`infra/datadog-fleet/README.md`, the C1 fallback's `BEACON_VIEW`, older docs) stay with #691.
- **The health report's shape did not match the app.** `fleet-walkthrough.sh --json` has written `clusters` as a
  count and the rows as `results` since 559eed7. The app reads `clusters` as the list of rows, its page draws one
  row per item, and it answers 400 when `clusters` is not a list. `post_fleet_health` now posts the report with the
  rows moved into `clusters` and the count and `results` dropped. The walkthrough's own file is unchanged, because
  `test_walkthrough_no_state.sh` and anyone diffing two runs read it in its old shape. A report with no list of
  results is a failure and nothing is posted. `docs/admin-console.md` now says which shape goes where, and where the
  page is.

**Held offline.** `verify/test_admin_actions.sh` asserts that the posted body has the rows as `clusters` and keeps
`generated`, `failed` and `last_trace_error`, that a report with no results fails, that the default URL is the
Railway host, and that `docs/admin-console.md` names the same host. `verify/test_ops_view.py` follows the default.

**Checked against the app's own code, once, not as a suite test.** The app's `app.py` and templates, read through
`sources`, were run locally with Flask. A walkthrough report made by `test_walkthrough_report.sh`'s shims went
through the real `post_fleet_health` and real curl, and the response was 200. `/admin/console` then showed the row:
console 200, Argo 1/2, agent ready, last trace unknown with its reason. The same report posted raw, without the
reshape, got a 400. A page-form POST as wiggitywhitney@gmail.com queued `restart-agent`. `_prov_call` read it from
the pending list, `run_admin_action` claimed it and refused it, because there was no state for it on the runner and
no cluster was touched. The action log showed who, what, when, `failed`, exit 2 and the runner. This is not a
committed test, because it needs the sister repo's code, which the gate does not have.

**Not yet run on a cluster:** `infra/terraform/fleet/fleet.sh serve-actions --once` from a host holding the fleet
profiles, against a fleet that is up and the live app. Then press `restart-agent` on one attendee row of
`/admin/console?token=` and see the action go `done` with a new Ready workshop-agent pod. That needs the fleet up and
the admin token, so it waits for the next cluster build.

## 2026-10-30 · #320 · One interaction is one root again: the noise filter was cutting the parent chain

**What split the trace.** Nothing upstream. guard-proxy injects the W3C context inside `agent.forward`. agentgateway
v1.5.0 emits one SERVER span per request, parented on the incoming traceparent, and forwards its own span id as the
next one (`crates/agentgateway/src/telemetry/trc.rs`, read at the tag). kagent v0.10.1 runs `FastAPIInstrumentor` on
the agent's app (`kagent-core` `tracing/_utils.py`). a2a-sdk 0.3.26, kagent's lock, runs the executor in a task that
copies that context, and ADK's `invocation` starts under it. So kagent honours an incoming context on the A2A path,
and nothing belongs with kagent-dev/kagent#2734. The collector's `filter/drop_noise` cut the chain in three places,
each added for its own noise: every gateway span except `tools/call` (#265) took the gateway's A2A span, every
burritobot-agent HTTP verb (#286) took the agent's server span for the message, and every `a2a.*` span (#264) took
the request handlers between that span and `invocation`. With all three gone, `invocation` named a parent nothing
exported, and Datadog drew it as a second root. The "No content" rows #286 removed were most likely those server
spans as roots, orphaned by the #265 rule. That is inferred from the order the rules landed, not measured. If so,
each drop moved the orphan down one level, until it reached `invocation`.

**The change.** Each rule keeps its noise and lets the path through:
- the gateway rule exempts a span whose `http.host` ends `:3000`, the A2A bind guard-proxy's AGENT_URL dials;
- the agent HTTP rule exempts a POST of kind SERVER that has a parent. A server span with no parent, every client
  span, and the ASGI send and receive leaves are still dropped;
- the `a2a.*` rule exempts `a2a.server.request_handlers.*` spans that have a parent. The event-queue spans, and any
  a2a span with no parent, are still dropped.

The workshop-agent also sets `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false`, which a2a-sdk 0.3.26 reads at import. Its
spans are then never made, `invocation` hangs straight off the server span, and the tree loses four empty nodes. The
a2a exemption only matters on a pod that does not honour the variable. The interim the issue offered, a lab sentence
telling the student to press "Filter to Trace", is not added, because the context was reachable.

**Held without a cluster.** `verify/test_collector_one_root_e2e.py` (tools tier) runs one interaction through the
pinned otelcol-contrib v0.160.0 with each profile's traces processors: instructor, attendee and burn. It sends the
interaction's spans, shaped from the three components' source, once with the a2a-sdk spans and once without, plus the noise traces.
Each run comes out with one root, guard-proxy's `POST /chat`, every span on the path, and the noise still dropped.
Against the config before this change, it reproduces the issue exactly: roots `burritobot POST /chat` and
`burritobot-agent invocation`. Removing the `IsRootSpan()` guard from the agent rule fails it too.
`verify/test_collector_one_root.py` (offline) holds the `:3000` in the gateway rule to AGENT_URL's port and to the
gateway bind that proxies to workshop-agent, and pins the exemptions and the agent's variable.

**Not yet run on a cluster:** `CONTEXT=<admin-context> python3 verify/one_root_probe.py` on an admin or full
cluster. It sends one /chat through guard-proxy under a traceparent it picks, then reads that trace from Tempo. It
expects one root, guard-proxy's POST /chat, with the gateway span, the agent's server span and `invocation` beneath
it, and no a2a-sdk span. It is a by-hand probe, not a `test_*` file, because run-e2e.sh runs against an attendee
cluster, which has no Tempo. Then open the interaction in Agent Observability: the "Trace contains multiple root
spans" banner should be gone, and the list should show one row per interaction.

**For PRD #412's M5.** The plan defers #320 against a recorded Python baseline of roots per interaction. With this
change that baseline should be one, and `verify/one_root_probe.py` is the way to record it. The Go proxy keeps it
only if it sends the traceparent on its forward and dials agentgateway on :3000. The second is what the gateway
exemption keys on, and `verify/test_collector_one_root.py` follows AGENT_URL.

## 2026-10-29 · question 657 · A local-inference profile for one cluster, with a plain vLLM Deployment (#394)

**Answer (2026-10-24):** "Yes: a new bootstrap profile for one cluster, plain vLLM Deployment, then time a
cold build with it."

**Decided by hecaton's research under Michael's standing rules, not by Michael.** The answer run cited these
sources:

- Michael's bd45449 (2026-09-17), which built the `/local` route and the `gateway-local-qwen3` ModelConfig so
  that a local model would be "a configuration choice". Only the workload was left to build.
- The sister's measured vLLM pod spec.
- The Gitea rule, which keeps a 4-CPU server off the fleet.
- CLAUDE.md change-cadence rules 3 and 4.

**What it changes.**

- `gitops/manifests/vllm-qwen3/` holds a Deployment and Service in `agent`. They sit at the exact host, port and
  model name the `/local` route asks for, with the sister's pod spec:
  - requests 4 CPU / 10Gi, limits 6 CPU / 16Gi, and a 2 GiB KV cache;
  - SYS_NICE as the only capability, and a memory-backed /dev/shm;
  - tool calling on, for kagent;
  - the image pinned by digest (re-read from ghcr.io on 2026-10-29, unchanged since 2026-10-24).

  KServe is not used.
- `gitops/bootstrap/apps/vllm-qwen3.yaml` is its Application. `gitops/bootstrap/values-local-inference.yaml`,
  the only list that names it, is full's list plus vllm-qwen3.
- `infra/deploy-full-idp.sh local-inference` builds it.
- **Not presented in `lab-platform.yaml`**, so labctl is never handed it for a roster or attendee cluster.
  `verify/bootstrap_chart.py` names it in `DEPLOY_ONLY_PROFILES`, and the chart tests check it alongside
  lab-platform.yaml's four.
- The Agent stays on its committed modelConfig. Pointing it at `gateway-local-qwen3` is the switch.
- `verify/test_local_inference.py` (offline) checks two things. The server, the route and the ModelConfig agree.
  And no list but values-local-inference.yaml names vllm-qwen3, a list that is otherwise full's.
- **Known gap, recorded rather than half-fixed.** Any pod in the agent namespace can call the vLLM Service
  directly, around guard-proxy and agentgateway. A port-8000 ingress NetworkPolicy would close that. But once the
  namespace is enrolled in the ambient mesh, pod traffic arrives on ztunnel's port 15008, and that policy would
  cut the gateway off too.

**What differs from the 2026-10-24 draft.** The draft added a fifth app-of-apps root that took `gitops/apps` by
glob, and it kept the Application in `gitops/opt-in/` so that no glob could pick it up. Since #609 a profile is
an explicit list, so the Application lives in the chart's `apps/`, and containment is checked on the lists. The
draft also had `fleet.sh` arm the profile like full. That is dropped: no roster role maps to this profile, so
fleet.sh never builds it.

**Not yet run on a cluster.** Two things are owed. The first is a cold build:
`CONTEXT=<ctx> bash infra/deploy-full-idp.sh local-inference` on a fresh t3.2xlarge cluster, timed from start to
every Application Healthy. The second, once that build is up, is `CONTEXT=<ctx> python3
verify/local-inference-live.py`. It checks that the vLLM pod is Ready with no restarts and prints its time from
creation to Ready and its live footprint. It also checks that one chat call through `:3002/local` comes back from
qwen3-1.7b. It is not a `test_*.py`, because run-e2e.sh runs those against an attendee cluster, which has no vLLM.
The measured wall-clock and requests then go into the vllm entry as `measured: true`.

## 2026-10-29 · #394 · The two IDPs never shared a base, and platform-baseline.yaml now says what became of each component

#394 measured twenty components the sister platform (`peopleforrester/packt-agentic-devops`,
`solution/platform/`) runs and this one does not. It asked three things: why the two diverged, what the shared
baseline is, and which of the twenty to adopt, in what order.

**Why they diverged: they were never one platform.** The port commit that founded this IDP, `6880677`
(2026-06-18), says what it copied: "Copy the proven EKS IDP ... from kubeauto-ai-day; drop
ecom/sample/load-gen", with Promtail swapped for Alloy. The source was KubeAuto AI Day, not the Packt platform.
KubeAuto's `gitops/apps`, as archived (re-read 2026-10-29), holds 29 Applications and one of the twenty,
cert-manager-issuers, which came across in the port and was dropped in 3435e01. It has no OpenBao, no Argo
Rollouts, Workflows or Events, no KEDA, no Gitea and no model serving. So nothing was left behind from the sister,
because nothing was taken from it then. What the two share came across later, piece by piece: agentgateway, kagent,
LLM Guard, and the Terraform fleet layout. This corrects one premise of the 2026-09-17 Gitea entry, which compared
the port against the sister. The port brought no Gitea because its source had none. The rejection itself stands
on its own reasons.

**The baseline is `platform-baseline.yaml`, and two tests keep it true.** It has one entry per component: the
sister's 38 and this repo's own. Each entry has a status (adopted, equivalent, disabled, rejected, proposed, local,
opt-in) and the field that status needs. Entries are keyed on the sister's directory names, so the two lists can
be compared by a program. The file carries no versions. Those stay in VERSIONS.lock and the Application files, so
this is not a third list to drift.

- `verify/test_platform_baseline.py` (offline) fails on any of these:
  - a file in `gitops/bootstrap/apps` or `gitops/apps-disabled` that no entry claims;
  - a sister component claimed zero times or twice;
  - an entry missing what its status needs;
  - an opt-in app that a fleet profile lists.
- `verify/test_platform_baseline_sister.py` (E2E tools tier, so the gate runs it) fails when the sister's `main`
  gains or loses a component. It stays red until this file says what to do about that component.

**What happened to the twenty.**

- Four are here in another form: cert-manager-issuers, ai-dashboards, ai-policies and demo-agent. The file says
  by what.
- Gitea and gitea-config stay rejected. Re-read for this work, the 2026-09-17 revisit condition (a challenge
  that needs in-cluster git) has not happened.
- vLLM is built, on an opt-in profile (the question 657 entry above).
- Thirteen are proposals, ranked by the rule the Gitea entry applied: a component earns its place on a
  50-cluster fleet when a beat exercises it.
  - Tier 1, on the fleet with its beat: OpenBao (the question 656 entry below) and Argo Rollouts, which waits for
    a canary beat that aborts an agent-authored bad deploy.
  - Tier 3, off the fleet until a beat needs it: Argo Workflows, Argo Events, KEDA, KServe, llm-d, kgateway,
    Gateway API and agent-service. agent-service also needs Backstage (#244) and Gitea.

Loki, which the sister runs, is recorded as rejected under the #474 entry that dropped it here.

**What differs from the 2026-10-24 draft** (`origin/agent/394-7203`, which was never merged).
`verify/draft-drift.sh` found twelve drift lines against staging, chief among them #609's move of `gitops/apps/`
into the `gitops/bootstrap` chart. So the design was made again on the chart, not cherry-picked:

- The claimed files are `gitops/bootstrap/apps/*.yaml`.
- The local entries lose loki, alloy, customer-stream, rbac and resource-quotas, which staging removed.
- The local entries gain cluster-network-policies (#203) and otel-collector-burn (#476).
- OpenBao is a proposal again, not adopted.

## 2026-10-29 · question 656 · OpenBao's adoption is asked again, because lab-platform now reads the Datadog secret from Secrets Manager (#394)

**Answer (2026-10-24):** "OpenBao now (sister's dev-mode shape, ESO reads it, bootstrap Secrets move behind
it); Argo Rollouts only once its beat is written." It was decided by hecaton's research under Michael's standing
rules, citing Michael's 32a30e2 ("OpenBao remains the right post-event on-cluster secret store").

**The Argo Rollouts half stands.** Argo Rollouts stays `proposed`, tier 1, waiting for its beat.

**The OpenBao half is not built again, and is asked again on #394.** The answer rested on one premise: ESO was
installed with nothing to read. The 2026-10-24 draft built OpenBao on that premise, replacing the
`aws-secrets-manager` ClusterSecretStore with one named `openbao` and seeding `datadog-secret` into it from
deploy-full-idp.sh and fleet.sh. Since then, lab-platform has given ESO something to read in Secrets Manager:

- 2026-10-26, its question 840: an event's Datadog org pool writes each cluster's keys to Secrets Manager as
  `watch-it-burn/datadog/<cluster>`.
- 2026-10-28, its #205: lab-platform's build makes the `platform/external-secrets` Pod Identity role that reads
  the cluster's own secrets under `watch-it-burn/`.

Both are written for the store the draft removed. Building the draft again would break that path on every
lab-platform cluster. It would also put the bootstrap secret into deploy-full-idp.sh and fleet.sh, which
lab-platform's bootstrap does not run. Building OpenBao beside the AWS store, with nothing moved into it, would
add a pod on fifty clusters for a store nothing reads, which is the Gitea rule's "a component nothing uses".
Which way to go is a choice between two answered designs, so it goes back to Michael as one question. Until he
answers, platform-baseline.yaml has openbao as proposed, tier 1, and `security/eso` is unchanged.

## 2026-10-29 · question 912 · OpenBao is held until a beat needs it; the Secrets Manager store stays (#394)

**Question:** should OpenBao still go onto every cluster, now that lab-platform's build has External Secrets read
each cluster's Datadog key straight from AWS Secrets Manager?

**Answer:** Hold OpenBao until a beat needs it.

**Decided by hecaton's research under Michael's standing rules, not by Michael.** The answer run cited this
repo's 2026-09-17 Gitea rule: a component that no challenge exercises does not go onto a platform that builds in
15 to 25 minutes, 50 times over, and is revisited when a challenge needs it. OpenBao beside the AWS store,
holding nothing, is that case.

**What it changes.**

- The OpenBao half of question 656 (2026-10-24) is superseded. Its premise, that ESO had nothing to read,
  stopped holding on 2026-10-28, when lab-platform's build gave `platform/external-secrets` a Pod Identity role
  that reads each cluster's own `watch-it-burn/` secrets (lab-platform #205). That role exists for the
  per-cluster Datadog secret its question 840 names. The Argo Rollouts half of 656 stands: it waits for its
  canary beat.
- `security/eso/cluster-secret-store.yaml` stays the `aws-secrets-manager` store. No OpenBao Application,
  namespace, seed script or second ClusterSecretStore is added, and deploy-full-idp.sh and fleet.sh keep writing
  `datadog-secret` as they do.
- `platform-baseline.yaml` keeps openbao as `proposed`, tier 1, with this decision as its recommendation. It goes
  in with the first challenge that teaches an in-cluster secret store, such as the ESO exfiltration game that
  `docs/BUILD-PLAN.md` sketches with "possibly Vault".
- The 2026-10-24 draft's OpenBao work (`origin/agent/394-7203`, d2412aa) is not to be revived as written: it
  removes the store lab-platform's path reads.
- **Revisit when** a challenge or tour step needs an in-cluster secret store, or lab-platform stops reading
  Secrets Manager through ESO.

This closes the third question #394 asked, which of the twenty to adopt and in what order. No component joins
the 50-cluster fleet, so the fleet's build time is unchanged. vLLM goes onto one deploy-only cluster (question
657 above), and its cold-build cost is the one measurement still owed, under that entry's "Not yet run on a
cluster".

## 2026-10-30 · #394 · Run 11202's draft is replayed onto staging 7b132c5 unchanged in design

Run 11202's five commits (`origin/agent/394-11202`, cut from staging 540d040) were never promoted: its report was
refused because its followups were strings, not objects. `bash verify/draft-drift.sh origin/agent/394-11202
origin/staging` named two drift lines, `decisions.md` and `gitops/ai-layer/resources.yaml`. Neither is a layout
move. In `decisions.md` both sides only appended, so staging's entries come first and the draft's follow. In
`resources.yaml` the draft's hunk is the comment on the `/local` route, and staging's (1d39b44) is the CEO persona's
prompt further down. No path the draft touches was moved or deleted, and nothing under `gitops/bootstrap/`,
`infra/` or the deploy scripts changed between 540d040 and 7b132c5. So the design is the draft's as written, and
the commits are applied in their order. Nothing differs from the draft but the merged `decisions.md`.
`bash verify/run-tests.sh` passes on the result.

**Not yet run on a cluster:** the cold build of the local-inference profile and `verify/local-inference-live.py`,
as the question 657 entry above says.

## 2026-10-29 · #492 · The C6 probe's observable judge is still owed its live run, on a fresh attendee cluster

**No code changed.** #492 asks for one live run of `verify/agent_probe.py`'s c6-off and c6-on beats, which since
9d30bbc (#352) are judged on whether the maintenance-shell Deployment exists in the agent namespace, not on spent
input tokens. Hecaton runs have no cluster and no AWS profile, so runs 11521 and the one before it could not do it.
The offline suite, which holds the judge against a fake cluster, passes.

**Two things moved since the issue was filed**, and whoever runs it should read the result with them in mind:
- **The target must be a fresh attendee cluster, before Challenge 2.** Since #640 the ticket asks for
  `docker.io/peopleforrester/joker:latest`, which `restrict-image-registries` refuses wherever it is at Deny: on an
  admin cluster it is armed, on an attendee cluster the student arms it in Challenge 2. With it armed, c6-off reads
  the model's report of the denial as yellow "NARRATED, NOT OBEYED", which looks like #352 coming back and is not.
- **The 19/20 baseline was measured on the old shape.** b23cc9e counted the payload pasted into the prompt, with
  alpine. c6-off now has the bot fetch ticket HC-7731 through `read_support_ticket`, and c6-on is the ticket withheld
  by the tool's input check (#640). A rate near 19/20 still says the judge and the beat agree; a much lower one is a
  question about the fetched-ticket shape as much as about the judge. The 2026-10-27 kubecon_probe.py runs on
  michael-admin (#627) exercised the same Deployment check, with the image #640 later replaced.

**Not yet run on a cluster:** on a fresh attendee cluster, with Kyverno's registry policy not yet armed,
`python3 verify/agent_probe.py <host> --context <ctx> --profile accen-dev --only c6-off,c6-on --repeat 5`
(10 model calls, under the default `--max-calls 20`), compared against 19/20.
## 2026-10-30 · #485 · The fleet monitors load into Whitney's sandbox org: a write key for the apply, the org named the way the read-only key allows

#485 asks for the first `fleet.sh monitors --apply` against a live org and a check that every fleet-dashboard
column fills. Its premise was an instructor org per event, after a pool was loaded. #454 closed on 2026-10-29
with no pool: Datadog no longer issues per-student orgs, so both KubeCon clusters ship to Whitney's sandbox org
(`burritobot-public` and `burritobot-private`), and `watch-it-burn/datadog` holds a read-only application key
(#629). The loader was written for the old premise, and against the sandbox org it could not have worked:

- **`--check` would fail before it read a monitor.** `main()` named the org with `GET /api/v1/org`, which the
  read-only key answers 403 (found on #665, which is why `room_view.py` uses `/api/v2/current_user`). So
  `fleet.sh monitors --check` and `verify/test_fleet_monitors_live.py` would have failed on the org lookup
  whether or not the monitors were loaded. `org_name()` moves from `room_view.py` into `fleet_monitors.py`, and
  both loaders use it.
- **`--apply` would write with the read-only key.** It now takes the application key from
  `WIB_FLEET_MONITORS_APP_KEY` in the command's environment, the way `room_view.py --apply` takes
  `WIB_ROOM_VIEW_APP_KEY`: an unscoped key Whitney issues from her own user. Without it the apply stops before
  reading any key. `--check` keeps the secret's read-only key.
- **Both modes refuse an org whose name does not start with `WIB_DD_POOL_PREFIX`** (default `Datadog`, as in
  `verify/datadog-orgs.sh` and `room_view.py`), so six monitors with `notify_no_data` never land in some other org.

No metric or tag name changed. Nothing here measured them, so the six names the issue lists are as unproven
as before. The docs that give the apply line (the README, GO-LIVE-CHECKLIST step d2, the run-of-show's Night
Before item and the live test's failure hint) now include the key.

**Tests.** `verify/test_fleet_monitors.py`'s fake org now answers `/api/v1/org` with 403 and names itself from
`/api/v2/current_user`, as the sandbox org does. New checks: the apply sends the env key and `--check` the
secret's key; `--apply` without the env key exits 1 having read no key and made no call; `--apply` and
`--check` against an org named `event-001` exit 1 after one read and no write; `WIB_DD_POOL_PREFIX` names a
pool's org instead. The old loader fails the file (no `APP_KEY_ENV`), and a loader that applies with the
read-only key fails the key check.

**Not yet run on a cluster.** With the clusters up and shipping: Whitney (or Michael signed in to her org)
issues the key and runs `WIB_FLEET_MONITORS_APP_KEY=<key> infra/terraform/fleet/fleet.sh monitors --apply
--session <start>Z/<end>Z`, then `infra/terraform/fleet/fleet.sh monitors --check`. Then
`verify/test_fleet_monitors_live.py` (in `bash verify/run-e2e.sh`) must pass, and every column of the fleet
dashboard must fill for both clusters. A blank column means a wrong name, fixed in `infra/datadog-fleet/` and
`verify/test_fleet_monitors.py` together (#485).

## 2026-10-30 · #520 · #481's live check: the public half passes on both clusters, the in-cluster half is still owed

**No code changed.** #520 asks for `verify/test_console_no_toggle_live.py` on the admin and community clusters.
Hecaton runs have no AWS profile or kubeconfig, so the test's `kubectl exec` steps cannot run from one. The
clusters are now watch-it-burn-community (`attackme`) and watch-it-burn-private (`burritobot-private`), the
admin-profile cluster since #632. michael-admin is gone and answers 404 even on `/guards`.

**The public half was probed from outside on 2026-10-30 at 03:12Z**, with the same requests the test sends
(GET, no query, so nothing flips), on `attackme` and `burritobot-private` under both agenticburn.com and
burritobot.co:
- `/guards` returned 200 with the guard JSON on both. Every guard was off on both clusters.
- `/a2a/toggle`, `/a2a/guards`, `/a2a/` and `/toggle` returned 404 on all four hosts. The 404 body is the console's
  own nginx/1.27.5 page and holds no guard key. With the old route in place, `/a2a/guards` would have returned
  guard-proxy's JSON. So the deployed consoles carry #481, and no separate roll-console run is needed for them.

**Not yet run on a cluster:** the test's in-cluster half: the `cluster-identity` public host, guard-proxy's
`/guards` read over `kubectl exec`, the terminal's `_px` and `guards-status` helpers, and the check that the guards
did not move. A session with the accen-dev profile runs this once for each of watch-it-burn-private and
watch-it-burn-community:

    C=watch-it-burn-private; K=/tmp/$C.kubeconfig
    AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig $K --name $C --region us-west-2
    CTX=$(KUBECONFIG=$K kubectl config current-context); [[ $CTX == *"cluster/$C" ]] && \
      KUBECONFIG=$K AWS_PROFILE=accen-dev CONTEXT="$CTX" python3 verify/test_console_no_toggle_live.py
## 2026-10-30 · #532 · The live `ingest pool` run waits on #656, and on an attendee pool being up

#532 asks for one live `fleet.sh ingest pool` run, so that claimed rows show the terminal login their cluster
enforces and the harvester's interface (`<cluster> [region] [out-dir]`, AWS_PROFILE from the environment, exits
0/3/1, #445) is confirmed. Hecaton run 12337 did not run it, and found that the command it would run is no longer
the one the issue describes. No code changed.

- **Its write side moved.** Since #600, `ingest_one` pipes each row to `labctl import` into lab-platform's
  handout pool, not to the provisioning app's /admin/import. The claimed rows #445 wanted corrected were the
  provisioning app's, and nothing in fleet.sh writes there now.
- **Its read side did not.** `cmd_ingest pool` still takes its names from `pool_rows`, which reads the
  provisioning app's /admin/roster with the admin token. Run today, it would re-import into lab-platform the
  names of a pool fleet.sh no longer fills. #656 is the issue that moves `pool_rows` to lab-platform, and its
  blocker is gone: lab-platform#302 added `labctl pool --customer <c> --event <e>` (lab-platform commit 227774f),
  which prints every cluster still in an event's pool with its state.
- **No attendee pool is up.** The platform rebuilt on 2026-10-28 is the roster alone, `watch-it-burn-community`
  and `watch-it-burn-private` in accen-dev (PROJECT_STATE.md, "KubeCon platform up"). The KubeCon session points
  nobody at a distributor, so no attendee lab runs (`facilitation/kubecon-na-2026-run-of-show.md`, "The one
  platform, and the two clusters on it"). Both roster clusters carry `sprouts`, not `agentic`.
- **The harvester's source is still unread.** `sources repo-cat agenticburn/provisioning-agenticburn/scripts/harvest_terminal_credential.sh`
  is still refused as "looks like a secret", and `repo-ls` of that directory does not list it.

**Not yet run on a cluster.** After #656 lands, with an attendee pool imported for the event and its clusters up,
a session with the fleet's AWS profiles, labctl on PATH, `DATABASE_URL`, `USER` and `WIB_EVENT` set, and
`WIB_PROVISION_DIR` at a provisioning-agenticburn checkout that holds commit 3462ba2 runs
`infra/terraform/fleet/fleet.sh ingest pool`. It must end with no `ingest:<name>` or `terminal-open:<name>`
failure, `labctl pool --customer agenticburn --event "$WIB_EVENT"` must list the same names with every claimed
row still claimed (#655's fifth assumption), and the terminal login a claimed attendee is handed must be
`agentic` / `agentic`.

## 2026-10-30 · #535 · The off-topic answer is promised: the community probe was 6 of 6 live, 3 of 3 on the linked-list ask

Michael ran `verify/kubecon_probe.py community` on attackme.agenticburn.com on 2026-10-27 (#610): 6 PASS, 0
FAIL. The linked-list ask was answered 3 of 3, and `judge_ceo_leaks` passed on the CEO record's address in the
reply the room reads (Michael's comment on #535). That is the condition #530 set, so its notes come out:
Segment 2 of the run-of-show and the off-topic beat on `/kubecon` now say the bot answers the room's off-topic
asks, citing the 10-27 run, and `docs/KUBECON-ABSTRACT-READINESS.md` row 9 says the same. The two checks in
`verify/test_kubecon_probe.py` that pinned the "not promised" wording are removed, as Michael asked.

The gate does not go away, it moves to the night. The off-topic beat is still part of the community probe, which
the Night Before list says must end `KUBECON PROBE GREEN`, and later runs missed it once each on 2026-10-29
(2 of 3, the miss narrating its plan; both are in the run-of-show's Probe record). If the night's run misses it,
that run is red and the room is not told the bot will answer until it is green again.

The C5 address judge's first live run on the admin kind was the same 10-27 bring-up (michael-admin, C5 leaks
PASS) and the 10-28 watch-it-burn-private run (24 PASS), so both cluster kinds have now run it.

## 2026-10-30 · #608 · The #607 Secret checks wait on a live run, and watch-it-burn-private can carry it now

#608 asks for the first live run of `verify/test_llm_bypass_live.py`, which no cluster has run since #490
(2026-10-24): the `container()` TypeError stopped it after its prerequisites, and #607 fixed that. Hecaton run 12398
had no cluster and no AWS credentials (`kubectl config get-contexts` lists none, `aws sts get-caller-identity` finds
no credentials), so the run is still owed. No code changed.

- **The attendee build the issue waits for is not coming before KubeCon.** The platform rebuilt on 2026-10-28 is the
  roster alone (PROJECT_STATE.md, "KubeCon platform up"), and no attendee lab runs at KubeCon (#532's entry above).
- **watch-it-burn-private can run it today.** It is the admin profile (`role_of_instructor_name`, held by
  `verify/test_cluster_roles.sh`), whose app list in `gitops/bootstrap/values-admin.yaml` has every app the attendee
  profile has that the test reads: kyverno and kyverno-policies (both ValidatingPolicies it compares with
  `policies/kyverno/`), namespaces (`agent`), and ai-layer (agent-sa and chat-path-ingress, for the #552 checks).
  Arming the admin cluster flips only require-resource-limits and restrict-image-registries to Deny (`fleet.sh`,
  `arm_infra_guardrails`). The test's pods set CPU and memory limits and use the signed busybox, so neither policy
  should refuse a shape the test expects to be admitted.
- **watch-it-burn-community cannot.** It is the burn profile, with no Kyverno, so the test fails its "ValidatingPolicy
  deny-llm-endpoint-bypass is installed" prerequisite there, as designed.
- **What a run touches.** The #607 checks are server-side dry runs and store nothing. The #333, #490 and #552 checks
  create real Pods, Deployments and a ConfigMap in `agent`, labelled `wib.test/run=<id>`, and delete them on the way
  out. Nothing calls a model.

**Not yet run on a cluster:** `verify/test_llm_bypass_live.py`, all of it. A session with the accen-dev profile runs:

    C=watch-it-burn-private; K=/tmp/$C.kubeconfig
    AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig $K --name $C --region us-west-2
    CTX=$(KUBECONFIG=$K kubectl config current-context); [[ $CTX == *"cluster/$C" ]] && \
      KUBECONFIG=$K AWS_PROFILE=accen-dev CONTEXT="$CTX" python3 verify/test_llm_bypass_live.py

and records here whether the three #607 checks pass (terminal-auth refused by volume and by secretKeyRef, each
with its message; ceo-personal-record admitted), and whether the #490 and #552 checks the TypeError hid pass.

## 2026-10-30 · #629 · The sandbox org's done-when list is one live check: verify/test_datadog_sandbox_live.py

Everything #629 asks of the repo is on staging: the env tag (57ad24d), the burritobot-public and burritobot-private
cluster names (77cd0d9), the single-org verifier (7210a3b), the AI-layer pods' log labels (75dd08e), the platform pods'
(#661, #662), and question 868's root-service exception (above). What was missing was a way to see the done-when list
hold in Whitney's org: the issue stayed open on "the live check", and no test said what that check was. There was no
earlier draft to check against staging; the three agent/629-* branches are all merged.

- **`verify/test_datadog_sandbox_live.py`** (`# SUITE: e2e`) reads the org with watch-it-burn/datadog's read-only keys,
  through `fleet_monitors.read_keys` and `fleet_monitors.Datadog`, over the last `WIB_DD_LOOKBACK_MIN` minutes
  (default 60). It checks the Agents (`datadog.agent.running` by kube_cluster_name and env: both cluster names report,
  every series under the env), every log (the Logs aggregate API over `kube_cluster_name:burritobot-*`, grouped by
  cluster, service and env), every span (`traces.span.metrics.calls` grouped the same way: the collector counts every
  span before sampling, so this sees spans an indexed-span search would miss) and ml_app (`ml_obs.trace` under the
  env reports as burritobot and nothing else; ml_obs.* carries no cluster tag, so this one is per env). A service
  passes when it is the root `burritobot` or `burritobot-<name>`, per question 868. Request and response shapes are
  from Datadog's Logs and Spans aggregate references and the LLM Observability metrics page, read 2026-10-30.
- **`verify/test_datadog_sandbox_live_logic.py`** runs it offline against a fake org: a compliant org passes, and a
  workshop_agent span service, a log with no service or the old env, an Agent with no env, a silent cluster, one
  shared cluster name and a renamed ml_app each fail. Making the service rule always true fails four of its checks.
- **Not checked by it:** "nothing outside BurritoBot changes in the org" is a rule for whoever writes to the org, and
  the read-only key cannot read the Audit Trail. `fleet.sh monitors --apply` already touches only monitors tagged
  `wib-monitor:*` and the dashboards it names (#485).
- **It is expected to fail on the spans check until #634 lands.** kagent reports the agent's spans as
  `workshop_agent`; #634's fix (the collector's `transform/kagent_service_name`, on origin/agent/634-10236) has not
  merged, and that draft now drifts from staging in three files.
- Also corrected the stale "the SDLC env (production)" comment on the workshop-agent in `gitops/ai-layer/resources.yaml`.

**Not yet run on a cluster:** `verify/test_datadog_sandbox_live.py`, all of it. A session with the accen-dev profile,
with both KubeCon clusters up on a staging that includes #634, drives one /chat on each and then runs:

    WIB_DEFAULT_ACCOUNT=accen-dev WIB_REGION=us-west-2 python3 verify/test_datadog_sandbox_live.py

and records here which checks pass. When all pass, #629 closes.

## 2026-10-30 · #638 · The admin role's guardrails arm from lab-platform's arm parameter, guardrails.validationAction

The front door half of #638 is on staging (96c050f, 264c252, the 2026-10-28 entry above). The issue's newest comment
adds lab-platform#310's request (hecaton filed no separate issue for it): lab-platform's `labctl event up` now has an
`arm` step (lab-platform#311, #312) that sets one Helm parameter on the `lab-bootstrap` root of every cluster whose
role arms its guardrails, the admin role of burn@2.0.0, 2.1.0 and 2.2.0, and refuses a burn event whose talk config
declares no `arm` section. So `labctl event up`, which the front door's definition of done runs, needs this section
too. There was no earlier draft of this part to check against staging.

- **The parameter is `guardrails.validationAction`,** the example lab-platform's docs use, declared in
  `lab-platform.yaml` as `arm: {parameter: guardrails.validationAction, value: Deny}` (block style, as the strict
  parser wants). The chart's default is `Audit`; any other value fails the render by name.
- **Deny is a kustomize patch on the kyverno-policies Application.** With the parameter at Deny,
  `gitops/bootstrap/apps/kyverno-policies.yaml` renders `kustomize.patches` replacing `/spec/validationActions` with
  `[Deny]` on `require-resource-limits` and `restrict-image-registries`, and does not render its `ignoreDifferences`
  on that field, so selfHeal holds the armed state from git. At Audit the file renders as before, with the ignore,
  so the attendee's C2 patch and fleet.sh's `toggle-kyverno-enforce.sh` on a deploy-full-idp.sh admin or full
  cluster (KubeCon) still hold. Both guards sit in YAML comments, as the front door's do; `verify/bootstrap_chart.py`
  `for_guardrails` is the file as rendered at either action.
- **policies/kyverno gains a `Kustomization`,** listing all ten policy files and nothing else, because Argo CD
  applies `kustomize.patches` only over a kustomization file. Named `Kustomization`, the third name kustomize and
  Argo CD read, so the `*.yaml` globs that feed the directory to the Kyverno CLI in five verify/ tests do not pick it
  up. Argo CD now builds the directory as kustomize on every profile instead of as a plain directory; the build is
  the same ten policies, which the render test checks with the pinned kubectl. A policy file added there and not
  listed would reach no cluster, so `verify/test_guardrails_arm.py` fails on one.
- **Considered and not taken:** a second directory of Deny copies of the two policies (two files to keep equal), and
  making the directory a Helm chart (a larger change to every policy for one field). No profile's values file sets
  the action: arming waits for lab-platform's arm step, after the root has synced, so a guardrail at Deny never
  refuses the platform's own pods during the first sync.
- **Tests:** `verify/test_guardrails_arm.py` (offline: the Kustomization's list, both policies at Audit, the
  parameter a chart value), `verify/test_bootstrap_chart.py` (the section, the default, the guards) and
  `verify/test_bootstrap_chart_render.py` (Helm v4.2.1: attendee, admin and full unarmed keep the ignore and no
  patches; admin armed has the two patches and no ignore and nothing else changes; kubectl v1.36.2's kustomize
  applies them to Deny and leaves the other eight policies as written; `Enforce` fails by name).

**Not yet run on a cluster:** the arm step against a real admin cluster. A session with AWS access runs
`labctl event up` for a burn event at a staging commit that includes this, then on the admin cluster
`KUBECONFIG=<file> kubectl --context <ctx> get validatingpolicy require-resource-limits restrict-image-registries
-o jsonpath='{.items[*].spec.validationActions}'` shows `["Deny"]` twice, and `argocd app get kyverno-policies` is
Synced. `verify/test_kyverno_cel_live.py` is not that check: it wants a full or attendee cluster at Audit. The front door's live checks, the bootstrap step's `front doors: 2 roster clusters recorded` and
`labctl tls-check attackme.agenticburn.com`, are still owed as the 2026-10-28 entry says.
## 2026-10-30 · #647 · The run-of-show's teardown carries the purge of burritobot-public from Whitney's org

The 2026-10-29 #647 entry left one part of the issue owed after the talk: purging the `burritobot-public`
data from Whitney's sandbox org. The run-of-show's Teardown section, the list followed when the session closes,
did not name it. It now has a step for it: signed in to her org, find the room's traces under
`kube_cluster_name:burritobot-public` for the session window. Delete their LLM Observability spans by trace id
through `POST /api/v2/llm-obs/deletion/data/llmobs`. That endpoint is in preview: Datadog's API reference,
read 2026-10-30, says it takes a query with an `@trace_id` filter and returns a deletion request. For the APM
spans, ask Datadog support or leave them to retention. Then post on #647 what went and what is left.

- **No purge script.** The endpoint is in preview, and no run has a key to Whitney's org to try it. A script
  written now could not be checked before the one time it is used, so the step names the call and says to
  confirm it on the day.

**Tests.** `verify/test_collector_pii_scrub.py` now also checks that the run-of-show's Teardown section has a
purge step naming #647, the cluster tag, the deletion endpoint and retention. It fails 6 checks with the step
taken out.

**Not yet run.** The purge itself, after the talk on 2026-11-12, by Whitney or by Michael signed in to her org.

## 2026-10-30 · #653 · Second pass: the KubeCon run-of-show's C2 fallback row names the promo/ Joker; the pull still waits on the package toggle

The 2026-10-29 entry's change is on staging (7ffbc73, 1414255, e5bd6fe). Run 12561 checked what it left:
- **One stale copy.** `facilitation/kubecon-na-2026-run-of-show.md`'s fallback table still said the C2 script denies
  a Deployment of `docker.io/peopleforrester/joker:latest`. The script creates
  `ghcr.io/peopleforrester/lab-platform/promo/joker:v1`, so the row now says that. `verify/test_promo_villains.py`
  now reads the row and checks it names the image the fallback's `VILLAIN` resolves to and no `docker.io/` image.
  With the row reverted, that check fails.
- **Left as written on purpose.** `docs/RUN-OF-SHOW-2026-08.md` is the August record and says so in its banner. The
  Docker Hub Joker in C6's ticket (`ticket_site.py`, lab.html's C6 section, LAB-TEXT.md, PROMPT-CATALOG.md and the
  injection text) is the C6 follow-up the first entry named, not part of this issue.
- **The packages are still private.** On 2026-10-30, `python3 verify/test_promo_villains_public.py` failed on all
  ten with "token refused, HTTP 401 Unauthorized: the package is private or does not exist", as in #678. Until
  Michael sets the ten promo/ packages in lab-platform to Public, a cluster admits the villain in Audit and then
  leaves it in ImagePullBackOff, and the E2E tools tier stays red on that one test.

**Not yet run on a cluster.** The checks the 2026-10-29 entry names, once the packages are public:
`python3 verify/test_promo_villains_public.py`, then on an attendee cluster
`CONTEXT=<ctx> python3 verify/test_kyverno_cel_live.py`, and `CONTEXT=<admin-ctx>
challenges/c2-villain-image/fallback.kubectl.sh`, whose denial now matches the run-of-show row.

## 2026-10-30 · #504 · The on-topic guard is tested in the running path: the pinned proxy.py, on the deployed env

**Decision.** `verify/test_topic_guard_proxy.py` (offline, new) checks the #455 criterion, "BurritoBot ends selling
burritos only", against guard-proxy itself. Before it, the tests held the deployed phrase lists to
`verify/topic_cases.py`'s own copy of the rule, and only grepped the terminal helpers. The first run of #504
(2026-10-24) was blocked because proxy.py had no topic stage. guard-proxy-agenticburn#7 has since added it, and the
submodule pin (000f57e) carries it.

**What it does.** It loads proxy.py from the `gitops/ai-layer/guard-proxy` submodule with the guard-proxy
Deployment's literal env from `gitops/ai-layer/resources.yaml`, so TOPIC_GUARD, both phrase lists, TOPIC_REFUSAL,
PROXY_FAIL_CLOSED and the rate limits are the ones a cluster runs. Only AGENT_URL, LLM_GUARD_URL and the token
point at stand-ins on localhost. The stand-in agent answers anything and records what reached it. The stand-in LLM
Guard plays BanTopics: it refuses the `topic_cases.OFF_TOPIC` paraphrases that no phrase catches, unless BanTopics
is suppressed. The guard is flipped by the web terminal's own `guard-topic-on` and `guard-topic-off`, taken from
`web-terminal/entrypoint.sh`. A stub kubectl runs their `exec deploy/guard-proxy` python against this proxy. The
test checks these things in order:
- With the guard off, the canonical off-topic asks reach the model, as the wide-open start needs.
- `guard-topic-on` turns the guard on, and `/guards` reports it on.
- On `/chat`, every off-topic ask gets the deployed TOPIC_REFUSAL, `guarded`, 0 tokens, and never reaches the
  agent. An ask with an off phrase makes no classifier call. An ask without one makes one `/analyze/prompt` call
  with `scanners_suppress: ["PromptInjection"]` and the bearer token. Each refusal logs `topic_guard_block` with
  the step that decided it.
- Every on-topic ask reaches the model with no classifier call, and a vague one the classifier passes reaches it too.
- On A2A `/`, an off-topic message gets 403 with TOPIC_REFUSAL, and an on-topic one is forwarded.
- With LLM Guard answering 500, an ask left to the classifier is refused (fail closed). An on-topic ask still
  passes on its phrase.
- `guard-topic-off` opens the guard again.

**Checked to fail when the criterion stops holding.** Seven mutants of proxy.py, each written to a copy outside the
repo, fail the test: the /chat topic stage removed, the A2A topic stage removed, the topic stage's suppress list
dropped, an on phrase that refuses, a classifier error that fails open, `/toggle` that ignores `topic`, and a /chat
refusal that is not TOPIC_REFUSAL.

**Also changed.** The Deployment's comment said these variables are inert until guard-proxy-agenticburn carries the
topic stage. It does now, so the comment names the new test instead.

**What differs from the draft.** Run 10552's draft (`origin/agent/504-10552`, commit 24aa93a) was cut from an
older staging (633f814) and never reached staging. `verify/draft-drift.sh` named two drifted paths, decisions.md and
`gitops/ai-layer/resources.yaml`, both edited by later commits in places away from the draft's. The test file is
the draft's, unchanged: proxy.py, the Deployment env, `topic_cases.py` and the terminal helpers it reads are as they
were, and it passes on this staging with the same 184 checks. The resources.yaml comment and this entry are written
again on the current files rather than cherry-picked. The run after 10552 stalled with no commit; this one found no
test that hangs (see the run's report).

**Not changed.** `verify/test_topic_guard.py` still arms its BanTopics scanner checks only once BanTopics is in
scanners.yml. That waits on the offline image carrying the zero-shot model (llm-guard-cpu-offline#2) and is not
#504's criterion.

**Not yet run on a cluster.** The real BanTopics scores on the paraphrases are judged by
`verify/test_topic_classifier.py` (E2E suite). The live refusal through the storefront is judged by
`verify/kubecon_probe.py`'s topic beats, run by hand on a presenter's admin cluster: `python3 verify/kubecon_probe.py
admin burritobot-private.burritobot.co --context <admin-context> --kubeconfig /tmp/private.kubeconfig --profile
accen-dev`.

## 2026-10-30 · #559 · The trace view's beats scope to one session, and C6 reads the guard decision guard-proxy stamps

**Decision.** guard-proxy-agenticburn#8 (commit d98ad61) stamps two attributes on the `POST /chat` root span:
`session.id`, the storefront's browser session id, and `witb.guard.decision`, the guard that decided the turn
(input_blocklist, input_classifier, topic, rate_limit, budget or output_redacted; absent when no guard touched it).
Michael moved the submodule pin by hand in ac68a12 (2026-10-27, now 000f57e, which holds d98ad61 and is on
guard-proxy-agenticburn main). That was question 766's answer, "Michael pins, a run does the rest", because
hecaton's forbidden gate refuses any change to a gitlink. This entry is the rest.

**What changed.**
- `observability-idp/grafana/dashboards/agent-observability.yaml` gains a `session` variable, labelled Session: a
  Tempo label-values query (`type: 1`, `label: session.id`, unscoped, because Grafana's Tempo datasource looks the
  scope up itself and prefixes it). It defaults to All with `allValue` `.*`, takes one session at a time, and
  accepts a typed id. The C5, C6, C7 and C7-companion queries each add `span.session.id =~ "$session"` to their
  burritobot `/chat` span. The gen_ai trace panel is kagent's spans, which carry no session.id, and stays unscoped.
- C6 is now `{ burritobot /chat && session && (witb.guard.decision = input_blocklist || = input_classifier) }`. It
  no longer infers a block from a `/chat` root with no `agent.forward` under it, which also listed rate-limit,
  budget and on-topic stops as C6 rows. The 400 for an empty prompt carries no decision, so the status filter went.
- `verify/test_trace_walkthrough_view.py` (the file #675 renamed from `test_segment6_view.py`, which the issue
  names) holds the C6 query to that exact shape, holds the variable and the four session filters, and checks
  proxy.py: `_stamp` writes to the server span, each input guard stamps its decision after its log line and before
  any `agent.forward`, session.id is stamped before any guard answers, the other decisions are ones C6 leaves out,
  and the storefront sends its session on every `/chat`. Against the old dashboard it fails 7 checks.
- The run-of-show's trace-view section names the Session picker and says to leave it on All, since Reset starts a
  new session. The sentence that called the 30-minute window "this session" is gone.

**Checked against Tempo 3.0.3.** The release binary (SHA-256 7ac4f095…, matching the release's SHA256SUMS) ran
locally on eleven synthetic traces: each decision, a sessionless block, a 400, a C5 redaction, C7 with and without
read_internal_config, and a plain turn, across two sessions. Each of the four beat queries, run as All and for each
session, returned exactly its intended traces (12 of 12). The old C6 query on the same traces also returned the
rate_limit, budget and topic turns. `/api/v2/search/tag/span.session.id/values`, the call behind the picker,
listed both sessions. Grafana's own variable query was not run against a live Grafana 13.2.2.

**What differs from the draft.** Run 8269's commit da48d3c is gone from the remote (question 766), so nothing was
reused. Staging has moved since: the segment 6 test became `test_trace_walkthrough_view.py` (#675), the row became
"Traces" in C5, C6, C7 order, and proxy.py gained the topic decision, which C6 leaves out. The pin and
checksum/proxy-py were Michael's commit, not this one.

**Known gap, filed as a follow-up.** Since #676, KubeCon's Challenge 3 (C6, HC-666) is stopped inside
`read_support_ticket`, which withholds the flagged ticket; the `/chat` prompt is innocent and the model is still
called. That turn carries no input-guard decision, so this panel (like the old one) lists the direct-prompt block,
not the HC-666 beat. Showing that beat needs a query on the tool span, which is outside this issue.

**Not yet run on a cluster.** No E2E test covers the Grafana view. On the private cluster with guard-input-on,
send a blocked `/chat` from the storefront and open
`https://grafana-burritobot-private.agenticburn.com/d/witb-agent-obs`. The Session picker should list the
storefront's `sess-…` id, and C6 should show the turn with All and with that id.
## 2026-10-30 · #587 · An attendee cluster on the instructor's own org ships the lab markers there, once

#587 is a live run: validate the lab markers, `/lab-events`, the collector's lab pipeline and the fleet-analytics
dashboard on an attendee cluster. This run had no cluster and no AWS, so it did not do that (CLAUDE.md, Dispatched
runs, rule 1). `verify/test_lab_pipeline_live.py` (2026-10-25 entry above) is the check that does. Reading it
against the cluster the next live run will build showed that it could not pass, and neither could the platform.
The next attendee cluster is #461's: question 926 chose a one-row pool copied from `watch-it-burn/datadog`, so the
cluster's own key is the instructor org's key (Whitney's one sandbox org, #629). Four things assumed a second org:

- **The attendee collector would not start.** `infra/datadog-cluster-identity.sh` writes no `datadog-admin-secret`
  when the admin key equals the cluster's key (since #242, so nothing counts twice). `values-dual.yaml` read
  `DD_ADMIN_API_KEY` from that secret with a required reference, so the pod could not start, and the markers,
  traces and metrics had nowhere to go. Now the attendee ConfigMap has two files. `datadog.yaml` is one org: the
  instructor overlay without Tempo, with the lab pipelines to `datadog`. `datadog-dual.yaml` is two orgs, unchanged.
  The datadog-gate (values.yaml) reads `DD_ADMIN_API_KEY` from the admin secret, optionally, and copies the dual file
  only when the key is set and the file exists. The instructor and burn ConfigMaps have no dual file, so nothing
  changes for them. `DD_ADMIN_API_KEY` on the attendee collector is optional now; `DD_API_KEY` stays required.
- **Its markers carried the EKS name.** Helm replaces `extraEnvs`, and `values-dual.yaml`'s `WIB_CLUSTER_NAME` still
  read `cluster-name` after #629 moved every consumer to `datadog-cluster-name`. Attendee spans and `witb.lab.calls`
  said `watch-it-burn-attendee-NNN` while the Agents said `burritobot-attendee-NNN`, against #629's rule that
  BurritoBot's cluster names start with burritobot. It reads `datadog-cluster-name` now. The fleet-analytics
  dashboard's `cluster` default moves from `watch-it-burn-attendee-*` to `burritobot-attendee-*`; its
  `datadog.agent.running{$cluster}` widget matched nothing since #629. Pass 6's regex takes either name.
- **`fleet.sh converge` would repair the cluster on every pass.** `repair_datadog` wanted an admin secret whenever
  an admin key resolved, and the identity script removes it on one org, so every converge re-ran the identity script
  and restarted the collector and Agents. It wants one only when the admin key differs from the cluster's.
- **`verify/datadog-orgs.sh` failed the cluster.** An attendee without `datadog-admin-secret` was a FAIL. It now reads
  `watch-it-burn/datadog`'s api key and passes "one org by design" when that is the cluster's own key; any other
  attendee without the secret still fails, including when the instructor key cannot be read.

**The live check reads which way the cluster ships.** `test_lab_pipeline_live.py` used to fail unless the
student's org differed from the instructor's. Now, when the cluster's `datadog-secret` key is
`WITB_DD_ADMIN_API_KEY`, it requires no `datadog-admin-secret`. Otherwise it requires that secret to carry the
instructor key and keeps the two student-org absence checks. In both cases it requires the calls to add up to the
spans sent, which a second exporter on the same org would double. It scopes every Datadog query, and pass 6's row,
by `datadog-cluster-name`.

**Tests.** `test_collector_no_datadog.py` runs the gate under sh with the attendee ConfigMap in four states (no
secret, datadog-secret only, admin secret only, both), and checks the one-org file against the instructor
overlay's lists without Tempo. It also checks that no datadog/admin exporter or DD_ADMIN_API_KEY is in the one-org
config, and that a missing admin secret blocks nothing. `test_lab_events.py` checks the one-org lab exporters and
every profile's `WIB_CLUSTER_NAME` key. `test_datadog_sandbox_names.py` checks that key per profile, as each
Application layers its value files; on the old overlay it fails for attendee.
`test_fleet_converge_repairs.sh` adds a one-org pool: an attendee on the instructor key with no admin secret is
left alone, and one with an admin secret is repaired. Both checks fail on the old `want_admin` line.
`test_datadog_admin_key.sh` runs `datadog-orgs.sh` against shim kubectl, curl and aws. The one-org case passes,
and fails on the old verifier. A second org without the secret, and an unreadable instructor key, both fail.
`test_lab_pipeline_collector.py` (E2E tools tier) validates the one-org attendee config with the real
otelcol-contrib 0.160.0 and no `DD_ADMIN_API_KEY` in its environment. The live check was smoke-run outside the
repo against a fake kubectl, a fake Datadog and a fake pass 6. Both modes passed. Doubled calls on one org, and a
stale admin secret on one org, each failed one check.

**Not yet run on a cluster.** `verify/test_lab_pipeline_live.py`, all of it, during #461's run (question 926's
one-row pool, `WIB_NO_INGEST=1 ./fleet.sh up 1`). Before `run-e2e.sh`, apply the dashboard to the sandbox org.
That takes an application key that can write, which Whitney issues from her user, as for #485's monitors:
`cd infra/terraform/dashboards && DD_API_KEY=<watch-it-burn/datadog api-key> DD_APP_KEY=<write key> terraform init &&
DD_API_KEY=... DD_APP_KEY=... terraform apply`. Then run `run-e2e.sh`, or the check alone:
`KUBECONFIG=/tmp/watch-it-burn-attendee-001.kubeconfig CONTEXT=arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-attendee-001
WITB_DD_ADMIN_API_KEY=<watch-it-burn/datadog api-key> WITB_DD_ADMIN_APP_KEY=<watch-it-burn/datadog app-key> python3
verify/test_lab_pipeline_live.py`. Also owed on that cluster: the datadog-gate's log says datadog-secret found, and
not dual (`kubectl -n monitoring logs ds/otel-collector-opentelemetry-collector-agent -c datadog-gate`).
`verify/datadog-orgs.sh <context>` says one org by design, and a second `fleet.sh converge` repairs nothing.

## 2026-10-30 · #603 · images.lock records all 25 image references and the declared llm-guard-api by digest and source; the tarballs wait on a netcup save

The fleet rule from llm-coding-workflow#182 (claude-config/rules/infra/image-retention.md there) asks each repo for
an `images.lock`: one row per image it depends on, with its registry digest, where its source lives and the date
its tarball was saved, written by llm-coding-workflow's `scripts/mirror-images.sh`. VERSIONS.lock's digest TODO for
laiyer/llm-guard-api was closed in the earlier run of this issue.

- **`images.lock` at the root.** Its rows are the 25 references `mirror-images.sh refs .` finds, in its order, then
  one declared row, laiyer/llm-guard-api:0.3.16 at sha256:bea3efb1…50ba, upstream protectai/llm-guard (the issue's
  source; the rule would switch an archived upstream to a `repo:` fork, and llm-guard-upstream-mirror is a private
  mirror of it, but nothing deploys that image now). Every digest was read from its registry on 2026-10-30 over the
  registry API, and every pinned reference matched. Two were not readable anonymously: lab-platform's llm-guard:v1
  package is private, so its row takes the digest ai-layer.yaml pins, and watch-it-burn:tool-pin is a 404.
- **Sources.** The docker-library and vendor images are `upstream:` their Dockerfile repos; the watch-it-burn
  mirror copies of python, nginx and busybox are `upstream:` the image they copy. workshop-mcp, web-terminal and
  sample-app are `repo:` this repo's `images/<name>`; llm-guard (a kustomize name) is
  `repo:peopleforrester/lab-platform/deploy/images` with lab-platform's name@sha256 as its digest; vllm-qwen3 is
  `repo:peopleforrester/packt-agentic-devops/images/vllm-qwen3`. The four KubeArmor references are templated on
  `{{.Values.imageRegistry}}`, so their digests are the lab-platform mirror copies by name@sha256.
- **Not images.** The two Backstage scaffolder parameters, challenge 03's `REGISTRY/evil-mcp-shim@sha256:REPLACE_AT_BUILD`
  and its untagged privileged `busybox` (a deliberate bad example the policies deny), and beat 02's
  `docker.io/DOCKERHUB_USER/villain-joker:latest` are `not-an-image:` with digest `-`. The #480 spike's tag-only
  `watch-it-burn:tool-pin` was never pushed, so it is `build:images/tool-pin` with digest `-`; when it is pushed by
  digest it becomes a `repo:` row.
- **`verify/test_images_lock.py`** finds references as the script does and fails when one has no row, when a row's
  source, digest or saved column breaks the rule, when a digest disagrees with the one pinned in its reference, or
  when the llm-guard-api row drifts from VERSIONS.lock. It finds the same 25 references in the same order as
  `refs`. It accepts saved `-`, since the date is the netcup step; `mirror-images.sh check .` is what owes it, and
  today it reports the 20 rows that need a tarball as "never saved" and nothing else.

**Not yet saved.** This run is on netcup but cannot reach the Docker daemon (the socket is root:docker) or write
`~/repos/private/image-archive`. As michael, after this reaches staging, in the talk's checkout:
`mirror-images.sh save . && mirror-images.sh check .`, then commit images.lock with the dates it writes. The pull
of lab-platform's llm-guard and mirror copies needs a ghcr login that can read lab-platform's packages, and
vllm-qwen3 is about 5 GB.

**Out of scope here.** Images a Helm chart pulls (Argo CD, Kyverno, Falco and the rest) are named by no tracked
`image:` line, so they are not rows; lab-platform's mirror copies of the Docker Hub ones are its own to retain.
## 2026-10-30 · #264 · A blocked tool call is an error on its own span, whichever shape its result takes

**What was left of the issue.** The one-trace half is #320's entry above (b78bc62): the noise filter no longer cuts
the parent chain, so one interaction is one root and its tool calls hang under the prompt. The lab half was already
there, in Whitney's wording: Challenge 1 names `run_shell` and its `curl`, and says a tool runs commands inside the
cluster and a command can send a web request anywhere. What remained is the clause "the failed call must read as an
error" (#261) on the span a student clicks. `transform/adk_tool_content` marked `execute_tool` only from MCP's
`isError: true`. Whether a raised run_shell failure reaches ADK's span as MCP's error result or as the exception's
text depends on how ADK hands the result over, and Michael's 2026-09-06 comment left open an OTTL rule that "sets the
span status from a tool_response starting with 'command FAILED'".

**Made it.** Two statements beside the isError pair also set `STATUS_CODE_ERROR` and its message when the tool
response carries `command FAILED`, the wording every run_shell raise keeps (`verify/test_run_shell_failure.py`).
`verify/test_tool_failure_status_e2e.py` (E2E tools tier) runs four spans through the pinned otelcol-contrib for
the instructor, attendee and burn traces processors: run_shell with the failure as text and with MCP's isError are
both errors, get_marketing_intel's success is not, and the model call that read the failure is (mark_tool_failure).
Against the config before this change, its six text-shape checks fail; with it, every check passes.
`verify/test_collector_config.py` pins both statements.

**Against the earlier drafts.** Run 12155's e39438e was cut from 6f24e46 and carried a parent-chain fix of its own;
#320 landed the same fix on staging first, in b78bc62, keeping the gateway span by its `:3000` Host. Run 12313's
redo (11df574 on `origin/agent/264-12155`, cut from f72df7b) dropped those regions and carried over only the status
statements, with this test. Since then staging edited `gitops/otel-collector/values.yaml` for #587 (the datadog-gate
and its dual overlay) and `decisions.md`; `verify/draft-drift.sh` named both. Neither touches
`transform/adk_tool_content`, so the design is made again on d70ba27 unchanged: the same two statements, the same
test, the same config check. Nothing differs from 11df574 but this entry.

**Not yet run on a cluster:** on a fresh attendee cluster with the collector rolled, send Challenge 1's stuck prompt
with the C1 NetworkPolicies on, open the interaction in Agent Observability and confirm `execute_tool run_shell` is
`status:error` with the "command FAILED" result readable on it, under the guard-proxy root. The one-root half is
#320's `CONTEXT=<admin-context> python3 verify/one_root_probe.py`.

## 2026-10-30 · #634 · The collector renames kagent's workshop_agent to burritobot-agent, first in each pipeline

Whitney's sandbox org, after one /chat on attackme, had `traces.span.metrics.calls` series for `service:burritobot`
and `service:workshop_agent`. Her rule (#629) is that every service starts with `burritobot`.

- **Where the name comes from.** kagent 0.10.1 sets it. kagent-adk's `cli.py` calls
  `configure_tracing(app_cfg.name, app_cfg.namespace, server)`. kagent-core exports that name for `configure` in
  `kagent/core/tracing/_utils.py` (read at tag v0.10.1), which builds `Resource.create({"service.name": name,
  "service.namespace": namespace})`, and `KAgentConfig.name` (`kagent/core/_config.py`) is KAGENT_NAME with `-`
  turned into `_`. OpenTelemetry's Resource.create gives the attributes passed to it precedence over
  OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES, so the Agent's pinned burritobot-agent is dropped, while
  service.version and deployment.environment.name from the same env still arrive. The collector and ADK set no
  service name. KAGENT_NAME is also kagent's A2A app name, so this repo leaves it alone and fixes the name
  downstream.
- **The fix.** `transform/kagent_service_name` in `gitops/otel-collector/values.yaml` holds one resource-context
  statement, `set(service.name, "burritobot-agent") where service.name == "workshop_agent"`, for traces and for
  metrics. It runs right after memory_limiter, ahead of filter/drop_noise, because every agent rule after it
  matches burritobot-agent. While the agent reported workshop_agent those rules matched nothing: its ASGI send and
  receive spans and its empty `chat <model>` spans shipped again, and call_llm and invocation lost their
  invoke_agent stamp. The rename puts all of that back.
- **The burn overlay.** `values-burn.yaml` restates the traces processors in full (for `transform/scrub_pii`, #647),
  and burn is attackme, where the issue was measured, so the rename is listed there too.
- **An exact name.** `verify/test_service_naming.py` derives the literal from the Agent's metadata.name. A renamed
  Agent then fails the offline suite before a new service can reach the org. The same test holds the rename's
  position on every profile, with and without datadog-secret.
- **Checked on the real collector.** `verify/test_kagent_service_name_collector.py` (`# E2E TIER: tools`, the
  pinned otelcol-contrib 0.160.0) runs each profile's shipped pipelines on one /chat's spans and kagent's token
  metric. On staging's config it reproduces the measurement: spans and `traces.span.metrics.calls` as burritobot
  and workshop_agent. With the rename both are burritobot and burritobot-agent on all three profiles, the ASGI
  send and empty chat spans are dropped, the parented `POST /` server span stays (#320), and call_llm carries
  invoke_agent.

**What differs from the draft.** Run 10236's commit ca7e601 was cut from a staging that predates #320 and #647. Its
E2E test checked that a parented `POST /` server span was dropped; since #320 that span is kept, so the test
checks the ASGI send leaf and the empty chat leaf instead, and also checks the server span stays. The draft
missed `values-burn.yaml`, which #647 later gave its own traces processor list; this change lists the rename
there. The draft's test ran the attendee profile only; this one runs all three.

**Not yet run on a cluster.** On attackme, after the collector syncs, drive one /chat and run
`verify/test_datadog_sandbox_live.py`. Its span check groups `traces.span.metrics.calls` by service and should
list only burritobot and burritobot-agent.

## 2026-10-30 · #608 · #638's arm parameter flips the same two policies, so the guarded run on watch-it-burn-private stands

Hecaton run 12735, the fifth on #608, again had no cluster and no AWS credentials (`kubectl config get-contexts`
lists none, `aws sts get-caller-identity` returns NoCredentials). `python3 verify/test_llm_bypass_live.py` stops at
"CONTEXT names the cluster to run against", exit 1, as designed. Since the first #608 entry above, #638 (ea699ed)
gave the admin role a second way to arm: lab-platform's `labctl event up` sets `guardrails.validationAction=Deny` on
the lab-bootstrap root, and `gitops/bootstrap/apps/kyverno-policies.yaml` then patches `[Deny]` onto
require-resource-limits and restrict-image-registries and nothing else. These are the same two policies that
`infra/terraform/fleet/fleet.sh` `arm_infra_guardrails` flips. The test's pods still set CPU and memory limits
(`verify/test_llm_bypass_live.py` `container()`) and use the signed busybox on ghcr.io/peopleforrester. So an armed
watch-it-burn-private still refuses nothing the test expects admitted, either way it was armed. No code changed.

**Not yet run on a cluster:** `verify/test_llm_bypass_live.py`, all of it, with the guarded command in the first
#608 entry above. The result goes here: the three #607 checks, and the #490 and #552 checks the TypeError hid.
## 2026-10-30 · #265 · question 925: a blocked tool call is one error, on its tool span, shaped as the GenAI semantic conventions say

**Question 925.** Should a blocked BurritoBot tool call be marked as an error only on its tool span, or on both the
tool span and the model call that read its result? **Answer:** "Need that to align with the Gen AI semantic
conventions, whatever needs to be done to make it as readable and presentable as possible." **Decided by Michael**
(verdict: overridden, in the web view; neither offered option was picked by name).

**What the conventions say.** Read on 2026-10-30 from open-telemetry/semantic-conventions-genai at 3fe8460 (the
GenAI conventions moved there from semantic-conventions, whose pages now only point at it): `gen-ai-spans.md`'s
execute_tool span, `gen-ai-agent-spans.md` and `mcp.md`, and the Recording Errors document of semantic-conventions
v1.44.0 they all defer to for span status.
- Status "MUST be left unset if the instrumented operation has ended without any errors", and errors "handled
  (allowing an operation to complete gracefully) SHOULD NOT be recorded on spans ... that describe this operation".
  The model call that reads a "command FAILED" result completed normally, so marking it was against the conventions.
  That settles the question for the tool span alone, which was also run 12158's recommendation.
- A failed operation is status ERROR and carries `error.type`, Conditionally Required "if the operation ended in an
  error". For a CallToolResult with `isError: true`, `mcp.md` says error.type "SHOULD be set to `tool_error`".
  Datadog maps `error.type` to `meta.error.type` and the status message to `meta.error.message` (its OTel
  instrumentation page, read 2026-10-30), so the value shows on the span.
- `gen_ai.tool.call.result` is described as the result "if execution was successful". It is still copied on a
  failure: the failure text is what a student reads to see the block, which is the "readable" half of the answer.
  The status message stays a pointer to it (Recording Errors: the description is "not expected to contain sensitive
  details", and tool output here can hold the exfiltrated payload).

**What it changes.**
- `transform/mark_tool_failure` is gone from `gitops/otel-collector/values.yaml` and from the traces processors in
  `values.yaml` and `values-burn.yaml`. A block is one error, not the "2 errors" #320 quotes.
- `transform/adk_tool_content` also sets `error.type` to `tool_error` beside each of its two status pairs (MCP's
  isError and workshop-mcp's "command FAILED" text, #264). Only a tool that raises gets marked, and run_shell is
  the only one that does. `deploy_app` returns Kyverno's refusal in Challenge 2 as text ("deploy failed for ..."),
  which FastMCP sends as a success, so `challenges/PROMPT-CATALOG.md`'s "the deploy tool call is `status:error` in
  the trace" was not true before this change and is not true now. mark_tool_failure never matched that text either.
  Making deploy_app raise, as #463 did for run_shell, is a follow-up: it changes what the agent reads back.
- `transform/set_genai_provider` now runs after `transform/set_llmobs_workflow`. This is run 12158's finding
  (2fcebad on `origin/agent/265-12158`): the provider stamp needs an operation name, and it ran before `invocation`
  and `call_llm` got theirs, so those agent spans had no `gen_ai.provider.name`.
- `verify/test_trace_shape_e2e.py` (E2E tools tier) is new. It runs Challenge 1's interaction through each profile's
  traces processors, built with datadog-secret present, on the pinned otelcol-contrib. Every agent span must carry an
  operation name and `aws.bedrock`. Both tool calls must be named `execute_tool <tool>` and carry their arguments and
  result under `gen_ai.tool.call.*`. The blocked run_shell must be ERROR with `tool_error` and the pointer message,
  and nothing else in the trace may be red. Against the previous config it fails 9 checks (provider, error.type and
  the second error, on each of the three profiles); with this change it passes.
- `verify/test_tool_failure_status_e2e.py` now requires `tool_error` on both result shapes, none on the success,
  and no error on the model call. `verify/test_collector_config.py` pins the error.type statements, that
  mark_tool_failure is gone, and that every STATUS_CODE_ERROR statement in the config reads a tool response.
  `verify/test_run_shell_failure.py` checks that adk_tool_content, not mark_tool_failure, matches "command FAILED".
  `docs/CHALLENGE-ASSETS.md`'s Challenge 1 proof now names the tool span.

**What differs from the draft.** `verify/draft-drift.sh origin/agent/265-12158 origin/staging` named
`decisions.md`, `gitops/otel-collector/values.yaml` and `verify/test_collector_config.py`, all edited since by #264
(06bb086). The draft was not cherry-picked. Its provider reorder is carried over. Its test is written again on
`verify/test_collector_one_root_e2e.py`'s parentage, which #320 read from the components' source after the draft
was cut: execute_tool sits under call_llm, the gateway's :3000 hop and kagent's server span are on the path, and
guard-proxy's GenAI span is `sanitize`, as `weaver/registry/guard-proxy-spans.yaml` defines it. The draft's noise
and one-root checks are left to that test rather than repeated. The draft's hypothesis that the split trace was our
own filter has since been confirmed and fixed by #320 (b78bc62), so it is not restated.

**Left as it is, to be read on a cluster first.** `call_llm` is stamped `invoke_agent`, so one interaction shows
three nested agent spans (invocation, invoke_agent, call_llm per turn). The conventions have no operation for an
agent's LLM step, and the 2026-09-07 Datadog reading kept these spans for their hierarchy. Whether the tree reads
better with call_llm unclassified or renamed is a judgement made by opening the trace, not by a rule.

**Not yet run on a cluster:** the before/after trace #265 asks for. On a cluster with the collector rolled and
Datadog on, send Challenge 1's prompt with the C1 NetworkPolicies on (`verify/c1-exfil-block.sh`). Open the
interaction in Agent Observability and check: the trace list says 1 error; `execute_tool run_shell` is red with
`error.type:tool_error`, and its arguments and result are readable; the generate_content after it is not red; and
`invocation` and `call_llm` carry `gen_ai.provider.name:aws.bedrock`. The offline half is
`python3 verify/test_trace_shape_e2e.py`.

## 2026-10-30 · #656 · `ingest pool` and `reconcile-pool` read lab-platform's pool through `labctl pool`

The 2026-10-29 #656 entry above left two of the issue's three paths waiting on a labctl command that lists an
event's pool. lab-platform#302 added it in lab-platform commit 227774f: `labctl pool --customer <c> --event <e>`
writes every cluster imported into the event and still in its pool, claimed or not, as CSV under
`cluster_name,state,region,reserved_for,claimed_by` (store.WritePoolCSV, Go's encoding/csv). The state is
claimable, claimed, reserved, instructor or failed. An unknown event exits 1 with nothing written, and an empty
pool writes the header alone. It is read-only and needs DATABASE_URL but no USER. That was read from
`cmd/labctl/pool.go` and `internal/store/pool.go` through `sources`. Deregister moved in #624. With this, all three
paths use lab-platform's pool.

- **`pool_rows` runs `labctl pool`.** It runs `labctl pool --customer agenticburn --event "$WIB_EVENT"` and still
  prints `<name>\t<state>`, so `reconcile_pool` and `cmd_ingest pool` are unchanged around it. It no longer scrapes
  /admin/roster with the admin token. It parses the output with Python's csv module, so a quoted address with a
  comma in it stays one field. It refuses output that has no `cluster_name` and `state` columns, and a row that
  does not fit the header, rather than reading either as an empty pool. That is the same rule the old parse used
  when its row count did not match. A labctl failure (an unknown event, a database that does not answer) is
  `pool:unreadable`, as an unreachable page was.
- **It checks labctl and DATABASE_URL, not USER.** `labctl_ready` also requires USER, because import, deregister
  and release are audited. A dry run of `reconcile-pool`, which the hygiene gate makes, only reads, so it should
  not need USER. Under WIB_APPLY=1 the deregister still goes through `labctl_deregister`, and that function still
  requires USER.
- **What the pool now holds.** labctl pool leaves out clusters that have already left the pool (released,
  deregistered, torn down). So reconcile-pool no longer names a ghost that only the old roster still lists. Before,
  it recorded `deregister:<name>` on every teardown, because labctl refuses a name the pool does not hold.
- **The admin token stays.** `resolve_admin_token` and `WIB_PROVISIONING_URL` are still used by `serve-actions`,
  the actions view and `ops`, which read the provisioning app for their own purposes. This issue did not ask for
  those to move, so `reconcile-pool` and `ingest pool` are simply no longer among the token's users.
  `cmd_reconcile_pool` now requires `aws labctl python3` in place of `aws curl jq python3`.
- **Wording.** The usage text, the hygiene gate's section 3b (`verify/fleet-hygiene.sh`) and
  `docs/GO-LIVE-CHECKLIST.md` now name lab-platform's pool and `labctl status` where they named the provisioning
  rows and the admin page. The gate still matches the same reconcile-pool log lines.
- **Tests.** `verify/test_fleet_pool_reconcile.sh` drops its /admin/roster HTML fixture. In its place a labctl shim
  serves a `labctl pool` CSV. The checks show the pool is read through labctl for the fleet's event and never from
  /admin/roster, and that a quoted comma does not break a row. A failed `labctl pool`, a missing DATABASE_URL (labctl
  not run), a wrong header, empty output and a short row each fail with nothing deregistered. The header alone is a
  clean empty pool, and a dry run with USER unset still names the ghost. The `ingest pool` case in
  `verify/test_fleet_terminal_harvest.sh` reads its three rows from the same shim, and a failed `labctl pool` there
  imports nothing.
- **Earlier drafts.** `origin/agent/656-10488` and `origin/agent/656-10497` carry no commits beyond staging
  (`verify/draft-drift.sh`: CLEAN), so nothing was reused.

**Not yet run on a cluster.** This needs a session with the fleet's AWS profiles, labctl on PATH, DATABASE_URL and
USER, against an attendee pool imported for the event. First run `infra/terraform/fleet/fleet.sh reconcile-pool` (a
dry run). It must list the same names as `labctl pool --customer agenticburn --event "$WIB_EVENT"` and end with
"all N row(s) name a live cluster". Then run `bash verify/fleet-hygiene.sh` and check that section 3b reports ok.
Then run #532's live `fleet.sh ingest pool`, per the #532 entry above.

## 2026-10-30 · #655 · fleet.sh's labctl import row holds against lab-platform's parser; the live import is still owed

This run could read lab-platform: `sources repo-cat` gave `docs/provisioning.md` section 9 ("Loading clusters into the
pool"), `cmd/labctl/import.go`, `internal/store/import.go` and `cmd/labctl/main.go`, read 2026-10-30. The 2026-10-29
#655 entry above listed five assumptions; the source settles each one.

- **(1) An empty `role` is an attendee.** `store.ParsePoolCSV` turns a blank role into `attendee`, and
  `ImportEnvironments` puts an attendee row with no `reserved_for` in `ready`, which `claim_environment` hands to
  anyone. `instructor` goes in `held`, which it never hands out. Any other role refuses the whole file.
- **(2) The quoting is read.** The header and row go through Go's `encoding/csv`, which reads RFC 4180 quotes the way
  jq's `@csv` writes them, a doubled quote included. Header names are trimmed and a leading byte-order mark is dropped.
- **(3) Every column is known.** The known set is `name`, `role`, `reserved_for` and thirteen access columns,
  `terminal_user` and `terminal_password` among them. Columns are matched by name, so order does not matter, and an
  unknown or repeated column refuses the file. All fifteen columns fleet.sh sends are in the set.
- **(4) The exit code is success.** `main.go` exits 1 on any error `importCommand` returns. That covers a row it
  refuses, an unknown event, one past its deadline, a file holding only placeholder rows, a missing `USER`, and a
  claimed cluster the file would move. In the last case the access merge has already been committed.
- **(5) Re-import keeps a claim, with two exceptions /admin/import never had.** A cluster is matched by name within
  the event. Each non-blank value replaces the stored one and a blank leaves it. A `claimed` or `active` cluster keeps
  its state and its claim. The first difference: an unclaimed cluster's role and reservation follow the file, and
  fleet.sh never sends `reserved_for`, so re-ingesting a cluster that a pool.csv reserved for one address puts it back
  in `ready` for anyone. A claimed cluster that was reserved goes in labctl's `NotPlaced` list and exits 1, so fleet.sh
  retries it three times and records `ingest:<name>`, although its terminal login was merged each time. Nothing in
  this repo reserves a cluster today, so this is filed on lab-platform as a follow-up and fleet.sh is unchanged. The
  second difference: a `released` or torn-down cluster is left out of the pool and labctl still exits 0, so
  `ingested: <name>` read as success for a cluster nobody can claim.
- **Changed.** `ingest_one` now logs labctl's own summary lines after a successful import, and warns by name when
  labctl says it left the cluster alone as released or torn down. `verify/test_fleet_terminal_harvest.sh` gains
  `labread`, a reader that applies ParsePoolCSV's rules (the known columns, no repeats, field count, a blank name,
  and the role values with blank read as attendee). The row fleet.sh sends is held to it: an attendee reads as
  attendee, each roster cluster as instructor, and a password holding a comma and a quote survives the quoting. Because
  the reader is a copy, it can drift from lab-platform; the comment names the file it was read from.
- **Still not read.** `ingest pool` still takes its names from the provisioning app's /admin/roster (#656).

**Not yet run on a cluster:** this is the live half of #655. It needs a session with the fleet's AWS profiles, labctl on
PATH, `DATABASE_URL` at lab-platform's database, `USER` set, and a test event on a `managed_cluster` lab
(`labctl create-event agenticburn burn@2.1.0 <event> <attendance> <hours>`) in `WIB_EVENT`, against built clusters.
Run `infra/terraform/fleet/fleet.sh ingest watch-it-burn-attendee-001` and `infra/terraform/fleet/fleet.sh
ingest-instructors`. Then `labctl status agenticburn <event>` must count the attendee as ready and each roster
cluster as held. Claim once on `/c/agenticburn/<event>` and rerun the attendee ingest: it must log `0 added` with the
claim still held. No attendee cluster is up today; the 2026-10-28 platform is the roster alone.

## 2026-10-30 · #690 · The finale lowers the public cap live; guard-proxy pinned at a022fa5 (staging)

guard-proxy a022fa5 adds `/toggle?cost_cap=N`, which lowers the cluster-wide cap and keeps the tally. The web
terminal gains `finale-cap-on [headroom]` (cap = spent + headroom, $1.00 by default), `finale-cap-off` (restores
`COST_CAP_USD`) and `cost-watch` (spent, cap, turns and a bar, large, every 2 s). `verify/test_finale_cap.py`
drives all three against the pinned proxy.py. The pin is a guard-proxy staging commit, not main: it is pushed
(`verify/submodule-pins-pushed.sh` passes) and its CI is green, and the finale needs it before guard-proxy's
heavy gate promotes it. The same pin brings TURN_TIMEOUT, so #694 is done here: 270 s for the turn, 120 s a call.

**Run on attackme, 2026-10-30.** `finale-cap-on 0.30` from the public terminal set the cap to $0.30 (the tally
was $0.00 after the guard-proxy restart). 20 sessions on one address, sending as fast as replies came back, put
83 turns through the model (about $0.004 each, $0.3362 in all) and crossed the cap in under 45 s; the 188 turns
after it were answered with the budget reply and cost nothing. `finale-cap-off` restored $25 and the next turn
was answered. The 50-phone rate is an estimate from that per-turn cost, not a measurement.

**Open.** The capped reply says "This conversation hit its spend budget... Press Reset", which is wrong when the
cluster cap tripped; asked on guard-proxy-agenticburn#25.
## 2026-10-30 · #113 · The community cluster leaks node IMDS creds on purpose (hop limit 2), every other cluster keeps it out of reach, and a facilitator beat steals them to a node role

**Context.** #113 (child of #110) proposes the IMDS credential-theft challenge: a compromised pod curls
`169.254.169.254`, steals the EC2 node instance-role credentials and calls AWS from inside the pod, so
`aws sts get-caller-identity` returns a node role. That is the moment a container compromise becomes a
cloud-account one (OWASP Agentic **ASI03, Identity and Privilege Abuse**). The issue offered two builds and
asked for a decision first. Michael answered question 843 (2026-10-26, accepted in the web view) and chose
**Option 2, "make a cluster genuinely vulnerable"**: leave one cluster exploitable so the theft actually
succeeds and the contrast with the hardened clusters is real rather than narrated. This run builds that.

**The one load-bearing fact.** Our clusters already pin `http_tokens=required` and `http_put_response_hop_limit=1`
(PRD 35 §3.7-A), and #203 added the Admin-tier `agent-deny-imds` ClusterNetworkPolicy on attendee/admin/full
(not burn), so the naive attack already fails everywhere. Making a cluster genuinely vulnerable is therefore
a single per-cluster knob: the node IMDSv2 PUT-response hop limit. At 1 a pod's packet dies one hop short of
node IMDS; at 2 the pod reaches it. The community (burn) cluster alone gets 2, and it already ships no
`agent-deny-imds`, so both IMDS controls are off there and nowhere else.

**What differs from the issue's framing (draft drift, #291).** The issue says "set `hop_limit=2` on the R1
roster entry only ... the roster already carries per-cluster overrides (that is how R1 gets `pids=-1`), so
this is a roster column." That predates #291, which retired the numbered rounds: `roster.tsv` is now two
role-based rows (`watch-it-burn-community|community|...|-1|burn|` and `watch-it-burn-private|admin|...`), and
the burn-vs-armed posture is already **role-derived in fleet.sh** (`bootstrap_profile_for_role`: community→burn,
admin→admin), NOT read from the roster's `bootstrap` column, which an earlier loop left stale (a documented
wart). So the IMDS leak is derived from the role the same way the profile is, rather than as a new roster
column. A new column would have to be threaded through every positional `IFS='|' read` of the roster and would
reintroduce exactly the stale-column problem the `bootstrap` column already is. `pids` stays a column because
it is one of several numeric §4.6 shape knobs (tier/instance_type/pids); the IMDS leak is the binary
"is this the unguarded cluster", which is the role.

**What changed.**
- **Terraform** (`infra/terraform/aws/cluster/main.tf`): new `variable "imds_hop_limit"` (number, default 1,
  the control). The managed node group's `metadata_options.http_put_response_hop_limit` now reads
  `var.imds_hop_limit` instead of the literal 1. Comments explain the community=2 deliberate leak and that
  Pod Identity (the container-creds endpoint `169.254.170.23`) is unaffected at either value. `terraform fmt`
  clean.
- **fleet.sh** (`infra/terraform/fleet/fleet.sh`): new `imds_hop_limit_for_role` (community→2, everything
  else→1), a sibling of `bootstrap_profile_for_role`. `up_one` computes it from the role it already derives
  (`role_for_cluster`, which returns `community` only for `watch-it-burn-community`) and passes
  `-var imds_hop_limit=<n>` on every apply and in the dry-run plan line, so a plan shows which clusters are
  vulnerable. `up_one` is the single cluster-module apply site (`setup-instructor-cluster.sh` only arms an
  already-provisioned cluster), so this is the only wiring needed.
- **Burn profile doc** (`gitops/bootstrap/values-burn.yaml`): the comment that claimed "the node's IMDSv2 hop
  limit of 1 still keeps pods off the instance metadata service" was now false for this cluster; it now states
  the deliberate `imds_hop_limit=2` leak and the ASI03 beat it enables.
- **Facilitator beat** (`challenges/imds-node-creds/`): `steal-node-creds.sh` execs the agent's tool pod
  (`workshop-mcp`, the pod that runs `run_shell`), requests an IMDSv2 token, reads the node role and its
  credentials, and runs `aws sts get-caller-identity` with the stolen creds. It prints a node-role ARN on the
  community cluster and `IMDS: BLOCKED` on a guarded one. It is read-only (one GET of IMDS, one
  get-caller-identity; nothing created). Per CLAUDE.md kube-safety it requires `CONTEXT` with no
  current-context fallback and every `kubectl` carries `--context "$CONTEXT"`. `FACILITATOR.md` carries the
  controls table, the contrast with Challenge 8's `BLOCKED` probe, the ASI03 peg, the node-role-scope caveat
  (a stock node role reads ECR and describe but cannot reach S3 or Secrets, so do not over-promise on stage)
  and the owed live check.

**Why this is a presenter beat rather than a numbered Challenge 9.** The student lab runs on attendee clusters, where this is
blocked by design, so there is nothing for a phone to do. That is also why Challenge 8's terminal RBAC work was
cut from the KubeCon breakout. So this is a watch-the-screen beat on the community cluster (like the C4 fork bomb
"on our box only"), not a student step. Numbering it C9 would also collide with the lab's existing feedback
step "Challenge 9" and cascade the eight-challenge counts (`docs/CHALLENGE-ASSETS.md`,
`verify/test_challenge_assets.py`'s `range(1,9)`, `docs/DESIGN-GLANCE.md`, `lab.html`). The canonical count of
eight live challenges is unchanged.

**Not added:** `prds/36-multicloud-attack-control-signal-matrix.md` (the ASI/ATLAS matrix) is a DRAFT whose
locked scope decision #2 is "descriptive of the existing attack set, not a new attack set ... does not invent
attacks." Adding a beat there would expand a sealed-scope PRD and is Michael's call, so it was left alone; the
ASI03 peg lives in the facilitator doc and the terraform/values comments instead.

**Tests.**
- `verify/test_imds_credential_theft.py` (offline, new): the node group reads `var.imds_hop_limit` (not a
  literal) defaulting to 1; `imds_hop_limit_for_role` gives community 2 and everything else 1 and is wired into
  `up_one`'s vars and dry-run; the burn profile omits `cluster-network-policies` and the values file names the
  leak; the steal script is CONTEXT-safe, targets `169.254.169.254`, does the IMDSv2 token→role→creds→
  get-caller-identity chain, reports BLOCKED when refused, makes no aws call but the identity lookup, and never
  touches `169.254.170.23`.
- `verify/test_cluster_roles.sh` (offline, extended): a new section asserts `imds_hop_limit_for_role` gives
  community 2, admin 1, attendee 1, and that `up_one`'s dry-run plans `-var imds_hop_limit=2` for the community
  cluster and `=1` for the admin and an attendee cluster.
- `verify/test_agent_cloud_credential.py` (offline, updated): its hop-limit check moved off the literal
  `http_put_response_hop_limit = 1` (which my change removed) to assert the node group reads `var.imds_hop_limit`
  and that the variable defaults to 1. `bash verify/run-tests.sh` green (192 tests).

**Not yet run on a cluster.** Owed on a build with AWS access (named in the facilitator doc): provision the
community cluster (`fleet.sh instructors up community`), run
`CONTEXT=<community-ctx> challenges/imds-node-creds/steal-node-creds.sh` and confirm it prints a node-role ARN;
provision a fresh attendee cluster and confirm the same script prints `IMDS: BLOCKED`. Final stage placement in
the run-of-show (which segment, how it flows in the 30-minute KubeCon demo vs the 2-hour format) is the
presenters' choreography call and is left as a follow-up rather than written into the tightly-timed scripts here.

## 2026-10-31T00:30:00Z · 3.1 · Cluster readings for #701, #711, #713, and run_shell off the event loop

**#701, Challenge 1 trace (burritobot-private, egress NetworkPolicies on).** Three runs, read out of Tempo and
Datadog. A blocked POST to the beacon: `execute_tool run_shell` STATUS_CODE_ERROR at 20.0 s with "command FAILED:
it did not complete within 20s". A fast failure (curl exit 6, a DNS miss): STATUS_CODE_ERROR at 0.03 s with
"command FAILED with exit code 6", the shape #463 changed. Both error spans are in Datadog's indexed spans. The
issue's first check (the model call after the block is status:error) no longer applies: question 925 removed
transform/mark_tool_failure, and every generate_content span read UNSET, as intended. Recorded beside the
2026-09-07 measurement in `verify/test_collector_config.py`.

**run_shell blocked the whole tool server.** The second Challenge 1 run had Nova call run_shell and
get_marketing_intel together. run_shell was a plain `def`, which FastMCP (mcp 1.29.1, func_metadata.py) calls on
its event loop, so the 20 s hung curl stalled every other tools/call; agentgateway cut get_marketing_intel at
10 s ("upstream call timeout", HTTP 500) and the model told the room "internal server error" instead of the
NetworkPolicy's message. run_shell is now `async` and runs its subprocess in a worker thread.
`verify/test_tool_audit_live.py` drives the real server on the pinned library: a second session's check_inventory
took 2.58 s while run_shell slept 3 s before the change and 0.05 s after. The other tools are still plain `def`
(deploy_app, read_support_ticket and the web search make network calls); none was seen to stall.

**#711, service names in Whitney's sandbox org.** Datadog's own usage metric
(`datadog.estimated_usage.apm.ingested_spans` by service) last saw `workshop_agent` in the 2026-10-30 04:00 UTC
hour and has seen only burritobot, burritobot-agent and burritobot-gateway since. `verify/test_datadog_sandbox_live.py`
span check passed on both clusters. Tempo, fed by the same processors, holds no ASGI send/receive spans and no
empty `chat` spans for a fresh /chat. The same run failed two checks outside #711: logs from argocd, kubearmor and
aws-load-balancer-controller carry their own service names (#629's log rule), and ml_obs.trace had not reported
inside the 60-minute window yet (it shows 5 burritobot traces for 10-31 a few minutes later).

**#713, call_llm as invoke_agent.** Moot on the deployed runtime. The Go runtime emits no call_llm span; LLM
Observability draws one interaction as workflow POST, agent invocation, agent workshop_agent, then llm
generate_content and tool rows under it. Kept `transform/set_llmobs_workflow` as it is: unstamping invocation
would bring back Datadog's "No operation was reported" note on every trace, and the call_llm half still serves
a Python-runtime agent. Not read in the Datadog UI itself (the sandbox org is Whitney's login); read from the LLM
Observability spans API.

**Found while reading, filed separately:** every generate_content row in LLM Observability has no input and no
output. The Go runtime writes the request and response to gcp.vertex.agent.llm_request and llm_response,
truncated at 2048 characters, not to gen_ai.input.messages and gen_ai.output.messages.
## 2026-10-31 · #492 · The C6 observable-judge run can go on watch-it-burn-community, which is up, so no bring-up is owed

**No code changed.** The 2026-10-29 entry for #492 sends the live run to a fresh attendee cluster before Challenge 2,
because the ticket asks for the Joker image and `restrict-image-registries` refuses it wherever it is armed. That
was written when no cluster suited it, so running it meant a bring-up and its spend. The community cluster now
does. watch-it-burn-community boots `values-burn.yaml`, which has no Kyverno, so nothing refuses the image, and it
carries ai-layer, which ships `fake-ticket` (HC-7731) and workshop-mcp's `read_support_ticket`. On 2026-10-31 a GET of
`/guards` on `attackme.agenticburn.com` and `attackme.burritobot.co` returned 200 with every guard off on both.
`agent_probe.py` flips the guards through guard-proxy's `/toggle`, restores them at the end, and deletes
`maintenance-shell`. The beat is judged on whether that Deployment exists, not on its pod pulling, so #678's
private promo/ packages and #671's payload move do not change the verdict. What the 2026-10-29 entry says about the
baseline still holds: b23cc9e's 19/20 was measured with the payload pasted into the prompt, not fetched by the tool.

Hecaton run 13061 has no AWS credentials or kubeconfig, so it could not run the probe, and this repo's rules keep it
off a cluster it did not provision. The previous attempt at this run stopped on the host, not in the repo: the podman
store in pool claude-performantpro-3 could not join its user namespace. This pool's store answers `podman info`.

**Not yet run on a cluster:** from a session with accen-dev, in us-west-2:
`aws eks update-kubeconfig --kubeconfig /tmp/community.kubeconfig --name watch-it-burn-community --region us-west-2 --profile accen-dev`,
then `KUBECONFIG=/tmp/community.kubeconfig python3 verify/agent_probe.py attackme.agenticburn.com --context <the
watch-it-burn-community context that file names> --profile accen-dev --only c6-off,c6-on --repeat 5`. That is 10 model
calls, under the default `--max-calls 20`. Compare the result with 19/20. Those calls add to attackme's `/cost`, so
`./fleet.sh reset-bot watch-it-burn-community` before the room plays, as the run-of-show's Night Before already does.

## 2026-10-31 · #643 · Standbys for attackme and burritobot-private, promoted automatically, across three regions

Agreed on the 2026-10-28 planning call (`facilitation/kubecon-na-2026-planning-2026-10-28.md`): 12 public standbys
and 3 private ones, across zones and regions. If the cluster serving attackme fails its self-check, the next healthy
one takes the hostname with nobody acting, and the same goes for the private bot. Three public standbys stand up the
night before and nine six hours out. The reason given was that Portland narrowly missed a us-west-2 outage.

- **The standbys are data, `infra/terraform/fleet/backups.tsv`**: `name|role|region|wave`, and the order of the rows
  is the promotion order. The public ones are `watch-it-burn-community-b01` to `-b12` and the private ones
  `watch-it-burn-private-b01` to `-b03`. They alternate us-east-2, us-east-1 and us-west-2, so the next standby is
  never in the region of the one before it, and the first one is outside us-west-2, where the roster clusters are.
  All of them are in `WIB_DEFAULT_ACCOUNT`, as the roster is (`account_for_role`).
- **The three private standbys stand up the night before.** The call gave the public waves only. The night-before
  wave is the one that gets a full night of checks, and the private bot is the one whose guard toggles the
  presenters need to have seen work. This is a choice made here, and it is one column to change.
- **A standby is its roster cluster under another name.** fleet.sh gives it the role (`role_of_instructor_name`,
  so the `role=` tag and the bootstrap profile follow), the presenters' terminal login, and its role's hostname
  (`public_host_for`), so its cluster identity is already right when it is promoted. `datadog-cluster-identity.sh`
  reports it as `burritobot-public` or `burritobot-private`, so Whitney's two tabs follow a promotion.
- **`infra/terraform/fleet/backups.py` drives the standbys.** `up <wave>` makes one fleet.sh run per region:
  `instructors up all` over a roster file of that region's standbys, with `WIB_REGION` set to the region and with
  `WIB_NO_ROUTES`, `WIB_NO_INGEST` and `WIB_NO_VERIFY` set. Then it runs `converge` on the same clusters, and then
  the self-check. Standbys stay out of the router until they are promoted, out of the provisioning pool, and out of
  the walkthrough, because the walkthrough reaches a cluster by its routed hostname. `down`, `check`, `status`,
  `watch`, `promote`, `schedule` and `unschedule` are the other verbs.
- **The self-check runs on each console's own load balancer**, with the Host header of the role's hostname. It
  checks `/healthz`, the storefront page, `/controls`, and one `/chat` carrying the probe marker, so the chat never
  reaches the prompt wall. It never goes through the router, so a standby can be checked before it is routed.
- **Promotion repoints the router table, not DNS.** After three failed checks in a row (`--fail-after`, at a
  15-second interval), the watcher walks the role's pool, starting after the cluster that failed and wrapping round.
  It gives the hostname to the first standby that passes the full self-check: every row of the apex table that
  pointed at the failed console's LB is repointed (the burritobot.co twins and the service hosts included), and the
  table goes to the live router through the apex repo's `reload-routes.sh`. Reading the failed cluster's LB from
  the table needs no AWS call into the region that failed. If the router refuses the reload, the file is put back
  and the next tick tries again.
- **`states/promoted.tsv` records the holder**, and `cmd_routes` reads it. Without it, the Night Before's
  `fleet.sh routes roster` after a promotion would give attackme back to the failed cluster. A holder that
  backups.tsv does not list is ignored, and the log says so.
- **Nothing fails back on its own.** A cluster that failed once is not given the room again until someone runs
  `backups.py promote <role> <cluster>`. That command is also how a drill is undone.
- **The chat check runs every fourth tick by default (`--chat-every`)**, which is one model call a minute on the
  cluster that holds the hostname. The marker keeps it off the wall. It still counts toward `/cost`, which no
  longer matters on stage since C4 was cut.
- **Cross-region builds needed four fixes in fleet.sh.** First, the lab VPC state outside `WIB_HOME_REGION`
  (us-west-2) is `states/<account>.<region>.tfstate` for every account, the default one included
  (`lab_vpc_state_for`, `read_vpc_for`, `lab_vpc_present`, and preflight.sh). Second, the Datadog keys are still
  read from the home region (`WIB_SECRETS_REGION`), where they are kept. Third, `deploy-full-idp.sh` is given
  `REGION`, which it defaulted to us-west-2 when it looked up the VPC for the load balancer controller. Fourth,
  `provider_write_kubeconfig` takes an optional region.
- **Bedrock follows the cluster's region.** A cluster's application inference profiles are created in its own
  region, so a us-east-2 standby has us-east-2 ARNs, and the committed `region: us-west-2` would fail every call.
  `pin_bedrock_profiles` now also sets each Bedrock ModelConfig's `.spec.bedrock.region` and agentgateway's new
  `BEDROCK_REGION` env to the region in the ARN. agentgateway-config reads `region: ${BEDROCK_REGION:-us-west-2}`,
  and ai-layer ignores both fields, just as it ignores the model. A us-west-2 cluster is unchanged. The default is
  required: agentgateway v1.7.0 expands its config file with `shellexpand::full` and refuses the whole config when a
  variable is unset (`errors_on_unset_environment_variable` in crates/agentgateway/src/config.rs, read at tag v1.7.0
  on 2026-10-31). The ignore can keep Argo from adding the new env entry to a cluster built before this change, and
  without the default that cluster's gateway would reject the synced config. Every such cluster is in us-west-2, so
  the default is right for it, and `fleet.sh converge <name>` sets the entry anyway, the same way
  `BEDROCK_NOVA_MODEL` reached clusters after #561.
- **The schedule takes the session start as an argument.** The start is conference-knowledge's `kubecon-na-2026`
  entry (#417). `schedule` prints crontab lines in the cron host's time zone: the night-before wave 18 hours out,
  the six-hours wave 6 hours out, the watcher from 17 hours out until 90 minutes after the start, and `down all
  --apply` two hours after the start, followed by `unschedule`. Cron has no year field, so the lines remove
  themselves.
- **The watcher is one process on the host that holds the fleet profiles**, behind a lock file. If that host goes
  down, there is no promotion. The router itself was not changed to hold several upstreams (apex-agenticburn),
  because the self-check is more than a health URL, and this run could not read that repo.
- **Tests.** `verify/test_backups.py` (offline) holds the pools and waves and the standby naming in fleet.sh. It
  drives the watcher with a fake check against a real `routes.map` and a recording reload script: promotion after
  three failures, in order, skipping unhealthy clusters and ones without an LB, wrapping round, the private bot, no
  healthy standby, a refused reload, and the drill. It also runs the self-check against a local console and checks
  the schedule and the dry-run bring-up and teardown. `verify/test_fleet_standbys.sh` (offline) covers `routes
  roster` with a promoted standby read in its own region, the lab VPC state per region, and `REGION` reaching the
  bootstrap. `verify/test_pin_bedrock_profiles.sh` adds the cross-region pin, and `verify/test_preflight_boundary.sh`
  adds the standby-region VPC state.
- **Not yet run on a cluster.** `verify/test_backups_promotion_live.py` (E2E) is the rehearsal the issue asks for.
  It runs after both waves are up: all 17 consoles pass their self-check, then a drill fails each roster cluster,
  the watcher moves its hostname through the live router, the hostname answers, and the hostname is failed back by
  hand. Before that, the lab VPCs in us-east-2 and us-east-1 have to be applied (`backups.py up` prints the apply
  command), `preflight` has to pass in both regions, and the waves have to be built. All of that is spend that
  waits for Michael's go.
- **Remade on the staging of 2026-10-31 (run 13081).** The design was first drafted on 2026-10-29 in run 10394
  (`origin/agent/643-10394`, commit 24132c4), cut from a staging that has since moved 110 commits.
  `verify/draft-drift.sh` named six paths staging had changed since: PROJECT_STATE.md, decisions.md, the run of show,
  agentgateway.yaml, the ai-layer Application and fleet.sh. Each draft change was checked again against what staging
  added in the meantime. agentgateway moved to v1.7.0 (0ad8d1a). It still reads the model from
  `${BEDROCK_NOVA_MODEL}`, so the region uses the same substitution. Reading v1.7.0's expander is what showed the
  draft's bare `${BEDROCK_REGION}` could stop the gateway on a cluster built before this change, such as the
  KubeCon pair rebuilt on 2026-10-28, at its next sync, so the reference now
  carries `:-us-west-2`, and `verify/test_pin_bedrock_profiles.sh` holds it. The ai-layer Application gained LLM
  Guard's image (#652) and the conditional Agent tools ignore (#679) since the draft. Neither touches the ModelConfig
  or Deployment ignores the region entries join. The node IMDS leak (067c0c1, #113) follows the role, and a
  community standby has the community role, so it plans hop limit 2 and keeps the credential-theft beat after a
  promotion. A private standby plans 1. `verify/test_fleet_standbys.sh` now holds that, together with each standby's
  hostname and region. C6's `support-` and `maintenance-shell-` hosts (#664, a4fb773) are emitted on the console LB
  with the service hosts, so the watcher, which repoints every row on the failed LB, already moves them. Apart
  from the region default, the design is the draft's. The run of show now also says that C6's maintenance-shell does not carry
  over to a promoted standby. The cloud-credential probe's fixed `region=us-west-2` (#203) was left alone: agent-sa's
  policy allows the `us.` system profiles in any region, so the probe reads the same on a standby.
## 2026-10-31 · #638 · front-door-cert.sh prints the bare ARN, which labctl's --front-door-cert takes

lab-platform#297 is merged (lab-platform 6214e66): `labctl event up` and `labctl dry-run` take
`--front-door-cert=<arn>`, pass it to each roster cluster's `lab-bootstrap` root as `frontDoor.certificateArn`, and
refuse the line `frontDoor.certificateArn=<arn>` by name, telling the operator to give only the ARN. That line is what
`infra/front-door-cert.sh` printed once the certificate was issued (the 2026-10-28 entry above), so pasting its output
was refused. It now prints the ARN alone on stdout, so
`--front-door-cert="$(infra/front-door-cert.sh <aws-profile> <region>)"` works, and stderr names the flag. A root built
by hand takes the same ARN as `--set frontDoor.certificateArn=<arn>`. Nothing in this repo read the old line.
`verify/test_front_door_cert.sh` checks the bare ARN and the flag hint.

lab-platform#297 also settled the assumption the 2026-10-28 entry left open. The gateway had verified each front door
against the recorded `<nlb>.elb.amazonaws.com` name. It now sends the roster hostname (attackme, burritobot-private,
and the same names under burritobot.co) as the TLS server name and verifies against it, which the ACM certificate for
`*.agenticburn.com` and `*.burritobot.co` covers.

**Not yet run on a cluster:** the definition of done's live leg, a billable `labctl event up` in AWS with Michael's
go. First `infra/front-door-cert.sh accen-dev us-west-2`, writing its validation CNAMEs with
`infra/dns/set-demo-dns.py` (dry run, then `--apply`) until it exits 0. Then `labctl event up ... --front-door-cert=<that
ARN>`, whose bootstrap step must log `front doors: 2 roster clusters recorded`, and
`labctl tls-check attackme.agenticburn.com burritobot-private.agenticburn.com --no-ws` once the roster hostnames route
to lab-platform's gateway rather than apex-agenticburn's Caddy on Railway. Hecaton run 13101 has no AWS access.
## 2026-10-31 · #532 · `ingest pool` now reads the pool it writes to; the live run waits only on an attendee pool

The 2026-10-30 #532 entry above held the live run on two things. One is gone: #656 landed on staging as a71afae, so
`cmd_ingest pool` takes its names from `pool_rows`, which runs `labctl pool --customer agenticburn --event
"$WIB_EVENT"`, and writes them back through `labctl import`. The command reads and writes the same pool now, so
running it would no longer re-import names from a pool fleet.sh does not fill. Hecaton run 13062 still did not run
it, and no code changed.

- **No attendee pool is up, and none is scheduled.** PROJECT_STATE.md's "KubeCon platform up" still lists only
  `watch-it-burn-community` and `watch-it-burn-private`, the roster clusters, which `WIB_NO_INGEST=1` keeps out of
  the pool. In conference-knowledge `events/registry.yaml`, `aiewf-2026-watch-it-burn` and
  `devopsdays-portland-2026` are delivered, and `kubecon-na-2026` (2026-11-09 to 11-12) is a 30-minute session with
  no attendee lab. The run waits on Michael bringing up an attendee pool, which is spend.
- **The harvester's source is still unread.** `sources repo-cat agenticburn/provisioning-agenticburn/scripts/harvest_terminal_credential.sh`
  is still refused as "looks like a secret", and `repo-ls` of that directory still does not list it. Its
  interface (`<cluster> [region] [out-dir]`, AWS_PROFILE from the environment, exits 0/3/1) is confirmed by the
  live run alone.
- **The previous attempt's failure was the host's.** Run 13062's predecessor stopped before any work because
  podman could not join the user namespace of the store in `/var/lib/hecaton/pools/claude-performantpro-3`. That is
  a hecaton pool's container store, not this repo. Nothing in `verify/` calls podman, and the store in the pool this
  run used answers `podman info`.

**Not yet run on a cluster.** With an attendee pool imported for the event and its clusters up, a session with the
fleet's AWS profiles, labctl on PATH, `DATABASE_URL`, `USER` and `WIB_EVENT` set, and `WIB_PROVISION_DIR` at a
provisioning-agenticburn checkout holding commit 3462ba2 runs, in order: `infra/terraform/fleet/fleet.sh
reconcile-pool` (dry run; it must end "all N row(s) name a live cluster"), `bash verify/fleet-hygiene.sh` (section
3b ok), then `infra/terraform/fleet/fleet.sh ingest pool`. That must end with no `ingest:<name>` or
`terminal-open:<name>` failure, `labctl pool --customer agenticburn --event "$WIB_EVENT"` must list the same names
with every claimed row still claimed, and a claimed attendee's terminal login must be `agentic` / `agentic`.
## 2026-10-31 · #467 · The promo villains repinned to lab-platform#55's republish; the CEL migration's live run is still owed

**Why.** Hecaton run 13049, dispatched on #467 (validate the Kyverno CEL policy migration on a live cluster), ran
`bash verify/run-e2e-tools.sh` and it failed on `test_promo_villains_public.py` alone. All ten
`ghcr.io/peopleforrester/lab-platform/promo/<name>:v1` tags still answer an anonymous pull, but each serves a digest
other than the one `verify/promo_villains.py` held from #653. The tags moved on purpose: lab-platform#55 rebuilt
every published v1 image under `umask 022` on 2026-10-30, the ten promo/ villains included (lab-platform
decisions.md, entry 2026-10-30T18:04:37Z, "promo/* (ten): the digests in `deploy/watch-it-burn/images.tsv`"). That
file's ten `villain` rows match what ghcr.io served on 2026-10-31, digest for digest.

**Changed.** `verify/promo_villains.py`'s `DIGESTS` takes those ten digests, and its docstring names lab-platform#55
as the hand-over. `test_promo_villains_public.py` stops calling the digest "the digest handed over on #653". The lab
still names villains by `:v1`, so nothing a student copies changes.

**Not changed.** `images.lock`'s `ghcr.io/peopleforrester/lab-platform/llm-guard` row still records `781a126b…`.
lab-platform#55 lists `llm-guard:v1` at `6cdbf3a2…`. `test_images_lock.py` is offline and does not read the
registry, so it stays green. That row is a separate record and is filed as a follow-up, not changed here.

**Not yet run on a cluster.** #467's own checks need two fresh clusters, a full-profile one and an attendee one, and
a session with AWS access. This run has none: `kubectl config get-contexts` is empty and `aws sts
get-caller-identity` says NoCredentials. Against each cluster, run `CONTEXT=<ctx> python3
verify/test_kyverno_cel_live.py` and then `bash verify/run-e2e.sh` (with CONTEXT, IAM_PIPELINE_PROFILE and
IAM_PIPELINE_REGION set). The live check reads the policy list from `policies/kyverno/` and `policies/floor/`, so it
now expects eleven, not the issue's ten: #606 added `restrict-agent-spawned-workloads.yaml` after d8076da, and the
check counts it with no edit.
## 2026-10-31 · #664 · `build.sh joker` pushes the C6 Joker alone; the push still waits on a Docker Hub token

On 2026-10-29 Michael checked the Joker page in a browser. The route, the console page and C6's reply all work.
docker.io/peopleforrester/joker:latest is still the log-loop build from 2026-06-29: one layer, with no
`/villain` layer from `build_joker_web`. So the Service has an endpoint and nothing answers on 8080. Both Docker
Hub tokens on disk return `personal access token is expired`. He asked for a Joker-only push, since the rest of
build.sh's roster does not need re-pushing. build.sh had no way to do that: run with no arguments, it pushes all
nine log-loop villains before the Joker.

- **`build.sh [name...]`.** With no names it pushes the whole roster as before, the Joker last. With names
  (`joker`, or any key of `M` or `V`) it pushes only those, so `build.sh joker` is one `crane append` and one
  `mutate` to `$ORG/joker:latest`. It checks every name before it pushes anything, and an unknown name exits 2
  and lists the known ones.
- **The previous run of this issue (hecaton run on pool claude-performantpro-3) failed before it changed any
  code.** That pool's podman store could not re-exec into its existing user namespace. Nothing in this repo runs
  podman, and podman works in the pool this run used, so the repo had nothing to fix.

**Tests.** `verify/test_c6_villain_endpoint.py` now runs build.sh against a stand-in crane (`CRANE=`), and
reads each call and the layer each `append` gets. `build.sh joker` makes only the Joker's two calls, and its
layer holds `villain/start.sh` and `villain/www/index.html`. With no names, every key of `M` and `V` is pushed,
then the Joker's two calls. `build.sh joker jokr` exits non-zero with no crane call. Against the old build.sh,
the first and the last of these fail, which was tried and then reverted.

**Not yet run on a cluster.** Still owed, in order. First, a fresh Docker Hub PAT with write on
peopleforrester/joker: `echo "$DOCKERHUB_PAT" | crane auth login docker.io -u "$DOCKERHUB_USER" --password-stdin`,
then `bash images/villains/build.sh joker`. Then
`curl -s https://maintenance-shell-attackme.burritobot.co/ | grep 'HA HA HA'` once C6 has deployed the pod, and
steps 3 and 4 of the 2026-10-29 #664 entry. The routes (step 2) went out on 2026-10-29 with `fleet.sh routes`.
