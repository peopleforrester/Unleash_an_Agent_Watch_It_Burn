# ABOUTME: Render gate: every image from a registry we publish to is pinned by digest, not only by tag.
# ABOUTME: A tag is a moving pointer, so an allowlist that admits a tag does not name an artifact.
"""Why this exists (#415).

The registry allowlist admits `ghcr.io/*`, which means it admits whatever that tag points at today. The
workshop argues on stage that guardrails belong at the cluster abstraction layer, and a policy that
names a moving pointer is a weaker version of that argument than one that names an artifact.

There is a second reason this is a test rather than a one-time sweep, and it is the more instructive
one. The manual sweep that found these reported "none left" while two files were still unpinned,
because it filtered with `grep -v @sha256` and those lines carried the literal string `@sha256` inside
the comment `# verify-at-build: pin @sha256`. The matcher could not tell a digest from a note asking
for one. This check strips the comment before testing, and asserts the matcher fires on a known
unpinned reference so it cannot go vacuous the same way.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
# Registries we publish to or control the tags of. A third-party tag we merely consume is out of scope
# here; agentgateway is in scope because we pin it deliberately and a bump must not drop the digest.
OURS = re.compile(r"(ghcr\.io/peopleforrester/|cr\.agentgateway\.dev/|cr\.kagent\.dev/)")
IMAGE_LINE = re.compile(r"^[ \t]*image:[ \t]*(\S+)")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", "docs"}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def refs():
    """Yield (path, lineno, image reference) with any trailing comment removed."""
    for path in REPO.rglob("*.yaml"):
        if any(part in SKIP_DIRS for part in path.relative_to(REPO).parts):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            # Strip the comment FIRST. This is the bug the manual sweep had.
            code = line.split("#", 1)[0]
            m = IMAGE_LINE.match(code)
            if m:
                yield path.relative_to(REPO), i, m.group(1)


print("== the matcher fires on an unpinned reference ==")
_probe = "          image: ghcr.io/peopleforrester/watch-it-burn:sample-app # verify-at-build: pin @sha256"
_code = _probe.split("#", 1)[0]
_m = IMAGE_LINE.match(_code)
check("a tag-only reference with '@sha256' in its COMMENT is seen as unpinned",
      _m is not None and OURS.search(_m.group(1)) is not None and "@sha256:" not in _m.group(1))

print("== every image from a registry we publish to carries a digest ==")
unpinned = [(p, n, r) for p, n, r in refs() if OURS.search(r) and "@sha256:" not in r]
for p, n, r in unpinned:
    print(f"        {p}:{n}  {r}")
check(f"all pinned by digest ({len(unpinned)} unpinned)", not unpinned)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll image-pin checks passed.")
