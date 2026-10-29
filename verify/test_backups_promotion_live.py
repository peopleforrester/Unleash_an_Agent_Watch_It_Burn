# ABOUTME: The live rehearsal of #643: every standby passes its self-check, then a drill fails each roster cluster and
# ABOUTME: the watcher moves its hostname to a standby through the live router with nobody acting, and it is failed back.
# SUITE: e2e (needs both standby waves up, the fleet's AWS profile, kubectl, and an apex checkout that can reload the router)
#
# The offline half (test_backups.py) proves the watcher's choices against fakes. This proves them on the real
# platform: the console LBs read from EKS in three regions, the self-check against each console, a table the live
# router takes, and a public hostname that answers from the standby afterwards. It changes what the room's hostname
# points at for a few minutes, so it runs during a bring-up, never during a session.
#
# Usage: python3 verify/test_backups_promotion_live.py     (after `backups.py up night-before` and `up six-hours`)
import datetime as dt
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET_DIR = REPO / "infra/terraform/fleet"
sys.path.insert(0, str(FLEET_DIR))
import backups as b  # noqa: E402

BACKUPS = [sys.executable, str(FLEET_DIR / "backups.py")]
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


missing = [t for t in ("aws", "kubectl", "bash", "railway") if shutil.which(t) is None]
if missing:
    print(f"FAIL: not on PATH: {', '.join(missing)}", file=sys.stderr); sys.exit(1)
x = b.Ctx()
router = x.router()
if not router.table.exists() or not os.access(router.reload, os.X_OK):
    print(f"FAIL: no apex checkout with routes.map and scripts/reload-routes.sh at {router.table.parent}", file=sys.stderr)
    sys.exit(1)

print("== every cluster in both pools passes its self-check on its own console LB ==")
r = subprocess.run(BACKUPS + ["check"], capture_output=True, text=True, timeout=1800)
print(r.stdout)
check("all 17 consoles pass (two roster clusters, 15 standbys)", r.returncode == 0 and r.stdout.count("PASS") == 17,
      r.stderr[-500:])

for role, primary in (("community", "watch-it-burn-community"), ("admin", "watch-it-burn-private")):
    host = x.hosts[role]
    print(f"== drill: {primary} fails, and {host} moves with nobody acting ==")
    before = b.upstream_of(router.read(), host)
    until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    w = subprocess.Popen(BACKUPS + ["watch", "--drill", primary, "--interval", "5", "--fail-after", "3",
                                    "--until", until], stderr=subprocess.PIPE, text=True)
    after, deadline = before, time.monotonic() + 360
    while after == before and time.monotonic() < deadline and w.poll() is None:
        time.sleep(5)
        after = b.upstream_of(router.read(), host)
    w.terminate(); err = w.communicate(timeout=30)[1]
    check(f"the watcher repointed {host}", after not in (None, before), err[-800:])
    check("and logged the promotion", "PROMOTED" in err, err[-800:])
    try:
        with urllib.request.urlopen(f"https://{host}/healthz", timeout=20) as resp:
            code = resp.status
    except Exception as e:  # noqa: BLE001 - any failure here is the finding
        code = str(e)
    check(f"https://{host}/healthz answers 200 through the live router afterwards", code == 200, str(code))
    held = b.read_promoted(x.promoted).get(role)
    check("promoted.tsv names the standby that holds it", bool(held) and held != primary, str(held))
    r = subprocess.run(BACKUPS + ["promote", role, primary], capture_output=True, text=True, timeout=600)
    check(f"failing back to {primary} by hand works", r.returncode == 0
          and b.upstream_of(router.read(), host) == before, r.stderr[-500:])
    check("and clears promoted.tsv for the role", role not in b.read_promoted(x.promoted))

print()
if failures:
    print(f"FAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("ALL PASS")
