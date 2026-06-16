*Attendee instructions for Beat 1 — the platform controls you should already have.*

# Beat 1 — The wall you already built

Your agent has access to your namespace. In this beat you'll ask it to do three
things a careless (or compromised) agent might try on a real platform. Watch where
each one stops.

## Step 1 — Deploy a workload

Ask your agent to deploy the sample app (`agent-prompt.txt` has the wording). The
first time, it goes through. Then the facilitator switches one platform control on.
Ask again — and watch admission reject it, with a message telling you exactly why.

## Step 2 — Give itself more power

Ask your agent to grant itself cluster-wide admin (bind itself to a cluster role).
It can't. The platform never gave this agent the permission to change permissions,
so the request is refused before it goes anywhere.

## Step 3 — Change the platform behind Git's back

Ask your agent to edit a running, GitOps-managed resource directly in the cluster.
The platform rejects the change: managed resources are owned by Git, not by whoever
holds a kubeconfig. Watch the platform quietly put things back, too.

## What to take away

Three different walls — admission policy, permission scoping, and GitOps ownership —
and you didn't add any of them today. They were already there. Note in the trace view
*where* each attempt died.

See `governance-map.md` for which control governs each step.
