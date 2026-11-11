# ABOUTME: Offline checks for verify/test_collector_relay_live.py (#1340): its checks pass on a fake pair of clusters whose
# ABOUTME: relay is this checkout's render, and fail on each way #1335's relay criterion can stop holding on one of them.
"""test_collector_relay_live.py is the live test for #1335's criterion "on both clusters the relay ConfigMap no longer
defines transform/coc_mask and reads about 25 KB". It needs both clusters. This runs its `run` against fake clusters,
so the healthy pair passes and each way the criterion can stop holding fails it, on the check that names that way: a
context naming the wrong cluster; the ConfigMap gone or put there by another Application; no relay key, a relay that
is not YAML or not a map; the mask defined in the relay, written back as #1328 had it (which also fails the size) or as
a stub (which does not); the traces pipeline no longer naming the mask; a relay padded past the upper bound or cut
under the lower one. The bounds are held at their edges.

The healthy fakes carry this checkout's relay as helm writes it (values `config`, every alias written out): burn's on
the community cluster and instructor's on the private one, the profiles their `otel-collector` Applications run. So a
change that grows a profile's relay past the band, or puts the mask back into it, fails here before it reaches a
cluster. A cluster that cannot be read fails, and the other cluster is still checked. Nothing here touches a cluster.
"""
from __future__ import annotations

import contextlib
import copy
import io
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import test_collector_relay_live as live  # noqa: E402

# Each profile's `otel-collector` Application. The values are read here, not through collector_render.py, which 30
# other tests import already: a 31st would make it a shared helper whose every change runs the whole suite.
PROFILE_APP = {"instructor": "gitops/bootstrap/apps/otel-collector.yaml",
               "attendee": "gitops/bootstrap/apps/otel-collector-attendee.yaml",
               "burn": "gitops/bootstrap/apps/otel-collector-burn.yaml"}
COC_MASK_MANIFEST = "gitops/otel-collector/coc-mask/configmap.yaml"

failures: list[str] = []


def deep_merge(base, over):
    """Maps merged recursively; anything else in `over` replaces `base`. Helm's rule."""
    if not (isinstance(base, dict) and isinstance(over, dict)):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
    return out


def relay_values(profile: str) -> dict:
    """values `config` for the profile: the chart source's valueFiles of its Application, merged in order."""
    app = yaml.safe_load((REPO / PROFILE_APP[profile]).read_text(encoding="utf-8"))
    chart = [s for s in app["spec"]["sources"] if s.get("chart") == "opentelemetry-collector"]
    assert len(chart) == 1, f"{PROFILE_APP[profile]}: no single opentelemetry-collector chart source"
    vals: dict = {}
    for f in chart[0]["helm"]["valueFiles"]:
        vals = deep_merge(vals, yaml.safe_load((REPO / f.replace("$values/", "")).read_text(encoding="utf-8")) or {})
    return vals["config"]


def mask_definition() -> dict:
    """transform/coc_mask as the coc-mask ConfigMap defines it."""
    cm = yaml.safe_load((REPO / COC_MASK_MANIFEST).read_text(encoding="utf-8"))
    return yaml.safe_load(cm["data"]["coc-mask.yaml"])["processors"][live.MASK]


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CONTEXTS = {"COMMUNITY_CONTEXT": "arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-community",
            "PRIVATE_CONTEXT": "watch-it-burn-private"}
COMMUNITY = "watch-it-burn-community"
PROFILE = {CONTEXTS["COMMUNITY_CONTEXT"]: "burn", CONTEXTS["PRIVATE_CONTEXT"]: "instructor"}


class _Expanded(yaml.SafeDumper):
    """Writes an object as often as the config holds it, as helm's toYaml does, where PyYAML would write an alias."""

    def ignore_aliases(self, data) -> bool:
        return True


def dump(config: dict) -> str:
    return yaml.dump(config, Dumper=_Expanded, sort_keys=False, width=10 ** 9)


def healthy(profile: str) -> dict[tuple[str, str], dict]:
    """One cluster's relay ConfigMap as #1335 left it: this checkout's render of the profile, Argo CD's."""
    cm = {"metadata": {"name": live.CONFIGMAP, "namespace": live.NAMESPACE,
                       "annotations": {"argocd.argoproj.io/tracking-id": live.TRACKING}},
          "data": {live.KEY: dump(relay_values(profile))}}
    return {("configmap", live.CONFIGMAP): cm}


class FakeCluster(live.Cluster):
    def __init__(self, context: str, objects: dict | None, broken: bool = False) -> None:
        super().__init__(context)
        self.objects, self.broken = objects, broken

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        if self.broken:
            raise RuntimeError(f"kubectl --context {self.context} -n {namespace} get {kind} {name}: connection refused")
        if namespace != live.NAMESPACE:
            return None
        return copy.deepcopy(self.objects.get((kind, name)))


def run(community: dict | None = None, contexts: dict | None = None, broken: bool = False) -> tuple[list[str], str]:
    """`run` with the private cluster healthy and the community one as given; the failed labels and the output."""
    objs = {CONTEXTS["COMMUNITY_CONTEXT"]: community if community is not None else healthy("burn"),
            CONTEXTS["PRIVATE_CONTEXT"]: healthy("instructor")}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        failed = live.run(contexts or CONTEXTS,
                          lambda c: FakeCluster(c, objs.get(c, {}), broken and c == CONTEXTS["COMMUNITY_CONTEXT"]))
    return failed, buf.getvalue()


print("== this checkout's relays ==")
for profile in PROFILE_APP:
    config = relay_values(profile)
    size = len(dump(config).encode("utf-8"))
    check(f"{profile}: the relay renders to {size:,} bytes, inside {live.LOW_BYTES:,} to {live.HIGH_BYTES:,}",
          live.LOW_BYTES <= size <= live.HIGH_BYTES, "the live test would fail once Argo CD syncs this")
    check(f"{profile}: the relay names {live.MASK} in the traces pipeline and defines it nowhere",
          live.MASK in config["service"]["pipelines"]["traces"]["processors"]
          and live.MASK not in config.get("processors", {}))

print("== the healthy pair passes ==")
failed, out = run()
check("both clusters as #1335 left them pass every check", not failed, f"failed: {failed}\n{out}")
check("both clusters are checked", all(f"on {n} (" in out for n, _e in live.CLUSTERS), out)
n_ok = out.count("  PASS  ")
check("each cluster runs all seven checks", n_ok == 14, f"{n_ok} PASS lines\n{out}")


def mutate(fn) -> dict:
    objs = healthy("burn")
    fn(objs)
    return objs


def cm(o):
    return o[("configmap", live.CONFIGMAP)]


def relay_config() -> dict:
    return relay_values("burn")


def with_relay(config: dict, pad: int = 0):
    """A mutator writing `config` as the relay, then a comment of `pad` bytes, which changes the size and not the map."""
    text = dump(config) + ("#" * (pad - 1) + "\n" if pad else "")
    return lambda o: cm(o)["data"].update({live.KEY: text})


def padded_to(size: int):
    """A mutator writing burn's relay padded to exactly `size` bytes."""
    base = len(dump(relay_config()).encode("utf-8"))
    assert size > base + 1, f"burn's relay is {base:,} bytes, too big to pad to {size:,}"
    return with_relay(relay_config(), size - base)


def mask_inline() -> dict:
    """#1328's layout: the full mask written back into the relay's processors."""
    c = relay_config()
    c["processors"][live.MASK] = mask_definition()
    return c


def mask_stub() -> dict:
    c = relay_config()
    c["processors"][live.MASK] = {"error_mode": "ignore", "trace_statements": []}
    return c


def mask_unrun() -> dict:
    c = relay_config()
    procs = c["service"]["pipelines"]["traces"]["processors"]
    assert live.MASK in procs, f"burn's traces pipeline no longer names {live.MASK}"
    procs.remove(live.MASK)
    return c


def cut_short() -> dict:
    return {"receivers": {"otlp": {}}, "processors": {"batch": {}}, "exporters": {"debug": {}},
            "service": {"pipelines": {"traces": {"receivers": ["otlp"], "processors": ["batch", live.MASK],
                                                 "exporters": ["debug"]}}}}


check("the mask written back in is over the upper bound by far",
      len(dump(mask_inline()).encode("utf-8")) > 10 * live.HIGH_BYTES, f"{len(dump(mask_inline())):,} bytes")

DEFINES, NAMES, SIZE = f"does not define {live.MASK}", f"still names {live.MASK}", "reads about"

# (what breaks, the community cluster's objects, the label fragments that must fail, those that must not)
CASES = [
    ("the relay ConfigMap gone", mutate(lambda o: o.pop(("configmap", live.CONFIGMAP))),
     [f"{live.CONFIGMAP} exists"], []),
    ("the relay ConfigMap put there by another Application",
     mutate(lambda o: cm(o)["metadata"]["annotations"].update(
         {"argocd.argoproj.io/tracking-id": f"stray:/ConfigMap:{live.NAMESPACE}/{live.CONFIGMAP}"})),
     ["put there by the otel-collector Application"], []),
    ("the relay ConfigMap with no tracking id", mutate(lambda o: cm(o)["metadata"].pop("annotations")),
     ["put there by the otel-collector Application"], []),
    ("the ConfigMap without its relay key", mutate(lambda o: cm(o).update(data={"other": "x: 1\n"})),
     ["parses as a YAML map"], []),
    ("the relay not YAML", mutate(lambda o: cm(o)["data"].update({live.KEY: "processors: [unclosed"})),
     ["parses as a YAML map"], []),
    ("the relay a list", mutate(lambda o: cm(o)["data"].update({live.KEY: "- processors\n"})),
     ["parses as a YAML map"], []),
    ("the mask written back into the relay as #1328 had it", mutate(with_relay(mask_inline())), [DEFINES, SIZE], [NAMES]),
    ("a stub mask defined in the relay", mutate(with_relay(mask_stub())), [DEFINES], [NAMES, SIZE]),
    ("the traces pipeline no longer naming the mask", mutate(with_relay(mask_unrun())), [NAMES], [DEFINES, SIZE]),
    ("the relay one byte over the upper bound", mutate(padded_to(live.HIGH_BYTES + 1)), [SIZE], [DEFINES, NAMES]),
    ("the relay cut short", mutate(with_relay(cut_short())), [SIZE], [DEFINES, NAMES]),
]
check("the cut-short relay is one byte or more under the lower bound",
      len(dump(cut_short()).encode("utf-8")) < live.LOW_BYTES)

print("== each way the criterion stops holding on the community cluster fails, on its own check ==")
for what, objs, must, must_not in CASES:
    failed, out = run(objs)
    ours = [f for f in failed if f.startswith(COMMUNITY)]
    for fragment in must:
        check(f"{what}: fails on the check naming {fragment!r}", any(fragment in f for f in ours),
              f"failed: {failed}\n{out}")
    for fragment in must_not:
        check(f"{what}: passes the check naming {fragment!r}", not any(fragment in f for f in ours),
              f"failed: {failed}\n{out}")
    check(f"{what}: the private cluster still passes", not [f for f in failed if not f.startswith(COMMUNITY)],
          f"failed: {failed}")

print("== the bounds hold at their edges ==")
for size, ok in ((live.HIGH_BYTES, True), (live.HIGH_BYTES + 1, False)):
    failed, out = run(mutate(padded_to(size)))
    check(f"a relay of {size:,} bytes {'passes' if ok else 'fails'}", (not failed) == ok, f"failed: {failed}\n{out}")
lean = relay_config()
lean["processors"] = {k: v for k, v in lean["processors"].items() if k in ("batch", "memory_limiter")}
lean_size = len(dump(lean).encode("utf-8"))
for size, ok in ((live.LOW_BYTES - 1, False), (live.LOW_BYTES, True)):
    assert size > lean_size + 1, f"the lean relay is {lean_size:,} bytes, too big to pad to {size:,}"
    objs = mutate(with_relay(lean, size - lean_size))
    failed, out = run(objs)
    check(f"a relay of {size:,} bytes {'passes' if ok else 'fails'}",
          len(cm(objs)["data"][live.KEY].encode("utf-8")) == size and (not failed) == ok, f"failed: {failed}\n{out}")

failed, out = run(contexts={**CONTEXTS, "COMMUNITY_CONTEXT": "watch-it-burn-private"})
check("a COMMUNITY_CONTEXT naming the private cluster fails as the wrong cluster",
      any(f.startswith(f"{COMMUNITY}: the context") for f in failed), f"failed: {failed}\n{out}")
failed, out = run(broken=True)
check("a community cluster that cannot be read fails, and the private one is still checked",
      failed == [f"{COMMUNITY}: the cluster can be read"] and out.count("  PASS  ") == 7, f"failed: {failed}\n{out}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("test_collector_relay_live.py passes the healthy pair and fails on each way #1335's relay criterion stops holding.")
