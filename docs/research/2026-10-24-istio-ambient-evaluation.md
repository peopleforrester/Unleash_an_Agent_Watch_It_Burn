<!-- ABOUTME: Evaluation of Istio ambient (#238): whether the five mesh apps can carry a real challenge, what
     ABOUTME: dropping them saves, and what enrolling a namespace would break. Static, from git and Istio docs. -->
# Istio ambient: keep it for a real challenge, or drop it? (#238)

Michael, 2026-09-05, from the #236 audit: *"evaluate individually whether this could be useful rather than
assume it is dead weight."*

The issue asks three things: is there a challenge worth building on the mesh, what does dropping it save,
and, if it stays without a challenge, how the tour can show it doing something. This evaluation answers
them from the repository at `b54e94e` (2026-10-24) and Istio's ambient documentation, read on 2026-10-24
(links inline). This run could not provision a cluster, so nothing here was measured live. The commands
that would measure it are in section 5. The guard-proxy source is a submodule this run could not read,
so what it says about `/toggle` comes from the lab and the scripts that call it, not from `proxy.py`.

## Recommendation

1. **Do not keep it as it is.** The mesh enrols no workload, so its five apps, three pods and one tour
   sentence describe a control that is not running. Of the three options, keeping it without a challenge
   costs the most for the least: making the tour sentence true takes most of the work a challenge would,
   and teaches nothing (section 3).
2. **Drop it for the next event unless Michael wants the challenge in section 2.** Dropping removes five
   apps, the `istio-cni` plugin from every pod's creation path, and an untrue sentence. It changes no
   challenge, because none of them depends on the mesh today (section 4).
3. **If it stays, the challenge worth building is "BurritoBot switches off its own guardrail."** The
   agent's tool pod can reach guard-proxy's unauthenticated `/toggle` on port 8080, and C1's own
   NetworkPolicy allows it. A mesh policy on a waypoint can refuse `/toggle` by path, and a NetworkPolicy
   cannot. The issue's first candidate, an L4 AuthorizationPolicy, would do no more than a NetworkPolicy
   ingress rule. The second, mTLS identity in the trace, cannot tell the agent from its tool pod, because
   they share a ServiceAccount. It costs a waypoint, the Gateway API CRDs, enrolling `agent` with STRICT
   relaxed, and a ServiceAccount for the console. That is a Barcelona-sized build.
4. **Close the `/toggle` route regardless of the mesh decision.** The console's public `/a2a/` route
   forwards every guard-proxy path, `/toggle` included (section 2.1). On the community cluster, which the
   whole room shares, a student could turn the guards off for everyone. That fix belongs in nginx or
   guard-proxy, not the mesh.
   **Done in #481:** `console.conf` no longer has an `/a2a/` route, and every route it keeps to
   guard-proxy is an exact match on one path (`verify/test_console_no_toggle.py`).

The decision is Michael's. Nothing above changes what is deployed.

## 1. What the mesh does today

| Piece | What the repo says | Effect on a cluster |
|---|---|---|
| `istio-base`, `istio-cni`, `istiod`, `ztunnel` | `gitops/apps/istio.yaml`, ambient profile, chart 1.30.4, waves -6 to -4 | istiod, plus `istio-cni` and `ztunnel` on every node |
| `istio-mesh-config` | `security/istio/peer-authentication.yaml`: STRICT mTLS in `agent` and `apps` | applies to no traffic |
| enrolment | ambient captures a pod only when it or its namespace carries `istio.io/dataplane-mode=ambient` | **no file sets the label**: not `gitops/namespaces/namespaces.yaml`, not a pod template, not a script |
| tour | "Istio ambient mesh encrypts all traffic between containers inside the cluster, automatically" (`lab.html:281-282`) | not true on any cluster built from this repo |

`peer-authentication.yaml` has said since it was written that the label still has to be added
("verify-at-build"). The #236 audit found the same thing. Nothing has changed since.

`verify/test_mesh_enrollment.py` now pins every fact in this evaluation, so when one of them changes the
offline suite fails, instead of the evaluation going quietly out of date.

## 2. Is there a challenge worth building?

### 2.1 The attack the mesh could stop: the agent turns off its own guardrails

The guards from C4, C5 and C6 are flags in guard-proxy, and a GET flips each one:
`GET /toggle?budget=on -> GUARDS['budget'] = True` (`lab.html:546`), and the same for `output` and
`input`. The lab tells the student to call it from inside the guard-proxy container on `localhost`.
That choice came from Kyverno, not from a lock on the endpoint. Commit `409bb16` (2026-06-26) moved the
toggle scripts onto `exec` because Kyverno Enforce rejected the curl pod they used to spawn.
`verify/beat-02.sh:45` and `verify/beat-cost.sh:29` still call `http://guard-proxy.agent:8080/toggle`
from a separate pod, without a credential. So guard-proxy accepts `/toggle` over the network.

The agent's tool pod can make that call:

- `run_shell` runs commands in `workshop-mcp` (`workshop-mcp-server.py:304`), and C1 already uses its
  `curl` (`lab.html`, "Prove it is the policy, not luck").
- C1's own fix allows it. `agent-allow-intra-namespace` permits egress from every `agent` pod to every
  other `agent` pod on any port (`policies/network-policies/per-namespace/agent-allow-intra-namespace.yaml`),
  and guard-proxy is in `agent`.

So after C5, a student can ask BurritoBot to run "the ops maintenance command"
`curl -s 'http://guard-proxy.agent:8080/toggle?output=off'` and then repeat the C5 leak. This is an agent
disabling its own control, the most agent-specific attack the workshop does not cover yet. Nobody has
run it live, so whether the model will make the call is untested, as it was for C1's beacon.

The same endpoint is also public. `console.conf:129-130` proxies `/a2a/` to `http://guard-proxy:8080/`
with the trailing slash, which strips the prefix. So `https://<cluster>.agenticburn.com/a2a/toggle?output=off`
reaches `/toggle`. The route's only consumer was chat-ui, removed in #240. The console Service is an
internet-facing NLB (`resources.yaml:1250-1256`), and the community cluster is shared by the whole room.
That is the reason for recommendation 4, and no mesh policy can fix it (see the table below).

**Closed in #481.** The `/a2a/` route is gone. The console now forwards only `/chat`, `/cost`, `/guards`,
`/prompts` and `/controls` to guard-proxy, each as an exact match, so `/a2a/toggle` and `/toggle` both 404
at the console. `verify/test_console_no_toggle.py` resolves request paths against the config the way nginx
does and fails if any of them reaches `/toggle`. The tool pod's in-cluster call above is still open.

### 2.2 Which control stops it

| Control | Stops the tool pod's `/toggle` | Stops the public `/a2a/toggle` | Cost |
|---|---|---|---|
| NetworkPolicy ingress on guard-proxy, only from the console pod | yes | **no**: that traffic arrives from the console | one manifest, works today |
| L4 AuthorizationPolicy at ztunnel, only from the console's identity | yes, the same as the row above | **no**, for the same reason | enrol `agent`, give the console its own ServiceAccount |
| **L7 AuthorizationPolicy on a waypoint, DENY `paths: ["/toggle"]`** | **yes** | **yes**: the console's call goes through the waypoint too | enrol `agent`, a waypoint, the Gateway API CRDs |
| guard-proxy refuses `/toggle` unless it comes from loopback, or nginx stops forwarding it | yes | yes | a code change in guard-proxy or `console.conf` |

The `exec` + `localhost` toggle that students use keeps working under every row, because loopback
traffic never leaves the pod.

**Only the waypoint row is a mesh lesson.** ztunnel enforces only L4 fields: principals, namespaces,
IP blocks and ports. A policy with an L7 attribute and no waypoint "will fail safe by becoming a `DENY`
policy" ([L4 policy](https://istio.io/latest/docs/ambient/usage/l4-policy/)). A NetworkPolicy matches pod
labels and ports, so it can say "only the console may call guard-proxy" but not "nobody may call
`/toggle`". The waypoint row is what the issue's "mesh-layer sibling of C1's NetworkPolicy" would have
to be to teach something C1 does not.

The last row is the real defence for the guard-proxy, and it should ship whatever happens to the mesh.
A mesh challenge built on this attack is a teaching choice: it shows the platform layer closing a hole
the application left open. Michael has to decide whether that is worth a waypoint.

### 2.3 Identity: why the L4 options are weaker than they look

Istio's identity is the ServiceAccount: `spiffe://cluster.local/ns/<ns>/sa/<sa>`. In `agent`:

| ServiceAccount | Workloads |
|---|---|
| `default` | `console`, `llm-guard`, **`evil-mcp-shim`** |
| `agent-sa` | `workshop-agent` (the Agent CR's `serviceAccountName`), **`workshop-mcp`** |
| `guard-proxy-reader` | `guard-proxy` |
| `web-terminal` | `web-terminal` |
| `agentgateway` | `agentgateway` |

- "Allow only the console's identity" would also let in `evil-mcp-shim`, C7's rogue server, because both
  run as `default`. Any identity rule first needs a ServiceAccount for the console.
- The issue's second candidate, "mTLS identity in the trace as the who-called-whom evidence", cannot tell
  BurritoBot from its tool pod, because both are `agent-sa`. It also would not appear in the trace: no
  span carries a SPIFFE ID. It appears in ztunnel's access log as `src.identity=` and `dst.identity=`
  ([ztunnel troubleshooting](https://istio.io/latest/docs/ambient/usage/troubleshoot-ztunnel/)), which
  Datadog collects with every container log. The OTel spans already show who called whom by service name.
  This one is something to look at, not a challenge with an attack and a fix.

### 2.4 What the waypoint challenge would take

| Step | Why |
|---|---|
| Install the Gateway API CRDs | a waypoint is a Gateway with `gatewayClassName: istio-waypoint`, and nothing in `gitops/` or `infra/` installs the CRDs ([waypoints](https://istio.io/latest/docs/ambient/usage/waypoint/)) |
| Enrol `agent`, and relax STRICT first | see section 3: STRICT on an enrolled `agent` rejects the NLB, kagent's controller and anything else outside the mesh |
| A ServiceAccount for the console | section 2.3 |
| A waypoint for guard-proxy, `istio.io/use-waypoint` on its Service | L7 policy is enforced only at the waypoint |
| Let the student create it | `console-terminal` (`resources.yaml:825`) grants no write on `security.istio.io` |
| A badge | guard-proxy's `/controls` reads what it is allowed to `get`. It would need the AuthorizationPolicy |
| Live checks | that the model actually makes the `/toggle` call when asked (section 2.1); that the waypoint does not break A2A streaming or the SSE MCP connections; the waypoint's footprint |

## 3. Keeping it without a challenge

The issue says that if the mesh stays without a challenge, the tour should show it doing something. On
today's clusters it does nothing, so the first step is enrolment, and enrolment is not just a label:

- **STRICT in `agent` cuts the front door.** The console Service is an NLB with `target-type: ip`
  (`resources.yaml:1253`), so traffic reaches the console pod straight from the load balancer, from
  outside the mesh. STRICT means "TLS with client cert must be presented"
  ([PeerAuthentication](https://istio.io/latest/docs/reference/config/security/peer_authentication/)).
  The same applies to kagent's controller in the unenrolled `kagent` namespace, which dials the MCP
  servers for tool discovery, and to anything else that calls into `agent` from outside it. Fixing that
  means PERMISSIVE, port-level exceptions, or enrolling `kagent` as well. Each needs a live check.
- **Enrolling `apps` breaks the party hostnames on the full profile.** `apps` runs default-deny on
  ingress and egress (`policies/network-policies/default-deny.yaml`). `apps-allow-ingress.yaml` admits
  ports 80, 5000 and 8080 only. Mesh traffic arrives on HBONE port 15008, and NetworkPolicy "is enforced
  on the host, outside the pod", so it needs an exception for 15008 and for the probe address
  `169.254.7.127/32` ([ambient and NetworkPolicy](https://istio.io/latest/docs/ambient/usage/networkpolicy/)).
  The console in `agent` calls the party apps on port 80 (#233). With both namespaces enrolled, that
  call would arrive on 15008 and be refused.
- C1's egress policies in `agent` are less exposed: `agent-allow-intra-namespace` allows every port
  inside the namespace. The issue's KubeArmor concern does not apply as built: `block-recipe-snoop` has
  file and process rules and no network rules.

If Michael keeps the mesh anyway, the tour should show one line from ztunnel. No `istioctl` is in the
terminal image, but `console-terminal` can read logs cluster-wide:

```
kubectl -n istio-system logs -l app=ztunnel --tail=200 | grep 'connection complete' | tail -1
```

On an enrolled cluster that line names both ends by SPIFFE ID. On today's clusters it prints nothing,
which is the evidence for section 1.

Until a decision lands, the tour sentence is the cheapest thing to fix. Suggested text, for Michael's
review, since it is student-facing: *"Istio ambient mesh is installed, but no namespace is enrolled in it
yet, so it is not encrypting anything. Run `kubectl get ns -L istio.io/dataplane-mode` and see."* Or
drop the bullet.
**Done in #482 (question 702):** the tour bullet now carries that text, and the "Istio ambient mTLS for
in-cluster traffic" control is gone from `challenges/c1-exfil-s3/README.md`. `verify/test_mesh_enrollment.py`
holds both while nothing is enrolled.

## 4. What dropping it saves

| Item | Detail |
|---|---|
| Applications | five of the attendee profile's ~39 (`istio-base`, `istio-cni`, `istiod`, `ztunnel`, `istio-mesh-config`) |
| Pods | istiod, plus one `istio-cni` and one `ztunnel` per node. The default attendee node is one `t3.2xlarge` (`infra/terraform/aws/cluster/main.tf:88-106`), so three pods |
| Requests and limits | 250m CPU / 448Mi requested, 1.3 CPU / 1.28Gi limit: istiod 100m/256Mi, ztunnel 100m/128Mi, cni 50m/64Mi. That is about 3% of a t3.2xlarge's CPU requests |
| Pod creation path | `istio-cni` is a chained CNI plugin, so it runs on every pod's creation, enrolled or not |
| Datadog | the `istio` named-integration check on ztunnel and the `istio` Service Map node (`test_datadog_service_map.py:206`, `test_observability.py:163-164`) |
| Install time | **not measured.** The Istio apps share sync waves -6 to -3 with KubeArmor, Kyverno, ESO, the policy apps and Falco. `gitops/argocd/values.yaml` has no health check for child `Application`s, so the root app-of-apps does not wait for one wave's apps to be healthy before starting the next. Removing Istio shortens no wave chain. What it removes is four Helm releases and their image pulls competing at bootstrap, and five apps on `fleet.sh`'s "every Application Synced and Healthy" readiness gate. Section 5 has the measurement |
| NetworkPolicy and KubeArmor | **nothing to save today.** Nothing is enrolled, so the mesh interacts with neither. The interactions in section 3 appear only if it is enrolled |

What goes with it: `gitops/apps/istio.yaml`, `security/istio/`, `verify/test_mesh.py`,
`verify/test_mesh_enrollment.py`, the Istio rows in `test_observability.py` and
`test_datadog_service_map.py`, the `lab.html` tour bullet, the Istio entries in `links.html`,
`platform.html` and `diagram.html`, and the docs that list Istio as part of the platform (README,
ABSTRACT, DESIGN-GLANCE, MASTER-RECREATION-SPEC, STACK-WALKTHROUGH, RUN-OF-SHOW). C1's README already
lists "Istio ambient mTLS for in-cluster traffic" as one of its controls. That line is false today too.
#25, the optional waypoint, closes with it.

## 5. What a cluster would settle

On any attendee cluster, with an explicit context:

```
kubectl --context "$CONTEXT" get ns -L istio.io/dataplane-mode            # section 1: expect no ambient
kubectl --context "$CONTEXT" -n argocd get applications -o \
  jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.operationState.startedAt}{"\t"}{.status.operationState.finishedAt}{"\n"}{end}'
                                                                           # section 4: per-app sync time
kubectl --context "$CONTEXT" -n agent exec deploy/workshop-mcp -- \
  curl -s -m 6 http://guard-proxy.agent:8080/guards                       # section 2.1: reachable, read-only
```

The third command reads the guard state without changing it, so it confirms the tool pod can reach
guard-proxy's control surface without switching anything off.
