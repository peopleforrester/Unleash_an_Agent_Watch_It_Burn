# ABOUTME: Offline check that verify/iam_plan_render.py runs a terraform step once more when terraform says a
# ABOUTME: provider timed out starting, fails on a second such miss, and never re-runs any other failure.
#
# Why. Terraform gives a provider a fixed minute to start. On a loaded host the aws provider missed it once in
# run 17949's tools tier and test_iam_policy_structural.py failed, then passed alone. A stub terraform stands in for
# the real one and fails `plan` with terraform's own words as many times as a case asks, so this needs no network
# and no terraform.
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
rec = os.environ["STUB_RECORD"]
with open(rec, "a") as f:
    f.write(args[0] + "\\n")
if args[0] == "plan":
    plans = open(rec).read().split().count("plan")
    if plans <= int(os.environ["STUB_PLUGIN_MISSES"]):
        sys.stderr.write("Error: Failed to load plugin schemas\\n" + os.environ["STUB_PLAN_ERROR"] + "\\n")
        sys.exit(1)
if args[0] == "show":
    print("{}")
"""

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    stub = tmp / "terraform"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    record = tmp / "record.txt"
    os.environ["TERRAFORM"] = str(stub)
    os.environ["STUB_RECORD"] = str(record)
    os.environ["TF_PLUGIN_CACHE_DIR"] = str(tmp / "cache")
    import iam_plan_render  # noqa: E402

    words = iam_plan_render.PLUGIN_START_TIMEOUT
    check("the words matched are terraform's own", words == "timeout while waiting for plugin to start", words)

    def case(misses: int, error: str):
        record.write_text("")
        os.environ["STUB_PLUGIN_MISSES"] = str(misses)
        os.environ["STUB_PLAN_ERROR"] = error
        try:
            out, err = iam_plan_render.render("boundary"), ""
        except SystemExit as e:
            out, err = None, str(e)
        return out, err, record.read_text().split()

    print("a provider that starts first time")
    out, err, calls = case(0, f"... {words}..")
    check("init, plan and show run once each, and show's JSON comes back",
          calls == ["init", "plan", "show"] and out == {}, f"calls={calls} err={err}")

    print("a provider that misses its start once")
    out, err, calls = case(1, f"failed to instantiate provider: {words}..")
    check("plan runs once more and the render comes back", calls == ["init", "plan", "plan", "show"] and out == {},
          f"calls={calls} err={err}")

    print("a provider that misses its start twice")
    out, err, calls = case(2, f"failed to instantiate provider: {words}..")
    check("plan runs twice, no third time, and show never runs", calls == ["init", "plan", "plan"], calls)
    check("the render fails naming the plan, the root and both misses",
          out is None and "terraform plan of boundary failed" in err and "on both tries" in err and words in err, err)

    print("any other plan failure")
    out, err, calls = case(1, "Error: Unsupported argument")
    check("is not run again", calls == ["init", "plan"], calls)
    check("and fails with terraform's own error", out is None and "Unsupported argument" in err
          and "both tries" not in err, err)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll iam render plugin-start checks passed.")
