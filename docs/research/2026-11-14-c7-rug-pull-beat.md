<!-- ABOUTME: Build design for #117, the C7 rug-pull beat: a tool approved once, then its description changed
     ABOUTME: with the name kept, which name-based allow-listing misses, and the hash-pin control that catches it. -->
# C7 rug-pull beat: build design

**Status: deferred to the next event.** Michael deferred #117 on 2026-09-07 with the label
`deferred-barcelona`, and kept it open because the design work is still wanted for the next event. On #447 he
set that the Barcelona challenges wait until 2026-11-13, the day after the KubeCon NA breakout on 2026-11-12.
This note is that design. It changes no lab text, slide, run of show or deploy config. It names the on-stage
beat, the control that answers it, the pieces the build must produce, and the live assertions owed on a
cluster. The hash-pin control itself was already spiked in #480 and measured live; this note reuses that work
rather than restating it.

The note is written at the altitude of `2026-10-24-tool-pin-spike/README.md` and the sibling deferred-barcelona
notes (`2026-10-31-c1-dns-exfil-beat.md`, #116). It names the channel and the checks that prove it. How the
agent's tool produces each result is written at build time, inside the lab, under the same review as the
existing C7 beat.

"Beat" names a step of the demonstration. The fleet's retired "round" vocabulary (`verify/round_shapes.py`) is
kept out of it.

## What C7 covers today

C7 is the poisoned-tool challenge (`challenges/LAB-TEXT.md`, "Challenge 7"). A rogue MCP server, `evil-mcp`
(`gitops/ai-layer/server.py`, served through the shim deployment `evil-mcp-shim`), carries a tool whose
description instructs the agent to call a second tool it was never asked for, which surfaces the fake sentinel
`FAKE-MCP-EXFIL-sentinel-4c1d`. The control is the tool allow-list: the agent's spec
(`gitops/workshop-agent/agent.yaml`) lists which of `evil-mcp`'s tools the agent may call, and the fix narrows
that list by name to the one harmless tool. Verified both directions: with the full list the sentinel leaks,
with the list narrowed it does not.

The allow-list is a list of names (kagent's `toolNames`). It says which tool names the agent accepts from the
server.

## The gap the beat shows

The allow-list keys on the tool **name**. A rug-pull keeps the name and changes the **description**. The
server's `get_weather` is approved and listed. Later the server serves the same `get_weather` name with a
description that now carries the chained instruction. The allow-list sees the approved name and admits it. The
model reads the changed description and behaves differently. Nothing in `toolNames` moved.

This is the gap #117 names: allow-listing by name does not cover post-approval mutation. MCP has no capability
attestation, so a server cannot prove at call time that its tool definitions match what the client approved.
That is unclosed in the current spec (see "The MCP 2026-07-28 asymmetry" below).

## The beat on stage

Five steps, on `evil-mcp`, which we run and can mutate:

1. **Approve.** The allow-list holds `get_weather` with its approved, benign description. The agent lists its
   tools and the approved `get_weather` is among them.
2. **Show it benign.** Ask the innocent weather question. The agent answers from the benign tool. No sentinel,
   no second tool call.
3. **Mutate in place.** Change `get_weather`'s description on the server so it now chains to the second tool.
   The name and the input schema are untouched, so the allow-list still admits `get_weather` by name.
4. **Re-ask.** Ask the same innocent weather question. The agent now calls the second tool and the sentinel
   leaks. Nothing in the allow-list changed between steps 2 and 4.
5. **Pin and refuse.** Apply the hash-pin control. The pin caught the approved definition's hash at approval.
   On the next list it sees the changed description, finds the hash does not match the pinned one for that
   name, and strips the changed tool. The agent answers the weather question with no access to the mutated
   tool, so the sentinel does not leak.

The sharp point for the room: the allow-list, a correct and sufficient control for the first beat, is blind to
step 3. The name it keys on did not move.

## The control

The hash-pin was built and measured in #480 (`2026-10-24-tool-pin-spike/README.md`,
`images/tool-pin/tool_pin.py`). It is an agentgateway ExtMCP processor on the `tools/list` response phase. For
each tool it computes `sha256` over the canonical JSON of `{name, description, inputSchema}` and looks the hash
up in a baseline pinned at approval (`baseline.json`). An approved tool is kept. A tool whose name is pinned
but whose hash changed, or a name that is new, is not approved.

The spike measured two modes live on `watch-it-burn-community` on 2026-11-05 (hecaton run 17293), which put the
cluster back as found:

- **Strip mode** removes the unapproved tool from the list. The agent keeps the approved tools and answers
  without the mutated one. This is the mode the beat uses.
- **Deny mode** refuses the whole list. On the cluster's kagent 0.10.1 Go runtime a refused `tools/list` fails
  the agent's whole answer, which hands the attacker a denial of service instead of a leak. The spike's
  decision is strip mode for that reason.

The hook point already exists: since #514, `evil-mcp` is served through its own agentgateway bind (the
`agentgateway-c7` container, config in ConfigMap `agentgateway-c7-config`). The spike's `gateway_bind.py` adds a
pinned bind and routes `evil-mcp` through the processor. The student's action is repointing `evil-mcp`'s
RemoteMCPServer `spec.url` at the pinned bind, the same shape as C7's existing `toolNames` patch.

## The MCP 2026-07-28 asymmetry

The 2026-07-28 MCP spec revision hardened authorization and left tool trust where it was. Sources, read on
2026-11-14 (#1462): the revision post, [The 2026-07-28 Specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
(MCP blog, 2026-07-28), its [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
against 2025-11-25, and the revision's
[Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) and
[Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) pages.

What the revision itself changed in authorization, per its changelog:

- **RFC 9207 issuer validation (new in 2026-07-28, SEP-2468).** Authorization servers SHOULD include the `iss`
  parameter in the authorization response, and clients MUST validate a present `iss` against the recorded
  issuer before redeeming the code. The post says this "closes an authorization-server mix-up hole". The
  mandate is on the client's check when `iss` is present; the server returning it is a SHOULD, so "mandatory
  issuer validation" is right only with that qualifier.
- **DCR deprecated in favour of CIMD (new in 2026-07-28, PR #2858).** OAuth 2.0 Dynamic Client Registration
  (RFC 7591) is deprecated as a registration mechanism in favour of Client ID Metadata Documents. It stays for
  backward compatibility with authorization servers that lack CIMD; the post adds that it "will be removed in a
  future version of the MCP spec".
- **Credentials bound to their issuer (new, SEP-2352),** and clients set `application_type` during DCR
  (SEP-837). Neither was in the note before; both are authorization hardening of the same kind.

What the revision carries forward and did not introduce. These three are in the 2026-07-28 Authorization page,
but they arrived in the 2025-06-18 revision ([changelog](https://modelcontextprotocol.io/specification/2025-06-18/changelog)),
and the 2026-07-28 post does not mention them:

- **OAuth 2.1 resource-server semantics.** "A protected MCP server acts as an OAuth 2.1 resource server", and
  authorization servers MUST implement OAuth 2.1 (draft-ietf-oauth-v2-1-13). 2025-06-18 classified MCP servers
  as OAuth resource servers (PR #338).
- **RFC 9728 protected-resource metadata.** MCP servers MUST implement it and clients MUST use it for
  authorization-server discovery. Added in 2025-06-18 with the resource-server change (PR #338).
- **RFC 8707 resource indicators.** Clients MUST send the `resource` parameter naming the target server, so a
  token is bound to the server it was requested for. Added in 2025-06-18 (PR #734) "to prevent malicious
  servers from obtaining access tokens".

So the slide's accurate form is: the current revision's authorization is OAuth 2.1 resource-server semantics,
RFC 8707 and RFC 9728 (in force since 2025-06-18), and 2026-07-28 added RFC 9207 issuer validation and
deprecated DCR for CIMD. #117's text credits all five to 2026-07-28; that is the correction.

Tool trust in the same revision: the Tools page says clients MUST treat tool annotations as untrusted unless
they come from trusted servers, and the only tool-list change is that `tools/list` SHOULD return a
deterministic order, which the post ties to clients caching tool catalogs. Neither page defines a signature,
hash or attestation of a tool definition. None of the revision touches whether a tool's definition at call
time matches what the client trusted at approval. Every defence against the rug-pull is out of band: hashing and
pinning tool definitions (the control here), validating descriptions against a known-good baseline, `mcp-scan`,
manifest pinning with a signature state machine that ends the session on downgrade, or a gateway enforcing an
allow-list. That asymmetry, authorization hardened and tool trust untouched, is the observation for the stage.

## Real precedent

Each fact below was read against its primary source on 2026-11-14 (#1462).

- **postmark-mcp**, an npm MCP server for sending mail through Postmark, published by npm user `phanpak` and not
  by Postmark. Sources: Snyk,
  [Malicious MCP Server on npm postmark-mcp Harvests Emails](https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/)
  (Liran Tal, 2025-09-25); Koi Security, who found it,
  [First Malicious MCP in the Wild: The Postmark Backdoor That's Stealing Your Emails](https://web.archive.org/web/20250929094654/https://www.koi.security/blog/postmark-mcp-npm-malicious-backdoor-email-theft)
  (Idan Dardikman, 2025-09-25; the live URL now redirects to Palo Alto Networks, so the link is the Wayback
  copy); and OSV's [MAL-2025-47604](https://osv.dev/vulnerability/MAL-2025-47604).
  - **Version.** Benign through 1.0.15; 1.0.16 added one line, `Bcc: 'phan@giftshop.club'`, that copied every
    email the server sent to the attacker. Snyk: "the behavior began around `1.0.16` and persisted in later
    versions", and it diffs 1.0.15 (benign) against 1.0.18 (malicious). Koi: "Versions 1.0.0 through 1.0.15
    work perfectly" and "Version 1.0.16 adds the BCC. Nothing else changes." OSV: introduced in 1.0.16.
  - **Release date, as Snyk states it.** Snyk gives no single date for 1.0.16. Its timeline, in UTC+3: 1.0.0
    first published 2025-09-15; "2025-09-15 to 2025-09-17: Rapid iteration through multiple minor versions",
    within which 1.0.16 introduced the BCC; 1.0.18, the latest release noted, on 2025-09-17; and on 2025-09-25
    the package no longer existed on npm. So the malicious release falls between 2025-09-15 and 2025-09-17.
    2025-09-25 is the date of disclosure and removal, not of the release. #117's text puts 2025-09-25 against
    the incident; on a slide it reads "backdoored in mid-September 2025, disclosed 2025-09-25".
  - **Downloads and organisations: corrected.** Snyk gives neither figure. Both are Koi's, and both are weekly
    estimates, not counts: "downloaded 1,500 times every single week", then, under "We can only guestimate the
    impact", a list that runs "1,500 downloads every single week", "Being conservative, maybe 20% are actively
    in use", "That's about 300 organizations". The note's "roughly 1,500 downloads across about 300 organisations" therefore becomes
    "about 1,500 downloads a week, which Koi estimated at about 300 organisations in use".
  - **No CVE: confirmed, reason corrected.** Neither Snyk nor Koi mentions a CVE. NVD returns no CVE for
    `postmark-mcp` (keyword search, 2026-11-14), and OSV tracks it as malicious package MAL-2025-47604 (from
    the OpenSSF malicious-packages feed, published 2025-09-26) with no CVE alias. No source states why. The
    reason the note gave ("a behavioural backdoor, not a code flaw") is our reading, consistent with how the
    OpenSSF feed tracks deliberately malicious packages by MAL id rather than CVE. On a slide: "no CVE; it
    is tracked as malware, MAL-2025-47604", with the reason spoken as ours, not quoted as a source's.
  - **"First".** Koi calls it "the world's first sighting of a real world malicious MCP server"; Snyk calls it
    "perhaps the first media coverage case" of a "known and tracked malicious MCP Server". "First confirmed"
    is Koi's claim, so the slide credits it to Koi.
- **Anthropic GTG-1002.** Sources: Anthropic,
  [Disrupting the first reported AI-orchestrated cyber espionage campaign](https://www.anthropic.com/news/disrupting-AI-espionage)
  (news post, 2025-11-13) and its
  [full report](https://assets.anthropic.com/m/ec212e6566a0d47/original/Disrupting-the-first-reported-AI-orchestrated-cyber-espionage-campaign.pdf)
  (dated November 2025, with a changelog entry of 2025-11-17 that clarifies the attribution language).
  - **Date: corrected.** Anthropic published 2025-11-13, not 2025-11-14 as #117's text and this note had it.
  - **What the report says.** Detected in mid-September 2025; a Chinese state-sponsored group Anthropic
    designated GTG-1002, assessed with high confidence; "roughly 30 entities" targeted, with "a handful of
    successful intrusions" validated; the actor used AI "to execute 80-90% of tactical operations
    independently". Anthropic calls it "the first documented case of a cyberattack largely executed without
    human intervention at scale".
  - **Built on MCP: confirmed.** The framework "used Claude Code and open standard Model Context Protocol
    (MCP) tools", and its commodity tools "were orchestrated through custom automation frameworks built around
    Model Context Protocol servers".

## Also in this beat: Unicode TAG-block concealment

A second short move on the same theme (arXiv 2607.05744). Tool metadata can hide bytes from the human approval
view using Unicode TAG-block characters, reported across three independent server implementations. The approval
UI renders one thing; the model reads another. It demos in seconds and ties to the emoji-smuggling evasion in
#115.

Where it sits against the hash-pin: the pin covers the exact bytes the model reads, so it catches a TAG payload
**added after** approval, because the hash changes. It does not catch a TAG payload **present at** approval,
because the pin caught those bytes as the approved baseline. The defence against at-approval concealment is an
honest approval view that renders the same bytes the model will read. The beat draws that line: the pin answers
post-approval mutation, the approval view answers at-approval concealment, and both are needed.

## What the build must produce

A later cluster-capable, non-doc-lane run owns this. The pieces:

| Piece | What it is |
|---|---|
| Mutation switch | A way to change `evil-mcp`'s `get_weather` description in place, name and schema kept, for step 3. The simplest is a second description in the server selected by an env var or a mounted file, toggled by a patch of the same shape as C7's `toolNames` patch |
| Pinned bind in GitOps | Promote the spike's `gateway_bind.py` bind and `tool_pin.py` into `gitops/ai-layer/`, strip mode, failure mode chosen per the spike's open item |
| Baseline ConfigMap | The pinned hashes for `evil-mcp`'s approved tools, built from the approved descriptions |
| Service port and ingress | The `agentgateway` Service port for the new bind, and that port added to the "from" rules of the `agentgateway-ingress` NetworkPolicy (`gitops/ai-layer/chat-path-ingress.yaml`), so kagent's controller and the agent can reach the bind; `verify/test_chat_path_ingress.py` learns the new caller |
| `/controls` badge | A "tool pin" badge in guard-proxy's `/controls` that reads whether the pin is wired (the RemoteMCPServer url and the baseline ConfigMap), per the spike's badge decision |
| Lab text and slide | A C7 sub-section for the rug-pull beat and the mutation step, plus the TAG-block move, and the matching slide and run-of-show line |
| Offline checks | A test that the mutation changes the description and not the name or schema, that the baseline covers the approved tools, and that the badge reads the wiring |

## Validation owed on a cluster

For the `verify/run-e2e.sh` live tier, on `watch-it-burn-community` or `watch-it-burn-private`, once the build
lands:

1. **Benign.** With the approved description and the pin on, the weather question answers with no sentinel.
2. **Rug-pull, pin off.** After the description is mutated, with the pin off, the same question leaks the
   sentinel and the allow-list is unchanged.
3. **Rug-pull, pin on, strip.** After the description is mutated, with the pin on in strip mode, the mutated
   tool is stripped from the list and the sentinel does not leak.
4. **Badge.** The `/controls` "tool pin" badge reads on when the url points at the pinned bind and the baseline
   covers the approved tools, and off otherwise.

Each check leaves the cluster as found, as the spike's `live-check.sh` does.
