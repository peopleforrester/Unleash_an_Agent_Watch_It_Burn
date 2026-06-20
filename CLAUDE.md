# Repo working rules (read first)

## Kube-context safety (CRITICAL: other Claude Codes may be managing other clusters)

Concurrent Claude Code sessions may be operating other Kubernetes clusters on this box. Never touch
global kube state. Be explicit about the target cluster on every single command.

**Rules, no exceptions:**

1. **Every `kubectl` call carries an explicit `--context "$CONTEXT"`** (or runs with a per-command
   `KUBECONFIG=<isolated-file>` prefix). Never rely on the global current-context.
2. **Never run `kubectl config use-context`** or `kubectl config set-context` against the shared
   `~/.kube/config`. That mutates state every other process and Claude Code sees.
3. **Never `export KUBECONFIG`** into the environment as a shared default. If you need a kubeconfig,
   pass it per command: `KUBECONFIG="$KCFG" kubectl --context "$CONTEXT" ...`.
4. **`eksctl` must not clobber the shared kubeconfig.** Always pass
   `--kubeconfig <isolated-path> --set-kubeconfig-context=false` on `create`/`delete`/`utils
   write-kubeconfig`, so it never rewrites `~/.kube/config` or flips the current-context.
5. **Scripts take the context explicitly.** The verify harness (`verify/*.sh`) already takes a
   `<kube-context>` arg; the demo toggle/fallback scripts read a required `CONTEXT` env. A script that
   cannot determine its target context must fail loudly, never fall back to the current-context.
6. **AWS profiles too:** pass `--region` (and `--profile` when relevant) explicitly; do not depend on
   a shared default region/profile that another session may have changed.

If you are unsure which cluster a command will hit, stop and make the context explicit first.
