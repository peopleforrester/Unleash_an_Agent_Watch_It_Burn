<!-- ABOUTME: The KubeCon NA 2026 breakout's recorded fallback for the live input (#452): the replayable prompt set,
     ABOUTME: the per-segment videos and the screenshots deck, where each lives and when each is used. -->

# Recorded fallback for the KubeCon breakout

Point 9 of the accepted abstract has the room bring its weirdest off-topic question
and send it live from their phones. A ballroom's venue Wi-Fi is the likeliest thing
to fail, so this directory holds three fallbacks, one per thing that can break. They
go with the rollback steps in `facilitation/kubecon-na-2026-run-of-show.md`.

| What broke | Fallback | Where |
|---|---|---|
| The venue network cannot carry the room, but the clusters answer | Replay the room's prompts from a laptop on a phone hotspot | `prompts.yaml`, sent by `scripts/replay-prompts.py` |
| Nothing live works, video plays | One video per demo segment, from the first full rehearsal | `videos/segment-<N>-*.mp4`, listed in `assets.yaml` |
| Nothing live works and video will not play | The screenshots deck | `screenshots/deck.html` |

This is not what `challenges/<beat>/fallback.*.sh` does. Those replace one agent
call that wandered; they need the cluster and the network. Everything here is for
the case where the room's input, or the whole network, is gone.

## 1. The replayable prompt set

`prompts.yaml` is what the room would have typed in segment 2: two on-topic asks
that prove it is a working burrito-chain bot, the weird off-topic questions, and
the CEO-record leak copied word for word from `/brief` Phase 1. Each prompt says
what should land on screen.

```bash
# from the repo root, on the presenter laptop, on the phone hotspot
python3 scripts/replay-prompts.py --target https://attackme.agenticburn.com

# just the off-topic asks, e.g. re-sent in segment 7 on the admin cluster
python3 scripts/replay-prompts.py --target https://michael-admin.agenticburn.com --tag off-topic

# see what would be sent, no network
python3 scripts/replay-prompts.py --target https://attackme.agenticburn.com --dry-run
```

It needs `python3` and PyYAML, nothing else, and it goes through the same front door
as a phone: the console's nginx `/chat`, then guard-proxy `/chat`. So the replayed
prompts climb the cost counter and show on the side-screen feed like typed ones.
Each prompt is its own browser session, as fifty phones would be.

- **Pacing.** One prompt at a time, the next starting no sooner than 6 seconds
  after the last (`--interval`). guard-proxy allows 120 model-bound requests per
  60 seconds for the whole cluster (#450), and the presenters' own asks share that
  window, so the script refuses anything faster than one a second.
- **It stops at the first failure.** A network or TLS error, a timeout, any status
  but 200, an empty reply, or guard-proxy refusing it (its rate limit or its cost
  cap, which come back as a 200 with a canned reply) ends the run with exit 1 and
  says which. Do not retry from the stage: move to the next rollback step.
- **What is not a failure.** A guardrail blocking a prompt (on the admin cluster that
  is the demo working), and a marker that did not appear (the model declined; resend
  it, or use the next prompt in `challenges/PROMPT-CATALOG.md`). Both are printed.

## 2. The segment videos

One video for each demo segment of the run-of-show, 2 to 7, recorded at the first
full rehearsal on the KubeCon clusters. The exact files are in `assets.yaml`:

```
videos/segment-2-wide-open-start.mp4
videos/segment-3-platform-tour.mp4
videos/segment-4-kubernetes-layers.mp4
videos/segment-5-ai-guardrails-live.mp4
videos/segment-6-genai-observability.mp4
videos/segment-7-burritos-only.mp4
```

Record each as a screen capture of the projector output at 1920x1080, MP4 (H.264),
with the presenters' audio. Each one starts at the segment's first screen and ends
at its hand-off line, so the next one can be cued from the run-of-show.

**Where the videos live.** Not in git: `.gitignore` keeps `videos/*.mp4` out. Six
rehearsal captures are hundreds of megabytes that every clone would carry forever,
and a dead network is the case they cover, so a link is useless on the day. After
the rehearsal, copy them to these paths on both presenter laptops, and keep a
second copy on a USB stick in the presenter bag. Storing them elsewhere (Git LFS, a
release asset) is open for Michael (#452).

## 3. The screenshots deck

`screenshots/deck.html` opens from disk in any browser, with no network, and steps
through one PNG per beat: right arrow, space or a click forward, left arrow back,
F for full screen. The shots it expects are listed in `assets.yaml` (and inside
the page; the offline suite holds the two lists together). Take each at the
rehearsal, from the projector output, and commit the PNGs into `screenshots/`
under the names listed. A shot that is not there shows as a red MISSING card.

## Proving it

The Night Before, on each presenter laptop:

```bash
python3 scripts/check-fallback-assets.py      # every video and screenshot in place, of the right type
python3 scripts/replay-prompts.py --target https://attackme.agenticburn.com   # the full set, over the hotspot
```

The first exits 1 until the rehearsal files are copied in. The second is the one
rehearsal of the replay that the run-of-show's Night Before step asks for; it costs
about ten Bedrock calls.

`bash verify/run-tests.sh` covers the replay offline: it drives the real
guard-proxy `/chat` handler on loopback and checks the replay stops on its rate
limit, its cost cap, its 502 and an empty reply. `bash verify/run-e2e.sh` sends
the smoke prompt to the cluster it is pointed at.
