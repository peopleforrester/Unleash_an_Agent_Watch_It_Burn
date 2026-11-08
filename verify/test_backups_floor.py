# ABOUTME: Offline test of #985: a KubeCon standby that takes attackme's hostname has Kyverno admission armed first,
# ABOUTME: and the new holder is linked to the other KubeCon cluster; the 2-hour workshop's watcher arms nothing.
"""What #985 asks, held without a cluster.

A promotion is driven through backups.py's own watcher, built by make_watcher as `backups.py watch` builds it, so
the arming and the link are the code the watcher runs. Only the edges are fakes: `aws` and `kubectl` are scripts on
PATH that play the EKS clusters, each one's two registry policies kept in a state file, so the test reads each
cluster's guardrail state after the promotion; fleet.sh is a stub that records the guardrails-link it is asked
for; the console self-check is a function of the LB; the router's reload script copies the table and records every
cluster's policy state at the moment the router takes it. Nothing reaches AWS, a cluster or the router.

The design (decisions.md, #985): the community standby that takes attackme has both registry policies at Deny
before the router moves the hostname; RBAC, KubeArmor and egress are left as its start state has them, for
guardrails-on; the private standby keeps its start state; after the router takes the table, the new holder is
linked with the other role's holder; the workshop profiles arm and link nothing.
"""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET_DIR = REPO / "infra/terraform/fleet"
sys.path.insert(0, str(FLEET_DIR))
import backups as b  # noqa: E402

import no_cloud  # noqa: E402
no_cloud.setup()

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


T = pathlib.Path(tempfile.mkdtemp(prefix=".backups-floor-test.", dir=REPO))
atexit.register(shutil.rmtree, T, True)
STATE = T / "eks"           # <cluster>.json: {"restrict-image-registries": "Audit", ...}; <cluster>.missing: no policies
STATE.mkdir()
CALLS = T / "calls.jsonl"   # every fake aws and kubectl call, with its argv and AWS_PROFILE
FAKE_BIN = T / "bin"
FAKE_BIN.mkdir()

# The fake EKS. aws writes a kubeconfig naming the cluster's ARN; kubectl reads the context from it, refuses a
# --context that is not it, and answers the console Service, a policy patch and a policy read. Anything else is
# recorded and fails, so a guardrail the design leaves off (a Role, a KubeArmorPolicy, a NetworkPolicy) would show.
FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ["FAKE_EKS_STATE"])
tool, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["FAKE_EKS_CALLS"], "a") as f:
    f.write(json.dumps({"tool": tool, "args": args, "profile": os.environ.get("AWS_PROFILE", "")}) + "\n")
def opt(flag):
    return args[args.index(flag) + 1] if flag in args else None
if tool == "aws":
    if args[:2] != ["eks", "update-kubeconfig"]:
        sys.exit(1)
    name, region = opt("--name"), opt("--region")
    if (state / f"{name}.unreachable").exists():
        sys.exit(1)
    pathlib.Path(opt("--kubeconfig")).write_text(f"arn:aws:eks:{region}:000000000000:cluster/{name}\n")
    sys.exit(0)
ctx = pathlib.Path(opt("--kubeconfig")).read_text().strip()
rest = [a for i, a in enumerate(args) if a not in ("--kubeconfig", "--context")
        and (i == 0 or args[i - 1] not in ("--kubeconfig", "--context"))]
if rest == ["config", "current-context"]:
    print(ctx); sys.exit(0)
if opt("--context") != ctx:
    sys.exit(1)
name = ctx.rsplit("/", 1)[-1]
f = state / f"{name}.json"
pol = json.loads(f.read_text()) if f.exists() else {}
if rest[:5] == ["-n", "agent", "get", "svc", "console"]:
    print(f"lb-{name}"); sys.exit(0)
if (state / f"{name}.missing").exists() and rest[1:2] == ["validatingpolicy"]:
    sys.exit(1)
if rest[:2] == ["patch", "validatingpolicy"]:
    patch = json.loads(rest[rest.index("-p") + 1])
    assert patch[0]["path"] == "/spec/validationActions"
    pol[rest[2]] = patch[0]["value"][0]
    f.write_text(json.dumps(pol)); sys.exit(0)
if rest[:2] == ["get", "validatingpolicy"]:
    print(pol.get(rest[2], "")); sys.exit(0)
sys.exit(1)
'''
for tool in ("aws", "kubectl"):
    (FAKE_BIN / tool).write_text(FAKE)
    os.chmod(FAKE_BIN / tool, 0o755)
# Ahead of no_cloud's stubs, so these answer and the stubs record nothing; the last check reads the stubs' log.
os.environ.update(PATH=f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}", FAKE_EKS_STATE=str(STATE),
                  FAKE_EKS_CALLS=str(CALLS))

# fleet.sh, as far as the watcher's link reaches it: a stub that records its argv and the token-try limit.
LINKS = T / "links.jsonl"
FLEET_STUB = T / "fleet.sh"
FLEET_STUB.write_text("#!/usr/bin/env bash\n"
                      f'[[ -f "{T}/link_fails" ]] && {{ echo "guardrails-link: NOT linked both ways" >&2; exit 1; }}\n'
                      f'[[ -f "{T}/desk_link_fails" && "$1" == desk-link ]] && '
                      f'{{ echo "desk-link: NOT linked; the private bot\'s deploys do not reach it" >&2; exit 1; }}\n'
                      f'python3 -c \'import json, os, sys; print(json.dumps({{"argv": sys.argv[1:], '
                      f'"tries": os.environ.get("WIB_LINK_TOKEN_TRIES", "")}}))\' "$@" >>"{LINKS}"\n')
os.chmod(FLEET_STUB, 0o755)

pools = b.load_pools(FLEET_DIR / "roster.tsv", FLEET_DIR / "backups.tsv", "us-west-2")
NAMES = [c.name for p in pools.values() for c in p]
HOSTS = {"community": "attackme.agenticburn.com", "admin": "burritobot-private.agenticburn.com"}
TABLE = ("attackme.agenticburn.com  lb-watch-it-burn-community:443\n"
         "attackme.burritobot.co  lb-watch-it-burn-community:443\n"
         "burritobot-private.agenticburn.com  lb-watch-it-burn-private:443\n")
apex = T / "apex"
(apex / "scripts").mkdir(parents=True)
SEEN = T / "seen-at-reload.jsonl"   # every cluster's policy state when the router took a table
(apex / "scripts/reload-routes.sh").write_text(
    "#!/usr/bin/env bash\n"
    f'cp "$1" "{T}/live.map"\n'
    f'python3 -c \'import json, pathlib; d = pathlib.Path("{STATE}"); '
    f'print(json.dumps({{p.stem: json.loads(p.read_text()) for p in d.glob("*.json")}}))\' >>"{SEEN}"\n')
os.chmod(apex / "scripts/reload-routes.sh", 0o755)
START = {p: "Audit" for p in b.FLOOR_POLICIES}   # the KubeCon start state: present and off (#774)
down: set[str] = set()


def fake_check(lb: str, host: str, chat: bool) -> tuple[bool, str]:
    return (lb not in down), ("healthy" if lb not in down else "/healthz answered 502")


def fresh(profiles: dict[str, str]) -> b.Watcher:
    """A watcher as `backups.py watch` builds it (make_watcher), for an event with these bootstrap profiles."""
    for f in list(STATE.iterdir()) + [CALLS, LINKS, SEEN, T / "promoted.tsv", T / "failover.jsonl", T / "link_fails"]:
        f.unlink(missing_ok=True)
    for n in NAMES:
        (STATE / f"{n}.json").write_text(json.dumps(START))
    (apex / "routes.map").write_text(TABLE)
    down.clear()
    x = types.SimpleNamespace(pools=pools, hosts=HOSTS, promoted=T / "promoted.tsv", logs=T, account="accen-dev",
                              profiles=profiles, router=lambda: b.Router(apex, retries=1, backoff=0))
    w = b.make_watcher(x, types.SimpleNamespace(fail_after=3, drill=""))
    w._check = fake_check   # the self-check is HTTPS to the console LB; #643's test holds it
    w.refresh()             # console_lb, through the fake aws and kubectl
    return w


def policies(name: str) -> dict:
    return json.loads((STATE / f"{name}.json").read_text())


def routed(host: str) -> str | None:
    return b.upstream_of((apex / "routes.map").read_text(), host)


def events() -> list[dict]:
    return [json.loads(l) for l in (T / "failover.jsonl").read_text().splitlines()]


def links() -> list[dict]:
    return [json.loads(l) for l in LINKS.read_text().splitlines()] if LINKS.exists() else []


def kubectl_calls() -> list[list[str]]:
    lines = CALLS.read_text().splitlines() if CALLS.exists() else []
    return [c["args"] for c in map(json.loads, lines) if c["tool"] == "kubectl"]


KUBECON = {"community": "kubecon-community", "admin": "kubecon-private"}
b.FLEET = FLEET_STUB
try:
    print("== KubeCon: attackme's cluster goes down, and the standby that takes it is armed first ==")
    w = fresh(KUBECON)
    check("make_watcher arms the community role alone", w.arm_roles == {"community"}, str(w.arm_roles))
    check("every console LB was read through the fake EKS", w.lbs.get("watch-it-burn-community-b01")
          == "lb-watch-it-burn-community-b01", str(w.lbs)[:300])
    CALLS.unlink(missing_ok=True)
    down.add("lb-watch-it-burn-community")
    for _ in range(3):
        w.tick()
    check("attackme goes to b01, the first standby", routed("attackme.agenticburn.com")
          == "lb-watch-it-burn-community-b01:443")
    check("b01's two registry policies are at Deny: the floor", policies("watch-it-burn-community-b01")
          == {p: "Deny" for p in b.FLOOR_POLICIES}, str(policies("watch-it-burn-community-b01")))
    seen = [json.loads(l) for l in SEEN.read_text().splitlines()]
    check("and were already at Deny when the router took the table, so the room never reached it open",
          len(seen) == 1 and seen[0]["watch-it-burn-community-b01"] == {p: "Deny" for p in b.FLOOR_POLICIES},
          str(seen)[:400])
    check("no other cluster's guardrails moved: the roster cluster, the other standbys and the private ones",
          all(policies(n) == START for n in NAMES if n != "watch-it-burn-community-b01"))
    kc = kubectl_calls()
    mutating = [a for a in kc if any(v in a for v in ("patch", "apply", "create", "delete", "replace", "edit"))]
    check("the only changes made are the two policy patches on b01; RBAC, KubeArmor and egress wait for "
          "guardrails-on", len(mutating) == 2 and all("watch-it-burn-community-b01" in a[a.index("--context") + 1]
                                                     and a[a.index("--context") + 2:][:2] == ["patch", "validatingpolicy"]
                                                     for a in mutating), json.dumps(mutating)[:500])
    check("every kubectl call names an isolated kubeconfig and an explicit --context",
          all("--kubeconfig" in a and ("--context" in a or a[-2:] == ["config", "current-context"]) for a in kc))
    check("every aws call carries the fleet profile", all(c["profile"] == "accen-dev" for c in map(
        json.loads, CALLS.read_text().splitlines()) if c["tool"] == "aws"))
    check("the new holder is linked with the private bot's cluster, community first: the guardrails switch, then the "
          "one support desk (#1159)",
          [l["argv"] for l in links()] == [["guardrails-link", "watch-it-burn-community-b01@us-east-2",
                                             "watch-it-burn-private@us-west-2"],
                                            ["desk-link", "watch-it-burn-community-b01@us-east-2",
                                             "watch-it-burn-private@us-west-2"]], str(links()))
    check("with three token reads at most, so the watcher is not held for fleet.sh's thirty",
          [l["tries"] for l in links()] == ["3", ""])
    ev = events()[-1]
    check("the event log records the floor and the link", ev["promoted"] == "watch-it-burn-community-b01"
          and ev["armed"] is True and ev["linked"] is True, str(ev))

    print("== the next promotion arms the next standby, and links it ==")
    down.add("lb-watch-it-burn-community-b01")
    for _ in range(3):
        w.tick()
    check("b02 takes attackme, armed", routed("attackme.agenticburn.com") == "lb-watch-it-burn-community-b02:443"
          and policies("watch-it-burn-community-b02") == {p: "Deny" for p in b.FLOOR_POLICIES})
    check("and the private bot's terminal now reaches b02", links()[-1]["argv"][1:]
          == ["watch-it-burn-community-b02@us-east-1", "watch-it-burn-private@us-west-2"], str(links()))

    print("== the private bot's standby keeps its start state, and is linked with attackme's holder ==")
    down.add("lb-watch-it-burn-private")
    for _ in range(3):
        w.tick()
    check("burritobot-private goes to private-b01", routed("burritobot-private.agenticburn.com")
          == "lb-watch-it-burn-private-b01:443")
    check("with its registry policies as it started, at Audit, for guardrails-on in Segment 3",
          policies("watch-it-burn-private-b01") == START, str(policies("watch-it-burn-private-b01")))
    check("linked with b02, which holds attackme now", links()[-1]["argv"][1:]
          == ["watch-it-burn-community-b02@us-east-1", "watch-it-burn-private-b01@us-east-2"], str(links()))
    ev = events()[-1]
    check("its event says it was not armed by design and was linked", ev["armed"] is None and ev["linked"] is True,
          str(ev))

    print("== a failing back by hand (backups.py promote) arms the roster cluster too ==")
    table = (apex / "routes.map").read_text()
    ok = w.promote("community", pools["community"][0], "lb-watch-it-burn-community-b02:443", table, why="by hand",
                   failed="watch-it-burn-community-b02")
    check("the roster cluster takes attackme back, armed", ok and routed("attackme.agenticburn.com")
          == "lb-watch-it-burn-community:443" and policies("watch-it-burn-community")
          == {p: "Deny" for p in b.FLOOR_POLICIES})

    print("== a standby that cannot be armed still takes the hostname, and says so ==")
    w = fresh(KUBECON)
    (STATE / "watch-it-burn-community-b01.missing").touch()
    down.add("lb-watch-it-burn-community")
    for _ in range(3):
        w.tick()
    check("b01 takes attackme: a dead cluster is an outage now, an unarmed one only the chance of one",
          routed("attackme.agenticburn.com") == "lb-watch-it-burn-community-b01:443")
    check("and the event log records it was not armed", events()[-1]["armed"] is False, str(events()[-1]))

    print("== a link that fails leaves the promotion standing ==")
    w = fresh(KUBECON)
    (T / "link_fails").touch()
    down.add("lb-watch-it-burn-community")
    for _ in range(3):
        w.tick()
    check("b01 holds attackme, armed", routed("attackme.agenticburn.com") == "lb-watch-it-burn-community-b01:443"
          and events()[-1]["armed"] is True)
    check("and the event log records the link failed", events()[-1]["linked"] is False, str(events()[-1]))
    (T / "link_fails").unlink()

    print("== a desk link that fails alone is a failed link too (#1159) ==")
    w = fresh(KUBECON)
    (T / "desk_link_fails").touch()
    n = len(links())
    down.add("lb-watch-it-burn-community")
    for _ in range(3):
        w.tick()
    check("b01 holds attackme, and the guardrails switch was still linked",
          routed("attackme.agenticburn.com") == "lb-watch-it-burn-community-b01:443"
          and [l["argv"][0] for l in links()[n:]] == ["guardrails-link"], str(links()[n:]))
    check("but the event log records the link failed, since the private bot's deploys miss the one page",
          events()[-1]["linked"] is False, str(events()[-1]))
    (T / "desk_link_fails").unlink()

    print("== the 2-hour workshop: the burn and admin profiles, nothing armed and nothing linked ==")
    w = fresh({"community": "burn", "admin": "admin"})
    check("make_watcher arms no role and links nothing", w.arm_roles == frozenset() and w.link is None)
    CALLS.unlink(missing_ok=True)
    down.update({"lb-watch-it-burn-community", "lb-watch-it-burn-private"})
    for _ in range(3):
        w.tick()
    check("both hostnames still move to the first standbys", routed("attackme.agenticburn.com")
          == "lb-watch-it-burn-community-b01:443" and routed("burritobot-private.agenticburn.com")
          == "lb-watch-it-burn-private-b01:443")
    check("no cluster was patched", not [a for a in kubectl_calls() if "patch" in a]
          and all(policies(n) == START for n in NAMES))
    check("no link was asked for", links() == [])
    check("the events say nothing was armed or linked", all(e["armed"] is None and e["linked"] is None
                                                         for e in events() if e.get("applied")))
finally:
    b.FLEET = FLEET_DIR / "fleet.sh"

print("== the event's profiles come from fleet.sh, as the roster's do ==")
x = b.Ctx()
check("this event (event.sh) is the KubeCon pair", x.profiles == KUBECON, str(x.profiles))
saved = os.environ.get("WIB_ROSTER_PROFILES")
os.environ["WIB_ROSTER_PROFILES"] = "workshop"
try:
    xw = b.Ctx()
finally:
    os.environ.pop("WIB_ROSTER_PROFILES")
    if saved is not None:
        os.environ["WIB_ROSTER_PROFILES"] = saved
check("WIB_ROSTER_PROFILES=workshop is the 2-hour workshop's burn and admin", xw.profiles
      == {"community": "burn", "admin": "admin"}, str(xw.profiles))
a = types.SimpleNamespace(fail_after=3, drill="")
check("so its watcher arms nothing and links nothing", b.make_watcher(xw, a).arm_roles == frozenset()
      and b.make_watcher(xw, a).link is None)
check("and the KubeCon watcher arms attackme's role and links", b.make_watcher(x, a).arm_roles == {"community"}
      and b.make_watcher(x, a).link is b.link_pair)

print("== a standby build does not link, so it cannot undo the watcher's link ==")
ups = b.region_steps(None, "us-east-2", [], "up")
check("backups.py up builds standbys with WIB_NO_LINK=1", ups[0][0].get("WIB_NO_LINK") == "1", str(ups[0][0]))
fleet_src = (FLEET_DIR / "fleet.sh").read_text()
ANCHOR = '&& "${WIB_ROSTER_PROFILES:-}" == "kubecon" ]]; then'
if fleet_src.count(ANCHOR) != 1:
    sys.exit(f"FAIL: {FLEET_DIR / 'fleet.sh'} carries {fleet_src.count(ANCHOR)} copies of {ANCHOR!r}, not one: "
             "the instructors up pair-link block this test reads has moved or been reworded")
block = fleet_src[fleet_src.index(ANCHOR):][:1000]
check("and fleet.sh's instructors up skips the pair link when WIB_NO_LINK is set, before it would link",
      block.index('-n "${WIB_NO_LINK:-}"') < block.index("cmd_guardrails_link"), block)
check("the link step is fleet.sh guardrails-link with each cluster's region",
      b.link_step(pools["community"][3], pools["admin"][0])[1][1:]
      == ["guardrails-link", f"{pools['community'][3].name}@us-west-2", "watch-it-burn-private@us-west-2"])
check("then fleet.sh desk-link on the same pair, so the new pair shares the one desk (#1159)",
      [c[1:] for _, c in b.link_steps(pools["community"][3], pools["admin"][0])]
      == [["guardrails-link", f"{pools['community'][3].name}@us-west-2", "watch-it-burn-private@us-west-2"],
          ["desk-link", f"{pools['community'][3].name}@us-west-2", "watch-it-burn-private@us-west-2"]])

print()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called the real aws, kubectl, eksctl, terraform or helm", not _calls)
if _calls:
    print("".join(f"        {line}\n" for line in _calls.splitlines()), end="")

if failures:
    print(f"FAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("ALL PASS")
