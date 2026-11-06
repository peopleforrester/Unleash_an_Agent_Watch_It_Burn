# ABOUTME: Offline check of helm_fetch.run_helm with a fake helm: a repo that cannot be reached is fetched once more,
# ABOUTME: two failures name both errors, and any other helm error fails on the first attempt (#989).
#
# Why. In run 17888 (#938) one dropped fetch of charts.external-secrets.io's index.yaml failed test_enforce_floor.py
# and turned the 33-minute tools tier red, though the same URL answered a moment later. run_helm fetches again once
# when helm says the repo cannot be reached. This proves it does that, that a lasting outage still fails and prints
# both of helm's errors, and that an error a second fetch cannot change is not retried. The fake stands in for helm,
# so this needs no helm and no network and runs in the offline suite.
import pathlib, stat, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import helm_fetch  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []

UNREACHABLE = ('Error: looks like "https://charts.external-secrets.io" is not a valid chart repository or cannot be '
               'reached: Get "https://charts.external-secrets.io/index.yaml": dial tcp: i/o timeout')
UNREACHABLE_2 = UNREACHABLE.replace("i/o timeout", "connection reset by peer")
BAD_VERSION = 'Error: chart "external-secrets" version "9.9.9" not found in https://charts.external-secrets.io repository'

# The fake reads its answers from a file, one per call: "<exit code>\t<stderr>". It logs each call so the test can
# count them, and prints a manifest on a zero exit.
FAKE = """#!/bin/sh
dir="$(dirname "$0")"
echo "$*" >>"$dir/calls"
n=$(wc -l <"$dir/calls")
line=$(sed -n "${n}p" "$dir/answers")
rc=$(printf '%s' "$line" | cut -f1)
msg=$(printf '%s' "$line" | cut -f2-)
if [ "$rc" = 0 ]; then
  printf 'apiVersion: v1\\nkind: ConfigMap\\nmetadata:\\n  name: rendered\\n'
  exit 0
fi
echo "walk.go:75: found symbolic link in path" >&2
echo "$msg" >&2
exit "$rc"
"""


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f" ({detail})" if detail and not c else ""))
    if not c:
        failures.append(n)


def run(answers):
    """Run run_helm against a fake helm that gives `answers` in turn; return (result, error, number of calls)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        fake = d / "helm"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        (d / "answers").write_text("".join(f"{rc}\t{msg}\n" for rc, msg in answers))
        (d / "calls").write_text("")
        r, err = helm_fetch.run_helm([str(fake), "template", "external-secrets", "external-secrets",
                                      "--repo", "https://charts.external-secrets.io"], pause=0)
        return r, err, len((d / "calls").read_text().splitlines())


print("== a repo that answers at once is fetched once ==")
r, err, calls = run([(0, "")])
check("no error", err is None, err)
check("one call", calls == 1, f"{calls} calls")
check("the rendered manifest is returned", "name: rendered" in r.stdout, r.stdout)

print("== a repo that cannot be reached once is fetched again, and the second answer is used ==")
r, err, calls = run([(1, UNREACHABLE), (0, "")])
check("no error", err is None, err)
check("two calls", calls == 2, f"{calls} calls")
check("the second attempt's manifest is returned", r.returncode == 0 and "name: rendered" in r.stdout, r.stdout)

print("== a repo that cannot be reached twice fails, naming both errors ==")
r, err, calls = run([(1, UNREACHABLE), (1, UNREACHABLE_2), (0, "")])
check("an error is returned", bool(err))
check("two calls, not a third", calls == 2, f"{calls} calls")
check("the error names attempt 1 and its message",
      bool(err) and "attempt 1: " in err and "i/o timeout" in err, err)
check("the error names attempt 2 and its message",
      bool(err) and "attempt 2: " in err and "connection reset by peer" in err, err)
check("the error is helm's message, not the warning above it", bool(err) and "symbolic link" not in err, err)
check("the failed result is returned with its exit code", r.returncode != 0)

print("== any other helm error fails on the first attempt ==")
r, err, calls = run([(1, BAD_VERSION), (0, "")])
check("one call", calls == 1, f"{calls} calls")
check("the error is helm's message alone", err == BAD_VERSION[:200], err)

print("== the defaults: two attempts, with a pause between them ==")
check("ATTEMPTS is 2", helm_fetch.ATTEMPTS == 2, str(helm_fetch.ATTEMPTS))
check("the default pause is above zero", helm_fetch.PAUSE_SECONDS > 0, str(helm_fetch.PAUSE_SECONDS))

print("== test_enforce_floor.py renders its charts through run_helm ==")
floor = (REPO / "verify/test_enforce_floor.py").read_text()
check("it imports run_helm", "from helm_fetch import run_helm" in floor)
check("helm_render calls run_helm(cmd)", "r, err = run_helm(cmd)" in floor)
check("helm_render no longer runs helm with subprocess.run(cmd", "subprocess.run(cmd," not in floor)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All helm_fetch checks passed.")
