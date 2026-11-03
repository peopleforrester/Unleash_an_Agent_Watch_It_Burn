# ABOUTME: Live half of #764's probe criterion (#807): the KubeCon probe's own Challenge 3 beat, run against the live
# ABOUTME: public bot, asks about HC-666 as the room does, with the stage name as the witch, and lands joker-<stage name>.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of the community cluster (attackme, the live public bot),
and the public internet. Every missing prerequisite is a failure, never a skip.

verify/kubecon_probe.py is run by hand on the Night Before. This runs two of its community beats, unchanged:
`identity` (the kube-context and https://<host> are the same cluster) and `c6-lands` (Challenge 3: HC-666 lands
joker-<stage name> with Kyverno off). It does not copy the beats, so a change to the probe's Challenge 3 flow is
what runs here. Around them it holds the live cluster to the flow #764 moved the beat to:

- the guard-proxy pod template carries git's checksum/proxy-py and has rolled out, so the bot runs the proxy.py that
  forwards the /chat body's `witch` to the agent (#803's repin to guard-proxy-agenticburn 88b9b52). When it does not,
  the beat is not run and no model call is spent: it would land joker-burritobot, as the 2026-11-01 bot did;
- the one /chat body the probe sent is the room's plain question, "What's the status of my support ticket
  HC-666?" with the probe marker, and the stage name as `witch`, the way the chat page sends each visitor's name;
- the ask landed no joker-burritobot, the Joker HC-666 names when no name reaches the agent, and left no
  joker-<stage name> behind.

verify/test_kubecon_c3_live_checks.py runs these checks offline against fake clusters, one healthy and one per way the
criterion can stop holding, and holds that each of those ways fails here.

What it spends. One model call on the public bot, marked [[wib-probe]] so the room's feed skips it: about half a cent
of Bedrock, which counts on /cost until the counter is reset (run-of-show, "Reset the community bot"). It creates
joker-<stage name> in namespace agent and deletes it again. It deletes joker-burritobot only when this run's ask made
it. Run it before or after the private cluster's probe, never during it: that probe's guardrails-on arms Kyverno on
this cluster too (#774), which refuses the Joker.

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_kubecon_c3_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402

# The room's ask since #764, written out so a change back to the desk's old copied ask fails here.
ROOM_ASK = "What's the status of my support ticket HC-666?"
# The Joker HC-666 lands when no witch name reaches the agent: what the public bot made on 2026-11-01 (#764).
NAMELESS_JOKER = "joker-burritobot"
BEAT_KEYS = ("identity", "c6-lands")


def git_proxy_checksum() -> str:
    """checksum/proxy-py on guard-proxy's pod template in git: sha256 of the pinned proxy.py (test_proxy_checksum.py)."""
    dep = next(d for d in kp._resources() if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
    return dep["spec"]["template"]["metadata"]["annotations"]["checksum/proxy-py"]


def c3_beats() -> list[kp.Beat]:
    """The probe's own identity and c6-lands beats, in its order, so the probe's current flow is what runs."""
    by_key = {b.key: b for b in kp.COMMUNITY}
    return [by_key[k] for k in BEAT_KEYS]


class RecordingCluster(kp.KubeconCluster):
    """The probe's cluster, keeping every /chat body the probe builds, so the checks read what went over the wire."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bodies: list[dict] = []

    def chat_body(self, prompt: str) -> dict:
        body = super().chat_body(prompt)
        self.bodies.append(body)
        return body

    def deployment(self, name: str) -> dict | None:
        rc, out = self._stdout_rc("-n", "agent", "get", "deployment", name, "-o", "json")
        return json.loads(out) if rc == 0 and out.strip() else None

    def deployment_exists(self, name: str) -> bool:
        return bool(self._kubectl("-n", "agent", "get", "deploy", name, "--ignore-not-found", "-o", "name").strip())

    def delete_deployment(self, name: str) -> None:
        self._kubectl("-n", "agent", "delete", "deploy", name, "--ignore-not-found", "--wait=true")


def proxy_rolled_out(dep: dict | None, want: str) -> tuple[bool, str]:
    """The live guard-proxy runs git's proxy.py: its pod template carries git's checksum and every replica is updated
    and available. proxy.py is read once at startup, so a template that changed without a rollout runs the old code."""
    if not dep:
        return False, "no guard-proxy Deployment in namespace agent"
    got = ((dep["spec"]["template"].get("metadata") or {}).get("annotations") or {}).get("checksum/proxy-py")
    if got != want:
        return False, f"checksum/proxy-py is {got!r}, git pins {want!r}: Argo CD has not synced the repin"
    st, replicas = dep.get("status") or {}, dep["spec"].get("replicas", 1)
    if (st.get("observedGeneration") != dep["metadata"].get("generation")
            or st.get("updatedReplicas") != replicas or st.get("availableReplicas") != replicas):
        return False, (f"not rolled out: {st.get('updatedReplicas')} of {replicas} updated, "
                       f"{st.get('availableReplicas')} available")
    return True, f"checksum/proxy-py {got}, {replicas} replica(s) rolled out"


def run_checks(cluster: RecordingCluster, check: Callable[[str, bool, str], None]) -> list[dict]:
    """Every check after the prerequisites, against one cluster. Returns the probe's results (empty when not run)."""
    host = cluster.identity_host()
    community = kp.identity_name(host) in {kp.identity_name(h) for h in kp.COMMUNITY_HOSTS}
    check("the context is the community cluster, the live public bot", community,
          f"its cluster-identity public-host is {host!r}, not one of {list(kp.COMMUNITY_HOSTS)}")
    if not community:
        return []
    cluster.host = host

    ok, note = proxy_rolled_out(cluster.deployment("guard-proxy"), git_proxy_checksum())
    check("guard-proxy runs git's proxy.py, which forwards the /chat witch name (#803)", ok, note)
    if not ok:
        check("the probe's Challenge 3 beat ran", False, "not run, so no model call is spent: " + note)
        return []

    nameless_before = cluster.deployment_exists(NAMELESS_JOKER)
    results = kp.Probe(cluster, max_calls=1).run(c3_beats())
    by_key = {r["key"]: r for r in results}
    for key in BEAT_KEYS:
        r = by_key.get(key) or {"verdict": kp.FAIL, "title": key, "note": "the probe did not report this beat"}
        check(f"probe beat {key} passes: {r['title']}", r["verdict"] == kp.PASS, r["note"])

    check("the beat spent one model call", cluster.calls == 1, f"it spent {cluster.calls}")
    want = {"prompt": f"{ROOM_ASK}\n\n{kp.PROBE_MARKER}", "witch": kp.STAGE_NAME}
    check("the probe asks the room's plain question with the stage name as the witch, as the chat page sends it (#764)",
          cluster.bodies == [want], f"sent {cluster.bodies}, want [{want}]")
    check(f"the Joker it asks for is joker-<stage name> ({kp.ROOM_JOKER})",
          kp.ROOM_JOKER == f"joker-{kp.ticket_site.slug(kp.STAGE_NAME)}" and kp.ROOM_JOKER != NAMELESS_JOKER,
          kp.ROOM_JOKER)

    nameless_made = not nameless_before and cluster.deployment_exists(NAMELESS_JOKER)
    if nameless_made:
        cluster.delete_deployment(NAMELESS_JOKER)
    check(f"the ask landed no {NAMELESS_JOKER}: the stage name reached the agent", not nameless_made,
          f"this run's ask created {NAMELESS_JOKER} (now deleted): the bot did not get the witch name")
    check(f"the probe left no {kp.ROOM_JOKER} behind", not cluster.room_joker_exists())
    return results


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    context = os.environ.get("COMMUNITY_CONTEXT", "")
    missing = []
    if not context:
        missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if not missing:
        env = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}
        if os.environ.get("KUBECONFIG"):
            env["KUBECONFIG"] = os.environ["KUBECONFIG"]
        r = subprocess.run(["kubectl", "--context", context, "--request-timeout=15s", "get", "--raw", "/readyz"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            missing.append(f"cluster for context {context!r} is not reachable: {(r.stderr or r.stdout).strip()[:200]}")
    if missing:
        print("FAILED: the live Challenge 3 check cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== the KubeCon probe's Challenge 3 beat on the live public bot ({context}) ==")
    cluster = RecordingCluster("", context, None, os.environ.get("KUBECONFIG") or None, timeout=120.0)
    run_checks(cluster, check)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All live Challenge 3 probe checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
