<!-- ABOUTME: Build design for #117, the C7 MCP rug-pull beat: a tool approved once then silently mutated, which
     ABOUTME: name-based allow-listing cannot catch, plus the Unicode TAG-block concealment variant. Deferred to the next event. -->
# C7 MCP rug-pull beat: build design

**Status: deferred to the next event.** Michael deferred #117 on 2026-09-07 with the label `deferred-barcelona`,
and kept it open because the design work is still wanted for the next event ("Keeping it open and labelled rather
than closing it, because the design work here is still wanted, just for the next event", on the issue). On #447 he
set that the Barcelona challenges wait until 2026-11-13, the day after the KubeCon NA 2026 breakout
(`facilitation/kubecon-na-2026-run-of-show.md`, line 56: "The Barcelona challenges wait until 2026-11-13"). This note
is the design, in the shape of `docs/research/2026-10-31-c1-dns-exfil-beat.md` (#116) and
`docs/research/2026-11-02-workload-management-exercises.md` (#130). It changes no lab text, slide, run of show or
deploy config. The build, the lab text and the live check start on or after 2026-11-13.

C7 is Challenge 7, the poisoned-tool challenge in `challenges/LAB-TEXT.md`. The issue's one gap is post-approval
mutation: a tool whose description is approved once, then silently changed, so the behaviour moves while the name the
allow-list pins does not. The core control for it — pinning a hash of the tool definition at approval and refusing on
mismatch — is already designed and spiked in #480 (`docs/research/2026-10-24-tool-pin-spike/`) and argued in section 3
of the agentgateway evaluation (`docs/research/2026-10-24-agentgateway-evaluation.md`). This note does not repeat
that build; it specifies the student-facing beat that exercises it, and it designs the one piece the issue asks for
that is not designed anywhere yet: the Unicode TAG-block concealment variant.

## What exists today

Facts checked on staging 4aa58c1.

- **The challenge and its prop.** Challenge 7 in `challenges/LAB-TEXT.md` (the beat starting near line 670) runs a
  synthetic rogue MCP server, `evil-mcp-shim` (`challenges/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py`,
  deployed from the `evil-mcp-src` ConfigMap at `gitops/ai-layer/resources.yaml:552`). It serves a benign-looking
  `get_weather` whose description is the poisoned payload, chaining the agent into `read_internal_config`, which
  surfaces the fake sentinel `FAKE-MCP-EXFIL-sentinel-4c1d`, and `apply_optimization`, which returns a non-compliant
  "clown file" manifest. The prop is clearly labelled synthetic and reaches nothing real.
- **The wiring.** evil-mcp is a kagent `RemoteMCPServer` (`gitops/ai-layer/resources.yaml:694`) that the agent dials
  through agentgateway on its own bind, `:3003`, served by the `agentgateway-c7` container since #514. The gateway is
  pinned to v1.7.0 since #698.
- **Today's control.** C7's control is MCP tool allow-listing by name: on an attendee cluster the student narrows the
  Agent's `evil-mcp` `toolNames` to `[get_weather]` (`challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh`,
  and the same patch in the lab text and the web terminal's `guard-mcp-on`); on an admin cluster the control is
  agentgateway's `mcpAuthorization` CEL rule on the `:3003` bind instead (#496). Verified both directions: the attack
  leaks the sentinel with the full toolset, and does not once the list is narrowed.
- **The rug-pull control, already spiked (#480).** `images/tool-pin/tool_pin.py` is an agentgateway ExtMCP gRPC
  processor on the `tools/list` response phase. It computes `sha256` over the canonical JSON of each tool's
  `{name, description, inputSchema}`, looks the hash up in a baseline pinned at approval
  (`docs/research/2026-10-24-tool-pin-spike/baseline.json`), and strips (default) or denies the tools whose hash
  changed, and it refuses a `tools/call` for any tool the last list did not approve. It runs on its own cluster bind,
  `:3004` (#290, because #514 took `:3003`). The processor works against the real v1.5.0 and v1.7.0 binaries on a
  local bed; its kagent-side behaviour is read from kagent v0.9.9 source and has not been checked live
  (`docs/research/2026-10-24-tool-pin-spike/README.md`, "Still open: the cluster check").

## Why the current control does not cover the gap

`toolNames` filters by tool **name**. A rug-pull leaves the name unchanged and changes the description, so the
allow-list still contains `get_weather` and the agent still reads the new, poisoned description. The gateway's
`mcpAuthorization` CEL cannot catch it either: no documented CEL variable carries a tool's description, so a rule
cannot tell an approved definition from a changed one with the same name (evaluation section 3). The protocol has no
capability attestation: a server cannot prove its tool definitions match what the client trusted at approval. The
2026-07-28 MCP spec revision hardened authorization (OAuth 2.1 resource-server semantics, RFC 9207 issuer validation,
RFC 8707 resource indicators, RFC 9728 metadata discovery, DCR deprecated for CIMD) and did almost nothing for tool
trust. Every defence against rug-pull is out-of-band: hashing and pinning tool definitions, baselining descriptions,
`mcp-scan`, a manifest-pinning state machine, or a gateway enforcing the pin. That asymmetry — auth solved, trust not
— is the slide this beat earns.

## Stage R: the rug-pull

Placed as a second control stage inside Challenge 7, on an attendee cluster, after the student has narrowed
`toolNames` and seen the leak stop. "Stage" names a step of the demonstration; the retired "round" vocabulary stays
out of it. About 10 minutes.

We run `evil-mcp-shim`, so we control the server and can mutate it in place. The build serves the mutation from the
`evil-mcp-src` ConfigMap, not a rebuilt image, so a facilitator or the student flips it with a `kubectl` edit and a
pod restart, with no registry round-trip. The beat has three steps:

1. **Approve and watch it work benignly.** The student (or facilitator) confirms `evil-mcp`'s `get_weather` is on the
   allow-list and its description is innocuous, asks the weather question, and gets a plain weather answer with no
   second tool call. This is the "approved once" state.
2. **Mutate in place and re-ask.** The description of `get_weather` is swapped for the poisoned one — the same name,
   the same allow-list entry, a changed description — and the pod restarts. The student asks the **same** innocent
   weather question again. BurritoBot now chains into `read_internal_config` and the sentinel walks out. Nothing in
   the allow-list changed; the student changed nothing; the behaviour changed. That is the whole point.
3. **Pin and refuse.** The student points `evil-mcp`'s `RemoteMCPServer` `spec.url` at the pinned bind (`:3004`),
   which puts tool-pin on the `tools/list` and `tools/call` phases with the baseline captured at step 1. The same
   mutation is now caught: in deny mode `kubectl get remotemcpserver evil-mcp` shows `Accepted=False` with tool-pin's
   reason ("changed since approval: get_weather"), and the agent no longer gets the poisoned tool. The control the
   issue asked for — "pin a hash of the tool definitions at approval and refuse on mismatch" — is what closes it.

The exact student action for step 3 is one field, `spec.url`, the same shape as the `toolNames` patch the student
already ran; the gateway config and bind stay in GitOps, so a typo breaks only evil-mcp (#480, "What the student
configures can be one field"). Whether step 3 teaches better in strip mode or deny mode is an open choice settled by
the live check (below): deny gives a visible `Accepted=False` condition, strip is more precise but leaves only a tool
missing from `discoveredTools`.

## Stage T: Unicode TAG-block concealment

This is the "Also worth adding" piece (arXiv 2607.05744), and it is the net-new design here. It is a different attack
from the rug-pull and worth keeping distinct: the rug-pull is a time-of-check-to-time-of-use attack (approved clean,
mutated later); TAG-block concealment is an at-approval attack (the human approves something different from what the
model reads, at the same instant). Both defeat name-based allow-listing, and the beat places them side by side.

**The mechanism.** The Unicode TAG block, U+E0000–U+E007F, holds "tag" code points; U+E0020–U+E007E mirror printable
ASCII 0x20–0x7E. Most terminals, editors and approval UIs render them as nothing, so a description can carry an
entire instruction in TAG characters that a human approver never sees, while the model's tokenizer decodes them back
into readable ASCII. The paper reports this working across three independent server implementations: the approval
view shows one thing, the model reads another. It is the same theme as the hidden-document injection the lab already
teaches in Challenge 6 — an instruction the human does not see but the model obeys — carried in the tool metadata
rather than a support ticket.

**The beat.** `evil-mcp-shim` serves a `get_weather` whose **visible** description is clean, with a TAG-encoded
instruction appended that says to call `read_internal_config`. The student asks the weather question and the sentinel
leaks, yet `kubectl get agent workshop-agent -o yaml` and the approval UI show a clean description. The reveal is the
slide: one terminal command decodes the hidden bytes.

```bash
kubectl -n agent exec deploy/evil-mcp-shim -- python3 - <<'PY'
import json, urllib.request
# list evil-mcp's tools and show any non-printable / TAG-block code points per description
# (build writes the exact listing call against the served transport)
PY
```

The build renders the concealed description from a small encoder helper in the shim, kept beside `server.py`, so the
visible and hidden halves are explicit in source and the prop stays clearly synthetic. It demos in seconds, which is
its value on stage.

**The sharp distinction for the talk, and for the control.** The hash-pin from Stage R catches the rug-pull because
the hash covers the raw description bytes, TAG characters included — so a *post-approval* TAG mutation trips it like
any other. But the pin does **not** catch TAG concealment present *at approval*: if the baseline is captured from a
server that already carries the hidden characters, the pin faithfully trusts what was approved. The defence against
at-approval concealment is making the approval view honest: normalize or strip disallowed Unicode ranges (the TAG
block, variation selectors) before the human approves and before the model reads, and hash the normalized form.
`mcp-scan`-style scanning that flags non-printable code points is the out-of-band version of the same check. Stating
that limit precisely is the lesson: pinning answers "did it change after I trusted it?", not "is what I trusted what
I saw?".

## Real precedent (for the slide)

- **postmark-mcp**, 2025-09-25: the first confirmed malicious MCP server. Benign through v1.0.15; v1.0.16 added a
  single line BCC-ing every email the agent sent to the attacker's domain. ~1,500 downloads, roughly 300
  organisations. No CVE was assigned, because it was a behavioural backdoor, not a code flaw
  (`https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/`). "No CVE, because nothing was
  technically vulnerable" is a slide on its own, and it is exactly the rug-pull shape: a trusted tool, one quiet line
  added in a later version.
- **Anthropic GTG-1002**, 2025-11-14: the first reported AI-orchestrated espionage campaign at scale, built on MCP.
  The point for the talk is scale, not mechanism: MCP is now load-bearing for real adversaries.

## Build pieces

1. **The mutable shim.** `evil-mcp-shim` serves `get_weather`'s description from a value it can swap without a rebuild
   (the `evil-mcp-src` ConfigMap already carries the source), with a clean, a rug-pulled, and a TAG-concealed variant,
   and a tiny TAG encoder helper beside `server.py` so the concealed bytes are explicit in source. Keep the sentinel
   fake and the prop labelled synthetic, as it is today.
2. **The pin, promoted from the spike.** tool-pin becomes a deployed artifact for the next event: an image built,
   pushed and signed from `images/tool-pin/` (the `Dockerfile` has the steps; grpcio 1.84.1 is the one dependency,
   recorded in the #480 decisions entry), the `:3004` bind rendered by `gateway_bind.py`, and the baseline and
   Deployment from `docs/research/2026-10-24-tool-pin-spike/`. The spike kept all of this off the deployed path on
   purpose; the next event's build is where it lands behind its own Argo CD Application.
3. **Lab text.** Stage R and Stage T added to Challenge 7 in `challenges/LAB-TEXT.md`, after the `toolNames` fix, with
   the reveal command and the pin-and-refuse step. `verify/lab-render.py` and `verify/test_instructor_brief.py` cover
   the rendered pages.
4. **The badge, if wired.** guard-proxy's `/controls` could read whether the pin is wired (evil-mcp's `spec.url` is
   the pinned bind and the baseline pins every allow-listed name), not what it last decided — the recommendation in
   the #480 README, pending the live check. It needs `get` on `remotemcpservers/evil-mcp` and the baseline ConfigMap
   added to `guard-proxy-reader`.
5. **Offline checks.** A test that the shim's three description variants differ only as intended (clean vs. rug-pull
   vs. TAG-concealed, the last identical to the clean one once TAG code points are stripped), that the baseline hashes
   the clean variant, and that every Stage R and Stage T command names a resource and field that exists in the
   manifests, in the shape of `verify/test_tool_pin.py` and `verify/test_agent_tools_exist.py`.
6. **Run of show.** The next event's run of show places Stage R and Stage T with their timings. The KubeCon NA 2026
   breakout narrates the rug-pull gap on a slide and does not run it.

## Open choice: strip or deny for Stage R step 3

The #480 README leaves this for the live check. Deny mode surfaces a visible `Accepted=False` condition carrying
tool-pin's reason, which is the better teaching surface; strip mode is more precise but shows only a tool missing from
`discoveredTools`. On v1.7.0 a refused `tools/call` comes back as an `isError` tool result the model reads, so the
model may repeat the reason to the student — behaviour the source reading did not cover and the live check must
observe. This note recommends deny for the lesson, confirmed on a cluster before the lab text is written.

## Validation owed on a cluster

Not yet run on a cluster; a session with AWS access runs these on a fresh attendee cluster in the `verify/run-e2e.sh`
tier, taking `<kube-context>` like the existing beat checks, on or after 2026-11-13:

- The #480 `live-check.sh` phases (`setup`, `observe`, `rugpull`, `deny`, `restore`): discovery and the agent's own
  `list_tools` both pass through the processor, the rug-pulled `get_weather` is stripped or denied, and the pin's
  blast radius and ArgoCD scope behave as the local bed showed.
- Stage R: after the in-place description swap with the allow-list unchanged, a weather prompt leaks the sentinel;
  after `spec.url` is repointed at the pinned bind, the same prompt does not, and the RemoteMCPServer shows
  `Accepted=False` with tool-pin's reason (deny mode).
- Stage T: the TAG-concealed description leaks the sentinel while `kubectl get agent ... -o yaml` shows a clean
  description; the reveal command prints the hidden TAG code points; and the normalized-and-hashed pin treats the
  concealed and clean descriptions as the same definition (confirming the pin does not catch at-approval concealment,
  which is the stated lesson).

## References

- #117 (this design), #110 (the parent set), #480 (the tool-pin spike), #290 (the spike's `:3004` bind), #514
  (evil-mcp behind agentgateway on `:3003`), #698 (gateway v1.7.0), #496 (the admin-cluster gateway rule), #447 (the
  Barcelona dates), #116 and #130 (the sibling Barcelona design notes), #115 (the emoji-smuggling theme Challenge 6
  teaches).
- `docs/research/2026-10-24-tool-pin-spike/README.md`, `docs/research/2026-10-24-agentgateway-evaluation.md` (section
  3), `images/tool-pin/tool_pin.py`, `challenges/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py`,
  `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh`, `gitops/ai-layer/resources.yaml`,
  `challenges/LAB-TEXT.md`.
- MCP 2026-07-28 spec revision: `https://blog.modelcontextprotocol.io/posts/2026-07-28/`. postmark-mcp:
  `https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/`. TAG-block concealment: arXiv
  2607.05744.
