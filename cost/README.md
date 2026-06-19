*The live Bedrock cost counter for the "wasted tokens are the new DoS" story (BUILD-SPEC §2/§5).*

# Cost counter

## Approach (implemented in the guard proxy)
The guard proxy (`agent/gateway/guard-proxy/proxy.py`) already sits in front of the agent and sees
every A2A response, and kagent reports token usage in each one
(`result.metadata.kagent_usage_metadata`: `promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`,
confirmed live 2026-06-17). So the proxy tallies tokens and exposes:

```
GET /cost  ->  {"requests":N,"input_tokens":..,"output_tokens":..,"total_tokens":..,"usd":..}
```

`usd` = input_tokens/1k × `COST_PER_1K_IN` + output_tokens/1k × `COST_PER_1K_OUT` (env, set the real
Bedrock price for the chosen Claude model at build, currently placeholder, **verify-at-build**).

## How it tells the story
- **Cluster 1 / Cluster 2:** the counter climbs as the agent is hammered, even on Cluster 2 where
  CNCF *blocks* the damage, the tokens were already spent. "Kyverno is the last mile and the most
  expensive."
- **Cluster 3, input block-list ON:** the cheap deterministic block-list (`BLOCK_LIST` in proxy.py)
  rejects destructive intent **before** the LLM call, so `/cost` **stops climbing**. That visible flatline
  is the cost lesson: input sanitization is cheaper security.

## Authoritative number
The live counter is an estimate from token metadata × configured price. The **real** run cost comes
post-hoc from Cost Explorer via `teardown/cost-report.sh`, never hardcode a dollar figure.

## TODO (live, when cluster is up)
- Set real `COST_PER_1K_IN` / `COST_PER_1K_OUT` for the chosen model into the guard-proxy env.
- Front `/cost` on the attendee/demo UI as a ticking counter (per cluster).
- Optional: cross-check the counter against Bedrock model-invocation logging in CloudWatch.
