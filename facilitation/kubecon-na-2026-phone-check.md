<!-- ABOUTME: The real-phone check for the KubeCon NA 2026 breakout's audience page, the projector QR and the
     ABOUTME: Feedback link (#451). A person fills it in on real devices; headless emulation does not count. -->

# KubeCon NA 2026: real-phone check for the audience page

The room opens one page from their phones: the community BurritoBot at
**https://attackme.burritobot.co/** (segment 2 of
`facilitation/kubecon-na-2026-run-of-show.md`). This file is the check that the
page, the QR code on the projector and the Feedback button work for them. A
person does it, on the live community cluster, after the Night Before bring-up.

**Headless browser emulation does not count.** The BurritoBot repo was checked
only in Chromium emulation (320, 390 and 412 px) and left this row open. Every
row below is one real phone, in hand, on the network named.

## Result

**Signed off by Michael on 2026-11-01:** "Already done. It works great"
([#451 comment](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/451#issuecomment-6551797906)).
He ran the check himself on real phones. His comment does not give the
per-row detail (phone models, OS versions, distances), so the tables below are
left blank rather than filled in from a guess. They stay here for the next
event's check.

## Where the two addresses come from

Both come from one file, `gitops/ai-layer/web/event.js`:

- `publicUrl`, `https://attackme.burritobot.co/`, is what the QR encodes.
  burritobot.co is the displayed domain (#651); `attackme.agenticburn.com`
  still serves the same bot as its twin.
- `feedbackUrl`, `https://feedback.burritobot.co/?source=burritobot`, is where
  the storefront's Feedback button goes: the talk's own short form on our
  feedback app (EVENT_ID `kubecon-na-2026`, Michael's decision of 2026-11-08,
  #1162). It opens in a new tab, so the chat is still there afterwards, and no
  cluster or user is added to it. `source=burritobot` is stored with each
  response, so the storefront's answers are told apart from the deck QR's
  `source=deck`. The form's thanks page links on to the Sessionize rating for
  session 1249553.

The projector QR is `facilitation/kubecon-na-2026-audience-qr.svg` (version 3,
error correction M, black on white). Put that file on the slide; do not make a
new code in some other tool. If `publicUrl` changes, regenerate the QR:

```bash
uv run --no-project --with segno==1.6.6 python -I scripts/audience-qr.py
```

`bash verify/run-tests.sh` fails while the QR and `event.js` disagree, and
`verify/test_audience_page_e2e.py` (in `bash verify/run-e2e.sh`) re-renders it
byte for byte.

For the 2-hour workshop, set `feedbackUrl` and `publicUrl` in `event.js` to `""`.
The button then goes back to the workshop's `/quick` form and carries the
student's cluster and user again.

## Before you start

- [ ] The community cluster is up and `https://attackme.burritobot.co/` shows
  the storefront on a laptop.
- [ ] `curl -s https://attackme.burritobot.co/event.js` returns the `event.js`
  in this repo. If it does not, the console pod has not rolled yet.

## Real devices

One iPhone in Safari and one Android phone in Chrome, each on venue-like Wi-Fi
(one shared access point with many clients behind one NAT, not a home network)
and on cellular with Wi-Fi turned off. On each row, write **yes** or what went
wrong, plus the phone model and OS version.

What each column means:

- **Loads:** the storefront appears within a few seconds, with the menu and the
  chat box. The public bot carries no banner (the community banner was retired in
  #761; only the private administrator bot shows one).
- **No overlap:** in portrait, scrolled top to bottom, no text sits on top of
  other text, nothing is cut off at the side, and the keyboard does not cover the
  send button.
- **Prompt answered:** send "What burritos do you have?". A menu answer, or a
  refusal you can read, counts. "the kitchen isn't answering" or "NO BURRITOS FOR
  YOU" does not.
- **Feedback opens:** tap Feedback. A new tab opens on our form at
  `feedback.burritobot.co/?source=burritobot`, naming this talk, with the
  usefulness question (1 to 5) and no lab, Datadog or sponsor link, and the chat
  tab is still there when you switch back.

| Phone | Network | Model and OS | Loads | No overlap | Prompt answered | Feedback opens | Checked by, date |
|---|---|---|---|---|---|---|---|
| iPhone, Safari | venue-like Wi-Fi | | | | | | |
| iPhone, Safari | cellular | | | | | | |
| Android, Chrome | venue-like Wi-Fi | | | | | | |
| Android, Chrome | cellular | | | | | | |

## The projector QR, from the back of the room

Project `facilitation/kubecon-na-2026-audience-qr.svg` at the size the slide will
use, in a room at least as deep as the session's room (conference-knowledge (`events/registry.yaml`, entry `kubecon-na-2026`))
or as close as you can get.
Scan it with each phone's own camera app, not a QR app, from the back row.

| Phone | Distance from the screen | Scans first try | Opens https://attackme.burritobot.co/ | Checked by, date |
|---|---|---|---|---|
| iPhone, camera | | | | |
| Android, camera | | | | |

## Submit the form, then the Sessionize link

On each phone, from the Feedback tab the storefront opened, submit the form once:
tap a usefulness score and type `phone check` in the "one thing you'll change"
box, so the answer is easy to find and set aside. The thanks page appears, and
its Sessionize link opens session 1249553, "BurritoBot Said Let's Dance, the
Platform Said No". Then confirm the answer shows in the feedback app's `/admin`
under `kubecon-na-2026` with source `burritobot` (ask feedback-agenticburn to
read it if you cannot sign in there).

| Phone | Thanks page appears | Its Sessionize link opens session 1249553 | Shows in /admin with source burritobot | Checked by, date |
|---|---|---|---|---|
| iPhone, Safari | | | | |
| Android, Chrome | | | | |

Sessionize rating is mobile-only and opens near the session. On 2026-10-24 the
Sessionize page said "There are no sessions to rate at the moment."

- [ ] Once rating opens, the thanks page's Sessionize link on a phone shows
  **this** talk (session 1249553) and offers to rate it. If it shows another
  session or nothing, the link lives in the feedback app, not here: ask
  feedback-agenticburn to correct it, then run this table again.
