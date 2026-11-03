# ABOUTME: Runs hecaton's ai-isms gate over this branch's prose before the dispatcher does (#796): each changed .md,
# ABOUTME: .mdx and .html file at the base and in the working tree, read by the scanner module hecaton itself runs.
"""Usage: python3 verify/prose_gate.py <scanner.py> <base-ref>

Why. Hecaton's promotion gate runs an ai-isms check on every changed public-prose file, and in a talk repo every
`.md`, `.mdx` and `.html` file is public prose. A change fails when it adds an em-dash, or an en-dash outside a
numeric range, or adds a hype word or connective filler to a file that then reads `major` on the scanner's rubric.
decisions.md, PROJECT_STATE.md and PROGRESS.md already read `major`, so a single word in a run's record fails the run.
Run 9604 failed on the repo's nickname, whose verb is on the hype list, and runs 14794, 14817 and 16077 failed the
gate on their own records. Each learned it only from the gate, after its time was spent.

What. This reads the files the way the gate does (hecaton's `gate_ai_isms`): each at the merge base of <base-ref>
and HEAD and as it now stands in the working tree, tracked and untracked alike; a hit counts only where its label's
total over all those files grew; a file newly declaring `ai-isms-exempt` is held for Michael. It prints each file
the gate would fail with its labels and the added lines that carry them, and exits 1; 0 when the gate would pass;
2 when it cannot run (no scanner at the path, a bad ref).

The scanner is hecaton's port of check-ai-isms, `/var/lib/hecaton/app/current/src/hecaton/run/aiisms.py` on a
hecaton host. It is passed in, not copied here, so this check and the gate cannot drift apart.
"""
from __future__ import annotations

import difflib
import importlib.util
import pathlib
import subprocess
import sys
from collections import Counter
from types import ModuleType

# The globs hecaton's governance makes public prose in a talk repo (`**/*.md`, `**/*.mdx`, `**/*.html`).
PUBLIC_PROSE = (".md", ".mdx", ".html")
SCANNER_API = ("is_prose", "exempt", "scan", "added", "EMPTY")


def die(msg: str) -> None:
    print(f"prose_gate: {msg}", file=sys.stderr)
    sys.exit(2)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def load_scanner(path: pathlib.Path) -> ModuleType:
    if not path.is_file():
        die(f"no scanner at {path}; on a hecaton host it is /var/lib/hecaton/app/current/src/hecaton/run/aiisms.py")
    spec = importlib.util.spec_from_file_location("aiisms", path)
    if spec is None or spec.loader is None:
        die(f"{path} cannot be loaded as a Python module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aiisms"] = mod  # its dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    missing = [name for name in SCANNER_API if not hasattr(mod, name)]
    if missing:
        die(f"{path} is not the gate's scanner: it has no {', '.join(missing)}")
    return mod


def changed_paths(base: str) -> list[str]:
    tracked = git("diff", "--name-only", "--no-renames", base)
    untracked = git("ls-files", "--others", "--exclude-standard")
    if tracked.returncode or untracked.returncode:
        die((tracked.stderr or untracked.stderr).strip())
    paths = set(tracked.stdout.split("\n")) | set(untracked.stdout.split("\n"))
    return sorted(p for p in paths if p)


def at_base(base: str, path: str) -> str | None:
    r = git("show", f"{base}:{path}")
    return r.stdout if r.returncode == 0 else None


def in_tree(root: pathlib.Path, path: str) -> str | None:
    f = root / path
    return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None


def added_lines(old: str | None, new: str) -> list[tuple[int, str]]:
    """The working tree's lines that are not in the base's copy, with their 1-based numbers."""
    out: list[tuple[int, str]] = []
    matcher = difflib.SequenceMatcher(a=(old or "").splitlines(), b=new.splitlines(), autojunk=False)
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            out += [(j + 1, line) for j, line in enumerate(new.splitlines()[j1:j2], start=j1)]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        die("usage: python3 verify/prose_gate.py <scanner.py> <base-ref>")
    scanner = load_scanner(pathlib.Path(argv[0]))
    top = git("rev-parse", "--show-toplevel")
    if top.returncode:
        die(top.stderr.strip())
    root = pathlib.Path(top.stdout.strip())
    mb = git("merge-base", argv[1], "HEAD")
    if mb.returncode:
        die(f"{argv[1]} has no merge base with HEAD: {mb.stderr.strip() or 'unknown ref'}")
    base = mb.stdout.strip()

    scoped = [p for p in changed_paths(base) if p.lower().endswith(PUBLIC_PROSE) and scanner.is_prose(p)]
    if not scoped:
        print(f"prose gate: no public-prose file changed since {base[:12]}")
        return 0

    before: dict[str, object] = {}
    after: dict[str, object] = {}
    texts: dict[str, tuple[str | None, str | None]] = {}
    held: list[str] = []
    for path in scoped:
        old, new = at_base(base, path), in_tree(root, path)
        if new is not None and scanner.exempt(new):
            if old is None or not scanner.exempt(old):
                held.append(f"{path} newly declares itself exempt from the AI-isms checker")
            continue
        vouched = old is not None and not scanner.exempt(old)
        before[path] = scanner.scan(old, path) if vouched else scanner.EMPTY
        after[path] = scanner.scan(new, path) if new is not None else scanner.EMPTY
        texts[path] = (old if vouched else None, new)
    total: Counter[str] = Counter()
    for s in after.values():
        total.update(s.counts)
    for s in before.values():
        total.subtract(s.counts)
    grew = +total

    failed = 0
    for path in after:
        found = scanner.added(before[path], after[path], grew)
        if not found:
            continue
        failed += 1
        print(f"FAIL  {path}: {', '.join(found)}")
        old, new = texts[path]
        gained = {label for label, n in (after[path].counts - before[path].counts).items() if n and grew[label] > 0}
        for number, line in added_lines(old, new or ""):
            hits = sorted(label for label, n in scanner.scan(line, path).counts.items() if n and label in gained)
            if hits:
                print(f"      line {number} ({', '.join(hits)}): {line.strip()}")
    for item in held:
        print(f"HELD  {item}")
    if failed or held:
        print(f"\nprose gate: {failed} file(s) fail and {len(held)} held, of {len(scoped)} public-prose file(s) "
              f"changed since {base[:12]}")
        return 1
    print(f"prose gate: pass, {len(after)} public-prose file(s) read against {base[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
