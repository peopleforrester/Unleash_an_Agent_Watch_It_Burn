# ABOUTME: Render gate for #751: the go-spend-store Component gives guard-proxy a PVC, SPEND_STORE_PATH on it and
# ABOUTME: Recreate, changes nothing else, and must be on whenever guard-proxy no longer runs proxy.py (#738).
# SUITE: e2e (needs kubectl: every check reads the `kubectl kustomize` render of gitops/ai-layer)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. The Go guard-proxy keeps its spend in a bbolt file at SPEND_STORE_PATH (guard-proxy-agenticburn#32). It
# will not start without the variable, it fails startup while another process holds the file's flock, and on the
# container filesystem the file dies with the pod. proxy.py ignores all of it, so KubeCon runs without the
# Component and the Go cutover (#738) turns it on. The last check is what stops the cutover forgetting to.
import json, os, pathlib, shutil, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI_LAYER = REPO / "gitops/ai-layer"
COMPONENT = "go-spend-store"
STORE_PATH = "/var/lib/guard-proxy/spend.db"
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def render(path):
    out = subprocess.run(["kubectl", "kustomize", str(path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def key(d):
    return (d["kind"], d["metadata"]["name"])


def guard_proxy(docs):
    return next(d for d in docs if key(d) == ("Deployment", "guard-proxy"))


def runs_proxy_py(docs):
    c = guard_proxy(docs)["spec"]["template"]["spec"]["containers"][0]
    return c.get("command") == ["python", "/app/proxy.py"]


def store_checks(docs, label):
    """The store's whole contract on one render. Returns whether every check passed."""
    before = len(failures)
    gp = guard_proxy(docs)
    spec = gp["spec"]
    pod = spec["template"]["spec"]
    proxy = pod["containers"][0]
    check(f"{label}: container 0 is proxy, the container the Component's ops address", proxy["name"] == "proxy")
    check(f"{label}: guard-proxy is one replica, so one process holds the store", spec.get("replicas") == 1)
    # A RollingUpdate starts the new pod while the old one holds bbolt's flock, and the Go build fails startup
    # after 2 s of waiting for it. rollingUpdate alongside Recreate is refused by the API server.
    check(f"{label}: strategy is Recreate, with no rollingUpdate", spec.get("strategy") == {"type": "Recreate"})

    env = proxy.get("env", [])
    store_env = [e for e in env if e["name"] == "SPEND_STORE_PATH"]
    check(f"{label}: SPEND_STORE_PATH is set once, to {STORE_PATH}",
          len(store_env) == 1 and store_env[0].get("value") == STORE_PATH)
    check(f"{label}: SPEND_STORE_PATH is the LAST env entry, so no existing entry moves (#679)",
          bool(env) and env[-1]["name"] == "SPEND_STORE_PATH")

    store_dir = os.path.dirname(STORE_PATH)
    mount = next((m for m in proxy.get("volumeMounts", []) if m["mountPath"] == store_dir), None)
    check(f"{label}: the proxy mounts a volume at {store_dir}, read-write", mount is not None and not mount.get("readOnly"))
    vol = next((v for v in pod.get("volumes", []) if mount and v["name"] == mount["name"]), None)
    claim = ((vol or {}).get("persistentVolumeClaim") or {}).get("claimName")
    check(f"{label}: that volume is a PersistentVolumeClaim, so the file outlives the pod", claim is not None)
    pvc = next((d for d in docs if d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == claim), None)
    check(f"{label}: the claim {claim} is rendered in the bundle", pvc is not None)
    check(f"{label}: the claim is ReadWriteOnce, one node's pod at a time",
          pvc is not None and pvc["spec"].get("accessModes") == ["ReadWriteOnce"])
    check(f"{label}: the claim requests storage",
          pvc is not None and bool(pvc["spec"].get("resources", {}).get("requests", {}).get("storage")))
    sc = pod.get("securityContext", {})
    check(f"{label}: fsGroup is the proxy's group, so uid {sc.get('runAsUser')} can create the store on the volume",
          sc.get("fsGroup") is not None and sc.get("fsGroup") == sc.get("runAsGroup"))
    check(f"{label}: the root filesystem stays read-only (the store writes to the volume only)",
          proxy.get("securityContext", {}).get("readOnlyRootFilesystem") is True)
    return len(failures) == before


committed = render(AI_LAYER)
wired = COMPONENT in (yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text()).get("components") or [])

print(f"== the {COMPONENT} Component, rendered into the bundle ==")
with tempfile.TemporaryDirectory(dir=REPO) as tmp:
    copy = pathlib.Path(tmp) / "ai-layer"
    shutil.copytree(AI_LAYER, copy)
    kfile = copy / "kustomization.yaml"
    k = yaml.safe_load(kfile.read_text())
    if not wired:
        k["components"] = (k.get("components") or []) + [COMPONENT]
        kfile.write_text(yaml.safe_dump(k, sort_keys=False))
    with_store = render(copy)
    k["components"] = [c for c in k.get("components") or [] if c != COMPONENT] or None
    if k["components"] is None:
        del k["components"]
    kfile.write_text(yaml.safe_dump(k, sort_keys=False))
    without_store = render(copy)

store_checks(with_store, "with the Component")

print("== the Component changes guard-proxy's store and nothing else ==")
added = {key(d) for d in with_store} - {key(d) for d in without_store}
check(f"it adds exactly the claim (added: {sorted(added)})", added == {("PersistentVolumeClaim", "guard-proxy-spend")})
check("it removes nothing", not ({key(d) for d in without_store} - {key(d) for d in with_store}))
others = {key(d): d for d in without_store if key(d) != ("Deployment", "guard-proxy")}
check("every other object renders identically",
      all(others[key(d)] == d for d in with_store if key(d) in others))
before_env = [e["name"] for e in guard_proxy(without_store)["spec"]["template"]["spec"]["containers"][0]["env"]]
after_env = [e["name"] for e in guard_proxy(with_store)["spec"]["template"]["spec"]["containers"][0]["env"]]
check("the existing env entries keep their order", after_env == before_env + ["SPEND_STORE_PATH"])
gp_before = guard_proxy(without_store)["spec"]["template"]["spec"]["containers"][0]
gp_after = guard_proxy(with_store)["spec"]["template"]["spec"]["containers"][0]
check("the proxy's image and command are untouched (the cutover changes those, not this)",
      (gp_before["image"], gp_before.get("command")) == (gp_after["image"], gp_after.get("command")))

print("== Argo CD syncs SPEND_STORE_PATH from git ==")
# ai-layer ignores live drift on the toggled env entries by name. The store path is not a toggle: if an ignore
# covered it, a path change in git would never reach the pod.
app = yaml.safe_load((REPO / "gitops/bootstrap/apps/ai-layer.yaml").read_text())
gp = guard_proxy(with_store)
exprs = [e for ig in app["spec"].get("ignoreDifferences", [])
         if ig.get("kind") == "Deployment" and ig.get("name") == "guard-proxy" for e in ig.get("jqPathExpressions", [])]
check("ai-layer has the guard-proxy env ignore this check reads", bool(exprs))
for expr in exprs:
    out = subprocess.run(["jq", "-c", expr], input=json.dumps(gp), capture_output=True, text=True, check=True).stdout
    selected = [json.loads(line) for line in out.splitlines() if line.strip()]
    check("the ignore expression does not select SPEND_STORE_PATH",
          not any(isinstance(e, dict) and e.get("name") == "SPEND_STORE_PATH" for e in selected))

print("== the committed bundle: a guard-proxy that does not run proxy.py carries the store ==")
py = runs_proxy_py(committed)
print(f"  committed guard-proxy runs proxy.py: {py}; {COMPONENT} listed in components: {wired}")
if py:
    # proxy.py ignores SPEND_STORE_PATH, so the store is optional while it runs. The KubeCon bundle must still
    # render the way it did before this Component existed, or KubeCon's chat path would wait on an EBS volume.
    check("while proxy.py runs, the committed bundle renders as the bundle without the Component, or with it",
          committed in (without_store, with_store))
else:
    check(f"the Go build runs, so the committed bundle carries the store ({COMPONENT} in components)",
          store_checks(committed, "committed bundle"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All guard-proxy spend store checks passed.")
