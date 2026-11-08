# ABOUTME: Offline check that verify/iam_plan_render.py runs every terraform call against the provider mirror and with
# ABOUTME: the plugin cache allowed with no lockfile, so a render takes providers from the host cache (#883, #1119).
#
# Why. The renders copy no lockfile into their working copy of a root, and Terraform 1.4+ skips the plugin cache
# for any provider a lockfile does not record. Without TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE, each of
# test_iam_policy_structural.py's four renders downloaded the aws provider (about 840 MB) and cloudinit again, and
# a reset connection on one of them failed the E2E tools tier on staging (#883). A stub terraform stands in for
# the real one here and records the environment of each call, so this needs no network and no terraform.
#
# #1119: every call also gets the CLI config tf_plugin_cache.py writes, which installs providers from the mirror in the
# host artifact cache only. Here the config is one for a scratch root the test prepares, so the renders take the
# caller's prepared config, as they do under a workflow's `tf_plugin_cache.py prepare`, and nothing is filled.
import json, os, pathlib, stat, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import tf_plugin_cache  # noqa: E402

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
                        "cache": os.environ.get("TF_PLUGIN_CACHE_DIR"),
                        "config": os.environ.get("TF_CLI_CONFIG_FILE")}) + "\\n")
if args[0] == "show":
    print("{}")
"""

with tf_plugin_cache.scratch("iam-render-cache-") as tmp:
    tmp = pathlib.Path(tmp)
    stub = tmp / "terraform"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    record = tmp / "record.jsonl"
    os.environ["TERRAFORM"] = str(stub)
    os.environ["STUB_RECORD"] = str(record)
    # A prepared config for a scratch artifact root, as `tf_plugin_cache.py prepare` leaves one.
    art = tmp / "artifacts"
    config = str(tf_plugin_cache.write_config(art))
    shared = str(tmp / "shared-cache")
    os.environ.update({"TF_CLI_CONFIG_FILE": config, "TF_PLUGIN_CACHE_DIR": shared})
    os.environ.pop("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", None)
    import iam_plan_render  # noqa: E402

    print("each root's render, with a prepared provider mirror")
    for root in sorted(iam_plan_render.ROOTS):
        record.write_text("")
        out = iam_plan_render.render(root)
        calls = [json.loads(line) for line in record.read_text().splitlines()]
        check(f"{root}: the render runs init, plan and show, and returns show's JSON",
              [c["cmd"] for c in calls] == ["init", "plan", "show"] and out == {}, calls)
        check(f"{root}: every call may use the plugin cache with no lockfile",
              all(c["may_break"] == "true" for c in calls), calls)
        check(f"{root}: every call uses the prepared plugin cache", all(c["cache"] == shared for c in calls), calls)
        check(f"{root}: every call installs providers from the mirror's CLI config",
              all(c["config"] == config for c in calls), calls)
    check("the prepared config is the one that installs from the root's mirror only",
          pathlib.Path(config).read_text() == tf_plugin_cache.render_config(tf_plugin_cache.mirror_dir(art)))
    check("and nothing was filled into the scratch root", not (art / "sha256").exists())

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
