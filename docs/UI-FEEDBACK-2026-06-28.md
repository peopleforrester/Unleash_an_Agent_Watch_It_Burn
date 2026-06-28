# UI Feedback and Plan, 2026-06-28 (Michael + Whitney walkthrough)

Point-by-point capture of the walkthrough Michael and Whitney ran, in order:
BurritoBot storefront first, then the VTT terminal. This amends the spec
(`BUILD-SPEC.md`, `MASTER-RECREATION-SPEC.md`), the design
(`attendee-access-design.md`, `DESIGN-DECISIONS.md`), and the run-of-show
(`RUN-OF-SHOW-AND-BACKLOG-2026-06-27.md`). Each item has an ID used by the
task list. Most of this is cosmetic, with three larger structural items
(BurritoBot left/right split, VTT instruction reveals + multi-terminal, VTT
environment + pre-configured AWS).

Status: captured; plan approved 2026-06-28. We tackle one piece at a time.

### Decisions (2026-06-28)
- **Name:** one word, `BurritoBot`, everywhere. Not "Burrito Bot".
- **Round/cluster selector prefix:** the purple-bar label is **"Choose"**.
- **Datadog viewing:** **inline per challenge** for now. Michael and Whitney
  will judge ingest lag on a later walkthrough and move it to the end only if
  needed. Not a concern to design around now.

---

## A. BurritoBot storefront

### Branding and naming
- **BB-1.** Rename "BurritBot"/"BURRITBOT" to **BurritoBot** everywhere (the
  missing `o`). No location should read "Burritbot". Canonical token:
  `BurritoBot`. Open question for display: "Burrito Bot" (two words) vs
  "BurritoBot" (one word); Michael said both, defaulting to one word unless he
  says otherwise.
- **BB-2.** Replace the broom icon in the upper-left with a **burrito in a
  cauldron** image. No frog imagery.
- **BB-3.** Remove the broom emoji/icon **everywhere** it appears.
- **BB-29.** Remove **all** mini emoji/pictures from menu items (proteins,
  bases, fillings, salsas, toppings). All or none, so none.

### Left menu (static)
- **BB-4.** The left menu is a **static menu**, not clickable. It only shows
  what can be ordered. No click behavior this iteration.
- **BB-5 / BB-7.** Remove the "That's my order, ring me up" button from the
  menu entirely (it returns as a chat Easter egg, see BB-9). Subtitle under
  "Hex & Cauldron" should read: **"Build your burrito. The BurritoBot will
  take your order."** Not "Tap to order."
- **BB-8.** Keep the name "Hex & Cauldron". Fix the copy that says "around"
  twice.

### "No Burritos for you" screen
- **BB-6.** The only condition that shows "No Burritos for you" is **loss of
  connection to the backend cluster** (e.g., a fork bomb killed it). Never on a
  menu click, never on send. Pressing **Escape** on that screen returns to the
  chat window.

### Right band: infrastructure / info (the split)
- **BB-19 (structural).** Sequester all infrastructure/info to its **own
  right-hand band**, cleanly divided from the storefront by a vertical line.
  Left = the burrito-ordering product (Hex & Cauldron static menu + BurritoBot
  chat), the end-user illusion. Right = round/cluster selector, the
  round/cluster banner (condensed), tokens, cost, saved prompts. Keep the
  BurritoBot title banner at the very top. The point: BurritoBot reads as its
  own product; the backend-learner concerns do not bleed into it.

### Round/cluster selector and banner
- **BB-16.** "Round" currently appears twice: as the dropdown prefix label and
  inside each item ("Round 1/2/3"). Drop the prefix, or relabel the purple bar
  prefix to **"Choose"** or **"Cluster"**.
- **BB-17.** Banner colors: **Round 1 = red** (no guardrails, straight to the
  model), **Round 2 = blue** (some guardrails, +AI), **Round 3 = green** (your
  cluster). Currently R3 is purple-on-purple; make the three distinct so red,
  blue, and green each stand out on the "your cluster" titles.
- **BB-18.** Copy cleanup on the banner ("around" duplicate, "some
  guardrails").

### Tokens and cost
- **BB-12 / BB-15.** Label reads **"tokens"**, never "tok" or "0 tok". Do not
  shorthand anything in the UI unless explicitly told (reset, saved prompts,
  etc. are all spelled out; tokens should be too).
- **BB-13.** Ensure the token counter increments on real LLM calls (it does
  when a call lands; verify it is reliable and not masked by the No-Burritos
  game screen).
- **BB-14.** Add a **cost** display (dollars) next to tokens. Token and cost.

### Saved prompts and capture
- **BB-9-save.** Every prompt sent is **automatically saved** to the
  right-hand saved-prompts panel. Verify and fix (it is not reliably saving
  now).
- **BB-12-obs.** Prompts are captured to the backend per Whitney's Datadog
  standards (OTEL GenAI semantic conventions), flowing through kagent. Do not
  necessarily wire a separate BurritoBot Datadog application if the backend
  already captures it; confirm capture and conformance. (Spike SP-3.)

### Order-completion Easter egg
- **BB-9.** If a user completes the full five-step order, BurritoBot surfaces a
  **"That's my order, ring me up"** button **in chat**. Pressing it triggers a
  silly animation. Stretch: an "enter your email for a cheat sheet" gag that
  throws up a deliberately over-the-top AI-generated cornucopia of Hex &
  Cauldron (pixies, ogres, every menu item). Image is deferred; the
  button-in-chat plus animation is the ask. (Asset spike SP-6.)

### BurritoBot behavior and system prompt
- **BB-21.** When a user tries to push BurritoBot into malicious
  infrastructure actions, BurritoBot **responds to the request and always
  nudges the next order step** ("ready to pick your filling now?").
- **BB-22.** BurritoBot's menu responses must match the **actual left menu**
  dynamically. Today it returns generic items (chicken/beef/shrimp) that are
  not on our menu. The system prompt must carry the real menu as a single
  source of truth shared with the left display; change the menu, the prompt
  changes.
- **BB-23.** The system prompt is **identical across rounds 1, 2, 3**. Not
  challenge-aware. The rounds differ by guardrails/infra, not by prompt.
  First step: read the current system prompt across all clusters.

### Cluster identity on BurritoBot
- **BB-24.** Show which cluster the user is on. For attendees, lower-left
  (storefront side) and lower-right (infra side): "You're on student cluster
  `<name>`, assigned to `<email>`." Instructors see round 1/2/3; students need
  their assigned cluster name keyed off their email.

### Menu revision (saved for last; directional notes)
- **BB-10.** Finalize the witchy menu, single source of truth shared with the
  system prompt. Directional notes from the walkthrough:
  - **Proteins:** keep Bogbacoa (barbacoa); drop "Wraith Wisp" (no real food);
    "Sootfritas" reads as "Soot-Fritas" (sofritas), add the dash, and it is the
    tofu option, so call out tofu; reconsider "Sorcerizo" (chorizo, a stretch);
    keep Croak-nitas (carnitas) for now; **move "Fajita veggies" up into
    proteins** (it is a protein/veggie, not a topping).
  - **Base:** base is rice or salad (Chipotle model); beans are fillings, not
    base. Want **two rices** (cilantro-lime rice, liked, plus a second rice)
    and **a salad** with a new name (no "bog", already used in Bogbacoa).
    Tortilla chips are **not a base**; move chips to the end as a side.
  - **Fillings:** black beans (keep) and pinto beans (rename "Imp-into Beans"
    to something cleaner; "pinto beans" reads well). Queso is an add-on, can
    keep.
  - **Salsas/toppings:** "Ogresnut Guac" should be **"Ogre Snot Guac"**.
    Pixie-o de Gallo works (green/mild). Cursed-Corn keeps. Rework the red
    salsa naming (a green "de gallo" and a clear red one; "Lizard Lickins'" is
    unclear; consider "Goblin de Gallo" / a dragon-themed queso). Drop "Pixie
    Dust" (pixie already used). Keep "Hag Wrinkle Relish" and "Tardigrade
    Crunch".

---

## B. VTT (in-browser terminal lab page)

### Cluster identity and breadcrumbs
- **VT-3.** The VTT does not show which cluster it is on. Add breadcrumbs
  (top and/or bottom) stating explicitly: instructor vs student, and the
  cluster name. Make it clear even when an instructor is emulating a student.
- **VT-3b.** The instructor per-cluster VTT links (r1, r2, r3, attendee, the
  vertically stacked ones) currently all open the **same** cluster and all
  label "round three". Each must open its **own** distinct cluster with the
  correct label. (Today they point at the single live wt1 because that is the
  only cluster up; the design intent is distinct per cluster.)
- **VT-3c (troubleshooting).** Surface the student's assigned cluster name
  prominently so the room can be troubleshot live (50 attendees). Apply uniform
  naming conventions and version/identity signals as standard practice.

### VTT environment
- **VT-1.** Install the full toolset into the VTT and have it auto-configured:
  **AWS CLI v2**, kubectl (present), helm, eksctl, k9s, jq (present), yq, curl
  (present), git, and the common cluster/AWS management tools. AWS CLI is
  currently missing. (This needs a glibc base image; the current Alpine image
  cannot run AWS CLI v2.)
- **VT-1b.** Run the shell as a scoped **`student`** user in **`/home/student`**,
  not on the root directory `/`. The user space stays scoped even if it holds
  admin rights on the cluster.
- **VT-2.** Pre-configure the student's **AWS CLI with their access and secret
  keys** in the VTT so `aws` works immediately, as the default credentials, no
  manual `aws configure`. (Spike SP-4: per-student creds via Pod Identity vs
  mounted secret.)

### VTT instructions (left pane)
- **VT-4.** Replace the single long scroll with **collapsible carets per
  step**: closed by default until first click, then they persist whatever state
  the student sets. Whitney accepts a long left page as long as every step is a
  hideable caret. A "Next"-paginated variant is the alternative; carets are the
  baseline.
- **VT-10.** Include the **explicit guardrail on/off instructions** using the
  scripts we built (the same `guards-on`/`guards-off` commands instructors
  use). These are missing from the left pane today.
- **VT-5 (structural).** Add the ability to open an **additional terminal** via
  a "+" terminal tab on the right, the common Katacoda/KodeKloud multi-terminal
  pattern. (Spike SP-1: ttyd multi-terminal.)

### VTT home-base buttons and the three-views framing
- **VT-6.** Top-of-page "home base" buttons: **Back to provisioning page**
  (to retrieve credentials), **Open Datadog**, **Open BurritoBot**. No "back to
  VTT" (you are in it).
- **VT-7.** Reframe the content. Drop "Order a burrito from your BurritoBot" as
  a step; ordering a burrito is not the objective. Open with a lab-environment
  tour and the **three-views** framing: the student lives in three tabs,
  **Terminal, BurritoBot, Datadog**, with the terminal as home base. Step 1:
  you are here in the terminal, you have opened BurritoBot and Datadog, take a
  look around, then go to the challenges.

### VTT Datadog step
- **VT-9.** Add an **Open Datadog** step with the student's Datadog credentials
  shown on the VTT page (so they do not bounce back to provisioning), plus deep
  links to the exact dashboard per challenge. Investigate whether Datadog login
  can be pre-submitted via URL (likely not; Datadog labs do not). Default site
  tag us1 / us-east. (Spike SP-2.)

### VTT challenge flow (rounds 3 / 5 / 6 / 7)
- **VT-8.** Build the challenge flow as **one step per challenge with substeps
  (5a, 5b, 5c)** under collapsible carets:
  - **Challenge 5, output sanitization:** show the BurritoBot weakness with a
    copyable malicious prompt, see it pass through (output + Datadog capture),
    turn on the challenge-5 guardrail via a command, re-run the same prompt,
    see it blocked, look in Datadog. Then reveal the hidden cost: output
    sanitization still leaves PII in the traces (dirty logs), which sets up
    challenge 6.
  - **Challenge 6, input classifier:** the PII-in-logs problem. An input
    classifier catches it upstream before the LLM, keeping logs clean and
    cutting cost. Show weakness, turn on, see it blocked upstream, costs down,
    logs clean.
  - **Challenge 7, evil MCP server:** show weakness, turn on, show block.
  - Framing (not a product pitch): "this is instrumented with OpenTelemetry;
    Datadog is our backend, but any OTEL/OTLP-conformant backend works." Use
    "OTEL semantic conventions" and "OTLP-conformable"; do not overclaim.
  - Sequencing question to test live: whether to view Datadog inline per
    challenge or batch all Datadog viewing at the end to give telemetry time to
    ingest.

### Keep as-is (praised)
- Copy interfaces, terminal color coding, overall VTT look. Do not regress
  these.

---

## C. Provisioning page

- **PV-1.** The admin/instructor view is "double" and not fully working; clean
  it up. (Michael's email renders the instructor/admin view.)
- **PV-2.** The per-cluster instructor links exist and open BurritoBot/terminal
  correctly, but all currently point at the same cluster; make them distinct
  per cluster (ties to VT-3b).
- **PV-3.** Datadog credentials should be reachable from the VTT page (VT-9),
  reducing back-and-forth to provisioning.

---

## D. Cross-cutting

- **X-system-prompt:** one identical, non-challenge-aware system prompt across
  all rounds, carrying the real menu, nudging the order flow even on infra
  requests (BB-21/22/23). Read the current prompt first.
- **X-observability:** prompt/telemetry capture conforms to Whitney's OTEL
  GenAI semantic conventions through kagent (BB-12-obs).
- **X-breadcrumbs:** cluster name and assignment visible on BurritoBot and VTT;
  uniform naming; version/identity signals for live troubleshooting
  (BB-24, VT-3, VT-3c).

---

## E. Research spikes

- **SP-1. DECIDED (2026-06-28): multiple iframes, no ttyd change.** ttyd spawns a
  fresh bash per client connection (the entrypoint runs `ttyd ... bash` with no
  `--once` and no client cap), so each `<iframe src="/terminal/">` is its own
  independent terminal. The "+" tab adds an iframe; tabs show/hide panes. No tmux,
  no second ttyd, no xterm.js rebuild needed.
- **SP-2.** Datadog: deep-linking to a specific dashboard, login pre-fill /
  pre-submit feasibility, and how Datadog's own labs surface credentials.
- **SP-3.** Whitney's Datadog GenAI semantic-convention standards for prompt
  capture (overlaps tasks #13/#14/#27/#20).
- **SP-4. DECIDED (2026-06-28): mounted secret, not Pod Identity.** The student's
  own access/secret keys (the ones on their provisioning page) land in the VTT pod
  as an optional Secret `student-aws-creds`; the entrypoint writes them as the
  **default** AWS profile (`~/.aws/credentials` + region), so `aws` works with no
  flags. Pod Identity was rejected because it grants a role, not the student's
  keys, so the VTT would not match the provisioning page. The per-cluster Secret
  is created by the cluster bootstrap (the same imperative step that mints the
  IAM user), outside git, since gitops manifests are shared across all clusters.
- **SP-5.** Katacoda/KodeKloud reveal + multi-terminal interaction patterns
  (extends the prior DNS/entry-point spike work).
- **SP-6.** AI-generated Hex & Cauldron cornucopia Easter-egg image asset.

---

## F. Proposed sequencing (one piece at a time)

Cosmetic-first, structural-second, content-last, so each lands and is testable.

1. **BurritoBot quick wins:** BB-1 spelling, BB-3 broom removal, BB-29 emoji
   removal, BB-15 "tokens", BB-16 round-label dedupe, BB-17 banner colors,
   BB-7 subtitle, BB-6/BB-5 remove ring-me-up + No-Burritos-on-click, BB-8/18
   copy. Pure cosmetic, no backend.
2. **BurritoBot split (BB-19):** left storefront vs right infra band. Structural
   CSS/layout.
3. **BurritoBot counters (BB-13/14):** reliable token increment + cost.
4. **VTT environment (VT-1/1b/2):** glibc image, full toolset, student home,
   pre-configured AWS. (Needs SP-4.)
5. **VTT breadcrumbs (VT-3/3b/3c) + home-base buttons (VT-6).**
6. **VTT instruction reveals (VT-4/VT-10) and multi-terminal (VT-5).**
   (Needs SP-1.)
7. **VTT challenge flow content (VT-7/VT-8/VT-9).** (Needs SP-2.)
8. **System prompt + menu single-source (BB-10/22/23) and behavior (BB-21).**
9. **Observability conformance (BB-12-obs).** (Needs SP-3.)
10. **Cluster identity on BurritoBot (BB-24), Easter egg (BB-9), provisioning
    cleanup (PV-1).**
11. **Image asset + polish (BB-2, SP-6).**
