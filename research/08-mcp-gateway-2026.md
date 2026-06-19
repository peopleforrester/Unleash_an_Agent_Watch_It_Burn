<!-- ABOUTME: Grounded June 2026 comparison of OSS MCP gateways / proxies / registries for the Beat 3 -->
<!-- ABOUTME: tool-restriction control: agentgateway vs Docker MCP Gateway vs ToolHive vs kagent-native toolNames. -->

# MCP Gateway Landscape, June 2026, for Beat 3 (MCP Tool Restriction)

This spike answers a single procurement question for Beat 3 (the "bad MCP server / excessive
agency" beat): of the OSS MCP gateways / proxies / registries current in June 2026, which one most
simply implements "restrict which MCP tools/servers the agent may call" and "block a malicious MCP
server" for a 2-hour workshop on EKS with kagent in front. It does NOT re-litigate the threat model
(see `research/04-mcp-security.md`) or agentgateway's guardrail mechanics (see
`research/02-agentgateway.md`); it sits on top of both.

## Verification Method

Web and GitHub-API research, dated **2026-06-19**. Version and license claims were confirmed against
the GitHub REST API (`api.github.com/repos/<org>/<repo>/releases` and `.../<repo>` for `license`),
NOT against rendered HTML, because a plain page fetch of one releases page mis-stated the years as
2024 while the API `published_at` field showed 2026. The API JSON is the source of truth for every
version and date below. Each material claim carries its source inline. Enforcement-semantics claims
that the docs did not state explicitly are quarantined in the Unverified section and are NOT used to
ground the recommendation.

Primary sources:

- agentgateway releases (GitHub API): `https://api.github.com/repos/agentgateway/agentgateway/releases`
- agentgateway MCP authz docs: `https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/`
- Docker MCP Gateway repo + releases (GitHub API): `https://api.github.com/repos/docker/mcp-gateway/releases`
  and `https://github.com/docker/mcp-gateway`
- Docker MCP Gateway announcement: `https://www.docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/`
- ToolHive repo + releases (GitHub API): `https://api.github.com/repos/stacklok/toolhive/releases`
  and docs `https://docs.stacklok.com/toolhive/`
- kagent tools docs: `https://kagent.dev/docs/kagent/concepts/tools`,
  `https://kagent.dev/docs/kagent/getting-started/first-mcp-tool`,
  `https://kagent.dev/docs/kagent/concepts/agents`

---

## Verified

### Version / license / maintenance snapshot (GitHub API, 2026-06-19)

| Project | Latest stable | Date | License | Maintenance |
|---|---|---|---|---|
| **agentgateway** | **`v1.3.0` GA** | **2026-06-18** | Apache-2.0 (LF/AAIF) | Very active. `v1.2.1` was 2026-05-15; `v1.3.0-rc.2` and GA both landed 2026-06-18. |
| **Docker MCP Gateway** | `v0.42.3` | 2026-06-12 | **MIT** | Very active (986 commits; `v0.42.x` cadence Apr-Jun 2026). |
| **ToolHive (Stacklok)** | `v0.30.0` | 2026-06-16 | Apache-2.0 | Very active, weekly cadence; 9 contributors on the v0.30.0 release. |
| **kagent-native `toolNames`** | ships in kagent (`kagent.dev/v1alpha2`) | n/a | Apache-2.0 (CNCF sandbox) | Active; it is a field on the Agent CRD, not a separate release train. |

Sources: the four GitHub-API release/license endpoints listed in Verification Method.

**agentgateway version note that supersedes `research/02-agentgateway.md`:** that file (dated
2026-06-15) pins `v1.2.1` and says "do NOT chase the v1.3 beta." As of 2026-06-18 **`v1.3.0` is GA**,
not beta. The pinning advice was correct on its date; for the build, re-evaluate whether to pin
`v1.2.1` (known-good, what the existing beat scripts assume) or `v1.3.0` (current GA). Do NOT silently
adopt v1.3 without re-running the Beat 3 build-spike, MCP authz field names can move across a minor.

### What each option actually enforces for "restrict tools / block a bad server"

**agentgateway, `mcpAuthorization` (Apache OSS).**
Source: `https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/`
- **Tool allowlist/denylist:** CEL rules over `mcp.tool.name` (plus `mcp.tool.target`,
  `mcp.prompt.name`, `mcp.resource.name`, and JWT claims), evaluated per MCP method invocation
  (`list_tools`, `call_tool`). This is the headline control for Beat 3.
- **Tool filtering:** a disallowed tool is filtered out of `list_tools`, the agent never sees it.
- **Server allowlist:** structural, via the `targets` list, only configured MCP backends are reachable.
- **OAuth/token validation:** OAuth 2.0 / JWT, gateway acts as MCP resource server; Keycloak/Auth0 built in.
- **SSRF:** not a documented turnkey MCP-SSRF control; it is a proxy, so egress is mediated, but no
  named "metadata-endpoint block" feature. Treat as architectural, not a checkbox.
- **Footprint:** already deployed in the workshop stack as the LLM gateway. Adding the MCP authz
  policy is a CRD/config change, **zero new components per attendee**.

**Docker MCP Gateway (`docker/mcp-gateway`, MIT).**
Sources: repo + `https://www.docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/`
- **Tool allowlist:** yes, enable/disable tools per server within a profile (`docker mcp profile tools`).
- **Server allowlist / registry:** yes, the Docker MCP Catalog (300+ verified, signed container
  images) acts as a curated registry; custom catalogs enforce an approved-server allowlist.
- **Container isolation:** each MCP server runs in an isolated Docker container with restricted
  privileges/network, plus call-tracing and logging.
- **OAuth + secrets:** built-in OAuth flows; secrets via Docker Desktop, kept out of env vars.
- **Footprint / fit:** **Docker-Desktop / Docker-daemon centric.** No documented Kubernetes-native
  deployment path. This is the disqualifier here, the workshop is kagent on EKS, not Docker Desktop.
  Excellent product, wrong substrate for this beat.

**ToolHive (Stacklok, `stacklok/toolhive`, Apache-2.0).**
Sources: repo + `https://docs.stacklok.com/toolhive/`
- **Tool filtering:** "customize and filter tools and descriptions" per server.
- **Server allowlist / registry:** "curate a catalog of trusted MCP servers," group-based.
- **vMCP gateway:** the Virtual MCP Server is ToolHive's gateway, a proxy that handles inbound
  traffic, secures credentials, optimizes tool selection, and applies org policies (rate limiting
  added in v0.30.0).
- **Isolation + authz:** runs MCP servers in isolated containers with fine-grained permissions and
  network access filtering; OAuth (Okta/Entra in Enterprise); OTel + Prometheus audit logging.
- **Kubernetes:** **yes, a real Kubernetes operator** for multi-user environments, the only
  dedicated MCP gateway here besides agentgateway with a first-class K8s story.
- **Footprint / fit:** strong and K8s-native, but it is a **whole second control plane** (operator +
  CRDs + vMCP) layered next to kagent+agentgateway. For a 2-hour workshop that already has a gateway,
  this is a new component per attendee with its own learning curve. Best-in-class if you were building
  an MCP-server platform; overkill as the Beat 3 toggle.

**kagent-native `toolNames` allowlist (Apache-2.0, CNCF).**
Sources: `https://kagent.dev/docs/kagent/concepts/tools`, `.../getting-started/first-mcp-tool`,
`.../concepts/agents`
- **Tool allowlist:** the Agent CRD's `tools[].mcpServer.toolNames` field enumerates exactly which
  tools from an MCP server the agent may use. Docs: "Even if the MCP server has multiple tools, you
  can decide which tools to include for this particular agent." Tools not listed are not exposed.
- **Server allowlist:** structural, the agent only references the `MCPServer` / `RemoteMCPServer`
  resources you bind to it.
- **Human-in-the-loop:** **`requireApproval` field exists** (lists tools that pause for an
  Approve/Reject button in the UI; rejection reasoning is fed back to the LLM). This DIRECTLY closes
  the HITL gap that `research/02-agentgateway.md` and `research/04-mcp-security.md` flagged as "not
  native / unverified." Example:
  ```yaml
  tools:
  - type: McpServer
    mcpServer:
      name: kagent-tool-server
      kind: RemoteMCPServer
      toolNames:           # allowlist: only these tools reach the agent
      - k8s_get_resources
      - k8s_delete_resource
      requireApproval:     # HITL gate on the dangerous one
      - k8s_delete_resource
  ```
- **Footprint:** **zero new components.** It is a field on the agent the workshop already deploys.

### New OSS entrants

- The official **MCP Registry** (modelcontextprotocol.io ecosystem) is a discovery/provenance
  catalog, not a runtime enforcement point, it does not block a tool call live. Slide material, not a
  Beat 3 toggle.
- Commercial/hosted players (Arcade, Composio, AWS AgentCore, Smithery, JFrog MCP, WorkOS) appear in
  the 2026 landscape roundup (`https://www.arcade.dev/blog/mcp-gateways-runtimes-registries-guide/`)
  but are SaaS/commercial, out of scope for an OSS, per-attendee, in-cluster demo.
- No net-new OSS Kubernetes-native MCP gateway beyond agentgateway and ToolHive surfaced in this
  spike that would change the recommendation.

---

## Unverified / could not confirm (June 2026 gaps)

1. **kagent `toolNames` enforcement point.** The docs say the agent only "includes" the listed tools,
   strongly implying an **agent-level filter** (disallowed tools are never put in the agent's tool
   list, so the model cannot call them). The docs do NOT state whether there is also a server-side
   runtime rejection if a call somehow targets an unlisted tool. For Beat 3 this nuance is benign and
   arguably favorable: a poisoned description cannot induce a call to a tool the agent was never
   handed. But verify the exact enforcement boundary hands-on before scripting the before/after.
   General 2026 framing (system-prompt filter vs runtime block) confirmed only second-hand
   (`https://thebackenddevelopers.substack.com/p/runtime-verification-for-ai-agents`); not a primary kagent source.
2. **agentgateway `v1.3.0` MCP-authz field compatibility.** GA landed 2026-06-18. Whether the
   `mcpAuthorization` CEL field names are byte-identical to `v1.2.1` (what the beat scripts assume)
   is unverified. Re-run the build-spike if adopting v1.3.
3. **kagent `requireApproval` in a non-interactive demo.** It presents UI Approve/Reject buttons; in
   a scripted/headless before-after it needs a human click or an API approval call. Confirm the
   approval can be driven non-interactively (or that the UI click is acceptable on stage) before
   relying on it as the live toggle.
4. **SSRF specifics.** None of the four options advertises a turnkey MCP-SSRF (metadata-endpoint)
   block as a named feature. SSRF defense remains architectural (egress policy / network policy),
   consistent with `research/04-mcp-security.md` treating SSRF as slide material, not a live toggle.
5. **Docker MCP Gateway on Kubernetes.** No K8s deployment path was found in docs; treated as
   Docker-Desktop-bound. If a K8s path exists it was not surfaced, and it would not change the
   recommendation given agentgateway is already in-cluster.

---

## RECOMMENDATION

**Do NOT add a dedicated MCP gateway. Use what is already in the stack.** Two OSS controls already
present make Beat 3 land cleanly; a third component is not worth it for a 2-hour workshop.

**Primary (the live toggle): agentgateway `mcpAuthorization` CEL Deny over `mcp.tool.name`.**
It is the existing gateway (zero new per-attendee footprint), it is genuine OSS (Apache-2.0), it
denies and filters at the proxy independent of what the tool description claims, and it is exactly the
"control sits between the agent and the tool server" story the beat already narrates. This remains
the right primary, gated on the existing Beat 3 build-spike passing on the OSS image with kagent in
front. The only new wrinkle since the prior research is that `v1.3.0` is now GA, decide pin
(`v1.2.1` known-good vs `v1.3.0` current) and re-spike if you move.

**Backstop / co-control: kagent-native `toolNames` allowlist (+ `requireApproval`).** This is the
simplest possible "restrict which tools the agent may call," a field on the agent the workshop
already ships, zero new components, and it CANNOT be Enterprise-gated because it is the open kagent
CRD. If the agentgateway OSS authz spike ever fails (the single load-bearing unknown in
`BUILD-SPIKE.md`), `toolNames` is a clean live fallback that keeps Beat 3 a real toggle instead of a
recorded segment: BEFORE = `read_internal_config` in `toolNames`, sentinel leaks; AFTER = remove it,
the agent can no longer call it. As a bonus, `requireApproval` lets you demo OWASP LLM06's
human-in-the-loop mitigation live, closing the HITL gap the earlier research left open. Worth a
second build-spike to confirm its enforcement boundary (Unverified #1).

**Explicitly rejected for this beat:**
- **Docker MCP Gateway** (MIT, excellent) , Docker-Desktop/daemon-centric, no K8s path; wrong substrate.
- **ToolHive** (Apache-2.0, K8s operator, best dedicated MCP platform here) , a whole second control
  plane next to kagent+agentgateway; real overkill for a 90-second on-stage toggle. Cite it on the
  governance map as the "dedicated MCP gateway" category, do not deploy it per attendee.
- **MCP Registry** , discovery/provenance, not a live enforcement toggle. Slide.

**One-line answer:** agentgateway MCP authz is the live control; kagent `toolNames` is the
zero-new-component fallback that also unlocks a HITL sub-beat. Adding Docker MCP Gateway or ToolHive
is not worth it for this workshop.
