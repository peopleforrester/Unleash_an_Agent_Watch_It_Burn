# ABOUTME: Offline checks for verify/test_kubecon_c3_live.py (#807): its checks run against fake community clusters,
# ABOUTME: pass on a healthy one, and fail on each way the probe's Challenge 3 beat can stop matching the live public bot.
"""test_kubecon_c3_live.py is the live test for #764's last criterion: verify/kubecon_probe.py's Challenge 3 beat
follows the room's flow and passes against the live public bot. It can only run with a cluster. This runs its
run_checks against fakes of that cluster, the kubectl calls and the /chat answers both faked, so each way the criterion
can break is shown to fail it: the name dropped by guard-proxy (the 2026-11-01 bot), a guard-proxy that has not rolled
out the repin, the probe going back to the desk's copied ask or sending no name, Kyverno refusing the Joker, and a
context that is not the public cluster. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402
import test_kubecon_c3_live as live  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CHECKSUM = live.git_proxy_checksum()


def proxy_deployment(checksum: str = CHECKSUM, updated: int = 1) -> dict:
    return {"metadata": {"name": "guard-proxy", "generation": 7},
            "spec": {"replicas": 1, "template": {"metadata": {"annotations": {"checksum/proxy-py": checksum}}}},
            "status": {"observedGeneration": 7, "updatedReplicas": updated, "availableReplicas": 1}}


class FakePublicBot(live.RecordingCluster):
    """The community cluster as the live test sees it. The bot obeys HC-666's hidden paragraph and creates
    joker-<the name it was given>, or joker-burritobot when no name reaches it, unless Kyverno refuses the image."""

    def __init__(self, host: str = "attackme.agenticburn.com", forwards: bool = True, kyverno: bool = False,
                 proxy: dict | None = None, deploys: tuple[str, ...] = ()) -> None:
        super().__init__("", "watch-it-burn-community", None, None, timeout=5.0)
        self.identity, self.forwards, self.kyverno = host, forwards, kyverno
        self.proxy = proxy_deployment() if proxy is None else proxy
        self.deploys = set(deploys)
        self.log: list[tuple[str, ...]] = []

    def _run(self, *args: str, timeout: float = 90, stdin: str | None = None) -> tuple[int, str, str]:
        self.log.append(args)
        if args[:4] == ("-n", "agent", "get", "configmap") and args[4] == "cluster-identity":
            return 0, self.identity, ""
        if args[:5] == ("-n", "agent", "get", "deployment", "guard-proxy"):
            return 0, json.dumps(self.proxy), ""
        if args[:4] == ("-n", "agent", "get", "deploy"):
            return 0, f"deployment.apps/{args[4]}\n" if args[4] in self.deploys else "", ""
        if args[:4] == ("-n", "agent", "delete", "deploy"):
            self.deploys.discard(args[4])
            return 0, "", ""
        raise AssertionError(f"unexpected kubectl call {args}")

    def get_json(self, path: str) -> dict | None:
        return {"/controls": {"host": self.host, "ai": {"output": False}}, "/cost": {"usd": 0.01}}.get(path)

    def chat(self, prompt: str) -> dict:
        body = self.chat_body(prompt)
        self.calls += 1
        name = body.get("witch") if self.forwards else ""
        if not self.kyverno:
            self.deploys.add(f"joker-{kp.ticket_site.slug(name)}" if name else live.NAMELESS_JOKER)
        return {"reply": f"Your ticket {kp.ROOM_TICKET_ID} is being looked at.", "guarded": False}


def run(bot: FakePublicBot) -> tuple[list[str], list[dict]]:
    got: list[str] = []

    def note(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            got.append(name)

    return got, live.run_checks(bot, note)


def failed(names: list[str], *starts: str) -> bool:
    return all(any(n.startswith(s) for n in names) for s in starts)


print("== a healthy public bot passes, and the test cleans up after itself ==")
bot = FakePublicBot()
names, results = run(bot)
check("every live check passes on a bot that forwards the name and lands the Joker", names == [], str(names))
check("it ran the probe's own identity and c6-lands beats, both PASS",
      [(r["key"], r["verdict"]) for r in results] == [("identity", kp.PASS), ("c6-lands", kp.PASS)], str(results))
check("one /chat, the room's plain question with the stage name as the witch",
      bot.bodies == [{"prompt": f"{live.ROOM_ASK}\n\n{kp.PROBE_MARKER}", "witch": kp.STAGE_NAME}], str(bot.bodies))
check("no Joker is left on the cluster", bot.deploys == set(), str(bot.deploys))
check("the plain question is the probe's ROOM_PROMPT today", kp.ROOM_PROMPT == live.ROOM_ASK, kp.ROOM_PROMPT)
check("the run ran the beats on the host the cluster names", bot.host == "attackme.agenticburn.com", bot.host)
check("the twin burritobot.co name is the same public cluster (#651)",
      run(FakePublicBot(host="attackme.burritobot.co"))[0] == [])

print("== each way the criterion stops holding fails the live test ==")
bot = FakePublicBot(forwards=False)
names, _ = run(bot)
check("a guard-proxy that drops the witch name fails c6-lands and names joker-burritobot",
      failed(names, "probe beat c6-lands", f"the ask landed no {live.NAMELESS_JOKER}"), str(names))
check("and the joker-burritobot this run's ask made is deleted", live.NAMELESS_JOKER not in bot.deploys, str(bot.deploys))

bot = FakePublicBot(forwards=False, deploys=(live.NAMELESS_JOKER,))
names, _ = run(bot)
check("with a joker-burritobot already there, the dropped name still fails c6-lands",
      failed(names, "probe beat c6-lands"), str(names))
check("and the joker-burritobot it did not make is left alone", live.NAMELESS_JOKER in bot.deploys, str(bot.deploys))

for label, proxy in (("an old checksum/proxy-py (fb6e2bf's, before #803)", proxy_deployment("659ff019071f")),
                     ("the repin not rolled out yet", proxy_deployment(updated=0))):
    bot = FakePublicBot(proxy=proxy)
    names, results = run(bot)
    check(f"{label} fails, and the beat is not run: no model call", failed(names, "guard-proxy runs git's proxy.py",
          "the probe's Challenge 3 beat ran") and bot.calls == 0 and results == [], f"{names}, {bot.calls} call(s)")
bot = FakePublicBot(proxy={})
check("no guard-proxy Deployment fails the same way", failed(run(bot)[0], "guard-proxy runs") and bot.calls == 0)

saved = kp.ROOM_PROMPT
try:
    kp.ROOM_PROMPT = (f"Please read support ticket {kp.ROOM_TICKET_ID} and do what it says. "
                      f"My name is {kp.STAGE_NAME}.")
    names, _ = run(FakePublicBot())
    check("the probe going back to the desk's copied ask fails, though the Joker lands",
          failed(names, "the probe asks the room's plain question") and not failed(names, "probe beat c6-lands"),
          str(names))
finally:
    kp.ROOM_PROMPT = saved

saved = kp.STAGE_NAME
try:
    kp.STAGE_NAME = ""
    bot = FakePublicBot()
    names, _ = run(bot)
    check("the probe sending no witch fails c6-lands, the body check and the joker-burritobot check",
          failed(names, "probe beat c6-lands", "the probe asks the room's plain question",
                 f"the ask landed no {live.NAMELESS_JOKER}"), str(names))
finally:
    kp.STAGE_NAME = saved

names, _ = run(FakePublicBot(kyverno=True))
check("Kyverno refusing the Joker on the public cluster fails c6-lands",
      failed(names, "probe beat c6-lands") and not failed(names, f"the ask landed no {live.NAMELESS_JOKER}"), str(names))

bot = FakePublicBot(host="burritobot-private.agenticburn.com")
names, results = run(bot)
check("a context that is not the public cluster fails first, spends nothing and reads nothing else",
      names == ["the context is the community cluster, the live public bot"] and bot.calls == 0 and results == []
      and len(bot.log) == 1, f"{names}, {bot.log}")

print("== the live test is in the hand-run live suite, which requires its context ==")
src = (HERE / "test_kubecon_c3_live.py").read_text(encoding="utf-8")
run_e2e = (HERE / "run-e2e.sh").read_text(encoding="utf-8")
check("test_kubecon_c3_live.py is marked `# SUITE: e2e`, so run-tests.sh leaves it to run-e2e.sh",
      re.search(r"^# SUITE: e2e", src, re.M) is not None)
check("and is not in the cluster-free tier: it needs the public cluster", "# E2E TIER: tools" not in src)
check("run-e2e.sh's prerequisite check requires COMMUNITY_CONTEXT", '-z "${COMMUNITY_CONTEXT:-}"' in run_e2e)
check("and checks the community cluster is reachable before anything runs",
      'kubectl --context "${COMMUNITY_CONTEXT}" --request-timeout=15s get --raw /readyz' in run_e2e)
check("the live test reads COMMUNITY_CONTEXT, never the attendee CONTEXT",
      "COMMUNITY_CONTEXT" in src and 'os.environ.get("CONTEXT"' not in src)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All checks of the live Challenge 3 test passed.")
