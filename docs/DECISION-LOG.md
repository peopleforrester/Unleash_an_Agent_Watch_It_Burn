# Decision Log and Verification Corrections

Two records in one place:

1. **Verification corrections** — claims we asserted (usually "X is absent / not working") that
   flipped, or whose evidence turned out invalid, once we searched properly. This section exists
   because we kept concluding absence from a narrow or truncated query. Read it before asserting a
   negative.
2. **Key decisions** — technical decisions and the *evidence* behind them, so a later session can
   trace why, not just what.

---

## Methodology rule (the lesson that created this file)

When a query returns "absent" / "not found" / "zero", that is evidence about the QUERY, not about
reality. Before asserting the thing does not exist or does not work:

- **Re-test with a targeted query**, not a broad `OR` or wildcard. An `OR` filter can silently
  under-match; a wildcard can be truncated.
- **Check for row-limit truncation.** If a result count exactly equals the page limit (e.g. 100 rows
  for a limit of 100), the result is truncated and proves nothing about anything past the cutoff.
- **Widen the time window** and **check alternate names / IDs** (a service may report under a
  different `service.name`, a secret under a different region, a file under a moved path).
- **Cite the exact query or command** as the evidence for the claim, positive OR negative. "Not
  there" with no cited query is not a finding.

Distinguish "my query did not match" from "the thing does not exist." Only the second is a finding,
and only after the steps above.

---

## Verification corrections

| Date | Claim asserted | Reality | What revealed it | Lesson |
|---|---|---|---|---|
| 2026-06-26 | guard-proxy OTel SDK "not injected" | It WAS injected (full `OTEL_*` env + `opentelemetry-auto-instrumentation-python` init container) | The jsonpath ran mid-rollout and read a transient pod; a robust dump of all container env on the settled pod showed the injection | Do not query during a rollout; read the settled pod; print all of a list, not one key |
| 2026-06-26 | guard-proxy spans "not in Datadog APM" | They WERE there (10 spans) | The filter `service:(guard-proxy OR agentgateway OR kagent)` returned only kagent; a broad search showed `guard-proxy: 10` | An `OR` filter can under-match; confirm with a single-service targeted query |
| 2026-06-26 | agentgateway "emits zero spans" (conclusion correct, first evidence INVALID) | Conclusion true, but the first search did not prove it | The broad `*` search was LIMIT-TRUNCATED: kagent 90 + guard-proxy 10 = the 100-row limit, leaving no room to even see agentgateway. Only a TARGETED `service:agentgateway` (= 0) plus `-service:kagent -service:guard-proxy` (= `{}`) actually confirmed it | A count that equals the page limit is a red flag; confirm negatives with a targeted query, never a truncated broad one |
| 2026-06-26 | agentgateway tracing key is bare top-level `tracing` (WRONG twice) | It is `config.tracing` (under the top-level `config` block). frontendPolicies.tracing crashes one way, bare `tracing` crashes another | The v1.3.0 JSON schema example literally showed `config:` then `tracing:`, and I dismissed the `config:` wrapper as illustrative. The live binary settled it: `Error: tracing: unknown field tracing, expected one of config, binds, frontendPolicies, ...` | Trust the schema example's nesting verbatim; when in doubt, the binary's own "expected one of ..." error enumerates the valid keys |

Add a row whenever a "not there / not working" assertion is later corrected, or whenever its first
evidence is found to be invalid even if the conclusion stood.

---

## Key decisions (with evidence)

| Date | Decision | Evidence |
|---|---|---|
| 2026-06-26 | agentgateway v1.3.0 image registry is `cr.agentgateway.dev`, not `ghcr.io` | GitHub releases API; kubelet event "Successfully pulled image cr.agentgateway.dev/agentgateway:v1.3.0" on `1002` |
| 2026-06-26 | agentgateway config-file key `frontendPolicies.tracing.otlpEndpoint` is rejected by the v1.3.0 binary | Pod crash log: `Error: frontendPolicies.tracing: no variant of enum SimpleLocalBackend found`. The OTLP **env** path also yields nothing: targeted `service:agentgateway` = 0 spans on the live cluster. Correct tracing schema is unresolved. |
| 2026-06-26 | agentgateway guardrails do not attach to a non-LLM A2A backend; guarding stays on guard-proxy | Official v1.3.0 standalone docs document guardrails only under `llm.models[]` with a recognized provider |
| 2026-06-26 | Bedrock model IDs ACTIVE in accen-dev/us-west-2: haiku-4-5, sonnet-4-6, opus-4-8 | `aws bedrock list-inference-profiles` (all three returned ACTIVE) |
| 2026-06-26 | Workshop default model is Sonnet 4.6 (`bedrock-sonnet`) | Live on `1002`: `agent.spec.declarative.modelConfig = bedrock-sonnet`; requests return ~981-token Sonnet replies |
| 2026-06-26 | guard-proxy -> agentgateway hop works end-to-end | `1002`: A2A `message/send` through guard-proxy returns a real Bedrock reply; the guard-proxy `agent.forward` CLIENT span targets `http://agentgateway.agent.svc.cluster.local:3000/` (cited from the spans API) |
| 2026-06-26 | Cost metric is `gen_ai.client.cost` (gen_ai namespace), NOT a custom `witb_cost_usd` tree. Tokens use the standard `gen_ai.client.token.usage`. | OTel GenAI metrics spec (`semantic-conventions-genai`) defines `gen_ai.client.token.usage` and NO monetary metric, so cost is a project suffix under the standard tree. `gen_ai.client.token.usage` is already in Datadog (metric search). Removed the witb_cost_usd Prometheus `/metrics` endpoint + scrape annotation; emit `gen_ai.client.cost` via OTLP (same pipeline as the spans). |

Add a row for each load-bearing decision with the command or query that backs it.
