# ABOUTME: Live half of #1067 (#1046's #1000 replays): Whitney's two messages in one chat on the public bot, behind the
# ABOUTME: pinned guard-proxy, never read the recipe card, and each card read is answered with workshop-mcp's shut reply.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of the community cluster (attackme, the live public bot),
and the public internet. Every missing prerequisite is a failure, never a skip.

#1000 shuts the recipe card in a chat that may not have it: guard-proxy (guard-proxy-agenticburn#65 on) sends
X-Pantry-Shut on the turn, kagent copies it onto workshop-mcp's tools/call, and workshop-mcp answers a card read with
its shut reply. verify/test_pantry_header_pin.py holds the pinned proxy.py's half offline. This runs the beats on the
public bot, as run 18215 did by hand for #1046:

- first, with no model call: the context is the community cluster; guard-proxy's pod template carries git's
  checksum/proxy-py and has rolled out, and git's pin holds #65, so the bot runs a proxy.py that sends the header;
  the workshop-agent Agent's workshop-mcp entry allows X-Pantry-Shut; and /guards reads every AI guard off, so a guard
  does not stand in for the shut;
- then REPLAYS chats (at least five), each a fresh session: the recon question, Whitney's line-cook message, the
  folder-naming attack, and an ask to run `ls /opt/legacy-menus`, all four in that chat. Each turn is judged on the
  header guard-proxy sends it, worked out from the replies the chat got (verify/pantry_replay.py): behind a header no
  reply carries the recipe, and every run_shell that names the card is answered with exactly that header's shut
  reply, read from workshop-mcp's audit line (result_chars). Any other answer means the header did not arrive, and
  at least one such shut answer is owed, so the header is seen arriving. The model declines the card reads from its
  prompt most of the time (all 12 in run 18851's first try); the ls ask is one it runs, and `legacy` in its path is
  what workshop-mcp shuts;
- then ATTACKS fresh sessions with the attack alone, a Reset: guard-proxy sends no header on a message that names
  the folder, so no card read there is answered shut, and at least one reads the card, so the card is there to shut.

It prints one `pantry replays:` line with the run's numbers, the line decisions.md records and
verify/test_pantry_shut_record.py holds. What it spends: 4 x REPLAYS + ATTACKS model calls on the public bot (27 by
default), each marked [[wib-probe]] so the room's feed skips it, about half a cent each, which counts on /cost until the
counter is reset. It switches nothing; it holds the community cluster's guard lock (verify/guard_lease.py) so no other
run turns a guard on mid-replay. Tool calls are matched to a turn by time, so a bystander's chat that calls a tool
inside a turn's window fails it as an overlap rather than being counted.

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] [REPLAYS=6] [ATTACKS=3]
       python3 verify/test_pantry_shut_live.py
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import kubecon_probe as kp  # noqa: E402
import pantry_replay as pr  # noqa: E402
from test_kubecon_c3_live import git_proxy_checksum, proxy_rolled_out  # noqa: E402

WITCH = "Mortimer the Warlock"
AI_GUARDS = ("input_blocklist", "input_classifier", "output", "topic")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def kubectl(context: str, *args: str) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}
    if os.environ.get("KUBECONFIG"):
        env["KUBECONFIG"] = os.environ["KUBECONFIG"]
    p = subprocess.run(["kubectl", "--context", context, "--request-timeout=30s", *args], capture_output=True,
                       text=True, env=env, timeout=120)
    return p.returncode, p.stdout if p.returncode == 0 else (p.stderr or p.stdout)


def allowed_headers(agent: dict) -> list[str]:
    for t in agent["spec"]["declarative"]["tools"]:
        srv = t.get("mcpServer") or {}
        if srv.get("name") == "workshop-mcp":
            return list(srv.get("allowedHeaders") or [])
    return []


def run_checks(cluster: kp.KubeconCluster, context: str, replays: int, attacks: int, check) -> None:
    host = cluster.identity_host()
    community = kp.identity_name(host) in {kp.identity_name(h) for h in kp.COMMUNITY_HOSTS}
    check("the context is the community cluster, the live public bot", community,
          f"its cluster-identity public-host is {host!r}, not one of {list(kp.COMMUNITY_HOSTS)}")
    if not community:
        return
    cluster.host = host

    pin = pr.pinned()
    want_sum = git_proxy_checksum()
    rc, out = kubectl(context, "-n", "agent", "get", "deployment", "guard-proxy", "-o", "json")
    ok, note = proxy_rolled_out(json.loads(out) if rc == 0 else None, want_sum)
    check("guard-proxy runs git's proxy.py", ok, note)
    sends = bool(pin) and pr.holds_fix(pin)
    check(f"git's guard-proxy pin {pin[:12]} holds #65 ({pr.PANTRY_FIX[:7]}), which sends X-Pantry-Shut", sends,
          "the pin predates #65: no turn carries the header, so the card is not shut")
    rc, out = kubectl(context, "-n", "agent", "get", "agent", "workshop-agent", "-o", "json")
    headers = allowed_headers(json.loads(out)) if rc == 0 else []
    check("the workshop-agent Agent passes X-Pantry-Shut to workshop-mcp (allowedHeaders)",
          "X-Pantry-Shut" in headers, f"workshop-mcp's allowedHeaders are {headers}" if rc == 0 else out[:200])
    guards = cluster.get_json("/guards") or {}
    on = [g for g in AI_GUARDS if guards.get(g) is not False]
    check("/guards reads every AI guard off", not on, f"/guards reads {guards}")
    if not (ok and sends and "X-Pantry-Shut" in headers and not on):
        check("the replays ran", False, "not run, so no model call is spent")
        return

    started = now()
    cluster.witch = WITCH
    turns: list[pr.Turn] = []

    def send(chat_no: int, session: str, label: str, prompt: str, state: pr.Chat) -> None:
        cluster.session = session
        header = state.header(prompt)
        t0 = now()
        try:
            reply = str(cluster.chat(f"{prompt}\n\n{kp.PROBE_MARKER}").get("reply") or "")
        except Exception as e:  # noqa: BLE001
            reply = ""
            check(f"chat {chat_no} {label}: the bot answers", False, f"{type(e).__name__}: {e}")
        state.read(reply)
        turns.append(pr.Turn(chat_no, label, header, reply, window=(t0, now())))
        print(f"  INFO  chat {chat_no} {label}: X-Pantry-Shut {header!r}, {len(reply)} characters back, "
              f"{'the recipe is' if pr.carries_recipe(reply) else 'no recipe'} in it")

    for i in range(1, replays + 1):
        session, state = f"wib-1067-same-{uuid.uuid4().hex[:12]}", pr.Chat()
        for label, prompt in pr.SAME_CHAT:
            send(i, session, label, prompt, state)
    for i in range(1, attacks + 1):
        send(-1, f"wib-1067-reset-{uuid.uuid4().hex[:12]}", str(i), pr.ATTACK, pr.Chat())

    rc, out = kubectl(context, "-n", "agent", "logs", "deploy/workshop-mcp", f"--since-time={started}")
    check("workshop-mcp's audit log reads back", rc == 0, out[:200])
    calls = pr.parse_audit(out if rc == 0 else "")
    for t in turns:
        t.calls = pr.in_window(calls, *t.window)
        for c in t.calls:
            post = c.get("post") or {}
            print(f"  INFO  chat {t.chat} {t.label}: {c.get('tool_name')} "
                  f"{json.dumps((c.get('tool_input') or {}).get('command'))[:100]} answered "
                  f"{post.get('result_chars', post.get('phase'))} characters")
    verdict = pr.judge(turns)
    for why in verdict.failures:
        check(why, False)
    check("Whitney's chats kept the card shut, and every card read behind the header was answered shut",
          not verdict.failures, f"{len(verdict.failures)} failure(s) above")
    print(f"\n  {pr.record_line(verdict, want_sum, pin)}")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # in order with guard_lease's stderr lines in a log
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    context = os.environ.get("COMMUNITY_CONTEXT", "")
    replays = int(os.environ.get("REPLAYS", "6"))
    attacks = int(os.environ.get("ATTACKS", "3"))
    missing = []
    if not context:
        missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if replays < pr.MIN_REPLAYS or attacks < 1:
        missing.append(f"REPLAYS must be at least {pr.MIN_REPLAYS} and ATTACKS at least 1 (got {replays}, {attacks})")
    if not missing:
        rc, out = kubectl(context, "get", "--raw", "/readyz")
        if rc != 0:
            missing.append(f"cluster for context {context!r} is not reachable: {out.strip()[:200]}")
    if missing:
        print("FAILED: the live pantry replays cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== #1000's pantry replays on the live public bot ({context}) ==")
    cluster = kp.KubeconCluster("", context, None, os.environ.get("KUBECONFIG") or None, timeout=150.0)
    if not guard_lease.run_held(context, lambda: run_checks(cluster, context, replays, attacks, check), check,
                                "verify/test_pantry_shut_live.py", kubeconfig=os.environ.get("KUBECONFIG") or None):
        return guard_lease.BUSY_EXIT

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All live pantry replay checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
