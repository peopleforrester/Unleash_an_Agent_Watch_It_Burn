<!-- ABOUTME: The walkthrough.agenticburn.com technical walkthrough: a self-contained reveal.js deck of the -->
<!-- ABOUTME: whole Watch It Burn stack, foundation to AI layer. How to view it and how to host it. -->

# Technical walkthrough (walkthrough.agenticburn.com)

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

## Hosting (LIVE at https://walkthrough.agenticburn.com)

Hosted on **Railway** (the repo is private, so GitHub Pages would need a paid plan). The `Dockerfile`
here serves the deck with nginx; `railway.json` builds from it. How it was deployed and wired:

```bash
cd tech-walkthrough
railway init --name watch-it-burn-walkthrough     # project on Michael's Railway workspace
railway up --ci                                    # builds the Dockerfile, deploys the service
railway variables --set PORT=80                    # REQUIRED: Railway's edge routes to $PORT; nginx
                                                   # listens on 80, so without this it 502s
railway domain walkthrough.agenticburn.com         # prints the CNAME + the _railway-verify TXT
```

DNS lives at **Namecheap** (agenticburn.com). Both records (CNAME `walkthrough` → the
`*.up.railway.app` target, and TXT `_railway-verify.walkthrough` → `railway-verify=...`) were added
with the Namecheap API using the **read-then-merge** pattern (getHosts, append, setHosts) so the
existing host set is never clobbered. See `~/.claude/rules/tools/namecheap-api.md`. The verify TXT is
load-bearing: without it Railway's cert stays stuck at `VALIDATING_OWNERSHIP`.

## Keeping versions accurate

When a component version changes in `gitops/apps/*.yaml` (`targetRevision`) or in the Terraform
module pins, update the matching `<span class="tag">` in `index.html`. The version tags are the
study reference, so they must match what actually deploys.
