# ABOUTME: Live half of the baseline check: the sister snapshot in platform-baseline.yaml still matches the
# ABOUTME: component directories on the sister's main branch (#394). Reads the public GitHub API.
# SUITE: e2e (needs the network: api.github.com)
# E2E TIER: tools
#
# The offline half (test_platform_baseline.py) proves every component in the snapshot is accounted for. This
# proves the snapshot is still the sister's real list, so a component added there turns this red until
# platform-baseline.yaml says what we do about it. That is the drift #394 found, made into a failing check.
# GITHUB_TOKEN is used when set, for the rate limit; the repo is public, so it is not required.
# Nothing here skips: no network, or an API error, is a failure with the reason printed.
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
baseline = yaml.safe_load((REPO / "platform-baseline.yaml").read_text(encoding="utf-8"))
sister = baseline["sister"]


def listing(layer: str) -> list[str]:
    path = f"{sister['path']}/{layer}" if layer else sister["path"]
    url = f"https://api.github.com/repos/{sister['repo']}/contents/{path}?ref={sister['ref']}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return sorted(e["name"] for e in json.load(r) if e["type"] == "dir")


failed = False
try:
    layers = {e for e in listing("") if e[0].isdigit() and e != "0-bootstrap"}
except (urllib.error.URLError, OSError, ValueError) as e:
    print(f"FAIL: cannot list {sister['repo']}/{sister['path']} at {sister['ref']}: {e}", file=sys.stderr)
    sys.exit(1)

recorded = baseline["sister"]["snapshot"]
if layers != set(recorded):
    print(f"FAIL: the sister's layers are {sorted(layers)}, the snapshot records {sorted(recorded)}")
    failed = True

for layer in sorted(layers | set(recorded)):
    try:
        live = set(listing(layer)) if layer in layers else set()
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"FAIL: cannot list {layer}: {e}", file=sys.stderr)
        sys.exit(1)
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
