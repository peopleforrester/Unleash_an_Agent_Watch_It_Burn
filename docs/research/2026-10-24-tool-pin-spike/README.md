<!-- ABOUTME: The #480 spike: an agentgateway ExtMCP processor that pins tool-definition hashes (the #117 rug-pull
     ABOUTME: control), what the real v1.5.0 binary did with it on a local bed, and what the cluster check must confirm. -->
# Spike: pin tool definitions at the gateway (#480, design for #117)

#117 is the rug-pull. A tool is approved, then its **description** changes while its **name** stays the
same. The #239 evaluation (`../2026-10-24-agentgateway-evaluation.md`, section 3) found one place in the
stack that can see a description: agentgateway's ExtMCP processor chain, on the `tools/list` response.
This spike builds that processor and runs it against the real gateway.

**State on 2026-10-24.** The processor works against agentgateway v1.5.0 on a local bed. The bed ran the
release binary, evil-mcp's own `server.py` and a rug-pulled copy of it. kagent's side is read from its
v0.9.9 source, not watched live: this run had no cluster. `live-check.sh` is the cluster half. It is
written but has not been run.

## What is here

| File | What it is |
|---|---|
| `images/tool-pin/tool_pin.py` | The processor. It is a gRPC `agentgateway.dev.ext_mcp.ExtMcp` server that hashes each tool and strips or denies the ones not in the baseline. It also refuses a `tools/call` for any tool the last list did not approve |
| `images/tool-pin/Dockerfile` | Its image: python:3.12-slim plus grpcio 1.84.1. Not built yet; no Docker access on the run host |
| `baseline.json` | The pin: evil-mcp's three tools as it serves them today. Each entry is the hash plus the description and input schema it covers |
| `gateway_bind.py` | Renders the bind: the committed `agentgateway-config` plus bind 3004 (3003 on the local bed; on the cluster 3003 is the `agentgateway-c7` container's since #514), with evil-mcp as its only target and tool-pin on its `tools/list` and `tools/call` |
| `tool-pin.yaml`, `kustomization.yaml` | The processor's Deployment, Service and baseline ConfigMap, for `live-check.sh`. No Argo CD Application points here |
| `probe.py` | An MCP client (mcp 1.29.1, the workshop-mcp image's pin) that lists tools, or calls one, and prints the outcome as JSON |
| `local-bed.sh` | The local bed (see "Reproduce") |
| `local-bed-2026-10-24.txt` | The bed's output from the run these findings come from |
| `live-check.sh` | The cluster check, in phases: `setup`, `observe`, `rugpull`, `deny`, `restore` |

`verify/test_tool_pin.py` holds the parts that need no binary offline: the hash, the verdicts, the
protobuf bytes, the baseline against `server.py`, and the rendered bind against the vendored v1.5.0 schema.

## The processor

For each tool in the `tools/list` result it computes `sha256` over the canonical JSON (sorted keys, no
whitespace) of `{name, description, inputSchema}`. It then looks the hash up in `baseline.json` under the
backend's name. The gateway sends that name unprefixed, as `service_names: ["evil-mcp"]`.

- **Approved** (the hash is in the baseline): the tool is kept.
- **Changed** (the name is pinned, the hash is not) or **unpinned** (the name is new): the tool is not approved.
- `PIN_MODE=strip` (the default) returns the result without the unapproved tools. ExtMCP calls this
  `mutated`; `nextCursor` and other fields are kept.
- `PIN_MODE=deny` refuses the whole list with `PERMISSION_DENIED`, and the reason names the tools.
- A `tools/call` passes only for a tool the most recent `tools/list` for that backend approved.
- A baseline that is missing or broken makes the RPC fail, and `failureMode: failClosed` refuses the list.
- It reads the baseline on every call, so re-approving means editing the ConfigMap. No restart is needed.

It encodes the protobuf messages by hand, with the field numbers from `crates/protos/proto/ext_mcp.proto`
at the v1.5.0 tag. The image therefore needs grpcio and nothing else, and the offline suite needs neither.

## Measured on the local bed, 2026-10-24

The bed ran agentgateway v1.5.0 (`agentgateway-linux-amd64`, sha256 `daca5cda…37e7b`, git revision
`fe67324`), evil-mcp's `server.py` under mcp 1.29.1, and tool-pin under grpcio 1.84.1. The gateway read its
config through a ConfigMap-style `..data` symlink, so a reload behaves the way it does in a pod. The full
output is `local-bed-2026-10-24.txt`.

| Case | What the client saw |
|---|---|
| `baseline.json` against a direct listing of evil-mcp | identical: the pin is what the server serves |
| Pinned bind, evil-mcp untouched | all three tools, unprefixed (`get_weather`, not `evil-mcp_get_weather`) |
| Pinned bind, `get_weather` description edited (strip) | `read_internal_config`, `apply_optimization`; `get_weather` gone |
| Calling the stripped `get_weather` by name anyway | before the `tools/call` phase was added, **it answered** with the poisoned reading. After: JSON-RPC `-32001` "tool get_weather is not an approved definition" |
| Same, deny | JSON-RPC `-32001`, message "evil-mcp tool definitions refused (changed since approval: get_weather)" |
| tool-pin down, pinned bind | JSON-RPC `-32603` "mcpGuardrails checkResponse failed: … Connection refused": failClosed |
| tool-pin down, the other bind | all three tools: a dead processor takes down only its own bind |
| Re-approve by rewriting the baseline file, no restart | `get_weather` back on the next list |
| Bad config swapped in while running | "Failed to reload config: …" logged, the old config kept serving, the process stayed up |
| Good config swapped in while running | the new bind served 0.4 s after the swap |
| Bad config at **startup** | exit 1 with the same error. A pod restarted on a bad ConfigMap would crash-loop |

Four things the docs did not say, or said differently:

1. **The standalone binary watches its config file and keeps the last good config on a bad reload.**
   Section 2 of the evaluation had both of these as unknown. On a cluster, the remaining delay is
   kubelet's ConfigMap sync.
2. **A request-phase deny on `tools/call` comes back as a JSON-RPC error (`-32001`).** The ExtMCP page
   (docs "latest", read 2026-10-24) says the client gets a tool result with `isError: true`. v1.5.0 does
   not do that.
3. **Stripping a tool from the list does not stop a call to it.** The gateway forwards a `tools/call`
   for a name it never listed. kagent's model only ever sees listed tools, but the pin is only a
   control on the wire once the call phase is checked as well.
4. **One target per bind keeps the names.** The gateway did not prefix the tool names, and it named the
   backend `evil-mcp` to the processor. Both match the proto comment about the "native (unmuxed) namespace".

## kagent's side, read from the v0.9.9 source (not yet seen live)

A background read of `kagent-dev/kagent` at v0.9.9 (file and line references in this run's report):

- **Discovery.** The controller lists each RemoteMCPServer's tools, keeping only name and description,
  into `status.discoveredTools`, and re-lists every 60 s. When `tools/list` returns an error it sets
  `Accepted=False` with `ReconcileFailed`, and the error text becomes the condition's message. It
  **keeps the last good `discoveredTools`**. It does not back off; it tries again 60 s later. The Agent's
  translation uses `toolNames` and the URL, not `discoveredTools`, so a failing server never blocks the Agent.
- **The agent's own `list_tools`.** The runtime is kagent-adk on google-adk 1.31.1. It builds a fresh
  toolset per A2A request and lists once per request, with no cache across requests. A changed
  description is therefore seen on the next chat message.
- **A JSON-RPC error on `tools/list`.** ADK retries once, logs "Failed to get tools from toolset", and
  drops **that toolset only**. The request still succeeds; the model just has none of evil-mcp's tools.
- **A tool in `toolNames` missing from the list** (stripped) is dropped silently, in the controller and
  in the runtime.

## What this means for the #117 design

- **Strip or deny.** Strip is the more precise control: only the changed tool goes, and the agent keeps
  the approved ones. Deny is the more visible one: by the source reading, the student can see it in
  `kubectl get remotemcpserver evil-mcp`, as `Accepted=False` with tool-pin's reason ("changed since
  approval: get_weather"). With strip, the only sign in kagent is a tool missing from `discoveredTools`.
  For a lesson, deny's condition is the better teaching surface. That is worth confirming live before
  choosing.
- **What the student configures can be one field.** The gateway config, bind 3004 included, can stay in
  GitOps. The student's action would be repointing evil-mcp's RemoteMCPServer `spec.url` at the pinned
  bind, which is the same shape as C7's `toolNames` patch. `ignoreDifferences` then covers that one
  field, not the whole `config.yaml` string that section 2 of the evaluation worried about. A typo in it
  breaks only evil-mcp.
- **Blast radius.** The separate bind contains a processor outage, as measured. It does not contain a
  config typo: all binds are one file. A bad edit is survivable while the pod runs, but crash-loops it on
  the next restart. That argues for the student not editing the gateway config at all, which the
  previous point makes possible.
- **Not covered by the pin.** The pin does not cover the tool's *output*. evil-mcp's `get_weather`
  result carries the same injection as its description, and `server.py` calls the output "the stronger,
  more reliable vector". The pin also leaves out `title`, `annotations` and `outputSchema`, which the
  issue did not ask for. A rug pull through any of those passes.

## Does the badge read the pin? Recommendation, pending the live check

**Yes. It should read whether the pin is wired, not what the pin last decided.** "Tool pin: on" would mean:

1. evil-mcp's RemoteMCPServer `spec.url` is the pinned bind, and
2. the `tool-pin-baseline` ConfigMap pins every name in the Agent's evil-mcp `toolNames`.

That matches how every other badge in guard-proxy's `/controls` works: each one reads a configuration
object, not an event. It needs `get` on `remotemcpservers/evil-mcp` and `configmaps/tool-pin-baseline`
added to the `guard-proxy-reader` Role.

The badge should not read `status.discoveredTools`. In deny mode kagent keeps the last good list there,
so the badge would show the old approved list as current. In strip mode it would show a tool that quietly
vanished. If the design picks deny, the `Accepted=False` condition could drive a second badge state,
"pin tripped", whose message is tool-pin's reason.

The recommendation rests on the source reading. Make the badge decision after `live-check.sh` has
confirmed kagent's behaviour.

## Still open: the cluster check

Run `live-check.sh` on a scratch attendee cluster, with `CONTEXT` set and an `IMAGE` built, pushed and
signed from `images/tool-pin/` (the Dockerfile has the steps). Run `observe` after each phase. It needs
to show:

1. **Discovery goes through the processor.** tool-pin logs a verdict about every 60 s, and the
   gateway's `route=default/evil-mcp-pinned` lines carry the kagent controller's pod IP.
2. **The agent's `list_tools` goes through it.** A chat message produces a line from the workshop-agent
   pod's IP.
3. **After `rugpull`, in strip mode.** `get_weather` leaves `discoveredTools`, and the agent does not
   call it.
4. **After `deny`.** The RemoteMCPServer shows `Accepted=False` with tool-pin's reason, and
   `discoveredTools` is stale. The agent log has "Failed to get tools from toolset", and the chat still
   answers.
5. **The `tools/call` phase.** See how kagent-adk handles a `-32001` on a call: a failed tool turn or a
   failed request. The source reading did not cover this.

`restore` deletes tool-pin and turns Argo CD auto-sync back on, and selfHeal reverts the rest.

`setup` pauses the root, `lab-bootstrap` since #609, as well as ai-layer, and refuses to go on without it:
the root's selfHeal would otherwise turn ai-layer's auto-sync back on mid-check. The names the script acts on
are rechecked against staging by `verify/test_tool_pin.py` (last changed 2026-10-29).

## Reproduce the local bed

```bash
mkdir -p tmp/agw && curl -sSL -o tmp/agw/agentgateway \
  https://github.com/agentgateway/agentgateway/releases/download/v1.5.0/agentgateway-linux-amd64
echo "daca5cda76e8c5ab0c1a75912fecf2d6365095403f810db72029c49d14a37e7b  tmp/agw/agentgateway" | sha256sum -c
chmod +x tmp/agw/agentgateway
uv venv tmp/venv --python 3.12 && uv pip install --python tmp/venv/bin/python 'mcp==1.29.1' 'grpcio==1.84.1' 'pyyaml==6.0.2'
bash docs/research/2026-10-24-tool-pin-spike/local-bed.sh tmp/agw/agentgateway tmp/venv/bin/python "$PWD/tmp/bed"
```

If `server.py`'s tool descriptions change, `verify/test_tool_pin.py` fails until the pin is regenerated.
Regenerate it from a direct listing, which is what the processor sees:
`python probe.py http://127.0.0.1:8000/mcp | jq .result | python images/tool-pin/tool_pin.py pin --service evil-mcp > baseline.json`.
