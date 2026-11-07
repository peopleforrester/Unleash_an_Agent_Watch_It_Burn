#!/usr/bin/env python3
# ABOUTME: Holds verify/scope-map.yaml against what each test opens when it runs (#1018): every test runs with an inotify
# ABOUTME: watch on each directory of the checkout, and a tracked file it opens that its entry does not cover is named.
"""What each test opens, against its entry in the map.

    python3 verify/scope_audit.py offline|tools [test ...]

scope_tests.py check holds the map to what each test's source names. This holds it to what the test does: each
offline test (or, with tools, each tier test, with the pinned tools fetched and the environment run-e2e-tools.sh gives
it) runs as its runner runs it, the no-cloud stubs first on PATH, while inotify reports every file opened under the
checkout, by the test and by every process it starts. A tracked file it opened that its entry does not cover is a read
the map misses; scope_tests.py's extractor needs to see it, or the entry needs it by hand. A test in always reads
everything already and is run only when named. A directory it listed counts only when no entry is inside it.

It takes as long as the suite, so no suite runs it: run it after a change to scope_tests.py's extractor, and when a
test seems to be left out. Exit 1 names each miss.
"""
from __future__ import annotations

import ctypes
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import threading
import time

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import scope_tests as st  # noqa: E402
import tf_plugin_cache  # noqa: E402

IN_OPEN = 0x00000020
IN_ISDIR = 0x40000000
IN_Q_OVERFLOW = 0x00004000
IN_CLOEXEC = 0o2000000


class Watch:
    """An inotify watch on every directory under the given ones; opened() hands over what was opened since last time."""

    def __init__(self, dirs: list[pathlib.Path]):
        self.libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self.fd = self.libc.inotify_init1(IN_CLOEXEC)
        if self.fd < 0:
            raise SystemExit(f"scope_audit: inotify_init1 failed: {os.strerror(ctypes.get_errno())}")
        self.paths: dict[int, str] = {}
        for d in dirs:
            wd = self.libc.inotify_add_watch(self.fd, str(d).encode(), IN_OPEN)
            if wd < 0:
                raise SystemExit(f"scope_audit: cannot watch {d}: {os.strerror(ctypes.get_errno())}")
            self.paths[wd] = os.path.relpath(d, REPO) if d != REPO else ""
        self.lock = threading.Lock()
        self.seen: list[tuple[str, bool]] = []
        self.overflow = False
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        while True:
            buf = os.read(self.fd, 1 << 20)
            i = 0
            with self.lock:
                while i < len(buf):
                    wd, mask, _cookie, n = struct.unpack_from("iIII", buf, i)
                    name = buf[i + 16:i + 16 + n].rstrip(b"\0").decode(errors="replace")
                    i += 16 + n
                    if mask & IN_Q_OVERFLOW:
                        self.overflow = True
                        continue
                    base = self.paths.get(wd)
                    if base is None:
                        continue
                    self.seen.append((os.path.join(base, name) if name else base, bool(mask & IN_ISDIR)))

    def opened(self) -> tuple[list[tuple[str, bool]], bool]:
        time.sleep(0.3)  # let the last events of the finished test arrive
        with self.lock:
            got, over = self.seen, self.overflow
            self.seen, self.overflow = [], False
        return got, over


def watched_dirs(tree: st.Tree) -> list[pathlib.Path]:
    dirs = {REPO} | {REPO / d for d in tree.dirs}
    for sub in tree.submodules:
        for d, subdirs, _ in os.walk(REPO / sub):
            subdirs[:] = [s for s in subdirs if s != ".git"]
            dirs.add(pathlib.Path(d))
    return sorted(d for d in dirs if d.is_dir())


def tier_env(base: dict[str, str], no_cloud_bin: str, helm: pathlib.Path) -> dict[str, str]:
    """The environment run-e2e-tools.sh gives a tier test."""
    tools = VERIFY / ".tools" / "bin"
    env = {k: v for k, v in base.items() if k not in (
        "CONTEXT", "IAM_PIPELINE_PROFILE", "IAM_PIPELINE_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")}
    for d in ("config", "cache", "data"):
        (helm / d).mkdir(parents=True, exist_ok=True)
    env.update({"KUBECONFIG": "/dev/null", "PATH": f"{no_cloud_bin}:{tools}:{base['PATH']}",
                "TF_PLUGIN_CACHE_DIR": str(tf_plugin_cache.ensure(base)),
                "KYVERNO_CLI": str(tools / "kyverno"), "CONFTEST": str(tools / "conftest"),
                "TERRAFORM": str(tools / "terraform"), "OTELCOL_CONTRIB": str(tools / "otelcol-contrib"),
                "TTYD": str(tools / "ttyd"), "CRANE": str(tools / "crane"),
                "AGENTGATEWAY": str(tools / "agentgateway"), "HELM_CONFIG_HOME": str(helm / "config"),
                "HELM_CACHE_HOME": str(helm / "cache"), "HELM_DATA_HOME": str(helm / "data")})
    return env


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("offline", "tools"):
        print(__doc__, file=sys.stderr)
        return 2
    suite, named = argv[0], argv[1:]
    doc, tree, tests = st.load_map(), st.Tree(), st.discover()
    names = named or [t for t, s in tests.items() if s == suite and t in doc["reads"]]
    unknown = [t for t in names if t not in tests]
    if unknown:
        print(f"scope_audit: not a test either runner runs: {', '.join(unknown)}", file=sys.stderr)
        return 2
    subprocess.run(["bash", str(VERIFY / "ensure-submodules.sh")], check=True)
    if suite == "tools":
        subprocess.run(["bash", str(VERIFY / "fetch-e2e-tools.sh")], check=True)
    watch = Watch(watched_dirs(tree))
    misses: dict[str, list[str]] = {}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="scope-audit-"))
    stubs = ["aws", "eksctl"] if suite == "tools" else []
    base_env = {k: v for k, v in os.environ.items() if k != "HECATON_BASE_SHA"}
    start = time.time()
    for n, name in enumerate(names, 1):
        rel = f"verify/{name}"
        interp = "python3" if name.endswith(".py") else "bash"
        env = tier_env(base_env, str(tmp / "nc" / "bin"), tmp / "helm") if suite == "tools" else base_env
        cmd = (f'. {VERIFY}/no-cloud.sh && no_cloud_setup "$1" {" ".join(stubs)} && shift && no_cloud_run "$@"')
        watch.opened()
        r = subprocess.run(["bash", "-c", cmd, "audit", str(tmp / "nc"), interp, str(VERIFY / name)],
                           capture_output=True, text=True, env=env)
        opened, overflow = watch.opened()
        entries = doc["reads"].get(name, [""] if name in doc["always"] else [])
        miss = set()
        for p, is_dir in opened:
            k = tree.known(p) if p else ""
            if k is None or k == rel or any(st.covers(e, k) for e in doc["full"]):
                continue  # a change to a path in full runs every test already
            if is_dir:
                # Python lists each sys.path directory to import, and git lists the tree for a status; a listing
                # counts only for a directory no entry reaches into.
                if k in ("", "verify") or any(st.covers(e, k) or e.startswith(k + "/") or not st.names(e)
                                               for e in entries):
                    continue
                miss.add(f"{k}/ (listed)")
            elif k not in tree.files and k not in tree.submodules:
                continue
            elif not any(st.covers(e, k) or st.covers(e, p) for e in entries):
                miss.add(k)  # a file inside a submodule counts as the submodule, or as itself to a glob
        if overflow:
            miss.add("(inotify's queue overflowed, so some opens were lost; run this test alone)")
        status = "ok" if not miss else f"{len(miss)} missed"
        print(f"[{n}/{len(names)} {int(time.time() - start)}s] {name}: exit {r.returncode}, {status}", flush=True)
        if miss:
            misses[name] = sorted(miss)
            for m in sorted(miss):
                print(f"    {m}", flush=True)
    print(f"\n{len(names)} tests audited, {len(misses)} with reads their entries miss")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
