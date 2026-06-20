<!-- ABOUTME: Durable archive of Whitney's Google Doc comments + all replies, with the section each
<!-- ABOUTME: anchors to. Backup so comments are never lost if a Doc is ever re-synced/overwritten. -->

# Whitney comment archive

Captured 2026-06-20 from the live Google Docs via the Drive API. Each entry keeps the original
section reference (the quoted text the comment anchors to) plus every reply (hers and the build updates).

## Watch It Burn - 3 - Run of Show (17 comments)

### [3.1] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "0:45–1:30, Cluster 3: your own cluster, guards on + free-play (Whitney narrates, Michael on the gaps) Each attendee drives their own Cluster 3 (chat UI + terminal). An agent is already running on it. With 45 minutes there is room to demo each guard, run the optional beats if time allows, and let the room try to beat it."
- **Comment:** I said this during our live conversation, but I don't have a clear story for this in my mind. I don't have a good mental model. I don't know these technologies.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.2] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Output sanitization is on, so the sentinel is blocked from the response. Turn on OTel content capture and re-run. The response is still clean, but the sentinel now sits inside the trace span. The observability you trusted is a second, unguarded sink."
- **Comment:** I'm interested whether Gateway will block prompts from showing up in Datadog. 

Or I'm wondering if we can show a prompt in Datadog before it hits the gateway and the same prompt after the gateway.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Datadog is now the primary sink; the guard-proxy sits in front, so before/after-gateway prompt visibility is demoable.

### [3.3] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Free-play"
- **Comment:** They each have a demo app running in their own cluster, right? What would it take for that demo app to have a public endpoint? 

We could take volunteers, for them to share their endpoint. In the whole room, try to break that person's cluster. Maybe they give us their Datadog login info. 

But the observability lags behind what's actually happening. I don't know that it'd make for super fascinating live viewing. 

Maybe they just trade agent endpoints with each other. Pick a partner and try to break each other's cluster.

### [3.4] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "input, output, and tool calls on the dashboard"
- **Comment:** also cost

We'll be able to see stuff in our cluster that we're demoing with, and we can direct them about how to see it in their own too.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Cost is on the dashboard too (witb_cost_usd panel in agent-observability).

### [3.5] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Whitney narrates the interesting ones on the trace view."
- **Comment:** We're giving them their own Datadog so they will have their information from their own cluster in their own trial datadog account in their own browser. I won't have a way to see what everyone's doing individually and show that on a main screen or anything.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Datadog wired as primary (each attendee their own); collector exports there first, Grafana/Tempo as fallback.

### [3.6] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "MCP tool restriction"
- **Comment:** What is the mechanism here? kmcp (part of kagent)? Or Langgraph/whatever? Does this fit the story of us being able to configure these things at the platform level?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.7] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Input sanitization"
- **Comment:** And this is the same technology? kgateway?

I think we should mention caching too, yes? Since we're talking about cost?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Prompt caching folded into the cost thesis (BUILD-SPEC §1).
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.8] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Output sanitization"
- **Comment:** What technology enables this? An Agent Gateway?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.9] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "the tokens are already spent."
- **Comment:** Cost isn't necessarily the only problem here. Another problem is maintenance, right? If we're adding guardrails on a per-app or per-agent basis, that has more room for maintenance and more chances for failure or something getting missed. What if we could do that at a different abstraction layer where it automatically happens for any workload that's running in the cluster? 

Am I understanding that correctly?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Added to the thesis: maintenance cost of per-agent guardrails vs the cluster abstraction layer (BUILD-SPEC §1).

### [3.10] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Walk each wall with its distinct error:"
- **Comment:** I'd like to be more specific about what we expect to hit up against here. 

A kyverno message, ok. 
A Falco block
Sending data outside the cluster?

For cluster one and cluster two, we could have a target S3 bucket we give them and challenge them to get secrets into it, like a funny game of basketball.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Added the ESO/S3 exfil 'basketball' game + challenge ladder as optional challenges (runbook).

### [3.11] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "CNCF guardrails block it"
- **Comment:** Now a tour of the security CNCF projects that are enabled

That way, we're not explaining a bajillion projects to them all at once. Also, then I get to explain some projects too. 
(◠‿・)—☆
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Done: CNCF security projects are now introduced at Cluster 2 as they turn on, and you present some (runbook 0:25 section).

### [3.12] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "platform tour"
- **Comment:** I think the platform tour should be the guard rails OFF version of the platform. Minimal security features.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Done: the Cluster 1 tour is now the guards-OFF / minimal view (runbook 0:00 section).

### [3.13] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Argo CD, Kyverno, Falco, Prometheus/Grafana/Tempo/Loki, cert-manager, External Secrets, Backstage"
- **Comment:** We have Datadog. So no Grafana needed. If the agent is written in TypeScript or JavaScript, I can run Spinybacked Orbweaver to instrument it. Personally, I've been playing with using pino for logs too and getting that correlated with my telemetry and then working out how to add attributes to the traces that then show up as metrics 

Also, some of these, like Falco, won't get turned on until cluster two, so I don't think we should talk about them yet. I think we should talk about them when they get turned on. But you could argue that cert manager and external secrets make sense at this stage. Although again, I think we should store some secrets in the cluster to try to challenge them to get the agent to expose the secrets.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Datadog added as the PRIMARY telemetry sink; Grafana/Tempo kept as the analog fallback (gitops/apps/otel-collector.yaml; BUILD-PLAN). You drive Datadog, we finish Grafana.

### [3.14] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "the trace re-leak trap"
- **Comment:** What;s this?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.15] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Whitney (Michael on controls) Cluster 2, CNCF guardrails block it"
- **Comment:** I'll talk about what CNCF guardrails got added here?
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Yes, that intro is yours, moved to the Cluster 2 segment (runbook 0:25).

### [3.16] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "CNCF"
- **Comment:** Here I am picturing Harbor with image signing, network policy, Falco, maybe external secrets operator,  service mesh would make sense for encrypted pod-to-pod communication. Spiffe/Spire for identity, and then we can use that identity to make cluster-level policy with Kyverno, OpenTelemetry instrumentation, especially the agent instrumented with OpenTelemetry and the prompts flowing to Datadog, but all of it instrumented/captured really

Is that what you were thinking?
  - **Reply, Whitney Lee (2026-06-19):** One thing we can talk about here is also using the prompt to let it know what guard rails exist so it doesn't try things that I can't do. That's a money saver.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Added a cosign image-signing Kyverno policy (Audit). NetworkPolicy/Falco/ESO already present. Istio mesh + SPIFFE/SPIRE are planned (spike).
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [3.17] Whitney Lee, 2026-06-19 (open)
- **Comment:** Instrumented w Otel and data flowing to Datadog, and see about getting that data scraped quickly. 

Ideally, we want to see what prompt finally killed the cluster. 

Also, we should be ready with some prompts and attack paths. 1. Instead of just saying, "Hey, kill this," maybe challenge them to exfiltrate data.
2. Then challenge them to get the agent to tell them secrets. Maybe we could make some funny secrets (Kubernetes secrets).
3. Then challenge them to break the cluster altogether.
  - **Reply, Whitney Lee (2026-06-19):** for the first cluster
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Added a challenge ladder (exfiltrate -> reveal secrets -> break cluster) as an optional beat (runbook).

## Watch It Burn - 6 - Build Spec (2 comments)

### [6.1] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "Architecture"
- **Comment:** I don't see anything about building the agent itself.
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Full mechanism + roles map (how this is actually wired, where each guardrail lives, what invokes what) is in the new doc 'Watch It Burn - 7 - Stack Walkthrough': https://docs.google.com/document/d/1l5JqnSqTbFgo-J0cXFd_jUdM21HA7PO4n1ttl42nR-c/edit

### [6.2] Whitney Lee, 2026-06-19 (open)
- **Anchored to section:** "kube-prometheus + OTel→Tempo to finish (rev3 kps install wedged, redo lighter, focus Tempo+Grafana trace view)."
- **Comment:** Datadog and OTel
  - **Reply, Michael Forrester (2026-06-20):** [Build update] Datadog set as primary, OTel collector exports to it first (gitops/apps/otel-collector.yaml).

_Total: 19 comments archived._
