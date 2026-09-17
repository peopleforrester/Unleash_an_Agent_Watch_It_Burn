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
