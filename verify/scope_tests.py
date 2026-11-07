#!/usr/bin/env python3
# ABOUTME: Scopes the two runners to what a change touched (#1018): reads verify/scope-map.yaml, the committed map of
# ABOUTME: each test to the repo paths it reads, and with HECATON_BASE_SHA set says which tests the change can affect.
"""Which tests a change can affect.

    python3 verify/scope_tests.py select offline|tools   the plan for HECATON_BASE_SHA..HEAD (stdout), why (stderr)
    python3 verify/scope_tests.py check                  exit 1 naming each way the map is out of date
    python3 verify/scope_tests.py write                  add what the extractor finds to the map, keeping the rest

The map, verify/scope-map.yaml, has five parts:

    full    changed paths that run everything: the runners, this file, and the helpers and config that many tests
            read (every verify/ helper that more than SHARED_HELPER tests read must be listed here)
    unread  changed paths that are known and that no test reads beyond those whose own entry names them
    bounds  helpers that build paths from repo data, each with the paths that bound what it builds and why;
            test_scope_tests.py holds each bound against the data
    always  tests that run on every scoped run, each with why: they read the whole repo or its git history
    reads   every other test the two runners run, with each repo path it reads. A path covers itself and everything
            under it; one holding * or ? is a glob in which * also crosses /

A changed path selects the tests whose reads cover it, and a changed test selects itself. A changed path that is in
full, or that no entry covers and unread does not name, runs the whole suite, so nothing is skipped silently. A
change to the map itself runs the whole suite when it edits full, unread or bounds, and otherwise runs each test
whose own entry it edits: a test cannot drop a path from its entry in the same change that edits the path and so
leave itself out, since the edit to its entry runs it.

`check` holds the map to what extract() reads in each test's source: every path literal, every path built from
literals, every helper it imports or names, and every glob or directory walk. A test that starts to read a path its
entry does not cover fails the offline suite through test_test_scope.py, which runs on every scoped run.
"""
from __future__ import annotations

import ast
import fnmatch
import os
import pathlib
import re
import subprocess
import sys

import yaml

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
MAP = VERIFY / "scope-map.yaml"
# A verify/ helper read by more tests than this, about a tenth of the offline suite, is shared: a change to it runs the
# whole suite, as one to a runner does.
SHARED_HELPER = 30
# The runners themselves: a test that names one reads its text, never runs the real suite.
RUNNERS = {"verify/run-tests.sh", "verify/run-e2e-tools.sh", "verify/run-e2e.sh", "verify/run-all.sh"}
# git subcommands that read the repo's tree or history rather than a file of it.
GIT_READS = {"ls-files", "grep", "log", "show", "diff", "ls-tree", "cat-file", "rev-list", "blame", "archive",
             "diff-tree", "whatchanged", "shortlog"}
PATH_FUNCS = {"Path", "PurePath", "PosixPath", "abspath", "realpath", "normpath", "resolve", "absolute", "expanduser",
              "fspath", "str"}
WALKS = {"walk", "listdir", "scandir", "iterdir"}
TRAILING = ".,:;)]}>'\"`!?"


# ---------------------------------------------------------------------------------------------------------------------
# The repo as git has it


class Tree:
    """The tracked files, their directories and the submodules, read once."""

    def __init__(self, root: pathlib.Path = REPO):
        self.root = root
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-s"], capture_output=True, text=True, check=True)
        self.files: set[str] = set()
        self.submodules: set[str] = set()
        for line in out.stdout.splitlines():
            meta, path = line.split("\t", 1)
            (self.submodules if meta.startswith("160000") else self.files).add(path)
        self.dirs: set[str] = set()
        for f in self.files | self.submodules:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.top = {p.split("/")[0] for p in self.files | self.submodules}
        self.all = sorted(self.files | self.submodules)

    def known(self, p: str) -> str | None:
        """p as a map entry when it names a tracked file, directory or submodule (or a path inside one)."""
        if p in self.files or p in self.dirs or p in self.submodules:
            return p
        for s in self.submodules:
            if p.startswith(s + "/"):
                return s
        return None

    def matches(self, pattern: str) -> bool:
        return any(covers(pattern, f) for f in self.all) or any(covers(pattern, d) for d in self.dirs)


def suite_of(path: pathlib.Path) -> str | None:
    """offline, tools or None (a live-only e2e test, which neither runner here runs)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"^# SUITE: e2e", text, re.M):
        return "tools" if re.search(r"^# E2E TIER: tools", text, re.M) else None
    return "offline"


def discover(verify: pathlib.Path = VERIFY) -> dict[str, str]:
    """Each test the two runners run, by file name, with its suite: the same globs and markers the runners read."""
    found = {}
    for t in sorted(verify.glob("test_*.py")) + sorted(verify.glob("test_*.sh")):
        s = suite_of(t)
        if s:
            found[t.name] = s
    return found


def names(entry: str) -> bool:
    """The entry names a path or a directory, as opposed to a glob over the whole tree like *.md. Only an entry that
    names a path counts for whether the map covers a changed path; a scan of the whole tree covers everything."""
    head = re.split(r"[*?\[]", entry, maxsplit=1)[0]
    return head == entry or "/" in head


def covers(entry: str, path: str) -> bool:
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatchcase(path, entry) or fnmatch.fnmatchcase(path, entry.rstrip("/") + "/*")
    return path == entry or path.startswith(entry + "/") or entry == ""


# ---------------------------------------------------------------------------------------------------------------------
# What a test reads, from its source


def _norm(p: str) -> str | None:
    p = os.path.normpath(p)
    if p == ".":
        return ""
    if p.startswith("..") or p.startswith("/"):
        return None
    return p


class Extraction:
    def __init__(self):
        self.paths: set[str] = set()       # map entries the source reads
        self.why_always: list[str] = []    # why it reads the whole tree or its history
        self.runtime: list[str] = []       # each place it builds a path from a value found at run time

    def unbounded(self) -> list[str]:
        return self.why_always + self.runtime


def _candidates(raw: str, path_context: bool, here: str, tree: Tree, out: Extraction) -> None:
    """Resolve one string the source holds against the repo root, verify/ and the file's own directory."""
    s = raw.strip()
    if not s or "\n" in s or "://" in s or len(s) > 300:
        return
    if " " in s or "\t" in s:
        for tok in s.split():
            tok = tok.strip(TRAILING).lstrip("(['\"`")
            if "/" in tok or re.search(r"\.[A-Za-z0-9]{1,6}$", tok):
                _candidates(tok, False, here, tree, out)
        return
    s = s.strip(TRAILING) if not any(c in s for c in "*?[") else s.rstrip(".,:;)'\"`")
    if s.startswith("./"):
        s = s[2:]
    if not s or s.startswith("/") or s.startswith("-"):
        return
    single = "/" not in s.rstrip("/")
    head = re.split(r"[*?\[]", s, maxsplit=1)[0]
    static = "/" in head  # a glob with a directory before its first wildcard
    for base in dict.fromkeys(("", "verify", here)):
        p = _norm(os.path.join(base, s)) if base else _norm(s)
        if p is None or p == "":
            continue
        if any(c in p for c in "*?["):
            if (path_context or static) and tree.matches(p):
                out.paths.add(p)
            continue
        k = tree.known(p)
        if k is not None:
            if single and k in tree.dirs and not path_context:
                continue  # a bare word like "images" outside a path expression is a word, not the directory
            out.paths.add(k)
            continue
        # A path the repo does not have yet: a check that it stays absent reads it too.
        if not base and not single and p.split("/")[0] in tree.top and re.fullmatch(r"[\w.@+-]+(/[\w.@+-]+)+/?", s):
            out.paths.add(p)


CAP = 256  # the most values one expression folds to before it counts as unknown


def _join(a: str, b: str) -> str | None:
    if b.startswith("/"):
        return None
    return _norm(os.path.join(a, b)) if a else _norm(b)


class _PathEval:
    """Folds a Python expression to the repo-relative paths it can hold, where its parts are literals.

    REPO / "a" / "b" folds to {"a/b"}, and `for d in ("gitops", "policies"): REPO / d` to both. The root is "". An
    expression that holds anything else (a parameter, a value read from a file) folds to None, unknown.
    """

    SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
              ast.GeneratorExp)

    def __init__(self, tree_ast: ast.AST, file_rel: str):
        self.file_rel = file_rel
        self.memo: dict[int, frozenset[str] | None] = {}
        self.parent: dict[int, ast.AST] = {}
        for node in ast.walk(tree_ast):
            for child in ast.iter_child_nodes(node):
                self.parent[id(child)] = node
        # (scope, name) -> the name's bindings in that scope: ("value", expr) / ("iter", expr, index path) / ("opaque",)
        self.env: dict[tuple[int, str], list[tuple]] = {}
        self.calls: dict[str, list[ast.Call]] = {}
        self.loads: dict[str, list[ast.Name]] = {}
        for node in ast.walk(tree_ast):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    self._bind(tgt, ("value", node.value))
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                self._bind(node.target, ("value", node.value), scope=self.scope_of(node) if
                           isinstance(node, ast.AnnAssign) else self._walrus_scope(node))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._bind(node.target, ("iter", node.iter, ()))
            elif isinstance(node, ast.comprehension):
                self._bind(node.target, ("iter", node.iter, ()), scope=self.parent[id(node)])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = node.args
                plain = isinstance(node, ast.FunctionDef) and not node.decorator_list and \
                    isinstance(self.scope_of(node), (ast.Module, ast.FunctionDef))
                for arg in a.posonlyargs + a.args + a.kwonlyargs:
                    self.env.setdefault((id(node), arg.arg), []).append(("param", node, arg.arg) if plain else
                                                                        ("opaque",))
                for arg in (a.vararg, a.kwarg):
                    if arg:
                        self.env.setdefault((id(node), arg.arg), []).append(("opaque",))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.calls.setdefault(node.func.id, []).append(node)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.loads.setdefault(node.id, []).append(node)
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                self._bind(node.optional_vars, ("opaque",))
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                self.env.setdefault((id(self.scope_of(node)), node.target.id), []).append(("opaque",))
            elif isinstance(node, ast.ExceptHandler) and node.name:
                self.env.setdefault((id(self.scope_of(node)), node.name), []).append(("opaque",))

    def scope_of(self, node: ast.AST) -> ast.AST:
        up = self.parent.get(id(node))
        while up is not None and not isinstance(up, self.SCOPES):
            up = self.parent.get(id(up))
        return up

    def _walrus_scope(self, node: ast.AST) -> ast.AST:
        s = self.scope_of(node)
        while isinstance(s, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            s = self.scope_of(s)
        return s

    def bindings(self, name: ast.Name) -> list[tuple] | None:
        """The bindings a name load sees: the for loop around it that binds it, else its own scope's, else each
        enclosing scope's in turn."""
        node, up = name, self.parent.get(id(name))
        while up is not None and not isinstance(up, self.SCOPES):
            if isinstance(up, (ast.For, ast.AsyncFor)) and any(node is b for b in up.body):
                found: dict[str, list[tuple]] = {}
                self._collect(up.target, ("iter", up.iter, ()), (), found)
                if name.id in found and not any(
                        isinstance(n, ast.Name) and n.id == name.id and isinstance(n.ctx, ast.Store)
                        for b in up.body for n in ast.walk(b)):
                    return found[name.id]
            node, up = up, self.parent.get(id(up))
        s = self.scope_of(name)
        while s is not None:
            got = self.env.get((id(s), name.id))
            if got:
                return got
            s = self.scope_of(s)
        return None

    def _bind(self, tgt: ast.AST, how: tuple, index: tuple = (), scope: ast.AST | None = None) -> None:
        if isinstance(tgt, ast.Name):
            if how[0] == "value" and index:
                how = ("unpack", how[1], index)
            elif how[0] == "iter":
                how = ("iter", how[1], index)
            sc = scope if scope is not None else self.scope_of(tgt)
            self.env.setdefault((id(sc), tgt.id), []).append(how)
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for i, e in enumerate(tgt.elts):
                self._bind(e, how, index + (i,), scope)
        elif isinstance(tgt, ast.Starred):
            self._bind(tgt.value, ("opaque",), (), scope)

    def _collect(self, tgt: ast.AST, how: tuple, index: tuple, found: dict[str, list[tuple]]) -> None:
        if isinstance(tgt, ast.Name):
            found.setdefault(tgt.id, []).append(("iter", how[1], index))
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for i, e in enumerate(tgt.elts):
                self._collect(e, how, index + (i,), found)
        elif isinstance(tgt, ast.Starred) and isinstance(tgt.value, ast.Name):
            found.setdefault(tgt.value.id, []).append(("opaque",))

    def _arguments(self, fn: ast.FunctionDef, param: str) -> list[ast.AST] | None:
        """What each call of fn in this file passes as param, or None when fn is also passed around uncalled."""
        calls = self.calls.get(fn.name, [])
        if len(self.loads.get(fn.name, [])) != len(calls) or not calls:
            return None
        a = fn.args
        positional = [x.arg for x in a.posonlyargs + a.args]
        defaults = dict(zip(positional[len(positional) - len(a.defaults):], a.defaults))
        defaults.update({x.arg: d for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
        out = []
        for c in calls:
            if any(isinstance(x, ast.Starred) for x in c.args) or any(k.arg is None for k in c.keywords):
                return None
            kw = {k.arg: k.value for k in c.keywords}
            if param in positional and positional.index(param) < len(c.args):
                out.append(c.args[positional.index(param)])
            elif param in kw:
                out.append(kw[param])
            elif param in defaults:
                out.append(defaults[param])
            else:
                return None
        return out

    def elements(self, node: ast.AST, depth: int = 0) -> list[ast.AST] | None:
        """The expressions a literal collection, or a name bound only to them, iterates over."""
        if depth > 20:
            return None
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                return None
            return list(node.elts)
        if isinstance(node, ast.Dict):
            return None if None in node.keys else list(node.keys)
        if isinstance(node, ast.Name):
            out = []
            for b in self.bindings(node) or [("opaque",)]:
                if b[0] != "value":
                    return None
                got = self.elements(b[1], depth + 1)
                if got is None:
                    return None
                out += got
            return out
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in ("sorted", "list", "tuple", "set", "reversed", "frozenset") \
                    and len(node.args) == 1:
                return self.elements(node.args[0], depth + 1)
            if isinstance(f, ast.Attribute) and f.attr in ("items", "keys", "values") and not node.args:
                d = f.value
                while isinstance(d, ast.Name):
                    vals = self.bindings(d) or []
                    if len(vals) != 1 or vals[0][0] != "value":
                        return None
                    d = vals[0][1]
                if not isinstance(d, ast.Dict) or None in d.keys:
                    return None
                if f.attr == "keys":
                    return list(d.keys)
                if f.attr == "values":
                    return list(d.values)
                return [ast.Tuple(elts=[k, v], ctx=ast.Load()) for k, v in zip(d.keys, d.values)]
        return None

    def __call__(self, node: ast.AST, depth: int = 0) -> frozenset[str] | None:
        key = id(node)
        if key not in self.memo:
            self.memo[key] = None  # a name bound to itself folds to nothing
            got = self._eval(node, depth)
            self.memo[key] = got if got is None or len(got) <= CAP else None
        return self.memo[key]

    def _binding(self, b: tuple, depth: int) -> frozenset[str] | None:
        if b[0] == "value":
            return self(b[1], depth + 1)
        if b[0] == "param":
            args = self._arguments(b[1], b[2])
            if args is None:
                return None
            vals: set[str] = set()
            for a in args:
                got = self(a, depth + 1)
                if got is None:
                    return None
                vals |= got
            return frozenset(vals)
        if b[0] in ("iter", "unpack"):
            elts = self.elements(b[1]) if b[0] == "iter" else [b[1]]
            if elts is None:
                return None
            vals: set[str] = set()
            for e in elts:
                for i in b[2]:
                    if not isinstance(e, (ast.Tuple, ast.List)) or i >= len(e.elts):
                        return None
                    e = e.elts[i]
                got = self(e, depth + 1)
                if got is None:
                    return None
                vals |= got
            return frozenset(vals)
        return None

    def _eval(self, node: ast.AST, depth: int) -> frozenset[str] | None:
        if depth > 60:
            return None
        ev = lambda n: self(n, depth + 1)  # noqa: E731
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return frozenset([node.value]) if node.value else None
        if isinstance(node, ast.Name):
            if node.id == "__file__":
                return frozenset([self.file_rel])
            binds = self.bindings(node)
            if not binds:
                return None
            vals: set[str] = set()
            for b in binds:
                got = self._binding(b, depth)
                if got is None:
                    return None
                vals |= got
            return frozenset(vals)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            a, b = ev(node.left), ev(node.right)
            if a is None or b is None or len(a) * len(b) > CAP:
                return None
            if isinstance(node.op, ast.Add):
                return frozenset((y[1:] if x == "" and y.startswith("/") else x + y) for x in a for y in b)
            got = {_join(x, y) for x in a for y in b}
            return None if None in got else frozenset(got)
        if isinstance(node, ast.JoinedStr):
            acc = {""}
            for i, v in enumerate(node.values):
                got = ev(v.value) if isinstance(v, ast.FormattedValue) else ev(v)
                if got is None or len(acc) * len(got) > CAP:
                    return None
                acc = {(y[1:] if x == "" and i > 0 and y.startswith("/") else x + y) for x in acc for y in got}
            return frozenset(acc)
        if isinstance(node, ast.Attribute):
            base = ev(node.value)
            if base is not None and node.attr == "parent":
                return frozenset(os.path.dirname(x) for x in base)
            return None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            base = ev(node.value.value)
            idx = node.slice
            if base is None or not (isinstance(idx, ast.Constant) and isinstance(idx.value, int)):
                return None
            out = set()
            for x in base:
                for _ in range(idx.value + 1):
                    x = os.path.dirname(x)
                out.add(x)
            return frozenset(out)
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if name in PATH_FUNCS:
                if isinstance(f, ast.Attribute) and name in ("resolve", "absolute", "expanduser") and not node.args:
                    return ev(f.value)
                if len(node.args) == 1 and not node.keywords:
                    return ev(node.args[0])
                return None
            if name == "joinpath" and isinstance(f, ast.Attribute):
                acc = ev(f.value)
                for a in node.args:
                    got = ev(a)
                    if acc is None or got is None or len(acc) * len(got) > CAP:
                        return None
                    joined = {_join(x, y) for x in acc for y in got}
                    acc = None if None in joined else frozenset(joined)
                return acc
            if name == "join" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == "path" and node.args:
                acc = ev(node.args[0])
                for a in node.args[1:]:
                    got = ev(a)
                    if acc is None or got is None or len(acc) * len(got) > CAP:
                        return None
                    joined = {_join(x, y) for x in acc for y in got}
                    acc = None if None in joined else frozenset(joined)
                return acc
            if name == "dirname" and node.args:
                base = ev(node.args[0])
                return frozenset(os.path.dirname(x) for x in base) if base is not None else None
        return None


def _extract_python(src: str, rel: str, tree: Tree, out: Extraction) -> list[str]:
    """Paths and helpers a Python file reads. Returns the verify/ helpers it imports."""
    try:
        mod = ast.parse(src)
    except SyntaxError as e:
        out.why_always.append(f"its source does not parse ({e.msg}, line {e.lineno})")
        return []
    here = os.path.dirname(rel)
    ev = _PathEval(mod, rel)
    parent = ev.parent
    imports = []
    consts = set()

    def path_op(up: ast.AST, node: ast.AST) -> bool:
        """up builds a path from node: a / or +, an f-string, .parent, Path(), os.path.join(), joinpath()."""
        if isinstance(up, (ast.BinOp, ast.JoinedStr, ast.Subscript)):
            return True
        if isinstance(up, ast.Attribute):
            return up.attr in ("parent", "parents")
        if isinstance(up, ast.Call):
            f = up.func
            if isinstance(f, ast.Name):
                return f.id in PATH_FUNCS and node in up.args
            if isinstance(f, ast.Attribute):
                return (f.attr in PATH_FUNCS | {"joinpath", "join", "dirname"}) and (f.value is node or node in up.args)
        return False

    def builds_on(node: ast.AST) -> bool:
        """The node is a part of a larger path expression, which is read in its place: REPO in REPO / "a"."""
        up = parent.get(id(node))
        if isinstance(up, ast.keyword):
            return up.arg in ("cwd", "dir")  # where a command runs, or a temp dir is made, is not a file it reads
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute) and up.func.attr in ("insert", "append") \
                and isinstance(up.func.value, ast.Attribute) and up.func.value.attr == "path":
            return True  # sys.path: what it imports from there is followed as an import
        if isinstance(up, ast.FormattedValue):
            up = parent.get(id(up))
        if up is not None and path_op(up, node):
            return ev(up) is not None
        if isinstance(up, (ast.Assign, ast.AnnAssign)) and up.value is node:
            targets = up.targets if isinstance(up, ast.Assign) else [up.target]
            # A name bound once is read where it is used; a name bound to several values is read at each binding.
            return all(isinstance(t, ast.Name) and len(ev.env.get((id(ev.scope_of(t)), t.id), [])) == 1
                       for t in targets)
        return False

    def anchored_unknown(node: ast.AST) -> bool:
        """A path under the repo root whose rest is not a literal: REPO / name, with name read at run time."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = ev(node.left)
            return left is not None and "" in left and ev(node.right) is None
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.FormattedValue):
            first = ev(node.values[0].value)
            return first is not None and "" in first and ev(node) is None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            f = node.func
            if f.attr == "joinpath":
                base = ev(f.value)
                return base is not None and "" in base and ev(node) is None
            if f.attr == "join" and isinstance(f.value, ast.Attribute) and f.value.attr == "path":
                base = ev(node.args[0])
                return base is not None and "" in base and ev(node) is None
        return False

    for node in ast.walk(mod):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            consts.add(node.value)
            up = parent.get(id(node))
            # A bare directory name counts where a path is built from it or a collection of them is iterated.
            listed = isinstance(up, (ast.Tuple, ast.List, ast.Set)) or (isinstance(up, ast.Dict) and node in up.keys)
            if not builds_on(node):
                _candidates(node.value, listed, here, tree, out)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                top = n.split(".")[0]
                if (VERIFY / f"{top}.py").is_file():
                    imports.append(f"verify/{top}.py")
        elif isinstance(node, (ast.BinOp, ast.Call, ast.JoinedStr, ast.Subscript, ast.Attribute)) or \
                (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            vals = ev(node)
            if vals is not None and not builds_on(node):
                for p in vals:
                    if p and p != rel:
                        _candidates(p, True, "", tree, out)
            elif vals is None and anchored_unknown(node):
                out.runtime.append(f"line {node.lineno} builds a path under the repo root from a value it "
                                      "finds at run time")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if name in ("glob", "rglob") and isinstance(f, ast.Attribute):
                pats = ev(node.args[0]) if node.args else None
                if isinstance(f.value, ast.Name) and f.value.id == "glob":  # glob.glob(pattern)
                    if pats is None:
                        out.runtime.append(f"line {node.lineno} globs a pattern built at run time")
                    else:
                        for pat in pats:
                            _candidates(pat, True, "", tree, out)
                    continue
                recv = ev(f.value)
                if recv is not None and pats is not None:
                    for r in recv:
                        for pat in pats:
                            full = os.path.join(r, ("*" if name == "rglob" else "") + pat) if r else \
                                ("*" if name == "rglob" else "") + pat
                            out.paths.add(_norm(full) if "**" not in full else full)
                elif recv is not None and "" in recv:
                    out.runtime.append(f"line {node.lineno} calls {name}() on the repo root with a pattern "
                                          "built at run time")
                elif recv is not None:
                    for r in recv:
                        _candidates(r, True, "", tree, out)
            if name in WALKS:
                target = ev(f.value) if (name == "iterdir" and isinstance(f, ast.Attribute)) else \
                    (ev(node.args[0]) if node.args else None)
                if target is not None and "" in target:
                    out.runtime.append(f"line {node.lineno} lists the repo root with {name}()")
                elif target is not None:
                    for t in target:
                        _candidates(t, True, "", tree, out)
    if "git" in consts:
        subs = sorted(GIT_READS & consts)
        if subs:
            out.why_always.append(f"it runs git {', '.join(subs)}, which reads the tree or history as a whole")
    if "grep" in consts and ({"-r", "-R", "-rn", "-rl", "-Rn", "-rln"} & consts):
        out.why_always.append("it runs grep -r")
    return imports


SHELL_VAR_PREFIX = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/")


def _extract_text(src: str, rel: str, tree: Tree, out: Extraction, comment: str) -> None:
    """Paths a shell or JavaScript file reads: every path-shaped word outside a comment line."""
    here = os.path.dirname(rel)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(comment)]
    body = "\n".join(lines)
    if rel.endswith(".sh"):
        if re.search(r"\bgit\b[^\n|;&]*\b(" + "|".join(sorted(GIT_READS)) + r")\b", body):
            out.why_always.append("it runs git on the tree or history as a whole")
        if re.search(r"\bgrep\s+-[A-Za-z]*[rR]", body):
            out.why_always.append("it runs grep -r")
        if re.search(r"\bfind\s+(\.|\"?\$\{?(REPO|ROOT|REPO_DIR|REPO_ROOT)\}?\"?)(\s|$)", body):
            out.why_always.append("it runs find over the repo root")
    for m in SHELL_VAR_PREFIX.finditer(body):
        tail = re.match(r"[^\s'\"`;|&()<>]+", body[m.end():])
        if tail:
            _candidates(tail.group(0), True, here, tree, out)
    for tok in re.split(r"[\s'\"`;|&()<>=,{}\[\]]+", SHELL_VAR_PREFIX.sub(" ", body)):
        if tok and ("/" in tok or re.search(r"\.[A-Za-z0-9]{1,6}$", tok)):
            _candidates(tok, False, here, tree, out)


def extract(rel: str, tree: Tree, bounds: dict | None = None, _seen: set[str] | None = None) -> Extraction:
    """Every repo path the file at rel (repo-relative) reads, following the verify/ helpers it imports or names.

    bounds is the map's own: a file listed there builds paths from repo data, and the paths it lists bound them."""
    bounds = bounds or {}
    seen = _seen if _seen is not None else set()
    seen.add(rel)
    out = Extraction()
    path = tree.root / rel
    src = path.read_text(encoding="utf-8", errors="replace")
    helpers: list[str] = []
    if rel.endswith(".py"):
        helpers = _extract_python(src, rel, tree, out)
    elif rel.endswith(".js") or rel.endswith(".mjs"):
        _extract_text(src, rel, tree, out, "//")
    else:
        _extract_text(src, rel, tree, out, "#")
    if rel in bounds:
        out.runtime = []
        out.paths |= set(bounds[rel]["paths"])
    out.paths.discard(rel)
    out.paths.discard("")
    helpers += [p for p in out.paths if p.startswith("verify/") and not os.path.basename(p).startswith("test_")
                and p.endswith((".py", ".sh", ".js", ".mjs")) and (tree.root / p).is_file()]
    for h in sorted(set(helpers)):
        out.paths.add(h)
        if h in seen or h in RUNNERS:
            continue  # a runner is in full: a change to it runs everything, so what it reads needs no entry
        sub = extract(h, tree, bounds, seen)
        out.paths |= sub.paths
        out.why_always += [f"{h}: {w}" for w in sub.why_always]
        out.runtime += [f"{h}: {w}" for w in sub.runtime]
    return out


# ---------------------------------------------------------------------------------------------------------------------
# The map


def load_map(path: pathlib.Path = MAP) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    doc.setdefault("full", [])
    doc.setdefault("unread", [])
    doc["always"] = doc.get("always") or {}
    doc["reads"] = {k: list(v or []) for k, v in (doc.get("reads") or {}).items()}
    doc["bounds"] = doc.get("bounds") or {}
    return doc


def problems(doc: dict, tree: Tree, verify: pathlib.Path = VERIFY) -> list[str]:
    """Every way the map is out of date with the tests, the tree and what extract() reads."""
    bad = []
    tests = discover(verify)
    always, reads = doc["always"], doc["reads"]
    for name in tests:
        if name in always and name in reads:
            bad.append(f"{name} is in both always and reads; it belongs in one")
        elif name not in always and name not in reads:
            bad.append(f"{name} has no entry; run `python3 verify/scope_tests.py write` and review what it adds")
    for name in list(always) + list(reads):
        if name not in tests:
            bad.append(f"{name} is in the map but is not a test either runner runs; remove its entry")
    for name, why in always.items():
        if not isinstance(why, str) or not why.strip():
            bad.append(f"always: {name} says no reason")
    for part in ("full", "unread"):
        for e in doc[part]:
            if not tree.matches(e) and not tree.known(e):
                bad.append(f"{part}: {e} names nothing in the repo")
    for f, b in doc["bounds"].items():
        if f not in tree.files:
            bad.append(f"bounds: {f} is not a file in the repo")
        if not isinstance(b, dict) or not str(b.get("why", "")).strip() or not b.get("paths"):
            bad.append(f"bounds: {f} needs a why and the paths that bound it")
            continue
        for e in b["paths"]:
            if not tree.known(e) and not tree.matches(e):
                bad.append(f"bounds: {f} lists {e}, which names nothing in the repo")
    for name in tests:
        if name not in reads:
            continue
        x = extract(f"verify/{name}", tree, doc["bounds"])
        for w in x.unbounded():
            bad.append(f"{name} reads more than an entry can name ({w}); move it to always with that reason, or "
                       "bound the file that builds the path in bounds")
        for p in sorted(x.paths):
            if not any(covers(e, p) for e in reads[name]):
                bad.append(f"{name} reads {p}, which its entry does not cover")
    counts: dict[str, int] = {}
    for name, entries in reads.items():
        for e in entries:
            if e.startswith("verify/") and not os.path.basename(e).startswith("test_") and \
                    e.endswith((".py", ".sh", ".js")):
                counts[e] = counts.get(e, 0) + 1
    for helper, n in sorted(counts.items()):
        if n > SHARED_HELPER and not any(covers(f, helper) for f in doc["full"]):
            bad.append(f"{helper} is read by {n} tests, more than {SHARED_HELPER}, so it is shared: list it in full")
    return bad


def write(doc: dict, tree: Tree, verify: pathlib.Path = VERIFY) -> dict:
    """The map with each test's entry grown by what extract() finds; nothing already there is removed."""
    tests = discover(verify)
    for name in list(doc["reads"]):
        if name not in tests:
            del doc["reads"][name]
    for name in list(doc["always"]):
        if name not in tests:
            del doc["always"][name]
    for name in tests:
        if name in doc["always"]:
            continue
        x = extract(f"verify/{name}", tree, doc["bounds"])
        if x.unbounded():
            doc["reads"].pop(name, None)
            doc["always"][name] = "; ".join(dict.fromkeys(x.unbounded()))
            continue
        have = doc["reads"].get(name, [])
        new = [p for p in sorted(x.paths) if not any(covers(e, p) for e in have)]
        doc["reads"][name] = sorted(set(have) | set(new))
    return doc


def dump(doc: dict, path: pathlib.Path = MAP) -> None:
    head = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                break
            head.append(line)
    out = "\n".join(head) + ("\n" if head else "")
    for part in ("full", "unread"):
        out += f"{part}:" + ("" if doc[part] else " []") + "\n" + "".join(f"  - {yaml.safe_dump(e).strip().removesuffix(chr(10) + '...')}\n"
                                      for e in doc[part])
    out += "bounds:" + ("" if doc["bounds"] else " {}") + "\n"
    for k, v in sorted(doc["bounds"].items()):
        out += f"  {k}:\n    why: {yaml.safe_dump(v['why'], width=10**6).strip().removesuffix(chr(10) + '...')}\n"
        out += "    paths:\n" + "".join(f"      - {e}\n" for e in v["paths"])
    out += "always:\n" + "".join(f"  {k}: {yaml.safe_dump(v, width=10**6).strip().removesuffix(chr(10) + '...')}\n"
                                 for k, v in sorted(doc["always"].items()))
    out += "reads:\n"
    for k, v in sorted(doc["reads"].items()):
        out += f"  {k}:" + (" []\n" if not v else "\n" + "".join(f"    - {yaml.safe_dump(e).strip().removesuffix(chr(10) + '...')}\n" for e in v))
    path.write_text(out, encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------------
# Selection


def changed_paths(base: str, root: pathlib.Path = REPO) -> list[str]:
    """Every path that differs between base and the working tree, both sides of a rename, and untracked files."""
    def git(*args):
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"scope_tests: git {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout
    git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    paths = set(git("diff", "--name-only", "--no-renames", base).splitlines())
    paths |= set(git("ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(p for p in paths if p)


MAP_REL = "verify/scope-map.yaml"
RULES = ("full", "unread", "bounds")  # the map's own rules: a change to one runs everything


def base_map(base: str, root: pathlib.Path = REPO) -> dict | None:
    """The map as it stood at base, or None when base has none."""
    r = subprocess.run(["git", "-C", str(root), "show", f"{base}:{MAP_REL}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    doc = yaml.safe_load(r.stdout) or {}
    for part in RULES:
        doc[part] = doc.get(part) or ([] if part != "bounds" else {})
    doc["always"] = doc.get("always") or {}
    doc["reads"] = {k: list(v or []) for k, v in (doc.get("reads") or {}).items()}
    return doc


def entry(doc: dict, name: str):
    if name in doc["always"]:
        return ("always", doc["always"][name])
    if name in doc["reads"]:
        return ("reads", sorted(doc["reads"][name]))
    return None


def select(doc: dict, suite: str, changed: list[str], tests: dict[str, str],
           before: dict | None = None) -> tuple[str, dict[str, list[str]]]:
    """("full", {path: [why]}) or ("scoped", {test: [why]}) for the suite's tests.

    before is the map at the base, read when the change edits the map. A change to its rules (full, unread, bounds), or
    a map the base did not have, runs everything. A change to a test's own entry runs that test: an entry that stops
    covering a path the change also edits cannot leave its test out, since the test runs for the entry's change."""
    full_why: dict[str, list[str]] = {}
    entry_changed: set[str] = set()
    if MAP_REL in changed:
        if before is None:
            full_why[MAP_REL] = ["the base has no map to compare it with"]
        else:
            for part in RULES:
                if before[part] != doc[part]:
                    full_why.setdefault(MAP_REL, []).append(f"its {part} section changed")
            entry_changed = {n for n in set(doc["always"]) | set(doc["reads"]) | set(before["always"]) |
                             set(before["reads"]) if entry(doc, n) != entry(before, n)}
    for p in changed:
        if p == MAP_REL:
            continue
        hit = next((e for e in doc["full"] if covers(e, p)), None)
        if hit is not None:
            full_why.setdefault(p, []).append(f"it is in the map's full list ({hit})")
            continue
        if re.fullmatch(r"verify/test_[^/]*\.(py|sh)", p):
            continue  # a test: it runs itself below, and whoever reads it is in reads
        if any(names(e) and covers(e, p) for v in doc["reads"].values() for e in v):
            continue
        if any(covers(e, p) for e in doc["unread"]):
            continue
        full_why.setdefault(p, []).append("no entry in the map covers it")
    if full_why:
        return "full", full_why
    picked: dict[str, list[str]] = {}
    for name, s in tests.items():
        if s != suite:
            continue
        why = []
        if f"verify/{name}" in changed:
            why.append("the change edits it")
        if name in entry_changed:
            why.append("the change edits its entry in the map")
        if name in doc["always"]:
            why.append(f"always: {doc['always'][name]}")
        else:
            hits = [p for p in changed if any(covers(e, p) for e in doc["reads"].get(name, []))]
            if hits:
                why.append("reads " + ", ".join(hits[:5]) + (f" and {len(hits) - 5} more" if len(hits) > 5 else ""))
        if why:
            picked[name] = why
    return "scoped", picked


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "select" and argv[1] in ("offline", "tools"):
        base = os.environ.get("HECATON_BASE_SHA", "")
        if not base:
            print("scope_tests: select needs HECATON_BASE_SHA", file=sys.stderr)
            return 2
        doc, changed, tests = load_map(), changed_paths(base), discover()
        before = base_map(base) if MAP_REL in changed else None
        mode, why = select(doc, argv[1], changed, tests, before)
        err = sys.stderr
        print(f"scope: HECATON_BASE_SHA={base}; the change touches {len(changed)} paths", file=err)
        if mode == "full":
            print("scope: running every test, because of:", file=err)
            for p, ws in why.items():
                print(f"  {p}: {'; '.join(ws)}", file=err)
            print("FULL")
        else:
            n = sum(1 for s in tests.values() if s == argv[1])
            print(f"scope: running {len(why)} of {n} {argv[1]} tests, each because:", file=err)
            for t, ws in why.items():
                print(f"  {t}: {'; '.join(ws)}", file=err)
            print("SCOPED")
            for t in why:
                print(t)
        return 0
    if argv == ["check"]:
        bad = problems(load_map(), Tree())
        for b in bad:
            print(f"  {b}")
        print(f"{len(bad)} problems in {MAP.relative_to(REPO)}")
        return 1 if bad else 0
    if argv == ["write"]:
        tree = Tree()
        dump(write(load_map(), tree), MAP)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
