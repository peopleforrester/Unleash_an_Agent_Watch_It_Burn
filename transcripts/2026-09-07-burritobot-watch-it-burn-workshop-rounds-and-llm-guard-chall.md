<!-- ABOUTME: Routed transcript (My recording 23 - 2026-06-25.mp3), matched to this repo on 2026-09-07. -->
<!-- ABOUTME: Auto-routed because: 4 section(s) of this conversation match the Unleash_an_Agent_Watch_It_Burn topic. Raw diarization; speaker labels are approximate. -->

# BurritoBot - Watch It Burn workshop rounds and LLM Guard challenge design

_Routed from the transcription pipeline on 2026-09-07. Source: My recording 23 - 2026-06-25.mp3._

---

### Serial Language and Round Structure Overview

Speaker 1: Serral language moving forward, I want you to remember that.

Speaker 2: Yeah, because it was using beats and I think I was just like, let's just do rounds and challenges and stuff.

Speaker 3: Mm-hmm.

Speaker 2: So, all right. So I guess the thing that I was wondering is that, one, it should be like three rounds matches are three different types of clusters, like no guardrails, infrastructure guardrails, AI guardrails. Correct?

Speaker 1: Yep. Correct.

Speaker 2: In terms of mental models, that's right.

Speaker 1: Yep.

Speaker 2: So I think three of the challenges were...

Speaker 4: For four of the challenges are infrastructure challenges and then the remainder are A_I_ challenges in terms of the seven, the total seven sets of challenges,

Speaker 1: Okay.

Speaker 4: right?

Speaker 1: And the last two are both execution levels. So they're basically two sides of the same coin.

Speaker 4: Well I think that's where the gap is. I think, uh either our my transcript translation didn't capture it correctly, I didn't remember all the details, but I think that's why we're going to go through this.

Speaker 1: Okay.

Speaker 4: So if we're looking at round start agent at mar dot com, get if you go to the next one. Excellent. So that matches the cluster types. Round one is the no guardrails everything works. Round two is infrastructure guardrails are on, right. Um

Speaker 1: Mm-hmm.

Speaker 4: and progressively on, right.

Speaker 1: Mm-hmm.

Speaker 4: And then round three is the AI guardrails get progressively, right. We progressively turn them on and show them working, right.

Speaker 1: Mm-hmm.

Speaker 4: So the defense activation and the challenges are cumulative. But like the same attack prompts could carry forward across the rounds. That was sort of the general thought, yes.

Speaker 1: same attack prompts yeah yes I don't I know less about I have less of a vision for the third one so that's I'll have a lot of questions when we get there but

Speaker 4: Good. Absolutely.

Speaker 1: for this for one and two yes exact same attack prompts

Speaker 4: Okay.

Speaker 1: now it works now it doesn't also I will say round one you say no guardrails I do think we'll have some guardrails like ESO and search manager for example external secrets operator

Speaker 4: I understand. women what will those everything's

Speaker 1: we don't need to talk about it but um uh i'm

Speaker 4: installed it

Speaker 1: just saying yeah you already have it and we're already doing those things so i guess i'm not saying is it's a misnomer to say there's no guardrails because you i thought you were using those things yeah

Speaker 4: is a misnomer there are guardrails actually at every level the clusters are dependent and absolutely they don't get one hacked publicly and two don't embarrass us

Speaker 1: yeah so they don't have there's no code of conduct content violations so there are okay so just between us we don't have to say it but there are a couple guardrails

Speaker 4: So would it be better to remove it and say minimal guardrails?

Speaker 1: I think that's more honest or I mean we can say no guardrails in writing and our voices can say we know there's gonna be guardrails in here we don't we don't trust you actually right yeah

Speaker 4: Fair.

Speaker 1:

Speaker 4: So then that's why I'm asking why you're making the distinction. Do you want to make a change there?

Speaker 1: I'm just saying now I don't need to make a change.

Speaker 4: Okay, go

Speaker 1: I

Speaker 4: ahead.

Speaker 1: just am talking with you about making sure we're on the same page.

Speaker 4: We are.

Speaker 1: Okay.

Speaker 4: There are definitely guardrails.

Speaker 1: All right.

### Three Rounds and Challenge Classification

Speaker 4: And then all seven challenges could succeed on the round one if we even show them, which we may not. Challenges one through four are blocked on round two. Challenges five through seven are blocked on round three. Notice it says same install for every cluster, basically every round. What differs is what is enabled and not. In other words, Falco will probably... will probably be on round one. It just won't be doing anything with our rules.

Speaker 1: Okay.

Speaker 4: We'll have rules. But you know what I mean, for them the story

Speaker 1: Right.

Speaker 4: is there's no rules.

Speaker 1: Yeah. Uh I don't I can't say I really care one way or the other I

Speaker 4: I guess want whether

Speaker 1: to

Speaker 4: or not we want to acknowledge that all the tools are actually installed.

Speaker 1: Okay.

Speaker 4: Base level guardrails to protect the workshop will be installed.

Speaker 1: Okay.

Speaker 4: Production level blocking guard rails won't be installed for round one. Some will be installed for round two. to you all of them will eventually be turned on for me and

Speaker 1: Okay, here's the thing. I thought, and maybe that's a question for you. This one says all seven challenges succeed. I thought we were only giving them the first four challenges. Are we giving them seven challenges?

Speaker 4: that's where I think I got things wrong

Speaker 1: Okay.

Speaker 4: we're not going to run through all seven challenges we

Speaker 1: Yeah.

Speaker 4: don't have time for that

Speaker 1: Here are four ways we're going to have fun banging on this.

Speaker 4: because that's maybe the question here is that maybe there aren't seven challenges. Because I think what it's doing is there are challenges five, six, and seven I think were optional. Like if we had time and we needed the time to burn, we could run additional challenges.

Speaker 1: Five, six, and seven are your AI guardrail challenges.

Speaker 4: Right.

Speaker 1: Okay.

Speaker 4: I guess my point is that out of the seven, it seems like one, three, six, and seven were like the ones that we might want to focus on and leave the others as optional in case we get to round three and we burn all the time. we all have our time we

Speaker 1: Yeah.

Speaker 4: have a bunch of free time but let's run through this and we'll talk about the challenges and we'll pick and choose but I think we're on the same page

Speaker 1: Yeah.

Speaker 4: okay

Speaker 1: And I don't even think picking and choosing now is the thing. I think that's like wait till we have that problem to solve that problem.

Speaker 4: yeah

Speaker 1: Do you agree?

Speaker 4: I mean if we don't get to well hold on so here's the problem and we can't do them in order because if we go one through four and we don't get to the five six or seven

Speaker 1: Right. Right.

Speaker 4: This is why I'm saying we might need to reorder them.

Speaker 1: I hear you. Well, I don't think reorder will just be like, oh, we don't get to do four. infrastructure challenges because we need to make room for the a this last

Speaker 4: Let's

Speaker 1: thing yeah

Speaker 4: say they are parts of the airport.

Speaker 1: but but again we don't have that problem yet so I don't want to solve for it until like when we get when we have everything together and we run through it together and then we time ourselves and we're like oh shit this is way too long then we cut what we need to cut right at that time

Speaker 4: Yep.

Speaker 1: instead of trying to figure it out now do

Speaker 4: Okay.

Speaker 1: you agree with that strategy I'm open to doing

Speaker 4: Yeah, it sounds

Speaker 1: something else

Speaker 4: fine.

### Challenge 1-4: Data Exfiltration, Malicious App, Easter Egg Secret

Speaker 1: okay Um, customer data exfiltration to an S3 bucket, yes. Deploy malicious app, yes. Grep a planted Easter egg secret, sure. I don't, is this something, are we trying to get a Kubernetes secret or like it's something from Kubernetes or trying to get something like planted on a, no, it's not a Kubernetes secret. Just to be clear, we want something from the file system. We want. We want them to like get exactly in the file system, LS around, find a thing.

Speaker 4: How are secrets mounted inside Kubernetes?

Speaker 1: Are they always, they're always on the node that has the secret.

Speaker 4: It can be.

Speaker 1: Yeah.

Speaker 4: They can be set as many environment variables or they can be mounted as part of the file system. So my thought is to mount it as part of the file system.

Speaker 1: Okay. Okay. I don't, I guess I don't see too much where it matters except. Uber, maybe secrets shouldn't be encrypted at rest, and I guess that's another thing to mention. They shouldn't be in play text on the file system.

Speaker 4: It's obfuscated, but it's not encrypted, remember? You know,

Speaker 1: Oh, that

Speaker 4: it

Speaker 1: it's

Speaker 4: doesn't,

Speaker 1: encode,

Speaker 4: it's encoded,

Speaker 1: decode base

Speaker 4: but it's,

Speaker 1: 64.

Speaker 4: yeah, yeah, yeah. But it's not encrypted by default, you have to add additions, you have to add things to make that happen. Actually,

Speaker 1: So

Speaker 4: it's a trade.

Speaker 1: what we can make a FACO rule about is something as simple as someone running a less on a host machine because that should never happen in production. There's no reason.

Speaker 4: What if they're troubleshooting?

Speaker 1: On a production machine,

Speaker 4: yeah person the exact same thing and starts troubleshooting right

Speaker 1: I guess you want to be at least formed about it or like have a falco rule that someone's poking around. But I don't think you're supposed to do that.

Speaker 4: that's standard practice when debugging you'll freeze it and then go in and take a look at it especially if it's a security violation might snap it freeze it isolate it and then go yeah but most of time you're right you don't run ls you go in there and run a security tool it snapshots everything inside the file system and then you get the fuck out

Speaker 1: Yeah.

Speaker 4: even opening a tunnel to a good cause but it's not it's not it's very common it's how people who are bad at it really do it they do it a lot they'll exact in like ask chris how many times he's exact into a container and he'll tell you oh yeah i been in there and i take a look around and we don't have a lot of it's like so what's interesting though is that falco could stop you from mounting secrets inside of the file system and just keep them in this environment or even then actually so mad I

Speaker 1: was thinking it's as easy as a Falco because of what what Victor's demoed is he said there's you shouldn't have a listening in a file system and here it is being blocked and if we wanted to use kubarmer but like um really like if it's just like here we are look so here's the class here's they're looking around the file system trying to find the easter egg dragon we do have like funny names or whatever to lead them there um and then they find the easter egg but then later we show them oh falco has captured all of your moves as you go um and been alerting so we've been getting alerts that someone's like poking around and we can see and it's not one you know or whatever but so uh that's that was the story in my head when i was talking about it i'm not against the kubernetes story kubernetes secret story

Speaker 4: So we can do whatever you want. You want to keep it simple? Let's just go to follow along the file system.

Speaker 1: Yeah.

Speaker 4: Okay, let's just do that. We don't have to do a Kubernetes secret. We don't have to add complexity to

Speaker 1: Yeah.

Speaker 4: it.

Speaker 1:

Speaker 4: Just keep it secret. Keep

Speaker 1: And

Speaker 4: it simple.

Speaker 1: then we have, we do need external secrets operating on real secrets or like whatever. So okay, so LS.

Speaker 4: We should leave that alone. I don't like them messing with the secrets inside AWS.

Speaker 1: Yeah. Yeah. So right. So therefore we just manage everything with ESO. You can't see it. see it as a lab person there's no Kubernetes secret

Speaker 4: Yep.

Speaker 1: here even

Speaker 4: Let's just put a silly file inside of a container.

Speaker 1: yeah even made it up secrets or whatever yeah silly file in a container silly um file path names to leave you there exactly

Speaker 4: Okay. Is this what you're looking for?

Speaker 1: don't don't look here all caps

Speaker 4: Right? Right.

Speaker 1: the

Speaker 4: or you

Speaker 1: directory

Speaker 4: find it like

Speaker 1: name

Speaker 4: this and then you have two directories is or is not and it's like is and then what maybe you know what I'm people you know buffalo we're looking for it's like you know

Speaker 1: I like for the love of God do not open this directory in all caps definitely not this one just

Speaker 4: Oh, that's a good one.

Speaker 1: again

Speaker 4: Definitely not this one.

Speaker 1: again yeah

Speaker 4: Yes, definitely not this one. Yeah. Oh, my God.

Speaker 1: so then you see someone exiting on a machine you see LS you see you know yeah opening directories or whatever you can capture in Falco and then that'll go through even into a data dog back end we can show them and then the fork bomb yeah

Speaker 4: When we run that one in the cluster, just poofs.

Speaker 1: and

Speaker 4: What happened? You know what? Let's pull up another cluster. And it's like, we're losing them, you know? Why is that happening?

Speaker 1: that should be quick because they've already figured out how to trick their agent into running code Right, like because their agent is the one who's actually doing this. Yeah, I wonder if Don't Look Here would actually work for an agent. I said not to look in that one.

Speaker 4: look for a file system called don't look here we should give them a hint and be like Um it'll be fairly obvious.

Speaker 1: Yeah.

### Repository Structure and Lab Interface

Speaker 1: And it's, what do I need to do my own milestoneing? I can't tell. That's not very true to get there.

Speaker 4: That may already be done remember this is maybe a day so maybe it hasn't caught up

Speaker 1: Okay. I just.

Speaker 4: So what I'll do is I can the idea though was for us to look at it to mainly get the challenges and things it wasn't it wasn't this this react to list is bullshit.

Speaker 1: Okay.

Speaker 4: So yeah notice by the way that carbon card cardio and like Our back and all that will probably be a little bit more narrow. But notice that there are guardrails actually active. It's not really off. But we'll put some things on there. Like I'll turn it on input guards and output guards as well. Like we're not going to allow it without contact, right?

Speaker 1: Yeah.

Speaker 4: Yeah. So we can say minimal guardrails just to protect the ending experiences.

Speaker 1: Yeah.

Speaker 4: So is this helpful? Does that get us closer?

Speaker 1: I think so, don't you think so?

Speaker 4: I think so too. We'll stop recording unless you want me to.
