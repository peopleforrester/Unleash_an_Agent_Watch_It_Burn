# ABOUTME: Names the wib-e2e-tools image the tools tier runs in (#1188): its tag from e2e-tools.lock's SHA-256 and the
# ABOUTME: build files', and the check that verify/e2e-image/Containerfile pins exactly the lock's tools and versions.
"""The image ghcr.io/peopleforrester/wib-e2e-tools carries the tier's eleven pinned binaries, fetched once at build and
checked against e2e-tools.lock, so a host that runs the tier pulls one image once instead of fetching each binary
(#1188). Its tag is

    <the first 16 hex of e2e-tools.lock's SHA-256>-<the first 8 hex of the SHA-256 of the other build inputs>

so a new lock is a new tag, and so is a change to the Containerfile or anything else the build copies (BUILD_INPUTS):
a tag never names two different images, and a host holding the tag never needs to pull it again.

Command line:
  e2e_image.py ref               print the image reference for the lock and build files in this checkout
  e2e_image.py tag               print the tag alone
  e2e_image.py check             exit 1, naming each difference, unless the Containerfile's `install.sh tool` lines are
                                 exactly the lock's rows, in the lock's order, and .dockerignore lets in exactly
                                 the build inputs
  e2e_image.py matches <file>    exit 1 unless <file> (the image's tools.txt) lists exactly the lock's tools, versions
                                 and SHA-256s: run-e2e-tools.sh's check inside the image
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

VERIFY = pathlib.Path(__file__).resolve().parent
LOCK = VERIFY / "e2e-tools.lock"
IMAGE_DIR = VERIFY / "e2e-image"
CONTAINERFILE = IMAGE_DIR / "Containerfile"
DOCKERIGNORE = VERIFY / ".dockerignore"
REPOSITORY = "ghcr.io/peopleforrester/wib-e2e-tools"
# What the build reads from its context (verify/), besides e2e-image/ itself: the Python pins the image installs PyYAML
# and Playwright from, through the repo's own hash-checked installer (#1121).
CONTEXT_FILES = ("python.lock", "package_cache.py", "artifact_cache.py")
TOOL_LINE = re.compile(r"^RUN /usr/local/lib/wib-e2e/install\.sh tool (.*)$")


class ImageError(RuntimeError):
    """A pin or input that does not hold; the message names it."""


def lock_rows(text: str) -> list[tuple[str, ...]]:
    """(name, version, sha256, url, member) for each tool row of e2e-tools.lock."""
    rows = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = tuple(line.split())
        if len(parts) != 5 or not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
            raise ImageError(f"e2e-tools.lock line {n} is not `name version sha256 url member`: {raw!r}")
        rows.append(parts)
    if not rows:
        raise ImageError("e2e-tools.lock names no tools")
    return rows


def containerfile_rows(text: str) -> list[tuple[str, ...]]:
    """The (name, version, sha256, url, member) of each `install.sh tool` line, in order."""
    return [tuple(m.group(1).split()) for m in map(TOOL_LINE.match, text.splitlines()) if m]


def pin_problems(lock_text: str, containerfile_text: str) -> list[str]:
    """Each way the Containerfile's tool lines differ from the lock's rows; none when they are the same, in order."""
    lock = lock_rows(lock_text)
    built = containerfile_rows(containerfile_text)
    problems = []
    lock_by = {r[0]: r for r in lock}
    built_by = {r[0]: r for r in built}
    for row in built:
        if len(row) != 5:
            problems.append(f"the Containerfile's `install.sh tool {' '.join(row)}` line is not "
                            "`name version sha256 url member`")
    for name in lock_by.keys() - built_by.keys():
        problems.append(f"the lock pins {name} {lock_by[name][1]} and the Containerfile does not install it")
    for name in built_by.keys() - lock_by.keys():
        problems.append(f"the Containerfile installs {name}, which the lock does not pin")
    if len(built_by) != len(built):
        problems.append("the Containerfile installs a tool twice")
    fields = ("version", "SHA-256", "URL", "archive member")
    for name in sorted(lock_by.keys() & built_by.keys()):
        for i, field in enumerate(fields, 1):
            a, b = lock_by[name], built_by[name]
            if len(b) == 5 and a[i] != b[i]:
                problems.append(f"{name}: the lock's {field} is {a[i]} and the Containerfile's is {b[i]}")
    if not problems and [r[0] for r in built] != [r[0] for r in lock]:
        problems.append("the Containerfile installs the lock's tools in another order than the lock lists them")
    return problems


def build_inputs() -> list[pathlib.Path]:
    """Every file the build reads besides the lock: all of e2e-image/, CONTEXT_FILES and .dockerignore."""
    files = sorted(p for p in IMAGE_DIR.rglob("*") if p.is_file())
    return files + [VERIFY / f for f in CONTEXT_FILES] + [DOCKERIGNORE]


def dockerignore_problems(text: str) -> list[str]:
    """.dockerignore must shut out all of verify/ but e2e-image/ and CONTEXT_FILES, so the build cannot read a file
    the tag does not hash, and verify/.tools is never sent to a builder."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    want = ["*", "!e2e-image/", *(f"!{f}" for f in CONTEXT_FILES)]
    return [] if lines == want else [f"verify/.dockerignore reads {lines}, not {want}"]


def tag() -> str:
    lock = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    h = hashlib.sha256()
    for p in build_inputs():
        h.update(p.relative_to(VERIFY).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return f"{lock[:16]}-{h.hexdigest()[:8]}"


def ref() -> str:
    return f"{REPOSITORY}:{tag()}"


def tools_txt_problems(lock_text: str, tools_text: str) -> list[str]:
    """Each way the image's tools.txt (name version sha256 per line) differs from the lock's rows."""
    want = [r[:3] for r in lock_rows(lock_text)]
    have = [tuple(ln.split()) for ln in tools_text.splitlines() if ln.strip()]
    if have == want:
        return []
    return [f"the image holds {' '.join(h)}" for h in have if h not in want] + \
           [f"the lock pins {' '.join(w)}, which the image lacks" for w in want if w not in have] or \
           ["the image lists the lock's tools in another order"]


def main(argv: list[str]) -> int:
    try:
        if argv == ["ref"]:
            print(ref())
        elif argv == ["tag"]:
            print(tag())
        elif argv == ["check"]:
            problems = pin_problems(LOCK.read_text(encoding="utf-8"), CONTAINERFILE.read_text(encoding="utf-8"))
            problems += dockerignore_problems(DOCKERIGNORE.read_text(encoding="utf-8"))
            if problems:
                print("E2E IMAGE PINS DIFFER FROM e2e-tools.lock:", file=sys.stderr)
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)
                return 1
            print(f"verify/e2e-image/Containerfile pins the {len(lock_rows(LOCK.read_text()))} tools of "
                  f"e2e-tools.lock; the image is {ref()}")
        elif len(argv) == 2 and argv[0] == "matches":
            problems = tools_txt_problems(LOCK.read_text(encoding="utf-8"),
                                          pathlib.Path(argv[1]).read_text(encoding="utf-8"))
            if problems:
                print(f"E2E IMAGE IS NOT THIS LOCK'S: {argv[1]} differs from verify/e2e-tools.lock; run the tier in "
                      f"{ref()}:", file=sys.stderr)
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)
                return 1
        else:
            print(__doc__.split("Command line:")[1], file=sys.stderr)
            return 2
    except (ImageError, OSError) as e:
        print(f"E2E IMAGE FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
