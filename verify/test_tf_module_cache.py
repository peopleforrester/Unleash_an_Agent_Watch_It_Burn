# ABOUTME: Holds verify/tf_module_cache.py (#1246) on a made-up install: the key reads only module sources and versions, a
# ABOUTME: kept copy seeds a fresh directory, a changed copy fails naming both sums and stays put. Offline, no terraform.
"""Each case uses a cache root outside every worktree (artifact_cache.scratch_dir) and a .terraform/modules it writes
itself, so nothing here reads the network, terraform or the host's own cache. The tools-tier test
test_iam_policy_structural.py holds the same module on a real init of the cluster root, with the network closed."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402
import tf_module_cache as mc  # noqa: E402

for var in ("ARTIFACT_FETCH_LOG", "HECATON_TOOLS_CACHE", "WIB_ARTIFACT_CACHE"):
    os.environ.pop(var, None)

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def raises(fn, exc) -> str | None:
    try:
        fn()
    except exc as e:
        return str(e)
    return None


MAIN = '''terraform {
  required_version = ">= 1.5"
}

module "b_pod" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12.0"

  name                     = "b"
  permissions_boundary_arn = "arn:aws:iam::1:policy/x"
}

module "a_eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.29.0"
  inner = {
    source = "not/the/module"
  }
}

resource "null_resource" "x" {}
'''

base = ac.scratch_dir("tf-module-cache-test-")
root = base / "cache"
env = {"WIB_ARTIFACT_CACHE": str(root), "HOME": str(base)}
try:
    print("the key")
    cs = mc.calls(MAIN)
    check("it reads each block's top-level source and version, sorted by name, and no nested `source`",
          cs == [("a_eks", "terraform-aws-modules/eks/aws", "~> 21.29.0"),
                 ("b_pod", "terraform-aws-modules/eks-pod-identity/aws", "~> 1.12.0")], cs)
    k = mc.key(MAIN)
    check("it is a SHA-256", k is not None and ac.SHA256.fullmatch(k) is not None, k)
    check("an edit inside a block that leaves source and version alone keeps the key (break_rules' kind)",
          mc.key(MAIN.replace('  permissions_boundary_arn = "arn:aws:iam::1:policy/x"\n', "")) == k)
    check("a resource edit keeps the key", mc.key(MAIN.replace('"x" {}', '"y" {}')) == k)
    check("a new version constraint is a new key", mc.key(MAIN.replace("~> 1.12.0", "~> 1.13.0")) not in (k, None))
    check("a new source is a new key",
          mc.key(MAIN.replace("eks-pod-identity/aws", "iam/aws//modules/iam-role")) not in (k, None))
    check("a renamed call is a new key", mc.key(MAIN.replace('module "b_pod"', 'module "c_pod"')) not in (k, None))
    check("a root with no module call has no key", mc.key('resource "null_resource" "x" {}\n') is None)
    msg = raises(lambda: mc.key('module "x" {\n  version = "1"\n}\n'), mc.ModuleCacheError)
    check("a block with no source line fails, naming the module", msg is not None and '"x"' in msg, msg)
    msg = raises(lambda: mc.key(MAIN + 'module  "odd"   {\n  source = "a/b/c"\n}\n'), mc.ModuleCacheError)
    check("a module block the key cannot read fails rather than being left out of it", msg is not None, msg)
    real = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
    names = [n for n, _, _ in mc.calls(real)]
    check("the cluster root's six module calls are all read", names == sorted(
        ["eks", "ebs_csi_pod_identity", "aws_lb_controller_pod_identity", "eso_pod_identity",
         "agent_bedrock_pod_identity", "tutor_bedrock_pod_identity"]), names)

    print("a miss, then a kept copy")
    first = base / "first"
    mods = first / ".terraform" / "modules"
    (mods / "a_eks" / ".git").mkdir(parents=True)
    (mods / "a_eks" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (mods / "a_eks" / "main.tf").write_text("# eks\n")
    (mods / "a_eks" / "modules" / "kms").mkdir(parents=True)
    (mods / "a_eks" / "modules" / "kms" / "main.tf").write_text("# kms\n")
    os.symlink("main.tf", mods / "a_eks" / "link.tf")
    (mods / "b_pod").mkdir()
    (mods / "b_pod" / "main.tf").write_text("# pod identity\n")
    (mods / "modules.json").write_text('{"Modules":[]}\n')
    check("seed() on a cold cache is a miss", mc.seed(base / "cold", MAIN, env=env) is False)
    check("a miss writes nothing into the working directory", not (base / "cold").exists())
    e = mc.store(first, MAIN, env=env)
    check("store() keeps the install under <root>/terraform-modules/<key>", e == root / "terraform-modules" / k, e)
    check("the kept copy leaves each module's .git out", not (e / "modules" / "a_eks" / ".git").exists())
    check("the kept copy keeps a symlink as a symlink", (e / "modules" / "a_eks" / "link.tf").is_symlink())
    log = (root / "fetch.log").read_text(encoding="utf-8").splitlines()
    check("store() logs one line naming both sources and the key, since the install reached the network",
          len(log) == 1 and "terraform-aws-modules/eks/aws" in log[0] and "eks-pod-identity/aws" in log[0]
          and k in log[0], log)
    check("a second store() of the same key keeps the first and logs nothing",
          mc.store(first, MAIN, env=env) == e and len((root / "fetch.log").read_text().splitlines()) == 1)
    check("no temp directory is left beside the entry",
          sorted(x.name for x in e.parent.iterdir()) == sorted([k, f"{k}.lock"]), list(e.parent.iterdir()))

    second = base / "second"
    hit = mc.seed(second, MAIN.replace('"x" {}', '"y" {}'), env=env)
    check("seed() with the same module calls is a hit", hit is True)
    got = second / ".terraform" / "modules"
    check("the hit copies every file in", (got / "modules.json").is_file()
          and (got / "a_eks" / "modules" / "kms" / "main.tf").read_text() == "# kms\n"
          and (got / "b_pod" / "main.tf").read_text() == "# pod identity\n")
    check("a hit logs no fetch", len((root / "fetch.log").read_text().splitlines()) == 1)
    msg = raises(lambda: mc.seed(second, MAIN, env=env), mc.ModuleCacheError)
    check("seed() refuses a directory that already has modules", msg is not None and "exists already" in msg, msg)
    check("seed() with other module calls is a miss",
          mc.seed(base / "third", MAIN.replace("~> 1.12.0", "~> 1.13.0"), env=env) is False)

    print("a kept copy that changed")
    (e / "modules" / "b_pod" / "main.tf").write_text("# changed\n")
    msg = raises(lambda: mc.seed(base / "fourth", MAIN, env=env), mc.ModuleCopyMismatch)
    want = (e / "DIGEST").read_text().strip()
    check("a changed copy fails naming the path and both sums",
          msg is not None and str(e / "modules") in msg and want in msg and mc.digest(e / "modules")[0] in msg, msg)
    check("it is an ArtifactMismatch, as a changed cache file is", issubclass(mc.ModuleCopyMismatch, ac.ArtifactMismatch))
    check("the changed copy is left where it is", (e / "modules" / "b_pod" / "main.tf").read_text() == "# changed\n")
    check("nothing is copied into the working directory", not (base / "fourth" / ".terraform").exists())
    (e / "modules" / "b_pod" / "main.tf").write_text("# pod identity\n")
    (e / "modules" / "b_pod" / "extra.tf").write_text("\n")
    check("an added file fails too", raises(lambda: mc.seed(base / "fifth", MAIN, env=env), mc.ModuleCopyMismatch))
    (e / "modules" / "b_pod" / "extra.tf").unlink()
    check("with the file put back it is a hit again", mc.seed(base / "sixth", MAIN, env=env) is True)

    print("what store() refuses")
    msg = raises(lambda: mc.store(base / "nothing", MAIN.replace("~> 1.12.0", "~> 9.0"), env=env), mc.ModuleCacheError)
    check("an install with no modules.json is not kept", msg is not None and "modules.json" in msg, msg)
    stray = root / "terraform-modules" / mc.key(MAIN.replace("~> 1.12.0", "~> 2.0"))
    stray.mkdir()
    msg = raises(lambda: mc.store(first, MAIN.replace("~> 1.12.0", "~> 2.0"), env=env), mc.ModuleCacheError)
    check("an entry with no DIGEST is named and left, never deleted", msg is not None and str(stray) in msg
          and stray.is_dir(), msg)
    check("a root with no module call stores nothing", mc.store(first, 'resource "null_resource" "x" {}\n', env=env)
          is None)
    inside = REPO / "tmp-module-cache-root"
    msg = raises(lambda: mc.seed(base / "seventh", MAIN, env={"WIB_ARTIFACT_CACHE": str(inside)}), ac.RootInWorktree)
    check("a cache root inside a worktree is refused", msg is not None and not inside.exists(), msg)
finally:
    shutil.rmtree(base, ignore_errors=True)

print(f"\n{len(failures)} failure(s)")
if failures:
    sys.exit(1)
print("ALL TF MODULE CACHE CHECKS GREEN")
