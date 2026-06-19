<!-- ABOUTME: Grounded research spike on cryptographic agent identity (SPIFFE/SPIRE, WIMSE, agent-auth) for the workshop. -->
<!-- ABOUTME: Resolves June 2026 maturity, EKS fit, the spawned-sub-agent question, and a live/narrated/omit verdict. -->

# Agent Identity Research, SPIFFE/SPIRE and the 2026 Agent-Identity Landscape

Michael raised: today the agent's identity is just a Kubernetes ServiceAccount + IRSA. There is
no workload-identity-document layer for the agent or for any sub-agents it spawns. Is SPIFFE/SPIRE
(or newer agent-identity work) worth showing in this 2-hour workshop?

This spike answers that against current primary sources. The honest verdict is at the bottom.

## Verification Method

Web research, dated 2026-06-19. Every material claim carries its source URL inline. Version and
maturity facts were resolved against the GitHub release page and IETF datatracker, NOT training
data. One arXiv result (`2603.24775`, "AIP: Agent Identity Protocol") carried an impossible
year-stamp (2603) of the same malformed kind quarantined in `research/04-mcp-security.md`; it is
discarded and grounds nothing here. Load-bearing claims rest on:

- SPIRE releases (GitHub): https://github.com/spiffe/spire/releases
- CNCF project pages: https://www.cncf.io/projects/spiffe/ , https://www.cncf.io/projects/spire/
- IETF WIMSE architecture draft: https://datatracker.ietf.org/doc/html/draft-ietf-wimse-arch-07
- IETF agent-auth draft: https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/
- CSA Agentic Identity Governance Framework (draft white paper):
  https://labs.cloudsecurityalliance.org/agentic/agentic-identity-governance-framework-v1/

---

## SPIFFE / SPIRE current state (Verified)

- **CNCF maturity: Graduated.** SPIFFE graduated 2022-08-23, SPIRE 2022-08-22. Both remain
  graduated as of June 2026. This is the most mature, least-hype anchor in the whole topic.
  Source: https://www.cncf.io/projects/spiffe/ , https://www.cncf.io/projects/spire/
- **SPIRE version: `v1.15.1`** (2026-05-28), latest stable. (`v1.15.0` was 2026-05-19; the
  maintained prior line is `v1.14.7`, also 2026-05-28.) Source: https://github.com/spiffe/spire/releases
- **What it does:** SPIRE issues **short-lived SVIDs** (SPIFFE Verifiable Identity Documents),
  either X.509 certs or JWTs, to each workload after **multi-factor node + workload attestation**.
  A pod calls the Workload API socket; the SPIRE agent identifies the caller by PID, resolves the
  container -> pod -> namespace/ServiceAccount via the kubelet/API, and maps it to a SPIFFE ID
  (`spiffe://<trust-domain>/<path>`). The workload never holds a long-lived secret.
  Source: https://spiffe.io/docs/latest/spire-about/spire-concepts/

### EKS fit (Verified, with one caveat)

- SPIRE has a first-class AWS node attestor, **`aws_iid`**, which attests an agent using the EC2
  Instance Identity Document from IMDS, the established pattern for EKS. Source (mechanism):
  SPIRE docs referenced via https://medium.com/@noah_h/cloud-native-identity-management-exploring-spiffe-spire-istio-89253cdb046a
- **Important framing for the talk:** SPIRE on EKS is **additive to**, not a replacement for, the
  existing SA + IRSA / EKS Pod Identity model. IRSA (OIDC federation, 2019) and EKS Pod Identity
  (2023) already deliver short-lived **AWS** credentials to a pod. Source:
  https://aws.amazon.com/blogs/containers/amazon-eks-pod-identity-a-new-way-for-applications-on-eks-to-obtain-iam-credentials/
  SPIRE's distinct value is a **platform-agnostic workload identity** usable for **mTLS between the
  agent and its tools/MCP servers and between sibling agents**, which IRSA (an AWS-IAM construct)
  does not provide. That is exactly the layer the workshop's SA+IRSA stack is missing.

---

## Emerging OSS / standards work SPECIFIC to AI-agent identity in 2026

This is where honesty matters most. There is real, named, dated activity, but it is **early-stage
draft work, not shipping standards**. Ranked by maturity:

1. **IETF WIMSE (Workload Identity in Multi-System Environments)**, the closest thing to a real
   standard. WG chartered 2024-03. Architecture draft is `draft-ietf-wimse-arch-07` (March 2026,
   expires 2026-09-03). It defines a **Workload Identity Token (WIT)** and a **Workload Proof Token
   (WPT)** (`draft-ietf-wimse-wpt-00`) and a workload **Identifier** draft
   (`draft-ietf-wimse-identifier-02`). SPIFFE is positioned as the **deployed implementation** of
   WIMSE principles; WIMSE is the **forthcoming formal standard**. Realistic timeline: arch -> RFC
   over 2026-2027; the full stack is a **2027-2028** event. Sources:
   https://datatracker.ietf.org/doc/html/draft-ietf-wimse-arch-07 ,
   https://datatracker.ietf.org/doc/draft-ietf-wimse-identifier/ ,
   https://www.ietf.org/ietf-ftp/internet-drafts/draft-ietf-wimse-wpt-00.txt
   **WIMSE is about workloads generally, not AI agents specifically.**

2. **IETF `draft-klrc-aiagent-auth-02`** (2026-06-01), "AI Agent Authentication and Authorization."
   This is the one piece **specific to AI agents**. But it is an **individual Internet-Draft**, NOT
   a WG document, and the datatracker page states it is **not endorsed by the IETF** and has **no
   formal standing**. Its thesis is deliberately un-novel: agents are workloads; **use WIMSE
   identifiers as the primary agent identifier, SPIFFE as the mature implementation, and OAuth 2.0
   for delegation**. It addresses on-behalf-of delegation via OAuth `sub` claims but does **not**
   detail nested sub-agent architectures. Source:
   https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/

3. **CSA Agent Identity Governance Framework (AIGF)**, a **draft white paper** dated 2026-03-27 (a
   governance framework, not a wire protocol or runnable spec). Notably it is the one source that
   speaks **directly to spawned sub-agents**: it defines "ephemeral sub-agent identities" created by
   an orchestrator with **seconds-to-minutes TTLs**, mandates **constrained delegation** ("no
   identity may delegate more privilege than it has been granted"), and requires **full
   delegation-chain audit trails** with a permission ceiling enforced at every hop. It explicitly
   names **SPIFFE SVIDs as the preferred credential format for orchestrator / persistent autonomous
   agent identities**, while flagging SVID-issuance **latency** as a concern for very high-velocity
   ephemeral agents. Does not cite WIMSE. Source:
   https://labs.cloudsecurityalliance.org/agentic/agentic-identity-governance-framework-v1/

4. **NIST AI Agent Standards Initiative** (launched Feb 2026) and its NCCoE concept paper reportedly
   recommend **SPIFFE + OAuth as the baseline** for agent authentication. Secondary sourcing only in
   this spike; treat as directional, not as a citable primary. Source (secondary):
   https://www.resilientcyber.io/p/identity-is-the-agentic-ai-problem

### The honest synthesis on "agent-specific" work

There is **no shipping, agent-specific identity standard** in June 2026. The consistent message
across every serious source (IETF agent-auth draft, CSA AIGF, NIST, the resilientcyber analysis) is
the **same**: **agent identity is an acknowledged unsolved problem, and the agreed answer is to
reuse existing workload-identity primitives**, SPIFFE/SPIRE for identity, OAuth 2.0 for delegation,
WIMSE as the standard that formalizes it. The genuinely new agent-specific layer (constrained
delegation chains, sub-agent TTLs, on-behalf-of attenuation) exists today only as **draft
governance frameworks and individual drafts**, not as code you can `helm install` and demo. Source
for the "unsolved, non-deterministic, eliminate standing privilege" framing:
https://www.resilientcyber.io/p/identity-is-the-agentic-ai-problem

---

## Does it map to the "spawn agents and sub-agents, each needs an identity" idea?

**Conceptually: cleanly. Operationally for this workshop: not as a live demo.**

- The mapping Michael wants exists and is articulated best by the **CSA AIGF**: orchestrator agent
  gets a SPIFFE SVID; each spawned sub-agent gets an **ephemeral, short-TTL** identity whose
  privileges are **bounded by the parent** (constrained delegation), with a **delegation-chain audit
  trail**. This is a precise fit for "spawn sub-agents, each needs an identity."
- The concrete controls it would demonstrate, and how they contrast with today's stack:
  - **Short-lived SVIDs vs long-lived SA tokens.** Today the kagent pod authenticates with a
    Kubernetes ServiceAccount token. With SPIRE, the agent (and each sub-agent) would carry a
    minutes-lived SVID that auto-rotates, no standing credential to steal.
  - **mTLS between the agent and its tools/MCP servers.** SVIDs give the agent and each MCP server a
    cryptographic identity, so the gateway can authorize on **verified workload identity** rather
    than network position. This dovetails with `research/04`'s agentgateway tool-authz beat (which
    already matches on JWT claims).
  - **Attestation.** SPIRE proves *what* the workload is (node + workload attestation) before issuing
    identity, you cannot mint a rogue sub-agent identity without passing attestation.
  - **Per-sub-agent identity + delegation ceiling.** A spawned sub-agent gets its own SPIFFE ID and
    cannot exceed the parent's grant, the cryptographic analog of the RBAC scoping the workshop
    already does with `agent/rbac/`.

**But:** standing up SPIRE server + agents, registration entries, the trust domain, SVID issuance,
and an mTLS-aware path between agent, gateway, and MCP, then *also* spawning sub-agents with
attenuated identities, is a **substantial build**. It is a workshop of its own. None of it is
live-verified in this repo (the existing stack is SA + IRSA only), and the agent-specific delegation
layer is **draft-stage** with no runnable reference implementation. Even the friendly source (CSA)
flags **SVID-issuance latency** as a real concern for high-velocity ephemeral sub-agents, i.e. the
exact "spawn many sub-agents fast" case would be the hardest to make behave on stage.

---

## VERDICT: NARRATED slide / governance-map row. NOT live. Do not omit.

**Justification on time budget and payoff.**

- **Why not LIVE:** The 2-hour run-of-show (`BUILD-SPEC.md` Section 2) is already full, three
  clusters, output/input/MCP guard toggles, the cost counter, and a protected 10-minute regroup. A
  credible SPIRE-on-EKS + sub-agent-identity demo is hours of build for one new live beat, none of
  it verified in this repo today, and the agent-specific delegation piece is **draft-only** with no
  OSS reference to install. It fails the same test `research/04` applied to enterprise MCP controls:
  not a clean, OSS, toggleable, visually obvious live toggle by late June. Building it would put the
  protected regroup at risk for a beat that is mostly plumbing the audience cannot see.

- **Why not OMIT:** This is genuinely the **20%** the workshop's thesis is about, and it is the
  single best illustration of "CNCF covers most of it, but agent identity is the open frontier." It
  directly answers Michael's premise (SA + IRSA is the whole identity story today; there is no
  workload-identity-document layer for the agent or its sub-agents). It is also the most
  *defensible* item in the whole agent-governance map because its foundation (SPIFFE/SPIRE) is
  **CNCF-graduated and boring-stable**, while the frontier (per-sub-agent attenuated SVIDs) is
  visibly, honestly nascent. That contrast IS the talk.

- **What the narrated slide should say (and not over-claim):**
  - Today in this repo: agent identity = Kubernetes ServiceAccount + IRSA. Long-lived SA token,
    AWS-scoped IRSA, no cross-workload cryptographic identity, no per-sub-agent identity.
  - The mature answer that already exists: **SPIFFE/SPIRE (CNCF graduated, SPIRE v1.15.1)**, short-
    lived attested SVIDs, mTLS between agent and tools, `aws_iid` node attestation on EKS. Additive
    to IRSA, not a replacement.
  - The frontier (label it as draft, not shipping): **IETF WIMSE** (WIT/WPT, arch draft `-07`, RFC
    in 2027-2028), the individual **`draft-klrc-aiagent-auth-02`** ("agents are workloads, reuse
    WIMSE + OAuth"), and **CSA's AIGF** for the spawned-sub-agent model (ephemeral short-TTL
    sub-agent SVIDs, constrained delegation, delegation-chain audit).
  - The one-line thesis: *the controls (attestation, short-lived identity, constrained delegation,
    mTLS) are not new, the open work is binding them to fast-spawning, non-deterministic agents and
    their sub-agents. That binding is draft-stage in June 2026.*

- **Optional stretch (only if a pre-build spike has spare time, do not promise):** a tiny
  **recorded** clip, SPIRE issues an SVID to the agent pod, `kubectl exec` shows a minutes-lived
  cert that rotates, contrasted with the long-lived SA token. That makes "short-lived vs long-lived"
  tangible in ~60 seconds without risking live time. Treat as `[SPIKE]`; cut first if the build runs
  long.

---

## Unverified / Could not confirm

1. **NIST NCCoE "SPIFFE + OAuth baseline" recommendation**, seen only via a secondary analysis
   (resilientcyber). Fetch the primary NIST NCCoE concept paper before putting NIST's name on a
   slide.
2. **Exact `aws_iid` + EKS Pod Identity interplay** for issuing SVIDs alongside Pod Identity, the
   mechanism is real but the specific co-deployment was not verified hands-on; would need a live
   spike if this ever became a demo rather than a slide.
3. **arXiv `2603.24775` ("AIP: Agent Identity Protocol for Verifiable Delegation Across MCP and
   A2A")**, impossible year-stamp (2603); discarded, grounds nothing. Same malformed-arXiv pattern
   already noted in `research/04-mcp-security.md`.
4. **A2A protocol identity model**, named (150+ orgs) but its concrete identity/credential mechanism
   was not run down in this spike; out of scope for the SPIFFE question.
5. **CSA AIGF status**, it is a draft white paper, not a ratified spec; quote it as "CSA draft
   guidance," not as a standard.
