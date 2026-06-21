# AIEWF 2026 Workshop Logistics Research Spike

Workshop: "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
Presenters: Michael Forrester and Whitney Lee
Slot: Day 1, Track 5, 2:20 to 4:20pm (2 hours), hands-on
Venue: Moscone West, San Francisco
Demo footprint that depends on the network: AWS Bedrock, 60 EKS clusters, Datadog, all over the wire.

## Verification Method

Web research only, conducted 2026-06-21. No contact with organizers and no
walkthrough of the room. Sources are the official AI Engineer World's Fair
2026 site and schedule, the Sessionize call for speakers, the AIEWF FAQ, the
Moscone Center venue pages (internet/telecom and WiFi), the A/V production
vendor for the 2024 fair (Talon Audio Visual), and third-party recaps of the
2024 and 2025 editions. Source URLs are listed inline and in the Sources
section at the end.

Confidence labels:
- CONFIRMED = stated on an official AIEWF page or the venue's own page.
- UNCERTAIN = inferred, from a prior-year or third-party source, or not
  publicly documented. Every UNCERTAIN item has a specific question to ask
  the organizers.

The single most important caveat: AIEWF does not publish a speaker A/V or
network spec sheet publicly. Most of the load-bearing operational detail in
sections 1, 2, 4, and 5 is UNCERTAIN and must be confirmed with the
organizers (info@ai.engineer) and, for the network, very likely escalated to
the AIEWF production and network team directly.

---

## 1. Network for presenters and hands-on workshops (LOAD-BEARING)

This is the highest-risk area for this specific demo and the area with the
weakest public documentation.

### What is CONFIRMED about the venue's baseline network

- Moscone's free attendee WiFi is rate-limited to 1 Mbps up and down, is
  described as "unsupported," and is only guaranteed "throughout the street
  level lobbies of Moscone South, Moscone North, and Moscone West." The venue
  itself says that for "a more robust or event specific wireless network in
  these public spaces or inside session rooms or exhibit halls" you must
  contact them for a quote. (CONFIRMED, moscone.com/wifi)
- Read that literally: the free WiFi is a lobby service, not an in-room
  service, and 1 Mbps symmetric is far below what a 30-to-100-person hands-on
  workshop hitting Bedrock, 60 EKS clusters, and Datadog would need.
- The venue backbone is strong (three 10-Gigabit Ethernet circuits with
  redundant entrances from separate tier-1 providers, redundant core
  switches and routers, enterprise gigabit PoE switches, 24/7 NOC). Peak
  events have seen 18,000+ simultaneous device connections consuming multiple
  gigabits per second. So the capacity exists; the question is what slice of
  it your specific room gets. (CONFIRMED, moscone.com/internet-telecom)
- Dedicated and hardwired internet is an orderable service from Moscone
  Facility Services (the exclusive provider): internet@moscone.com,
  (415) 974-4126. They publish a "Telecom-Internet Order Form 2026." Custom
  in-room wired drops and event-specific wireless are quoted per request.
  No public rate card. (CONFIRMED, moscone.com/internet-telecom)

### What is CONFIRMED about AIEWF's posture

- AIEWF explicitly tells workshop attendees to "BYOD, and be prepared to
  clone a repo and dive in," which means the format assumes every attendee is
  on the network at once doing real work. (CONFIRMED, ai.engineer/faq)
- The 2024 production writeup notes the event included "live demos requiring
  rock-solid network connections" and that the A/V vendor treated network as
  a first-class production concern, which implies AIEWF provisions event
  network beyond the free venue WiFi. It does not state the per-room spec.
  (UNCERTAIN on specifics, talonaudiovisual.com 2024 spotlight)

### What is UNCERTAIN (ask the organizers)

1. Is there a dedicated, event-provisioned WiFi SSID inside the workshop
   rooms (separate from the free 1 Mbps lobby WiFi), and what is its
   committed per-attendee and per-room bandwidth? Ask: "What is the
   guaranteed down/up bandwidth in the Track 5 workshop room, and is it a
   shared pool or rate-limited per device?"
2. Can presenters get a hardwired Ethernet drop at the presenter station in
   the Track 5 room, and if so what is the committed bandwidth and is there a
   public or static IP available? Ask: "Can you provide a wired uplink at the
   presenter podium for our demo machine, committed bandwidth, and can it
   reach AWS and Datadog without a captive portal?"
3. Is there a captive portal, MAC registration, or per-device session cap on
   the workshop WiFi that would interrupt a 2-hour lab? Ask: "Does the
   workshop WiFi use a captive portal or time out sessions, and are outbound
   ports (443 to AWS/Bedrock/EKS API endpoints, Datadog intake) open?"
4. Are outbound firewall rules permissive enough for the kubectl/EKS API,
   AWS SDK, Bedrock streaming, and Datadog agent traffic? Convention WiFi
   sometimes blocks non-80/443 ports and long-lived connections. Ask: "Are
   there egress restrictions on the workshop network beyond 80/443?"
5. If we need to guarantee the demo, can we order a dedicated drop directly
   from Moscone Facility Services for our room and slot, who pays, and what
   is the lead time? Ask the organizers first (they may already have a block
   order); only contact Moscone directly with organizer sign-off.

### Mitigation guidance regardless of answers

- Treat the network as hostile until proven otherwise. The free venue WiFi
  alone (1 Mbps) will not carry this demo.
- Pre-stage the 60 EKS clusters and as much Bedrock/Datadog state as possible
  before the slot so the live network load is reads and small writes, not
  bulk provisioning.
- Bring a backup uplink the presenter controls: a high-throughput cellular
  hotspot (Moscone has a Distributed Antenna System with AT&T, Verizon,
  T-Mobile in-building, so cellular generally works), or two bonded hotspots.
  This is independent of whatever the organizers provision. (Venue DAS
  CONFIRMED, moscone.com)
- Have a pre-recorded video fallback of the full demo (see section 5).

---

## 2. A/V

### CONFIRMED

- Sessions are professionally recorded and the production is large-scale:
  the 2024 fair ran across "11 different rooms" with "a dozen breakout
  producers and over 40 union technicians and stagehands," general sessions
  that split and recombined, livestreaming, and "complex AV routing, and
  custom audio filters." So expect a real A/V crew per breakout room, not a
  self-serve projector. (CONFIRMED scale, talonaudiovisual.com 2024)

### UNCERTAIN (ask the organizers)

AIEWF publishes no public A/V spec sheet. Confirm each of these:

1. Display type and resolution: projector vs LED wall, native resolution,
   and aspect ratio (16:9 vs 16:10 vs ultrawide). Ask: "What is the display
   resolution and aspect ratio in the Track 5 workshop room so we can size
   slides and terminal font for legibility?"
2. Laptop connection and adapters: HDMI, USB-C, DisplayPort. Industry
   standard for a 2026 event is to have a full adapter kit at the lectern,
   but confirm. Ask: "Do you provide HDMI and USB-C connections at the
   presenter station, or should we bring our own dongles?" Bring our own
   USB-C-to-HDMI and USB-C-to-DisplayPort adapters regardless.
3. Confidence monitor: is there a downstage confidence monitor showing our
   slides/terminal, and does it mirror or extend? Ask: "Is there a
   confidence monitor in the workshop room, and does it mirror the main
   display?"
4. Own laptop vs house machine: workshops are almost certainly presenter's
   own laptop (the BYOD culture and "clone a repo" framing imply it), but
   confirm. Ask: "Do we present from our own laptops?"
5. Audio/mic: count and type of mics for two presenters (two lavaliers or
   handhelds), and whether there is program audio out from the laptop for
   any demo sound. Ask: "Can you provide two wireless lav mics for two
   presenters in the workshop room?"
6. Two-presenter switching: with Michael and Whitney both presenting, ask
   whether the A/V supports two laptop inputs with a switcher, or whether we
   should present from one machine. Ask: "Can the room take two laptop
   inputs, or should we drive from a single machine?"

---

## 3. Workshop and session format

### CONFIRMED

- Workshops are 1 to 2 hours, defined as "Hands-on sessions or technical
  deep dives." Our 2:20 to 4:20pm slot is a 2-hour workshop. (CONFIRMED,
  ai.engineer/worldsfair/2026 and sessionize.com/aiewf2026)
- Format expectation: attendees "BYOD, and be prepared to clone a repo and
  dive in." Hands-on labs are run by having every attendee work on their own
  device against a shared repo. (CONFIRMED, ai.engineer/faq)
- Day 1 (June 29) is the heavy workshop day: the 2026 site describes "45+
  hands-on workshops across all rooms" and the llms.md lists Day 1 workshop
  blocks of roughly 9:00AM to 1:00PM and 2:30PM to 5:30PM, plus
  Lunch-and-Learn workshops 1:15 to 2:15PM. Our 2:20 to 4:20pm sits in the
  afternoon workshop block. (CONFIRMED that Day 1 is workshop day; the exact
  published block boundaries shift between the marketing page and llms.md, so
  treat the 2:20 to 4:20 slot from your acceptance as authoritative over the
  generic site copy.) (ai.engineer/worldsfair/2026/llms.md)
- Workshop access is gated to specific ticket types ("Workshops + Engineering
  or AI Leadership / All Access"), which caps and self-selects your audience
  to people who paid for hands-on. (CONFIRMED, ai.engineer/faq)
- Speakers are told to "dive right into the content with minimal
  self-introduction as the MC will introduce you." (CONFIRMED,
  sessionize.com/aiewf2026)

### UNCERTAIN (ask the organizers)

1. Room capacity and seating for the Track 5 workshop room: rounds (better
   for hands-on, lets people help each other) vs theater vs classroom. The
   2024 fair had 1,500 in-person attendees across 11 rooms; per-room workshop
   capacity is not published. Ask: "What is the seating capacity and seating
   style (rounds, classroom, theater) for the Track 5 workshop room, and is
   there table space for laptops?"
2. Expected or capped attendee count for our specific workshop. Ask: "Is
   there a registration cap on our workshop, and what attendance should we
   plan for?"
3. Power at seats: a 2-hour BYOD lab needs power. Ask: "Is there power at or
   near attendee seats, or should attendees come charged with their own
   power strips?" Build the lab to survive on battery if power is not at
   seats.
4. Helpers/TAs: are room volunteers available to help attendees who fall
   behind in a hands-on lab? Ask: "Are room hosts or TAs available to help
   attendees during the workshop?"
5. Pre-event setup instructions to attendees: is there a channel
   (pre-event email, Discord, the session page) to push prerequisites so
   attendees arrive with tooling installed and repos cloned, reducing live
   network and setup load? Ask: "How can we send prerequisites to registered
   attendees before the session?"

Note on "Track 5": third-party indexers label tracks by theme (one source
called Track 5 "Security"). Track numbering and themes shift year to year and
between marketing copy and the live grid. Treat your acceptance email's
"Day 1, Track 5, 2:20 to 4:20pm" as authoritative and confirm the physical
room name with the organizers. (UNCERTAIN, conflicting third-party labels)

---

## 4. Timing and logistics

### CONFIRMED

- Slot length: 2 hours (2:20 to 4:20pm), consistent with the 1-to-2-hour
  workshop format. (CONFIRMED format, ai.engineer/worldsfair/2026)
- Day 1 is a dense back-to-back workshop day with morning and afternoon
  blocks and Lunch-and-Learns between, which means turnover between sessions
  in the same room is tight. (CONFIRMED that Day 1 is fully booked with
  workshops, ai.engineer/worldsfair/2026/llms.md)

### UNCERTAIN (ask the organizers)

1. Setup time before the slot: with a 1:15 to 2:15 Lunch-and-Learn possibly
   in the same room before our 2:20 start, changeover could be only minutes.
   Ask: "How much setup time do we have in the room before our 2:20 start,
   and is the room used immediately before us?"
2. Hard stop at 4:20: is there a session immediately after that forces a
   hard stop, or buffer? Plan for a hard 4:20 stop. Ask: "Is 4:20 a hard
   stop with a session behind us?"
3. Tech check / rehearsal: is there a scheduled A/V and network check in the
   actual room before the day, or only a minutes-long line check at
   changeover? This matters enormously for a network-dependent demo. Ask:
   "Can we get into the Track 5 room ahead of time for an A/V and network
   dry run, and when?" Industry norm is a 30-minute technical run-through;
   AIEWF's availability is unconfirmed.
4. Arrival/check-in for speakers: where and when to check in, green room
   location, and who our day-of A/V producer contact is. Ask: "Where do
   speakers check in on Day 1 and who is our room's A/V producer?"

---

## 5. Recording and streaming

### CONFIRMED

- Every session is professionally recorded and published: "Your talk will be
  professionally recorded and published on our YT page, X, and LinkedIn for
  free consumption, along with optional interviews." (CONFIRMED,
  sessionize.com/aiewf2026 and ai.engineer/worldsfair/2026)
- The fair livestreams ("thousands more online" in 2024). Whether every
  breakout/workshop room is livestreamed vs only recorded is not stated.
  (CONFIRMED that streaming exists; per-room workshop streaming UNCERTAIN,
  talonaudiovisual.com 2024)

### UNCERTAIN (ask the organizers)

1. Is our workshop room recorded, livestreamed, or both? Workshops are
   sometimes recorded but not livestreamed. Ask: "Will the Track 5 workshop
   be recorded, livestreamed, or both?"
2. What exactly is captured: room camera plus a clean screen-capture feed of
   our laptop, or just a camera? A clean HDMI/screen feed matters if we want
   a usable recording of the terminal-heavy demo. Ask: "Does the workshop
   recording include a clean screen-capture feed of our laptop output?"
3. Can we get the raw recording, and is there an embargo/release timeline?
   Ask: "Will we receive our session recording, and when does it publish?"

### Implication for the pre-recorded fallback

Because recording and publication are guaranteed, a bad live demo is
permanent and public. Combined with the network risk in section 1, this
strongly argues for a pre-recorded demo segment we can cut to instantly if
the live network fails. Keep the pre-record ready on local disk (not
streamed), so it works with zero network.

---

## 6. AIEWF-specific gotchas that have bitten presenters before

Drawn from prior-edition recaps and the venue/production realities. Some are
UNCERTAIN by nature (operational, not documented), flagged as such.

1. The free venue WiFi is a trap for demos. It is a 1 Mbps lobby service,
   not an in-room workshop network. Anyone who plans a network-heavy live
   demo on "the conference WiFi" without confirming the dedicated in-room
   provisioning is gambling. This is the number-one risk for this specific
   talk. (CONFIRMED venue limit; mitigation is yours to own.)
2. BYOD setup tax eats lab time. With every attendee cloning a repo and
   installing tooling live, the first 20 to 30 minutes of a hands-on lab
   commonly evaporates into "it doesn't work on my machine" and simultaneous
   network load. Push prerequisites before the event and design the lab so
   late/stuck attendees can still follow. (UNCERTAIN per-room, but a
   well-known hands-on-workshop failure mode.)
3. Tight room changeover on the dense Day 1. Day 1 is wall-to-wall
   workshops; assume minimal setup buffer and a hard stop. Rehearse a cold
   start that gets you presenting within a few minutes. (CONFIRMED Day 1 is
   packed; exact buffer UNCERTAIN.)
4. Egress firewall surprises. Convention networks sometimes block non-443
   ports and throttle long-lived connections, which can break kubectl/EKS
   API streaming, agent loops, and Datadog agent traffic specifically.
   Confirm egress rules and have the cellular backup. (UNCERTAIN, ask
   organizers.)
5. Two-presenter A/V switching. Coordinating two laptops (Michael and
   Whitney) on one room feed can cause dead air at handoffs. Decide in
   advance: single driving machine, or confirm a switcher exists. (UNCERTAIN,
   ask organizers.)
6. "It is recorded forever." Failures are published to YouTube/X/LinkedIn.
   The pre-recorded fallback protects both the live audience and the
   permanent record. (CONFIRMED recording policy.)
7. Slide/terminal legibility in a large breakout room. Confirm resolution
   and aspect ratio early and use large terminal fonts; rooms are sized for
   1,500-across-11-rooms scale, so back-row legibility is real. (Display
   spec UNCERTAIN; room scale CONFIRMED.)

---

## Consolidated list of questions for the organizers (info@ai.engineer)

Network (priority):
- Is there a dedicated in-room WiFi separate from the free 1 Mbps lobby WiFi,
  and what is its committed bandwidth in our Track 5 room?
- Can we get a hardwired Ethernet drop at the presenter station, committed
  bandwidth, and unrestricted egress to AWS/Bedrock/EKS/Datadog?
- Is there a captive portal, session timeout, or egress port filtering on the
  workshop network?
- If we need a guaranteed dedicated drop from Moscone Facility Services, do
  you handle that, who pays, and what is the lead time?

A/V:
- Display resolution and aspect ratio in the Track 5 room?
- HDMI and USB-C at the presenter station, or BYO adapters?
- Confidence monitor present (mirror or extend)?
- Two wireless lav mics for two presenters?
- Two laptop inputs/switcher, or single driving machine?
- Do we present from our own laptops? (assume yes)

Format and room:
- Seating capacity and style (rounds vs classroom vs theater) and table space?
- Registration cap / expected attendance for our workshop?
- Power at attendee seats?
- Room hosts/TAs to help attendees?
- Channel to send prerequisites to registered attendees beforehand?

Timing:
- Setup buffer before our 2:20 start; is the room used right before us?
- Hard stop at 4:20?
- Can we get into the room ahead of time for an A/V and network dry run?
- Speaker check-in location/time and our room's A/V producer contact?

Recording:
- Recorded, livestreamed, or both?
- Clean screen-capture feed of our laptop included?
- Do we receive the recording, and when does it publish?

---

## Sources

- AI Engineer World's Fair 2026 (official): https://www.ai.engineer/worldsfair/2026
- AIEWF 2026 machine-readable details (llms.md): https://www.ai.engineer/worldsfair/2026/llms.md
- AIEWF 2026 Call for Speakers (Sessionize): https://sessionize.com/aiewf2026/
- AIEWF FAQ: https://www.ai.engineer/faq
- AIEWF 2026 schedule: https://www.ai.engineer/worldsfair/schedule
- Moscone Center Internet & Telecom: https://www.moscone.com/internet-telecom
- Moscone Center WiFi: https://moscone.com/wifi
- Moscone Center venue: https://www.moscone.com/events/ai-engineer-worlds-fair-2026
- Talon Audio Visual, AIEWF 2024 production spotlight: https://talonaudiovisual.com/blog/2024/11/30/project-spotlight-2024-ai-engineer-worlds-fair
- AIEWF 2025 comprehensive summary (third-party recap): https://www.bestaievents.com/blog/ai-engineer-worlds-fair-2025-a-comprehensive-summary
- AIEWF 2025 schedule (prior edition): https://wf2025.ai.engineer/schedule
