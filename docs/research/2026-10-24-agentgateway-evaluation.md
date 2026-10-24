<!-- ABOUTME: Evaluation of agentgateway (#239): what traffic it carries, whether C7's tool control should
     ABOUTME: move onto it, and whether it can cover the post-approval rug-pull (#117). Static, from git and docs. -->
# agentgateway: is it earning its place, and should C7 live on it? (#239)

Michael, 2026-09-05: *"Agent Gateway and Chat UI are not being used, really? Let's file issues for each
of those individually to evaluate whether they could be useful."*

The issue asked three things: does any traffic reach the gateway, could C7 be stronger with it, and
should it either become what the student configures in C7 or be removed. This evaluation answers them
from the repository at `d08b572` (2026-10-24), agentgateway's v1.5.0 schema vendored at
`verify/schemas/agentgateway-v1.5.0-config.json`, and agentgateway's published docs, all read on
2026-10-24. This run could not provision a cluster, so the traffic numbers are Michael's own measurement
from 2026-09-05, on the issue.

## Recommendation

1. **Keep agentgateway.** Every chat message and every workshop-mcp tool call goes through it.
   Removing it means re-pointing guard-proxy's `AGENT_URL` and the `workshop-mcp` RemoteMCPServer, and
   it drops the hosted-or-local model switch from #394.
2. **Keep C7 on the kagent `toolNames` allow-list.** A gateway rule would filter tools by name, and that
   is exactly what `toolNames` already does. Moving the control would put the student's edit on the
   component every challenge depends on, and C7's defence would be no stronger for it.
3. **The gateway's real case is #117, the rug-pull.** Neither `toolNames` nor the gateway's CEL
   authorization can see a tool's description. agentgateway's ExtMCP processor chain can, on the
   `tools/list` response. It is the one place in the stack where "pin the tool definitions at approval
   and refuse on mismatch" can be built without changing kagent. #117 is deferred to Barcelona, so this
   belongs in that design, not in Portland's C7.

The decision is Michael's. Nothing above changes what Portland ships.

## 1. What reaches the gateway today

The issue said the gateway was on no challenge's path. Michael's comment on the issue corrected that:
on a fresh attendee-profile cluster (`watch-it-burn-pres-michael`, 2026-09-05) it logged 386 request
lines in its first hour. The manifests agree, with one correction to the #236 audit:

| Port | Traffic | Through the gateway? | Where |
|---|---|---|---|
| 3000 | every chat message, guard-proxy to workshop-agent over A2A | **yes, always** | `resources.yaml` guard-proxy `AGENT_URL`; `agentgateway.yaml` bind 3000 |
| 3001 | every workshop-mcp tool call (all of BurritoBot's real tools) | **yes, always** | `workshop-mcp` RemoteMCPServer `url: http://agentgateway.agent:3001/mcp` |
| 3002 | model calls | **only if a cluster is switched** to `gateway-bedrock-nova` or `gateway-local-qwen3` | the Agent's committed `modelConfig` is `bedrock-nova`, `provider: Bedrock`, which calls Bedrock directly |
| 3003 | evil-mcp, C7's rogue tools (since #514; this row read "none, no" when written) | **yes, always** | `evil-mcp` RemoteMCPServer `url: http://agentgateway.agent:3003/mcp`; the `agentgateway-c7` container |

**Note (2026-10-25, #514).** The last row changed after this evaluation was written. evil-mcp now goes
through the gateway on its own bind (:3003), served by a second agentgateway container from its own
ConfigMap, `agentgateway-c7-config`, with one target so the tool names are not prefixed. That bind's
`mcpAuthorization` rule is committed `'true'`, so it gates nothing yet. The rest of this evaluation is as
written on 2026-10-24.

The #236 audit says "every model call: both kagent ModelConfigs, port 3002". The two gateway
ModelConfigs exist, but nothing binds the agent to either of them: no script, overlay or bootstrap
patches `modelConfig` to a `gateway-*` name. By default the gateway carries no inference.

`verify/test_agentgateway_path.py` now pins all four rows, so whichever one changes first fails the
offline suite rather than leaving this table, and the conclusion below, quietly wrong.

### What the gateway does to that traffic

It forwards. It enforces nothing:

- The 3001 route's `mcpAuthorization` is the single rule `'true'`, which allows everything.
- No prompt guard, rate limit or budget is configured on any bind. The input and output guards and the
  C4 budget cap are all in guard-proxy. When the terminal's C4 message says "a spend cap at the gateway",
  the gateway it means is guard-proxy.
- It forwards the `X-Agent-Identity` header that `tool_audit.py` stamps on workshop-mcp's audit lines
  (#190). That works because it passes the header through, not because it adds anything.
- It exports OTLP spans as `burritobot-gateway`, the middle hop of the Service Map chain from PRD #27.

**Can a student see it?** Only as that Service Map node. The lab names agentgateway once, as an
allowed image registry in C2 (`lab.html:429`). No challenge, tour step or badge points at it.

## 2. Could C7 be stronger with it?

### What C7 defends against

The rogue server `evil-mcp` serves `get_weather`, whose description and result tell the model to call
`read_internal_config`. The student's fix narrows evil-mcp's `toolNames` to `[get_weather]`, so kagent
leaves the rogue tools out of the agent's tool set. The "Tool allow-list" badge comes from guard-proxy's `/controls`,
which reads the Agent object. The `guard-proxy-reader` Role grants `get` on `agents/workshop-agent` and
nothing else for C7.

### The same control on the gateway

agentgateway's `mcpAuthorization` is allow-only CEL, OR-combined and implicitly denying. Its documented
request-time variables are `mcp.tool.name`, `mcp.tool.target`, `mcp.prompt.name`,
`mcp.resource.name`, `mcp.methodName` and JWT claims. A tool the rules do not allow is also filtered out
of the `tools/list` response
([standalone MCP authz reference](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/mcp-authz.md)).
A C7 rule would read `mcp.tool.name == "get_weather"`.

Against C7's attack that is the same control in a different place. Both of them filter by tool name.
The gateway adds a few things C7 does not use:

- It checks every `tools/call` on the wire, not only the tool set kagent renders.
- One policy can cover several agents, and with a JWT it can differ per agent.
- Each denial shows up in the gateway's own log and spans.

C7 has one agent, no MCP authentication and a lesson about the allow-list.

### What moving it would take

| Step | Cost |
|---|---|
| Route evil-mcp through the gateway | Either a second target on the 3001 backend or a new bind. A second target on 3001 multiplexes two servers, and under the default `prefixMode` the tool names get prefixed with the target name, which renames the tools the poisoned description refers to. A separate bind avoids that |
| The student edits the gateway config | It is one `config.yaml` key inside the `agentgateway-config` ConfigMap, not a one-line `kubectl patch` of a list. A broken edit lands on the component carrying every chat message, so a typo in C7 takes BurritoBot down for C1 to C8. Whether the binary keeps the last good config on a bad reload is not documented |
| The change takes effect | The docs say routes and policies update dynamically, but not whether the standalone binary watches its file. A ConfigMap volume update also waits on kubelet's sync, so somebody would have to measure the delay live. The `toolNames` patch has been measured at about 30 to 60 seconds |
| ArgoCD stops reverting it | `ignoreDifferences` would have to cover the whole `config.yaml` key, because the config is one string. That takes the A2A, MCP and LLM routes out of GitOps on every cluster, for one challenge |
| The badge reads it | guard-proxy-reader needs `get` on `configmaps/agentgateway-config`, and `/controls` has to parse the YAML and judge a CEL string, where today it compares a list |

Running a second, C7-only agentgateway in front of evil-mcp would contain the blast radius and the
ArgoCD scope, but that brings back the extra component this issue set out to question.

**Verdict for C7:** it would be no stronger, and it would be harder to type and riskier to get wrong. Keep `toolNames`.

## 3. The rug-pull (#117): where the gateway would earn a place

#117's attack: a tool is approved, then its **description** changes while its **name** stays the same.

- `toolNames` filters by name, so it cannot catch this. #117 already says so.
- `mcpAuthorization` cannot catch it either. No documented CEL variable carries a tool's description,
  so a rule cannot tell an approved definition from a changed one with the same name.
- **ExtMCP guardrails can.** `mcpGuardrails.processors` is an ordered chain of remote gRPC policy
  servers, modelled on Envoy `ext_authz`, keyed by JSON-RPC method, with a request or response phase.
  `tools/list: response` is the documented example. A processor can pass, mutate or deny the result,
  and it fails closed by default
  ([ExtMCP about](https://agentgateway.dev/docs/standalone/latest/documentation/mcp/guardrails/about.md);
  `McpGuardrails`, `Processor` and `Phase` in the vendored v1.5.0 schema). agentgateway ships no
  built-in processor: the only kind is `remote`.

A processor that hashes each tool's name, description and input schema, compares the hashes against a
pinned baseline and rejects or strips the tools that changed is #117's proposed control: "pin a hash of
the tool definitions at approval and refuse on mismatch." The student would configure it, and the badge
could read the pin. That is the role the issue asked about: the gateway is "the thing the student
configures", and it catches an attack nothing else in the stack can catch.

What it costs, for the Barcelona design:

- a small gRPC ExtMCP server, which we write;
- evil-mcp routed through a gateway bind;
- a live check that kagent's tool discovery and the agent's own `list_tools` both pass through the
  response phase, and how kagent behaves when `tools/list` returns a JSON-RPC error;
- the same ArgoCD-scope and blast-radius questions as section 2, which a dedicated bind or instance
  answers.

**Spiked in #480** (`2026-10-24-tool-pin-spike/README.md`). The processor works against the v1.5.0
binary on a local bed: it strips or denies a rug-pulled `get_weather`, and on its own bind it fails closed
without affecting the other binds. The bed also settled two of section 2's unknowns. The binary watches
its config file, and it keeps the last good config when a reload is bad. It still exits on a bad config
at startup. kagent's side is read from source and has not yet been checked live.

## Not changed by this evaluation

- No manifest behaviour changed. The commit fixes four comments that stated the old routing: the
  `agentgateway.yaml` header, two in `resources.yaml` and the toggle's "WHY" block.
- The `agent/gateway/` overlays (`agentgateway.yaml`, `mcp-authz-on.yaml`, `mcp-authz-off.yaml`) were the
  pre-gitops v1.2/v1.3 config shape and nothing applied them. `verify/test_beat3_mcp.py` asserted its
  "after" state against `mcp-authz-on.yaml` instead of the deployed toggle. Both were fixed in #479: the
  overlays are deleted and the test reads the toggle's ON-state `toolNames`.
