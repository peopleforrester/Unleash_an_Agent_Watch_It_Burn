# ABOUTME: Each collector profile's rendered config builds in under 10 s of CPU in the pinned otelcol-contrib (#1328),
# ABOUTME: measured with `validate`, and #1316's single code-of-conduct statements, put back, do not.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on the config alone)
"""The measured half of verify/test_collector_startup_budget.py.

otelcol-contrib 0.160.0 parses an OTTL string in CPU time that grows with the square of its length. #1316 wrote the
code-of-conduct pattern into transform/coc_mask as four statements of 108,437 characters, and the whole config cost
about 46 s of CPU to build, so the collector crashlooped under its liveness probe (#1326). #1328 cut the pattern into
floor.portable_patterns(), 36 patterns applied in turn. This runs `otelcol-contrib validate`, which builds every
component and parses every OTTL statement but starts nothing, on each profile's config as its cluster renders it
(collector_render.py), with and without datadog-secret, and reads the CPU the child used (user plus system, which a
loaded host does not add to the way it adds to the wall clock). Each must succeed and use under BUILD_LIMIT_S.

The same profile's config with one string of #1316's statement's length added must use more than BUILD_LIMIT_S, so
the measurement tells the two forms apart.

Fails when the binary is missing: run verify/fetch-e2e-tools.sh (verify/run-e2e-tools.sh does).
"""
from __future__ import annotations

import copy
import os
import pathlib
import resource
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import PROFILE_APP, REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"
BUILD_LIMIT_S = 10.0  # #1328's criterion
MASK = "transform/coc_mask"
SINGLE_STATEMENT_CHARS = 108_437  # #1316's replace statement, as #1326 read it in the live relay.yaml
# What the configs read from the environment; validate needs a value for each, not a real one.
ENV = {"WIB_CLUSTER_NAME": "burritobot-validate", "DD_API_KEY": "0" * 32, "DD_ADMIN_API_KEY": "0" * 32,
       "DD_SITE": "datadoghq.com", **{f"WIB_BEDROCK_PROFILE_{t}": "unpinned" for t in ("HAIKU", "NOVA", "OPUS", "SONNET")}}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:1500]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if not os.access(OTELCOL, os.X_OK):
    print(f"FAIL: {OTELCOL} is missing; run bash verify/fetch-e2e-tools.sh (this is a failure, not a skip)")
    sys.exit(1)
pinned = next(line.split()[1] for line in LOCK.read_text().splitlines() if line.startswith("otelcol-contrib "))
version = subprocess.run([str(OTELCOL), "--version"], capture_output=True, text=True, check=True).stdout.strip()
check(f"the binary is the pinned {pinned} ({version})", version.endswith(" " + pinned.lstrip("v")))


def validate(config: dict, profile: str) -> tuple[int, str, float]:
    """validate's exit code, its stderr, and the CPU seconds it used."""
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "relay.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False, width=10 ** 9), encoding="utf-8")
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        run = subprocess.run([str(OTELCOL), "validate", f"--config={path}", *feature_gate_args(profile)],
                             capture_output=True, text=True, env={**os.environ, **ENV})
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
    used = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return run.returncode, run.stderr, used


def with_long_literal(config: dict) -> dict:
    """The config with one statement of #1316's length added to transform/coc_mask's span context: a set() of a
    108,437-letter string. The parse cost is the string's, not the regex's (#1326: 10.3 s for such a set() against
    12.9 s for #1316's statement, 15.45 s at 108,000 letters), and one costs more than BUILD_LIMIT_S on its own."""
    mutant = copy.deepcopy(config)
    for group in mutant["processors"][MASK]["trace_statements"]:
        if group["context"] == "span":
            group["statements"] = list(group["statements"]) + [f'set(cache["pad"], "{"a" * SINGLE_STATEMENT_CHARS}")']
    return mutant


print(f"== each profile's config builds in under {BUILD_LIMIT_S:g} s of CPU ==")
for profile in PROFILE_APP:
    for secret in (False, True):
        config = collector_config(profile, datadog_secret=secret)
        statements = sum(len(g["statements"]) for g in config["processors"][MASK]["trace_statements"])
        code, err, used = validate(config, profile)
        label = f"{profile} {'with' if secret else 'without'} datadog-secret"
        check(f"{label}: validate accepts the config ({statements} {MASK} statements)", code == 0, err[-1500:])
        check(f"{label}: it used {used:.2f} s of CPU, under {BUILD_LIMIT_S:g} s", used < BUILD_LIMIT_S)

print("== one string of #1316's length, added, does not ==")
code, err, used = validate(with_long_literal(collector_config("burn", datadog_secret=False)), "burn")
check(f"burn with one {SINGLE_STATEMENT_CHARS:,}-character string added: validate accepts the config and uses "
      f"{used:.1f} s of CPU, over {BUILD_LIMIT_S:g} s, so the measurement tells #1316's form from the cut",
      code == 0 and used > BUILD_LIMIT_S, err[-1500:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"Every collector profile's config builds in under {BUILD_LIMIT_S:g} s of CPU.")
