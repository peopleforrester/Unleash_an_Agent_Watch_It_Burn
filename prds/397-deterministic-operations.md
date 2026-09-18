# PRD #397: Every fleet operation runnable from a shell, without an agent

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/397
**Children**: #398 (one teardown path), #399 (promote the harvest), #400 (account audit),
#401 (version drift), #402 (reap secrets), #395 (teardown exit code)
**Priority**: High. Not because anything is broken right now, but because the gaps are only visible
while the memory of this week is fresh, and they are the reason several leaks went unnoticed for months.
**Status**: **Delivered 2026-09-18.** All six children closed. The five commands exist, the runbook
names them, and every new check carries a negative control proving it can fail. Validation of the
accompanying chart upgrades is running on a live cluster; see "What shipped" below.

---

## Problem

A person with a shell should be able to run this platform. Today a meaningful part of it can only be
done by reconstructing what an agent did in a session, and that is a dependency nobody chose.

Three distinct failure shapes, all found on 2026-09-18:

**Work that exists only in throwaway scripts.** Seven scripts in `/tmp` and five in the gitignored
`.harvest/` did real work this week: the audit that found the leftovers, the version measurement the
entire upgrade was built on, and the harvest that is the only record of what attendees did at Portland.
None of it is tracked. It is all one reboot or one `rm` from gone, and none of it can be re-run.

**Two implementations of the same verb.** `teardown/teardown.sh` and `fleet.sh down` are both "tear it
down" and do different work. The cron path uses the weaker one. That is why 107 orphaned log groups
accumulated while a correct `cleanup-log-groups.sh` sat in the repo, wired into the path nobody runs.

**Checks scoped narrower than their name.** `audit-zero` reads as "assert the account is empty" and
means "assert nothing billable beyond the lab VPC is running". Both readings are defensible, which is the
problem: it passed while each account held 105 orphaned security groups and 111 GB of log data.

## The pattern worth naming

Four separate defects this week share one shape: **the tooling reported the wrong thing about its own
success.**

| Defect | What it reported | What was true |
|---|---|---|
| Orphaned security groups | `audit-zero`: ZERO | 105 groups per account, blocking VPC deletion |
| Datadog service-map gate | skip, exit 2 | had never executed on any machine, ever |
| Teardown routes reload (#395) | `1 cluster(s) FAILED` | everything destroyed correctly |
| Orphaned log groups | nothing at all | 107 groups, ~111 GB |

None was found by a check. All four were found by hand, and only because somebody went looking.
Determinism is the fix for that: a check that runs on a schedule and can fail is worth more than a check
that is correct but never runs.

## Solution

Five commands, one document, no agent required.

| Command | Answers |
|---|---|
| `fleet.sh down all` | tear it down, completely, exit 0 on success |
| `verify/account-audit.sh` | is anything of ours running anywhere |
| `verify/version-drift.py` | what is behind its latest GA |
| `scripts/harvest/run.sh <event>` | capture what happened at an event |
| `fleet.sh reap-secrets` | remove our secrets |

Plus `docs/RUNBOOK.md`: one page, one line per operation, naming the command. Not prose, a table.

### Ordering

1. **#398, one teardown path.** Everything else is downstream. While two paths exist, every fix has to
   be made twice and will not be.
2. **#399, promote the harvest.** Highest loss-if-delayed: the code is gitignored and the knowledge in
   it (where prompts live in a span, which namespace Falco is in, which Datadog org a cluster ships to)
   cost hours to establish and is written down nowhere else.
3. **#400, the account audit.** The check that would have caught three of the four defects above.
4. **#401 and #402**, version drift and secret reaping. Both small, both currently impossible.
5. **#395, the teardown exit code.** Small, but until it is fixed no wrapper can trust `down all`.

## What "done" looks like

A person who has never read this repo can tear the fleet down, prove it is empty, and know what is out
of date, using commands named in one document, with no session transcript to consult.

## Risks

- **Consolidating the teardown paths can drop a step.** `teardown.sh` calls a tag audit that `fleet.sh`
  does not. Merging must move that, not lose it. A test should assert the merged path still calls it.
- **Reaping secrets by default could break the next build.** The Datadog pool is what `up` provisions
  against. Either reaping is opt-in, or `up` can recreate it. Decided in #402, not here.
- **These scripts are only trustworthy if they run.** Everything above is written by the same reasoning
  that produced a gate which never executed. Each new check needs a negative control proving it can
  fail, which is the practice that caught the last three.

## Out of scope

- The IDP component parity work (#394) and the inference toggle. Different problem.
- Anything about challenge content.


---

## What shipped

| Issue | Delivered | Where |
|---|---|---|
| #398 | One teardown path. `teardown.sh` reduced from 80 lines to 36 and execs `fleet.sh down all`; the tag audit it uniquely performed was absorbed. | `7f36f5f` |
| #399 | Harvest code moved to `scripts/harvest/`, five passes plus one entry point, parameterised by `WIB_EVENT`. Data still ignored. | `2a35cba` |
| #400 | `verify/account-audit.sh`, broader than `audit-zero`, co-tenant exclusions written in. | `20daa40` |
| #401 | `verify/version-drift.py`, reading the repo each Application actually names. | `20daa40` |
| #402 | `fleet.sh reap-secrets`, prefix-scoped and force-deleting. | `4cf5d9d` |
| #395 | A clean teardown exits zero. | `4cf5d9d` |
| — | `docs/RUNBOOK.md` | `3074bcd` |

## What the work found while being done

Two defects surfaced by the new tools on their first run, which is the argument for having built them:

**`kube-prometheus-stack` had never been upgraded**, despite being listed as behind in the inventory and
flagged high-risk in PRD #389. It is pinned in `gitops/apps/prometheus.yaml`, named for its purpose
rather than its chart, and the upgrade pass matched files to chart names. `version-drift.py` reports by
chart name and found it immediately: 86.2.3, five majors behind.

**Tempo's pin carried a rationale that had expired.** The comment said Tempo 3 was reachable only
through the microservices chart, which was true on 2026-09-10 and is no longer: the single-binary line
now ships 3.0.3. A dated markdown inventory could never have told us that; a command re-run eight days
later did.

Nine charts had drifted in eight days. That rate is the case for `version-drift.py` running on a
schedule rather than being remembered.

## What is still not deterministic

Recorded honestly rather than left implied:

- **Upgrade validation still needs a human decision.** `version-drift.py` says what is behind; nothing
  says whether a five-major jump is safe to take. That judgement is not automatable and should not be
  pretended otherwise.
- **The empty-routes fix is narrow by design.** It allows an empty table only when a shrink was already
  asserted. A teardown driven some other way still hits the guard, correctly.
- **`account-audit.sh` enumerates resource types by hand.** A service nobody thought of is invisible to
  it. The tagging-API check partly covers that, but only for resources that carry our tags.
