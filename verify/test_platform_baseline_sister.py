# ABOUTME: Live half of the baseline check: the sister snapshot in platform-baseline.yaml still matches the
# ABOUTME: component directories on the sister's main branch (#394). Reads the public repo over git, not the REST API.
# SUITE: e2e (needs the network: github.com over git's HTTPS)
# E2E TIER: tools
#
# The offline half (test_platform_baseline.py) proves every component in the snapshot is accounted for. This
# proves the snapshot is still the sister's real list, so a component added there turns this red until
# platform-baseline.yaml says what we do about it. That is the drift #394 found, made into a failing check.
# The listing comes from a shallow, blob-free clone (verify/sister_tree.py), not api.github.com: the host's runs
# share one anonymous API quota of 60 requests an hour, and run 17993 failed this on it (#1027). No token is needed.
# Nothing here skips: no network, or a failed clone, is a failure with git's reason printed.
from __future__ import annotations

import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sister_tree  # noqa: E402

REPO = HERE.parent
baseline = yaml.safe_load((REPO / "platform-baseline.yaml").read_text(encoding="utf-8"))
sister = baseline["sister"]

try:
    tree = sister_tree.read(sister_tree.github_url(sister["repo"]), sister["ref"], sister["path"])
except sister_tree.SisterReadError as e:
    print(f"FAIL: cannot read {sister['repo']}/{sister['path']} at {sister['ref']}: {e}", file=sys.stderr)
    sys.exit(1)

layers = {e for e in tree[""] if e[0].isdigit() and e != "0-bootstrap"}
failed = False

recorded = sister["snapshot"]
if layers != set(recorded):
    print(f"FAIL: the sister's layers are {sorted(layers)}, the snapshot records {sorted(recorded)}")
    failed = True

for layer in sorted(layers | set(recorded)):
    live = set(tree[layer]) if layer in layers else set()
    snap = set(recorded.get(layer, []))
    if live == snap:
        print(f"  PASS  {layer}: {len(live)} components, as recorded")
        continue
    failed = True
    for name in sorted(live - snap):
        print(f"  FAIL  {layer}/{name} is new on the sister: add it to the snapshot and give it an entry")
    for name in sorted(snap - live):
        print(f"  FAIL  {layer}/{name} is gone from the sister: drop it from the snapshot and its entry's sister list")

if failed:
    print(f"\nFAILED: platform-baseline.yaml's snapshot (checked_on {sister['checked_on']}) no longer matches "
          f"{sister['repo']}@{sister['ref']}. Update it, then re-run test_platform_baseline.py.", file=sys.stderr)
    sys.exit(1)
print(f"\nThe sister snapshot matches {sister['repo']}@{sister['ref']}.")
