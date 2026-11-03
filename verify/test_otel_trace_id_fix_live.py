# ABOUTME: Live check of #783's fix (#812): the copy's own trace id is on staging, and both KubeCon clusters' collectors
# ABOUTME: run it, synced by Argo CD from staging at a revision that holds 67c956a and rolled out to every node.
# SUITE: e2e
"""Needs git, kubectl, the network (GitHub), COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and
PRIVATE_CONTEXT naming the kube-context of watch-it-burn-private. Every missing prerequisite is a failure, never a skip.

#783's fix (67c956a) is the first statement of `transform/llmobs_one_root` in gitops/otel-collector/values.yaml:

    set(trace_id.string, Substring(SHA256(trace_id.string), 0, 32))

It gives Agent Observability's copy of each trace a trace id of its own, so APM's `dd_llmobs_enabled` false no longer
vetoes it. The statement has to run first: the turn's span id and kagent's re-parent are derived from the copy's trace
id. The criterion this test holds is "the fix is on staging and applied to watch-it-burn-community and
watch-it-burn-private". It stops holding in any of these ways, and each one fails here:

- staging. GitHub's staging, the branch the clusters' Argo CD reads, does not contain 67c956a, or its collector
  values (values.yaml alone for the private cluster's instructor Application, with values-burn.yaml for the community
  cluster's burn one, each with its Datadog overlay) no longer run the statement first in traces/llmobs.
- each cluster. The kube-context is not that cluster. The `otel-collector` Application does not read its values from
  staging, is not Synced, Healthy and Succeeded, or is synced at a revision that is not on staging or does not contain
  67c956a. The collector DaemonSet has not rolled the current template out to every node. The relay ConfigMap the
  DaemonSet mounts, alone and with each file of the Datadog overlay the datadog-gate may load, does not run the
  statement first in traces/llmobs, or the traces pipeline does not forward its copy there.

verify/test_otel_trace_id_fix_live_checks.py runs the same checks offline against fakes, a healthy pair of clusters
and one fake per way above, and holds that each way fails here. This spends nothing and changes nothing: one git fetch
of staging into FETCH_HEAD and read-only kubectl gets.

Whether Agent Observability then receives the copy is verify/agent_obs_flow.py's question (`chat`), not this one.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_otel_trace_id_fix_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from collector_render import deep_merge  # noqa: E402

FIX_COMMIT = "67c956adc5a2ddba99e9d8511f6055a77f045f63"
FIX_STATEMENT = "set(trace_id.string, Substring(SHA256(trace_id.string), 0, 32))"
REPO_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
BRANCH = "staging"
APP = "otel-collector"
NAMESPACE = "monitoring"
DAEMONSET = "otel-collector-opentelemetry-collector-agent"
# (cluster, the env naming its context, the Application file its bootstrap profile installs: community runs the burn
# profile, private the admin one, whose collector is the instructor Application.)
CLUSTERS = (("watch-it-burn-community", "COMMUNITY_CONTEXT", "gitops/bootstrap/apps/otel-collector-burn.yaml"),
            ("watch-it-burn-private", "PRIVATE_CONTEXT", "gitops/bootstrap/apps/otel-collector.yaml"))


def _repo_key(url: str) -> str:
    return url.strip().lower().removesuffix("/").removesuffix(".git")


def llmobs_fix_problems(config: dict) -> list[str]:
    """What keeps #783's fix from running in a collector config; empty when it runs."""
    problems = []
    processors = config.get("processors") or {}
    proc = processors.get("transform/llmobs_one_root")
    if not isinstance(proc, dict):
        problems.append("there is no transform/llmobs_one_root processor")
    else:
        groups = proc.get("trace_statements") or []
        first = next((g.get("statements") or [] for g in groups if isinstance(g, dict)), [])
        if not first or first[0] != FIX_STATEMENT:
            problems.append(f"transform/llmobs_one_root's first statement is {first[0] if first else 'missing'!r}, "
                            f"not {FIX_STATEMENT!r}")
        if not groups or groups[0].get("context") != "span":
            problems.append("transform/llmobs_one_root's first statement group is not in the span context")
    pipelines = ((config.get("service") or {}).get("pipelines")) or {}
    llmobs = pipelines.get("traces/llmobs") or {}
    if "forward/llmobs" not in (llmobs.get("receivers") or []):
        problems.append("the traces/llmobs pipeline does not receive forward/llmobs")
    if (llmobs.get("processors") or [None])[0] != "transform/llmobs_one_root":
        problems.append(f"the traces/llmobs pipeline's first processor is not transform/llmobs_one_root "
                        f"(processors: {llmobs.get('processors')})")
    if "forward/llmobs" not in ((pipelines.get("traces") or {}).get("exporters") or []):
        problems.append("the traces pipeline does not export forward/llmobs, so traces/llmobs gets no copy")
    return problems


def overlay_files(overlay_cm: dict) -> dict[str, dict]:
    """Every file of the Datadog overlay ConfigMap, parsed: the gate loads one of them, or none."""
    return {k: (yaml.safe_load(v) or {}) for k, v in sorted((overlay_cm.get("data") or {}).items())}


def config_problems(relay: dict, overlay_cm: dict | None, where: str) -> list[str]:
    """The fix checked in relay.yaml alone (no datadog-secret) and with each overlay file the gate can load on top."""
    out = [f"{where}, relay.yaml: {p}" for p in llmobs_fix_problems(relay)]
    if overlay_cm is None:
        return out + [f"{where}: there is no Datadog overlay ConfigMap (otel-collector-datadog)"]
    files = overlay_files(overlay_cm)
    if not files:
        out.append(f"{where}: the Datadog overlay ConfigMap has no files")
    for name, over in files.items():
        out += [f"{where}, relay.yaml with {name}: {p}" for p in llmobs_fix_problems(deep_merge(relay, over))]
    return out


class Git:
    """The git reads this test makes, in this repo's object store. The offline checks replace it with a fake."""

    def _git(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=timeout)

    def fetch_staging(self) -> str:
        """GitHub's staging head, fetched with its history into FETCH_HEAD. Raises when the fetch fails."""
        r = self._git("fetch", "--quiet", "--no-tags", REPO_URL, f"refs/heads/{BRANCH}", timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"git fetch {REPO_URL} {BRANCH} failed: {r.stderr.strip()}")
        return self._git("rev-parse", "FETCH_HEAD").stdout.strip()

    def has(self, rev: str) -> bool:
        return self._git("cat-file", "-e", f"{rev}^{{commit}}").returncode == 0

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self._git("merge-base", "--is-ancestor", older, newer).returncode == 0

    def show(self, rev: str, path: str) -> str | None:
        r = self._git("show", f"{rev}:{path}")
        return r.stdout if r.returncode == 0 else None


class Cluster:
    """Read-only kubectl gets on one cluster, every call naming its context. The offline checks fake `get`."""

    def __init__(self, context: str) -> None:
        self.context = context

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        r = subprocess.run(["kubectl", "--context", self.context, "--request-timeout=30s", "-n", namespace,
                            "get", kind, name, "-o", "json"], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            if "NotFound" in r.stderr or "not found" in r.stderr:
                return None
            raise RuntimeError(f"kubectl --context {self.context} -n {namespace} get {kind} {name}: {r.stderr.strip()}")
        return json.loads(r.stdout)


def staging_checks(git: Git, staging: str) -> list[tuple[str, bool, str]]:
    """#783's fix on staging: the commit is in its history, and each profile's collector values run the statement."""
    out = [(f"staging ({staging[:12]}) contains #783's fix {FIX_COMMIT[:12]}",
            git.has(FIX_COMMIT) and git.is_ancestor(FIX_COMMIT, staging), "")]
    for cluster, _env, app_path in CLUSTERS:
        problems: list[str] = []
        app_text = git.show(staging, app_path)
        if app_text is None:
            problems.append(f"{app_path} is not on staging")
        else:
            app = yaml.safe_load(app_text)
            chart = next((s for s in app["spec"].get("sources", []) if s.get("chart") == "opentelemetry-collector"), {})
            files = [f.replace("$values/", "") for f in ((chart.get("helm") or {}).get("valueFiles") or [])]
            vals: dict = {}
            for f in files:
                text = git.show(staging, f)
                if text is None:
                    problems.append(f"{f}, a value file of {app_path}, is not on staging")
                    continue
                vals = deep_merge(vals, yaml.safe_load(text) or {})
            overlay = next((m for m in vals.get("extraManifests") or []
                            if m.get("kind") == "ConfigMap" and m["metadata"]["name"] == "otel-collector-datadog"), None)
            if not files:
                problems.append(f"{app_path} names no value files")
            else:
                problems += config_problems(vals.get("config") or {}, overlay, " + ".join(files))
        out.append((f"staging's collector for {cluster} ({app_path}) runs the fix first in traces/llmobs",
                    not problems, "; ".join(problems)))
    return out


def cluster_checks(name: str, context: str, cluster: Cluster, git: Git, staging: str) -> list[tuple[str, bool, str]]:
    """#783's fix applied on one cluster: Argo CD synced it from staging, and the collector pods run it."""
    out: list[tuple[str, bool, str]] = []
    out.append((f"{name}: the context {context!r} is that cluster", context == name or context.endswith(f"/{name}"),
                "the context must be the cluster's name or its EKS ARN (…:cluster/<name>)"))
    if not out[-1][1]:
        return out
    app = cluster.get("application", APP, "argocd")
    out.append((f"{name}: Argo CD has the {APP} Application", app is not None, ""))
    if app is None:
        return out
    sources = app["spec"].get("sources") or ([app["spec"]["source"]] if app["spec"].get("source") else [])
    idx = next((i for i, s in enumerate(sources)
                if _repo_key(s.get("repoURL", "")) == _repo_key(REPO_URL) and s.get("ref") == "values"), None)
    out.append((f"{name}: {APP} reads its collector values from this repo's {BRANCH}",
                idx is not None and sources[idx].get("targetRevision") == BRANCH,
                f"sources: {[(s.get('repoURL'), s.get('targetRevision'), s.get('ref')) for s in sources]}"))
    status = app.get("status") or {}
    sync, op = status.get("sync") or {}, status.get("operationState") or {}
    health = (status.get("health") or {}).get("status")
    out.append((f"{name}: {APP} is Synced and Healthy, and its last sync Succeeded",
                sync.get("status") == "Synced" and health == "Healthy" and op.get("phase") == "Succeeded",
                f"sync {sync.get('status')}, health {health}, last operation {op.get('phase')}: {op.get('message', '')}"))
    revisions = sync.get("revisions") or ([sync["revision"]] if sync.get("revision") else [])
    rev = revisions[idx] if idx is not None and idx < len(revisions) else ""
    on_staging = bool(rev) and git.has(rev) and git.is_ancestor(rev, staging)
    out.append((f"{name}: {APP} is synced at a revision on staging ({rev[:12] or 'none'})", on_staging,
                f"staging is {staging[:12]}; a revision git cannot find after fetching staging is not on it"))
    out.append((f"{name}: that revision contains #783's fix {FIX_COMMIT[:12]}",
                on_staging and git.has(FIX_COMMIT) and git.is_ancestor(FIX_COMMIT, rev), ""))

    ds = cluster.get("daemonset", DAEMONSET, NAMESPACE)
    out.append((f"{name}: the collector DaemonSet {NAMESPACE}/{DAEMONSET} exists", ds is not None, ""))
    if ds is None:
        return out
    st = ds.get("status") or {}
    desired = st.get("desiredNumberScheduled", 0)
    rolled = (desired > 0 and st.get("observedGeneration") == ds["metadata"].get("generation")
              and st.get("updatedNumberScheduled") == desired and st.get("numberAvailable") == desired)
    out.append((f"{name}: the collector's current template runs, available, on every node", rolled,
                f"generation {ds['metadata'].get('generation')}, observed {st.get('observedGeneration')}, desired "
                f"{desired}, updated {st.get('updatedNumberScheduled')}, available {st.get('numberAvailable')}"))
    volumes = ds["spec"]["template"]["spec"].get("volumes") or []
    relay_cm = next((v["configMap"]["name"] for v in volumes if any(
        i.get("key") == "relay" for i in ((v.get("configMap") or {}).get("items") or []))), None)
    overlay_name = next((v["configMap"]["name"] for v in volumes
                         if v.get("name") == "datadog-overlay" and v.get("configMap")), None)
    relay_obj = cluster.get("configmap", relay_cm, NAMESPACE) if relay_cm else None
    overlay_obj = cluster.get("configmap", overlay_name, NAMESPACE) if overlay_name else None
    if relay_obj is None or "relay" not in (relay_obj.get("data") or {}):
        problems = [f"the DaemonSet mounts no readable relay ConfigMap ({relay_cm})"]
    else:
        problems = config_problems(yaml.safe_load(relay_obj["data"]["relay"]) or {}, overlay_obj,
                                   f"ConfigMap {relay_cm}")
    out.append((f"{name}: the collector's live config runs the fix first in traces/llmobs", not problems,
                "; ".join(problems)))
    return out


def report(results: list[tuple[str, bool, str]]) -> list[str]:
    failed = []
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
        if not ok:
            failed.append(label)
    return failed


def run(contexts: dict[str, str], git: Git, cluster_for) -> list[str]:
    """Every check, staging first; the failed labels. `cluster_for(context)` gives the Cluster to read."""
    try:
        staging = git.fetch_staging()
    except RuntimeError as e:
        return report([("GitHub's staging can be fetched", False, str(e))])
    print(f"== #783's fix on staging ({staging}) ==")
    failed = report(staging_checks(git, staging))
    for name, env, _app in CLUSTERS:
        print(f"== #783's fix applied on {name} ({contexts[env]}) ==")
        try:
            failed += report(cluster_checks(name, contexts[env], cluster_for(contexts[env]), git, staging))
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            failed += report([(f"{name}: the cluster can be read", False, str(e))])
    return failed


def main() -> int:
    missing = [f"{t} is not on PATH" for t in ("git", "kubectl") if shutil.which(t) is None]
    contexts = {env: os.environ.get(env, "") for _n, env, _a in CLUSTERS}
    missing += [f"{env} is not set: name the kube-context of {n}" for n, env, _a in CLUSTERS if not contexts[env]]
    if missing:
        print("FAIL: test_otel_trace_id_fix_live.py cannot run; this is a failure, not a skip:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    failed = run(contexts, Git(), Cluster)
    if failed:
        print(f"\nFAILED: {len(failed)}: #783's fix is not on staging and applied on both clusters", file=sys.stderr)
        return 1
    print("\n#783's fix is on staging and applied on watch-it-burn-community and watch-it-burn-private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
