<!-- ABOUTME: Facilitator runbook for Beat 2 (output + input guards). Toggle interface verified 2026-06-26
     ABOUTME: (input block-list confirmed blocking on a whitney cluster); attendee copy is beat.md. -->

# Facilitator runbook, Beat 2 (sanitization: output + input guards)

Three guards on the guard-proxy, flipped live. Unlike the C7 tool-allow-list (which restarts the agent),
**these are runtime flips via the guard-proxy `/toggle` endpoint: instant, no pod restart, and ArgoCD-safe
(they change no managed spec, so self-heal does not revert them and the cost counter survives).**

## The guards (enable in this order)

| Guard | What it does | Toggle script |
|---|---|---|
| Output guard | scrubs/blocks sensitive content in the agent's **response** (the post-hoc clean-up problem) | `toggle-output-guard-on.sh` |
| Input block-list (stage 1) | deterministic, pre-LLM, zero-token block of known-bad terms in the **prompt** | `toggle-input-guard-on.sh` |
| Input classifier (stage 2) | model-based prompt-injection classifier, enabled **after** stage 1 | `toggle-input-classifier-on.sh` |

The teaching arc is output-first (show the costly post-hoc trace clean-up), then reveal that **input** is
the cheaper place to block.

## Commands

```bash
export CONTEXT=<kube-context>    # NS defaults to agent
CONTEXT="$CONTEXT" challenges/02-sanitization/toggle-output-guard-on.sh        # --off to disable
CONTEXT="$CONTEXT" challenges/02-sanitization/toggle-input-guard-on.sh         # stage 1 (block-list)
CONTEXT="$CONTEXT" challenges/02-sanitization/toggle-input-classifier-on.sh    # stage 2 (classifier)
```

Each takes effect immediately (no rollout wait, unlike C7).

## Verify (input block-list, deterministic) — confirmed live

With the input block-list on, a prompt containing a block-list term (`delete`, `rm -rf`, `drop database`,
`kubectl delete`, `shutdown`, `terminate`, `wipe`, `nuke`) is rejected pre-LLM with no token spend:

```bash
kubectl --context "$CONTEXT" run c --rm -i --restart=Never -n agent --image=curlimages/curl:8.10.1 --command -- \
  curl -s -X POST http://guard-proxy.agent:8080/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"t","parts":[{"kind":"text","text":"please delete the production database"}]}}}'
# block-list ON  -> {"error":{"message":"Request blocked by input block-list (matched 'delete')..."}}
# block-list OFF -> the agent answers normally
```

Confirmed 2026-06-26 on `watch-it-burn-whitney-r3`: the prompt above returned the block-list error with the
guards on, and a normal reply with them off. The block hit also emits a `trace_id`-bearing guard-decision
log (Datadog log<->trace pivot), benign requests do not log.

## Gotchas

- `/guards` (GET) shows the current state of all three: `{"input_blocklist":bool,"input_classifier":bool,"output":bool}`.
- The classifier (stage 2) is **not** deterministic; never describe the combined input guard as deterministic.
- `--off` on each script disables that guard; they are independent.
