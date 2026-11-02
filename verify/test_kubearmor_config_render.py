# ABOUTME: Renders the kubearmor Application's two charts and holds that gitops/kubearmor-config's KubeArmorConfig is
# ABOUTME: the one kubearmor-operator's own hook would render from the same values, minus the hook (#629).
# SUITE: e2e (needs helm and the network: the operator chart is pulled at its pinned version)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why. gitops/kubearmor-config/values.yaml is a copy of kubearmor-operator's kubearmorConfig defaults, which the
operator chart's hook merged under the app's values. A chart bump that changed those defaults would leave the copy
behind without this. So the root renders the app, the operator chart renders with autoDeploy on and the config
source's values (what the hook was), and the spec must equal the local chart's, while the operator chart as the app
sets it renders no KubeArmorConfig at all. verify/test_kubearmor_config_tracked.py holds the offline half.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import CHART, REPO, values_path  # noqa: E402

HELM = shutil.which("helm")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def helm(*args: str) -> str:
    r = subprocess.run([HELM, *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAILED: helm {' '.join(args[:3])}: {r.stderr.strip()[-300:]}")
        sys.exit(1)
    return r.stdout


def configs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if isinstance(d, dict) and d.get("kind") == "KubeArmorConfig"]


if HELM is None:
    print("FAILED: helm is not on PATH; run this through verify/run-e2e-tools.sh, which fetches the pinned one")
    sys.exit(1)

root = helm("template", "lab-bootstrap", str(CHART), "-f", str(values_path("burn")), "--set", "revision=staging",
            "--set", "apps={kubearmor}")
app = next(d for d in yaml.safe_load_all(root) if d and d.get("kind") == "Application")
operator = next(s for s in app["spec"]["sources"] if s.get("chart") == "kubearmor-operator")
config = next(s for s in app["spec"]["sources"] if s.get("path") == "gitops/kubearmor-config")
ns = app["spec"]["destination"]["namespace"]

with tempfile.TemporaryDirectory() as tmp:
    work = pathlib.Path(tmp)
    helm("pull", operator["chart"], "--repo", operator["repoURL"], "--version", str(operator["targetRevision"]),
         "--untar", "--untardir", str(work))
    upstream = work / operator["chart"]
    op_vals, cfg_vals, hook_vals = work / "operator.yaml", work / "config.yaml", work / "hook.yaml"
    op_vals.write_text(yaml.safe_dump(operator["helm"]["valuesObject"]))
    cfg_vals.write_text(yaml.safe_dump(config["helm"]["valuesObject"]))
    hook_vals.write_text(yaml.safe_dump({**operator["helm"]["valuesObject"], "autoDeploy": True,
                                         **config["helm"]["valuesObject"]}))
    release = operator["helm"]["releaseName"]
    as_set = configs(helm("template", release, str(upstream), "-n", ns, "-f", str(op_vals)))
    as_hook = configs(helm("template", release, str(upstream), "-n", ns, "-f", str(hook_vals)))
    local = configs(helm("template", app["metadata"]["name"], str(REPO / config["path"]), "-n", ns, "-f", str(cfg_vals)))

print(f"== kubearmor-operator {operator['targetRevision']} and gitops/kubearmor-config ==")
check("the operator chart, as the app sets it, renders no KubeArmorConfig", not as_set, str(as_set)[:200])
check("with autoDeploy on, the operator chart renders its one config, as a hook (what this replaces)",
      len(as_hook) == 1 and "helm.sh/hook" in (as_hook[0]["metadata"].get("annotations") or {}))
check("the local chart renders one config, kubearmor-default, with no hook annotation",
      len(local) == 1 and local[0]["metadata"]["name"] == "kubearmor-default"
      and "helm.sh/hook" not in (local[0]["metadata"].get("annotations") or {}))
if len(as_hook) == 1 and len(local) == 1:
    a, b = as_hook[0]["spec"], local[0]["spec"]
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    check(f"its spec is the hook's, key for key {diff}", not diff)
    check("its name is the hook's, so Argo CD applies it over the config a cluster already has",
          local[0]["metadata"]["name"] == as_hook[0]["metadata"]["name"])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All KubeArmor config render checks passed.")
