# ABOUTME: Plans the cluster root against a mocked aws provider (`terraform test`) and holds lab-platform-operator's
# ABOUTME: access entry to #873: on attendee seats only, in accounts that hold the role, group learner-apps, no policy.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and network to registry.terraform.io for modules and a cold cache)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
# E2E SERIAL: terraform (run-e2e-tools.sh runs one such test at a time: they share the provider cache, #1005)
#
# lab-platform's harvest probes each seat's workshop apps as lab-platform-operator in every account but its own
# (lab-platform#370), and a seat that admits only its creator answers it with a 401. The cases are in
# verify/fixtures/lab_platform_operator_entry.tftest.hcl; this copies the root and that file into an empty
# directory, initialises it against the committed lock, and runs them. The mock provider means no AWS call.
import os, pathlib, shutil, subprocess, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import tf_plugin_cache  # noqa: E402

ROOT = REPO / "infra/terraform/aws/cluster"
CASES = REPO / "verify/fixtures/lab_platform_operator_entry.tftest.hcl"
RUNS = ["seat_in_an_account_with_the_role", "seat_in_the_base_account", "community_cluster_with_the_role",
        "admin_cluster_with_the_role"]
# The aws provider is ~800 MB unpacked on a cold plugin cache; a healthy init fits well inside this bound (#572).
TIMEOUT = 600
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); e2e-tools.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)
for f in (CASES, ROOT / "main.tf", ROOT / ".terraform.lock.hcl"):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing", file=sys.stderr)
        sys.exit(1)

env = {**os.environ, "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}
# No AWS credential reaches terraform: the mock provider needs none, and a case that started to call AWS fails.
for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    env.pop(k, None)
env["AWS_CONFIG_FILE"] = env["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
# The providers come from the host artifact cache's mirror, never a download (tf_plugin_cache.py, #1119).
try:
    env = tf_plugin_cache.terraform_env(env, [ROOT / ".terraform.lock.hcl"])
except tf_plugin_cache.CacheError as e:
    print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)

with tempfile.TemporaryDirectory(prefix="tf-operator-entry-") as tmp:
    work = pathlib.Path(tmp)
    for f in list(ROOT.glob("*.tf")) + [ROOT / ".terraform.lock.hcl"]:
        shutil.copy2(f, work / f.name)
    (work / "tests").mkdir()
    shutil.copy2(CASES, work / "tests" / CASES.name)

    def tf(*args):
        try:
            return subprocess.run([exe, *args, "-no-color"], cwd=work, env=env, capture_output=True, text=True,
                                  timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, "", f"terraform {args[0]} timed out after {TIMEOUT}s")

    r = tf("init", "-lockfile=readonly", "-backend=false", "-input=false")
    check("the cluster root initialises against its committed lock", r.returncode == 0, (r.stdout + r.stderr)[-2000:])
    if r.returncode == 0:
        r = tf("test")
        out = r.stdout + r.stderr
        check("terraform test passes every case", r.returncode == 0, out[-4000:])
        for run in RUNS:
            check(f"case {run} ran and passed", f'run "{run}"... pass' in out)
        check("no case was skipped", "... skip" not in out, out[-2000:])

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL LAB-PLATFORM-OPERATOR ENTRY CHECKS GREEN")
