# Run-of-Show Reaffirmation, Michael + Whitney, 2026-06-29

Captured from a Michael + Whitney working conversation (voice transcript at the end of this file,
verbatim, as history). This reconciles that conversation against the built repo and confirms which
run-of-show elements are covered and which are gaps. It supplements (does not replace)
`facilitation/runbook.md` and `docs/RUN-OF-SHOW-AND-BACKLOG-2026-06-27.md`.

## The flow they described

### Round 1, open cluster, attack the BurritoBot, watch the room burn
- A secret ingredient is the hook: a "fat spit secret recipe" planted on the cluster. Two attack goals:
  pull the secret recipe, and exfiltrate customer data (e.g. social-engineer a customer's delivery
  address) out to an S3 bucket.
- Other attacks: deploy a malicious image (the "Joker" / "grill zone" image), and run executable code
  in the cluster (exec, `ls`, live process activity).
- LIVE observability is the payoff: a shared view (Datadog, plus maybe an S3 / AWS view) where the room
  sees attacks land in real time, a malicious image deployed, customer data populating an S3 bucket,
  process/`ls` calls across clusters. Even an attendee who hasn't broken through sees others succeed.
- Gamified: "you can only order a burrito once you accomplish your objective." Facilitators give hints
  and show one known-working exploit prompt so nobody is stuck.

### Round 2, turn the CNCF guardrails on LIVE, one at a time, re-run the same attack
The thread is: take an attack that WORKED in R1, switch on one platform control, re-run the exact same
attack, watch it stop. In order:
1. NetworkPolicy: turn on egress restriction, re-run the R1 exfiltration prompt, data can no longer
   leave the cluster. (Cilium CNI / eBPF discussed; L3 vs L7.)
2. Image-source restriction: restrict pulls to a trusted registry (Harbor/GCR), re-run the malicious
   image, BurritoBot agrees but the image can't be pulled/run.
3. Falco (+ Kyverno): enable runtime detection/enforcement, re-run exec/`ls`, it's detected and blocked.
- Framing: the CNCF wall contains blast radius but the prompt still gets through some of the time, and
  the cost was already incurred. That motivates Round 3's AI guardrails.

### Round 3, your own cluster, three in-browser tabs, self-paced challenges 5/6/7
- Provisioning hands each attendee an in-browser BurritoBot, in-browser VTT terminal, and in-browser
  debug, three tabs, all in-browser. Local kubectl stays tiny optional print with an "experienced users
  only" warning; recommend just using the terminal (no time to set up local).
- Self-paced: a quick mental model, then left-pane step-by-step (5a/b/c...) in the VTT.
- Challenge 5, output sanitization: show the secret recipe leaking, turn the output guard on, re-run,
  it's blocked. Challenge 6, input classifier (PII-in-logs + cost). Challenge 7, evil MCP server.

## Coverage map (element to build state)

| Round | Element | Built? | Where / task |
|---|---|---|---|
| R1 | Open BurritoBot, attackable | YES | ai-layer (workshop-agent + console) |
| R1 | "Fat spit" secret recipe planted + grep attack | YES | `challenges/02-sanitization/plant-fake-recipe.yaml`, `challenges/c3-secret-grep` |
| R1 | Exfiltrate customer data to S3 | YES (scenario) | `challenges/c1-exfil-s3` |
| R1 | Fork bomb / the burn | YES | `challenges/c4-fork-bomb`; R1 clusters provision with `pod_pids_limit=-1` |
| R1 | Malicious image (Joker / grill zone) attack | GAP | no dedicated deploy-malicious-image scenario yet |
| R1 | Live "attack the room" view: S3 fills, process/`ls` feed, attack dashboard | GAP | Datadog Service Map exists; no S3 view, no Falco live-event feed, custom dashboards not fanned out (#25) |
| R1 | Gamified objective-gating ("order only if you succeed") + hints | GAP | order flow + easter egg exist; not gated on attack success |
| R2 | Turn guardrails on LIVE and re-run the SAME R1 attack | PARTIAL/MISMATCH | built beat-01 is resource-limits admission + RBAC + GitOps drift, not the exfil/image/exec thread |
| R2 | NetworkPolicy egress toggle vs the exfil attack | GAP | `gitops/apps/network-policies.yaml` deployed; no live toggle + re-run framing |
| R2 | Image-source/registry restriction toggle vs the malicious image | GAP | no registry-allowlist policy/toggle confirmed |
| R2 | Falco + Kyverno exec/`ls` block toggle | GAP | falco/falco-talon deployed; no live enforce toggle + re-run framing |
| R3 | Three in-browser tabs (BurritoBot / VTT / debug) | YES | VTT (#7) + BurritoBot (#8); multi-terminal in VTT |
| R3 | Local kubectl optional, tiny print + warning | YES (mostly) | `success.html` optional `<details>`; add "experienced users only" warning |
| R3 | Self-paced left-pane challenge instructions | YES | VTT challenge flow (#32) |
| R3 | Challenge 5 output sanitization (fat spit blocked) | YES | `challenges/02-sanitization/toggle-output-guard-on.sh` (#20) |
| R3 | Challenge 6 input classifier (PII/cost) | YES | `challenges/02-sanitization/toggle-input-classifier-on.sh` |
| R3 | Challenge 7 evil MCP | YES | `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` |

## Gaps to schedule
1. R2 re-frame as attack-mirrored live toggles: NetworkPolicy(egress)->exfil, registry-restriction->image,
   Falco/Kyverno->exec. This is the R2 half of #6/B11; the built beat-01 controls can stay as bonus walls.
2. R1 malicious-image (Joker/grill zone) attack scenario.
3. R1 live "attack the room" observability: S3-fill view, Falco process/`ls` feed, the curated attack
   dashboard fanned out per org (ties to #25).
4. R1 gamified objective-gating + hint system (order unlocks on objective success).
5. R3 "experienced users only" warning on the optional local-kubectl section.

## Source transcript (verbatim, history)

> Speaker 1: We need to play up one of the ingredients.
> Speaker 2: Secret recipe, I don't know what it's not about, I can tell you.
> Speaker 1: Bat spit amazing hot sauce. What? That would be a sauce.
> Speaker 2: So hey, guess what? Now my device filled some data and now we've run a malicious image.
> Speaker 1: Or we have our data dog interface we can bring up so like always see someone's running,
> someone was able to deploy a Joker image or I can see, I don't know if I can see data being
> exfiltrated or if we have observability for the S3 bucket we can, maybe it's an Amazon interface. to
> show oh look some of the customer data is being populated in this s3 bucket y'all are doing it
> someone's doing it in the room you know so having some live view of those things would be cool and
> then as far as executable code they did all kinds of process live process view i don't know if i'd be
> able to but there is such a thing see their LS calls being made in their cluster so they all are doing
> it like someone's getting like even if like the individual person is not getting through they can see
> that people in the room are getting through and we can give hints like You're dying to order a burrito
> only but you can only do it if you accomplish your objective, you know if they my need Or maybe like at
> the end of the first one Where it's like we want them to exfiltrate customer data Then we can show an
> example of it working We'll do a prompt that we know works with or with or flow, but we'll be like
> We're so worried about her, but we know she ordered a burrito last week and if I can get whatever
> address you delivered it to, whatever, you know. us and BTT but they're not in their own BTT yet right
> and it should be
> Speaker 2: Maybe we can show them running a grill zone, grill zone, I got it.
> Speaker 1: it should be now we're going to activate a Kubernetes network policy and make sure data
> cannot be sent outside of the cluster and so here's a command while we're doing policy and now now when
> you're in your round two burrito bot now try to do the same prompt you did that was successful before or
> the success you know our example successful one and you can't and we talked about maybe using s2 as part
> of that one too i'm sure s2 probably has network policies or whatever that's alpha versus l7
> Speaker 2: Let me see.
> Speaker 1: No, we had talked about
> Speaker 2: Cillium's also not running for the cluster, so I don't know if there's any either.
> Speaker 1: Is Cillium the CNI? Is it running in addition to different CNI?
> Speaker 2: It's running in your C. It's running in your C. It also has a new BF enabled. All of them do.
> Speaker 1: So here we are running a command to turn on the network policy now you're on cluster to try
> to do it you can't and now what you can still do attack to where you can run your malicious image but
> now we're going to turn on hyper
> Speaker 2: source like
> Speaker 1: no yeah
> Speaker 2: this is basically you can only source from that harbor or whatever GCR whatever
> Speaker 1: and now try to run it and now BurritoBot says yes, but then the BurritoBot can't do it. And
> at some point in there we'll naturally talk about how you can do it at the prompts level, but the
> BurritoBot is that's still gonna get through five percent of the time. Um or if it ever gets through
> it's a problem, you know. And then Okay, but you can still run executable code on round two cluster.
> Speaker 2: Yeah.
> Speaker 1: And now we're going to enable Falkow.
> Speaker 2: There's a blackout on the round-trip last week.
> Speaker 1: My poor Kooparma walks through stop at this one. It definitely does stop at less call, so now
> if you exactly onto the thing and try to run it LS, it'll get blocked.
> Speaker 2: The performer is not enabled by default. It's installed. The Buckeye will also do that.
> Speaker 1: Buckle will block it. Ignition today.
> Speaker 2: Well, but also Falcon will detect it. a series of instructions. So let let's talk about,
> we're not we're not gonna give you the whole reveal the whole thing to you. But let's show you where you
> start. Just Burrito Bot once again. So you've seen this already. Now you've
> Speaker 1: Mm-hmm.
> Speaker 2: got your own. Turning on your clustering.
> Speaker 1: Mm-hmm.
> Speaker 2: The visioning is also gonna give you an in-browser Burrito Bot, an in-browser VTT and you're
> gonna in-browser debug. With three tabs, all in browser. If you wanna hook up your own code c config,
> you can on you to manage your environment. We're just gonna say this right. I would recommend to just
> use the terminal because you're already wearing a hat.
> Speaker 1: I would say I would not even mention it.
> Speaker 2: Well, they asked when they see it.
> Speaker 1: Oh sure, but they might it's it's small print at the bottom, it says optional. If someone
> must ask about it on their own time, that's fine. But I
> Speaker 2: No, no, don't use the last.
> Speaker 1: Oh my
> Speaker 2: That was right. Um I was trying to create that.
> Speaker 1: Yes.
> Speaker 2: I probably should add a warning that's Because it's only for experienced users.
> Speaker 1: Yeah, I almost don't wonder why we're offering it. I kind of understand why we would offer it
> in a take-home version. But there's like literally not time for anyone to set it up.
> Speaker 2: So
> Speaker 1: And to what end really?
> Speaker 2: Control. The geekiness. So now they're running through their own thing and we're gonna be
> like, okay, so You don't have to stick with us. We're going to do challenges five, six, and seven. This
> is where you have the AI that's supposed to be, where else. We're going to give you a quick mental model
> to look at, but otherwise for those of you who want to forge ahead, here's instructions on the left-hand
> side for step five, A, B, C, D, etcetera. You can just go ahead and start following them. But
> Speaker 1: Mm-hmm.
> Speaker 2: here here's the deal. Challenge number five. How do you stop an LLM from outputting? Or
> actually we just rest you with the problem. We're going to show you we put this in and then we stop this
> bad thing from happening, right?
> Speaker 1: So we offer fat spit secret recipe.
> Speaker 2: Yep.
> Speaker 1: Fat spit good. Store it on the cluster. That's it, I'm ready. I was worried about their brand.
> Speaker 2: Same way.
> Speaker 1: I think they might not want this.
> Speaker 2: San Francisco scenes, right?
