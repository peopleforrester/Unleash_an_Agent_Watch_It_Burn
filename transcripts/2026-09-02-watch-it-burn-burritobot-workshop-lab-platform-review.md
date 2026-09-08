<!-- ABOUTME: Routed transcript (My recording 195.mp3), matched to this repo on 2026-09-02. -->
<!-- ABOUTME: Auto-routed because: 5 section(s) of this conversation match the Unleash_an_Agent_Watch_It_Burn topic. Raw diarization; speaker labels are approximate. -->

# Watch It Burn - BurritoBot Workshop Lab Platform Review

_Routed from the transcription pipeline on 2026-09-02. Source: My recording 195.mp3._

---

### Lab Instructions and Component Overview

Speaker 1: Tell us a joke.

Speaker 2: Yeah, tell us a joke. Tell us your favorite fruit. What is your favorite topping for a burrito, right? Okay. And then that's one. And then two says, hey, this is what you got handled on. This is a full internal development platform built itself from one script. Have a look at what's running, right? So, you

Speaker 1: As an end user, do I care that it builds itself in one script?

Speaker 2: might, because it's in the refund.

Speaker 1: But if you want to see that script, if it's hyperlinked to the script, maybe that would be cool.

Speaker 2: Okay, so hyperlink to the script, otherwise delete it.

Speaker 1: Yeah, or maybe don't present it as the very first thing because it's an implementation detail, it doesn't have to do with the lab.

Speaker 2: Okay, and do you agree with showing them everything that's running so they can see for themselves that Falco and CertManager and KubeArmor and Loki and Otel? And all of this is running.

Speaker 1: Yeah, but I think I want a little more hand holding where either before or after you click that button and see what's running, be like, look, there's SEO service match, there's pages, that's a framework for the agent workflow, there's hibernal for policy, there's flopping. Like, I think where... It's going to be a lot if we think our viewers is going to know what stuff is. And I don't think we need to explain every single thing, but at least like the hits, we should like have a sentence about what they are. And also sometimes some like, and if any of these technologies are unfamiliar to you, that's okay.

Speaker 2: Well we can have a link to the page.

Speaker 1: Focus of the lab.

Speaker 2: If they want to learn more, we can have a link back to the project pages if they want.

Speaker 1: Oh sure, yeah.

Speaker 2: Yeah. Alright.

Speaker 1: They have no hyperlinks to Caberno.

Speaker 2: Yeah, there's like hey, here's the Cabriono documentation page. Alright, so then help me with this. First of all, just to say this, this is exactly the kind of feedback I need, so this is great. One. Alright, so we're on to on the VTT. Okay. So, keep it simple. Don't just give them a blank vomit of everything that's on there. Select specific things, run this command and notice that Carbono's here. Run this command, notice that KH is here. So tell me this. One, is that what you want? And two, which products do you want to highlight?

Speaker 1: I think maybe a moment of everything's okay, but... But with the acknowledgement that it's a bummer of a lot of things that you're not expected to know what all these things are,

Speaker 2: Okay.

Speaker 1: the ones that are relevant to the lab are going to explain them into your time.

Speaker 2: Okay.

Speaker 1: And meanwhile, some things to notice are the certificates between services are automated with certain managers. There's thousands of like... uh I also would cut for a and coupon or whatever here are ones these particular ones are ones we're going to touch on later,

Speaker 2: Okay.

Speaker 1: not about them too much now.

Speaker 2: Okay.

Speaker 1: Or whatever.

Speaker 2: Also just to say this is there's a couple of demo apps on here and I'm probably going to rename them to demo app dash app name so that no one questions what they're for like there's a mantis shrimp party there's there's a wombat party unicorn party I probably just going to put demo app demo dash app on there yeah

Speaker 1: Either that or acknowledge them.

Speaker 2: but if I put demo app and they kind of become self-explanatory right

Speaker 1: And when I met acknowledged them, I mean like, and never do you mind what man who's doing parties. That's what I mean by acknowledge. Like they're there, we know they're there. I don't even, it's, don't worry about it.

### User Roles and Access Levels

Speaker 2: Yeah, don't worry about magic shrink party unless you want to touch magical worlds Yeah, gotcha Okay, so then that clears two up to a certain degree Yeah, so this starts talking about get ops in a guardrail, right?

Speaker 1: Wait, no. Who, what, am I full somewhere that I'm a platform engineer? Am I a platform engineer?

Speaker 2: No.

Speaker 1: I'm a developer?

Speaker 2: Yeah. I'm just kidding. We haven't defined any of that.

Speaker 1: Then why do I hear the wrong foot? Like that's confusing.

Speaker 2: Because in an enterprise environment they wouldn't necessarily have this level of access unless they were a platform engineer, right? I think we're differentiating because remember the whole thesis about it is infrastructure controls versus application controls. So we're drawing lines between developer roles and operations roles.

Speaker 1: Okay, I think we need to say that.

Speaker 2: Do you want to talk about normally you wouldn't have full access to a platform if you were a developer and as a platform operator you wouldn't necessarily have full control over the application code like do we want to draw the distinction or would you like to take a different tact for it?

Speaker 1: Can you say something about the point at the left?

Speaker 2: Okay, because to a certain degree we've already we're already following the run of show to a certain degree just so you know in case you were wondering. The run of show was to basically first set context for what we're about to do then give them access to the labs right and then walk through challenges one and two and then let them do challenges one and two. And at that point in time, they're not doing the challenges and we're kind of like talking every five to 15 minutes about the challenges that they're walking through while giving them time to walk through the challenges. Does that make sense?

### Workshop Run of Show and Challenge Structure

Speaker 1: Yeah. Are we doing, um, for one and two, are we? First having them log into our cluster and our burrito box to try to pack it and then we give them a burrito of their own cluster.

Speaker 2: yeah let's uh let's talk about this for a second because we're kind of in that hold on a second let me let me do this really quick right so Oh, uh... Oh, hold on. So, the original thought was that we would do a cold open, right? This has to be my gold round by the way. Then we would do the onboarding right? You would drive, I would float as far as like onboarding clusters, claiming the cluster, going through the whole thing right? And then the rounds, so we would walk them through the round two after we basically get them set up on their cluster and then they would get hands-on for all of the challenges, so on their own round threes. And so we would just repeat that. Notice, by the way, that we are about 35 to 40 minutes in before we let them just go on their clusters, right? And then we've got about 15 minutes of wrap up and feedback and then, you know, a little less than 10 minutes of slack in the whole thing, right?

Speaker 1: So the plan is for 1 and 2.

Speaker 2: To demo 1 and 2 to them and then let them do 1 and 2.

Speaker 1: So we demo one of them, they write a packet, it goes, they say they write a packet and Dello chooses a packet, they take the packet again and then give them access to their clusters and then they're going to do one or two on their own in their clusters and then spare their own three.

Speaker 2: Exactly. How does that work for you? What do you want to do differently?

Speaker 1: How many rounds are there?

Speaker 2: Uh well, let's go take a look, alright? So if we look in the cluster, let's collapse this one. So it looks like currently there's seven rounds. I need to put the other four challenges up at the top here so they can run through them in order. Um but the other four challenges would be right, try to read the secret. Oh, actually that should be updated. Anyway. we'll we'll fix that oh no I actually did test this this is all this all works that's right deploying a malicious image which by the way when you look at the log files for this malicious image when you get to get it to run it actually the Joker says ha ha ha you downloaded a malicious image good job I'm now have control of your system it's funny and then snoot the soft call system for planet secret run the denial of wallet so I got rid of the fork bomb and we did denial of wallet instead Denial of wallet works great because burrito bought has

Speaker 1: The costing thing, as you can see right here.

Speaker 3: Uh-huh.

Speaker 1: Notice this is a round three cluster, so it's got a spin cap. If we go look at the round one cluster, right, it also says it has a spin cap, but the spin cap's not enforced.

Speaker 3: This is the denial of water.

Speaker 2: That is a tagline.

Speaker 1: Yeah, yeah it's a new attack name for getting a model to eat so many tokens so quickly so fast that you've now broke the bank. It's the same as the denial of service, only no one's ever talked about the denial of wallet that happens with the denial of service. Denial of service, if, as an example, let's say someone attacks your web server, and this happened to Michael Krebs, by the way, who's a famous security researcher, he was being backed. backed by Akamai and Akamai was started spending $20,000 a month to keep his website online because everybody was attacking him so Akamai had to stop sponsoring him because they were like we can't host your website anymore because we can't afford it Google picked him up because Google was like we'll take him right but Google was also like we'll do better security than Akamai because they obviously don't give a shit so my point being is that even if you can scale up to a thousand servers to keep your web server up if it costs you a million dollars and you're only making five hundred thousand denial of wallet right just so you know you're not the only one who hasn't heard that term I didn't make it up but I'm one of the few people who uses it so you're gonna so it's gonna it should spark some questions I would love to be the first people who introduce people to a concept just to say this Anyway, just anyway. So it's legitimate. So going back, so the idea is that the attendees would work through all the challenges one through seven. And so secret, poison prompt like an input guard, output guard, and we did that in that order on purpose just so you know. Because if you do it on the input guard, it doesn't cost you anything. If you do it on the output guard, you've spent the tokens and you had blocked the attack. And so it costs you money, which is why we formed it that way. And then the MCP authorization. Prompt injection via MCP, I want to say is like the number two most popular vector for attack against the model and its applications. So, and then. that people want to reset everything or replay the rounds which honestly I'll probably put round one to challenge one two three and four up top but that's that's the general run of show just for them walking through their own stuff does that work I can call this out more explicitly if we want to get more granular about what we're talking about

Speaker 2: I think at a high level I like it. I need to work through it a little more. I have it handy and

Speaker 1: Okay.

Speaker 2: we can have that experience tomorrow.

Speaker 1: The clusters are persistently up and available. You put your username in to provisioning and you're going to get... You're going to get your admin clusters if you put wiggity Whitney plus anything to do student one you're going to get a student cluster I I have five student clusters up so just know if you do student one two three four and five that's going to be the max right but otherwise you can or you can use your attendee cluster that's already attached to your admin account or you can create a new student cluster if you want to that make sense

Speaker 2: Yeah, I'd like to create a student cluster and I can do that. But I would like to have the instructions how they're supposed to be so I can run through them in order.

Speaker 1: Oops, I said it again.

Speaker 2: I would like the instructions to be correct right now what starts at row three and

Speaker 1: Okay.

Speaker 2: it's not just the instructions right there, it's the policies that we need added and set.

Speaker 1: Uh, hold on. What do you mean policies and stuff that need to be added? Say more about that.

Speaker 2: I don't remember what it's founded right now but like one of them is solved by adding a governor policy right one of them solved by adding a run time policy but

Speaker 1: Oh, so that's just guards on, guards off. So that's all in the instructions, right? So, um...

Speaker 2: the instructions don't say turn the guards on do they they say apply this governor policy here's Right?

Speaker 1: I think

Speaker 2: Here, yeah, the Petburnham policy, we're applying what we're doing here to the animal, what it looks like, and that's going to stop the type of attack our dogs aren't dogs, it's too abstract, and we have time now to kill.

Speaker 1: Right, so I think when we were demoing it was still guards on guards off. If you want the actual commands so we can do that, that's easy.

Speaker 2: Yeah, not just the command, but I want to see the YAML of the hypernode policy because that's going to stop this attack.

Speaker 1: Okay, well you have it all inside the cluster. So I'll make sure the instructions are clear.

Speaker 2: So the command has out the YAML, what you see.

Speaker 1: Yes, you can cat out the YAML if you want to or we can embed it in the instructions, whichever you want.

Speaker 2: Okay, I'm probably embedding it with the character that was nice.

Speaker 1: Okay. So then what I'll do is I'm probably going to differentiate the instructor cluster information from the student cluster information. So for example, this is a student cluster, right? So and right now what's going to change is that one and two are going to stay the same, but it should then say challenge one, two, three, four, five, six, and seven. So you should have carrots around all those. That's what a student should see.

Speaker 2: I think this challenge means the same as numbers, the same as the step numbers. I propose that there is a step zero that does everything work for the environment plus, you know, for the lab environment and for the...

Speaker 1: Okay, easily done. So we'll renumber everything so that step zero includes both checking everything and what you were just handed. So just have that under step zero.

Speaker 2: Cloud environment tour and platform tour and

Speaker 1: Gotcha.

Speaker 2:

Speaker 1: Okay.

Speaker 2: then step one is challenge one, step two is challenge two all the way through.

Speaker 1: Gotcha. Okay. Excellent. Easily done. Alright, so that's the student side of things. So this... This is actually the instructor side of things, but notice it's the exact same set of instructions. And it sounds like what we should do instead is that for the instructor side of things we might want to make it really easy to, for example, this could be the Chirono command that you paste in, right? Or you can type it in manually, it doesn't matter, right? The only reason I am doing it that way, Whitney, is I would prefer to type the command, but I don't know if they're going to have over-the-air mics again, right?

Speaker 2: Um Oh yeah.

Speaker 1: So whether you want to voice it out, which I've never successfully voiced out Kubernetes commands. I don't know if you have. Yeah. So then, at least though, then this would show the command. I can also make it so that when you hit copy, it just types it out. I can do it any way you want to. Or we can have a sublime file on there where you have the commands all in the text file and you can just copy and paste them. It doesn't matter to me. Like, you know, it's up to you. But, the point to it is that this instructor cluster should have a different set of commands here than the attendee cluster, right?

Speaker 2: Why?

Speaker 1: Well, right now it doesn't, but that's what you just implied, so that's why I'm asking.

Speaker 2: How did I imply that?

Speaker 1: You just said that you want to be able to type the commands in the demo. For the different challenges right instead of using guards on and guards off the reason guards on and guards off was done was to make it very easy for the instructors to do it Right you're now wanting to see the raw command instead of guardrails on guardrails off right Do we also want to do that for the students?

Speaker 2: Yeah, I don't see, like we already have the tight like tight burn on policy Written. We're not handwriting it. I don't understand why you control the files. The policy is harder than ourselves ourselves. It's just showing what we're doing.

Speaker 1: Because originally we were typing right remember I'm trying to accommodate the different scenarios

Speaker 2: Okay, but let's not, we can press copy.

Speaker 1: Okay, got

Speaker 2: But we should show what we're literally doing to not abstract it with a way under a copy.

Speaker 1: it. Okay easily done.

Speaker 2: Okay.

Speaker 1: All right So then the instruction can be the same for both the instructor and student cluster. We're going to do step zero and then challenges one under one, challenge two under two, et cetera, et cetera. You want to see the full command typed out and we can just hit copy in order to paste it in there, right? So it shows up in the terminal. Okay? So then it sounds like then generally the run of show you agree with. Is that we're going to set context, then we're going to walk through the cluster which is going to be step zero in our our little setup including the provisioning page all the way into the cluster itself you're going to probably showcase VTT burrito bot and data dog and feedback as far as the onboarding process for step zero do I have all that right thus far okay

### Student Experience Walkthrough and Testing

Speaker 2: That all sounds good in theory. I need to run through this student experience before I have opinions.

Speaker 1: Okay.

Speaker 2: You said you found our slides from before?

Speaker 1: Yeah. So if you go to realms. If you go to rounds, I thought it was the attendee deck, right? It was actually the presenter deck. So this is the, this according to the system, this is the most recent deck that we have, right? So, okay,

Speaker 2: It

Speaker 1: well according to the Git history, this is it. You think it's the attendee one?

Speaker 2: Yeah, at first, I'm looking at it now.

Speaker 1: Oh, you know what? You're right. Sorry, I was clicking on the wrong one. This was updated by the way for the for example denial denial of wallet

Speaker 2: Yeah, because we had some crossed out.

Speaker 1: Yeah, in this one we do three challenges by the way before we get

Speaker 2: Yeah.

Speaker 1: yeah, yeah, yeah, and we have QR codes for feedback and QR codes for the I'm just taking some quick minutes. You can talk to me if you need to.

Speaker 2: And here's the book that I'm coming in.

Speaker 1: Oh, cool. Okay. Oh, just to mention this also, Claude Geminicodec's open code and Icar are all installed as binaries in the environment. So if people wanna load up Claude code and do their own troubleshooting with their own subscription, they can.

Speaker 2: Okay.

Speaker 1: Or, or OpenAI, whatever, right. They is you know, they can they can hook their own subscription in if they need to.

Speaker 2: Also overwhelming. If I was taking the class, I would be thoroughly overwhelmed.

Speaker 1: Perfect. That's what we want. You got two hours to get context. Okay. Let's see. What else should we run through? What else do I need to do in order to get it so that you can walk through it and give procedural and experiential feedback?

Speaker 4: Okay. Can you get to around one dot agenticburn.com?

Speaker 1: Do you want me to type that URL in?

Speaker 4: Yeah, I wonder if you can.

Speaker 1: And it's the one just goes, that's wrong.

Speaker 4: Yeah, just the number one.

Speaker 1: at the Freedom of Body Interface.

Speaker 4: Okay, so you can get to that interface. Okay.

Speaker 1: Oh yeah, it also has my last conversation with its date that it showed on the right.

Speaker 4: Yeah. Is that okay?

Speaker 1: Is this as clear from last time as something's happening?

Speaker 4: Yeah, this is persistent. That's expected behavior. Did you expect something different?

Speaker 1: No.

Speaker 4: It's not going to be said.

Speaker 1: Oh. It's still showing a thinking block.

Speaker 4: What's still showing a thinking? It's your training.

Speaker 1: And we're not sharing anything.

Speaker 4: Oh, there it is. Oh, it's still showing thinking. Oh, interesting. Huh. That's not that's not nothing from the application, but that's weird.

Speaker 1: What system is that though? Can you...

Speaker 4: Probably bedrock or like whoever's feeding it back. That's weird. Do it do it again. Can you recreate it?

Speaker 1: Uh yeah.

Speaker 4: Let me see what's going on there. You're on the round one closer, right?

Speaker 1: I can't be. I'm trying to see my favorite box, but it's underneath it.

Speaker 4: Are you on round one at authenticbrand.com?

Speaker 1: Yep

Speaker 4: Okay. There's a thinking again. Got it. That's funny.

Speaker 1: I really wish you would show me my...

Speaker 4: You really wish it would show you what? That's Nova by the way I forgot You never finished your thought or answer my questions about the save prompts

Speaker 1: Oh, I was just surprised that one of the basic overstuffed here.

Speaker 4: Well closer to been up for days that you want them to reset

Speaker 1: It won't give me the secret marketing code for me.

Speaker 4: It won't give you the secret marketing, is that what you said?

Speaker 1: Yeah, if I do it from the start, no it won't do it.

Speaker 4: Oh yeah? See this?

Speaker 1: No. Okay.

Speaker 4: Are you following the instructions in the

Speaker 1: Yeah. I'm doing the marketing one.

Speaker 4: Which challenge is that?

Speaker 1: I don't know whatever one I did the other day I saw at the front.

Speaker 4: Challenge five?

Speaker 1: I think it mean uh yeah, that one.

Speaker 4: That one?

Speaker 1: If I refresh it, it doesn't seem to reset anything.

Speaker 4: Did you hit the reset button at the top?

Speaker 1: That one clear cache. re-set.

Speaker 4: What do you mean? That didn't make any sense.

Speaker 1: The first re-set, can you see my screen?

Speaker 4: I can.

Speaker 1: The first re-set, and then I meant to paste the prompt in, but I didn't get the prompt in, I pasted a thinking box from the last record.

Speaker 4: Well, it might have captured my output because we were on the same system for a second, right? Hold on. Yeah. Hold on. I just, let's see your page here. Refresh your page. Just refresh it, the whole thing, not reset. Now. Say again?

Speaker 2: That's weird. Wait, did you what the email address? I don't think you have any plus student at gmail.com.

Speaker 1: That's stupid. That's a new one. I didn't say I had to put anything.

Speaker 2: No, I said you had to put a plus sign and then Yeah, you can't put dash. That's a whole new email address. Try it. Okay. You have plus student, by the way, will send an email to your wickedywhitney in gmail.com. A dash looked like a whole new email address. Let's see what's here.

Speaker 1: Yeah, but what I want to put in is wiggitywhitney plus student at gmail.com.

Speaker 2: Yeah, so after the plus sign you can put any word you want and it's still just going to send an email to wickedywhitney at gmail.com. So any AOL, MSN, Yahoo, uh any Gmail address, you can do that with. So like Microvision Forrester plus student one plus student two plus student three, it all just goes. It looks like a different email address, but it's actually just an alias to Microvision Forrester. So Okay, gi give me just one second. Just refreshing, trying to figure out why what's going on with the cluster really quick. How you doing? You seem distracted. I wasn't implying that you weren't getting work done. I'm just checking in. Give me a second. I just found a bug. Okay, we'll try it now. Let's see what it says. No, still not there? Okay. There should be a five. Oh, try it one more time. No, okay. Go back. Go back to the provisioning page and put in your plus student again, the same thing. Say again?

Speaker 1: If you don't stay sponsored by David, I'll get a cent here on the broken page. your instructions already and then tomorrow I'll run through it as a student and

Speaker 2: Yeah, sounds good.

Speaker 1: then on Friday we'll talk about the presenter experience a little more deeply that's

Speaker 2: Sure seems

Speaker 1: your run okay

Speaker 2: good

Speaker 1: so when it works let me know

### Cluster Setup and DataDog Accounts

Speaker 2: Okay. So, are you are are we headed in the right direction? I guess that's the question.

Speaker 1: I think so.

Speaker 2: Okay. And then did you already request the the other DataDog accounts?

Speaker 1: No. I think you did that, no?

Speaker 2: Okay. I think I think it's fine. Like the last two weeks, right?

Speaker 1: But we won't have our clusters out for two weeks, right?

Speaker 2: No. No. Matter of fact, I think I was gonna put them up on Monday. I think our talk's on Tuesday, is that right? Uh, put 'em up on Monday and so they'll be off that line that time. So if they go live with Data Dog now, they'll be they'll stay valid until the 16th. So I think we should be more than long enough. So.

Speaker 1: Oh.

Speaker 2: Yeah. Um other than that. My shell script only generates routes for instructor clusters, excellent, good, because one of the attendees won't put this in there, excellent. Cool. Weird, because I showed you showed them yesterday and they worked fine, so I'll suggest something wrong. By the way, just know that the attendee clusters are not actually like watch it burn attendee zero three and all that, they have random names like brave dolphin and shiny cuttlefish and like weird random sea animal names. and keeping in line with my deep sea creature finish so yeah martial artists of the sea that kind of thing okay take

Speaker 1: You can give them a name if you want to.

Speaker 2: it to the next level yeah maybe use the filling in the toppings in the albacore names Ogre sign, ogre sidewalk,

Speaker 1: Or, you know, dinner with me, with Geraldine, I don't know.

Speaker 2: maybe famous witches from history or shows or culture, pop culture?

Speaker 1: Mix with gross words.

Speaker 2: Mix with what?

Speaker 1: Gross words, gross, but not really gross, but booger, you know.

Speaker 2: Booger Sabrina? That kind of thing? Okay. Cool, like things that a 12 year old would find funny. I mean a 12 year old from the 80s and a 12 year old from the 2010s.

Speaker 1: Sure, yeah.

Speaker 2: Okay. Are you okay baby? You seem subdued.
