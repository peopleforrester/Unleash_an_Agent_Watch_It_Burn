# ABOUTME: A fresh `terraform init -lockfile=readonly` of each committed root (in a clean copy, no .terraform/)
# ABOUTME: succeeds against its committed lock and leaves it unchanged; providers come from the host artifact cache.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and on a cold artifact cache network to registry.terraform.io)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
# E2E SERIAL: terraform (run-e2e-tools.sh runs one such test at a time: they share the provider cache, #1005)
#
# #468: the cluster root's lock pinned aws 6.51.0 while the EKS module it resolved needed >= 6.59.0. That only
# showed on a machine with no older module cached, so this runs every init in an empty temp directory.
# -lockfile=readonly makes a lock that needs changing an error instead of a silent rewrite.
#
# #1047: on Tanjiro's CI runner (Actions run 42407284907) registry.terraform.io did not answer one provider query in
# time ("context deadline exceeded" after terraform's own 2 attempts) and the tier went red. An init that fails on
# what chart_fetch.is_network_error reads as the network is run again, in a new empty directory, up to len(BACKOFF) + 1
# times; any other failure, a lock that does not match included, fails on the first. TF_LOCK_INIT_BACKOFF (seconds,
# comma-separated) is for test_terraform_lock_init_retry.py, which runs this against a stub terraform.
#
# #1114: the inits took 326 s of the tier, nearly all of it downloading the same providers again. #1119: terraform no
# longer downloads them at all. tf_plugin_cache.terraform_env fills a filesystem mirror in the host artifact cache,
# outside every worktree, with each provider zip the locks pin, fetched once per host through artifact_cache.get() by
# the zh: SHA-256 the lock records, and gives terraform a CLI config that installs registry.terraform.io providers from
# that mirror only, with the shared plugin cache beside it. Each init is still fresh: a new directory with no
# .terraform/ and no module cache, which is what #468 needed. Neither cache weakens the lock: terraform checks each
# mirror zip against the lock's hashes, and takes a cached provider only when its h1: checksum is one the lock records.
# TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE, the one switch that loosens that, is dropped by terraform_env;
# test_terraform_mirror_lock.py holds that a mirror zip the lock does not match fails init, and
# test_terraform_plugin_cache_lock.py that a tampered cached provider never reaches one.
import os, pathlib, shutil, subprocess, sys, tempfile, time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from chart_fetch import is_network_error  # noqa: E402
import artifact_cache  # noqa: E402
import tf_plugin_cache  # noqa: E402

ROOTS = ["infra/terraform/aws/cluster", "infra/terraform/aws/network", "infra/terraform/aws/audit", "infra/org/boundary",
         "infra/terraform/dashboards"]
# A cold plugin cache unpacks each root's providers from the mirror, the aws one ~800 MB, and the cluster root still
# fetches its modules: a healthy init fits well inside this bound (#572).
INIT_TIMEOUT = 600
BACKOFF = tuple(float(x) for x in (os.environ.get("TF_LOCK_INIT_BACKOFF") or "10,30").split(","))
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
# Every network fetch of the artifact cache is one line in its fetch log: a warm run adds none.
try:
    FETCH_LOG = artifact_cache.fetch_log_path(tf_plugin_cache.root_of(env), env)
except tf_plugin_cache.CacheError as e:
    print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
fetched_before = len(FETCH_LOG.read_text().splitlines()) if FETCH_LOG.is_file() else 0
# The mirror is filled for exactly the locks this test inits against. A cold fill goes to the network, so one that
# fails on what reads as the network is tried again, as an init is.
began = time.monotonic()
for attempt in range(1, len(BACKOFF) + 2):
    try:
        env = tf_plugin_cache.terraform_env(env, [REPO / r / ".terraform.lock.hcl" for r in ROOTS])
        break
    except tf_plugin_cache.CacheError as e:
        if not is_network_error(str(e)) or attempt == len(BACKOFF) + 1:
            print(f"FAIL: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"  RETRY the provider mirror: {e}; again in {BACKOFF[attempt - 1]:g}s", flush=True)
        time.sleep(BACKOFF[attempt - 1])
print(f"provider mirror ready in {time.monotonic() - began:.1f}s")
print(f"CLI config: {env['TF_CLI_CONFIG_FILE']}")
print(f"provider cache: {env['TF_PLUGIN_CACHE_DIR']}")


def fresh_init(src: pathlib.Path) -> tuple[subprocess.CompletedProcess | None, bytes]:
    """One `terraform init` of src's *.tf and lock in a new empty directory: its result (None when it timed out) and
    the lock it left."""
    with tempfile.TemporaryDirectory(prefix="tf-lock-init-") as tmp:
        work = pathlib.Path(tmp)
        for f in list(src.glob("*.tf")) + [src / ".terraform.lock.hcl"]:
            shutil.copy2(f, work / f.name)
        # Bounded: a registry download that stalls fails this check loudly instead of holding the E2E tier (#572).
        try:
            r = subprocess.run([exe, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color"],
                               cwd=work, env=env, capture_output=True, text=True, timeout=INIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            r = None
        return r, (work / ".terraform.lock.hcl").read_bytes()


tries = len(BACKOFF) + 1
for root in ROOTS:
    src = REPO / root
    print(root)
    began = time.monotonic()
    for attempt in range(1, tries + 1):
        r, lock = fresh_init(src)
        if r is None or r.returncode == 0 or not is_network_error(r.stdout + r.stderr) or attempt == tries:
            break
        last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()][-1:]
        print(f"  RETRY {root}: init failed on the network ({' '.join(last)}); try {attempt} of {tries}, "
              f"again in {BACKOFF[attempt - 1]:g}s", flush=True)
        time.sleep(BACKOFF[attempt - 1])
    print(f"  init took {time.monotonic() - began:.1f}s")
    if r is None:
        check(f"{root}: fresh init finishes within {INIT_TIMEOUT}s", False, "timed out: a provider download stalled")
        continue
    said = (r.stdout + r.stderr)[-2000:]
    if r.returncode != 0 and attempt > 1 and is_network_error(r.stdout + r.stderr):
        said += f"\n(a network error on each of {attempt} tries)"
    check("fresh init succeeds against the committed lock", r.returncode == 0, said)
    check("the lock is unchanged by init", lock == (src / ".terraform.lock.hcl").read_bytes())
    # terraform names the signer of a package it downloaded from the registry; one from the mirror is unauthenticated
    # and one from the plugin cache is "from the shared cache directory".
    check("terraform downloads no provider: each comes from the mirror or the plugin cache",
          "(signed by" not in r.stdout and "(self-signed" not in r.stdout, said)

fetched = (len(FETCH_LOG.read_text().splitlines()) if FETCH_LOG.is_file() else 0) - fetched_before
print(f"\nartifact cache fetches this run: {fetched} (in {FETCH_LOG})")
if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL TERRAFORM LOCK-INIT CHECKS GREEN")
