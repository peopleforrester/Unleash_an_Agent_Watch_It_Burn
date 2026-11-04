# Argo CD sync replay (#679), 2026-10-30

Two things never reached the KubeCon clusters on 2026-10-29 while Argo CD said every sync succeeded: the Agent's
twelfth workshop-mcp tool, `read_support_ticket` (#640), and guard-proxy's new `CONSOLE_ORIGIN` env entry. This runs
both through Argo CD v3.5.7's own code, the version VERSIONS.lock pins since #858 (v3.5.2 before it), against a real
kube-apiserver. No cluster, no containers and no AWS are needed.

```
bash docs/research/2026-10-30-argo-sync-replay/replay.sh
```

It needs go 1.26 or later, git, curl, jq, python3 with PyYAML, and network the first time. It fetches envtest
v1.34.1 (etcd, kube-apiserver, kubectl; checked against the SHA-512 in controller-tools' `envtest-releases.yaml`) and
argo-cd v3.5.7's `gitops-engine` tree into the gitignored `tmp/argo-sync-replay`, and fetches that tree again when the
one there is of another tag. It starts its own apiserver on free localhost ports and runs about 35 seconds.

## What runs

- `main.go norm`: `normalizeTargetResources` from `controller/sync.go` at v3.5.2, for one resource, with
  `getMergePatch`, `applyMergePatch` and `restoreNonIgnoredFields` copied verbatim. All four are the same at v3.5.7.
  It is what a sync applies when the Application has `RespectIgnoreDifferences=true`.
- `main.go diff`: `util/argo/diff.StateDiff` from the argo-cd v3.5.7 module, configured as `controller/state.go`
  configures an Application with `ServerSideApply=true` (structured merge diff, manager `argocd-controller`).
- The apply is server-side, field manager `argocd-controller`, force-conflicts, as gitops-engine runs it.
- The live object it diffs is read with its managedFields, as Argo CD's live cache holds it.
- The manifests and ignores are the repo's: guard-proxy from `gitops/ai-layer/resources.yaml` with ai-layer's
  ignores, and the Agent from `gitops/workshop-agent/agent.yaml` with the workshop-agent Application's ignores (#707),
  or with the ignores ai-layer had before #707.

## What it showed (all checks pass: 20 on 2026-10-30, the first run's layout; 25 on 2026-11-01, on #707's layout; 25 on 2026-11-05 at v3.5.7)

1. guard-proxy, `CONSOLE_ORIGIN` added in git: one sync lands it in git's place, keeps a live `MODEL_TIER=sonnet`
   toggle, and the Deployment reads Synced. A built-in kind takes a strategic merge patch with merge keys, so the
   ignored env entries do not freeze the list's contents.
2. guard-proxy, the same entry added live with `kubectl set env`, which appends: the Deployment reads OutOfSync on
   order alone, and stays OutOfSync after every sync. The strategic patch carries `$setElementOrder/env` from live,
   so the sync applies the live order, while a server dry run of git's Deployment, which is what the diff predicts,
   puts the entry in git's place. That is the stuck guard-proxy and the selfHeal loop of 2026-10-29.
3. guard-proxy after `fleet.sh` converge's `repair_env_order` rewrite (the live entries in git's order, values
   kept): one sync, and it reads Synced.
4. guard-proxy, a commit that only moves an entry (2026-11-01): the same freeze from git's side. Two syncs keep the
   live order and it stays OutOfSync; after `repair_env_order`'s rewrite one sync reads Synced.
5. The Agent in ai-layer as before #707: it is a CRD, so the copy is a JSON merge patch, which carries the whole live
   tools array. Two syncs, and `read_support_ticket` never lands; the Agent stays OutOfSync.
6. The Agent in the workshop-agent Application (#707), which does not respect its ignores on sync: one sync lands git's twelve and it reads
   Synced, and a student's guard-mcp-on (evil-mcp narrowed to `get_weather`) still reads Synced, so selfHeal leaves it.

`verify/test_agent_tools_sync.py` ports the same function to Python and holds these results in the offline suite.
