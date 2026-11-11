# ABOUTME: Offline checks for verify/test_collector_pods_ready_live.py (#1341): its checks pass on a fake pair of clusters
# ABOUTME: whose collector pods run #1332's coc-mask list, ready and logged ready, and fail on each way that stops holding.
"""test_collector_pods_ready_live.py is the live test for #1335's criterion "on both clusters the collector pods rolled
onto the checksum/coc-mask annotation and logged Everything is ready with no restart". It needs both clusters. This
runs its `run` against fake clusters, so the healthy pair passes and each way the criterion can stop holding fails it,
on the check that names that way: a context naming the wrong cluster; the ConfigMap gone or without its key; the
DaemonSet gone, scheduling none, or running fewer pods than it schedules; a pod on an older template, with an older or
no checksum, not Running, not ready, or restarted; a start-up log without the line, rotated away, or missing from the
node. A pod of the DaemonSet that is being deleted, or a pod another owner runs under the same labels, is not counted.
It also holds that the log is read from the oldest file kubelet keeps of the running instance, gzipped or not, and
that a cluster that cannot be read fails while the other is still checked. The healthy fakes carry this checkout's own
ConfigMap (gitops/otel-collector/coc-mask/configmap.yaml), so its checksum is the one the repo ships. Nothing here touches a
cluster.
"""
from __future__ import annotations

import contextlib
import copy
import gzip
import hashlib
import io
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_collector_coc_mask_live as mask_live  # noqa: E402  (the live test this one borrows its names from)
import test_collector_pods_ready_live as live  # noqa: E402

MANIFEST = HERE.parent / "gitops/otel-collector/coc-mask/configmap.yaml"
SHIPPED = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CONTEXTS = {"COMMUNITY_CONTEXT": "arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-community",
            "PRIVATE_CONTEXT": "watch-it-burn-private"}
COMMUNITY = "watch-it-burn-community"
DS_UID = "3b02ede6-4999-4b6a-abeb-25b8d1fcb24f"
LABELS = {"app.kubernetes.io/instance": "otel-collector", "app.kubernetes.io/name": "opentelemetry-collector",
          "component": "agent-collector"}
SELECTOR = ",".join(f"{k}={v}" for k, v in sorted(LABELS.items()))


def startup(pod: str) -> str:
    """A collector start-up as kubelet writes it to the container's log file."""
    return (f"2026-11-11T06:32:10.428000000Z stderr F 2026-11-11T06:32:10.428Z\tinfo\tservice.go:200\tStarting\n"
            f"2026-11-11T06:32:12.217000000Z stderr F 2026-11-11T06:32:12.217Z\tinfo\tservice@v0.160.0/service.go:284\t"
            f"{live.READY}\t{{\"resource\": {{\"k8s.pod.name\": \"{pod}\"}}}}\n")


def later() -> str:
    return "2026-11-11T09:00:00.000000000Z stderr F 2026-11-11T09:00:00.000Z\tinfo\tdebugexporter\tTraces\n" * 3


def pod(n: int, digest: str) -> dict:
    name = f"{live.DAEMONSET}-p{n}"
    return {"metadata": {"name": name, "uid": f"uid-{n}", "labels": {**LABELS, "pod-template-generation": "30"},
                         "annotations": {live.ANNOTATION: digest, "checksum/config": "a" * 64},
                         "ownerReferences": [{"kind": "DaemonSet", "name": live.DAEMONSET, "uid": DS_UID,
                                              "controller": True}]},
            "spec": {"nodeName": f"node-{n}"},
            "status": {"phase": "Running",
                       "initContainerStatuses": [{"name": "datadog-gate", "restartCount": 0}],
                       "containerStatuses": [{"name": live.CONTAINER, "ready": True, "restartCount": 0,
                                              "state": {"running": {"startedAt": "2026-11-11T06:32:10Z"}}}]}}


def log_dir(p: dict) -> tuple[str, str]:
    m = p["metadata"]
    return p["spec"]["nodeName"], f"pods/{live.NAMESPACE}_{m['name']}_{m['uid']}/{live.CONTAINER}/"


def healthy() -> dict:
    """One cluster as #1335 left it: the repo's ConfigMap, two collector pods on its checksum, each logged ready."""
    cm = copy.deepcopy(SHIPPED)
    cm["metadata"]["namespace"] = live.NAMESPACE
    digest = hashlib.sha256(cm["data"][live.KEY].encode("utf-8")).hexdigest()
    ds = {"metadata": {"generation": 31, "uid": DS_UID, "annotations": {live.TEMPLATE_GENERATION: "30"}},
          "spec": {"selector": {"matchLabels": dict(LABELS)}},
          "status": {"desiredNumberScheduled": 2}}
    pods = [pod(1, digest), pod(2, digest)]
    logs = {}
    for p in pods:
        node, d = log_dir(p)
        logs[(node, d)] = {"0.log": startup(p["metadata"]["name"]).encode()}
    return {"objects": {("configmap", live.CONFIGMAP): cm, ("daemonset", live.DAEMONSET): ds},
            "pods": pods, "logs": logs}


class FakeCluster(live.Cluster):
    def __init__(self, context: str, state: dict, broken: bool = False) -> None:
        super().__init__(context)
        self.state, self.broken = state, broken
        self.reads: list[str] = []

    def _down(self, what: str) -> None:
        if self.broken:
            raise RuntimeError(f"kubectl --context {self.context} {what}: connection refused")

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        self._down(f"get {kind} {name}")
        if namespace != live.NAMESPACE:
            return None
        return copy.deepcopy(self.state["objects"].get((kind, name)))

    def pods(self, namespace: str, selector: str) -> list[dict]:
        self._down("get pods")
        if namespace != live.NAMESPACE or selector != SELECTOR:
            return []
        return copy.deepcopy(self.state["pods"])

    def node_log(self, node: str, path: str) -> bytes:
        self._down(f"get --raw {node} {path}")
        self.reads.append(path)
        directory, _, file = path.rpartition("/")
        files = self.state["logs"].get((node, directory + "/"))
        if files is None:
            raise RuntimeError(f"kubectl --context {self.context} get --raw /api/v1/nodes/{node}/proxy/logs/{path}: "
                               f"NotFound")
        if not file:
            return ("<pre>\n" + "".join(f'<a href="{f}">{f}</a>\n' for f in files) + "</pre>\n").encode()
        return files[file]


def run(community: dict | None = None, contexts: dict | None = None, broken: bool = False):
    """`run` with the private cluster healthy and the community one as given; the failed labels, output and fakes."""
    states = {CONTEXTS["COMMUNITY_CONTEXT"]: community if community is not None else healthy(),
              CONTEXTS["PRIVATE_CONTEXT"]: healthy()}
    made: dict[str, FakeCluster] = {}

    def cluster_for(c: str) -> FakeCluster:
        made[c] = FakeCluster(c, states.get(c, healthy()), broken and c == CONTEXTS["COMMUNITY_CONTEXT"])
        return made[c]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        failed = live.run(contexts or CONTEXTS, cluster_for)
    return failed, buf.getvalue(), made


check("the live test's names are this checkout's coc-mask ConfigMap and key",
      SHIPPED["metadata"]["name"] == live.CONFIGMAP and live.KEY in (SHIPPED.get("data") or {}),
      f"{MANIFEST}: name {SHIPPED['metadata'].get('name')}, keys {sorted(SHIPPED.get('data') or {})}")
check("the two live tests read the same DaemonSet and annotation",
      (live.DAEMONSET, live.ANNOTATION) == (mask_live.DAEMONSET, mask_live.ANNOTATION))

print("== the healthy pair passes ==")
failed, out, _m = run()
check("both clusters as #1335 left them pass every check", not failed, f"failed: {failed}\n{out}")
check("both clusters are checked", all(f"on {n} (" in out for n, _e in live.CLUSTERS), out)
n_ok = out.count("  PASS  ")
check("each cluster runs four cluster checks and five per pod", n_ok == 2 * (4 + 2 * 5), f"{n_ok} PASS lines\n{out}")

print("== the start-up log is read from the oldest file of the running instance ==")
check("oldest_log picks the oldest rotated file of the instance, gzipped or not",
      live.oldest_log(["0.log", "0.log.20261111-120000", "0.log.20261111-080000.gz", "1.log.20261111-070000.gz"], 0)
      == "0.log.20261111-080000.gz")
check("oldest_log picks the plain file when nothing has rotated", live.oldest_log(["0.log"], 0) == "0.log")
check("oldest_log reads the instance's own restart count", live.oldest_log(["0.log.20261111-080000.gz", "1.log"], 1)
      == "1.log")
check("oldest_log finds nothing for an instance with no file", live.oldest_log(["0.log"], 1) is None)


def rotated(gz: bool) -> dict:
    s = healthy()
    for (node, d), files in s["logs"].items():
        first = files["0.log"]
        files.clear()
        files["0.log"] = later().encode()
        files["0.log.20261111-120000"] = later().encode()
        files["0.log.20261111-090000" + (".gz" if gz else "")] = gzip.compress(first) if gz else first
    return s


for gz in (True, False):
    failed, out, made = run(rotated(gz))
    oldest = "0.log.20261111-090000" + (".gz" if gz else "")
    check(f"a start-up line in the oldest rotated file{' (gzipped)' if gz else ''} passes", not failed,
          f"failed: {failed}\n{out}")
    check(f"that oldest file{' (gzipped)' if gz else ''} is the one read",
          any(r.endswith("/" + oldest) for r in made[CONTEXTS["COMMUNITY_CONTEXT"]].reads),
          str(made[CONTEXTS["COMMUNITY_CONTEXT"]].reads))


def mutate(fn) -> dict:
    s = healthy()
    fn(s)
    return s


def objs(s):
    return s["objects"]


def p0(s):
    return s["pods"][0]


def c0(s):
    return p0(s)["status"]["containerStatuses"][0]


def log0(s):
    return s["logs"][log_dir(p0(s))]


def rotated_away(s):
    files = log0(s)
    files.clear()
    files.update({"0.log": later().encode(), "0.log.20261111-120000": later().encode(),
                  "0.log.20261111-100000.gz": gzip.compress(later().encode())})


def restarted(s):
    c0(s)["restartCount"] = 1
    log0(s)["1.log"] = startup(p0(s)["metadata"]["name"]).encode()


def stray(s):
    extra = copy.deepcopy(p0(s))
    extra["metadata"].update(name="stray", uid="uid-stray", ownerReferences=[{"kind": "ReplicaSet", "uid": "x",
                                                                              "controller": True}])
    s["pods"].append(extra)
    s["pods"].pop(1)


def other_instance_only(s):
    """The node holds another instance's log (1.log), none of the running one (0.log): its line must not count."""
    log0(s)["1.log"] = log0(s).pop("0.log")


def terminating(s):
    s["pods"][1]["metadata"]["deletionTimestamp"] = "2026-11-11T07:00:00Z"


POD = f"pod {live.DAEMONSET}-p1"
# (what breaks, the community cluster's state, the label fragment that must fail)
CASES = [
    ("the ConfigMap gone", mutate(lambda s: objs(s).pop(("configmap", live.CONFIGMAP))), f"holds {live.KEY}"),
    ("the ConfigMap without its key", mutate(lambda s: objs(s)[("configmap", live.CONFIGMAP)].update(data={})),
     f"holds {live.KEY}"),
    ("no collector DaemonSet", mutate(lambda s: objs(s).pop(("daemonset", live.DAEMONSET))), "the collector DaemonSet"),
    ("the DaemonSet scheduling no node",
     mutate(lambda s: objs(s)[("daemonset", live.DAEMONSET)]["status"].update(desiredNumberScheduled=0)),
     "one collector pod on each"),
    ("a pod missing", mutate(lambda s: s["pods"].pop()), "one collector pod on each"),
    ("a pod of another owner standing in for one", mutate(stray), "one collector pod on each"),
    ("a pod being deleted standing in for one", mutate(terminating), "one collector pod on each"),
    ("a pod on an older template",
     mutate(lambda s: p0(s)["metadata"]["labels"].update({"pod-template-generation": "29"})),
     f"{POD} is on the DaemonSet's current template"),
    ("a DaemonSet with no template generation",
     mutate(lambda s: objs(s)[("daemonset", live.DAEMONSET)]["metadata"].pop("annotations")),
     f"{POD} is on the DaemonSet's current template"),
    ("a pod on an older list's checksum",
     mutate(lambda s: p0(s)["metadata"]["annotations"].update({live.ANNOTATION: "0" * 64})),
     f"{POD} rolled onto {live.ANNOTATION}"),
    ("a pod with no checksum", mutate(lambda s: p0(s)["metadata"]["annotations"].pop(live.ANNOTATION)),
     f"{POD} rolled onto {live.ANNOTATION}"),
    ("the live file changed under the pods' checksum",
     mutate(lambda s: objs(s)[("configmap", live.CONFIGMAP)]["data"].update(
         {live.KEY: objs(s)[("configmap", live.CONFIGMAP)]["data"][live.KEY] + "\n"})),
     f"{POD} rolled onto {live.ANNOTATION}"),
    ("a pod Pending", mutate(lambda s: p0(s)["status"].update(phase="Pending")), f"{POD} is Running"),
    ("the collector not ready", mutate(lambda s: c0(s).update(ready=False)), f"{POD} is Running"),
    ("no collector container status", mutate(lambda s: c0(s).update(name="other")), f"{POD} is Running"),
    ("the collector restarted once", mutate(restarted), f"{POD} has no restart"),
    ("a sidecar restarted", mutate(lambda s: p0(s)["status"]["containerStatuses"].append(
        {"name": "sidecar", "ready": True, "restartCount": 2})), f"{POD} has no restart"),
    ("no container statuses", mutate(lambda s: p0(s)["status"].update(containerStatuses=[])), f"{POD} has no restart"),
    ("a start-up log without the line",
     mutate(lambda s: log0(s).update({"0.log": later().encode()})), f"{POD} logged"),
    ("the start-up log rotated away", mutate(rotated_away), f"{POD} logged"),
    ("no log file of the running instance, only another's", mutate(other_instance_only), f"{POD} logged"),
    ("a pod with no node", mutate(lambda s: p0(s)["spec"].pop("nodeName")), f"{POD} logged"),
]

print("== each way the criterion stops holding on the community cluster fails, on its own check ==")
for what, state, fragment in CASES:
    failed, out, _m = run(state)
    named = [f for f in failed if f.startswith(COMMUNITY) and fragment in f]
    check(f"{what}: fails on the check naming {fragment!r}", bool(named), f"failed: {failed}\n{out}")
    check(f"{what}: the private cluster still passes", not [f for f in failed if not f.startswith(COMMUNITY)],
          f"failed: {failed}")

failed, out, _m = run(mutate(rotated_away))
check("a rotated-away start-up log says so", "rotated away" in out and "begins '2026-11-11T09:00" in out, out)

failed, out, _m = run(mutate(lambda s: s["logs"].clear()))
check("a log directory the node does not serve fails as a cluster that cannot be read",
      failed == [f"{COMMUNITY}: the cluster can be read"], f"failed: {failed}\n{out}")
failed, out, _m = run(contexts={**CONTEXTS, "COMMUNITY_CONTEXT": "watch-it-burn-private"})
check("a COMMUNITY_CONTEXT naming the private cluster fails as the wrong cluster",
      any(f.startswith(f"{COMMUNITY}: the context") for f in failed), f"failed: {failed}\n{out}")
failed, out, _m = run(broken=True)
check("a community cluster that cannot be read fails, and the private one is still checked",
      failed == [f"{COMMUNITY}: the cluster can be read"] and out.count("  PASS  ") == 14, f"failed: {failed}\n{out}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("test_collector_pods_ready_live.py passes the healthy pair and fails on each way #1335's criterion stops holding.")
