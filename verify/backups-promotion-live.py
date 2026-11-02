# ABOUTME: The live rehearsal of #643: every standby passes its self-check, then a drill fails each roster cluster and
# ABOUTME: the watcher moves its hostname to a standby through the live router with nobody acting, and it is failed back.
# Needs both standby waves up, the fleet's AWS profile, kubectl, and an apex checkout that can reload the router.
#
# The offline half (test_backups.py) proves the watcher's choices against fakes. This proves them on the real
# platform: the console LBs read from EKS in three regions, the self-check against each console, a table the live
# router takes, and a public hostname that answers from the standby afterwards. It changes what the room's hostname
# points at for a few minutes, so it runs during a bring-up, never during a session.
#
# Not a test_*.py on purpose (#441): run-e2e.sh runs every `# SUITE: e2e` test against the one cluster CONTEXT names,
# and this needs the 15 standbys of both waves, which are clusters only `backups.py up` creates. In the suite it would
# be red on every run made without them, and it moves attackme and burritobot-private, which a suite run must not do.
# It is run by hand in the rehearsal of the run of show, like local-inference-live.py.
#
# Usage: python3 verify/backups-promotion-live.py     (after `backups.py up night-before` and `up six-hours`)
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

print("== across zones: in each region the standbys' nodes sit in the two zones backups.tsv names ==")


def node_zone(c: b.Cluster) -> str:
    """The availability zone of the cluster's node, read with an isolated kubeconfig and an explicit context."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        kcfg = os.path.join(d, "kubeconfig"); env = {**os.environ, "AWS_PROFILE": x.account}
        subprocess.run(["aws", "eks", "update-kubeconfig", "--kubeconfig", kcfg, "--name", c.name, "--region", c.region],
                       capture_output=True, text=True, timeout=60, env=env)
        ctx = subprocess.run(["kubectl", "--kubeconfig", kcfg, "config", "current-context"],
                             capture_output=True, text=True, timeout=15, env=env).stdout.strip()
        if not ctx.endswith(f"/{c.name}"):
            return ""
        return subprocess.run(["kubectl", "--kubeconfig", kcfg, "--context", ctx, "get", "nodes", "-o",
                               "jsonpath={.items[*].metadata.labels.topology\\.kubernetes\\.io/zone}"],
                              capture_output=True, text=True, timeout=30, env=env).stdout.strip()


for region in sorted({c.region for c in x.standbys()}):
    by_zone: dict[str, set[str]] = {}
    for c in (c for c in x.standbys() if c.region == region):
        by_zone.setdefault(c.zone, set()).add(node_zone(c))
    check(f"{region}: every standby of one zone letter is in one AZ, and a and b are different AZs",
          all(len(v) == 1 and "" not in v for v in by_zone.values())
          and len(set().union(*by_zone.values())) == len(by_zone), str(by_zone))

print("== no scheduled watcher may be running: the drill has to be the watcher ==")
lock = x.logs / ".backups-watch.lock"
free = True
if lock.exists():
    import fcntl
    with lock.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            free = False
check("the watcher lock is free (run before `backups.py schedule` is installed, or `backups.py unschedule` and stop it)",
      free)

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
    # The table on disk changes before the router has applied it, and promote() logs PROMOTED and writes
    # promoted.tsv only after the apply. Stopping the watcher on the table alone cut it off mid-apply on the
    # 2026-10-31 rehearsal, so it is stopped once promoted.tsv names the standby (or the apply is given up on).
    recorded = time.monotonic() + 180
    while after != before and time.monotonic() < recorded and w.poll() is None \
            and not b.read_promoted(x.promoted).get(role):
        time.sleep(3)
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
