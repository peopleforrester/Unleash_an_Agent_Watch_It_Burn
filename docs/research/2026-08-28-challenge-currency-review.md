# 2026 currency review of the challenge set: where each recommendation landed

The review itself is issue #110, researched 2026-08-28 against the OWASP Agentic Top 10 (2025-12-09) and
the OWASP LLM Top 10 revision (2026-08-03). Its sources, incident write-ups and "not verified" caveats live
in the issue and are not restated here: copying a dated external claim into a second file makes two
copies to re-verify. This file records the disposition of every recommendation, reconciled 2026-10-24, so
the next session does not have to rebuild it from eight issue threads.

## The child issues

| Issue | Recommendation | State (2026-10-24) | Where it landed |
|---|---|---|---|
| #111 | Add service-account token theft | Done, closed 2026-09-04 | Challenge 8 and its least-privilege RBAC fix, `bd9ad56`; `verify/test_c8_teaching.py` |
| #114 | Retire the fork bomb, replace with denial-of-wallet | Done, closed 2026-08-29 | `68e36ef`; `challenges/c4-denial-of-wallet/` |
| #115 | Stop calling the C5/C6 controls app-layer | Done, closed 2026-09-03 | Resolved as a ruling, not a reorder: the output guard and injection classifier run in the guard-proxy, which the platform injects, so they are platform guardrails. The ruling heads `docs/RUN-OF-SHOW-2026-08.md` and `/brief` |
| #112 | Add privileged pod / hostPath escape | Open, `deferred-barcelona` | Deferred by Michael 2026-09-07 (the Portland set of eight was closed). Note on the issue: `disallow-privileged` must not be armed as written; it would deny nine platform DaemonSets |
| #113 | Add IMDS credential theft | Open, `deferred-barcelona` | Deferred by Michael 2026-09-07 |
| #116 | C1 two-stage, DNS exfil defeats the L3/L4 policy | Open, `deferred-barcelona` | Deferred by Michael 2026-09-07 |
| #117 | C7 MCP rug-pull | Open, `deferred-barcelona` | Deferred by Michael 2026-09-07 |

## What the review raised that has no child issue

These are talk-content choices, so they wait on Michael rather than on a build. Question 575
(`decisions.md`, 2026-10-24) settled where they go: #110 closes as a tracker, and these items move
together to one new `deferred-barcelona` issue, following the pattern of #112, #113, #116 and #117.

- **The suggested new opener** (the 2026-07-16 Hugging Face disclosure). `facilitation/slides-outline.md`
  still opens on the personal cluster-deletion story, and `facilitation/cold-open-script.md` scripts it.
  The issue's warning stands for any use of it: present the chain, never the model attribution.
- **The "other incidents worth a slide"** list and **the authorities to cite** (OWASP, CISA / Five Eyes,
  MITRE ATLAS, NIST COSAiS). None is on a slide or in the lab. The one OWASP ID an attendee sees today is
  ASI03 in Challenge 8's lab copy. `prds/36-multicloud-attack-control-signal-matrix.md` pegs the beats to
  ASI IDs, but it is a draft awaiting approval and maps the pre-review set.
- **C2 (malicious image) "aged to table-stakes"** and **C3 (filesystem snooping) "weak standalone"** were
  verdicts without a proposed change.
- **ASI06, ASI07, ASI08, ASI09 and ASI10** remain uncovered. The review chose ASI03 as the theme for its
  additions; #111 covers it today, and #112 and #113 would extend it.

**Update 2026-10-24 (#466, question 679):** a run drafted the opener, the five incident slides and a citation
slide in `facilitation/slides-draft-2026-currency.md` for Michael to rewrite and approve. That file holds the
re-check of every dated claim above against its source. Several moved since 2026-08-28: Hugging Face's own
timeline now names the models (the draft still leaves the attribution off), MITRE ATLAS has moved past
v5.4.0 to calendar versions, NIST renamed COSAiS on 2026-10-20, and the Five Eyes guidance's wording differs
from the paraphrase in #110. The delivered outline and cold-open script are unchanged.
