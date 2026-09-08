<!-- ABOUTME: Routed transcript (My recording 201.mp3), matched to this repo on 2026-09-07. -->
<!-- ABOUTME: Auto-routed because: 3 section(s) of this conversation match the Unleash_an_Agent_Watch_It_Burn topic. Raw diarization; speaker labels are approximate. -->

# Michael Rishi Forrester - BurritoBot Agentic Security Lab Challenge Design

_Routed from the transcription pipeline on 2026-09-07. Source: My recording 201.mp3._

---

### Attack Me Phase and Challenge One Setup

Speaker 1: So, we're going from attack me, we're moving over to provisioning. You've left them on a cliffhanger of like, hey, you attacked this thing, you probably exfiltrated some data, maybe you got some of that, you know, like whatever, right? You've maybe accomplished something. Did you discover batsmith amazing awesome sauce? Do you even know what that is?

Speaker 2: Again, they can't do any of those things on their own without knowing what they're doing. The only thing they can do is challenge one,

Speaker 1: Okay.

Speaker 2: which is, I forget.

Speaker 3: I just looked at it, and I can't fucking remember. I'm a little fuzzy this morning. Oh, Michael. Michael R. Forster, Accenture. What were you thinking?

Speaker 2: Maybe don't one is exfiltrate to the beacon in point.

Speaker 3: I thought it was.

Speaker 2: Okay, then we'll have to give them that beacon in point So for do you know what we can do is have our community cluster with a different system prompt so they'll print the demographics to track

Speaker 3: Okay, so that was hard. The model resisted that.

Speaker 2: Okay

Speaker 3: That's why we went to Expo.

Speaker 2: I thought we changed the model.

Speaker 3: It is Nova. But understand that the base amount of security baked into all models now is much higher even than it was when we did it a few months ago. So

Speaker 2: 'Kay.

Speaker 3: challenge one is exfiltrate customer data. Yeah.

Speaker 2: Yeah.

Speaker 3:  So I made some modifications to some of your text where I changed the color to purple or

Speaker 2: Oh, okay.

Speaker 3: I added a vampire icon to the vampire thing.

Speaker 2: Okay.

Speaker 3: So they should like that which is tons of fun.

Speaker 2: I like those touches have become so important because they're showing you a human wrote

Speaker 3: Yeah,

Speaker 2: this.

Speaker 3:

Speaker 2: Yeah.

Speaker 3: yeah. We can try it. Let me check it out this morning.

Speaker 2: Okay.

Speaker 3: I'll try and make it so there's no additional information needed for the attack me cluster, right?

Speaker 2: Yeah.

Speaker 3: Like maybe we keep the X-Wheel as challenge one and leave the display data just for the attack me cluster. Like take the same data instead of X-Wheeling it, I just want you to display it on the prompt. Can you just do that?

Speaker 2: Yeah, yeah. Just for the attack me, but not for

Speaker 3: Well, and we've done that with amazing. that's been amazing awesome sauce right

Speaker 2: yeah

Speaker 3: so we could use that if as like as a preview for later on right so that wouldn't hurt anything yeah

Speaker 2: yeah let's try it

Speaker 3: okay um right

Speaker 2: that would be cool because then when the student does their own experience they have a different experience

Speaker 3: because

Speaker 2: yeah

Speaker 3: it's a new challenge like they're not starting with challenge one that we we start we showed them challenge five but they don't know that yet they haven't seen challenge five so

Speaker 2: wait what are you talking about challenge five No.

Speaker 3: Which one?

Speaker 2: We're going to have problems down the road, because we both have a different idea about what is what system, where the recipe is used.

Speaker 3: Oh yeah, where is the recipe used?

Speaker 2: I think it should be used in runtime security when they try to pull something off the hard drive off the host machine, but you have it somewhere else that I haven't gotten that far yet.

Speaker 3: Well they are they are reading it off the host machine they're displaying it though on the terminal, yeah on the the burrito bot, yes? Isn't that what we want?

Speaker 2: That's what we were... what we were supposed to do, but that's not what the labs do. Not last time I looked that far ahead. You have it on some other challenge.

Speaker 3: Well, it says make an agent leak the recipe.

Speaker 2: That's that's the runtime challenge maybe

Speaker 3: I believe so.

Speaker 2: it fixed it maybe it

### Runtime Challenge and Secret Recipe Storage

Speaker 3: Oh, it's stored in the Kubernetes secret. Yeah, that's an amazing awesome sauce. It's stored in a Kubernetes secret.

Speaker 2: Yeah that's not the that's not the runtime challenge. The runtime challenge has the has it stored on from the host machine and that's what we're getting. I guess you'd never be able to make it LS or a MC.

Speaker 3: Well it doesn't have access to a terminal. That's why we took it off because it wasn't realistic. If a burrito bot wouldn't have file system access.

Speaker 2: Well then what are we even doing? What are we doing for runtime?

Speaker 3: I don't think we're doing runtime, right?

Speaker 2: I'm sure we had Falco and Cucumber in there.

Speaker 3: Oh you mean get the secret recipe off the file system. That makes sense. Yeah yeah. Sorry it was one of the earlier challenges it was number three. Yeah, so it's there. Oh, 'cause the application wrote oh oh so this is that's right, I did change it because it was realistic I found a realistic path. The application wrote a temp file to temp burrito data, and that's where the the leaky secret is,

Speaker 2: Mm-hmm.

Speaker 3: right, and the recipe in this particular case. And so the house secret recipe is sitting in a file under temp burrito data and burritobot's going to get it, so that is the runtime blocker.

Speaker 2: Okay.

Speaker 3: Yeah, so it's there.

Speaker 2: Okay. Okay.

Speaker 3: Yeah, yeah, it's number three. So does that mean we're having an issue where we're seeing it differently?

Speaker 2: Okay. No, no, it got fixed. Okay, cool.

Speaker 3: Yeah, yeah, it got fixed.

Speaker 2: How's run up the bill get blocked?

Speaker 3: Run up the bill gets blocked because, um, uh... GuardProxy and or KHNN have limiters that you can put in there as far as spin goes. First of all, it has a cap no matter what we tell it. It's not going to let the students go above like $25. Like this is not going to happen, right? But I think we set a lower limit at some point.

Speaker 2: Challenge five is also make the agent make the recipe.

Speaker 3: Yep.

Speaker 2: So we have. So where I wanted it is fixed, but now I wonder if we can get it to leak something.

### Workshop Structure and Provisioning Phase

Speaker 3: then, so then just to check then, it's like, okay, so we're going to see them up, run through the attack me server, give them a server, and then once, once we go through provisioning, which is our third step, so we're, you know, step one is, you know, set up, right, step two is they attack me, step three is the provisioning server, so now they've gotten, they've gotten their own servers, and then once they get their own system.

Speaker 2: Uh-huh.

Speaker 3: what is the variant net after we've shown them the tabs they have open and where they go,

Speaker 2: Uh-huh.

Speaker 3: what do they do next? We already already

Speaker 2: So now

Speaker 3: say

Speaker 2: we're gonna give you a tour of the lab environment.

Speaker 3: Okay, which is part I think of the provisioning process. I think you're Oh, gonna right,

Speaker 2: okay.

Speaker 3: you're gonna open the three apps and then you're gonna give them a tour of DataDog, the Provil the uh terminal and we've they've already seen BurritoBot so they should be pretty comfortable with BurritoBot. robot at this point yes so

Speaker 2: Yeah.

Speaker 3: what are you laughing at

Speaker 2: Uh, there's a burrito bot button on the top page. Press it and it opens a new browser tab and you will meet burrito bot, a goth burrito ordering chat bot. The word goth made me laugh.

Speaker 3: so So, we seeded them, they're in provisioning, we've now, sorry, we've seeded them, we gave them ATT&CK me, now they're in provisioning,

Speaker 2: Mm-hmm.

Speaker 3: and then now uh in provis the provisioning process you've walked them through all three interfaces and now we're gonna walk them through the VTT for challenge one. So you're gonna walk them through the tour and challenge one. So the tour happens in the provisioning phase.

Speaker 2: Mm-hmm.

Speaker 3: Once you're done with the prov like the tour, you've hit all three buttons, they've seen DataDog and they're good wi good with comfortable with where traces are that's the last step you've already they've already seen burrito bot they've already seen the terminal they've right now they've seen data dog they're comfortable with ancient observability then you're going to walk through challenge one okay

Speaker 2: Yeah, and I think there may be once everyone's been hammering away so on community cluster a while having a page open a community robot a data dog page seeing everybody's hammering away. away at it and then like choosing like say haha look someone tried this someone tried this like it really drives home we can see what you're doing yeah

Speaker 3: So before we transition to provisioning we should pull up the community page and data dog and show them the shared prompts and then say look go you can go look at the traces

Speaker 2: also we can maybe be like did it was anyone successful are you willing to share like is it okay if we highlight you up here yes okay what was your was your prompt, I'll find it in in agent of usability.

Speaker 3: Yeah.

Speaker 2: Then we'll go through and see

Speaker 3: Okay.

Speaker 2: like their back and forth what uh

Speaker 3: So we should simulate prompts so that you can practice finding prompts easily in Datadog.

Speaker 2: Yeah, and that's probably a nice to have but it would be I think a nice way to round that out,

Speaker 3: Yeah.

Speaker 2: right?

Speaker 3: Yeah. Agreed.

Speaker 2: Mm-hmm.

Speaker 3: No, I think it's a great way to show because remember the one thing is is that it definitely I know this sounds weird, but I need DataDog to be shown in a good light.

Speaker 2: Mm-hmm.

Speaker 3: Right?

Speaker 2: Mm-hmm.

Speaker 3: So that like DataDog's like comfortable, you know, like th it's worth your time, all this other stuff. Accenture's already shown in a good light, because they're paying for the clusters and da da da da, right?

Speaker 2: Mm-hmm.

Speaker 3: And right, and we're fine. Like the whole thing's like expertise driven.

Speaker 2: Yeah.

Speaker 3: Which by the way I have some insight on that that has nothing to do with our talk, and so we're gonna talk about it probably on Thursday before you leave, but about the buyers versus builders thing. 'Cause I've just figured out exactly what Accenture's doing with the conferences.

Speaker 2: Oh, okay.

Speaker 3: Yeah, but it's

Speaker 2: What they should be doing or what they are doing.

Speaker 3: what they are doing.

Speaker 2: Okay.

Speaker 3: Yeah, and I know why they don't go to these conferences now.

Speaker 2: Okay.

Speaker 3: Yeah, anyway, side note, sidebar. Because so my point is, is that yes, I think we should take the time in the attack me phase to go to the shared prompts admin page,

Speaker 2: Mm-hmm.

Speaker 3: show all the prompts, invite people to, well, like show it, like tell us what prompt it is, go to DataDog, find the prompt, pull up the thing, and then that way you can show the DataDog interface and let them see like what's going on. Like what's going on there?

Speaker 2: Yeah,

Speaker 3: Yeah.

Speaker 2: yeah,

Speaker 3: So I it is worth saying that, you know, we're using DataDog, as you probably know, in the stack, we also have, yeah, there's availability tools, but they're not as sophisticated. I can say this with a lot of authority, I feel like they're just not as sophisticated as DataDog is,

Speaker 2: yeah.

Speaker 3: right? Don't get me wrong, you could probably eventually massage and get all the components and the integrations together and get close, but you're just not going to get to that level. a level without

Speaker 2: Mm-hmm.

Speaker 3: data dog right and i'll say that just so we're clear i'm gonna say that i

Speaker 2: Yeah.

Speaker 3: don't work for data dog yeah

Speaker 2: It's going to be like to be clear, it's instrument with open telemetry so you can send it to any back end

Speaker 3: yeah

Speaker 2: you want.

Speaker 3: yeah and i'll probably add a note just say look you can do everything most of the things that are here but you can't do everything that data dog's doing i'm not right we don't have open source corollaries for this so i'm not saying that you shouldn't use open source i think it's great it's here we've wired it up right this is where I spend most of my time but you know and I'm saying this not Whitney right she works for data dog I don't I have no affiliation for data dog right but it is just to say this it is actually true data dogs level of presentation sophistication and whatever is orders of magnitude above the open source tools you can't y you know you can't recreate that mote with

Speaker 1: Mm-mm.

Speaker 3: a tape podcast. Anyway. Um so okay. So this is great. So now I'm getting all of the beats that are inside of the setup. Okay, so then we finished provisioning, you've run through all three apps, you're now going through challenge one. They have clusters at this point in time. So we're now in what I would call a phase four. They have clusters.

Speaker 2: Mm-hmm.

Speaker 3: You're walking through challenge one. Do we Well this is the part that I was just slightly unclear of from earlier. Do we give them time? Do we walk through the challenges real time with them? And and while we're talking like you guys can tune us out and just go do challenge one. But we're gonna walk through it with you so those of you who wanna stay with us we're gonna do a little bit and pause and let you catch up and then do a little bit more and pause and let you catch up. And then we're going to stop right before giving you the answer, give you some time to come up with your own answer, and then we're going to work the hint, show you the answer, like turn on the guardrails, work the answer, and then, right, like, is that the way we want to do it, or do we want to be like, hey, we're now at challenge one, you've got a ten minute timer.

Speaker 2: Yeah.

Speaker 3: You've got ten minutes to go and hack this thing and do the whole nine yards and what we're gonna do is at the end of the ten minutes we're gonna talk about the solution very briefly and then we're gonna move on to challenge two. Do you want it those two ways or you want some hybrid?

Speaker 2: It depends on how much time. If we run through the lab and it takes an hour and we have a two hour block,

Speaker 3: Yeah.

Speaker 2: then we give them time and then run through and then we'll use a bunch more time.

Speaker 3: So you want to see what our data or run

Speaker 2: I through? think it depends on how it all works. on how it all times out

Speaker 3: Okay.

Speaker 2: and then and then there's always a middle ground where we give them time to break like do the challenge part on their own and then we go through the fix together So it could be all of them. We're going to mostly chill and recap all of us where we go through every little thing and there's no pause or a hybrid where they do the challenge where they try to break it on their own and we do the fix together.

Speaker 3: Okay, so

Speaker 2: And I think it depends on timing.

Speaker 3: we want to run through the workshop at least once before. Okay, so I'm now much more clear about the run of the show. I'm leaving phase four. Which is ambiguous which is going to be the bulk of the remainder of the two hours We need that we definitely need another timings of Setting them up, getting into rebu like they attack me and then provisioning phases, we need to one hundred percent know those timings. Let's say that takes thirty minutes. Means we got ninety minutes to do eight challenges, just so you know, we actually have twelve challenges, but we only put eight on there, right? So I've got four more that I'm probably gonna carry underneath the very bottom. So, right?

Speaker 2: Very un-grade.

Speaker 3: Well the reason is is that we could burn through eight challenges really fast. We're not gonna burn through twelve, right? So I'm just trying to make sure that we have uh extra extra content in case we need it right because the other thing is is that let's say we burn the first 30 minutes we've got 90 minutes left we're going to take 15 minutes for Q&A at the

Speaker 2: Yeah.

Speaker 3: end right we are we're going to stop and be like okay questions comments because we also would want to take that 15 minutes to walk through the repo like I'm going to walk through the repo and say by the way this repo is open free for you to use but I want you to understand what's here because understanding what's here shows you the value of what you just just did and how you can now take this home with you and implement both the AI and the infrastructure guardrails that we're talking about. But I want you to understand what's in this repository just very loosely. It's going to take two minutes just so you can understand the values. So here's fleet.sh and this is what invokes all of the terraforming.

Speaker 2: Yeah.

Speaker 3: It has specific syntax. This is all in the README. Underneath here, this is where Argo lives and this is where Caverno lives. This is where all that All of the apps live. I'm not going to run through them all. They're all in this directory. You want to add more apps, you go to this directory and you add them to Argo. And then, you know, and just like by the way this is all provisioned on EKS. You can do this on any Kubernetes conformant cluster, right? This is the EKS portion. If you want to put an Azure directory here or a GCP directory natively, like I just want to take a moment to say I don't need you to memorize this, but I want you to know that fleet.sh is where everything starts. So if you're wondering how things work, you start here, right? And then just let it go.

Speaker 2: I would prefer not to have. Bonus challenges. I would like to respectfully request that we don't include those.

Speaker 3: Okay.

Speaker 2: 'Cause these are ones we've talked through a lot embedded and if we add more content this late in the game then then I feel like I wanna vet it and it's not like I that sounds like s a lot of extra work that I don't wanna do.

Speaker 3: Done. Okay.

Speaker 2: And then also if we have stuff we don't go through then that makes it feel unfinished for them and we're gonna take their cluster away. Okay, so that is a bad user experience.

Speaker 3: Okay.

Speaker 2: Yeah, and I'm sure we can still fix in between in at 90 minutes. That's fine too. Like no one's going to be upset that we didn't use the full two hours, but I think the problem's going I don't I'm I don't think we're gonna have that problem.

Speaker 3: Okay.

Speaker 2: That okay?

Speaker 3: Yeah, that's fine. Yeah. Okay. So then that's the last question then for the run of show is like how what is the actual timing for the running through the eight challenges that we have?
