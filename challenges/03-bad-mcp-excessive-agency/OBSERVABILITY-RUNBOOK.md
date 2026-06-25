# Observability Runbook (PRD #22 M4)

Facilitator runbook for the two observability beats that ride on top of the security beats:
the **rogue MCP tool-call** (Beat 3, this directory) and the **re-leak trap** (the sanitization
beat's two-act teardown). Covers what the attendee sees in Datadog, the exact instructor
commands, and the verify-at-build findings from the live dry run on `watch-it-burn-attendee-001`
(2026-06-25).

Everything below was verified live against Tempo (the Collector's secondary trace sink, which
receives the identical spans Datadog does), so the trace shapes and redaction behavior are
confirmed, not assumed.

---

## Beat 3: rogue MCP tool-call waterfall (Datadog APM)

**No instructor action required.** kagent/ADK emits the gen_ai trace natively; the attendee just
asks the question in `agent-prompt.txt` and watches the trace.

### What the attendee sees

The trace waterfall under service `kagent`:

```
invoke_agent workshop_agent
  └─ call_llm
       └─ chat us.anthropic.claude-haiku-4-5-...   (gen_ai.operation.name = chat)
  └─ execute_tool <tool_name>                       (gen_ai.tool.name = <tool_name>)
```

When the poisoned tool description induces the agent, the rogue call appears as
`execute_tool read_internal_config` and the sentinel `FAKE-MCP-EXFIL-sentinel-4c1d` lands in the
reply. After the facilitator switches on tool authorization (Step 2 of `beat.md`), the
`read_internal_config` call never reaches the server and the sentinel does not appear.

### Verified 2026-06-25

- ADK emits `execute_tool {tool_name}` spans with `gen_ai.tool.name` set to the tool name.
  Confirmed with a benign `execute_tool list_pods` span in trace `58258a10cbf7811e95a6b071fe338020`,
  showing the full `invoke_agent → call_llm → chat → execute_tool` waterfall.
- **Induction is probabilistic on Claude Haiku.** Four consecutive runs of the `agent-prompt.txt`
  weather prompt did not take the bait (the model noticed it has no weather tool and listed its
  real tools instead). This matches the caveat already documented in `agent-prompt.txt`. The
  deterministic proof of the deny rule is `fallback.curl.sh`, not model induction. Do not rely on
  the bait firing live; lead with the curl fallback if a clean rogue-call trace is needed on stage.
- **Tool-result capture: verify-at-build, accepted state = caller-side tool name only.** The
  `execute_tool` span carries `gen_ai.tool.name` (the tool that was called). It does not carry the
  tool's return value as a semconv attribute. The Beat 3 narrative only needs the tool *name* in
  the waterfall, which is present. evil-mcp-shim stays dark (meta-PRD decision); no shim-side spans.

---

## Re-leak trap: the two-act teardown

The sanitization beat captures the guard-proxy `sanitize` span's prompt content so the attendee can
see the before/after in Datadog LLM Observability. That capture is itself a leak channel:
observability became an exfil path. The two acts show the leak, then close it at the Collector.

### The arming mechanism (and why Act 2 is GitOps-only)

- **Act 1 arm/teardown is a runtime env toggle** on the guard-proxy `proxy` container. proxy.py reads
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` once at module load, so flipping it requires a
  pod restart, which `kubectl set env` triggers. The ArgoCD `ai-layer` Application carries an
  `ignoreDifferences` for `select(.name=="proxy") | .env`, so this env edit survives selfHeal. This
  is the intended instructor toggle: reversible, no commit.
- **Act 2 (the Collector redaction) is GitOps-only.** The cluster's kyverno `block-argocd-drift`
  policy rejects direct edits to the ArgoCD-managed Collector ConfigMap (`This resource is managed by
  ArgoCD. Change it in Git, not in the cluster.`). So the OTTL redaction toggle must go through Git:
  add the `transform/redact_sentinel` processor to `gitops/apps/otel-collector.yaml` and let ArgoCD
  sync. Canonical source for the processor is `gitops/apps/otel-collector-act2-overlay.yaml`. Commit
  to flip to Act 2; revert the commit to return to Act 1.

### Act 1: arm capture, show the leak

```bash
KCFG=/tmp/watch-it-burn-attendee-001.kubeconfig
CTX=arn:aws:eks:us-west-2:<ACCOUNT_ID>:cluster/watch-it-burn-attendee-001
AWS_PROFILE=accen-dev KUBECONFIG="$KCFG" kubectl --context "$CTX" -n agent \
  set env deploy/guard-proxy -c proxy OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY
AWS_PROFILE=accen-dev KUBECONFIG="$KCFG" kubectl --context "$CTX" -n agent \
  rollout status deploy/guard-proxy
# Run a prompt through guard-proxy (chat-ui, or POST an A2A message/send to guard-proxy:8080).
```

**Expected in Datadog LLM Observability:** the `sanitize` span (`gen_ai.operation.name=chat`) shows
the original prompt in `gen_ai.input.messages` and `gen_ai.output.messages`. The proxy forwards the
prompt unchanged, so input and output are equal here; that is the leak.

Verified 2026-06-25 (trace `97d2eef4003e3eba4adf56cdd59433e`): both attributes carried the sentinel
`DEMO-SENTINEL-ACT1-9f3c2a`.

### Act 2: redact at the Collector, show the fix

Flip the toggle in Git (the only allowed path), then let ArgoCD sync:

```bash
# In gitops/apps/otel-collector.yaml, add transform/redact_sentinel to processors AND to the
# traces pipeline processors (last, before exporters); see otel-collector-act2-overlay.yaml.
git commit -am "flip re-leak-trap to Act 2" && git push origin staging
AWS_PROFILE=accen-dev KUBECONFIG="$KCFG" kubectl --context "$CTX" -n argocd \
  annotate application otel-collector argocd.argoproj.io/refresh=hard --overwrite
# The Collector ConfigMap gains the transform and the DaemonSet rolls to pick it up (~40-60s).
# Re-run the same prompt.
```

**Expected in Datadog:** the `sanitize` span now shows `gen_ai.input.messages = "[DEMO-REDACTED]"`
and `gen_ai.output.messages = "[DEMO-REDACTED]"`. The attribute key is still present (the transform
replaces the value, it does not delete the key), so Datadog confirms the redaction happened and the
secret never reached the platform.

Verified 2026-06-25 (trace `20211b7a66106d17d837f7fc403521ec`): both attributes read `[DEMO-REDACTED]`;
the Act-2 sentinel `DEMO-SENTINEL-ACT2-7b1e84` never reached the trace store.

### Teardown: stop capture

Revert the Act-2 commit (returns the Collector to Act 1), then disarm content capture:

```bash
git revert --no-edit <act2-commit> && git push origin staging
AWS_PROFILE=accen-dev KUBECONFIG="$KCFG" kubectl --context "$CTX" -n argocd \
  annotate application otel-collector argocd.argoproj.io/refresh=hard --overwrite
AWS_PROFILE=accen-dev KUBECONFIG="$KCFG" kubectl --context "$CTX" -n agent \
  set env deploy/guard-proxy -c proxy OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT
```

**Expected:** subsequent `sanitize` spans keep `gen_ai.operation.name=chat` (still an LLM span) but
carry no `gen_ai.input.messages` / `gen_ai.output.messages` at all.

Verified 2026-06-25 (trace `69565ab1ba496b78c1d13ad6ba2e5741`): op=`chat`, no content attributes.

---

## Verify-at-build findings (live dry run 2026-06-25)

| Item | Finding |
|---|---|
| Beat 3 `execute_tool {tool_name}` waterfall | Confirmed. ADK emits it natively with `gen_ai.tool.name`. Verified via `execute_tool list_pods`. |
| Rogue induction reliability | Probabilistic on Haiku; did not fire in 4 runs. Use `fallback.curl.sh` for a deterministic live demo. |
| Tool-result capture on `execute_tool` | Not captured as a semconv attribute. Accepted state: caller-side tool name only (sufficient for the narrative). |
| Act 1 content capture | Confirmed: arming via `kubectl set env` (survives selfHeal via the ai-layer `ignoreDifferences` on the proxy `.env`); sentinel visible on the `sanitize` span. |
| Act 2 Collector redaction | Confirmed: OTTL `transform/redact_sentinel` replaces both message attributes with `[DEMO-REDACTED]`; key preserved. Must be applied via Git (kyverno blocks live ConfigMap edits). |
| Teardown | Confirmed: `NO_CONTENT` removes the content attributes on subsequent spans. |
| Collector to Datadog LLM-Obs routing | Open / instructor-confirmed in the UI. The spans reach Datadog via the contrib `datadog` exporter (it is the primary traces exporter) and carry `gen_ai.operation.name=chat`, which is the classification Datadog needs to render the Input/Output panel. Programmatic confirmation needs a Datadog Application key (only the ingest API key is in-cluster), so the LLM-Observability panel render is the facilitator's manual check on Whitney's Datadog org. If the contrib `datadog` exporter does not route to LLM-Obs, the fallback is a dedicated OTLP exporter with the `dd-otlp-source=llmobs` header (research/28 Q7). |
