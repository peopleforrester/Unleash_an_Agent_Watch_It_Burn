# ABOUTME: Offline checks for verify/test_collector_coc_mask_live.py (#1339): its checks pass on a fake pair of clusters
# ABOUTME: running #1332's coc-mask ConfigMap, and fail on each way #1335's criterion can stop holding on one of them.
"""test_collector_coc_mask_live.py is the live test for #1335's criterion "on both clusters the otel-collector
Application is Synced and Healthy, and the otel-collector-coc-mask ConfigMap is in monitoring". It needs both clusters.
This runs its `run` against fake clusters, so the healthy pair passes and each way the criterion can stop holding fails
it, on the check that names that way: a context naming the wrong cluster; no Application, OutOfSync, Degraded or
Progressing; a destination other than monitoring or no coc-mask source; the ConfigMap untracked or tracked out of sync;
the ConfigMap gone, put there by another Application, without its key, or defining more than the mask; the DaemonSet
gone, not mounting the ConfigMap or mounting it optionally, carrying an older checksum, or not rolled out. The healthy
fakes carry this checkout's own ConfigMap (collector_render.coc_mask_configmap), so a change here that breaks the file
fails the healthy case too. A cluster that cannot be read fails, and the other cluster is still checked. Nothing here
touches a cluster.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collector_render as cr  # noqa: E402
import test_collector_coc_mask_live as live  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CONTEXTS = {"COMMUNITY_CONTEXT": "arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-community",
            "PRIVATE_CONTEXT": "watch-it-burn-private"}
COMMUNITY = "watch-it-burn-community"

check("the live test's ConfigMap name, key and source directory are this checkout's",
      (live.CONFIGMAP, live.KEY, live.SOURCE_PATH)
      == (cr.coc_mask_configmap()["metadata"]["name"], cr.COC_MASK_KEY,
          cr.COC_MASK_MANIFEST.parent.relative_to(cr.REPO).as_posix()))


def healthy() -> dict[tuple[str, str], dict]:
    """One cluster's objects as #1335 left them: the repo's ConfigMap, Argo CD's, mounted and rolled out."""
    cm = copy.deepcopy(cr.coc_mask_configmap())
    cm["metadata"]["namespace"] = live.NAMESPACE
    cm["metadata"]["annotations"] = {"argocd.argoproj.io/tracking-id": live.TRACKING}
    digest = hashlib.sha256(cm["data"][live.KEY].encode("utf-8")).hexdigest()
    app = {"spec": {"destination": {"namespace": live.NAMESPACE, "server": "https://kubernetes.default.svc"},
                    "sources": [{"repoURL": "https://open-telemetry.github.io/opentelemetry-helm-charts",
                                 "chart": "opentelemetry-collector"},
                                {"repoURL": live.REPO_URL, "ref": "values", "targetRevision": "staging"},
                                {"repoURL": live.REPO_URL, "path": live.SOURCE_PATH, "targetRevision": "staging"}]},
           "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"},
                      "resources": [{"kind": "ConfigMap", "name": live.CONFIGMAP, "namespace": live.NAMESPACE,
                                     "status": "Synced", "version": "v1"},
                                    {"kind": "ConfigMap", "name": "otel-collector-datadog",
                                     "namespace": live.NAMESPACE, "status": "Synced", "version": "v1"}]}}
    ds = {"metadata": {"generation": 30},
          "spec": {"template": {"metadata": {"annotations": {live.ANNOTATION: digest}},
                                "spec": {"volumes": [{"name": "datadog-overlay",
                                                      "configMap": {"name": "otel-collector-datadog"}},
                                                     {"name": "coc-mask", "configMap": {"name": live.CONFIGMAP}}]}}},
          "status": {"observedGeneration": 30, "desiredNumberScheduled": 2, "updatedNumberScheduled": 2,
                     "numberAvailable": 2}}
    return {("application", live.APP): app, ("configmap", live.CONFIGMAP): cm, ("daemonset", live.DAEMONSET): ds}


class FakeCluster(live.Cluster):
    def __init__(self, context: str, objects: dict | None, broken: bool = False) -> None:
        super().__init__(context)
        self.objects, self.broken = objects, broken

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        if self.broken:
            raise RuntimeError(f"kubectl --context {self.context} -n {namespace} get {kind} {name}: connection refused")
        want = "argocd" if kind == "application" else live.NAMESPACE
        if namespace != want:
            return None
        return copy.deepcopy(self.objects.get((kind, name)))


def run(community: dict | None = None, contexts: dict | None = None, broken: bool = False) -> tuple[list[str], str]:
    """`run` with the private cluster healthy and the community one as given; the failed labels and the output."""
    objs = {CONTEXTS["COMMUNITY_CONTEXT"]: community if community is not None else healthy(),
            CONTEXTS["PRIVATE_CONTEXT"]: healthy()}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        failed = live.run(contexts or CONTEXTS,
                          lambda c: FakeCluster(c, objs.get(c, {}), broken and c == CONTEXTS["COMMUNITY_CONTEXT"]))
    return failed, buf.getvalue()


print("== the healthy pair passes ==")
failed, out = run()
check("both clusters as #1335 left them pass every check", not failed, f"failed: {failed}\n{out}")
check("both clusters are checked", all(f"== #1335's criterion on {n}" in out for n, _e in live.CLUSTERS), out)
n_ok = out.count("  PASS  ")
check("each cluster runs all twelve checks", n_ok == 24, f"{n_ok} PASS lines\n{out}")


def mutate(fn) -> dict:
    objs = healthy()
    fn(objs)
    return objs


def app(o):
    return o[("application", live.APP)]


def cm(o):
    return o[("configmap", live.CONFIGMAP)]


def ds(o):
    return o[("daemonset", live.DAEMONSET)]


def replace_key_text(o, text):
    cm(o)["data"][live.KEY] = text


EXTRA_PROC = cm(healthy())["data"][live.KEY].replace("processors:\n", "processors:\n  batch: {}\n", 1)
assert EXTRA_PROC != cm(healthy())["data"][live.KEY], f"{cr.COC_MASK_MANIFEST}: its file no longer starts processors:"

# (what breaks, the community cluster's objects or None for the context case, the label fragment that must fail)
CASES = [
    ("no otel-collector Application", mutate(lambda o: o.pop(("application", live.APP))),
     "Argo CD has the otel-collector Application"),
    ("the Application OutOfSync", mutate(lambda o: app(o)["status"]["sync"].update(status="OutOfSync")),
     "is Synced and Healthy"),
    ("the Application Degraded", mutate(lambda o: app(o)["status"]["health"].update(status="Degraded")),
     "is Synced and Healthy"),
    ("the Application Progressing", mutate(lambda o: app(o)["status"]["health"].update(status="Progressing")),
     "is Synced and Healthy"),
    ("the Application with no status", mutate(lambda o: app(o).pop("status")), "is Synced and Healthy"),
    ("the destination another namespace", mutate(lambda o: app(o)["spec"]["destination"].update(namespace="default")),
     f"deploys {live.SOURCE_PATH}"),
    ("the coc-mask source dropped", mutate(lambda o: app(o)["spec"]["sources"].pop()), f"deploys {live.SOURCE_PATH}"),
    ("the coc-mask source from another repo",
     mutate(lambda o: app(o)["spec"]["sources"][2].update(repoURL="https://github.com/someone/fork.git")),
     f"deploys {live.SOURCE_PATH}"),
    ("the ConfigMap not among the Application's resources",
     mutate(lambda o: app(o)["status"].update(resources=app(o)["status"]["resources"][1:])), "Argo CD tracks"),
    ("the ConfigMap tracked OutOfSync",
     mutate(lambda o: app(o)["status"]["resources"][0].update(status="OutOfSync")), "Argo CD tracks"),
    ("the ConfigMap gone from monitoring", mutate(lambda o: o.pop(("configmap", live.CONFIGMAP))),
     f"ConfigMap {live.CONFIGMAP} is in {live.NAMESPACE}"),
    ("the ConfigMap put there by another Application",
     mutate(lambda o: cm(o)["metadata"]["annotations"].update(
         {"argocd.argoproj.io/tracking-id": f"stray:/ConfigMap:{live.NAMESPACE}/{live.CONFIGMAP}"})),
     "was put there by the otel-collector Application"),
    ("the ConfigMap without its key", mutate(lambda o: cm(o).update(data={})), "defines transform/coc_mask"),
    ("the file defining a second processor", mutate(lambda o: replace_key_text(o, EXTRA_PROC)),
     "defines transform/coc_mask"),
    ("the file not YAML", mutate(lambda o: replace_key_text(o, "processors: [unclosed")), "defines transform/coc_mask"),
    ("the mask with no statements",
     mutate(lambda o: replace_key_text(o, "processors:\n  transform/coc_mask:\n    error_mode: ignore\n")),
     "defines transform/coc_mask"),
    ("no collector DaemonSet", mutate(lambda o: o.pop(("daemonset", live.DAEMONSET))), "the collector DaemonSet"),
    ("the DaemonSet not mounting the ConfigMap",
     mutate(lambda o: ds(o)["spec"]["template"]["spec"].update(volumes=ds(o)["spec"]["template"]["spec"]["volumes"][:1])),
     "the collector mounts"),
    ("the ConfigMap mounted optionally",
     mutate(lambda o: ds(o)["spec"]["template"]["spec"]["volumes"][1]["configMap"].update(optional=True)),
     "the collector mounts"),
    ("an older list in the collector's checksum",
     mutate(lambda o: ds(o)["spec"]["template"]["metadata"]["annotations"].update({live.ANNOTATION: "0" * 64})),
     "SHA-256"),
    ("the live file changed under an unchanged checksum",
     mutate(lambda o: replace_key_text(o, cm(o)["data"][live.KEY] + "\n")), "SHA-256"),
    ("the DaemonSet's template not observed",
     mutate(lambda o: ds(o)["status"].update(observedGeneration=29)), "on every node"),
    ("a node on the old template", mutate(lambda o: ds(o)["status"].update(updatedNumberScheduled=1)), "on every node"),
    ("a node's collector unavailable", mutate(lambda o: ds(o)["status"].update(numberAvailable=1)), "on every node"),
    ("no node scheduled", mutate(lambda o: ds(o)["status"].update(desiredNumberScheduled=0, updatedNumberScheduled=0,
                                                                  numberAvailable=0)), "on every node"),
]

print("== each way the criterion stops holding on the community cluster fails, on its own check ==")
for what, objs, fragment in CASES:
    failed, out = run(objs)
    named = [f for f in failed if f.startswith(COMMUNITY) and fragment in f]
    check(f"{what}: fails on the check naming {fragment!r}", bool(named), f"failed: {failed}\n{out}")
    check(f"{what}: the private cluster still passes", not [f for f in failed if not f.startswith(COMMUNITY)],
          f"failed: {failed}")

failed, out = run(contexts={**CONTEXTS, "COMMUNITY_CONTEXT": "watch-it-burn-private"})
check("a COMMUNITY_CONTEXT naming the private cluster fails as the wrong cluster",
      any(f.startswith(f"{COMMUNITY}: the context") for f in failed), f"failed: {failed}\n{out}")
failed, out = run(broken=True)
check("a community cluster that cannot be read fails, and the private one is still checked",
      failed == [f"{COMMUNITY}: the cluster can be read"] and out.count("  PASS  ") == 12, f"failed: {failed}\n{out}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("test_collector_coc_mask_live.py passes the healthy pair and fails on each way #1335's criterion stops holding.")
