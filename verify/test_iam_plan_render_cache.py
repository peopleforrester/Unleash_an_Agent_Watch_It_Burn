# ABOUTME: Offline check that verify/iam_plan_render.py runs every terraform call with the plugin cache on and
# ABOUTME: allowed with no lockfile, so a render takes providers from the cache, not releases.hashicorp.com (#883).
#
# Why. The renders copy no lockfile into their working copy of a root, and Terraform 1.4+ skips the plugin cache
# for any provider a lockfile does not record. Without TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE, each of
# test_iam_policy_structural.py's four renders downloaded the aws provider (about 840 MB) and cloudinit again, and
# a reset connection on one of them failed the E2E tools tier on staging (#883). A stub terraform stands in for
# the real one here and records the environment of each call, so this needs no network and no terraform.
import json, os, pathlib, stat, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))

failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


STUB = """#!/usr/bin/env python3
import json, os, sys
args = [a for a in sys.argv[1:] if not a.startswith("-chdir=")]
with open(os.environ["STUB_RECORD"], "a") as f:
    f.write(json.dumps({"cmd": args[0],
                        "may_break": os.environ.get("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"),
                        "cache": os.environ.get("TF_PLUGIN_CACHE_DIR")}) + "\\n")
if args[0] == "show":
    print("{}")
"""

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    stub = tmp / "terraform"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    record = tmp / "record.jsonl"
    os.environ["TERRAFORM"] = str(stub)
    os.environ["STUB_RECORD"] = str(record)
    # The tier sets a shared cache; a run without one still gets a cache, one per process.
    os.environ.pop("TF_PLUGIN_CACHE_DIR", None)
    os.environ.pop("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", None)
    import iam_plan_render  # noqa: E402

    print("each root's render, with no TF_PLUGIN_CACHE_DIR set")
    for root in sorted(iam_plan_render.ROOTS):
        record.write_text("")
        out = iam_plan_render.render(root)
        calls = [json.loads(line) for line in record.read_text().splitlines()]
        check(f"{root}: the render runs init, plan and show, and returns show's JSON",
              [c["cmd"] for c in calls] == ["init", "plan", "show"] and out == {}, calls)
        check(f"{root}: every call may use the plugin cache with no lockfile",
              all(c["may_break"] == "true" for c in calls), calls)
        check(f"{root}: every call names a plugin cache", all(c["cache"] for c in calls), calls)

    print("with the tier's shared cache set")
    shared = str(tmp / "shared-cache")
    os.environ["TF_PLUGIN_CACHE_DIR"] = shared
    record.write_text("")
    iam_plan_render.render("cluster")
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    check("cluster: every call uses the shared cache, with no lockfile needed",
          all(c["cache"] == shared and c["may_break"] == "true" for c in calls), calls)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
