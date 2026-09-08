<!-- ABOUTME: Routed transcript (My recording 22 - 2026-06-24.mp3), matched to this repo on 2026-09-07. -->
<!-- ABOUTME: Auto-routed because: 2 section(s) of this conversation match the Unleash_an_Agent_Watch_It_Burn topic. Raw diarization; speaker labels are approximate. -->

# BurritoBot - AI Security Workshop Design

_Routed from the transcription pipeline on 2026-09-07. Source: My recording 22 - 2026-06-24.mp3._

---

### Recording and Screenshot Discussion

Speaker 2: Okay, and you can see the millions of views that's got.

Speaker 4: Yeah, so even if it doesn't hurt you, it can be embarrassing if you don't have a lockdown.

Speaker 3: Yeah. Yeah. So.

Speaker 4: And then you're going to say, here's the environment where running, the cluster we're running, we're running at IDP. You're going to have access to one of your own later in the course.

Speaker 3: Yep.

Speaker 2: And let me describe to you all the technologies that are at play.

Speaker 3: memory from bottom to top to bottom

Speaker 2: And you're going to leave all the security technologies out.

Speaker 3: I'm not going to talk about that unless

Speaker 2: Unless we're not demoing them, so like cert manager or something you could talk about.

Speaker 3: I'll probably wait until we get past the first interaction

Speaker 5: Or you could say there is a little bit of security running right now. Certain manager blah blah blah, whatever it is that's running that we're not using.

Speaker 3: The base and necessities.

Speaker 5: Yeah.

Speaker 3: But not prevention and detection.

Speaker 2: Okay.

Speaker 5: Um.

Speaker 3: Yeah.

Speaker 5: And you will get access to one of these later, but for now you have one plus you're running for the whole room, and you can access. You can order Here's a burrito box.

Speaker 3: Right.

Speaker 5: Right. And it's like, hi, there are no guardrails here, so we want some to pack the burrito box and we use it to access it and protect her and do the various things. We have some challenges for you to try to get through with path filming. And then we're just going to go through the three challenges that everyone overkills across here. And you are asking could we stream the prompt to the side.

Speaker 3: Yes.

Speaker 5: And I'd say that's a nice to have but not a must have.

Speaker 3: Okay.

Speaker 5: And of course we've talked about this before, if we do have it, it needs to be sanitized.

### Workshop Structure and Cluster Challenges

Speaker 3: Yep.

Speaker 5: It would be cool too if they get done with the challenge and we want to go back to amount of time to do it, then they have something to watch that keeps them in the workshop as opposed to checking out.

Speaker 3: Right.

Speaker 5: And then would this string part happen, does that happen only on our screens where they have to look up at the front of the room, or do they have a

Speaker 3: No, it has to happen on ours. Just on ours.

Speaker 5: Okay.

Speaker 3: Yeah. What is that? What is that?

Speaker 5: I don't know. It's like a four leaf clover flower.

Speaker 3: I think we do a round. It's almost like rounds or phases where it's like, okay, round one. This is relatively unfiltered. Round two, right? This one has infrastructure, right? Not AI got tails.

Speaker 5: Is it an actually unplanned question?

Speaker 3: Forward to question.

Speaker 5: I see that they're around, but like for round one, see the deterrent, do we also have... Here's round one still, and we're gonna use new technology to block it. Here's round two on the Honolulu platform. We put that one, and then we're gonna jump. Here's round two solution where we use new technology. We're gonna block that.

Speaker 3: So with round, so originally round one was just to show a completely unblocked cluster. And so then they like could destroy it or go willy nilly.

Speaker 5: So So round round...

Speaker 3: we were implementing solutions.

Speaker 5: Right. Around, I'm talking about, sorry, it's a windy day out for everything. So within like closer one time, like you have three challenges.

Speaker 3: Okay.

Speaker 5: And so you can either go, we're just going to spend the first third of Here is challenge one of round one. And now we're going to jump into question two and show you the solution. And then here's challenge two of round two and now we're going to jump into question two and see what happens.

Speaker 3: Right, that's what I was saying. No, that wasn't the original intention.

Speaker 5: Okay.

Speaker 3: But we can do that if that's what you want. But that wasn't the original framing.

Speaker 5: But what do you, what do you want?

Speaker 3: So I would prefer not to jump back and forth between clusters.

Speaker 5: Okay.

Speaker 3: So I prefer to just be like, okay, so this one failed.

Speaker 5: Okay.

Speaker 3: Now let's move on to the next cluster, next set of challenges, next round,

Speaker 5: Mm

Speaker 3: right?

Speaker 5: -hmm.

Speaker 3:  And this one has guardrails activated.

Speaker 5: Mm

Speaker 3: And that's where I think you show that the attacks that were used in the previous one, which is also why I want to capture possibly the attack and say, hey, okay, so does this get caught in phase two?

Speaker 5: Mm-hmm.

Speaker 3: And it's like, okay, because what should happen is that they're probably going to, we'll have our own pre-seated, but in round one, you sick? So like in round one, we're not responding, right? In round two, we are responding. Go. Why am I getting my own? In round two, we're responding mainly with infrastructure guardrails, right? In round three, we're responding with AI guardrails.

Speaker 2: I'm three, so okay.

Speaker 3: But those are the ones we're going to walk them through, yes?

Speaker 2: Yeah.

Speaker 5: one just not one at a time here's your challenge we're going to give you five ten minutes or whatever it takes. Um I can't see it I guess because I wouldn't figure out how long to give them. Um here's round two. Here's a five minute quiet to work it out and I one thing I like about street the idea of screaming um To the front of the room and if they're stuck they have hints from what other people are trying.

Speaker 3: Yep.

Speaker 5: You know what would be nice to have is if the prompts are showing up, it didn't look like green or something it would be obvious that that's a prompt.

Speaker 3: Yeah, and also I was thinking about making it so you could click on it and it would inject it into your prompt screen.

Speaker 2: Hmm.

Speaker 3: So that you could uh almost use like a library.

Speaker 5: But it's just our it's only showing on the instructor view, it's not showing on their view or it is?

Speaker 3: It is showing on instructor view, but they have a U_R_L_ that can get to see it.

Speaker 5: Oh okay.

Speaker 3: Oh I see what you were saying earlier. Are we only gonna show it up on our screen? We'll show it up on our screen, and but maybe there's a generic one that doesn't have the system prompts. Good for them. Regardless, we could give them the same interface. They could see the same thing if they wanted to.

Speaker 5: Oh yeah.

Speaker 3: We also don't know how big the screen's gonna be. So replicating it on their laptops might not be a bad idea. Does that make sense?

Speaker 5: Mm-hmm. So then they get five minutes to solve it. And then round three, it's like you get as long as we until someone, the first person who solves is going to ruin the cluster for everybody,

Speaker 3: Right.

Speaker 5: which is kind of will have a weird abrupt end.

Speaker 3: Yeah.

Speaker 5: And then it'd be cool if we could surface the prompt that killed it that got the got the AI to run a port prompt.

Speaker 3: Probably what I'll do is the prompt interface will be separate from this the cluster.

Speaker 5: Uh huh.

Speaker 3: So that we can just do a drop-down box if we want to. If that makes any sense. You can switch to the version one version around one round two around, even round three clusters.

Speaker 2: Uh-huh.

Speaker 3: So yeah. That way we can save the prompts.

Speaker 2: Yeah.

Speaker 3: How do birds just fall right into the crack between the sock and the shoe? Asking

Speaker 5: You'd

Speaker 3: for a

Speaker 5: just

Speaker 3: friend.

Speaker 5: make a little, it's like a little.

Speaker 3: We look like witches.

Speaker 5: You'll be a good place to form.

Speaker 3: It is pretty. So...

Speaker 5: that's all going to take an hour or more

Speaker 3: Just to do version one and two.

Speaker 5: Well let me think if it's maybe not that long but with the intros and the descriptions of the technology and five minutes each but really I think they need five or more minutes the first time to break it because they're actually trying and then the second time they don't need that long to try it one time. Yeah. You know,

Speaker 3: Yeah.

Speaker 5: So maybe an hour. But I think we could actually spend a good long time describing all the cutesy technologies we use here. Um. It's kind of a secret operator for the paint dealer. It would be something you could set up top that we're using that. You know what I mean?

Speaker 3: Yeah. Yeah, yeah.

Speaker 5: Um. So round one experience I think we talked that through pretty well.

Speaker 3: Yep.

Speaker 5: ideally they can see other people's attempts and we've even copy pasted other pencils there and

Speaker 3: Yep.

Speaker 5: we can encourage them in a few minutes to get your and if you at one minute see if you can try other ways to make the pencils. I wonder if there'll be something built into the foundational model that makes it so they won't want a fork bomb for example.

Speaker 3: Yep, let's see.

Speaker 5: I think it's at a yeah. And then we actually think two rounds were a little harder.

Speaker 3: So, okay.

Speaker 5: So round two. Okay, remember challenge one, and we had you get basketball, and we had you get customer data.

Speaker 3: That's super.

Speaker 5: You okay?

Speaker 4: Okay.

Speaker 5: Yeah.

Speaker 4:

Speaker 5: So that could be presented if you have the right network. to get that um out then if so we could actually even out if we always say like how much time we have and now it's um to get that do you guys pay somebody else to get that some of that 3d data in f3 and then we can be in the system and we can do that.

Speaker 3: I wonder though, it wouldn't be an attack of data and movement, right? In transit, it would be an attack on data at rest.

Speaker 5: I thought we had an app stream we cut through the data within the cluster from one to the other.

Speaker 3: How will they sniff wire to get the data that

Speaker 5: If they could figure out the command of how it's sending data, they could see it to their own, to the S3 bucket. What would you picture?

Speaker 3: there was a secret stored in like either a config map or a secret, right? And then what was happening is, or maybe even plain text or somewhere like it wasn't even like secured and they figured out how to copy it and exfil it into S3. Like they did, it's static, it's not encrypted.

Speaker 5: But then that's not demoing SEO, that's demoing a network policy only and not MDRF.

Speaker 3: No, well, yeah, it wasn't originally on my radar.

Speaker 5: Oh, we talked about it. I saw it written out. Okay. I mean, that's fine. I guess it was in the FTP.

Speaker 3: The abstract?

Speaker 5: Not the abstract, but like when we talked through and we didn't outline it so slow.

Speaker 3: Okay. I mean, we can do it.

Speaker 5: It's, again, I think it's a nice to have another must-have because there are two technologies that you need to prevent, like, like, exfiltrating customer data that's been from one app to another in the software. And you could show MPLS and SEO and then you can also show network policy could not.

Speaker 1: Right.

Speaker 4: Right.

Speaker 1: Right. Yes. Gotcha.

Speaker 4: Yeah,

Speaker 1: we can show up. That's why we talk it through.

Speaker 4: When we very first thought of the idea we talked about a secret. But now if we're supposed to agree to a secret secret operator at Is that what we're demoing as our environmental policy? Can I get to give notes and take as operator? I know we're supposed to use a secret.

Speaker 1: Yeah. Well, I think also, I mean, yeah,

Speaker 4: The problem with that is they're real people and they take jobs. We don't want them to exfiltrate.

Speaker 1: I mean, I think that's why we'll have to do a test. Remember, that's why the clusters one and two are disposable.

Speaker 4: Yeah.

Speaker 2: Yep.

Speaker 4: Yeah, I like those, the braided ones actually. And that also gives us room to make a funny type of thing. A wonder burritos on a wiki burrito bot, you know? Ready?

Speaker 3: Yes.

Speaker 4: So two things demo. Alright, let's talk about the second attack. What's the second attack again?

Speaker 3: So the first one was to show CNCF guardrails, right?

Speaker 4: So they're all the second attack guardrails.

Speaker 3: Sorry, let me rephrase that. The first attack is to show infrastructure guardrails, correct?

Speaker 4: What's the second challenge?

Speaker 3: Signal channels would be A_I_ based, right?

Speaker 5: No.

Speaker 3: No, that's not.

Speaker 5: There are three channels within section one. The first one is the scanning customer data. The second one is the phasing in. The third one is to kill the flusher. Oh we're going to run a malicious attack.

Speaker 3: Do you want me to do a malicious attack?

Speaker 5: Yeah. So you manage to run that malicious attack. you know if you have technology that can do things like that. So how would you actually, do you feel like okay paper no, you're only allowed to deploy what's running in our internal harbor registry?

Speaker 3: Well sourcing right so showing supply chain so probably signing and sourcing right you can only pull from our harbor registry and it has to be signed here's okay

Speaker 5: Of getting there.

Speaker 3:

Speaker 5: So that like you can like to play it from our internal Harper Road Street here that came around the policy

Speaker 3: Yep

Speaker 5: like but there's a way around it like and maybe we even let them do it depending how much time it is if you fit your malicious image into the Harper Registry then Chyverno will still deploy it like so we need to do more than that and like here's how we're gonna add signing and data stations and now we can talk about that. There's our two species again. It doesn't have to be that many species. And then the third problem is the fourth problem, which would be your use of propellant. Or what did you end up doing for a fourth drama? Do we need to change our executable?

Speaker 3: So that one ended up being Falco was doing detection and remediation in conjunction with a kernel change on the Linux screen. So it's both.

Speaker 5: Okay.

Speaker 3: One one has a eventual hard limit that catches it so it doesn't it can't actually overwhelm the Linux box but

Speaker 5: Would

Speaker 3: falco is dynamic and will detect it running anywhere and stop it as soon as it can yeah

Speaker 5: it be better to have some other sort of executable thing that would harness this one back to the Linux box?

Speaker 3: like scraping passwords for example yeah

Speaker 5: Yeah.

Speaker 3:

Speaker 5: Maybe challenge three is we have something stored on the like an Easter egg stored on the file system. Can you get your agent to fetch it?

Speaker 3: Yeah.

Speaker 5: Instead of it being the fourth llama. The fourth one's exciting because it like kills the cluster in like in seems in such a dramatic way.

Speaker 3: Yeah.

Speaker 5: So I'm sad to miss that beat.

Speaker 3: Well that might be one we do on question one.

Speaker 5: But the

Speaker 3: Like in round one. Sorry. It could be like the last challenge.

Speaker 5: Yeah, but every challenge backs to a solution. And so if we have the four clubs challenge, we need to show a four clubs solution. So I love a four clubs challenge. But the four clubs solution involves modifying kernel code, which is not found.

Speaker 3: Well, it's a file. Right?

Speaker 5: prevents the

Speaker 3: Yeah, prevents from doing four balls. What it does is it limits the number of PIDs that you can allocate to a specific process, so you can't four ball. So it just prevents PID uh over-allocation. I checked. The problem is, is that there's milliseconds between detection and enforcement. So like we I thought, because we had talked, we thought maybe Q-armor would do prevention.

Speaker 5: Yeah.

Speaker 3: But all of them seem to do detection and communication.

Speaker 5: Yeah. Do

Speaker 3: Now

Speaker 5: you understand the attention that I'm trying to solve? The attention is, okay, for challenge three and cluster one, we want to show Something that can be prevented by Falco or sea farmer.

Speaker 3: Right.

Speaker 5: I came up with a fourth option because I know that's an executable thing. But a fourth farm can't be prevented by Falco or sea farmer.

Speaker 3: Right. It can be detected during the year.

Speaker 5: And I like that beautiful farm because I like the drama of killing the cluster. But it's not solving the deep-seated objective that I want.

Speaker 1: Okay.

Speaker 5: Do you know what I mean?

Speaker 1: What is the teaching objective?

Speaker 5: That Falco and, yeah, Dora 2, for instance, execution level attacks.

Speaker 1: The clear phrase is that in that particular case they don't go to pass each other. But most of the time they would. Well, they wouldn't.

Speaker 3: Just a minute.

Speaker 5: Okay, the chapel boards want me not to do this. Colonel level stuff, I just think it's bad for the story. That's outside of the technology altogether.

Speaker 3: Yeah.

Speaker 5: Do you agree?

Speaker 3: I mean, I think it's part of it. But you're right, it's outside of the specific solution. I think it's a good way of showing though that sometimes the answer sometimes the answer is actually just a simple pile of pennies. You don't need a big technology to stop something from happening. I think that's also a good story.

Speaker 5: Or, I mean, maybe that's truly in the way the pile theory is really the top of the tech set. That's uh

Speaker 3: Pile's in place, absolutely.

Speaker 5: Not yet. I thought it's a place that there was a motive.

Speaker 3: Oh yeah. Absolutely. And Falco will detect it even with that problem in place.

Speaker 5: Yeah, that's okay. So maybe that's the story. Is this a different phone? We have to track the fourth phone with this particular situation. To the fifth, what is it? Limiting policy either.

Speaker 3: It's just setting the kernel so it won't allocate a certain number of pins to the fourth phone.

Speaker 1: So it's just a configuration change.

Speaker 5: Okay, so we figured this configuration is okay. But we want to know if someone's able to attack our cluster at the, at their executed, you know, at the file system level, like the third level, so we can do that with software to tell us, like we get that the alert's set. Right exactly where's

Speaker 3: Yep, that's the story.

Speaker 5: is that a better story than Carol screamed and there's a drug in the files, I see. Oh, I get that, you insert a file into your essay. That

Speaker 3: No,

Speaker 5: was,

Speaker 3: no, I didn't add to the story as well. Is it better than the Easter egg? Is that what you're asking?

Speaker 5: Yeah.

Speaker 3: I think that should be the third challenge, besides that round.

Speaker 5: The Easter egg.

Speaker 3: The Easter egg.

Speaker 5: The Easter egg is the first challenge.

Speaker 3: Love a phone call in five minutes. Well, I need to hear your thoughts that this is working out. the AI engineer world's fair. Are we spending too much time on infrastructure guardrails versus AI guardrails?
