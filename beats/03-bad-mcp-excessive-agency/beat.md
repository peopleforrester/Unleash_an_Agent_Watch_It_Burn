*Attendee instructions for Beat 3 — when the agent trusts a tool it never should have.*

# Beat 3 — The tool that talked the agent into it

Your agent has been wired to an extra tool server so it can answer a simple
question. You did not write that server, and neither did the platform team. One of
its tools carries a hidden instruction inside its own description — the kind of text
your agent reads to decide what a tool is for.

## Step 1 — Ask the innocent question

Ask your agent the question in `agent-prompt.txt`. It looks harmless: you want one
small piece of information the tool server can provide.

Watch the trace view. The agent answers your question — and then keeps going. The
poisoned tool description steered it into calling a second tool you never asked for,
`read_internal_config`, and the value that tool returns
(`FAKE-MCP-EXFIL-sentinel-4c1d`) lands right in the agent's reply. The agent did
something it was never asked to do, because a tool told it to.

## Step 2 — Switch on tool authorization

The facilitator applies one rule at the gateway: a deny on that tool by name. The
gateway now sits between the agent and the tool server and decides which tool calls
are allowed to reach it.

Ask the exact same question again. The poisoned description still tries its trick,
but the call to `read_internal_config` never reaches the server. The sentinel does
not appear. The agent answers only what you actually asked.

## What to take away

Nothing in the cluster control plane saw this attack. It rode in on a tool
description and a tool call — natural language and a function name. The control that
caught it is tool-level authorization at the gateway: an allow/deny list over which
tools the agent may actually call, independent of what any tool *claims* it should do.

See `governance-map.md` for the layer this control lives in, and `BUILD-SPIKE.md` for
how this beat was verified before the event.
