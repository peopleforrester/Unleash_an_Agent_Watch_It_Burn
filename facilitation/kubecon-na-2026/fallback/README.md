<!-- ABOUTME: The KubeCon NA 2026 breakout's recorded fallback for the live input (#452): the replayable prompt set,
     ABOUTME: and the screenshots deck, where each lives, how each is made and when each is used. -->

# Recorded fallback for the KubeCon breakout

Point 9 of the accepted abstract has the room bring its weirdest off-topic question
and send it live from their phones. A ballroom's venue Wi-Fi is the likeliest thing
to fail, so this directory holds two fallbacks, one per thing that can break. They
go with the rollback steps in `facilitation/kubecon-na-2026-run-of-show.md`.

| What broke | Fallback | Where |
|---|---|---|
| The venue network cannot carry the room, but the clusters answer | Replay the room's prompts from a laptop on a phone hotspot | `prompts.yaml`, sent by `scripts/replay-prompts.py` |
| Nothing live works | The screenshots deck | `screenshots/deck.html`, its shots listed in `assets.yaml` |

The segment videos the issue first asked for are not kept here. Michael dropped the
recorded-fallback milestone (M4, #613) on 2026-11-01, as handled outside this repo
and not a blocker, so the rollback steps go from the replay straight to the deck.

This is not what `challenges/<beat>/fallback.*.sh` does. Those replace one agent
call that wandered; they need the cluster and the network. Everything here is for
the case where the room's input, or the whole network, is gone.

## 1. The replayable prompt set

`prompts.yaml` is what the room types in each segment: every room prompt on
`/kubecon` (`gitops/ai-layer/web/kubecon.html`), word for word, under the segment the
page shows it in. Segment 1 is the linked-list ask; segments 2 to 5 are each
challenge's ask; segment 6 sends the four off-topic asks, the linked list among them,
for the on-topic guard. The one prompt not on the page is the smoke prompt, the
order (`segments: []`), which the E2E check sends with `--tag smoke` and no
`--segment` picks (#1104). Each prompt says what should land on screen. The offline
suite fails if the set and the page drift apart.

```bash
# from the repo root, on the presenter laptop, on the phone hotspot
python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 1

# the segment on stage, when the room cannot send it
python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 3

# see what would be sent, no network
python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --dry-run
```

It needs `python3` and PyYAML, nothing else, and it goes through the same front door
as a phone: the console's nginx `/chat`, then guard-proxy `/chat`, with the
storefront's body (the prompt, a session and a witch name) and its
`X-BurritoBot-Session` header. So the replayed prompts climb the cost counter and
show on the prompt wall like typed ones. Each prompt is its own conversation, as
separate phones would be, except where prompts share a `thread`: Challenge 2's Tron
ask and its follow-up are one conversation.

- **The target is required.** A replay that guessed could spend the room's prompts on
  the wrong cluster.
- **Pacing.** One prompt at a time, the next starting no sooner than 6 seconds
  after the last (`--interval`). guard-proxy allows 150 model-bound requests per
  60 seconds for the whole cluster (#450), and the presenters' own asks share that
  window, so the script refuses anything that would take more than half of it.
- **It stops at the first failure.** A network or TLS error, a timeout, any status
  but 200, an empty reply, or a limit refusing it ends the run with exit 1 and says
  which. The limits answer with a 200 and a sentence, so the script reads the
  sentence: guard-proxy's two rate limits, its cost cap and its budget guard, and the
  console nginx's 10 a minute per conversation. Do not retry from the stage: move to
  the next rollback step.
- **What is not a failure.** A guardrail blocking a prompt (after a switch, that is
  the demo working), and a marker that did not appear (the model declined; resend
  it, or use the next prompt in `challenges/PROMPT-CATALOG.md`). Both are printed.
- **What the challenge prompts do.** Segments 2 to 5 do what the room's own asks do
  on the public bot: read the CEO's record, deploy an image, read the recipe file,
  post to the beacon, deploy a Joker. Only replay them in the session, or on a
  bring-up that is reset afterwards. The Night Before replays segment 1 alone.

## 2. The screenshots deck

`screenshots/deck.html` opens from disk in any browser, with no network, and steps
through one PNG per beat: right arrow, space or a click forward, left arrow back,
F for full screen. The shots, in order, are listed in `assets.yaml`; the page carries
the same list, written into it by `python3 scripts/check-fallback-assets.py
--write-deck` after any edit to `assets.yaml` (the offline suite fails if the two
differ). A shot that is not there shows as a red MISSING card. The PNGs are committed
into `screenshots/`.

The deck holds 13 shots, every segment from 1 to 6, taken on the two live clusters
on 2026-11-04 and 2026-11-06. Two planned shots are not in it. They were to be taken
by hand at the first full rehearsal (Challenge 1's Datadog trace and the
`guardrails-on` terminal), and that rehearsal's recording left this repo with M4.
Each segment's narration covers its missing beat. Challenge 2's public image (03-1)
was taken on 2026-11-06, after #939: the room's Tron ask had not deployed on the
public bot in four tries on 2026-11-04 and 2026-11-05, because the model sent
`deploy_app` the manifest "Tron". The shot shows `deploy_app` as #939 left it, which
deployed that name on a public nginx image. Since #991 `deploy_app` refuses a bare
name and BurritoBot's prompt names the Tron game's exact image, so 03-1 is owed a
retake on the bot that runs #991.

Each shot says how it is made (`capture` in `assets.yaml`):

- **chat:** `scripts/capture-fallback-screenshots.py` sends the shot's prompt in the
  real storefront, in headless Chromium, on the cluster the shot names, and saves the
  screen with the reply. It reads that cluster's `/controls` first and refuses the
  shot unless each control the shot lists reads as listed, so a guarded shot is
  never taken on an open bot. It never flips a guard. A shot with a `toggle` waits
  for that command on the private terminal, then `--shot` takes it; put the guards
  back after (`guards-off`, `guardrails-off`).
- **page:** the same script screenshots the URL.
- **by_hand:** taken from the projector output, for a screen the script cannot
  drive, such as a signed-in Datadog tab or a terminal. No shot in the deck is taken
  this way now.

```bash
python3 scripts/capture-fallback-screenshots.py --list \
    --community https://attackme.burritobot.co --private https://burritobot-private.burritobot.co
python3 scripts/capture-fallback-screenshots.py \
    --community https://attackme.burritobot.co --private https://burritobot-private.burritobot.co
```

It needs `uv`; Chromium comes through the Playwright pinned in
`verify/playwright_browsers.py`. The script checks that the bot answered, not what it
said, so read every PNG before committing it, and take a shot again with `--shot`
when the model wandered.

## Proving it

The Night Before, on each presenter laptop:

```bash
python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 1   # over the hotspot
python3 scripts/check-fallback-assets.py      # the deck and every screenshot in place, each a real PNG
```

The first is the one rehearsal of the replay that the run-of-show's Night Before step
asks for; it costs one Bedrock call. The second exits 1 if any shot the deck lists is
missing, empty, or not a PNG.

`bash verify/run-tests.sh` covers the replay offline: it drives the real guard-proxy
`/chat` handler on loopback and checks the replay stops on its rate limits, its cost
cap, its budget guard, its 502 and an empty reply, and on the console nginx's
per-conversation limit. `bash verify/run-e2e.sh` sends the smoke prompt to the
cluster it is pointed at (`verify/test_replay_prompts_live.py`).
