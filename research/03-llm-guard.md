<!-- ABOUTME: Grounded research spike on LLM Guard (Protect AI, MIT) for the workshop exfil output guardrail. -->
<!-- ABOUTME: Resolves API-server mode, scanner determinism, and verdict semantics against current official docs as of 2026-06-15. -->

# LLM Guard, Research Spike (Phase 4 exfil guardrail)

## Verification Method

Web research against official Protect AI / LLM Guard docs and the `protectai/llm-guard`
GitHub repo, dated **2026-06-15**. No training data was trusted for scanner names,
config keys, image refs, or versions. Each material claim below carries its source URL.
Where two sources disagreed (e.g. Docker image name), both are recorded under Unverified.

Sources consulted:
- API deployment doc: https://protectai.github.io/llm-guard/api/deployment/
- API overview: https://protectai.github.io/llm-guard/api/overview/
- GitHub repo root: https://github.com/protectai/llm-guard
- GitHub releases: https://github.com/protectai/llm-guard/releases (empty, no GitHub releases)
- Output scanner dir listing: https://github.com/protectai/llm-guard/tree/main/docs/output_scanners
- Input scanner dir listing: https://github.com/protectai/llm-guard/tree/main/docs/input_scanners
- Secrets input scanner: https://github.com/protectai/llm-guard/blob/main/docs/input_scanners/secrets.md
- Sensitive output scanner: https://github.com/protectai/llm-guard/blob/main/docs/output_scanners/sensitive.md
- PromptInjection input scanner: https://github.com/protectai/llm-guard/blob/main/docs/input_scanners/prompt_injection.md
- DeepWiki (community-generated API/architecture summary): https://deepwiki.com/protectai/llm-guard and .../5-integration-and-deployment

---

## Verified

### API-server / deployment mode still ships (June 2026)
- LLM Guard ships a standalone REST **API server** distributed as a Docker image, intended
  for non-Python and production deployments. The server wraps all scanner functionality
  behind HTTP endpoints. Source: https://protectai.github.io/llm-guard/api/deployment/
- License: **MIT** (confirmed on repo metadata). Source: https://github.com/protectai/llm-guard
- Actively maintained as of access date (recent commits/issues/PRs; "© 2026" footer).

### Run + configure the API server
From the official deployment doc (https://protectai.github.io/llm-guard/api/deployment/):

```bash
# basic
docker run -d -p 8000:8000 -e LOG_LEVEL='DEBUG' -e AUTH_TOKEN='my-token' \
  laiyer/llm-guard-api:latest

# with mounted scanner config
docker run -d -p 8000:8000 -e APP_WORKERS=1 -e AUTH_TOKEN='my-token' \
  -v ./config/scanners.yml:/home/user/app/config/scanners.yml \
  laiyer/llm-guard-api:latest
```

- Scanners are declared in a mounted **`scanners.yml`** (the API config path is
  `/home/user/app/config/scanners.yml`).
- Env vars: `AUTH_TOKEN` (bearer auth), `LOG_LEVEL`, `APP_WORKERS`.
- App-level options seen: `lazy_load`, `low_cpu_mem_usage`, `scan_prompt_timeout`,
  `scan_output_timeout`. **>=16 GB RAM** recommended for Docker (drops fast if you
  trim scanners, relevant to the per-vCluster sizing in spec section 5).

`scanners.yml` shape (top-level `input_scanners` / `output_scanners`, each entry is
`type:` + `params:`):

```yaml
input_scanners:
  - type: Secrets
    params:
      redact_mode: "all"
output_scanners:
  - type: Sensitive
    params:
      redact: false
      threshold: 0.75
```
Source for YAML shape: scanners.yml structure as summarized from the repo config.

### Output scanners, what actually exists
Authoritative directory listing of `docs/output_scanners/`
(https://github.com/protectai/llm-guard/tree/main/docs/output_scanners) contains:
ban_code, ban_competitors, ban_substrings, ban_topics, bias, code, deanonymize,
emotion_detection, factual_consistency, gibberish, json, language, language_same,
malicious_urls, no_refusal, reading_time, regex, **sensitive**, sentiment, toxicity,
url_reachability.

- **`Sensitive` IS an output scanner.** It detects PII / sensitive entities using the
  NER + regex mechanisms from the Anonymize scanner. Params: `entity_types`
  (e.g. `["PERSON","EMAIL"]`), `redact` (bool), `threshold` (float, exposed in the API
  config), and `regex_pattern_groups_path` for custom patterns. No LLM-as-judge.
  Source: https://github.com/protectai/llm-guard/blob/main/docs/output_scanners/sensitive.md
- **There is NO `Secrets` OUTPUT scanner.** `Secrets` exists only as an **INPUT** scanner.
  This contradicts spec section 5 / Phase 4, which both name "Secrets" as an *output*
  scanner. See Risks. Confirmed by absence from the output_scanners dir listing and
  presence in the input_scanners dir listing.

### Input scanners, what exists
`docs/input_scanners/` (https://github.com/protectai/llm-guard/tree/main/docs/input_scanners):
anonymize, ban_code, ban_competitors, ban_substrings, ban_topics, code,
emotion_detection, gibberish, invisible_text, language, **prompt_injection**, regex,
**secrets**, sentiment, token_limit, toxicity.

- **`Secrets` (input):** wraps Yelp's **detect-secrets** library, high-entropy strings
  (Base64 + Hex) plus regex token plugins. **Deterministic** (pattern/entropy, no ML, no
  LLM). Params: `redact_mode` (partial / hide / hash), `detect_secrets_config` (custom
  detect-secrets config). Source:
  https://github.com/protectai/llm-guard/blob/main/docs/input_scanners/secrets.md
- **`PromptInjection` (input):** uses a **HuggingFace ML classifier**, model
  `ProtectAI/deberta-v3-base-prompt-injection-v2` (fine-tuned `microsoft/deberta-v3-base`).
  Params: `threshold` (default 0.5), `match_type` (`MatchType.FULL` etc.). **Model-based,
  not deterministic.** Source:
  https://github.com/protectai/llm-guard/blob/main/docs/input_scanners/prompt_injection.md

### Verdict semantics (how agentgateway acts on it)
- Endpoints: `/analyze/prompt`, `/analyze/output` (apply sanitization/redaction),
  and `/scan/prompt`, `/scan/output` (validation only, lower latency, no text mutation).
- Every scanner shares one interface `scan() -> (sanitized_text, is_valid, risk_score)`,
  and the API surfaces the same fields:
  - **`is_valid`** (bool), overall pass/fail; API aggregates all scanner results.
  - **`sanitized_output`** / **`sanitized_prompt`** (string), text with redactions applied.
  - **`scores`** (dict, per-scanner risk score 0–1).
- Gateway logic for the exfil beat: call `/analyze/output` on the agent response;
  if `is_valid == false` → **block**; else forward **`sanitized_output`** (redacted text)
  instead of the raw response → **redact**. This supports both the "blocked or redacted"
  outcomes the spec's Phase 4 / attack 4 allow.
  Sources: https://protectai.github.io/llm-guard/api/deployment/ ,
  https://deepwiki.com/protectai/llm-guard/5-integration-and-deployment

---

## Unverified / Could not confirm

- **Exact pinned version.** GitHub Releases page is empty
  (https://github.com/protectai/llm-guard/releases), the project does not cut GitHub
  releases. Versioning is via PyPI (`llm-guard`) and Docker image tags. PyPI page failed
  to render on fetch; the live PyPI version was NOT confirmed and must be pinned at build
  by `pip index versions llm-guard` / inspecting Docker Hub tags. Do not hardcode a number.
- **Docker image namespace.** Official deployment doc shows **`laiyer/llm-guard-api:latest`**
  (Laiyer = the company Protect AI acquired). DeepWiki could not confirm that exact string
  and references the `protectai/llm-guard` repo namespace. Resolve the authoritative image
  ref (laiyer vs protectai org) against Docker Hub at build time, and pin a digest, not
  `:latest`.
- **Scanner totals.** Sources gave 35 vs 36 (15 input + 20 vs 21 output). Cosmetic; the
  specific scanners we need are confirmed above. Not load-bearing.
- **Sensitive `threshold` at library level.** The library doc example omits `threshold`,
  but the API `scanners.yml` accepts it. Treat `threshold` as an API-config param; verify
  it is honored for `Sensitive` at build.
- **`/analyze/output` exact JSON envelope.** Field names (`is_valid`, `sanitized_output`,
  `scores`) are confirmed by the docs + DeepWiki, but the precise top-level JSON shape
  should be read off the live `http://<host>:8000/swagger.json` at build before wiring the
  agentgateway filter.

---

## Determinism note (maps to spec section 3 / section 4 design rule)

The spec's determinism rule applies **specifically to the OUTPUT exfil guardrail**
("Secrets via detect-secrets entropy plus regex, and Sensitive via NER and regex … must
not use any LLM-as-judge scanner").

| Scanner | Stage | Mechanism | Deterministic? | Fits the rule? |
|---|---|---|---|---|
| Sensitive | output | NER model + regex (PII) | Partly, regex is deterministic; the NER step is a small ML model (not an LLM judge) | YES for the spec's intent (no LLM-as-judge), but it is **not pure pattern-matching**, it loads an NER model |
| Secrets | **input only** | detect-secrets: entropy + regex | YES, fully deterministic, no ML | YES, but **NOT available as an output scanner** |
| PromptInjection | input | DeBERTa HF classifier | NO, ML model | N/A (input beat; spec rule targets output) |
| Regex | input + output | pure regex | YES, fully deterministic | YES |

Key nuance for the talk's "deterministic guardrails" thesis: **detect-secrets (the truly
deterministic, entropy+regex secret detector) is an INPUT scanner**, while on the OUTPUT
side the closest match is `Sensitive`, which catches credentials/PII via **NER (a small
ML model) + regex**. So the output guardrail is "rule/NER-based, no LLM-as-judge", which
honors the section-4 design rule (the probabilistic actor is the agent, the guard is not an
LLM), but it is not 100% pattern-only. If Michael wants the OUTPUT path to be purely
deterministic (no model at all), pair the **output `Regex` scanner** (with patterns matching
the `FAKE-PROD-DB-PASSWORD-sentinel-*` format and common secret shapes) alongside or instead
of `Sensitive`. That keeps the output guardrail demonstrably model-free for the sentinel
secret while `Sensitive` adds PII coverage.

For input sanitization beat: `PromptInjection` is model-based (DeBERTa); `Secrets` and
`Regex` inputs are deterministic. Be explicit in attendee/runbook framing that the input
injection detector is an ML classifier, not a rule engine.

---

## Risks for the build

1. **SPEC CORRECTION, "Secrets" is not an output scanner.** Section 5 and Phase 4 both
   list `Secrets` as an *output* scanner. It does not exist on the output side. The OUTPUT
   exfil guardrail must use **`Sensitive`** and/or the output **`Regex`** scanner. Update
   `agent/gateway/llm-guard-service.yaml` config and the Phase 4 verification text. This is
   the single most important finding.
2. **Determinism wording vs reality.** `Sensitive` uses an NER model. It is not an
   LLM-judge (rule honored), but it is not pure pattern-matching either. If the talk's
   payoff leans on "fully deterministic," use the output `Regex` scanner on the sentinel to
   make the demo provably model-free; keep `Sensitive` for breadth. Decide before recording.
3. **No GitHub releases → pin discipline.** No release tags exist. Pin the PyPI version AND
   a Docker image **digest** (not `:latest`) into `VERSIONS.lock` at build; the live PyPI
   version could not be confirmed in this spike.
4. **Image namespace ambiguity (`laiyer/` vs `protectai/`).** Official deploy doc uses
   `laiyer/llm-guard-api`. Confirm on Docker Hub which namespace is current/maintained
   before baking it into the manifest.
5. **16 GB RAM default footprint.** Each per-vCluster LLM Guard instance can be heavy with
   model-backed scanners (Sensitive NER, and any PromptInjection). Spec section 5 budgets
   ~1.5–2.5 GB per vCluster total, that will NOT hold if Sensitive's NER model loads per
   instance at default settings. Mitigate: enable `lazy_load` + `low_cpu_mem_usage`, run the
   output guardrail with `Regex` only (model-free) for the sentinel, or run one shared
   LLM Guard service the gateways call rather than one per vCluster. Validate RAM in Phase 2.
6. **Verdict shape must be read from live swagger.** Wire the agentgateway filter against
   `http://<host>:8000/swagger.json` at build; `/analyze/output` returns
   `is_valid` (→ block) + `sanitized_output` (→ redact) + `scores`. Confirm exact JSON
   envelope before pinning the filter mechanism in `GATEWAY-NOTES.md`.
