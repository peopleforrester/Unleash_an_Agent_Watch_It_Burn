# ABOUTME: Reads prompts-agenticburn's test_wall_page.py and conftest.py and names each way its burst tests could stop
# ABOUTME: holding #927's criterion: a fake clock, no network, and card count, shown prompt and "+N more" after each tick.
"""The static half of #936's check, with no network, so verify/test_wall_clock_burst.py can feed it made-up sources.

Why (#936). #927's criterion reads: "An offline test in prompts-agenticburn with a controlled clock (no real timers,
no network) feeds a burst of prompts and checks the card count, which prompt was shown, and the counter value after
each tick." prompts-agenticburn#18 landed that test in that repo (`6601313a`, test_wall_page.py). This repo cannot
change prompts-agenticburn, so the test that fails when the criterion stops holding reads that repo's file and holds
it to the criterion. verify/test_wall_clock_burst_sister_e2e.py downloads the file and runs it; this module is the
reading.

What `analyse()` holds, each as one named check:

- The page runs in MiniRacer (bare V8, which has no setTimeout, setInterval, fetch or EventSource of its own), and the
  JavaScript evaluated into it before the page defines all four as fakes, plus a `performance.now()` that returns the
  same virtual clock the fake timers fire on. So no real timer runs and no request leaves the process.
- The page's script is the one the wall serves at `/` (wall.html), not another page's.
- The test module imports no network client, and conftest.py turns the wall's fleet poller off.
- At least one test is a burst test: it hands `wall.ingest()` two or more prompts in one call, advances the virtual
  clock at least twice with `page.advance()`, asserts on the page (its cards or its "+N more") after every advance
  before the next one, and over those asserts reads the card count, the shown prompt's text and the counter.
"""
from __future__ import annotations

import ast
import dataclasses
import re

NETWORK_MODULES = {"requests", "httpx", "urllib.request", "http.client", "socket", "aiohttp"}


@dataclasses.dataclass
class Result:
    checks: list[tuple[str, bool, str]]
    burst_tests: list[str]

    @property
    def failed(self) -> list[str]:
        return [name for name, ok, _ in self.checks if not ok]


def _js_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level NAME = "..." string constants, which is where the fake browser's JavaScript lives."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _evaluated_names(tree: ast.Module) -> set[str]:
    """Names passed to any `<x>.eval(NAME)` call: the JavaScript the test puts into V8."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "eval"
                and node.args and isinstance(node.args[0], ast.Name)):
            names.add(node.args[0].id)
    return names


def _imports(tree: ast.Module) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def _fake_clock(js: str) -> tuple[bool, str]:
    """The JavaScript defines setTimeout, setInterval and performance.now on one virtual clock variable."""
    now = re.search(r"performance\s*=\s*\{\s*now\s*\(\s*\)\s*\{\s*return\s+(\w+)\s*;?\s*\}", js)
    if not now:
        return False, "no `performance = { now(){ return <clock>; } }`"
    clock = now.group(1)
    for fn in ("setTimeout", "setInterval"):
        body = re.search(rf"function\s+{fn}\s*\([^)]*\)\s*\{{(.*?)\}}\s*$", js, re.M)
        if not body:
            return False, f"no `function {fn}(...)` fake"
        if not re.search(rf"\b{clock}\b", body.group(1)):
            return False, f"{fn} does not schedule on `{clock}`, the clock performance.now() reads"
    return True, ""


def _reads(test: ast.Assert) -> set[str]:
    """What an assert reads from the page: "count", "text" and "more"."""
    src = ast.unparse(test)
    out: set[str] = set()
    if "len(page.cards())" in src:
        out.add("count")
    if "page.cards()" in src and re.search(r"\[\s*['\"]text['\"]\s*\]", src):
        out.add("text")
    if "browser.more()" in src:
        out.add("more")
    if "page.cards()" in src:
        out.add("cards")
    return out


def _is_burst(call: ast.Call) -> bool:
    """`wall.ingest(cluster, prompts)` with two or more prompts in the one call."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "ingest"
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "wall" and len(call.args) >= 2):
        return False
    prompts = call.args[1]
    if isinstance(prompts, ast.List):
        return len(prompts.elts) >= 2
    if isinstance(prompts, ast.ListComp):
        gen = prompts.generators[0].iter
        if isinstance(gen, ast.Call) and isinstance(gen.func, ast.Name) and gen.func.id == "range":
            bounds = [a.value for a in gen.args if isinstance(a, ast.Constant) and isinstance(a.value, int)]
            if len(bounds) == len(gen.args):
                span = range(*bounds)
                return len(span) >= 2
        return True
    return False


def burst_test_gaps(fn: ast.FunctionDef) -> list[str]:
    """What keeps one test function from being a burst test; empty when it is one."""
    gaps: list[str] = []
    if not any(isinstance(n, ast.Call) and _is_burst(n) for n in ast.walk(fn)):
        gaps.append("feeds no burst (no wall.ingest() call with two or more prompts)")
    ticks = sorted(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "advance" and isinstance(n.func.value, ast.Name) and n.func.value.id == "page")
    if len(ticks) < 2:
        gaps.append(f"advances the virtual clock {len(ticks)} time(s), fewer than 2")
    asserts = sorted(((n.lineno, _reads(n)) for n in ast.walk(fn) if isinstance(n, ast.Assert)), key=lambda a: a[0])
    seen: set[str] = set()
    for i, tick in enumerate(ticks):
        end = ticks[i + 1] if i + 1 < len(ticks) else float("inf")
        after = set().union(*([r for line, r in asserts if tick < line < end] or [set()]))
        if not after & {"cards", "more"}:
            gaps.append(f"asserts nothing on the page after the tick on line {tick}")
        seen |= after
    for what, label in (("count", "the card count (len(page.cards()))"),
                        ("text", "which prompt was shown (a card's \"text\")"),
                        ("more", "the counter (browser.more())")):
        if what not in seen:
            gaps.append(f"never asserts {label} after a tick")
    return gaps


def analyse(test_src: str, conftest_src: str) -> Result:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    tree = ast.parse(test_src)
    mods = _imports(tree)
    check("the page runs in MiniRacer, a bare V8 with no timers or network of its own",
          "py_mini_racer" in mods or "py_mini_racer.MiniRacer" in mods, f"imports: {sorted(mods)}")

    consts = _js_constants(tree)
    evaluated = _evaluated_names(tree)
    fakes = {name: js for name, js in consts.items() if name in evaluated and "function setTimeout" in js}
    check("a fake browser is evaluated into V8 (a module constant defining setTimeout, passed to .eval())",
          len(fakes) == 1, f"candidates: {sorted(fakes)}")
    js = next(iter(fakes.values()), "")
    ok, why = _fake_clock(js)
    check("its setTimeout, setInterval and performance.now() run on one virtual clock", ok, why)
    check("it advances that clock only when the test says so (an advance(ms) that fires due timers)",
          re.search(r"\badvance\s*\(\s*\w+\s*\)\s*\{", js) is not None)
    check("its fetch is a fake that only queues the request", re.search(r"function\s+fetch\s*\(", js) is not None)
    check("its EventSource is a fake that only records the stream", re.search(r"class\s+EventSource\b", js) is not None)
    check("the page's script is the one the wall serves at / (wall.html)",
          re.search(r"client\.get\(\s*['\"]/['\"]\s*\)", test_src) is not None
          and re.search(r"<script>", test_src) is not None)
    net = sorted(m for m in mods if m in NETWORK_MODULES or m.split(".")[0] in {"requests", "httpx", "aiohttp", "socket"})
    check("the test module imports no network client", not net, f"imports {net}")
    check("conftest.py turns the wall's fleet poller off before the app is imported",
          re.search(r"os\.environ\[\s*['\"]WALL_POLLER['\"]\s*\]\s*=\s*['\"]off['\"]", conftest_src) is not None)

    tests = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
             and any(a.arg == "page" for a in n.args.args)]
    burst = [fn.name for fn in tests if not burst_test_gaps(fn)]
    detail = "; ".join(f"{fn.name}: {', '.join(burst_test_gaps(fn))}" for fn in tests)
    check("at least one page test feeds a burst and, after each tick, asserts card count, shown prompt and counter",
          bool(burst), detail)
    return Result(checks, burst)
