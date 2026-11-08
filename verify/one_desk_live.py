# ABOUTME: #1158's live check of the one desk, run by hand on the two KubeCon clusters: a ticket filed on the public desk
# ABOUTME: is read by number by both bots, each bot deploys one ConfigMap that shows on the one page, then all of it goes.
"""The one desk's live check (#1158, #1215), written down from run 18737's by-hand check. No model call.

    . "$HECATON_CLUSTER_ENV"
    python3 verify/one_desk_live.py --community-context watch-it-burn-community \\
        --private-context watch-it-burn-private --kubeconfig "$KUBECONFIG" --profile accen-dev

What it checks, in this order:

  filed     A plain ticket is filed through the public desk's own form, POST https://support.burritobot.co/submit,
            and the desk answers with its number.
  read      read_support_ticket(<number>) is called in each cluster's workshop-mcp tool pod (the probe's C6 tool
            check's method), and each prints the ticket's one unusual word: the private bot reads the public desk
            through desk-relay, the public bot its own cluster's desk.
  deploy    deploy_app is called in each tool pod with one harmless ConfigMap, desk-check-<stamp>-<cluster>, and
            answers that it is deployed.
  page      https://deployments.burritobot.co/deployments.json lists both, labelled community and private.

Then, on every path out of the checks above, a failure or a raise included (#1215): both ConfigMaps are deleted, and
the two rows and the filed ticket are removed from the one desk with its loopback-only POST /desk-forget, run in the
desk's pod on the community cluster. Nothing else on the desk is touched: no other row, no other ticket, no restart.
Then it reads that nothing is left:
  gone      neither ConfigMap is on either cluster, and the one page lists no row of either name.
On 2026-11-08 run 18737's check left its two rows on the page, which no route could remove, and the room would have
seen them (#1215). It exits 1 when any check fails, the cleanup's included. It reads and writes no Secret, and never
agent/terminal-auth.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402

log = logging.getLogger("one-desk-live")

PASS, FAIL = "PASS", "FAIL"
PUBLIC_DESK = kp.PUBLIC_DESK
DEPLOYMENTS = "https://deployments.burritobot.co/deployments.json"
# A name from the vocabulary the chat page hands out, as run 18737 used, so the row reads as a witch's.
WITCH = "Agatha the Gargoyle"
FILED = re.compile(r"Your ticket is (HC-\d{4})\b")
SIDES = ("community", "private")
_TOOL = "import sys; sys.path.insert(0, '/app'); import server; "
READ_TOOL = ["-n", "agent", "exec", "deploy/workshop-mcp", "-c", "shim", "--", "python3", "-c",
             _TOOL + "print(server.read_support_ticket(sys.argv[1]))"]
DEPLOY_TOOL = ["-n", "agent", "exec", "deploy/workshop-mcp", "-c", "shim", "--", "python3", "-c",
               _TOOL + "print(server.deploy_app(sys.argv[1], requested_by=sys.argv[2]))"]


def check_name(stamp: str, side: str) -> str:
    return f"desk-check-{stamp}-{side}"


def config_map(name: str, stamp: str) -> str:
    return json.dumps({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name},
                       "data": {"check": f"one desk live check {stamp} (#1158, #1215)"}})


def plain_ticket(word: str, stamp: str) -> str:
    return (f"Desk check {stamp} (#1158): my burrito order page shows the wrong pickup time, and the note on it says "
            f"{word}. Both cantina bots should read this ticket by its number.")


def judge_rows(rows, names: dict[str, str]) -> tuple[bool, str]:
    """The one page lists each side's ConfigMap, labelled with the cluster whose bot deployed it."""
    if not isinstance(rows, list):
        return False, f"{DEPLOYMENTS} did not answer a list: {str(rows)[:200]}"
    got = {r.get("name"): r.get("cluster") for r in rows if isinstance(r, dict)}
    wrong = {side: got.get(name) for side, name in names.items() if got.get(name) != side}
    if wrong:
        return False, f"the one page does not list each check row under its cluster: {wrong} (rows: {got})"
    return True, "the one page lists " + ", ".join(f"{n} ({s})" for s, n in names.items())


class DeskCheck:
    """One run of the check. `clusters` maps each side to its KubeconCluster; the desk is the community one."""

    def __init__(self, clusters: dict[str, kp.KubeconCluster], stamp: str, http: Callable = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.clusters, self.stamp, self.http, self.sleep = clusters, stamp, http, sleep
        self.names = {side: check_name(stamp, side) for side in SIDES}
        self.word = f"word-{secrets.token_hex(4)}"
        self.tid: str | None = None
        self.results: list[dict] = []

    def record(self, step: str, ok: bool, note: str) -> bool:
        self.results.append({"step": step, "verdict": PASS if ok else FAIL, "note": note})
        log.info("%-4s  %-8s %s", PASS if ok else FAIL, step, note)
        return ok

    def page(self):
        with self.http(urllib.request.Request(DEPLOYMENTS, headers={"Cache-Control": "no-cache"}), timeout=20) as r:
            return json.load(r)

    def file(self) -> bool:
        data = urllib.parse.urlencode({"body": plain_ticket(self.word, self.stamp)}).encode()
        with self.http(urllib.request.Request(f"{PUBLIC_DESK}/submit", data=data, method="POST"), timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
        m = FILED.search(page)
        self.tid = m.group(1) if m else None
        return self.record("filed", bool(self.tid), f"the public desk filed {self.tid}" if self.tid else
                           f"the desk's answer names no ticket: {page[:200]}")

    def read(self, side: str) -> bool:
        rc, out = self.clusters[side].kubectl_rc(*READ_TOOL, self.tid, timeout=60)
        ok = rc == 0 and self.word in out and self.tid in out
        return self.record("read", ok, f"{side}: read_support_ticket({self.tid}) " +
                           ("printed the ticket" if ok else f"did not print its word {self.word}: {out.strip()[:200]}"))

    def deploy(self, side: str) -> bool:
        name = self.names[side]
        rc, out = self.clusters[side].kubectl_rc(*DEPLOY_TOOL, config_map(name, self.stamp), WITCH, timeout=60)
        ok = rc == 0 and f"deployed ConfigMap/{name}" in out
        return self.record("deploy", ok, f"{side}: " + (f"deploy_app deployed ConfigMap/{name}" if ok else
                                                        f"deploy_app of {name} answered: {out.strip()[:200]}"))

    def checks(self) -> None:
        if not self.file():
            return
        for side in SIDES:
            self.read(side)
        for side in SIDES:
            self.deploy(side)
        self.sleep(kp.DESK_REPORT_SETTLE_S)   # deploy_app reports from a thread; the private one through the relay
        self.record("page", *judge_rows(self.page(), self.names))

    def cleanup(self, since: float) -> None:
        """Every path ends here (#1215): both ConfigMaps deleted, the rows and the ticket forgotten on the one desk,
        then read back. Each step runs whatever the one before it did."""
        for side in SIDES:
            try:
                rc, out = self.clusters[side].kubectl_rc("-n", "agent", "delete", "configmap", self.names[side],
                                                         "--ignore-not-found", "--wait=true")
            except Exception as e:  # noqa: BLE001 - a delete that cannot run is a failed cleanup, not a stop
                rc, out = 1, str(e)
            self.record("cleanup", rc == 0, f"{side}: ConfigMap/{self.names[side]} " +
                        ("deleted (or never made)" if rc == 0 else f"NOT deleted: {out.strip()[:200]}"))
        why = self.clusters["community"].forget_on_desk(list(self.names.values()), since,
                                                        [self.tid] if self.tid else [], sleep=self.sleep)
        self.record("cleanup", why is None, why or ("the one desk no longer holds the check's rows" +
                                                    (f" or ticket {self.tid}" if self.tid else "")))
        for side in SIDES:
            try:
                rc, out = self.clusters[side].kubectl_rc("-n", "agent", "get", "configmap", self.names[side],
                                                         "--ignore-not-found", "-o", "name")
            except Exception as e:  # noqa: BLE001
                rc, out = 1, str(e)
            self.record("gone", rc == 0 and not out.strip(), f"{side}: ConfigMap/{self.names[side]} " +
                        ("is not on the cluster" if rc == 0 and not out.strip() else f"may be left: {out.strip()[:200]}"))
        try:
            left = [r.get("name") for r in self.page() if isinstance(r, dict) and r.get("name") in self.names.values()]
            self.record("gone", not left, "the one page lists no check row" if not left else
                        f"the one page still lists {left}")
        except Exception as e:  # noqa: BLE001
            self.record("gone", False, f"the one page could not be read after the cleanup: {e}")

    def run(self) -> list[dict]:
        since = time.time()
        try:
            self.checks()
        except Exception as e:  # noqa: BLE001 - a step that cannot run is a failed step; the cleanup still runs
            self.record("error", False, f"could not run: {e}")
        finally:
            self.cleanup(since)
        return self.results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--community-context", required=True, help="kube-context of the community cluster (the one desk)")
    ap.add_argument("--private-context", required=True, help="kube-context of the private (admin) cluster")
    ap.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
    ap.add_argument("--profile", help="AWS_PROFILE for kubectl, passed per command")
    ap.add_argument("--stamp", help="the check's name suffix (default: the UTC time, HHMMSS)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.community_context == args.private_context:
        log.error("--community-context and --private-context name the same cluster")
        return 2
    stamp = args.stamp or time.strftime("%H%M%S", time.gmtime())
    if not re.fullmatch(r"[a-z0-9-]{1,30}", stamp):
        log.error("--stamp must be 1 to 30 lowercase letters, digits or dashes")
        return 2
    clusters = {"community": kp.KubeconCluster(kp.COMMUNITY_HOSTS[0], args.community_context, args.profile,
                                               args.kubeconfig, 60),
                "private": kp.KubeconCluster("burritobot-private.burritobot.co", args.private_context, args.profile,
                                             args.kubeconfig, 60)}
    results = DeskCheck(clusters, stamp).run()
    fails = [r for r in results if r["verdict"] == FAIL]
    print()
    for r in results:
        print(f"  {r['verdict']}  {r['step']:<8} {r['note']}")
    print(f"\n{len(results)} checks: {len(results) - len(fails)} PASS, {len(fails)} FAIL")
    print("ONE DESK LIVE GREEN" if not fails else "ONE DESK LIVE RED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
