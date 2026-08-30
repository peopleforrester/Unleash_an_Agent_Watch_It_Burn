# ABOUTME: Guards the C3 bait against the ENOENT regression (#137): the bait must be baked into the
# ABOUTME: workshop-mcp image (read-only, pre-exists) and NOT written at runtime under the enforced dir.
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "images" / "workshop-mcp" / "Dockerfile").read_text()
SERVER = (REPO / "gitops" / "ai-layer" / "workshop-mcp-server.py").read_text()

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# The image must bake the bait so it pre-exists as a read-only layer: the C3 policy then denies the
# agent's READ (EPERM) instead of blocking the pod's own runtime WRITE (which failed to ENOENT, #137).
check("Dockerfile bakes the bait dir",
      "/tmp/burrito-data/config/legacy" in DOCKERFILE)
check("Dockerfile bakes the bait file",
      "secret-sauce-recipe.conf" in DOCKERFILE)
check("baked bait carries the C3 signature",
      "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7" in DOCKERFILE)

# server.py must NOT write under the enforced legacy dir at runtime (that write is blocked and the
# `except OSError: pass` hides it). It may still seed the non-enforced root data files.
wrote_bait_at_runtime = re.search(r"open\(\s*f?[\"'][^\"']*config/legacy", SERVER) is not None \
    or re.search(r"makedirs\(\s*bait", SERVER) is not None
check("server.py does NOT write the bait under config/legacy at runtime",
      not wrote_bait_at_runtime)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll C3-bait checks passed.")
