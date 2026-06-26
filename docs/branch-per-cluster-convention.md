# Branch-per-cluster convention (and where it breaks)

ABOUTME: Why the whitney-* experiment clusters each track their own git branch, and the hard limit
ABOUTME: on that pattern: it is for a handful of isolated experiment clusters, never the attendee fleet.

## What we did

Each of Whitney's four clusters tracks its own long-lived branch:

| Cluster | Branch | Profile |
|---|---|---|
| watch-it-burn-whitney-r1 | whitney-r1 | burn |
| watch-it-burn-whitney-r2 | whitney-r2 | full |
| watch-it-burn-whitney-r3 | whitney-r3 | full |
| watch-it-burn-whitney-att | whitney-attendee | full |

On each branch, all 21 ArgoCD `Application` files under `gitops/` have their `targetRevision` repointed
from `staging` to the branch name. The cluster is bootstrapped from that branch's checkout, so its
ArgoCD tracks the branch. Push to `whitney-r2` and only that cluster reconciles, in about three minutes.
`staging` and `main` are untouched.

## Why it is right here

For a small set of clusters someone needs full, isolated control over, this is the cleanest thing.
Whitney gets a real GitOps loop on her own clusters without coordinating on the shared branch and
without any risk of her experiments reaching the workshop fleet. No new tooling, no shared-branch
contention.

## The critique (read before copying this pattern)

This pattern does not generalize. Its problems, in order of how much they bite:

1. **It does not scale.** Four branches is fine. Two hundred fifty attendee branches is absurd: branch
   sprawl, 250 copies of the same 21-file `targetRevision` edit, and an ArgoCD config per branch. The
   attendee fleet must NOT use branch-per-cluster. It uses one branch (`staging`) for every attendee
   cluster, and per-cluster identity comes from the cluster itself, not from git.

2. **The branches diverge from staging and cannot merge back.** A `whitney-*` branch is a point-in-time
   fork. As `staging` advances with real workshop work, these branches go stale and do not receive the
   updates unless someone rebases or cherry-picks. They also cannot be merged into `staging`: the only
   thing that makes them special is the `targetRevision` repoint, and merging that would repoint the
   shared branch at a dead experiment branch. So they are throwaway, not feature branches. Treat them
   as disposable: delete and recreate from `staging` when they drift, rather than maintaining them.

3. **The repoint is an invasive, noisy diff.** Rewriting 21 files' `targetRevision` buries any real
   change on the branch under mechanical edits, which makes a genuine experiment hard to read in a diff.

4. **There is a better pattern for fleet scale.** An ArgoCD `ApplicationSet` with a cluster generator
   expresses "every cluster runs this app, from its own revision/values" as ONE definition, with the
   per-cluster value coming from a cluster label or a generator parameter. No branch proliferation, no
   21-file edits. For one-off experiments where someone wants to hand-edit manifests, a per-cluster
   kustomize overlay or a values override is lighter than a whole branch.

## The rule

Branch-per-cluster is for a handful of named experiment clusters whose owner wants total control and
total isolation. It is never the mechanism for the attendee fleet. The fleet tracks `staging` (one
branch, many clusters) and the auto-bootstrap in `fleet.sh` points every provisioned cluster there.
If you find yourself about to script the creation of more than a few of these branches, stop and reach
for an ApplicationSet instead.
