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
   Confirm ownership by the context name and cluster ARN, not by assumption. The one exception is a dispatched
   run's two clusters, `watch-it-burn-community` and `watch-it-burn-private`: hecaton hands them to the run in an
   isolated `$KUBECONFIG` of its own, and the run operates on them (Dispatched runs, point 1).

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
- **Argo CD Applications, since #609:** one file each in `gitops/bootstrap/apps/`, rendered by the `lab-bootstrap`
  chart at `gitops/bootstrap`. Each profile is an explicit list in `gitops/bootstrap/values-<profile>.yaml`
  (attendee, burn, admin, full), so adding or removing an app changes the file and the lists together, and
  `verify/test_bootstrap_chart.py` holds the counts. `gitops/apps/` no longer exists; older docs, PRDs and drafts
  that name it mean `gitops/bootstrap/apps/`.

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
IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION set against a fresh attendee cluster, and DRIFT_PROFILE and
ATTENDEE_CLUSTER naming the fleet account and attendee cluster the AWS-plane drift check uses (#205), and
COMMUNITY_CONTEXT naming the community cluster the KubeCon probe's Challenge 3 beat runs on (#807), and
PRIVATE_CONTEXT naming the private admin cluster that, with the community one, #783's collector fix is checked on (#812).
A dispatched run, which brings no cluster up, runs it on one of its two clusters instead (Dispatched runs, point 1). It is
deliberately not declared as the gate's E2E command: hecaton's promotion gate has no cluster, no AWS and none of its
tools, so declaring it would hold main red for good (#543).

## Dispatched runs (hecaton)

A run that hecaton dispatches starts from the current `staging` on its own `agent/<issue>-<run>` branch. It has the
two clusters that are up and an AWS session for them, it never brings a cluster up or down, and its governance
forbids deploying. Hecaton run 9654 lost its time to the first point below and run 9672 to the second (#633). Runs
9277 and 15763 lost theirs redoing work an earlier run had done that never reached staging, the third point, and a
stalled wait on the E2E command is the fourth (#798). Run 15816 lost its time to the fourth as well, and run 9604
to the fifth (#796).

1. **A run checks live on the two clusters that are up, and brings none up or down.** Since Michael's ruling of
   2026-11-02 (hecaton#496, #809), every run gets, in its run directory, a 12-hour session for the `accen-dev` AWS
   profile (account 515966504359, us-west-2) and a `$KUBECONFIG` whose only contexts are `watch-it-burn-community`
   (the public community cluster) and `watch-it-burn-private` (the admin cluster). It has AWS and kubectl access to
   both and runs live checks on them itself: no escalation and no wait on Michael, for access or for the spend of
   these two clusters. Each `kubectl` call still names its `--context`. A script that needs the AWS session (boto3,
   `verify/*.py`) runs after `. "$HECATON_CLUSTER_ENV"`, which exports AWS_PROFILE, AWS_REGION and the session
   files. A run never creates or tears down a cluster or nodegroup, and there is no third cluster; the `aws` and
   `terraform` on its PATH refuse to. So "provision one and validate" in change cadence rules 3 and 4 above means,
   in a run, validate on one of the two, and a step written for a fresh attendee cluster runs on one of them
   instead. In a run, write the change and its offline test, run `bash verify/run-tests.sh` and
   `bash verify/run-e2e-tools.sh`, run the live check, and put what it printed in the change's decisions.md entry.
   A live check that changes a cluster leaves it as found. The clusters take a change from staging, through Argo
   CD, once hecaton promotes the run, so a check that needs the change itself running is named, by its E2E test or
   command, under "Not yet run on a cluster" in that entry, and the next run on the issue runs it. When the issue's
   own work is a live run, the run does it; when it is a bring-up (#610 was one), its checks run on one of the two.
   Session files the run cannot read are hecaton's fault to name in the report (hecaton#508), not a wait on
   Michael. A go already asked on the issue is pointed at, not asked again in new words.
2. **An earlier draft is checked against staging before it is reused.** A re-dispatched issue's earlier drafts are
   on `origin/agent/<issue>-<run>` branches, cut from the staging of their day, and staging moves between runs:
   #474's approved change had to be redone three times, the last after #609 moved `gitops/apps/` into the chart.
   First run `bash verify/prior-drafts.sh <issue> origin/staging`. It lists, newest first, each draft whose commits
   are not in staging, with the verdict of `bash verify/draft-drift.sh origin/agent/<issue>-<run> origin/staging`
   on it. That names every path the draft changes that staging has since edited, moved or deleted, and every
   directory the draft adds files to that staging removed, and exits 1 when there is any. Where staging moved or
   deleted a path, make that part of the draft's design again on the current layout rather than cherry-picking it.
   Where staging only edited a path, cherry-pick the draft and reread the staging commit the line names against
   what the draft claims. An APPEND line is decisions.md, which both sides only added to: keep both entries. Say in
   decisions.md what differs from the draft.
3. **Work that never landed is reused.** A run's commits reach staging only when hecaton promotes
   them. A run that fails a gate or stalls leaves them on its branch, or on hecaton's host until it retires the
   workspace 14 days later, and the issue's comments name those commits. Run 9277 (#604) redid a measurement that
   run 9249 had committed and that failed only the prose gate; 9249's branch applied to 9277's base with no
   conflict. Run 15763 (#205) redid a draft 125 commits behind staging whose drift was three edits in place and a
   decisions.md append. When `prior-drafts.sh` prints START, read why that work did not land in the issue's
   comments (`gh issue view <issue> --comments`; hecaton writes "Not merged: run N ended failed (validation)"),
   port the draft as its verdict says, fix what stopped it, and redo only what the verdict or that reason names. A
   LATER line means a later run's work on the issue is already in staging: take from that draft only what it lacks.
4. **A long command is polled in the foreground.** `bash verify/run-e2e-tools.sh` runs the offline suite and then
   the tools tier, and on the shared host it takes over 20 minutes, longer on a cold fetch of the pinned tools.
   Hecaton stops a run that prints nothing for 15 minutes as stalled, and nothing the run had not committed
   survives it: the attempt before run 15763 on #205 and two attempts on #520 ended that way. Commit the change
   first. Then start the command in the background with its output in a log, and keep reading the log in the
   foreground (`tail -n 5 <log>` every few minutes) until it ends; never end the turn to wait for its completion
   notice. The E2E command runs `run-tests.sh` first, so it also answers the Test command.
   The background job's limit is 3600000 ms: run 15816 gave it 20 minutes and it was cut off, and its
   `checks ran` line prints how long it took (22m58s in run 16533). Write the output and the exit code to a log of
   this run's own: `bash verify/run-e2e-tools.sh >"$LOG" 2>&1; echo "exit=$?" >>"$LOG"`. A bounded foreground wait
   is `timeout 540 bash -c 'until grep -q "^exit=" "$0"; do sleep 15; done' "$LOG"`, under the shell tool's
   10-minute foreground limit, run again after each 124 with a `tail -n 5` of the log between. Monitor needs an
   approval a run cannot get, so do not reach for it; run 16484 on #796 ended its turn to wait instead and was
   stopped as stalled. Read the verdict from the log: the `checks ran` line, `ALL E2E TOOLS TIER CHECKS GREEN` and
   `exit=0`. Do not watch the job with `pgrep` or `pkill` by script name: other runs on the host run the same
   scripts from their own worktrees, so a name match finds their processes, not this run's.
5. **Prose is put through the ai-isms gate before it is committed.** Hecaton's ai-isms gate reads every changed
   `.md`, `.mdx` and `.html` file here, since a talk repo's Markdown is public prose. It fails a change that adds an
   em-dash, or that adds a hype word or connective filler to a file that then reads `major`. decisions.md,
   PROJECT_STATE.md and PROGRESS.md already read `major`, so one word in a run's record fails the run. Two words
   recur: the talk's own verb (`Unleash`, and the nickname `Unleashed`) is on the hype-verb list, and the
   third-person verb `lets` is read as `let's` (run 16077 failed on the second). Write the repo as
   `Unleash_an_Agent_Watch_It_Burn` or put the word in backticks, which the gate strips, and say "allows" or
   "admits" for the verb. Then run
   `python3 verify/prose_gate.py /var/lib/hecaton/app/current/src/hecaton/run/aiisms.py origin/staging`: it reads
   the working tree against staging with the gate's own scanner, names each file, label and added line the gate
   would fail, and exits 1 on any.

## Tests own their inputs

Two runs lost time to a test whose result hung on something the test did not own (#797). Run 9643 (#612) reworded
row 8's readiness cell in the run-of-show, and the deck export's test, which edited that file on the literal
`| **At risk.**`, broke; the run put the old label back to suit the test. Run 15808 (#583) saw the E2E tier go red on
a check that a randomly drawn witch name did not contain "rude", which "Prudence" does, one draw in 32.

1. **Find the tests that read the words before you reword them.** Run
   `git grep -nF '<the exact words you are changing>' -- verify scripts` first. A test or script that reads those
   words changes in the same commit as the text. Correct text is never reverted to suit a test.
2. **An anchor a test edits or splits on is checked first.** A test that builds a case by replacing or cutting repo
   text on a literal checks the literal is there and, when it is not, exits naming the literal and the file, so a
   reworded anchor reads as that and not as a broken check further on.
3. **Randomness is pinned or enumerated.** A test seeds the code's random source, stubs `Math.random`, or tries every
   value the code can pick, and each check holds for every one of them. `verify/test_storefront_witch_name_e2e.py`
   pins every draw and tries all 32 first names. A test that fails once and passes on a rerun is broken, not flaky.
   The run that sees it fixes it, or, when the run cannot find the cause, files an issue with the failing output.
