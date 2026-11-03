# ABOUTME: Offline checks for verify/test_otel_trace_id_fix_live.py (#812): its checks pass on a fake staging and a fake
# ABOUTME: pair of clusters running #783's fix, and fail on each way the fix can be off staging or not applied on a cluster.
"""test_otel_trace_id_fix_live.py is the live test for #783's criterion "the fix is on staging and applied to
watch-it-burn-community and watch-it-burn-private". It needs GitHub and both clusters. This runs its `run` against a fake
git and fake clusters, so the healthy pair passes and each way the criterion can stop holding fails it: the fix
reverted on staging or moved after the span-id statement, staging without the commit, a cluster's Application reading
another branch, out of sync, degraded or failed, synced at a revision off staging or older than the fix, the collector
not rolled out, the live ConfigMap without the statement or with traces/llmobs rewired, a context naming the wrong
cluster, and an Application or DaemonSet that is not there. The healthy fakes are built from this checkout's own
collector values (collector_render), so a change here that drops the fix fails the healthy case too. Nothing here
touches the network or a cluster.
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
import collector_render as cr  # noqa: E402
import test_otel_trace_id_fix_live as live  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


BEFORE = "b" * 40      # a staging commit from before the fix
STAGING = "5" * 40     # staging's head
BRANCH_REV = "e" * 40  # a commit on some other branch, never on staging
FIX = live.FIX_COMMIT
PROFILE = {"watch-it-burn-community": "burn", "watch-it-burn-private": "instructor"}
CONTEXTS = {"COMMUNITY_CONTEXT": "arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-community",
            "PRIVATE_CONTEXT": "watch-it-burn-private"}
TRACKED = ["gitops/otel-collector/values.yaml", "gitops/otel-collector/values-burn.yaml",
           "gitops/bootstrap/apps/otel-collector.yaml", "gitops/bootstrap/apps/otel-collector-burn.yaml"]


def checkout_files() -> dict[str, str]:
    return {p: (REPO / p).read_text(encoding="utf-8") for p in TRACKED}


def without_fix(text: str) -> str:
    """values.yaml with #783's statement taken out, as a revert of 67c956a leaves it."""
    lines = [ln for ln in text.splitlines(keepends=True) if live.FIX_STATEMENT not in ln]
    assert len(lines) == len(text.splitlines()) - 1, "values.yaml holds the fix statement exactly once"
    return "".join(lines)


class FakeGit(live.Git):
    """Commits and their ancestors, and staging's files. History: BEFORE, then FIX, then STAGING."""

    def __init__(self, files: dict[str, str] | None = None, history: dict[str, set[str]] | None = None,
                 fetch_error: str = "") -> None:
        self.files = checkout_files() if files is None else files
        self.history = history if history is not None else {
            BEFORE: {BEFORE}, FIX: {BEFORE, FIX}, STAGING: {BEFORE, FIX, STAGING}}
        self.fetch_error = fetch_error

    def fetch_staging(self) -> str:
        if self.fetch_error:
            raise RuntimeError(self.fetch_error)
        return STAGING

    def has(self, rev: str) -> bool:
        return rev in self.history

    def is_ancestor(self, older: str, newer: str) -> bool:
        return older in self.history.get(newer, set())

    def show(self, rev: str, path: str) -> str | None:
        return self.files.get(path) if rev == STAGING else None


def application(rev: str = STAGING, target: str = "staging", sync: str = "Synced", health: str = "Healthy",
                phase: str = "Succeeded") -> dict:
    return {"metadata": {"name": "otel-collector", "namespace": "argocd"},
            "spec": {"sources": [
                {"repoURL": "https://open-telemetry.github.io/opentelemetry-helm-charts",
                 "chart": "opentelemetry-collector", "targetRevision": "0.173.1"},
                {"repoURL": live.REPO_URL, "targetRevision": target, "ref": "values"}]},
            "status": {"sync": {"status": sync, "revisions": ["0.173.1", rev]}, "health": {"status": health},
                       "operationState": {"phase": phase, "message": "successfully synced",
                                          "syncResult": {"revisions": ["0.173.1", rev]}}}}


def daemonset(overlay_name: str, desired: int = 2, updated: int = 2, available: int = 2) -> dict:
    return {"metadata": {"name": live.DAEMONSET, "generation": 4},
            "spec": {"template": {"spec": {"volumes": [
                {"name": "opentelemetry-collector-configmap",
                 "configMap": {"name": live.DAEMONSET, "items": [{"key": "relay", "path": "relay.yaml"}]}},
                {"name": "datadog-overlay", "configMap": {"name": overlay_name}}]}}},
            "status": {"observedGeneration": 4, "desiredNumberScheduled": desired, "updatedNumberScheduled": updated,
                       "numberAvailable": available}}


class FakeCluster(live.Cluster):
    """A cluster running the collector this checkout renders for its profile, unless an object is replaced."""

    def __init__(self, name: str, **replace) -> None:
        super().__init__(name)
        vals = cr.helm_values(PROFILE[name])
        overlay = cr.overlay_configmap(vals)
        relay = copy.deepcopy(vals["config"])
        self.objects = {("application", "otel-collector"): application(),
                        ("daemonset", live.DAEMONSET): daemonset(overlay["metadata"]["name"]),
                        ("configmap", live.DAEMONSET): {"data": {"relay": yaml.safe_dump(relay)}},
                        ("configmap", overlay["metadata"]["name"]): overlay}
        self.relay = relay
        for key, obj in replace.items():
            self.objects[{"app": ("application", "otel-collector"), "ds": ("daemonset", live.DAEMONSET),
                          "relay": ("configmap", live.DAEMONSET)}[key]] = obj
        self.calls: list[tuple[str, str, str]] = []

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        self.calls.append((kind, name, namespace))
        return copy.deepcopy(self.objects.get((kind, name)))


def relay_with(mutate) -> dict:
    """The community cluster's relay ConfigMap with `mutate(config)` applied."""
    config = copy.deepcopy(cr.helm_values("burn")["config"])
    mutate(config)
    return {"data": {"relay": yaml.safe_dump(config)}}


def run_case(git: FakeGit | None = None, community: FakeCluster | None = None, private: FakeCluster | None = None,
             contexts: dict[str, str] | None = None) -> list[str]:
    git = git or FakeGit()
    by_ctx = {}
    ctxs = contexts or CONTEXTS
    by_ctx[ctxs["COMMUNITY_CONTEXT"]] = community or FakeCluster("watch-it-burn-community")
    by_ctx[ctxs["PRIVATE_CONTEXT"]] = private or FakeCluster("watch-it-burn-private")
    # The live test's own PASS/FAIL lines stay out of this output; what it failed is returned and checked below.
    with contextlib.redirect_stdout(io.StringIO()):
        return live.run(ctxs, git, lambda c: by_ctx[c])


def fails(label: str, failed: list[str], expect: str) -> None:
    check(f"{label}: fails, on '{expect}'", any(expect in f for f in failed), f"failed: {failed}")


print("== the healthy pair passes ==")
ok = run_case()
check("staging with the fix and both clusters synced to it and rolled out: no check fails", ok == [], f"failed: {ok}")
check("the fix statement is in this checkout's values.yaml once",
      (REPO / "gitops/otel-collector/values.yaml").read_text().count(live.FIX_STATEMENT) == 1)
check("FIX_COMMIT is 67c956a, #783's fix", live.FIX_COMMIT.startswith("67c956a"))
cl = FakeCluster("watch-it-burn-private")
run_case(private=cl)
check("the live test reads only the Application, the DaemonSet and its two ConfigMaps",
      {k for k, _n, _s in cl.calls} == {"application", "daemonset", "configmap"} and len(cl.calls) == 4, str(cl.calls))

print("\n== staging stops holding the fix ==")
reverted = checkout_files()
reverted["gitops/otel-collector/values.yaml"] = without_fix(reverted["gitops/otel-collector/values.yaml"])
fails("the statement reverted on staging", run_case(git=FakeGit(files=reverted)),
      "staging's collector for watch-it-burn-community")
fails("the statement reverted on staging", run_case(git=FakeGit(files=reverted)),
      "staging's collector for watch-it-burn-private")
moved = checkout_files()
v = moved["gitops/otel-collector/values.yaml"]
fix_line = next(ln for ln in v.splitlines(keepends=True) if live.FIX_STATEMENT in ln)
v = v.replace(fix_line, "", 1)
anchor = next(ln for ln in v.splitlines(keepends=True) if 'delete_key(attributes, "dd_llmobs_enabled")' in ln)
moved["gitops/otel-collector/values.yaml"] = v.replace(anchor, anchor + fix_line, 1)
fails("the statement moved after another on staging", run_case(git=FakeGit(files=moved)),
      "staging's collector for watch-it-burn-private")
burn_off = checkout_files()
burn = yaml.safe_load(burn_off["gitops/otel-collector/values-burn.yaml"])
burn.setdefault("config", {}).setdefault("service", {}).setdefault("pipelines", {})["traces/llmobs"] = {
    "receivers": ["forward/llmobs"], "processors": ["filter/llmobs_one_root"], "exporters": ["debug"]}
burn_off["gitops/otel-collector/values-burn.yaml"] = yaml.safe_dump(burn)
failed = run_case(git=FakeGit(files=burn_off))
fails("burn's values drop the processor from traces/llmobs on staging", failed,
      "staging's collector for watch-it-burn-community")
check("  and only the burn profile's staging check fails for it",
      not any("staging's collector for watch-it-burn-private" in f for f in failed), str(failed))
no_fix_history = {BEFORE: {BEFORE}, STAGING: {BEFORE, STAGING}}
fails("staging's history without 67c956a", run_case(git=FakeGit(history=no_fix_history)),
      "staging (555555555555) contains #783's fix")
fails("staging cannot be fetched", run_case(git=FakeGit(fetch_error="could not resolve host: github.com")),
      "GitHub's staging can be fetched")

print("\n== a cluster stops running it ==")
for name, kw in (("watch-it-burn-community", "community"), ("watch-it-burn-private", "private")):
    def case(**replace):
        return run_case(**{kw: FakeCluster(name, **replace)})
    fails(f"{name}'s Application reads main", case(app=application(target="main")),
          f"{name}: otel-collector reads its collector values from this repo's staging")
    fails(f"{name}'s Application OutOfSync", case(app=application(sync="OutOfSync")),
          f"{name}: otel-collector is Synced and Healthy")
    fails(f"{name}'s Application Degraded", case(app=application(health="Degraded")),
          f"{name}: otel-collector is Synced and Healthy")
    fails(f"{name}'s last sync Failed", case(app=application(phase="Failed")),
          f"{name}: otel-collector is Synced and Healthy")
    fails(f"{name} synced at a staging commit from before the fix", case(app=application(rev=BEFORE)),
          f"{name}: that revision contains #783's fix")
    fails(f"{name} synced at a commit that is not on staging", case(app=application(rev=BRANCH_REV)),
          f"{name}: otel-collector is synced at a revision on staging")
    fails(f"{name} with no Application", case(app=None), f"{name}: Argo CD has the otel-collector Application")
    fails(f"{name}'s collector half rolled out", case(ds=daemonset("otel-collector-datadog", updated=1)),
          f"{name}: the collector's current template runs")
    fails(f"{name}'s collector with a pod unavailable", case(ds=daemonset("otel-collector-datadog", available=1)),
          f"{name}: the collector's current template runs")
    fails(f"{name} with no collector DaemonSet", case(ds=None), f"{name}: the collector DaemonSet")


def drop_fix(c: dict) -> None:
    c["processors"]["transform/llmobs_one_root"]["trace_statements"][0]["statements"].remove(live.FIX_STATEMENT)


def unwire(c: dict) -> None:
    c["service"]["pipelines"]["traces/llmobs"]["processors"].remove("transform/llmobs_one_root")


def no_forward(c: dict) -> None:
    c["service"]["pipelines"]["traces"]["exporters"].remove("forward/llmobs")


for label, mutate in (("without the statement", drop_fix), ("with traces/llmobs not running the processor", unwire)):
    fails(f"the community collector's live relay config {label}",
          run_case(community=FakeCluster("watch-it-burn-community", relay=relay_with(mutate))),
          "watch-it-burn-community: the collector's live config runs the fix")
fails("the live relay config not forwarding a copy, with no Datadog overlay to add it",
      run_case(community=FakeCluster("watch-it-burn-community", relay=relay_with(no_forward))),
      "watch-it-burn-community: the collector's live config runs the fix")
unforwarded = yaml.safe_load(relay_with(no_forward)["data"]["relay"])
burn_overlay = cr.overlay_configmap(cr.helm_values("burn"))
check("  and it names relay.yaml alone, the config a cluster with no datadog-secret runs",
      any(p.endswith("relay.yaml: the traces pipeline does not export forward/llmobs, so traces/llmobs gets no copy")
          for p in live.config_problems(unforwarded, burn_overlay, "x")))
nooverlay = FakeCluster("watch-it-burn-private")
del nooverlay.objects[("configmap", "otel-collector-datadog")]
fails("the private cluster with no Datadog overlay ConfigMap", run_case(private=nooverlay),
      "watch-it-burn-private: the collector's live config runs the fix")
check("  and it says the overlay ConfigMap is missing",
      any("there is no Datadog overlay ConfigMap" in p
          for p in live.config_problems(cr.helm_values("instructor")["config"], None, "x")))
fails("a relay ConfigMap with no relay key",
      run_case(private=FakeCluster("watch-it-burn-private", relay={"data": {}})),
      "watch-it-burn-private: the collector's live config runs the fix")

print("\n== the contexts ==")
swapped = {"COMMUNITY_CONTEXT": "watch-it-burn-private", "PRIVATE_CONTEXT": "watch-it-burn-community"}
failed = run_case(contexts=swapped)
fails("the two contexts swapped", failed, "watch-it-burn-community: the context 'watch-it-burn-private' is that cluster")
fails("the two contexts swapped", failed, "watch-it-burn-private: the context 'watch-it-burn-community' is that cluster")
lookalike = {"COMMUNITY_CONTEXT": "watch-it-burn-community-b01", "PRIVATE_CONTEXT": "watch-it-burn-private"}
fails("a standby whose name only starts with the cluster's", run_case(contexts=lookalike),
      "watch-it-burn-community: the context 'watch-it-burn-community-b01' is that cluster")

print("\n== the prerequisites ==")
text = (HERE / "test_otel_trace_id_fix_live.py").read_text(encoding="utf-8")
check("the live test is in the E2E suite, not the offline one", "\n# SUITE: e2e\n" in text)
run_e2e = (HERE / "run-e2e.sh").read_text(encoding="utf-8")
check("run-e2e.sh requires PRIVATE_CONTEXT before anything runs, as it does COMMUNITY_CONTEXT",
      'if [[ -z "${PRIVATE_CONTEXT:-}" ]]; then' in run_e2e
      and run_e2e.index("PRIVATE_CONTEXT is not set") < run_e2e.index("E2E SUITE CANNOT RUN"))

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll test_otel_trace_id_fix_live.py offline checks passed.")
