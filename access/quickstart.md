*One-page attendee handout: reach your terminal, talk to your agent, find the beats. No local install. Local-kubeconfig fallback documented.*

# Quickstart, Your Cluster, Your Agent

Welcome. You have your own isolated Kubernetes cluster and an AI agent already running on it. Everything happens in your browser. **No local install.**

## 1. Open your console

- Open the **link** (or scan the **QR code**) the facilitators handed you. Your console loads in the browser — no login, no setup, no install.
- **Left:** the instructions for the current beat. **Right:** two tabs — **Terminal** and **Agent chat** — with a live **cost counter** at the top.
- The **Terminal** is a shell already connected to *your* cluster (`kubectl` just works — try `kubectl get pods -A`). Anything you run touches only your cluster, not your neighbor's.

If the console doesn't load, tell a facilitator before trying anything else. There's a fallback (below), but the console is the main path.

## 2. Talk to your agent

- Switch to the **Agent** tab. Your agent is already deployed and scoped — send it a prompt the way the facilitators show you on screen.
- Start with the warm-up prompt they give you and confirm you get a response. That proves your path works before any attack.
- Watch the cost counter move, and follow the agent's input/output/tool calls on the shared **trace view** on the facilitators' screen — that's how we follow each attack as it lands or gets stopped.

## 3. Where the beats live

Each round ("beat") has its own folder in the workshop repo on your cluster:

- `challenges/01-cncf-wall/`, round 1: unleash the agent on the platform.
- `challenges/02-sanitization/`, round 2: what goes in, what comes out.
- `challenges/03-bad-mcp-excessive-agency/`, round 3: when the agent's tools turn on it.

Each beat folder has a `beat.md` with the steps for that round. The facilitators drive the toggles; you drive your agent and watch what happens on your own cluster.

> Every secret you'll see is **obviously fake** (it starts with `FAKE-`). Nothing real is ever in your cluster.

## 4. If the web terminal won't work, local fallback

Only use this if a facilitator tells you to. It needs `kubectl` on your laptop.

1. Ask a facilitator for **your kubeconfig file** (per-attendee, scoped to your cluster only).
2. Save it locally, e.g. `~/burn-workshop.kubeconfig`.
3. Point `kubectl` at it for this session:
   ```bash
   export KUBECONFIG=~/burn-workshop.kubeconfig
   kubectl get nodes        # should list your cluster's node(s)
   ```
4. From here, drive the beats exactly as you would in the web terminal.

If `kubectl get nodes` fails, you likely can't reach the cluster API from your network, that's expected on some conference WiFi. Go back to the web terminal path, or follow along on the facilitators' screen. A facilitator can run the whole sequence from the front if the room can't get online.

## Need help?

Raise a hand. The facilitators have a reliable backup path for every beat, so even if your agent wanders, the lesson still lands.
