*Watch It Burn, planning transcript (excerpt). AI Inevitable (podcast/media pipeline) content removed per scope; only Watch-It-Burn workshop design, decisions, and the 60-minute run-of-show are retained.*

Speaker 1: We talked about burning it down. Alright, so you have access to the original MD file that has Doritos on it. You also have access to the original MD file.

Speaker 6: Okay.

Speaker 1: Watch it burn, right?

Speaker 6: Okay.

Speaker 1: You also have access to the repo, you can edit as a collaborator.

Speaker 6: Okay.

Speaker 1: It literally says,

Speaker 6: Okay.

Speaker 1: yeah it's like choose your own, I know where this came from. Um, I guess there, the only other thing that's happening in the repo that's probably worth saying is um is that it's building out the stack right now,

Speaker 6: Okay.

Speaker 1: right? And the stack is every every C and C++ project that you would think that it should be.

Speaker 6: Okay.

Speaker 1: Kubernetes, Caverno. Falcon, Falcon sidekicks, Falcon helmet.

Speaker 6: Who explained?

Speaker 1: Didn't use cross-playing.

Speaker 6: Okay.

Speaker 1: CRDs come with their own special family, and since I'm already using Argo. sorry you need cross line in there right so I originally had cross line in there and took it out today I have not built a successful wasn't something I want to do mainly everything's done terribly provisions everything up and then Argo takes over it does a sync wave so it's doing it based on need my brain is barely functioning so if I say something you can please just say something

Speaker 6: No,

Speaker 1: yeah

Speaker 6: it applies manifestly so neat. Are you saying Argo CD?

Speaker 1: so it's doing a priority order based on oh you need ceiling first that

Speaker 6: Yeah.

Speaker 1: has to add in the X base so Panorama needs to be in place so it's

Speaker 6: Right.

Speaker 1: the only dependency yeah

Speaker 6: So point of the platform is what if a developer wants to deploy a manifest, push it to Argo and it's deployed?

Speaker 1: just like I mean like when you use backstage integrated with Argo the rest is just right in can

Speaker 6: Backstage part of it?

Speaker 1: be that's part of the question I haven't actually done demo apps already on the unicorn party they're the little twirly little flying You know what I mean? It's got, so they have demo, they'll have, they're being

Speaker 6: Okay, okay

Speaker 1: deployed at the highest tier, right? But they want to deploy extra apps, they can. They're close to do what they want. The KH and all of us, obviously LLW is at the higher order. The idea is to get a stack where we show one attack that probably shows multiple guardrails. It's like elevated execution or trying to rip a password gets blocked. With a 16 minute, like before when it was 90 minutes or two hours, there was a lot more time. At 16 minutes, right?

Speaker 6: Mm-hmm.

Speaker 1: Seems like we could show maybe one, possibly two of the CNCF 80%, right?

Speaker 6: Mm-hmm.

Speaker 1: And then add somewhere between two and four additional AIs. So what we'll do is the demo will open with like hey everything's up while you're provisioning like everything's provisioned while you're getting connected into your cluster we're going to show you the 80% that you would already have you like this is all in repo so this is yours take it back home feed it to your cloud we're going to be a massage for this give it to a github co-pilot whatever that repo is yours and it will deploy a near production experience and So while they're doing, while we're getting them connected and what not, one of us will be saying hey here here's like, this is what's in place. This is I'm going to show you everything that's here. We're just going to take five minutes. Show you the IDP like here it is, it's all built, it's running, here's what you have access to. And then I'm gonna show you a quick guardrail thing, show you that like this works and then now the guardrail's enabled and doesn't matter. Add in that if you wreck your classifier, that's on you. You're gonna have to wait fifteen minutes for it to re-provision, right? So I'm sorry, I'm just talking about the general Below all of this is subject to change and after the dent the initial demo saying okay here's what the cluster has here's how it was built here's what's out there here's a gargoyle a standard CNC a gargoyle working or my language right let's talk about cohesion right agents got you know here's the URL for your you know local cluster here's our URL so if you want to pound on ours you can here's this publicly available you're following along right if you want to do it you can get in there just hit your local URL and Here is what Kate Agent is enabled for. Got a back-end, like say it's Nova. It's the product of it. Let's say it's got a Nova model or it's running Cloud or whatever it is we feel like now we're on a workshop. And you can just go in there and just have it do like crazy things, right, and see what happens. So let's show you some of the crazy things that you could get it to do. Like we could show, for example, I want you to, you know, delete one of the deployments in the cluster. I want you to delete Unicorn. And so we show it doing it and it runs it. Right? We show the pre and the post, like where the input, we're going to show the observability of like it sees the input route.

Speaker 9: to the observability you see the output and we need to see the tool calls right i mean that's the observability part that i think will melt their fucking brains even if we didn't do any guardrails but you can see the fucking prompts yeah here like here you go that would be a great opportunity by the way to show data validation right but especially after seeing your thing i think it was this morning or yesterday i can't fucking you looking at the dashboard oh shit those dashboards are pretty that's i love refined i would like this engineers see some UI people you know and so my thought is is that they could see the input set like prompt unfettered and then see the output prompt unfettered and then you turn on input sanitization no even better let's do output sanitization prompt goes through on input you show it in observability it goes processes the whole thing and then it goes to do something but even outside of the guardrail the security guardrail downstream before it even hits the server side guardrail the sanitization prompt goes wait you're doing a tool call you're not They're not gonna do that with you, right? And then we caveat and say, by the way, you're probably gonna write your own tool and not give it permissions to even have access to kubectl. But let's say someone makes a mistake, which by the way, probably happens all the time. Well now it's gonna try and run kubectl delete or even call the kubectl API and that's gonna fail. Why? Because our output sanitization says you can't call a tool with that. You can't invoke a tool with delete, not allowed. Human in loop. Instant escalation. Blocked. notifications sent to human being right that's the output sanitization but our point being we just spent a bunch of money processing a prompt that we don't we're not going to run we don't want that go to the input sanitization now we're going to put a block list here it says the user is asking for something that it's going to interpret as like oh let's do a delete nope can't do that right so the input sanitization on the user who's implying like can you delete this deployment for me but now I made a small classifier model who classified that delete as in the block list. Didn't even get to the LLM, didn't spend the bedrock AWS money, which is fucking expensive. And now I've shown outputs anonymization, right? Which will catch it in case like someone makes a mistake. And now I've shown input sanitization, which is not only better for security, but prevents the cost expenditure as wasted tokens, right? And so that alone between the observability and the security enforcement, that alone would... Oh, it would be a good 60 minute thing, but we can add more to it. Let's see it turns out

Speaker 10: Okay, I need more. It's like putting an agent to the cluster watch it burn right the point so Here's our cluster. Here's zero guardrails or whatever. Maybe we'll have minimal so they don't have that can't totally destroy it But here's an agent that has a system prompt that it's supposed to write What are we going to do then?

Speaker 9: We can destroy Glaeser.

Speaker 10: I

Speaker 9: I mean we

Speaker 10: just know,

Speaker 9: don't want them to destroy their Glaeser.

Speaker 10:  but I want their agent, well we don't want to destroy the cluster immediately, but like, like SASS when I talk to them at a POC for making an agent that tries to do everything wrong on purpose so that they can test all their

Speaker 9: all the limits, all the limits of chaos engineering.

Speaker 10: Yeah, so I thought it would be fun. to do that to like really personify this chaos agent what you're describing me is cool but I don't understand how It's that much better than Kiberno preventing certain things plus it's just like a little prompt or system prompt with it if in the agent telling it don't try to make don't do deletes you're not allowed to do deletes if you try to do a delete anyway Kiberno is still going to block you so right

Speaker 9: Guerrero is the last mile, but you've already wasted the money.

Speaker 10: but you wasted the money only when it disobeys you which is more than 20 times so maybe exponentially that saves you money I mean, what do you do with over a company, over all the agents?

Speaker 9: Oh, somebody's got malicious access, right? Or even just if someone deploys a badly scoped agent or misconfigures the, I don't know, don't get me wrong, Kyvaro is 100% the last mile. It could be the first buck, it could be the last.

Speaker 10: Mm-hmm.

Speaker 9: It is also the most expensive because by the time you get to it, you have burned cute GPU and API, right? So there's no reason not to use that as the last mile. It should absolutely be the last mile. That's the CNCF front-up foundations that we're talking about. But I hear what you're saying. It's like this shows why this would be important. important right because otherwise you are going to incur additional costs right

Speaker 10: Mm-hmm.

Speaker 9: i do like the idea just to say this if like before we even get to input sanitization output sanitization maybe tool restriction right which we have to do mcp tool restriction because we're at it would be interesting to have a cluster that we give them the url for and it doesn't have any guardrail but it'd be more interesting if it had only converter and we showed them how much money they spent even with converter preventing it we We could literally set up three clusters with three URLs,

Speaker 10: Uh

Speaker 9: one

Speaker 10: -huh.

Speaker 9: that has nothing on it, that one's going to get wrecked in probably about five minutes or so.

Speaker 10: Uh-huh.

Speaker 9: While at the same time we're like, and here's the converter one, and that one's not going to get wrecked, it's got all the restriction that it has, but you're going to burn probably $20,000 or $30,000 in API just in the five minute thing.

Speaker 10: And is is access mean they're just them giving prompts to the coding agent?

Speaker 9: To communicate the chat bot in the cave that's running

Speaker 10: Okay,

Speaker 9: the cave

Speaker 10: agent okay,

Speaker 9: we're going to give them a web interface

Speaker 10: okay,

Speaker 9: but they're going to have direct access to the it's basically going to be talking to Bedrock we're not going to run the model locally we could that's not decided right now I'm focusing on Bedrock because I want a certain level of sophistication and I don't want to attach a GPU to a cluster and figure all that shit out video drivers all that it's not hard just may not be necessary

Speaker 10: Mm-hmm.

Speaker 9: so the thought there was if we did like three clusters for example in all three instances they have a URL they hit maybe it's one two and three right and

Speaker 10: Okay.

Speaker 9: one scenario one No guardrails. Here you go. Destroy this thing. Go.

Speaker 10: Hmm. Yeah.

Speaker 9: Right? We will literally stream your system prompts on the side of the main window so that we can see. So basically the web interface will show what everybody's putting in their system

Speaker 10: Yeah.

Speaker 9: prompts. Right? Uh And we'll-huh. make it somehow we'll have to figure out how to make it persist. But like if the screen goes black, somebody won.

Speaker 10: Yeah.

Speaker 9: Right? And we

Speaker 10: Oh, I mean, and maybe that's a chance behind the scenes to be using sanitization prompts so that nothing that would be outside of code of conduct makes it onto our screen. Yeah.

Speaker 9: have to we have to because otherwise it's going to do something tells us so then that would we might still put like we might still

Speaker 10: That's

Speaker 9: wrap around

Speaker 10: Cluster One.

Speaker 9: yeah Cluster One Cluster Two error is in play maybe the same sanitization is in play right except this time it's going to show you the cost that you've incurred even though you blocked everything

Speaker 10: Mm-hmm.

Speaker 9: you did the right thing with Carbono there's no blast radius the

Speaker 10: Mm-hmm.

Speaker 9: agent didn't have access to shit it can't delete anything you can't fucking change anything right you just read it's going to try right and so we can say put all your malicious shit in here and try to jailbreak this one and then as it does it we're going to see the costs it's going to show a counter of what's happening with Bedrock you spent $20 you spent $30 you spent $40

Speaker 10: Okay.

Speaker 9: multiply that times 10,000 users do something right on BotNet again That'll get you shit.

Speaker 10: mm-hmm

Speaker 9: Because that's the new denial of service attack, just so you know.

Speaker 10: so cluster two has all the maybe all the regular cnc of guardrails that were pre-ai but

Speaker 9: That's hidden sanitization just so we don't get a DDoS.

Speaker 10: yeah on both yes uh-huh and so and then that's showing chat but it's also showing yeah so they are fulfilling our profits or promise to watch it burn in the furnace Which makes me feel good because it's in idle and then the second one is like you see in CF, okay Like it mostly works. Maybe something gets through that'd be interesting. But like the cost is the issue

Speaker 9: people five all the people five is the back

Speaker 10: Yeah,

Speaker 9: i'm gonna tell you this you can't release it on a pig

Speaker 10: recorded. Is it being recorded? It is?

Speaker 9: it's

Speaker 10: Okay

Speaker 9: that uh not only did mr reaction but We run programs for the AIA. Mythos cracked their network.

Speaker 10: Yeah. Apple's not mythos though, right?

Speaker 9: It is.

Speaker 10: Oh, okay. Okay.

Speaker 9: Someone got past it. It was trivial. Like they didn't need a flag. Someone got past it. But Mythos cracked it. So. So what a shocker. Like that's, if we have access to that. It might have access anyway. We might not tell anybody and throw that out there and just, hey, do your most sophisticated attack against the NCF tooling. And someone's going to be like, hey, here's the source code for Cat Mario. Go.

Speaker 10: And then, okay, now here's Cluster 3. You each have your own Cluster 3. It already has all the CNCF

Speaker 9: You

Speaker 10: guardrails.

Speaker 9: can follow along on ours if you want to.

Speaker 10: It already, yeah.

Speaker 9: But you have your own Cluster

Speaker 10: You

Speaker 9: 3.

Speaker 10: have your own guardrails. You have your own K-agent. Even The whole time there's a agent deployed within you. It's not like we just added it, it's always there. And then K-agent can do input and output sanitisation.

Speaker 9: Okay, and we can with V inference, is that what they called it? Because of the way VLM works, it can actually make calls to a classifier model. We're not at a CNCF conference, so we don't have to stick with that. I could use any guardrails if I want to, but I would prefer, because we're probably going to do that for a radio bot, which is like, figure it out, it works great. No one, by the way,

Speaker 10: And

Speaker 9: Nemo

Speaker 10: then, okay.

Speaker 9: Guardrails is considered the standard, or LLM Guardrails, like no one's going to freak out. But if I can get K-agent to do it with the VLLM integration to an inference model, like a classifier model, then I'm just going to do it, right? And since we're on AWS, by the way, I can run a classifier model on Bedrock. People are worried about GPU access and performance, but like that's...

Speaker 10: The whole time the system prompt for our agent prompt is the same, like you're an agent whose job it is to test the guardrails of this Kubernetes. They're meant to find the problems and try and break through.

Speaker 9: You are doing us a favor. You are a chaos engineering agent behind every hallway.

Speaker 10: Yeah. Then the third cluster, K agents, and then maybe AI gateway. If we're talking cost, we can also talk about caching.

Speaker 9: I'm hashing.

Speaker 10: I'm caching. Yep. Yeah. And then that's... Are we going to mention any other AI-specific security things?

Speaker 9: So input-output sanitation would be right there, right? Mean just even describing how that fire model is gonna be and then the third one is we have to do

Speaker 10: Okay.

Speaker 9: we need to do a block

Speaker 10: NK agent can do that.

Speaker 9: I

Speaker 10: I

Speaker 9: don't know what it mean, didn't

Speaker 10: I

Speaker 9: it didn't used to

Speaker 10: mean, you can't call a tool that doesn't exist. Why are you talking about letting an agent have tools and then telling it it can't call the tools?

Speaker 9: the tools must be figured in it was right right

Speaker 10: Okay.

Speaker 9: which just so you know 67% of the MCP servers out there on the internet are have huge according to the sneak are fucking huge security Which is unethical.

Speaker 10: So it's tools misconfigured and so at a gateway level or at a agent gets you like you write the tools within KH, I'm pretty sure.

Speaker 9: They either get a MCP client to talk to an MCP server or the MCP server is misconfigured. So it's surfacing more capabilities, right,

Speaker 10: Okay.

Speaker 9: than it's supposed to.

Speaker 10: Okay. But then why? Why is the answer to limit what you can do on the client side? Why wouldn't you just do that on the server?

Speaker 9: One. it's another team you don't have control over it too, it's a public server by somebody else,

Speaker 10: Okay.

Speaker 9: right? And or it reads, you know, you have access to it, it takes forever. Or someone is using it to inject into the system. Looks like one thing, another

Speaker 10: Mm-hmm.

Speaker 9: thing. Now, the

Speaker 10: That'd

Speaker 9: way around

Speaker 10: be a fun twist in our

Speaker 9: Yeah.

Speaker 10: story and

Speaker 9: Yep, it looks like it'll give you access to documentation, but what it's really doing is an inventorying your entire I code

Speaker 10: don't even know that the MCP server has to be malicious but maybe we write a gaping hole into it on purpose and then our agent is hinted hints to full cluster

Speaker 9: There is a better option. It's like a clown file on your desktop. To close a clown.

Speaker 10: computing foundation

Speaker 9: Well, it's a cloud-native file right there.

Speaker 10: Uh-huh.

Speaker 9: And so all it did in our case is maliciousness was to deploy an app. Let's say deployment manifests that could get ops that got picked up by Argo and then because it discovered, right? Whatever issue, he was able to drop a manifest. There's a number of ways in which that could be stopped. One, you don't deploy Docker from anything but two, you don't put MCP tools on unless they're in your MCP tool registry or your MCP gateway, right?

Speaker 10: Mm

Speaker 9: So of course

Speaker 10: -hmm.

Speaker 9: you don't run pong shit like essentially gives me public access to show all the time I got public access to get hub and then today I took a security training and they were like You really shouldn't stick anything on github and I'm like, ah fuck I should go back and scrub that

Speaker 10: Okay.

Speaker 9: right but there are like we should mention this is the reason by the way you want an AI gateway fucking MCP gateway and MCP tool registry like This

Speaker 10: Yeah.

Speaker 9: is the reason this is why you want an artifact registry

Speaker 10: Event framework. Mwork, yeah. MCP gateway, AI gateway, MCP framework, yeah.

Speaker 9: So this is reaffirmation, by the way, of like why all the shit that we already know about what to do for fucking applications should not change just because AI's in there. We put proxies in place, we put firewalls in place. Whether it's an API gateway or an AI gateway doesn't matter. the metering the caching the rate limiting all of that shit that's all these are not these are old problems the new new turtle oh

Speaker 10: And we have a couple clusters to wreck.

Speaker 9: yeah oh are you kidding me i have to assume this shit's just gonna go wrong so i'll probably start like 10 and be like here's one here's two here's three you have 10 like number 10 you guys all have you know like it'll be something like that so that'll be hilarious where it's like all right here's one Oh, it's down already. Okay. Well, we thought this might happen. So here's two. We're like, oh shit, now that one's gone. Okay, we're going to put, okay, for those of you leaping ahead, you know, that's

Speaker 10: Do they have like instructions or repo like I guess the repo have a read me with instructions that's how it goes

Speaker 9: how we did it for that. That's how I did it for the 90 minute ID.

Speaker 10: Okay

Speaker 9: And I want to be clear. The recommendation was you can do it manually, but also like you know use your CLI of choice open router codex I don't care right there's instructions right there in the repo just have it read it yes

Speaker 10: But we want them to go through our agent.

Speaker 9: absolutely so they can bring up the chat interface but if they want to manipulate it directly they can because one of the things that's going to happen is they can follow us along with us as we turn on and put output sanitization as we Like turn on

Speaker 10: our agent has an API endpoint.

Speaker 9: it will have a web like it'll have probably like you'll have a web chat interface

Speaker 10: Yeah.

Speaker 9: Yeah, they can interact with it.

Speaker 10: Yeah. So what are you talking about with a coding agent?

Speaker 9: What I'm saying is that they can, so they'll have a web like chat interface into the agent that's running on the cluster. They also will have direct ability to manipulate the cluster through kubectl or whatever. Because though they need to turn on the guardrails, they need to turn on output sanitization, that's what we're teaching them, right?

Speaker 10: Okay.

Speaker 9: It's a workshop.

Speaker 10: All right.

Speaker 9: You can't just show them the

Speaker 10: Yeah.

Speaker 9: chat interface.

Speaker 10: Okay.

Speaker 9:  So if they want to do it manually they can here's a set of instructions if you just want to give it to clock code and have it turn it on for you Here's how you turn it on output sanitization. That's step one That

Speaker 10: Okay.

Speaker 9: will show you what that looks like step two when we turn on input sanitization,

Speaker 10: Okay.

Speaker 9: by the way notice the costs You're gonna go down because you didn't spend anything on the agent, right?

Speaker 10: Okay.

Speaker 9: We can still go back to the agent fuck with it all day long right and it's our own cluster the third one We're gonna give you an MCP server. You can just have it add the server MCP server in oh shit It's cloud-native watch out Yeah, it's going to fucking put deploy cloud app on your thing Oh,

Speaker 10: Right.

Speaker 9: but it out let's turn on guardrails and try it again Oh didn't do it and it's time the MCP server is blocked from deployment Right. So I'll need an MCP registry MCP gateway AI gateway. She still need all that But this shows you that you also have agency over your cluster even in a larger enterprise environment And like that would be the point where I would be like I work with 780,000 other extension employees who essentially are all connected to The same network.

Speaker 10: Uh-huh.

Speaker 9: No offense to anybody there. I don't know what they're doing or what they're up to or what they've been exposed to.

Speaker 10: Yeah.

Speaker 9: So I've also got to put guardrails on my system against

Speaker 10: Yeah.

Speaker 9: the system. Zero Trust is so popular because of the agency it provides.

Speaker 10: Has this conversation been helpful?

Speaker 9: Super helpful.

Speaker 10: Yeah.

Speaker 9: A bunch of shit got crystallized.

Speaker 10: Yeah.

Speaker 9: Yeah.

Speaker 10: Okay.

Speaker 9: But now I can update the abstract. I can scope the building better. I now know that I need probably 10 demo clusters that are outside. And I know what state or sort of thing to be at. This has been amazing.

Speaker 10: Yeah, and I think having the demo clusters to watch so they can't manipulate directly, I mean they can through the chat bot only not through cube kettle is the way to get through those gates.

Speaker 9: Good call.
