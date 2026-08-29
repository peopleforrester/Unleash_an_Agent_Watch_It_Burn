<!-- ABOUTME: Challenge C4 (gateway) - agent runs up the Bedrock bill; the budget cap freezes it. -->
# Challenge C4: denial-of-wallet  (gateway)

**The attack:** nothing has to crash for an agent to hurt you. A room hammering the agent, or an agent
talked into a loop, runs the Bedrock bill up while everything stays green (see `agent-prompt.txt`). The
live **cost counter** on BurritoBot climbs and, on Round 1, nothing stops it. The damage is the invoice.

This is the current-attack replacement for the fork bomb (issue #114). Unlike the fork bomb, it fires
through **BurritoBot chat** (the model does not refuse an expensive-but-legitimate request), so it is the
agent itself running up the cost, and no node dies, so there is nothing to rebuild.

| Round | Outcome | Why |
|---|---|---|
| R1 (no guardrails) | bill runs away | `budget` guard off; every request reaches Bedrock, counter climbs unbounded |
| R2 (infra on) | frozen at cap | flip `budget` on live; gateway refuses once metered spend crosses `BUDGET_CAP_USD` |
| R3 (student self-serve) | student flips it | same control, exposed as `guard-budget-on` in the workbench terminal |

**Defense (guard-proxy, `gitops/ai-layer/proxy.py`):**
- A per-cluster **budget cap** (`BUDGET_CAP_USD`, default **$0.10**) metered against the same cost tally
  the counter shows.
- A **runtime toggle** (`GUARDS["budget"]`, flipped via `/toggle?budget=on` or the `guard-budget-on`
  terminal script), so the demo flips it live on Round 2 rather than through a pod-restarting env change
  that would also reset the counter.
- When tripped, the request is refused **before the model is called**, so a blocked request costs
  **zero** (`input_tokens: 0`) and BurritoBot replies that the kitchen tab is frozen.

Teaching gem: prevention is a **budget the gateway enforces**, not the model's willingness to say no.
The model happily keeps answering; the platform is what caps the spend.

**Verified live 2026-08-29** (whitney-round3): with `budget` on and the cap at $0.10, prompts 1-7 served
to a running $0.1012, prompt 8 froze at zero cost and the counter stopped climbing. Raise the cap to the
room size (`BUDGET_CAP_USD`) for the real run.
