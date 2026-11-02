<!-- ABOUTME: Build design for #130: two exercises in which a student operates BurritoBot (the kagent Agent) and its
     ABOUTME: Bedrock model and spend, beside the eight challenges that attack it. Deferred to the next event. -->
# Operating BurritoBot: agent and Bedrock workload-management exercises

**Status: deferred to the next event.** Michael deferred #130 on 2026-09-07 with the label `deferred-barcelona` and kept
it open because the design work is still wanted for the next event. On #447 he set that the Barcelona challenges wait
until 2026-11-13, the day after the KubeCon NA 2026 breakout (`facilitation/kubecon-na-2026-run-of-show.md`, "Dates to
hold"). This note is the design, in the shape of `docs/research/2026-10-31-c1-dns-exfil-beat.md` for #116. It changes
no lab text, slide, run of show or deploy config. The build, the lab text and the live check start on or after
2026-11-13.

The issue's done-when has two parts: at least one agent-management exercise and one Bedrock or model-management
exercise in the run of show with commands, and both verified on a live cluster. This note specifies both exercises,
names every command against the current manifests, and lists the build pieces and the live checks they owe.

## What exists today

Facts checked on staging 39c1140.

- **The agent.** BurritoBot is the kagent `Agent` `workshop-agent` in namespace `agent`
  (`gitops/workshop-agent/agent.yaml`), runtime `go`, with its persona in `spec.declarative.systemMessage` and its
  model in `spec.declarative.modelConfig: bedrock-nova` (line 23). Its tools are two `McpServer` entries (line 257):
  `workshop-mcp` with twelve tools, four of them real (`get_vault_entry`, `list_services`, `deploy_app`,
  `run_shell`), and `evil-mcp` with three. kagent builds the agent's Deployment, also named `workshop-agent`, from the
  CR; the Deployment is not in Git.
- **Who reverts what.** The `workshop-agent` Argo CD Application (`gitops/bootstrap/apps/workshop-agent.yaml`) syncs
  with `selfHeal: true` and ignores exactly two fields of the Agent (line 65): `evil-mcp`'s `toolNames`, which the C7
  toggle narrows, and `spec.declarative.modelConfig` (line 72), which exists for the per-cluster model tier. Any other
  edit a student makes to the Agent is put back by selfHeal. `block-argocd-drift` (`policies/kyverno/block-argocd-drift.yaml`)
  refuses updates and deletes, from anyone but the Argo CD controller, to Deployments, ConfigMaps and Services that
  carry Argo's `tracking-id` annotation, on admin and attendee clusters. The kagent-built Deployment is not
  created by Argo, so it should carry no tracking id; confirm that at build time, because O1c depends on it.
- **What the student's terminal may do.** The `console-terminal` ClusterRole (`gitops/ai-layer/resources.yaml:798`)
  grants read on everything, write on core, `apps`, `batch` and `networking.k8s.io` resources (line 811), and
  get, update and patch on kagent `agents` (line 822). It grants nothing on `modelconfigs`.
- **The model bindings.** Six `ModelConfig`s live in `gitops/ai-layer/resources.yaml`: `bedrock-nova` (Nova Pro,
  `us.amazon.nova-pro-v1:0`), `bedrock-haiku`, `bedrock-sonnet` and `bedrock-opus` call Bedrock directly in
  us-west-2; `gateway-bedrock-nova` and `gateway-local-qwen3` go through agentgateway. The agent's Pod Identity
  policy (`agent-bedrock-policy.json` in the `challenge-fixes` ConfigMap, a copy of `aws_iam_policy.bedrock_invoke`
  in `infra/terraform/aws/cluster/main.tf`) allows exactly the four Bedrock inference profiles and their foundation
  models, so a swap among those four needs no IAM change.
- **The spend controls.** guard-proxy (`gitops/ai-layer/guard-proxy/proxy.py`, submodule guard-proxy-agenticburn)
  meters spend from the token counts kagent returns and prices them with `TIER_PRICES_PER_1K` (line 576) for one
  tier, `MODEL_TIER`, read once from the environment at start (line 583). The Deployment sets `MODEL_TIER=nova`
  (`resources.yaml:481`) and `COST_CAP_USD=25`. The C4 control is the per-conversation `BUDGET_CAP_USD`, 3 cents
  (line 433), switched by `/toggle?budget=on`. The cluster-wide cap can be lowered live with `/toggle?cost_cap=N` and
  restored with `cost_cap=default`; `parse_cost_cap` (line 471) refuses any value above `COST_CAP_USD`. `/cost`
  (line 1006) reports the tally.
- **The traces.** The agent pod emits OTel GenAI spans (`invoke_agent`, `chat`, `execute_tool`) with message content,
  under service `burritobot-agent`, and they land in Datadog Agent Observability. `gitops/ai-layer/tool_audit.py`
  writes one JSON line per tool call in `workshop-mcp`, tagged with the caller's `X-Agent-Identity`, queryable as
  `kube_namespace:agent kube_deployment:workshop-mcp @event:tool_invocation`. Challenge 4 in `challenges/LAB-TEXT.md`
  already sends the student to the trace view for token counts.
- **Model behavior.** `challenges/PROMPT-CATALOG.md` records that every measured figure is against Nova Pro, that
  Claude refuses several attack beats outright and that Llama and Mistral leak tool calls as text. The comment on
  `modelConfig` in `agent.yaml` says the same.

## The constraint the design has to meet

Operating a workload means changing it. On a workshop cluster most of the Agent is owned by Argo CD with selfHeal, the
student has no write access to Git (`docs/branch-per-cluster-convention.md` keeps branch-per-cluster off the attendee
fleet), and the cost counter assumes one fixed model. Three consequences follow.

1. A model swap already survives selfHeal, so the Bedrock exercise can run on today's sync settings.
2. A toolset change on `workshop-mcp` is reverted within seconds. The exercise either uses that revert as its lesson
   or the Application ignores one more field (open choice below).
3. After a model swap the counter prices the new model at Nova rates. Opus input is about six times Nova's, so the
   spend lesson would be wrong by that factor until guard-proxy prices the model actually bound. That is a build
   piece in guard-proxy-agenticburn.

## Exercise O1: operate the agent

Placed after Challenge 8 in `challenges/LAB-TEXT.md`, on an attendee cluster, about 15 minutes. "O" marks an
operating exercise beside the numbered challenges.

**O1a. Read what the agent is.** The student reads the agent's instructions, its tool list and its model binding
from the cluster, and finds the four real tools among the mocked ones.

```bash
kubectl -n agent get agent workshop-agent -o jsonpath='{.spec.declarative.systemMessage}' | head -40
kubectl -n agent get agent workshop-agent -o json \
  | jq '.spec.declarative.tools[] | {server: .mcpServer.name, tools: .mcpServer.toolNames}'
kubectl -n agent get agent workshop-agent -o jsonpath='{.spec.declarative.modelConfig}{"\n"}'
kubectl -n agent get deploy workshop-agent -o wide
```

**O1b. Change what it can do.** The student removes `run_shell` from `workshop-mcp`'s list, sends the C1 or C3 prompt
again, and BurritoBot should answer that it has no way to run a command. What happens next depends on the open choice below:
either Argo CD puts the tool back within seconds and the student watches the drift heal, or the change holds until
the reset step.

```bash
i=$(kubectl -n agent get agent workshop-agent -o json | jq '[.spec.declarative.tools[].mcpServer.name] | index("workshop-mcp")')
kubectl -n agent get agent workshop-agent -o json \
  | jq --argjson i "$i" '[.spec.declarative.tools[$i].mcpServer.toolNames[] | select(. != "run_shell")]' > /tmp/tools.json
kubectl -n agent patch agent workshop-agent --type=json \
  -p='[{"op":"test","path":"/spec/declarative/tools/'$i'/mcpServer/name","value":"workshop-mcp"},
       {"op":"replace","path":"/spec/declarative/tools/'$i'/mcpServer/toolNames","value":'"$(cat /tmp/tools.json)"'}]'
kubectl -n agent rollout status deploy/workshop-agent
```

The `test` op is the same guard the reset section's C7 line uses, so a reordered array fails the patch.

**O1c. Restart and scale it.** The student restarts the agent and sends a prompt during the rollout, then reads the
replica count kagent keeps. A restart is a plain Deployment operation the terminal's role allows. Scaling goes
through the Agent CR (`spec.declarative.deployment.replicas`), because kagent owns the Deployment's spec and is expected to put
a direct `kubectl scale` back; confirm that too. Confirm the field on kagent v0.10.1 with `kubectl explain
agent.spec.declarative.deployment.replicas` at build time; if the field is absent, O1c keeps the restart and drops
the scale.

```bash
kubectl -n agent rollout restart deploy/workshop-agent
kubectl -n agent rollout status deploy/workshop-agent
kubectl -n agent get deploy workshop-agent -o jsonpath='{.spec.replicas}{"\n"}'
```

**O1d. Tie a behavior to a tool call.** The student sends one prompt that makes BurritoBot call a real tool (the C5
`get_vault_entry` prompt), opens Agent Observability, finds the `execute_tool` span, and matches it to the audit line
`workshop-mcp` wrote for the same call:

```bash
kubectl -n agent logs deploy/workshop-mcp --since=5m | grep '"tool_invocation"' | tail -5
```

In Datadog, the same lines are under the Log Explorer query above. The lesson is that the trace says what the model
asked for and the audit line says what the platform executed, attributed to `workshop-agent`.

## Exercise O2: the model is an operating decision

Same placement, about 15 minutes. It uses the four Bedrock tiers the IAM policy already allows.

**O2a. Find the binding.** The Agent names a `ModelConfig`; the `ModelConfig` names the provider, the inference
profile and the region; the Pod Identity role decides which profiles the agent may call.

```bash
kubectl -n agent get modelconfig
kubectl -n agent get modelconfig bedrock-nova -o jsonpath='{.spec.provider} {.spec.model} {.spec.bedrock.region}{"\n"}'
kubectl -n agent get cm challenge-fixes -o jsonpath='{.data.agent-bedrock-policy\.json}' | jq '.Statement[0].Resource'
```

**O2b. Swap it and compare.** The student sends the C4 long-answer prompt once on Nova and reads `/cost`, swaps the
agent to Haiku, presses Reset in BurritoBot, sends the same prompt and reads `/cost` again. Then they send the C5 CEO
prompt on each model and compare the replies. Nova complies with attack beats that Claude refuses, which is the lesson
the issue names: the cheaper model that executes the attack and the dearer model that refuses it are both operating
choices, and the platform controls are what hold on either.

```bash
kubectl -n agent patch agent workshop-agent --type=merge -p '{"spec":{"declarative":{"modelConfig":"bedrock-haiku"}}}'
kubectl -n agent rollout status deploy/workshop-agent
kubectl -n agent exec deploy/guard-proxy -- python3 -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/cost').read())"
```

`modelConfig` is in the Application's ignore list, so the swap holds against selfHeal. A sync caused by any other
Agent change sets it back to `bedrock-nova`, as the comment at `workshop-agent.yaml:70` says.

**O2c. Manage the spend.** With the budget guard on, the student counts how many C4 sends the 3-cent conversation
budget allows on Nova and on Haiku, then lowers the cluster cap and watches it refuse:

```bash
kubectl -n agent exec deploy/guard-proxy -- python3 -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/toggle?budget=on').read())"
kubectl -n agent exec deploy/guard-proxy -- python3 -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/toggle?cost_cap=0.50').read())"
kubectl -n agent exec deploy/guard-proxy -- python3 -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/toggle?cost_cap=default').read())"
```

A request above `COST_CAP_USD` is refused with a 400, which is itself the point: the student can tighten the
platform's spend limit and cannot lift it. Opus is left out of the student path. It is the dearest tier and the
cluster backstop is shared with the room's budget; the facilitator can show it once.

**Reset.** The reset section gains one line, so every later run measures against Nova as `PROMPT-CATALOG.md`
requires:

```bash
kubectl -n agent patch agent workshop-agent --type=merge -p '{"spec":{"declarative":{"modelConfig":"bedrock-nova"}}}'
```

## Open choice: how a toolset change behaves under selfHeal

- **A. Keep selfHeal as it is and teach the revert.** The student's edit to `workshop-mcp` is put back within
  seconds. O1b becomes "the platform owns the agent's definition; a lasting change goes through Git", and the student
  watches it happen. Cost: the behavior change is visible only for the seconds before the revert, so the student
  must send the prompt fast or the facilitator shows the revert on its own.
- **B. Ignore `workshop-mcp`'s `toolNames` as well.** The change holds until reset and the student sees the behavior
  change at leisure. Cost: a Git change to that list no longer makes the Application OutOfSync, so it reaches a
  cluster only with some other Agent change. That is the silent failure #349 recorded when the whole tools array
  was ignored and the `get_recipe` rename never reached the clusters.
- **C. A student-owned second Agent.** The student applies a narrow Agent of their own, outside Git, and operates it
  freely. Cost: the chat page and guard-proxy front only `workshop-agent`, so the second agent has no cost counter
  and needs another way to reach it (the kagent UI or an A2A call), which is new surface to build and secure.

This note recommends A for the first build: it needs no sync change and it teaches the GitOps ownership the rest of
the workshop relies on. The choice is the facilitator's at build time.

## Build pieces

1. **guard-proxy prices the bound model.** Read `spec.declarative.modelConfig` from the `workshop-agent` Agent,
   which `guard-proxy-reader` may already `get` (`resources.yaml:319`), map the ModelConfig name to its tier, and
   price each request at that tier. `MODEL_TIER` stays as the start-up default. This belongs in
   guard-proxy-agenticburn with its own tests and a submodule bump here. `verify/model_pin_check.py` checks today
   that `MODEL_TIER` prices the pinned model; it gains a case for a swapped tier.
2. **Lab text.** O1 and O2 in `challenges/LAB-TEXT.md` after Challenge 8, the reset line, and the matching `/brief`
   rows. `verify/lab-render.py` and `test_instructor_brief.py` cover the rendered pages.
3. **Offline checks.** A test that every command in O1 and O2 names a resource, field or ModelConfig that exists in
   the manifests, in the shape of `verify/test_agent_tools_exist.py`, and that the ModelConfigs O2 swaps to are all
   in the IAM resource list.
4. **Run of show.** The next event's run of show places O1 and O2 with their timings. The KubeCon NA 2026 breakout is
   demo-only and does not carry them.

## Validation owed on a cluster

A session with AWS access runs these on a fresh attendee cluster, in the `verify/run-e2e.sh` tier, taking
`<kube-context>` like the existing beat checks:

- O1b: with `run_shell` removed, a C3 prompt produces no `run_shell` entry in `workshop-mcp`'s audit log, and under
  choice A the list is back to twelve tools within one selfHeal interval.
- O1c: after `rollout restart`, the next `/chat` turn answers.
- O2b: after the swap to `bedrock-haiku`, a `/chat` turn answers and its `chat` span's `gen_ai.request.model` is the
  Haiku profile; `/cost` grows by the Haiku price for the reported tokens once build piece 1 is in.
- O2c: `/toggle?cost_cap=` above `COST_CAP_USD` answers 400, and a lowered cap refuses the next turn at zero cost.
- Reset: the patch returns `modelConfig` to `bedrock-nova`.

## References

- #130 (this design), #447 (the dates), #114 (the denial-of-wallet cap), #349 (the tools-array ignore), #707 (the
  Agent's own Application), #123 and #126 (the two-hour redesign and the manipulation commands this feeds).
- `gitops/workshop-agent/agent.yaml`, `gitops/bootstrap/apps/workshop-agent.yaml`, `gitops/ai-layer/resources.yaml`,
  `gitops/ai-layer/guard-proxy/proxy.py`, `gitops/ai-layer/tool_audit.py`, `challenges/LAB-TEXT.md`,
  `challenges/PROMPT-CATALOG.md`, `challenges/c4-denial-of-wallet/README.md`.
