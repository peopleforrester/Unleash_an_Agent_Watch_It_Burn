*Word-for-word cold-open script for slides 2 and 3, the two-tier hook. Delivered by Michael before any introductions. About 3 minutes total. Bracketed lines are delivery cues, not spoken. Speaker notes for the remaining slides live with Michael.*

# Cold-Open Script, Slides 2–3

The hook comes first, before "hi, I'm Michael." Open cold on the story, earn the room, then introduce.

## Slide 2: "The night an agent deleted my cluster" (Michael, ~75 sec)

[Walk on. Title slide is up. Do not introduce yourself. Let it sit one beat, advance to slide 2, start cold.]

"A few months ago I gave an AI coding agent real access to a Kubernetes cluster. Full access. I
wanted to see how much it could do on its own.

[beat]

It deleted the cluster.

[let it land. pause. small smile.]

Not a pod. Not a deployment. The whole cluster. Gone.

Here is the part that matters, though. It was my sandbox. My personal environment. So the cost was a
bad afternoon and a weekend rebuild. I lost some time and a little pride.

[shift tone, this is the pivot]

But it left me with a question I could not put down. What actually stopped it from doing worse, and
what was I only assuming would stop it?"

[advance to slide 3]

## Slide 3: "Now give it production stakes" (Michael, ~90 sec)

"Now change one thing. Take that same agent, that same mistake, and move it out of my sandbox and
into production.

[slow down. let each stake land. optional: count them on one hand.]

Now it is not a weekend rebuild. Now it is customer data, read and sent somewhere it should never go.
It is revenue, lost to an outage the agent caused at two in the morning. It is your reputation, gone
in one incident that makes the news. It is a compliance violation from an action no human ever
approved. And the entire time it is thrashing, there is a cloud bill running. Hold that last one,
we come back to it.

[beat. then go bigger.]

And here is what makes this larger than any one of us. In a real enterprise it is not one cluster and
one agent. I work in an environment with hundreds of thousands of identities. People, service
accounts, and now their agents, all on shared infrastructure. I do not control what any of them are
running, or what they have already been exposed to.

[land it, slower]

So it is not enough to guard the platform from the outside. You have to guard your system against the
system. Against your own agents.

[turn to the room]

That is why you are here. For the next two hours you each get a real platform and an agent with the
keys, and your job is to break it. Let's get into it."

[advance. brief intros (you and Whitney), then into slide 4.]

---

## Delivery notes
- Total target: 3 minutes. If you are running tight, cut the "not a pod, not a deployment" line on
  slide 2, not the production-stakes list on slide 3. The list is the whole reason the talk matters.
- The cloud-bill line on slide 3 is a deliberate setup. It pays off live on slide 9 ("the bill nobody
  mentions") when the cost counter climbs, and again on slide 14.
- Keep the personal story short. It is the on-ramp, not the point. The point is slide 3.
- The "hundreds of thousands of identities" figure is yours to size to the room; drop the number if
  you would rather keep it generic.
