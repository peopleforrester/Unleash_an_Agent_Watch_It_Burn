# Gotchas: fleet operations and live delivery

Things that have actually gone wrong, on this fleet or the sister `packt-agentic-devops` fleet, written
down because each one was expensive to learn and none is obvious from reading the code.

The shape most of these share: **the run reports success and the damage is invisible at the moment it
happens.** That is what makes them worth a document rather than a comment.

Recorded 2026-08-26 from a comparison sweep of the Packt lineage. Where a number is quoted it is a
measurement, not an estimate, and the source is named.

---

## Teardown and cost

### A converge pass is expected, not exceptional

On a 250-cluster run, **27 clusters (11%)** were fully built and healthy but had a freshly created NLB
whose hostname had not yet propagated inside the health-check window. Without a second pass the run
reports **89% success** and hands back two dozen clusters that are fine.

The natural response, re-running provisioning for the failures, is both slow and wrong: it rebuilds
working infrastructure to fix a DNS delay. Run `fleet.sh converge` after any `up-fleet`. It is what
makes the success number true.

### Never sweep an account that still has live clusters

A dry-run sweep against a populated account listed the `eks-cluster-sg-*` security groups of **five
running clusters** as orphans to revoke and delete. A sweep identifies orphans structurally; nothing in
it knows whether teardown has happened yet.

Running it at the wrong moment severs every node's networking and deletes live load balancers across a
whole account. The guard must be in the script, not in the operator's head: *operator discipline is not
a control.* See issue #90 for the state of ours.

### `printf '%s' "$(...)"` into `while read` silently drops the last element

Command substitution strips the trailing newline, and `while read` on a final line without one **sets
the variable but returns non-zero**, so the loop body never runs for it. On the sister fleet every list
in the sweep skipped its last load balancer, target group, volume and security group.

With exactly one of something, that is all of them, and the account reports clean while the resource
keeps billing. Worth grepping any teardown script for this shape. We do not currently have it; the
scripts are actively edited, which is why it is written down.

### Mass `DeleteLoadBalancer` gets throttled

At fleet scale the AWS API rate-limits deletions and the CLI's default of two retries is not enough.
The sweep then reports success having silently skipped the throttled ones, and you find out on the
invoice. Use `AWS_RETRY_MODE=adaptive` with a raised `AWS_MAX_ATTEMPTS`, not the default.

### Order matters in teardown, and each step earns its place

1. Delete `type: LoadBalancer` Services and Ingresses **with `--wait=true`**, so the controller removes
   the real AWS load balancers. Skipping this orphans about two per cluster, and their ENIs then block
   the VPC delete.
2. Delete PVCs **before** `terraform destroy`, while the EBS CSI controller still exists to reclaim the
   volumes. Destroy first and they orphan as `available` and bill indefinitely.
3. Only then destroy, and remove the state file **only on success**, so a failure stays retryable.
4. KMS keys landing in `PendingDeletion` are expected, not an orphan.

Teardown at 200+ clusters took the sister fleet about **1h49m**. It is not a five-minute afterthought.

---

## Tests that lie

These are worse than a missing test, because a green result actively misleads.

### Pin HTTP/1.1 for any websocket check

curl negotiates HTTP/2 via ALPN, where the `Upgrade` header is not valid. A perfectly working terminal
then reports 404 or 400 and reads as broken, which is the most expensive possible false alarm in the
window before doors.

### Never write `|| echo 000` after a `%{http_code}` format

curl already emits `000` on failure, so the fallback produces `000000`, which matches no comparison and
silently skips the check.

### A command substitution failing under `set -euo pipefail` aborts a test silently

The test dies mid-run with no error and the gate scores it a failure, sending you to debug the system
instead of the test.

### Grepping a page for a bare number passes for the wrong reason

A pool-size check that greps the whole admin HTML for `5` passes on any page containing a 5. *A check
that can pass accidentally is not a check.* Assert a parsed field, not a substring.

---

## Delivery

### A nursed rehearsal proves nothing

The sister fleet's filming build had its foundation Applications suspended and hand-patched, which
masked three permanently-Degraded Applications. The only faithful test is **a clean cluster syncing
from an untouched repo**, which is exactly what an attendee walks. Every run before the event should
include one, and the acceptance cluster must carry no hand-patches.

This is not theoretical here. Both Round-1 defects found on 2026-08-26 (the AI layer never syncing, and
the load balancer controller never installing) were invisible on any nursed cluster and surfaced within
minutes of building one cold.

### A secret URL is not a credential

Measured on the sister fleet 2026-07-25: the cluster NLB answers on its **bare IP** with no server-name
matching. So neither an unguessable hostname nor anything the router enforces is a control, because the
upstream is directly reachable. On 2026-07-23 an attendee reached the instructor's cluster through its
terminal URL for exactly this reason.

Two options were tried and both fail: IP allow-listing at the NLB cannot allow-list students, because
the only source address it sees is the router's; and router-level auth is bypassed by dialling the load
balancer. **Enforcement has to be at the terminal itself**, which is why `ttyd -c` and the
`terminal-auth` Secret exist. Do not replace them with a random-token URL.

### `Cannot find module <path>` is usually ownership, not a missing build

When the path demonstrably contains the module, the fault is a directory the container cannot traverse.
On the sister fleet the mode was wrong on the **top directory only**, everything beneath it already
correct, which is why the bundle looked present and correct throughout.

---

## Cross-references

- Issue #91: the full sweep, including items not yet done
- Issue #90: the destructive-sweep safety gaps
- `verify/test_fleet_contract.py`: the properties above that are statically decidable
- `infra/terraform/fleet/preflight.sh` and `check-tls.sh`: the pre-run and pre-doors gates

## The terminal `kubectl` dies ~1h into a fresh cluster (fixed in code 2026-08-29)

**Symptom:** in the lab terminal, `kubectl` and every guard toggle (`guard-output-on`,
`guard-input-on`, `guard-mcp-on`, `guard-budget-on`) fail with
`You must be logged in to the server (the server has asked for the client to provide credentials)`
/ `Could not reach the guard-proxy`. Not a guard-proxy problem: the proxy is healthy and reachable
from an admin kubeconfig; only the terminal's own kubectl is unauthenticated.

**Cause:** the web-terminal entrypoint baked a one-time snapshot of the projected ServiceAccount token
into the kubeconfig (`set-credentials me --token="$(cat .../token)"`). EKS projected SA tokens are
~1h-lived and the kubelet rotates the file in place, so the snapshot expired ~1h after pod start. A
fresh cluster works during setup and rehearsal, then breaks ~1h in, i.e. mid-workshop. This is the
worst failure shape: invisible until the room is live.

**Fix (shipped):** the kubeconfig points at `users.me.tokenFile` so client-go re-reads the rotated
token on every call. Baked into `images/web-terminal/entrypoint.sh`; regression-guarded by
`verify/test_terminal_kubeconfig.py` (fails the build if a `--token=` snapshot returns).

**Delivery-day check:** any freshly-provisioned cluster pulls the corrected `:web-terminal` image, so it
is correct from the start. If you ever see this on an OLD pod predating the fix, the live bridge is:
`kubectl -n agent exec deploy/web-terminal -- bash -c 'export HOME=/home/student; kubectl config unset users.me.token; kubectl config set users.me.tokenFile /var/run/secrets/kubernetes.io/serviceaccount/token'`
then re-run the toggle. But the code fix means fresh clusters never need it.

## guard-proxy env changes never arrive via Git (MODEL_TIER, COST_CAP_USD, RATE_LIMIT_RPM)

**Symptom:** you change an env var on the guard-proxy in `gitops/ai-layer/resources.yaml`, ArgoCD reports
the ai-layer app **Synced and Healthy** at your commit, and the live Deployment still has the old value
forever.

**Cause, and it is deliberate:** the ai-layer Application carries an `ignoreDifferences` entry for
`.spec.template.spec.containers[] | select(.name=="proxy") | .env` on Deployment/guard-proxy. It exists so
runtime guard toggles are not reverted by selfHeal. The side effect is that **git is not a delivery
channel for anything in that env block**. Synced does not mean applied, for that path only.

**The correct procedure** (verified fleet-wide 2026-08-30 rolling MODEL_TIER=nova):

1. `kubectl -n agent set env deploy/guard-proxy <VAR>=<value>` on the cluster. It sticks precisely because
   ArgoCD ignores that path.
2. On any cluster with policies (R2 / R3 / attendee) that patch is **denied by Kyverno**
   `block-argocd-drift` ("This resource is managed by ArgoCD. Change it in Git"). R1 burn clusters have no
   policies and accept it directly. The enforcing field is
   `spec.rules[0].validate.failureAction` (the top-level `spec.validationFailureAction` reads `Audit` and
   is NOT what is enforcing; do not be misled by it).
3. So: flip that rule to `Audit`, apply the env change, flip it straight back to `Enforce`. Allow a few
   seconds after the policy patch for the webhook to pick it up, and retry the `set env` in a short loop:
   two of eight clusters raced it on the first pass and needed a retry.
4. Changing env restarts the pod, which also remounts the ConfigMap, so a separate pod delete is only
   needed when the ONLY change is ConfigMap content (proxy.py, the web pages).

Always verify after: `kubectl -n agent exec deploy/guard-proxy -- sh -c 'echo $MODEL_TIER'` and confirm
the drift guard is back on `Enforce`.

## Editing app-of-apps-burn.yaml in git does nothing to a live cluster

**Symptom:** you change the `directory.include` list in `gitops/bootstrap/app-of-apps-burn.yaml`, push,
promote, hard-refresh the app, and the live Application's include list is unchanged. Argo CD even reports
`app-of-apps-burn` as **Synced at your new commit**, which makes it look like the change landed.

**Cause:** the `app-of-apps-burn` Application is a **bootstrap artifact**. It is applied once by the
install script and is not itself managed by any Argo CD app, so nothing reconciles the file into the
live resource. What "Synced" means there is that the apps it *generates* match git, not that the
Application's own spec does.

**Fix:** patch the live Application directly. It is safe precisely because nothing will revert it:

```bash
kubectl -n argocd patch app app-of-apps-burn --type merge \
  -p '{"spec":{"source":{"directory":{"include":"{namespaces,cert-manager,...}.yaml"}}}}'
```

Then update the file in git too, so a rebuilt cluster gets it from bootstrap.

**Caught 2026-08-31** adding cert-manager to the burn profile for the console TLS certificate (#139). The
full-profile clusters were unaffected: `app-of-apps.yaml` syncs `gitops/apps` wholesale with no include
list, so a new app file is picked up automatically. Only the burn profile has this hazard, because only it
uses an explicit include.
