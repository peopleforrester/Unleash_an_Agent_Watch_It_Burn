# ABOUTME: A fresh `terraform init -lockfile=readonly` of each committed root (in a clean copy, no cached
# ABOUTME: .terraform/) succeeds against its committed lock and leaves the lock byte-for-byte unchanged.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and network to registry.terraform.io)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# #468: the cluster root's lock pinned aws 6.51.0 while the EKS module it resolved needed >= 6.59.0. That only
# showed on a machine with no older module cached, so this runs every init in an empty temp directory.
# -lockfile=readonly makes a lock that needs changing an error instead of a silent rewrite.
import os, pathlib, shutil, subprocess, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
ROOTS = ["infra/terraform/aws/cluster", "infra/terraform/aws/network", "infra/org/boundary", "infra/terraform/dashboards"]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)

env = {**os.environ, "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}
env.pop("TF_DATA_DIR", None)
env.pop("TF_PLUGIN_CACHE_DIR", None)
for root in ROOTS:
    src = REPO / root
    print(root)
    with tempfile.TemporaryDirectory(prefix="tf-lock-init-") as tmp:
        work = pathlib.Path(tmp)
        for f in list(src.glob("*.tf")) + [src / ".terraform.lock.hcl"]:
            shutil.copy2(f, work / f.name)
        r = subprocess.run([exe, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color"],
                           cwd=work, env=env, capture_output=True, text=True)
        check("fresh init succeeds against the committed lock", r.returncode == 0, (r.stdout + r.stderr)[-2000:])
        check("the lock is unchanged by init",
              (work / ".terraform.lock.hcl").read_bytes() == (src / ".terraform.lock.hcl").read_bytes())

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL TERRAFORM LOCK-INIT CHECKS GREEN")
