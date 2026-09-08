<!-- ABOUTME: Routed transcript (My recording 193.mp3), matched to this repo on 2026-09-01. -->
<!-- ABOUTME: Auto-routed because: 1 section(s) of this conversation match the Unleash_an_Agent_Watch_It_Burn topic. Raw diarization; speaker labels are approximate. -->

# Mike Conway - Accenture LearnVantage IST Lab Feedback & Automation

_Routed from the transcription pipeline on 2026-09-01. Source: My recording 193.mp3._

---

### DevOps Days Portland Talk and Agentic Burn Platform Demo

Speaker 2: Alright, where's the desktop? We're not seeing any window.

Speaker 1: Oh sweet. Oh then that's negative two birds with no stones. So perfect. Actually that's not gonna help you here. Let's uh get off my cloud window and let's actually click the right panel. You would think that I use technology on a daily basis, but apparently I don't. So uh, so this is this is the Dallas Day program and so I'm giving a talk with a friend of mine named Whitney Lee and she works for Datadog and we're doing uh it's it's uh uh build a platform unleash an agent on it watch it burn right and so this it's the application is called Burrito Bot which is why there's a weird hand-drawn burrito just so you know Whitney is really strange and likes to hand draw everything so I just let her do whatever she wants because uh People love it. The reason this is interesting is that this is a copy of the talk that I did for AI Engineer World Sphere back in June out in San Francisco. And so, and I probably out talking once a month. So the platform that's being provisioned is an outgrowth of that concept because I didn't want that to fall on Alex's team, right? Because this is not an official product. And so Alex was gracious enough to give me Well, and I had one, but Alex is aware that I have an AWS account, and as long as I don't abuse it, he's fine with me doing whatever I want, right? And so I have an AWS account, obviously for development purposes to be upfront, right? So what happens is that on this platform, I developed this thing, and it's provisioning dot agenticburn.com, because watching eight, like... unrelation agent and watch it burn. So I bought the domain name agenticburn.com, agenticburn, and I put all my little domains there, right? So what happens is that when a student comes and joins the workshop, we had 250 attendees in the last workshop in San Francisco, which was crazy, honestly. And matter of fact, we didn't find out about the additional 200 until we were already there. And the reason this is significant is that if Whitney or I type in our email addresses and what will happen is that instantly since we're both We're both admins, we get an admin page, right? If someone else types in, and they have to be either a FedEx account, uh a um Accenture account or a DataDogHQ account, so let's say I do michael.arnold4ster@accenture.com, assuming by the way this is assuming everything's functioning, I have no idea what we're I didn't even know I was doing this, so I have no idea if any of this is actually still up or working. What happens is that this is what an attendee sees. Attendee instantly goes to a landing page, right, and then they can go straight to the lab or they can just click it and open it. And what it does is it is password protected, right? Passwords are usually pretty simple. This is just to stop some random stranger from grabbing the URL off the screen and doing the thing, right? That's a little bit of a nightmare, isn't it? So... Notice that up here, the instant thing is that we're in a VTT, right? So we're in our browser. I'm in a virtual terminal. This is probably not new to any of you if you've been to GoCloud or O'Reilly or I think I saw even Audacity has it on one of their pages. They have a VS Code embedment, right? Do you guys have a terminal embedment as well?

Speaker 2: Yes, yes we do.

Speaker 1: I want you to know the labs are really hard to find on Audacity. So the only thing I found as far as the Venus code path, I haven't even found any other labs. So I guess my point is that you're here at a terminal, this is all the instructions, and things can get copied in. And it's connected to a real cluster, so just so we're clear, it is connected to a live cluster. So all of this was just provisioned by me. But the thing that's relative to the suggestion box, right? is that there's a feedback button and the feedback button instantly just gathers feedback at any point in time that anybody wants to do it and they can fill out anything they want or nothing they want they can come down here and fill out something and just send feedback none of these are required fields right now it does gather which cluster it came from so that if there's a specific issue about that cluster in question we can go back and mine the cluster for the particular issue all the data by the way is teed out of the cluster just so we're clear So every single command they run, everything they do. And I actually have a feature to add behavior analytics. Anything they click on, anything they hover on will also be captured, right? I know that sounds weird, but like you can tell a lot by what someone does on the page, what they're having trouble with. Like for example, if they come back here, and I've actually seen this live, which is why I'm saying this. They come back here and they're like, hey, I don't see where challenges one, two, three, and four are, right? But I see challenges five, six, and seven. So the next thing you know, they're over here like clicking in. You know opening up everything and then the next thing you know I get a feedback loop that says hey I can't find challenges one two three and four I immediately know without them telling me that it was probably an interface problem because I saw them click through every single Karen they didn't and then they opened a feedback thing and said hey so I can actually find out what the user is doing so my initial suggestion wasn't all of that complication because that's not where you start my initial suggestion was just have a feedback button right just have a feedback button let it take them to a single blank page that says fill in everything you want i promise this will be read this is done anonymously go right and if you want to talk to us you can put your email in and we'll contact you right Now, again, I'll try to put a capstone or whatever if it's going to be wide open, but honestly most students are, if it's controlled access, you can just limit it to that last raise. But that was the initial suggestion. The other suggestion, which probably has less to do with you all, is that um Dan and I were talking, Dan Groh, oh my God, I can never say his name, Dan Groh and I were talking and um we were probably gonna embed a feedback button in the s in the presentations and the slides as well. So if the students were reading something they could click a feedback button in the lower right-hand corner, 'cause w I don't you you really all probably know we're doing reveal.js as our I HTML is our primary delivery. written method, not PDFs or whatever. So we were gonna mimic whatever the laptop team did, make it look exactly the same, have it give the same look and feel, and wherever it took them, take them to a similar place, they gather feedback. The only difference is that whereas this would catch what's going on with the labs, that button would catch what page they're on in our Word document. Right?

Speaker 2: Mm-hmm.

Speaker 1: It would say they're on page 12 of blah blah blah blah, right? So that was the up the first suggestion is having a feedback box. That's for the students. There's a second suggestion box um that might

Speaker 2: So

Speaker 1: just go ahead, please

Speaker 2: as Christian here, so the feedback you would like it in the live environment and you know that the students can right now do this to the board

Speaker 1: Mm-hmm.

Speaker 2: and And from there they launch the LAN, launch the audio, launch the audio, etc. So you will like that feedback at that point or you will like it more like in the LAN environment.

Speaker 1: So I would say honestly you couldn't go wrong with having a little a little thing that says feedback at every stage My only ask is that if you do that just make it the same format So if they click on Reggie and they're in Reggie and they're like I can't find what I'm looking for click Right? I just want to give you some feedback right now. They're going to talk to the instructor, but that also would allow the instructor to log in click feedback and say hey I had a student who came here into the thing for this particular class and couldn't find the thing and just put it in the same place make it the same make it the same color give it the same outputs so that way it just encourages them to leave feedback at any point in time We don't really get good telemetry except informally from, at least from the instructors. I don't know on the audacity side of things whether you're tracking behavioral analytics, but also I don't know what your feedback mechanisms are. So let me pause there. One, is there any more questions? And two, do you have a feedback mechanism for audacity already?

Speaker 2: It's a question mainly to Alex now. So now, as of today, we have zero mechanisms for learners to provide feedback to us within I-LT today, yes?

Speaker 1: Well, that's IOT, but I'm asking about e-learning, sorry.

Speaker 2: My understanding is that we have a relation that is drawn by operations. So I think there's something in Reiki because that's a part of operations that we don't touch. I'm not sure exactly what haven't worked. But my understanding is that when pre we receive after the class an evaluation report, but the little global how is the experience, how we see it, how we're sad, it's just like

Speaker 3: Yes, this is an overview.

Speaker 2: either about the entire experience. Uh one key to your question that you just gave, uh we have severed like we have this as well, like we have the evaluation survey which is about your entire experience and this is how we calculate the NPS and it's it's uh it's a must fill and submit survey before graduation. So you cannot graduate from a course or another degree unless you do that survey and it's mandatory. We have other surveys along the journey that are not mandatory that they that they can fill at its option. The other thing is we have the the persistent button in the glass form that says like send feedback and that button let you have to choose like which part of the page that you are porting feedback on. If it's a text item, it has the list of types of feedback that you can deliver about a text item. If it's a workspace, it's different. If it's an image, a video, so it depends on the what are you reporting. where they feedback on. There is a specific list, you you choose of that list, then you write your comment what's what you're facing. This book this string sit out

Speaker 1: to our deal and we call it atom level feedback.

Speaker 3: Yeah, okay.

Speaker 1: At the end of every lesson, when you finish the lesson, you see courses are like each course has several lessons. At the end of every lesson, you click next, you have a pop-up window that says pick a smiley face from one to three whether you're happy, neutral or sad and an optional comment.

Speaker 3: Can I, can you show me a lab, like a VTT lab like this one?

Speaker 2: Do you have quick access to that?

Speaker 1: I can show that. I think I am opening up.

Speaker 2: I think that's great by the way. Sorry, it's a mention. Yeah.

Speaker 1: There will be also one more question that we asked that do we capture any telemetric data? We capture which pages the students spend the most time on. I will share my entire screen.
