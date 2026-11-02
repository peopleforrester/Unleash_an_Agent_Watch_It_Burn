<!-- ABOUTME: The #480 spike: an agentgateway ExtMCP processor that pins tool-definition hashes (the #117 rug-pull
     ABOUTME: control), what the real v1.5.0 and v1.7.0 binaries did with it on a local bed, and what the cluster check must confirm. -->
# Spike: pin tool definitions at the gateway (#480, design for #117)

#117 is the rug-pull. A tool is approved, then its **description** changes while its **name** stays the
same. The #239 evaluation (`../2026-10-24-agentgateway-evaluation.md`, section 3) found one place in the
stack that can see a description: agentgateway's ExtMCP processor chain, on the `tools/list` response.
This spike builds that processor and runs it against the real gateway.

**State on 2026-10-24.** The processor works against agentgateway v1.5.0 on a local bed. The bed ran the
release binary, evil-mcp's own `server.py` and a rug-pulled copy of it. kagent's side is read from its
v0.9.9 source, not watched live: this run had no cluster. `live-check.sh` is the cluster half. It is
written but has not been run.

**Re-measured on 2026-11-01 on v1.7.0.** #698 moved the cluster's gateway to v1.7.0 on 2026-10-30. The ExtMCP
proto is byte-identical at both tags, and the same bed on the v1.7.0 binary gave the same results with two
differences: a refused `tools/call` now comes back as an `isError` tool result, and the failClosed error no
longer says why the processor failed. See "Re-measured on v1.7.0" below.

**Made one command for an existing cluster on 2026-11-02.** The coordinator's go on #480 (2026-11-02) is to run the
cluster check on `watch-it-burn-community`, the public cluster, never a new one, and to leave it as found, with
attackme answering 200 after. `live-check.sh run` now does the whole check, snapshots what it changes first and
restores it on any exit, and tool-pin no longer needs an image of its own. It has still not run on a cluster: the run
that made these changes had no cluster credentials. See "Still open: the cluster check".

## What is here

| File | What it is |
|---|---|
| `images/tool-pin/tool_pin.py` | The processor. It is a gRPC `agentgateway.dev.ext_mcp.ExtMcp` server that hashes each tool and strips or denies the ones not in the baseline. It also refuses a `tools/call` for any tool the last list did not approve |
| `images/tool-pin/Dockerfile` | Its image for a product version: python:3.12-slim plus grpcio 1.84.1. Never pushed, and the live check does not need it |
| `baseline.json` | The pin: evil-mcp's three tools as it serves them today. Each entry is the hash plus the description and input schema it covers |
| `gateway_bind.py` | Renders the bind: bind 3004 (3003 on the local bed; on the cluster 3003 is the `agentgateway-c7` container's since #514), with evil-mcp as its only target and tool-pin on its `tools/list` and `tools/call`. `cluster` adds it to the committed `agentgateway-config`; `extend`, which `live-check.sh` uses, adds it to the live one read on stdin |
| `tool-pin.yaml`, `kustomization.yaml` | The processor's Deployment, Service and baseline ConfigMap, for `live-check.sh`. It runs `tool_pin.py` from a `tool-pin-src` ConfigMap on the python:3.12-slim mirror guard-proxy runs, with grpcio installed by an init container. No Argo CD Application points here |
| `requirements.txt` | grpcio 1.84.1 and typing-extensions 4.16.0, hash-pinned, for that init container |
| `probe.py` | An MCP client (mcp 1.29.1, the workshop-mcp image's pin) that lists tools, or calls one, and prints the outcome as JSON |
| `local-bed.sh` | The local bed (see "Reproduce") |
| `local-bed-2026-10-24.txt` | The bed's output on v1.5.0, from the run these findings come from |
| `local-bed-2026-11-01-v1.7.0.txt` | The same bed's output on v1.7.0, the version the cluster runs since #698 |
| `live-check.sh` | The cluster check: `run` does it all in one command; the phases are `setup`, `ask`, `observe`, `call`, `rugpull`, `deny`, `restore` |

`verify/test_tool_pin.py` holds the parts that need no binary offline: the hash, the verdicts, the
protobuf bytes, the baseline against `server.py`, and the rendered bind against the vendored schema (v1.7.0
since #698). It also checks that `local-bed.sh` and the reproduce steps below name the gateway version the
cluster pins.

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
at the v1.5.0 tag, unchanged at v1.7.0 (sha256 `4ba750cc…3f563584` at both tags, compared 2026-11-01). The
image therefore needs grpcio and nothing else, and the offline suite needs neither.

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
   not do that. v1.7.0 does (next section).
3. **Stripping a tool from the list does not stop a call to it.** The gateway forwards a `tools/call`
   for a name it never listed. kagent's model only ever sees listed tools, but the pin is only a
   control on the wire once the call phase is checked as well.
4. **One target per bind keeps the names.** The gateway did not prefix the tool names, and it named the
   backend `evil-mcp` to the processor. Both match the proto comment about the "native (unmuxed) namespace".

## Re-measured on v1.7.0, 2026-11-01

#698 moved the cluster's gateway to v1.7.0 (`cr.agentgateway.dev/agentgateway:v1.7.0`, pinned by digest in
`gitops/ai-layer/agentgateway.yaml`), so the cluster check would no longer run the binary the bed measured.
The same `local-bed.sh` ran on the v1.7.0 release asset (`agentgateway-linux-amd64`, sha256
`1b2fc01a…2f42f8`, git revision `26f5aeb`), with mcp 1.29.1 and grpcio 1.84.1 as before. The full output is
`local-bed-2026-11-01-v1.7.0.txt`. The bed's config now carries the committed `config.session.key: disabled`,
as the cluster's does: without it, v1.7.0 wrote a generated key into the bed's config file on the first try,
which a pod's read-only ConfigMap would not allow. Every row of the table above is the same on v1.7.0 except two:

| Case | v1.5.0 | v1.7.0 |
|---|---|---|
| Calling the stripped `get_weather` by name | JSON-RPC `-32001` "tool get_weather is not an approved definition" | a tool result with `isError: true` and the same text, as the ExtMCP docs say |
| tool-pin down, pinned bind | JSON-RPC `-32603` "mcpGuardrails checkResponse failed: … Connection refused" | JSON-RPC `-32603` "guardrail check failed". The cause is no longer in the client's error |

A deny on `tools/list` is still JSON-RPC `-32001` with tool-pin's reason, so kagent's `Accepted=False`
condition should still carry "changed since approval: get_weather". The hot reload, keeping the last good
config on a bad reload, the 0.4 s pickup and the unprefixed names are unchanged. A bad config at startup
still exits 1 with the same error (run by hand with the bed's `bad.yaml`; `local-bed.sh` does not run it).

Two consequences for the design:

- **A refused call is now a tool result the model reads.** On v1.5.0 a call refusal was a JSON-RPC
  protocol error. On v1.7.0 it is an ordinary tool result marked `isError`, whose text is tool-pin's
  reason, so the model is likely to see that text. Open item 5 below changes with it.
- **The student cannot read a processor outage from the client side.** "guardrail check failed" does not
  say whether tool-pin is down or its baseline is broken. Only tool-pin's own log and the gateway log say
  which, so a lesson that breaks the processor on purpose has to point the student at those logs.

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
  breaks only evil-mcp. Two more things have to ship with the bind for that to hold, both found reading staging on
  2026-11-02: the `agentgateway` Service port, and port 3004 in the "from anywhere" rule of #552's
  `agentgateway-ingress` NetworkPolicy (`gitops/ai-layer/chat-path-ingress.yaml`). That policy opens only the
  gateway's named ports on every profile, so without it kagent's controller and the agent cannot reach the bind at
  all, and `verify/test_chat_path_ingress.py` would have to learn the new caller list.
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

The coordinator's go on #480 (2026-11-02) is to run it on `watch-it-burn-community`, the public cluster (attackme), and
leave that cluster as found. Michael's correction the same day allows `watch-it-burn-private` too, and never a third
cluster. The check is one command on a host with the accen-dev AWS profile, from a checkout of staging that has this
directory, with a kubeconfig of its own:

```bash
AWS_PROFILE=accen-dev aws eks update-kubeconfig --region us-west-2 --name watch-it-burn-community \
  --kubeconfig /tmp/watch-it-burn-community.kubeconfig --alias watch-it-burn-community
KUBECONFIG=/tmp/watch-it-burn-community.kubeconfig AWS_PROFILE=accen-dev CONTEXT=watch-it-burn-community \
  bash docs/research/2026-10-24-tool-pin-spike/live-check.sh run
```

It takes about ten minutes and writes everything it prints to `/tmp/tool-pin-live.watch-it-burn-community.record.txt`.
Commit that record here, as `live-2026-MM-DD-community.txt`, with the findings below.

**What `run` does to the cluster, and how it puts it back.** `setup` first records every object it will change in
`$STATE` (by default `/tmp/tool-pin-live.<context>`): `lab-bootstrap`'s and `ai-layer`'s auto-sync and their sync and
health, `agentgateway-config`'s `config.yaml`, the `agentgateway` Service's ports, `agentgateway-ingress`'s rules,
evil-mcp's url and `server.py`,
the agent's pods, and the public host from `cluster-identity`. It will not start unless that host answers 200, and
it will not snapshot over an earlier snapshot. It then pauses both Applications, deploys tool-pin, adds bind 3004
to the gateway config the cluster runs (`gateway_bind.py extend`, not this checkout's), opens 3004 next to 3001 and
3003 in `agentgateway-ingress`, checks the bind lists evil-mcp's three tools, and only then repoints evil-mcp's
RemoteMCPServer at it. It asks the agent through kagent's A2A proxy
(`kagent-controller.kagent:8083/api/a2a/agent/workshop-agent/`, kagent v0.9.9 `go/core/internal/httpserver/server.go`
line 336), not guard-proxy, so the public bot's `/cost` counter does not move. The gateway's `:3000` would not do:
#552's policy admits only guard-proxy there. On any exit, a failure
included, `restore` writes each recorded value back, deletes tool-pin, restarts evil-mcp-shim if the rug pull ran
(the running server loaded the edited source), and turns auto-sync back on as it was. It then compares every one of
those against the snapshot, waits for both Applications and evil-mcp's `Accepted` condition (False in deny mode) to be
as they were, and checks the public host answers 200.
On any difference it exits 1 and keeps the snapshot, so `live-check.sh restore` can be run again.
`verify/test_tool_pin_live_check.py` runs all of this against a stateful kubectl stand-in, including a failure in
the middle of the run and a gateway that refuses the config.

**tool-pin without its own image.** `watch-it-burn:tool-pin` was never pushed. The pod runs `tool_pin.py` from a
`tool-pin-src` ConfigMap that `setup` makes from `images/tool-pin/tool_pin.py` and `requirements.txt`, on the
python:3.12-slim mirror guard-proxy already runs. An init container installs grpcio by hash, which needs egress to
PyPI once (the community cluster has no NetworkPolicy; on the private cluster the agent namespace's default-deny would
need an allow first). On 2026-11-02 this shape ran in Docker with the same image, commands, read-only root and uid
1000: the install took about 5 seconds, tool-pin started, passed evil-mcp's untouched list over gRPC and stripped a
rug-pulled `get_weather`.

What the record needs to show:

1. **Discovery goes through the processor.** tool-pin logs a verdict about every 60 s, and the
   gateway's `route=default/evil-mcp-pinned` lines carry the kagent controller's pod IP.
2. **The agent's `list_tools` goes through it.** A question produces a line from the workshop-agent pod's IP.
   `run` also says whether kagent rolled the agent after the url change. If it did not, `run` restarts it (and
   `restore` restarts it again), and that is a finding: a student's url patch would need an agent restart too.
3. **After `rugpull`, in strip mode.** `get_weather` leaves `discoveredTools`, and the agent does not
   call it.
4. **After `deny`.** The RemoteMCPServer shows `Accepted=False` with tool-pin's reason, and
   `discoveredTools` is stale. The agent log has "Failed to get tools from toolset", and the chat still
   answers.
5. **The `tools/call` phase.** `call` calls `get_weather` by name through the pinned bind after the rug pull. On
   v1.7.0 the local bed gave an `isError` tool result carrying tool-pin's reason. The agent itself never sees a
   stripped tool, so it cannot call one; what a model does with that refusal only matters when a list and a call
   disagree, which this check does not stage.

Then decide the badge (the section above) from the record, and write it in decisions.md.

## Reproduce the local bed

```bash
mkdir -p tmp/agw && curl -sSL -o tmp/agw/agentgateway \
  https://github.com/agentgateway/agentgateway/releases/download/v1.7.0/agentgateway-linux-amd64
echo "1b2fc01a2de29ca113bbb6258b5cae7b1eb3c724071c09d687a449132f2f42f8  tmp/agw/agentgateway" | sha256sum -c
chmod +x tmp/agw/agentgateway
uv venv tmp/venv --python 3.12 && uv pip install --python tmp/venv/bin/python 'mcp==1.29.1' 'grpcio==1.84.1' 'pyyaml==6.0.2'
bash docs/research/2026-10-24-tool-pin-spike/local-bed.sh tmp/agw/agentgateway tmp/venv/bin/python "$PWD/tmp/bed"
```

If `server.py`'s tool descriptions change, `verify/test_tool_pin.py` fails until the pin is regenerated.
Regenerate it from a direct listing, which is what the processor sees:
`python probe.py http://127.0.0.1:8000/mcp | jq .result | python images/tool-pin/tool_pin.py pin --service evil-mcp > baseline.json`.
