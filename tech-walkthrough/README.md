<!-- ABOUTME: The tech.agenticburn.com technical walkthrough: a self-contained reveal.js deck of the -->
<!-- ABOUTME: whole Watch It Burn stack, foundation to AI layer. How to view it and how to host it. -->

# Technical walkthrough (tech.agenticburn.com)

A self-contained [reveal.js](https://revealjs.com/) slide deck that walks the entire Watch It Burn
stack, foundation to AI layer, one focused slide per component, with mermaid diagrams for the
architecture and the beat flows. Built so Michael and Whitney can study every part of the stack.

`index.html` is the whole deck. reveal.js and mermaid load from a CDN, so there is no build step.

## View it locally

```bash
cd tech-walkthrough
python3 -m http.server 8000   # then open http://localhost:8000
```

Opening `index.html` directly works too, but a local server is more reliable for the ES-module
imports (reveal + mermaid). Press `S` for speaker view, `Esc` for the slide overview, `?` for help.

## What it covers

Title and thesis → architecture overview → Foundation (Terraform / EKS / VPC-CNI / Pod Identity /
node config) → GitOps (ArgoCD app-of-apps) → Platform controls (Kyverno / RBAC / floor /
NetworkPolicies) → Runtime security (Falco / Talon / podPidsLimit) → Mesh and certs and secrets
(Istio / cert-manager / ESO) → Observability (OTel / Prometheus / Grafana / Loki / Tempo / Datadog)
→ AI layer (kagent + Bedrock / guard-proxy / LLM Guard / MCP / cost counter) → Backstage and burn
targets → the beats recap → provisioning and distribution.

Every component slide carries its pinned version; the versions are kept in sync with the gitops
`targetRevision` pins and the Terraform module versions (source of truth).

## Host it at tech.agenticburn.com

The deck is static, so any static host works. Two simple paths:

1. **Railway static site** (matches the lab-distribution host): serve this directory; add the custom
   domain `tech.agenticburn.com` in Railway; it prints a CNAME (and a verify TXT) to add at Namecheap.
2. **GitHub Pages**: publish `tech-walkthrough/` from the repo; set the Pages custom domain to
   `tech.agenticburn.com`.

DNS lives at **Namecheap** (agenticburn.com). Add the CNAME with the Namecheap API using the
read-then-merge pattern (never replace the whole host set):
see `~/.claude/rules/tools/namecheap-api.md`. The `HostName` is `tech`, the target is whatever the
chosen host gives (Railway `*.up.railway.app` or GitHub Pages `peopleforrester.github.io`).

## Keeping versions accurate

When a component version changes in `gitops/apps/*.yaml` (`targetRevision`) or in the Terraform
module pins, update the matching `<span class="tag">` in `index.html`. The version tags are the
study reference, so they must match what actually deploys.
