<!-- ABOUTME: The walkthrough.agenticburn.com deck: the live-delivery run-of-show for Watch It Burn -->
<!-- ABOUTME: (open cold, the BurritoBot frame, three rounds, land the governance map). View + host. -->

# Workshop walkthrough (walkthrough.agenticburn.com)

A self-contained [reveal.js](https://revealjs.com/) slide deck that walks the **live delivery of the
workshop** — the run-of-show as it is actually run with attendees: open cold on the hook, tell the room
they already have a cluster and leap in, the three-cluster spine (it burns → it's blocked but still
costs → you guard it yourself), and land on the governance map. It is the facilitator's how-we-run-it
walkthrough, not a foundation-up architecture tour.

The slides are what the room sees; the **speaker notes** (press `S`) carry the delivery detail —
timing, who leads (Michael / Whitney), the `/toggle` commands, the hand-offs, and the fallbacks.
Source of truth: `facilitation/runbook.md`, `cold-open-script.md`, and `governance-map.md`.

`index.html` is the whole deck. reveal.js loads from a CDN, so there is no build step.

## View it locally

```bash
cd railway/walkthrough
python3 -m http.server 8000   # then open http://localhost:8000
```

Opening `index.html` directly works too, but a local server is more reliable for the ES-module
imports (reveal + mermaid). Press `S` for speaker view, `Esc` for the slide overview, `?` for help.

## What it covers

The session in delivery order: open cold (the agent-deleted-my-cluster hook → production stakes) →
the promise + "you already have a cluster, leap in" → the BurritoBot frame (a witchy burrito
storefront, the bat-spit-hot-sauce secret, and the deliberately loose system prompt: never trust it to make
the agent behave) → how we watch (the trace dashboard) → the three rounds (Round 1 burns + the cost
counter → Round 2 CNCF controls block Challenges 1–4 but the bill still moved → Round 3 your own
cluster, toggle the output/input/MCP guards for Challenges 5–7 + free-play) → the optional trace
re-leak trap → the governance map + cost ladder → take it home.

Component detail (what Kyverno / Pod Identity / kagent actually are) lives in the **speaker notes**,
surfacing only where the flow hits each control — never as an opening lecture, mirroring the runbook's
reveal discipline (introduce each control WHEN it turns on, not up front).

## Hosting (LIVE at https://walkthrough.agenticburn.com)

Hosted on **Railway** (the repo is private, so GitHub Pages would need a paid plan). The `Dockerfile`
here serves the deck with nginx; `railway.json` builds from it. How it was deployed and wired:

```bash
cd railway/walkthrough
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

## Keeping it in sync

When the run-of-show changes (timing, owners, toggles, beats), update `index.html` to match
`facilitation/runbook.md` — the runbook is the source of truth for delivery. This deck is the visual
walkthrough of it, not a second copy to drift. Pinned component versions live in `VERSIONS.lock`.
