*One-page attendee handout: reach your terminal, talk to your agent, find the beats. No local install. Local-kubeconfig fallback documented.*

# Quickstart — Your Cluster, Your Agent

Welcome. You have your own isolated Kubernetes cluster and an AI agent already running on it. Everything happens in your browser. **No local install.**

## 1. Get to your terminal

- Open the **link** (or scan the **QR code**) the facilitators handed you.
- A web terminal loads in your browser, already connected to *your* cluster. No login, no setup.
- You'll see a shell prompt. That's your cluster. Anything you run here only touches your cluster — not your neighbor's.

If the terminal doesn't load, tell a facilitator before trying anything else. There's a fallback (below), but the web terminal is the main path.

## 2. Talk to your agent

- Your agent is already deployed and scoped. Send it a prompt the way the facilitators show you on screen.
- Start with the warm-up prompt they give you and confirm you get a response. That proves your path works before any attack.
- You'll watch what the agent does in a shared **trace view** on the facilitators' screen — that's how we'll follow each attack as it lands or gets stopped.

## 3. Where the beats live

Each round ("beat") has its own folder in the workshop repo on your cluster:

- `beats/01-cncf-wall/` — round 1: unleash the agent on the platform.
- `beats/02-sanitization/` — round 2: what goes in, what comes out.
- `beats/03-bad-mcp-excessive-agency/` — round 3: when the agent's tools turn on it.

Each beat folder has a `beat.md` with the steps for that round. The facilitators drive the toggles; you drive your agent and watch what happens on your own cluster.

> Every secret you'll see is **obviously fake** (it starts with `FAKE-`). Nothing real is ever in your cluster.

## 4. If the web terminal won't work — local fallback

Only use this if a facilitator tells you to. It needs `kubectl` on your laptop.

1. Ask a facilitator for **your kubeconfig file** (per-attendee, scoped to your cluster only).
2. Save it locally, e.g. `~/burn-workshop.kubeconfig`.
3. Point `kubectl` at it for this session:
   ```bash
   export KUBECONFIG=~/burn-workshop.kubeconfig
   kubectl get nodes        # should list your cluster's node(s)
   ```
4. From here, drive the beats exactly as you would in the web terminal.

If `kubectl get nodes` fails, you likely can't reach the cluster API from your network — that's expected on some conference WiFi. Go back to the web terminal path, or follow along on the facilitators' screen. A facilitator can run the whole sequence from the front if the room can't get online.

## Need help?

Raise a hand. The facilitators have a reliable backup path for every beat, so even if your agent wanders, the lesson still lands.
