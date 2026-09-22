# Forking a Dead Security Library, and Getting Off Hugging Face

Research report, 2026-09-22. Two questions: what it would actually cost to maintain a fork of
`protectai/llm-guard`, and how to hold the prompt-injection model weights and the Python packages
independently of Hugging Face and PyPI.

Every figure below was measured on 2026-09-22 against a live source. The command or API that
produced it is named so you can re-run it. Claims I could not verify are collected at the end.

Working files: `/tmp/claude-1000/-home-michael-repos-talks-Unleash-an-Agent-Watch-It-Burn/deddecfd-5492-4059-a230-666342ff1423/scratchpad/lg/`
holds the bare clone (`repo.git`), the full issue and PR dump (`issues_raw.json`), the fork listing
(`forks.json`), both dependency resolutions (`resolved_core.txt`, `resolved_onnx.txt`), the
hash-pinned lock (`hashed.txt`) and the OSV results (`osv_pinned_hits.json`).

---

# PART 1: What maintaining a fork of `protectai/llm-guard` actually costs

## 1.1 Baseline facts, with corrections to the brief

| Fact | Measured | Source |
|---|---|---|
| Archived | `archived: true`, last push `2026-07-08T23:58:40Z` UTC (`2026-07-09 01:58 +0200` local) | `gh api repos/protectai/llm-guard` |
| Stars / forks | 3,208 / 461 | same |
| **"38 open issues"** | **12 open issues plus 26 open PRs.** GitHub's `open_issues_count` counts PRs. | `gh api --paginate .../issues?state=all`, 350 items |
| Last functional commit | `2025-09-03` (#283). The final commit is "Archiving Project (#355)". | `git log` on a bare clone |
| Last release | v0.3.16, PyPI upload `2025-05-19T12:12:58Z`. 26 releases total, first `2023-08-08`. | `pypi.org/pypi/llm-guard/json` |
| License | MIT (repo), and the PyPI metadata carries the full MIT text with "Copyright (c) Protect AI" | both |
| Python support | `>=3.10,<3.13` | PyPI `requires_python` |
| Acquisition | Palo Alto Networks completed the Protect AI acquisition **2025-07-22** | [PAN press release](https://www.paloaltonetworks.com/company/press/2025/palo-alto-networks-completes-acquisition-of-protect-ai) |
| Forks pushed since archive | **60 unique**, of 326 unique forks. The API returns 467 rows with pagination duplicates. | `gh api --paginate .../forks` |
| Best fork | **2 stars.** Only 22 of 326 forks have any star at all. | same |

The archive came **11.5 months after** the acquisition closed. That is the normal lag for an
acquirer working through a portfolio's open source.

Two corrections to the brief worth carrying forward. First, the "38 open issues" figure is 12
issues and 26 PRs, which changes what a fork inherits: most of the backlog is contributed code
waiting for review, not user complaints. Second, the last functional commit is 2025-09-03, so the
code had been frozen for **ten months** before the archive notice went up, and the last release was
**fourteen months** before it.

## 1.2 Dependency surface

`uv pip compile` on `llm-guard==0.3.16`, Python 3.12, resolved 2026-09-22:

- **12 direct runtime dependencies**
- **98 transitive packages** in the core resolution
- **119 packages** with the `[onnxruntime]` extra
- **15 of those are NVIDIA CUDA wheels**, pulled in by `torch`

The ML-heavy share is `torch`, `transformers`, `tokenizers`, `safetensors`, `onnx`, `onnxruntime`,
`optimum`, `presidio-analyzer`, `presidio-anonymizer`, `spacy` plus its nine support packages
(thinc, blis, cymem, murmurhash, preshed, srsly, catalogue, confection, wasabi), `nltk`, `numpy`,
`datasets`, `pyarrow` and `pandas`. That is roughly **40 of 119 packages, 34% by count**, and
effectively all of the weight.

Measured cost of that weight in your own image. `ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline.2`
is **4,211 MB compressed across 15 layers**, with a single 3,364 MB layer (torch and CUDA) and a
679 MB layer (the baked model). Current digest:
`sha256:ec8ead8acca5c3f76cd2db192ad3d62c4651fe5ce61cc073021c27b98c9f845a`.

### The pin structure is the real inherited liability

Seven of the 13 direct requirements are exact `==` pins:

```
bc-detect-secrets==1.5.43
json-repair==0.44.1
presidio-analyzer==2.2.358
presidio-anonymizer==2.2.358
regex==2024.11.6
transformers==4.51.3
optimum[onnxruntime]==1.25.2      # extra
```

An exact pin means every security bump is a source change in the fork plus a release, not a
lockfile refresh. It also creates transitive back-pressure: `presidio-anonymizer==2.2.358` is what
holds `cryptography` down at 44.0.3, which is exactly open issue #342.

## 1.3 Security exposure

### Against llm-guard itself: zero

GitHub Security Advisories (`/advisories?ecosystem=pip&affects=llm-guard`) returns nothing. OSV
returns 0 vulns for the PyPI package. **Every bit of the exposure is inherited from dependencies.**

### Against the pinned resolution today: 24 CVEs on day one

OSV `querybatch` over all 119 packages at their resolved versions, deduplicated by CVE alias:

| Package | Version | Unique CVEs | Raw OSV records |
|---|---|---|---|
| transformers | 4.51.3 | **18** | 28 |
| cryptography | 44.0.3 | 6 | 10 |
| nltk | 3.10.3 | 1 | 1 |
| json-repair | 0.44.1 | 1 | 1 |
| **Total** | | **24 unique CVEs across 4 packages** | 40 |

A `pip install llm-guard==0.3.16` today lands you on 24 known CVEs immediately, and you cannot fix
the two largest groups without editing the fork's source, because both are exact pins.

### Advisory arrival rate against the dependency set

OSV, PyPI ecosystem, deduplicated by CVE alias, strict `published` field, 24-month window since
2024-09-22:

| Package | All-time | Last 24 months |
|---|---|---|
| nltk | 52 | 47 |
| aiohttp | 47 | 38 |
| transformers | 31 | 28 |
| torch | 31 | 27 |
| cryptography | 24 | 11 |
| onnx | 13 | 10 |
| urllib3 | 19 | 8 |
| jinja2 | 10 | 5 |
| requests | 8 | 3 |
| protobuf | 5 | 3 |
| setuptools | 5 | 3 |
| pyarrow | 5 | 2 |
| json-repair, datasets, pydantic | 4 | 3 |
| numpy | 8 | 0 |
| pandas | 1 | 0 |
| bc-detect-secrets, faker, fuzzysearch, presidio-analyzer, presidio-anonymizer, regex, tiktoken, structlog, optimum, onnxruntime, spacy, huggingface-hub, tokenizers, safetensors, triton | 0 | 0 |
| **Total surveyed, 32 packages** | **263** | **188** |
| **Direct dependencies only, 13 packages** | **115** | **103** |

I re-checked the nltk figure because 47 advisories in 24 months looked like a broken measurement.
It is real. GHSA-3gq4-3j92-5w49 (NLTK Corpus Reader Sandbox Bypass, published 2026-09-08) and
GHSA-469j-vmhf-r6v7 (NLTK Downloader Path Traversal, published 2026-03-19) are genuine nltk
advisories affecting the `nltk` PyPI package.

**103 advisories against the direct dependencies in 24 months is 4.3 per month** arriving at the
fork's door for triage, even though only a fraction turn out to be actionable at any given pin
level.

## 1.4 Historical maintenance load: what it took with a funded team

From the bare clone and the full issue and PR dump.

**Authorship and bus factor.** 518 commits from 27 git authors. GitHub reports **21 contributors**.
One person, `asofter` (Oleksandr Yaremchuk, counted under two identities), wrote **419 of 518
commits, 81%**. Dependabot wrote 82. That leaves **17 commits, 3.3%, from everyone else combined**.

**Commits per month.** Peak 70 in 2023-09. Sustained 40 to 63 through 2024-05. Then collapse:

```
2023-08  26   2024-01  40   2024-07   9   2025-02   5
2023-09  70   2024-02  59   2024-08   9   2025-03   4
2023-10  63   2024-03  27   2024-09   4   2025-05   5
2023-11  62   2024-04  49   2024-10   7   2025-07  10
2023-12  27   2024-05  24   2024-11   0   2025-09   1
             2024-06  16   2024-12   0   2026-07   1  (the archive commit)
                           2025-01   0
```

Three consecutive months with zero commits (2024-11 through 2025-01). All of 2025 produced 20
commits.

**Releases.** 26 total, 15 of them in the first 12 months. The nine-month gap between v0.3.15
(2024-08-22) and v0.3.16 (2025-05-19) is where the project actually died, fourteen months before
the archive notice.

**Issues.** 116 opened over 34 months, **3.4 per month**. Median **time-to-close 67.7 days** (mean
134.6, p25 7.7, p75 205.1, p90 350.2, max 579.1). Only **24% closed within 7 days** and **40%
within 30 days**. That is the triage performance of a funded vendor team, and it was not good.

**Pull requests.** 234 total. **163 from dependabot (70%)**, 71 human. Dependabot opened **5.8 per
month mean, 6.0 median, over 28 months**, peaking at 13. Only 82 dependabot commits landed, so
roughly **half the bot PRs were merged**. Human PRs during the active life ran 2.4 per month and
were merged at a median of **1.14 days**. Responsiveness to contributors was excellent;
issue triage was not.

## 1.5 What a fork inherits: the 12 issues and 26 PRs, categorized

**Open issues (12):**

| Category | Count | Issues |
|---|---|---|
| Security or dependency-blocking | 3 | #313 transformers vulnerability; #342 presidio blocks cryptography >=46 (CVE-2026-26007); #347 downstream release tracking |
| Runtime compatibility | 2 | #319 Python 3.13 core rules compliance; #320 sentencepiece install failure |
| Functional bugs | 3 | #154 scanner reconfiguration after model load; #331 PromptInjection drops phone and email; #337 Anonymize ignores `language` and hardcodes ALL_SUPPORTED_LANGUAGES |
| Feature proposals | 2 | #326 loading other models; #340 ATRScanner backed by 338 agent threat rules |
| Questions and meta | 2 | #324 "Is this repo maintained?"; #336 where cryptographic agent identity belongs |

The oldest open issue, #154, has been open since 2024-06-20. Two of the twelve (#324, #336) are
questions a fork maintainer would answer and close on day one. The real backlog is nine items.

**Open PRs (26):**

| Category | Count | Notable |
|---|---|---|
| Dependabot | 5 | GitHub Actions majors (checkout 4→6, codeql 3→4, cache 4→5, setup-python 5→6); optimum 1.25.2→2.0.0 (two PRs) |
| Security fixes | 4 | #323 and #332 are **duplicate** path-traversal and dangerous-assert fixes; #309 transformers; #353 presidio unblock for #342 |
| New scanners | 7 | #346 AgentThreatRules; #350 AgentEscalation; #351 AgentMemoryPoisoning; #352 CredentialExfiltration; #327 ToolCallAudit; #288 Regex vault support; #322 BanSubstrings Pydantic v2 |
| Bug fixes | 4 | #335 secrets redaction offset errors; #339 MaliciousURLs `top_k`; #308 json-repair; #317 feedback capture |
| Docs | 4 | #328, #334, #354, #333 (MiniMax examples) |
| Architecture | 1 | **#252 "Minify LLM-Guard and Lazy-Load Heavy Dependencies", open since 2025-06-03** |

#252 is the one that would most reduce the 4.2 GB image, and it has sat for fifteen months.

Worth noting for the workshop narrative: PRs #350, #351 and #352 are literally agent-escalation,
memory-poisoning and credential-exfiltration scanners, filed by one outside contributor
(`lavkeshdwivedi`) on 2026-07-06 and 2026-07-08. The repo was archived on 2026-07-08. The community
was still trying to extend the tool into agent security on the day it was closed.

## 1.6 Comparable cases

### The measurement that matters: contributor count

| Fork | Successor to | Institution | Contributors | Stars |
|---|---|---|---|---|
| Valkey | Redis (relicense 2024) | Linux Foundation, backed by AWS, Google, Oracle | **382** | 27,273 |
| OpenBao | HashiCorp Vault (BUSL 2023) | Linux Foundation | **374** | 7,456 |
| OpenTofu | Terraform (BUSL 2023) | Linux Foundation plus vendor consortium | **350** | 30,254 |
| Bandit | OpenStack security team | PyCQA, a volunteer org | **146** | 8,278 |
| **llm-guard** | | **none** | **21** | 3,208 |
| best llm-guard fork | | none | not measurable | **2** |

Every fork that survived had an institution behind it **before the first commit**, not after.
Bandit is the cheapest successful case and it still needed an existing organization (PyCQA) with
governance and a shared CI estate to move into. llm-guard has 21 contributors, 81% of the commits
from one person, and nothing to move into.

### The sharper question: has anyone sustained a fork of a tool an acquirer deliberately retired?

The three Linux Foundation forks above are **relicense forks**, not abandonment forks. Terraform,
Vault and Redis were all still actively developed when they were forked. What triggered each fork
was a license change that threatened downstream commercial users, which produced an immediate,
well-funded coalition with an existing product dependency and a legal reason to act. That is a
different situation from llm-guard in every respect that matters: the code was alive, the community
was large, and the forkers were companies with revenue at risk.

I could not find a case of a *successfully sustained community fork of a security tool that an
acquirer deliberately retired*. The honest statement is that my sources do not contain one, not
that none exists (WebSearch was unavailable, see the verification-gap section). What I can measure
is that llm-guard is not becoming one: fourteen months after the code froze and two and a half
months after the archive, 326 unique forks exist, 60 have been pushed since the archive, 22 have
any star at all, and the maximum is two.

Twenty-one forks bothered to rename themselves, which is the clearest available signal of intent to
take over: `llm-guard-enhanced`, `sigma-guard`, `Tueri`, `llm-guard-extended`, `aiops-llm-guard`,
`llm-guard-with-stateless-anonymization`, `llm-Sec`, `llm-guard-Ascend`, and thirteen others. Not
one accumulated more than one star.

### The retire-versus-lead-generation pattern, checked against the evidence

The team lead's framing is that across recent AI-security acquisitions, open source survived where
it was lead generation and was archived where it substituted for the paid runtime product. The
Protect AI portfolio is consistent with that, with one correction.

| Repo | Stars | Archived | Last push | Last commit | Relationship to the paid product |
|---|---|---|---|---|---|
| llm-guard | 3,208 | **yes** | 2026-07-08 | 2025-09-03 | Runtime guardrails. **Directly substitutes** for Prisma AIRS runtime protection. |
| rebuff | 1,521 | **yes** | 2024-08-07 | 2024-01-25 | Prompt-injection detection. Same substitution. |
| vulnhuntr | 2,776 | no | 2025-02-06 | | Static analysis for vulns. Research and reputation. |
| ai-exploits | 1,747 | no | 2024-10-23 | | Exploit collection. Pure marketing and research. |
| modelscan | 775 | no | 2026-02-18 | | Model file scanning. Scan-time, not runtime. |
| nbdefense | 87 | no | 2025-02-06 | | Notebook scanning. Scan-time. |

The two archived repos are the two runtime guardrail products. The four left public are research,
exploit collections and scan-time tools, which generate leads and cost nothing to leave up. The
pattern holds.

**The correction: rebuff was already dead before the acquisition.** Its last commit is 2024-01-25
and its last push 2024-08-07, both well before the deal closed on 2025-07-22. GitHub's API returns
`archived_at: null` for both rebuff and llm-guard, so I cannot date the archive *action* for either
and cannot say whether PAN set rebuff's flag or Protect AI did. What is measurable is that rebuff
was abandoned eighteen months before PAN arrived, so it is weak evidence for a deliberate-retirement
thesis. llm-guard is the strong case: it was still taking contributions the week it was closed.

**"Not archived" carries no signal here.** `modelscan` has been untouched for seven months and
`vulnhuntr` for nineteen. The entire Protect AI open-source portfolio is cold. A fork decision that
rests on "at least modelscan is still open" is resting on a flag nobody has bothered to set.

### The one real fork is a private company fork

Issue #347, filed 2026-07-01 by `orenk9`, tracks a release **`v0.3.16+aidealy.5`**. Its changelog is
a precise inventory of the work this report is costing:

- Fixed: resolve ONNX repos to local snapshot paths before `from_pretrained` (the `HF_HUB_OFFLINE`
  failure, which is the same bug your `images/llm-guard/Dockerfile` header documents)
- Changed: default `TokenLimit` encoding to `o200k_base`; **pin `transformers` to 4.57.x**; refresh
  lockfiles; exclude `onnxruntime-gpu` on macOS; point `llm-guard-api` at the Aidealy fork; require
  `orjson` in download-models; CI workflow permission and action bumps
- Security: regenerate locks for cryptography, pygments and requests advisories; document
  `pip-audit` ignores; `apt-get upgrade` in the API Docker images for base-layer CVEs

That fork is **not on PyPI** (`llm-guard-aidealy`, `aidealy-llm-guard`, `llmguard` and
`llm-guard-community` all return 404) and **not in the public fork list**. `orenk9` has no public
repositories. This is a company keeping a private copy alive for its own product, which is the
realistic model for a tool in this position, and it is not a community fork by any definition.

## 1.7 The costed answer

### Keeping a fork merely SAFE

Assumptions, stated: one engineer, existing CI, no new scanners, no model work. The goal is
"installable on a current Python and not shipping known-vulnerable dependencies."

| Activity | Working | h/month |
|---|---|---|
| Dependency-bot triage | 6 PRs/month measured, times 20 min each to read the changelog, check CI, merge or defer | 2.0 |
| CVE response | 103 advisories in 24 months against direct deps is 4.3/month arriving; roughly 1.5/month actionable at your pin level; each needs a pin bump, a regression run and an image rebuild at about 2 h | 3.0 |
| CI upkeep | GitHub Actions majors and runner deprecations; 5 such PRs were open at archive | 1.0 |
| Release and publish | PyPI sdist and wheel plus a container build and push, monthly | 1.0 |
| **Steady state** | | **7 h/month** |

Plus one-off work that cannot be avoided:

| One-off | Estimate | Why |
|---|---|---|
| Unpin the 7 exact `==` requirements, re-lock, fix the fallout | **20 to 40 h** | Required before any CVE bump is a one-line change instead of a source edit. `transformers` 4.51.3 to 4.57.x alone crosses a `tokenizers` major. Aidealy has already done this work behind a private fork. |
| Python 3.13 and 3.14 support (issue #319, the `<3.13` cap) | **16 to 40 h** | `sentencepiece` is already failing (#320). spaCy 3.8 and presidio set the ceiling, so this is upstream-blocked, not local work. |
| Clear the 4 open security PRs (#309, #323, #332, #353) | **8 to 16 h** | #323 and #332 are duplicate path-traversal fixes that need reconciling before either can land. |

**SAFE: 44 to 96 hours in year one, then 7 h/month (about 84 h/year) steady state.** At a loaded
engineering rate of $150/h that is roughly **$20k in year one and $13k/year after**, for a library
you do not own and cannot influence upstream.

### Keeping a fork ALIVE

Measured from what Protect AI actually spent. Forty to seventy commits per month with a median
issue time-to-close of 67.7 days is the output of roughly **one full-time engineer plus fractional
help**. When that one person's output fell, the project stopped within three months.

| Activity | Working | h/month |
|---|---|---|
| Everything under SAFE | | 7 |
| Issue triage and response | 3.4 issues/month measured; getting the median close under 30 days, which they never achieved, is about 4 h each | 14 |
| Contributor PR review | 2.4 human PRs/month at their measured 1.14-day median responsiveness | 10 |
| New scanners and features | 7 scanner PRs are already queued; a scanner with tests and docs is 30 to 60 h, at one per quarter | 15 |
| Docs site, examples, API server, Helm chart | the repo ships all four | 10 |
| Release engineering at the original cadence | 15 releases in 12 months | 8 |
| **Total** | | **64 h/month, about 0.4 FTE** |

Sustaining the pace of the project's actual peak (2023-09 through 2024-05) is **0.75 to 1.0 FTE,
120 to 160 h/month**.

### The cost nobody inherits: the model

`deberta-v3-base-prompt-injection-v2` is a fine-tune of `microsoft/deberta-v3-base` over seven named
datasets. Refreshing it against new injection techniques is an ML workload with data collection,
labeling, training and evaluation. It has no relationship to the software maintenance numbers above,
and it is the reason a "maintained fork" of the code still degrades in effectiveness. The Python can
be perfectly current while the detector ages. The model card itself now carries the archive warning,
so upstream will not refresh it either.

### The recommendation this produces

**Do not fork it.**

The evidence: 21 contributors with an 81% bus factor; no institution; no fork above two stars
fourteen months after the code stopped moving; the only serious fork is private and commercial; and
the tool sits in the category an acquirer retires rather than the category it keeps for lead
generation. A safe fork is $13k/year forever. An alive fork is a headcount decision. For a workshop
that uses LLM Guard as one implementation behind a platform-injected guardrail layer, neither is the
right spend.

What to do instead, in order:

1. **Pin what you have by digest and stop building from upstream.** Part 2 covers this. It is about
   a day of work and it removes the entire failure mode.
2. **Re-evaluate the control, not the library.** Your guard-proxy is the platform-injected layer in
   the taxonomy. LLM Guard is one implementation behind it, and the taxonomy survives replacing it.
3. **Track the Aidealy fork through issue #347** rather than starting a third one. Someone is
   already paying the SAFE cost and publishing the changelog.

---

# PART 2: Breaking the Hugging Face supply-chain dependency

## 2.1 The actual exposure in your build

`images/llm-guard/Dockerfile` calls:

```python
snapshot_download(repo_id=V2_MODEL.path, local_dir=d,
                  allow_patterns=["*.json", "spm.model", "onnx/model.onnx*"])
```

Three problems, all fixable in one change.

**1. No `revision=` pin.** It pulls `main`. The content under that ref can change and your build
would take it silently. The current revision is
`90c9989b1a342275dd0d1a95aad283c04e075671`, `lastModified: 2026-07-09T16:01:38Z`, which is the day
after the llm-guard archive, when the "THIS PROJECT HAS BEEN ARCHIVED" warning went onto the model
card.

**2. Build time still requires `huggingface.co`.** `HF_HUB_OFFLINE=1` protects runtime, not the
build. If the repo disappears you cannot rebuild the image, and you find out at the worst possible
moment.

**3. `allow_patterns` excludes `LICENSE` and `README.md`.** You redistribute Apache-2.0 weights in a
public image with no license text. Section 2.5 covers the fix.

Also verified: **nothing in `gitops/` is digest-pinned.** `grep -rc '@sha256:' gitops/` returns zero
matches across the tree. Every image is referenced by mutable tag, including images you already
re-host.

The good news is that you already mirror third-party images into your own namespace
(`ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim`, `:nginx-1.27-alpine`). The pattern
exists and is working. The model is the one artifact that still comes from somebody else's server at
build time.

## 2.2 Current state of the model on Hugging Face

| Fact | Value |
|---|---|
| Repo | `protectai/deberta-v3-base-prompt-injection-v2` |
| Status | Up, public, not gated, not disabled (as of 2026-09-22) |
| Revision | `90c9989b1a342275dd0d1a95aad283c04e075671` |
| Last modified | `2026-07-09T16:01:38Z` |
| Downloads, 30 days | 839,512 |
| Likes | 117 |
| License | `apache-2.0`, with a full 10,172-byte `LICENSE` file in the repo |
| NOTICE file | **none** |
| Base model | `microsoft/deberta-v3-base`, license **MIT**, last modified 2022-09-22 |
| Model card | Carries `THIS PROJECT HAS BEEN ARCHIVED` and "no longer under active development or maintained" |
| Weights | `model.safetensors` 737,719,272 B; `onnx/model.onnx` 738,563,188 B; total repo about 1.5 GB |

## 2.3 Ranked recommendation

### CNCF versus vendor, verified

Read from `cncf/landscape` `landscape.yml` on 2026-09-22:

| Project | CNCF level | Accepted | Latest release | Repo |
|---|---|---|---|---|
| ORAS | **sandbox** | 2021-07-13 | v1.3.4 (2026-08-27) | `oras-project/oras` |
| KitOps (ModelKit) | **sandbox** | 2025-03-04 | v1.15.0 (2026-06-25) | `kitops-ml/kitops` |
| ModelPack | **sandbox** | 2025-05-13 | spec repo, `modctl` v0.2.2 (2026-06-09) | `modelpack/model-spec` |
| KServe (modelcars) | **incubating** | 2025-09-29 | v0.20.0 (2026-08-06) | `kserve/kserve` |
| Harbor | CNCF (registry) | | | `goharbor/harbor` |
| zot | CNCF (registry) | | | `project-zot/zot` |
| sigstore / cosign | CNCF | | cosign v3.1.3 (2026-08-06) | `sigstore/cosign` |
| Kubeflow Model Registry | CNCF (Kubeflow) | | v0.3.17 (2026-09-21) | `kubeflow/model-registry`, redirects to `kubeflow/hub` |

Vendor products, by contrast: Artifactory (JFrog), the Ollama registry, `llmariner`, and MLflow's
registry as hosted by Databricks. MLflow itself is Apache-2.0 open source.

One stewardship signal worth recording, given the subject of this report: **`iterative/dvc` now
redirects to `treeverse/dvc`.** The tool you would adopt to escape one vendor's stewardship risk has
itself changed hands. Similarly `jozu-ai/kitops` now redirects to `kitops-ml/kitops` (the CNCF
donation), `containers/skopeo` to `podman-container-tools/skopeo`, and `kubeflow/model-registry` to
`kubeflow/hub`. Four of the eight candidate projects have moved organizations. Pin by URL that
survives a redirect, and do not hardcode an org name in automation.

### Rank 1: OCI artifact in your own GHCR namespace, digest-pinned, cosign-signed

**Do this one.** Reasons: one trust root, one auth path, the registry you already push to, and it
composes with both cosign and KServe modelcars if you ever need them. ModelPack even specifies a
media type for the licensing problem in section 2.5: `application/vnd.cncf.model.doc.v1.tar` is
defined as "a tar archive that contains documentation files like `README.md`, `LICENSE`, etc."

ModelPack's full media type set, from `modelpack/model-spec` `docs/spec.md` on `main`:

```
artifactType: application/vnd.cncf.model.manifest.v1+json
config:       application/vnd.cncf.model.config.v1+json
layers:       application/vnd.cncf.model.weight.v1.{raw,tar,tar+gzip,tar+zstd}
              application/vnd.cncf.model.weight.config.v1.{raw,tar,tar+gzip,tar+zstd}
              application/vnd.cncf.model.doc.v1.{raw,tar,tar+gzip,tar+zstd}
              application/vnd.cncf.model.code.v1.{raw,tar,tar+gzip,tar+zstd}
              application/vnd.cncf.model.dataset.v1.{raw,tar,tar+gzip,tar+zstd}
```

Tooling state on this box, checked: `cosign v3.1.3` and `crane 0.21.7` are installed. `oras`,
`skopeo`, `modctl` and `kit` are not (`brew install oras`).

```bash
# 1. Pull the exact revision, with the license files this time
REV=90c9989b1a342275dd0d1a95aad283c04e075671
hf download protectai/deberta-v3-base-prompt-injection-v2 \
    --revision "$REV" --local-dir ./pi-model
# equivalently: snapshot_download(repo_id=..., revision=REV, local_dir="./pi-model")
# with no allow_patterns, so LICENSE and README.md come too

# 2. Record what you got, before anything else touches it
( cd pi-model && find . -type f -print0 | sort -z | xargs -0 sha256sum ) > pi-model.SHA256

# 3. Push as an OCI artifact into the registry you already use
oras push ghcr.io/peopleforrester/watch-it-burn:pi-model-v2-${REV:0:12} \
  --artifact-type application/vnd.cncf.model.manifest.v1+json \
  --annotation "org.opencontainers.image.source=https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2" \
  --annotation "org.opencontainers.image.revision=$REV" \
  --annotation "org.opencontainers.image.licenses=Apache-2.0" \
  ./pi-model:application/vnd.cncf.model.weight.v1.raw

# 4. Pin and sign
DIGEST=$(crane digest ghcr.io/peopleforrester/watch-it-burn:pi-model-v2-${REV:0:12})
cosign sign --yes "ghcr.io/peopleforrester/watch-it-burn@$DIGEST"

# 5. Build from the mirror, not from huggingface.co.
#    Replace the snapshot_download block in images/llm-guard/Dockerfile with a
#    stage that runs: oras pull ghcr.io/peopleforrester/watch-it-burn@$DIGEST
#    then: COPY --from=model /pi-model /home/user/models/prompt-injection
```

**One verified constraint: GHCR does not implement the OCI referrers API.** A referrers query
against the real digest of your llm-guard image returns
`{"errors":[{"code":"MANIFEST_UNKNOWN","message":"manifest unknown"}]}` with HTTP 404, while
`GET /v2/` on the same token returns 200. So cosign signatures and attestations on GHCR land under
the fallback `sha256-<digest>.sig` tag scheme rather than as referrers. That works. Two consequences:
do not write a verification step that queries the referrers API, and do not read an empty referrers
response as a failed signature. If you want referrers, `zot` and Harbor both support it and both are
CNCF.

### Rank 2: Object store mirror plus a checksum manifest

`aws s3 cp --recursive` the snapshot into a bucket you own, keep `pi-model.SHA256` beside it, and
have the build verify with `sha256sum -c`. This is the simplest possible thing and needs no new
tooling. It loses content-addressing, the cosign integration and the registry auth you already have,
which is the only reason it ranks below the OCI path. Durability is equivalent.

### Rank 3: Sigstore model signing, alongside either of the above

`model-signing` 1.1.1 on PyPI, Apache-2.0, published 2025-10-10, from `sigstore/model-transparency`
(Apache-2.0, 246 stars, pushed 2026-09-21). It hashes every file in a model directory into a
manifest, wraps it in an in-toto statement, signs with Sigstore keyless, and records the signing
event to the append-only transparency log.

```bash
pip install model-signing
model_signing sign   ./pi-model                            # writes model.sig
model_signing verify ./pi-model --signature model.sig
```

This is the current best practice for signing **model artifacts specifically**, as opposed to cosign
which signs the OCI wrapper. Use both: `model_signing` attests to the weights themselves and
survives repackaging, `cosign` attests to the artifact you distribute them in.

Caveat to flag: **its last release was 2025-10-10, eleven months ago**, while the repo is actively
pushed (2026-09-21). Check release cadence before depending on it for anything beyond a workshop.

### Rank 4: Private Hugging Face repo mirror (rejected as primary)

`huggingface_hub` v1.32.0 (2026-09-17) makes this trivial and your `snapshot_download` code would
not change at all. It moves the dependency rather than removing it: same provider, same outage
domain, same terms of service, same organizational risk. Acceptable as a convenience copy, wrong as
the durable one.

Useful mechanics from the current `huggingface_hub` docs regardless of which option you pick:

- `revision=` accepts a **full-length commit hash** (7-character short hashes are rejected)
- `local_dir=` writes the original file structure instead of the blob cache, which is what you want
  for a container layer
- `hf download --dry-run` reports what would be fetched and how many bytes, which is a cheap
  pre-flight in CI
- `hf_xet` replaced the deprecated `hf_transfer` as the fast download path, and it queries the CAS
  by **the LFS SHA256 of each file**, which is the same hash you pin against

### Rank 5: Git LFS, DVC, MLflow, Kubeflow Model Registry (real, but oversized here)

Kubeflow Model Registry (v0.3.17, 2026-09-21) and MLflow (28,096 stars, actively pushed) are genuine
registries with lineage, staging and promotion. For a single 1.4 GB classifier that ships inside one
container image, each is a new system to run, back up and patch. Revisit if the workshop ever serves
more than one model. DVC carries the stewardship note above.

### Rank 6: KServe modelcars (only if you move to InferenceService)

Verified from `kserve/website`, `versioned_docs/version-0.20/model-serving/storage/providers/oci.md`.
Modelcars is **not enabled by default**. You turn it on by patching the `storageInitializer` key in
the `inferenceservice-config` ConfigMap and restarting the controller:

```bash
config=$(kubectl get configmap inferenceservice-config -n kserve -o jsonpath='{.data.storageInitializer}')
newValue=$(echo $config | jq -c '. + {"enableModelcar": true, "uidModelcar": 1010}')
# then kubectl patch the ConfigMap and delete the controller pod
```

Build the image with the model at `/models`:

```dockerfile
FROM busybox
RUN mkdir /models && chmod 775 /models
COPY data/ /models/
```

Reference it with the `oci://` scheme:

```yaml
spec:
  predictor:
    model:
      modelFormat: { name: sklearn }
      storageUri: oci://myuser/mymodel:1.0
```

The docs are explicit that you must use a **specific tag rather than `latest`**, because `latest` (or
no tag) forces `imagePullPolicy: Always`, which re-downloads the model on every pod restart and
scale-up and destroys the local caching that is the entire point of the feature. Not applicable to
your current guard-proxy architecture, but it is a reason to prefer the Rank 1 OCI path if that ever
changes.

## 2.4 The same question for Python packages and the base image

### PyPI

**Tamper-evidence.** Verified working on this box with `uv 0.11.21`:

```bash
uv pip compile requirements.in --generate-hashes -o requirements.lock
# produced 1,582 sha256 hashes across the 98-package core resolution
```

**Availability.** Hashes prove a wheel is the one you expected; they do not help if PyPI is
unreachable or a project is yanked. For that, build a wheelhouse into the image or a bucket:

```bash
pip download -r requirements.lock --require-hashes -d ./wheelhouse
pip install --no-index --find-links ./wheelhouse -r requirements.lock
```

Scope it with `--platform` and `--only-binary=:all:` or the wheelhouse carries the full 3.4 GB
torch and CUDA payload.

**A running mirror** is the heavier option: **devpi** (1,223 stars, pushed 2026-08-10; the GitHub API
reports no SPDX license, so read `LICENSE` in-tree before adopting) or Artifactory (vendor). For a
workshop, the wheelhouse is the right size of solution.

### Base and third-party images

`crane` is already installed. Mirror by digest and keep the digest:

```bash
SRC=python:3.12-slim
D=$(crane digest $SRC)
crane copy "$SRC@$D" ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim
crane copy "$SRC@$D" "ghcr.io/peopleforrester/watch-it-burn@$D"   # keep it digest-addressable
```

Then reference `ghcr.io/peopleforrester/watch-it-burn@sha256:...` in `gitops/`, not the tag. You
already do the copy. You are missing the digest. `skopeo copy` does the same job if you prefer it.

Start with the one you have: `llm-guard-0.3.16-offline.2` is
`sha256:ec8ead8acca5c3f76cd2db192ad3d62c4651fe5ce61cc073021c27b98c9f845a` as of 2026-09-22. Note it
is an OCI image **index** (`application/vnd.oci.image.index.v1+json`) with a linux/amd64 manifest at
`sha256:a276564799dfc2ba991c30ffd8dbc6e68df55a6182df32f3a3ea12a729b55167`. Pin the index digest, not
the per-platform one.

## 2.5 Licensing checklist for redistributing the model in a public image

### What the licenses actually are

- `protectai/deberta-v3-base-prompt-injection-v2`: **Apache-2.0**. A full `LICENSE` file (10,172
  bytes, the standard Apache License 2.0 text) is in the repo. **There is no `NOTICE` file** in the
  file listing.
- Its base model `microsoft/deberta-v3-base`: **MIT** (HF API `cardData.license`). The lineage
  carries two licenses.
- The model card lists seven training datasets with their own terms. Those govern the training, not
  your redistribution of the weights, but a downstream user may ask about them.

### Obligations when you bake the weights into a public image

| # | Obligation | Source | Status in your build |
|---|---|---|---|
| 1 | Ship a copy of the Apache-2.0 license text with the distribution | Apache-2.0 section 4(a) | **MISSING.** `allow_patterns` excludes `LICENSE` |
| 2 | Retain all copyright, patent, trademark and attribution notices from the source | Apache-2.0 sections 4(b), 4(c) | **MISSING.** `README.md`, the model card, is excluded too |
| 3 | Include the `NOTICE` file contents if one exists | Apache-2.0 section 4(d) | **N/A.** No NOTICE file exists upstream, so no obligation |
| 4 | State that you changed the files, if you did | Apache-2.0 section 4(b) | **APPLIES.** Your build moves `onnx/model.onnx*` to the directory root so `model_path` loading works. That is a modification of the layout and should be stated |
| 5 | Carry the MIT notice for the base model | MIT terms | **CHECK.** MIT requires the copyright and permission notice travel with the Software. The derived weights ship under Apache-2.0, the license Protect AI chose, so retaining their `LICENSE` and model card satisfies the practical case |
| 6 | Do not use "Protect AI" or "Palo Alto Networks" marks to imply endorsement | Apache-2.0 section 6 | **FINE.** Your image tag is `watch-it-burn:llm-guard-*`, which names the project, not the vendor |

**Baking Apache-2.0 weights into a public container image creates no obligation beyond items 1, 2
and 4.** Apache-2.0 is not copyleft. There is no source-disclosure trigger and nothing propagates to
the rest of the image or to the other software in it.

### The fix

```dockerfile
# 1. Add LICENSE and README.md to the snapshot_download allow_patterns, then:
COPY --from=model /pi-model/LICENSE   /licenses/deberta-v3-base-prompt-injection-v2.LICENSE
COPY --from=model /pi-model/README.md /licenses/deberta-v3-base-prompt-injection-v2.model-card.md
COPY MODIFICATIONS                    /licenses/deberta-v3-base-prompt-injection-v2.MODIFICATIONS

LABEL org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2" \
      org.opencontainers.image.revision="90c9989b1a342275dd0d1a95aad283c04e075671"
```

`MODIFICATIONS` needs one line: the ONNX files were relocated from `onnx/` to the model root so that
llm-guard's `model_path` parameter loads them with `local_files_only`.

## 2.6 Integrity checklist

| Layer | What to pin | Value or command |
|---|---|---|
| Model revision | HF commit SHA | `revision="90c9989b1a342275dd0d1a95aad283c04e075671"` (full length; short hashes are rejected) |
| Model weights | LFS sha256, readable without downloading | `model.safetensors` = `6521cb8d0ac08148c81464899c424e6148fcc62befa371089fa4061d8b6e0424` (737,719,272 B); `onnx/model.onnx` = `f0ea7f239f765aedbde7c9e163a7cb38a79c5b8853d3f76db5152172047b228c` (738,563,188 B) |
| How to read those | | `curl -s https://huggingface.co/<repo>/raw/main/<file>` returns the Git LFS pointer, which carries `oid sha256:...` and `size`. No download required. |
| Model directory | in-toto manifest, Sigstore keyless | `model_signing sign ./pi-model` then `model_signing verify ./pi-model --signature model.sig` |
| OCI artifact | digest plus signature | `crane digest`, reference `@sha256:...`, `cosign sign`. Fallback tag scheme on GHCR, not referrers. |
| Python deps | per-wheel sha256 | `uv pip compile --generate-hashes`, install with `--require-hashes` |
| Base images | digest | `crane copy src@digest`, reference `@sha256:` in `gitops/` |
| Your own images | digest | `llm-guard-0.3.16-offline.2` = `sha256:ec8ead8acca5c3f76cd2db192ad3d62c4651fe5ce61cc073021c27b98c9f845a` |

Current best practice for signing model artifacts specifically is the Sigstore model-transparency
route, because the signature covers a per-file hash manifest of the weights and therefore survives
repackaging: the weights can move from an HF snapshot to an OCI artifact to a container layer and
the same signature still verifies. Use cosign in addition, for the distribution wrapper.

---

# What I could not verify

- **WebSearch was unavailable for this entire report.** The session had exhausted its 50-call budget
  before this task started. Everything above is verified against the GitHub API, `cncf/landscape`
  `landscape.yml`, PyPI, OSV, the Hugging Face API, and WebFetch of canonical documentation pages.
  No general web search was run. Anything a search would have surfaced that is not in those sources
  is absent here. This matters most for section 1.6: my statement that I found no successfully
  sustained community fork of a deliberately retired security tool is a statement about my sources,
  not a proof of absence.
- **Archive dates for `llm-guard` and `rebuff`.** GitHub's API returns `archived_at: null` for both,
  so I can date the last push and the last commit but not the archive action itself, and I cannot
  attribute either archive to PAN rather than to Protect AI.
- **ModelPack's current spec version number.** Neither `modelpack.org` nor `modelpack/model-spec`
  states one, and the spec repo has published no releases. The media types above are read from
  `docs/spec.md` on `main`.
- **KitOps ModelKit spec version.** The docs page says v0.1 with no date.
- **Whether GHCR plans referrers API support.** I measured that it does not have it today (404
  `MANIFEST_UNKNOWN` on a real digest while `/v2/` returns 200). I have no roadmap source.
- **The Aidealy fork's location, license and terms.** Not on PyPI under the obvious names, not in
  the public fork list, and its filer `orenk9` has no public repositories. Everything I have about
  it comes from the text of issue #347.
- **Whether the 21 GitHub-reported contributors and the 27 git authors reconcile exactly.** They
  differ because of unmatched email identities. The 81% single-author figure holds under either
  count.
- **The brief's "54 forks pushed since the archive."** I measured 60 unique out of 326 unique forks.
  The delta is consistent with a different measurement date and with GitHub's fork listing returning
  duplicate rows under pagination (467 rows, 326 distinct names). Not material to any conclusion.
- **`devpi`'s license.** The GitHub API reports no SPDX identifier. Read `LICENSE` in-tree before
  adopting it.
