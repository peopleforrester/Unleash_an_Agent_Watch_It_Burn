# Repo working rules (read first)

## Kube-context safety (CRITICAL: other Claude Codes may be managing other clusters)

Concurrent Claude Code sessions may be operating other Kubernetes clusters on this box. Never touch
global kube state. Be explicit about the target cluster on every single command.

**Rules, no exceptions:**

1. **Every `kubectl` call carries an explicit `--context "$CONTEXT"`** (or runs with a per-command
   `KUBECONFIG=<isolated-file>` prefix). Never rely on the global current-context.
2. **Never run `kubectl config use-context`** or `kubectl config set-context` against the shared
   `~/.kube/config`. That mutates state every other process and Claude Code sees.
3. **Never `export KUBECONFIG`** into the environment as a shared default. If you need a kubeconfig,
   pass it per command: `KUBECONFIG="$KCFG" kubectl --context "$CONTEXT" ...`.
4. **`eksctl` must not clobber the shared kubeconfig.** Always pass
   `--kubeconfig <isolated-path> --set-kubeconfig-context=false` on `create`/`delete`/`utils
   write-kubeconfig`, so it never rewrites `~/.kube/config` or flips the current-context.
5. **Scripts take the context explicitly.** The verify harness (`verify/*.sh`) already takes a
   `<kube-context>` arg; the demo toggle/fallback scripts read a required `CONTEXT` env. A script that
   cannot determine its target context must fail loudly, never fall back to the current-context.
6. **AWS profiles too:** pass `--region` and `AWS_PROFILE` explicitly (per command), do not depend on
   a shared default region/profile that another session may have changed.
7. **Pull creds into an isolated file:** `aws eks update-kubeconfig --kubeconfig /tmp/<cluster>.kubeconfig
   --name <cluster> --region <r>`. Never let it write `~/.kube/config`.
8. **Verify before every mutation:** confirm `KUBECONFIG=<file> kubectl config current-context` matches
   the cluster you provisioned; if it does not match, STOP. Prefer a guarded one-liner:
   `KUBECONFIG=/tmp/x.kubeconfig AWS_PROFILE=p kubectl config current-context | grep -q <expected> && KUBECONFIG=/tmp/x.kubeconfig AWS_PROFILE=p kubectl apply ...`
9. **Only operate on clusters you provisioned this session.** If you did not create it, do not touch it.
   Confirm ownership by the context name and cluster ARN, not by assumption.

If you are unsure which cluster a command will hit, stop and make the context explicit first. This
mirrors the global rule `~/.claude/rules/infra/kubernetes.md` (Cluster Context Safety).

## Where things live

This repo is the platform and content of the workshop "Build a Platform, Unleash an Agent on it... and
Watch it Burn!" (Michael Forrester with Whitney Lee). It holds the build, not the record of the talk.

- **The talk register, abstracts and talk scripts:** talks-knowledge (`~/repos/talks/talks-knowledge`,
  `peopleforrester/talks-knowledge`). `talks/register.md` section 2 is this talk's entry: canonical repo,
  argument, and where it has run. Submitted abstracts are under `abstracts/` (`library.md` catalogs which
  went where); talk scripts are under `speaking/`. `docs/ABSTRACT.md` here is a working copy of the
  published listings.
- **Event state** (dates, slots, rooms, CFPs, acceptances): conference-knowledge
  (`~/repos/conferences/conference-knowledge`, `events/registry.yaml`, entries `aiewf-2026-watch-it-burn`,
  `devopsdays-portland-2026`, `kubecon-na-2026`). Name the entry; do not copy the fact here (#417).
- **Components built from their own repos** (git submodules): guard-proxy-agenticburn at
  `gitops/ai-layer/guard-proxy`, llm-guard-cpu-offline at `images/llm-guard`.
- **Upstream backup, not a submodule:** llm-guard-upstream-mirror (`peopleforrester/llm-guard-upstream-mirror`,
  private), a mirror of the archived `protectai/llm-guard` so builds survive if the upstream repo is deleted.
  Nothing in this repo builds from it; llm-guard-cpu-offline is the public offering (#416).
- **This repo's own state:** `PROJECT_STATE.md` (current cycle) and `decisions.md` (append-only).

## Branch target: staging, not main

All changes must be pushed to the `staging` branch, not `main`. Create feature branches off `staging` and open PRs targeting `staging`. Never open a PR targeting `main` directly.

## Change cadence and demo guardrails (NO deferral, NO production framing)

This is a disposable workshop demo, not a production system. Clusters are rebuilt on demand and torn
down after. There is no production-risk constraint here. Apply these without exception:

1. **Never defer or resist a change by citing proximity to the workshop date.** We build and change
   this platform up to and including the morning of the workshop. The live final run is a last-minute
   finalization by design. "We're close to the deadline" is never a reason to withhold, downscope, or
   delay a change. Do not raise it.

2. **The platform's own guardrails are demo props, not constraints on building it.** ArgoCD
   `selfHeal`, Kyverno `Enforce`, NetworkPolicy default-deny, Falco/Talon: these only need to be active
   during the actual live workshop run. When one of them blocks a build or config change, TURN IT OFF
   (or scope-exempt the field via `ignoreDifferences`, or set the policy to Audit), make the change,
   then turn it back on. Do not let a tool we installed stop a change we need. Re-enable before the run.

3. **"Can't live-test without a cluster" is not a reason to defer a correct change.** Write the code.
   When validation needs a cluster, provision one and validate; we will do this repeatedly. Unverifiable
   right now does not mean withhold.

4. **Bias to action.** Make the change, provision/validate, iterate. Surface real trade-offs once and
   briefly, then proceed with the change unless told otherwise. Do not re-raise settled objections.

Test command: `bash verify/run-tests.sh`
E2E command: `bash verify/run-e2e-tools.sh`

The E2E command is the cluster-free tier (#572): the offline suite, then every `# E2E TIER: tools` check, run
with the pinned, checksum-verified binaries in `verify/e2e-tools.lock`, which `verify/fetch-e2e-tools.sh`
downloads into the gitignored `verify/.tools`. It needs network but no cluster, no AWS and no CONTEXT, and it
fails when a fetch fails.

The live-cluster suite, `bash verify/run-e2e.sh`, is run by hand during a cluster build, with CONTEXT,
IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION set against a fresh attendee cluster. It is deliberately not
declared as the gate's E2E command: hecaton's promotion gate has no cluster, no AWS and none of its tools,
so declaring it would hold main red for good (#543).
