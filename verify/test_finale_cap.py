# ABOUTME: Drives the terminal's finale commands (#690) against the real guard-proxy: finale-cap-on lowers the cluster
# ABOUTME: cap to spend plus headroom, the room is then refused, finale-cap-off restores COST_CAP_USD, cost-watch shows it.
"""The KubeCon close invites the room to drive the public cluster's spend to its cap. COST_CAP_USD is $25, so
finale-cap-on lowers the cap live through guard-proxy's /toggle?cost_cap=N (guard-proxy-agenticburn#23).

Here the pinned proxy.py serves on localhost with COST_CAP_USD=25, and the terminal's own heredocs
(gitops/ai-layer/web-terminal/entrypoint.sh) run against a kubectl on PATH that runs each `exec ... python3 -c`
snippet locally, pointed at that proxy. No cluster, no model: spend is recorded through proxy.record_usage, the
metering the real /chat path calls.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


os.environ["COST_CAP_USD"] = "25"
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
sys.path.insert(0, str(REPO / "gitops/ai-layer/guard-proxy"))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("guard_proxy_finale", REPO / "gitops/ai-layer/guard-proxy/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
proxy.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def cost() -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/cost", timeout=5) as r:
        return json.load(r)


def spend(input_tokens: int, output_tokens: int = 0) -> None:
    proxy.record_usage({"result": {"metadata": {"kagent_usage_metadata": {
        "promptTokenCount": input_tokens, "candidatesTokenCount": output_tokens,
        "totalTokenCount": input_tokens + output_tokens}}}})


# kubectl -n agent exec deploy/guard-proxy -- python3 -c <code> [args]: run the code here, against the test proxy.
FAKE_KUBECTL = f"""#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
rest = args[args.index("--") + 1:]
assert rest[:2] == ["python3", "-c"], rest
code = rest[2].replace("localhost:8080", "127.0.0.1:{PORT}")
sys.exit(subprocess.run([sys.executable, "-c", code, *rest[3:]]).returncode)
"""

docs = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT, re.S))
with tempfile.TemporaryDirectory() as tmp:
    home = pathlib.Path(tmp, "home"); home.mkdir()  # noqa: E702
    fakebin = pathlib.Path(tmp, "bin"); fakebin.mkdir()  # noqa: E702
    for name, body in docs.items():
        (home / name).write_text(body + "\n")
        (home / name).chmod(0o755)
    (fakebin / "kubectl").write_text(FAKE_KUBECTL)
    (fakebin / "kubectl").chmod(0o755)
    calls = pathlib.Path(tmp, "calls")
    env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "FAKE_CALLS": str(calls)}

    def run(*cmd: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(home / cmd[0]), *cmd[1:]], env=env, capture_output=True, text=True,
                              timeout=timeout)

    print("== the terminal has the finale commands ==")
    check("finale-cap-on, finale-cap-off and cost-watch are written and made executable",
          all(n in docs for n in ("finale-cap-on", "finale-cap-off", "cost-watch"))
          and all(f'"$HOME"/{n}' in ENTRYPOINT for n in ("finale-cap-on", "finale-cap-off", "cost-watch")))
    check("before the finale the cap is COST_CAP_USD ($25)", cost()["cap_usd"] == 25.0, str(cost()))

    print("== finale-cap-on: the cap moves to what the cluster spent plus the headroom ==")
    spend(200_000, 5_000)  # the room's earlier challenges
    before = cost()["usd"]
    r = run("finale-cap-on", "0.50")
    out = r.stdout + r.stderr
    check("it exits 0", r.returncode == 0, out)
    check("the cap is now the spend plus $0.50", abs(cost()["cap_usd"] - (before + 0.50)) < 1e-3, str(cost()))
    check("it tells the presenter the spend and the new cap", f"${before:.2f}" in r.stdout
          and f"${before + 0.50:.2f}" in r.stdout, r.stdout)
    check("it prints the command it ran", "$ kubectl -n agent exec deploy/guard-proxy -- python3 -c" in out
          and "cost_cap=" in out, out)
    check("the spend is kept, not reset", abs(cost()["usd"] - before) < 1e-9)
    check("under the new cap the room still gets answers", not proxy.cost_capped())
    spend(int(0.6 / proxy.COST_PER_1K_IN * 1000))  # the room spends past the headroom
    check("past it, guard-proxy refuses before the model for everyone", proxy.cost_capped())
    check("and a session with a budget of its own is refused too", proxy.cost_capped("phone-17"))

    print("== cost-watch shows spend against the cap ==")
    try:
        w = run("cost-watch", timeout=5)
        shown = w.stdout
    except subprocess.TimeoutExpired as e:
        shown = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    check("it shows SPENT, CAP and that the cap is hit", "SPENT" in shown and "CAP " in shown
          and "CAP HIT" in shown, shown[-400:])
    check("it shows the command it runs", "$ kubectl -n agent exec deploy/guard-proxy -- python3 -c" in shown)

    print("== finale-cap-off restores COST_CAP_USD ==")
    r = run("finale-cap-off")
    check("it exits 0", r.returncode == 0, r.stdout + r.stderr)
    check("the cap is $25 again", cost()["cap_usd"] == 25.0, str(cost()))
    check("and the room is answered again", not proxy.cost_capped())

    print("== a bad headroom changes nothing ==")
    n = len(calls.read_text().splitlines())
    r = run("finale-cap-on", "lots")
    check("a non-number is a usage error and runs nothing", r.returncode == 2
          and len(calls.read_text().splitlines()) == n, r.stdout)
    check("the cap is still $25", cost()["cap_usd"] == 25.0)

print("== the close tells the presenters the finale ==")
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
close = ros[ros.index("- **Break it (the last minutes, #690):**"):ros.index("- **The close (Michael):**")]
check("the run-of-show's close runs finale-cap-on, shows cost-watch and ends with finale-cap-off",
      all(f"`{c}" in close for c in ("finale-cap-on", "cost-watch", "finale-cap-off")))
check("it says what the room sees when the cap trips, and that Reset does not help (guard-proxy-agenticburn#25)",
      "CAP HIT" in close and "Reset does not help" in close and "guard-proxy-agenticburn#25" in close)
check("it carries the 2026-10-30 measurement, labeled, and the estimate as an estimate",
      "Measured 2026-10-30 on attackme" in close and "an estimate" in close)
check("it no longer says the cap is not built", "not built yet" not in close)
kc = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
kclose = kc[kc.index("<b>Break it (the last minutes, #690):</b>"):]
kclose = kclose[:kclose.index("</div>")]
check("/kubecon's close names the same three commands",
      all(f"<code>{c}</code>" in kclose for c in ("finale-cap-on", "cost-watch", "finale-cap-off"))
      and "not built yet" not in kclose)

srv.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The finale cap lowers, trips, shows and restores as the close needs.")
