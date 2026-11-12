# ABOUTME: Holds verify/deck_renumber.py (#1391) on fixtures: under #1390's map 42 and 43 swap, 46 moves to 45 once,
# ABOUTME: a cut slide's citation and a dated-history line are left and reported, and a dry run writes nothing.
"""verify/deck_renumber.py, the tool #1390's apply step runs to move the deck's hash citations (#1391).

Every fixture is built here with H(n), so neither this file nor the tool spells a hash of 43 or more as a literal,
which #1099's deck-shift citation test would read as a stale citation; the last section checks that on
both sources. Nothing here reads the run-of-show or /kubecon.

  1. The 1390 preset keeps 0 to 41 and 44, swaps 42 and 43, cuts 45 and moves 46 to 126 down one.
  2. On a fixture line, 42 and 43 swap in one pass, and 46 becomes 45 and is not then cut as a 45.
  3. A line citing the cut slide keeps that hash and is reported with its file and line; the line's other hashes
     still move.
  4. A line naming a commit SHA, and a line matching a --history pattern, keep every hash and are reported; with
     --no-default-history the SHA line moves.
  5. Bare integers and hashes the map does not name are left; a map that merges two slides is refused.
  6. The CLI's dry run prints the change, the cut line and the history line with file and line, and leaves the
     file's bytes as they were; without --dry-run it writes the moved file, CRLF endings kept.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE / "deck_renumber.py"
spec = importlib.util.spec_from_file_location("deck_renumber", TOOL)
dr = importlib.util.module_from_spec(spec)
sys.modules["deck_renumber"] = dr
spec.loader.exec_module(dr)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def H(n: int) -> str:
    return "#" + "/" + str(n)


P1390 = dr.preset_1390()
DEFAULT = list(dr.DEFAULT_HISTORY)


def run(text: str, history=None, mapping=None) -> tuple[str, "dr.Report"]:
    return dr.renumber_text(text, P1390 if mapping is None else mapping, DEFAULT if history is None else history,
                            "fx.md")


print("== the 1390 preset (#1390's map) ==")
check("0 to 41 stay", all(P1390[n] == n for n in range(42)))
check("42 and 43 swap", P1390[42] == 43 and P1390[43] == 42)
check("44 stays", P1390[44] == 44)
check("45 is cut", 45 in P1390 and P1390[45] is None)
check("46 to 126 become 45 to 125", all(P1390[n] == n - 1 for n in range(46, 127)))
check("nothing past 126 is mapped", max(P1390) == 126)
dr.check_map(P1390)
check("the preset is one-to-one, so no two slides merge", True)
check("the CLI offers it as --preset 1390", "1390" in dr.PRESETS)

print("== one pass: the swap, and the shift without a double move ==")
line = f"Challenge 3 opens on {H(42)}, the heading is {H(43)}, the desk {H(44)}, then {H(46)} and {H(126)}.\n"
new, rep = run(line)
want = f"Challenge 3 opens on {H(43)}, the heading is {H(42)}, the desk {H(44)}, then {H(45)} and {H(125)}.\n"
check("42 and 43 swap on one line", new == want, repr(new))
check(f"{H(46)} becomes {H(45)} and stays there, not cut as a 45", H(45) in new and not rep.cut, repr(rep.cut))
check("the change is reported with its file, line and each move",
      [(c[0], c[1], c[4]) for c in rep.changes] == [("fx.md", 1, [(42, 43), (43, 42), (46, 45), (126, 125)])],
      repr(rep.changes))
two = f"{H(43)}\n{H(42)}\n"
check("a swap across lines holds as well", run(two)[0] == f"{H(42)}\n{H(43)}\n")
check("a three-digit hash moves as a whole, not by its two-digit prefix",
      run(f"{H(4)} {H(100)}\n")[0] == f"{H(4)} {H(99)}\n")

print("== a cut slide's citation is left and reported ==")
cut_text = f"intro\nthe desk slide ({H(45)}) and the next ({H(46)})\n"
new, rep = run(cut_text)
check("the cut hash is not rewritten and the line's other hash still moves",
      new == f"intro\nthe desk slide ({H(45)}) and the next ({H(45)})\n", repr(new))
check("the cut citation is reported with file and line", [(c[0], c[1], c[2]) for c in rep.cut] == [("fx.md", 2, [45])],
      repr(rep.cut))

print("== dated history keeps its numbers ==")
sha_line = f"`4627d95` moves that slide back, adds the lines on {H(45)} and {H(67)}\n"
new, rep = run(sha_line)
check("a line naming a commit SHA is left whole", new == sha_line, repr(new))
check("it is reported as history with file, line and its hashes",
      [(h[0], h[1], h[2]) for h in rep.history] == [("fx.md", 1, [45, 67])] and not rep.cut, repr(rep.history))
dated = f"Read from rounds main on 2026-11-09: the card on {H(68)}\n"
new, rep = run(dated, history=DEFAULT + [re.compile(r"Read from rounds")])
check("a line matching a --history pattern is left whole and reported", new == dated and len(rep.history) == 1)
new, rep = run(dated)
check("without that pattern the same line moves", new == dated.replace(H(68), H(67)) and not rep.history)
new, rep = run(sha_line, history=[])
check("with no history rules the SHA line moves, and its cut hash is still left",
      new == sha_line.replace(H(67), H(66)) and [c[2] for c in rep.cut] == [[45]], repr(new))
for name, text in {"an HTML colour": f"color #a1b2c3d4 on {H(50)}\n", "a word's hex tail": f"run abcdef12x {H(50)}\n",
                   "seven digits": f"1234567 seats, {H(50)}\n", "seven letters": f"defaced {H(50)}\n"}.items():
    check(f"{name} is not read as a SHA", run(text)[0] == text.replace(H(50), H(49)))

print("== bare integers, unmapped hashes and a bad map ==")
code = f"FIRST = 42\nslide = deck[46]\nurl = 'x{H(46)}'\n"
new, _ = run(code)
check("bare integers stay; only the hash moves", new == f"FIRST = 42\nslide = deck[46]\nurl = 'x{H(45)}'\n", repr(new))
new, rep = run(f"past the close, {H(127)}\n")
check("a hash the map does not name is left and reported", H(127) in new and [u[2] for u in rep.unmapped] == [[127]])
try:
    dr.check_map({1: 2, 3: 2})
    merged = False
except ValueError:
    merged = True
check("a map sending two slides to one is refused", merged)

print("== the CLI: dry run and write ==")
with tempfile.TemporaryDirectory() as d:
    f = pathlib.Path(d) / "fx.md"
    body = (f"swap {H(42)} {H(43)}\r\nshift {H(46)}\r\ndesk {H(45)}\r\n"
            f"rounds `faf4005` on 2026-11-09, {H(48)}\r\nnone here\r\n")
    f.write_bytes(body.encode())
    before = f.read_bytes()
    res = subprocess.run([sys.executable, str(TOOL), "--preset", "1390", "--dry-run", str(f)],
                         capture_output=True, text=True, check=False)
    out = res.stdout
    check("the dry run exits 0", res.returncode == 0, res.stderr)
    check("the dry run writes nothing", f.read_bytes() == before)
    check("it prints each change with file and line, old and new",
          f"CHANGE {f}:1: {H(42)} -> {H(43)}, {H(43)} -> {H(42)}" in out and f"CHANGE {f}:2: {H(46)} -> {H(45)}" in out
          and f"  + shift {H(45)}" in out, out)
    check("it prints the cut citation with file and line", f"CUT {f}:3: {H(45)}" in out, out)
    check("it prints the history line with file and line", f"HISTORY {f}:4: left as dated history: {H(48)}" in out, out)
    check("it says nothing was written", "dry run, nothing written" in out.splitlines()[-1], out)
    res = subprocess.run([sys.executable, str(TOOL), "--preset", "1390", str(f)], capture_output=True, text=True,
                         check=False)
    want = (f"swap {H(43)} {H(42)}\r\nshift {H(45)}\r\ndesk {H(45)}\r\n"
            f"rounds `faf4005` on 2026-11-09, {H(48)}\r\nnone here\r\n")
    check("without --dry-run the file is rewritten, CRLF kept, cut and history lines as they were",
          res.returncode == 0 and f.read_bytes() == want.encode(), repr(f.read_bytes()))
    m = pathlib.Path(d) / "m.json"
    m.write_text(json.dumps({"3": 4, "4": 3, "5": None}))
    g = pathlib.Path(d) / "g.md"
    g.write_text(f"{H(3)} {H(4)} {H(5)}\n")
    res = subprocess.run([sys.executable, str(TOOL), "--map", str(m), str(g)], capture_output=True, text=True,
                         check=False)
    check("a --map file is read: 3 and 4 swap, 5 is cut", g.read_text() == f"{H(4)} {H(3)} {H(5)}\n", g.read_text())
    m.write_text(json.dumps({"3": 4, "5": 4}))
    res = subprocess.run([sys.executable, str(TOOL), "--map", str(m), "--dry-run", str(g)], capture_output=True,
                         text=True, check=False)
    check("a merging --map file exits 2 naming both hashes", res.returncode == 2 and "3 and 5" in res.stderr,
          res.stderr)

print("== its own sources spell no hash of 43 or more ==")
for src in (TOOL, pathlib.Path(__file__).resolve()):
    stale = [n for n in re.findall(r"#/(\d+)", src.read_text(encoding="utf-8")) if int(n) >= 43]
    check(f"{src.name} holds no literal hash of 43 or more, for #1099's deck-shift test", not stale,
          repr(stale))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll #1391 deck_renumber checks passed.")
