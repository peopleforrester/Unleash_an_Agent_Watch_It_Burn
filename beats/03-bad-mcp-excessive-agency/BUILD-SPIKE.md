<!-- ABOUTME: The gating verification doc for Beat 3 (BUILD-SPEC Phase 4b). Confirms whether -->
<!-- ABOUTME: agentgateway mcpAuthorization CEL deny enforces on the Apache OSS build with kagent in front. -->

# Beat 3 Build-Spike, MCP tool-authorization enforcement

**Gate:** This beat is declared **live** only if the spike below **PASSES**. If it FAILS, Beat 3
demotes to a pre-recorded segment plus a governance-map row (see Fallback). The recorded segment is
built regardless (BUILD-SPEC §3, §11).

**Single load-bearing unknown** (from `research/04-mcp-security.md` and `research/02-agentgateway.md`):
whether agentgateway's `mcpAuthorization` CEL `Deny` over `mcp.tool.name` actually enforces on the
**Apache OSS build (`v1.2.1`)** with a **kagent agent in front**, as opposed to being an
Enterprise-only (`EnterpriseAgentgatewayPolicy`) capability, or simply not firing when the caller is
a kagent agent consuming the MCP server through the gateway.

## Verification Method (fill in at build)

- Method: live cluster (spoke), hands-on. NOT research. # verify-at-build
- agentgateway OSS version under test: `v1.2.1` # verify-at-build, confirm and record in VERSIONS.lock
- kagent chart version: `0.9.7`, API group `kagent.dev/v1alpha2` # verify-at-build
- MCP SDK version in evil-mcp-shim image + image digest: # verify-at-build
- Date run / operator:  # fill in

## Preconditions

1. Spoke cluster reachable; agent + agentgateway + evil-mcp-shim all running in the attendee spoke.
2. `evil-mcp-shim` deployed (`evil-mcp-shim/k8s-manifest.yaml`) and registered as an MCP `target`
   behind agentgateway. # verify-at-build: confirm the gateway target/route config (gateway author)
3. Planted sentinel applied (`plant-fake-secret.yaml`); `read_internal_config` returns
   `FAKE-MCP-EXFIL-sentinel-4c1d`.
4. `agent/gateway/mcp-authz-off.yaml` and `mcp-authz-on.yaml` exist (authored by the gateway agent).

## Steps

### Step A, BEFORE (deny rule OFF): confirm the over-reach fires deterministically
1. Apply the off state: `beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh --off`
2. Run the model-independent path:
   `beats/03-bad-mcp-excessive-agency/fallback.curl.sh --expect-allow`
3. Expected: the rogue tool returns the sentinel (sentinel present, script exits 0).
4. (Optional, model path) Run `agent-prompt.txt` against the live agent and confirm the sentinel
   appears in the reply and the gateway access log shows a `read_internal_config` tool call.

### Step B, AFTER (deny rule ON): confirm the gateway BLOCKS the call
1. Apply the on state: `beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh --on`
2. Run the model-independent path:
   `beats/03-bad-mcp-excessive-agency/fallback.curl.sh --expect-deny`
3. Expected: the call is rejected at the policy layer; sentinel ABSENT (script exits 0).
   Record HOW the denial surfaces (HTTP status / JSON-RPC error / filtered from `list_tools`).
   # verify-at-build
4. (Optional, model path) Re-run `agent-prompt.txt`; confirm the reply contains no sentinel.

### Step C, Confirm tool filtering (secondary, expected per docs)
1. With the deny rule ON, list tools through the gateway and confirm `read_internal_config` is
   filtered out of the `list_tools` response (agentgateway auto-filters disallowed tools).
   # verify-at-build, confirms the documented filtering behavior on the OSS build.

## Evidence to capture

- [ ] Step A fallback output (sentinel present). # paste / link
- [ ] Step B fallback output (sentinel absent + denial form). # paste / link
- [ ] Gateway access/policy log lines for both states. # paste / link
- [ ] Whether the policy resource applied cleanly on the OSS image (no Enterprise-only CRD error).
- [ ] Tool-filtering result from Step C.

## PASS / FAIL decision box

```
+-----------------------------------------------------------------------+
| BEAT 3 LIVE-ENFORCEMENT SPIKE RESULT                                  |
|                                                                       |
|   RESULT:  [ ] PASS    [ ] FAIL          <-- TODO: record at build    |
|                                                                       |
|   PASS  => mcpAuthorization CEL Deny enforces on OSS v1.2.1 with      |
|            kagent in front; Beat 3 ships LIVE with the toggle.        |
|                                                                       |
|   FAIL  => deny did NOT enforce (Enterprise-gated / did not fire /    |
|            kagent path not seen by gateway). Beat 3 ships as the      |
|            RECORDED fallback + governance-map row. Update BUILD-SPEC  |
|            §2 and §11 and the runbook.                                |
|                                                                       |
|   Decided by: __________________      Date: __________   # TODO      |
|   Notes / failure detail: ____________________________________       |
+-----------------------------------------------------------------------+
```

## Documented fallback if the spike FAILS

If RESULT = FAIL, do NOT run Beat 3 as a live toggle. Instead:

1. **Recorded segment.** Play the asciinema recording under `fallback/recordings/` showing the
   before (sentinel leaks) and after (blocked) on a rig where enforcement was confirmed, or, if
   enforcement is unavailable anywhere on OSS, record the BEFORE over-reach and narrate the
   control as an Enterprise/architecture gap rather than a demonstrated OSS toggle. The Beat-3
   recording is mandatory regardless of spike result (BUILD-SPEC §3).
2. **Governance-map row.** Add/keep the row mapping: attack = excessive agency via poisoned MCP
   tool description; control = MCP tool-level authorization (allow/deny over tool name); layer =
   MCP tool authorization (gateway); covered-by-existing-CNCF-tooling = NO (agent-specific gap).
   This teaches the gap even when the live toggle is cut (BUILD-SPEC §11 mitigation).
3. Update BUILD-SPEC §2 Beat 3 and §11, and `facilitation/runbook.md`, to reflect recorded status.

## Result log

- RESULT: **TODO** (run the spike; fill the decision box above).
- Verified hands-on against a live spoke: **TODO**.
