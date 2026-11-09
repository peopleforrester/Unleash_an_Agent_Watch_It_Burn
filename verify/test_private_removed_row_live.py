# ABOUTME: Live check of #1209's third criterion (#1250): a room Deployment Kyverno's sweep removes on the private
# ABOUTME: KubeCon cluster reads greyed, "removed at", under private on deployments.burritobot.co; no community row does.
# SUITE: e2e (needs kubectl, node, PRIVATE_CONTEXT and COMMUNITY_CONTEXT naming the KubeCon pair, and the network)
"""Usage: PRIVATE_CONTEXT=<kube-context> COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
              python3 verify/test_private_removed_row_live.py

Since #1209 the private cluster's reader (#1050) posts each read through desk-relay to the public desk's
/remote-cluster-read with the desk-report-token, and the public desk applies it to the rows labelled private alone.
verify/test_public_desk.py and verify/test_desk_remote_reports.py hold that on localhost; this runs it on the two
clusters, as the room sees it during guardrails-on on the admin cluster. verify/test_deployments_removed_live.py is the
same check for the community cluster's own rows.

In order, this:

1. checks the private cluster runs the sweep (the DeletingPolicy) and desk-relay, and the community desk labels the
   token's rows private;
2. reads both clusters' registry policies, and fails, having changed nothing, unless the community's read Audit (its
   sweep would then delete this check's community Deployment) and arming the private cluster's would delete nothing
   this check did not create;
3. creates three Deployments of zero replicas in agent, labelled burritobot.co/workload as deploy_app labels the room's
   (so they run no pod): on the private cluster one on a public.ecr.aws image (GONE) and one on registry.burritobot.co
   (KEPT), and on the community cluster one more named GONE on the public image;
4. reports each as that cluster's deploy_app does: the private two through desk-relay's /landed (a port-forward to
   svc/desk-relay), which sends them to the public desk's /remote-landed with the token, and the community one to the
   community desk's in-cluster /landed (a port-forward to svc/fake-ticket); then reads
   https://deployments.burritobot.co/deployments.json and checks it lists all three, private and community, unmarked;
5. waits one reader interval and checks all three are still unmarked: reads that list them mark none;
6. arms guardrails-on's Kyverno half on the private cluster alone (restrict-image-registries and
   deny-external-registries to Deny), as the terminal's `_kg on kyverno` does;
7. polls deployments.burritobot.co until the private GONE row reads "removed at <HH:MM:SS>", within LIMIT_S of the arm,
   and checks in that same read that the private KEPT row and the community GONE row, of the same name, are unmarked,
   that the sweep deleted the private GONE Deployment, and that both others still run;
8. runs the page the room sees, https://deployments.burritobot.co/, in node against those rows: the private GONE line
   reads "Someone deployed nginx at <t>, removed at <t> private" with the class the page greys, and the other two lines
   carry no class;
9. always puts the private policies back to the actions it read, deletes all three Deployments, removes the three rows
   from the one page with the community desk's loopback-only /desk-forget (#1215), and checks the policies and the
   names of every Deployment, StatefulSet, DaemonSet, Job and CronJob in agent on both clusters are as found, and that
   the page lists no row of this check's names.

Steps 2 to 9 hold the guard lock on the private cluster and its guardrails peer, the community cluster
(verify/guard_lease.py, #1016): this check switches policies on one and deploys on both. No model call, and no Secret
is read: the token stays in desk-relay. It takes about four minutes.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import guard_lease  # noqa: E402
import kube_forward  # noqa: E402

PRIVATE = os.environ.get("PRIVATE_CONTEXT", "")
COMMUNITY = os.environ.get("COMMUNITY_CONTEXT", "")
POLICIES = ("restrict-image-registries", "deny-external-registries")
SWEEP = "remove-untrusted-room-workloads"
PUBLIC_IMAGE = "public.ecr.aws/docker/library/nginx:1.29-alpine"
INTERNAL_IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
INTERNAL_REGISTRY = "registry.burritobot.co/"
ROOM_LABEL = "burritobot.co/workload"
# The one page both KubeCon bots' deploys land on: the community cluster's fake-ticket behind the router (#1157).
PAGE = "https://deployments.burritobot.co"
# The labels the public desk gives its own rows and the token's (gitops/ai-layer/components/desk-remote-reports).
PRIVATE_LABEL, COMMUNITY_LABEL = "private", "community"
FOUND_KINDS = ("deployments", "statefulsets", "daemonsets", "jobs", "cronjobs")
SWEEP_KINDS = ("deployments", "statefulsets", "daemonsets", "replicasets", "jobs", "cronjobs", "pods")
# workshop-mcp reads every 30 s and dates a read two seconds before it starts; a read that counts for a row starts
# within 32 s of it, and the relay adds one HTTPS hop to the public desk.
READ_INTERVAL_S = 45
# A sweep pass comes at the next minute boundary after the arm, then the read that counts, then the relay's hop. Run
# 18559 measured 91 s on watch-it-burn-private for its own desk; the relay's hop and a busy host get 180 s here.
LIMIT_S = 180
POLL_S = 5
STAMP = time.strftime("%H%M%S")
GONE, KEPT = f"wib-1250-public-{STAMP}", f"wib-1250-internal-{STAMP}"
NAMES = (GONE, KEPT)
HHMMSS = re.compile(r"\d\d:\d\d:\d\d")
# The community desk's loopback-only /desk-forget, run in its pod (#1215), as kubecon_probe.DESK_FORGET runs it.
DESK_FORGET = ["-n", "agent", "exec", "deploy/fake-ticket", "-c", "site", "--", "python3", "-c",
               "import sys, urllib.request; r = urllib.request.Request('http://127.0.0.1:8080/desk-forget', "
               "method='POST', data=sys.argv[1].encode(), headers={'Content-Type': 'application/json'}); "
               "print(urllib.request.urlopen(r, timeout=20).read().decode())"]
# The desk stamps a row with its own clock, in another pod; the forget's `since` is moved back this far for the skew.
DESK_CLOCK_SKEW_S = 30.0
DESK_ENV = ["-n", "agent", "exec", "deploy/fake-ticket", "-c", "site", "--", "python3", "-c",
            "import json, os; print(json.dumps({'cluster': os.environ.get('DESK_CLUSTER', ''), "
            "'remote': os.environ.get('DESK_REMOTE_CLUSTER', '')}))"]
sys.stdout.reconfigure(line_buffering=True)
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("PRIVATE REMOVED-ROW LIVE CHECK GREEN")
    sys.exit(0)


def kubectl(ctx: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "--context", ctx, *args]
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"kubectl {' '.join(args)[:120]} timed out after 120 s")


def get_json(ctx: str, *args: str) -> dict:
    r = kubectl(ctx, "get", *args, "-o", "json")
    try:
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except ValueError:
        return {}


def actions(ctx: str) -> dict[str, list[str]]:
    return {p: get_json(ctx, "validatingpolicy", p).get("spec", {}).get("validationActions", []) for p in POLICIES}


def set_actions(ctx: str, policy: str, value: list[str]) -> subprocess.CompletedProcess:
    return kubectl(ctx, "patch", "validatingpolicy", policy, "--type=json",
                   "-p", json.dumps([{"op": "replace", "path": "/spec/validationActions", "value": value}]))


def found_names(ctx: str) -> dict[str, list[str]]:
    return {k: sorted(o["metadata"]["name"] for o in get_json(ctx, k, "-n", "agent").get("items", []))
            for k in FOUND_KINDS}


def deployment_names(ctx: str) -> set[str]:
    return {d["metadata"]["name"] for d in get_json(ctx, "deployment", "-n", "agent").get("items", [])}


def sweep_targets(ctx: str) -> list[str]:
    """What remove-untrusted-room-workloads deletes once armed, by its own conditions: a room workload (its pod carries
    the room label) that owns itself, is not Argo CD's, and runs an image from outside the internal registry."""
    out = []
    for kind in SWEEP_KINDS:
        for o in get_json(ctx, kind, "-n", "agent").get("items", []):
            meta = o.get("metadata", {})
            spec = o.get("spec", {})
            pod = o if o.get("kind") == "Pod" else (spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
                                                     if o.get("kind") == "CronJob" else spec.get("template", {}))
            pspec = pod.get("spec", {})
            images = [c.get("image", "") for c in (pspec.get("containers") or []) + (pspec.get("initContainers") or [])]
            if (ROOM_LABEL in (pod.get("metadata", {}).get("labels") or {}) and not meta.get("ownerReferences")
                    and not any(str(f.get("manager", "")).startswith("argocd") for f in meta.get("managedFields") or [])
                    and any(not i.startswith(INTERNAL_REGISTRY) for i in images)):
                out.append(f"{o.get('kind')}/{meta.get('name')}")
    return sorted(out)


def deployment(name: str, image: str) -> dict:
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": "agent"},
            "spec": {"replicas": 0, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name, ROOM_LABEL: name}},
                                  "spec": {"containers": [{"name": "c", "image": image,
                                                           "resources": {"limits": {"cpu": "50m", "memory": "64Mi"}}}]}}}}


def landed(ctx: str, svc: str, name: str, image: str) -> tuple[int | None, object, str]:
    """POST /landed, as deploy_app reports a Deployment, to svc:8080 on ctx over a port-forward."""
    with kube_forward.forward(["kubectl", "--context", ctx], "agent", svc, 8080) as (port, err):
        if err:
            return None, None, err
        body = {"name": name, "ok": True, "detail": "", "image": image, "requested_by": "", "kind": "Deployment"}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/landed", method="POST", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read()), ""
        except urllib.error.HTTPError as e:
            return e.code, None, e.read().decode("utf-8", "replace")[:300]
        except (OSError, ValueError) as e:
            return None, None, f"{type(e).__name__}: {e}"


def fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace"), ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", f"{type(e).__name__}: {e}"


def page_rows() -> tuple[list[dict], str]:
    body, err = fetch(PAGE + "/deployments.json")
    try:
        rows = json.loads(body) if body else []
    except ValueError:
        return [], f"{PAGE}/deployments.json is not JSON: {body[:200]}"
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else [], err


def mine(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """This check's rows by (name, cluster), the newest of each (the desk lists newest first)."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r.get("name") in NAMES:
            out.setdefault((r["name"], r.get("cluster", "")), r)
    return out


P_GONE, P_KEPT, C_GONE = (GONE, PRIVATE_LABEL), (KEPT, PRIVATE_LABEL), (GONE, COMMUNITY_LABEL)
ALL_ROWS = {P_GONE, P_KEPT, C_GONE}


def marks(seen: dict) -> dict[str, str]:
    """Each of this check's rows as name@cluster, with what it reads in removed_at, for a failure's detail."""
    return {f"{name}@{cluster}": r.get("removed_at") for (name, cluster), r in seen.items()}


def unmarked(seen: dict) -> bool:
    return set(seen) == ALL_ROWS and all(r.get("removed_at") == "" for r in seen.values())


# The page's script run in node with stub elements, as verify/test_deployments_removed_live.py runs it: an element's
# text is its own textContent, or its children's text in order, which is what a browser shows.
HARNESS = r"""
const [script, rows] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
function el(tag){return {tag, children:[], className:'', title:'', _text:null,
  set textContent(v){this._text=String(v);this.children=[];}, get textContent(){return this._text!==null?this._text:
  this.children.map(c=>c.textContent).join('');}, appendChild(c){this.children.push(c);return c;},
  replaceChildren(...cs){this.children=cs;this._text=null;}};}
const ul = el('ul');
const document = {getElementById: id => id === 'deployments' ? ul : null, createElement: el,
  createTextNode: t => ({tag:'#text', title:'', get textContent(){return String(t);}, children:[]})};
const fetch = async () => ({json: async () => rows});
const vm = require('vm');
const ctx = vm.createContext({document, fetch, setInterval: () => 0, encodeURIComponent, console});
vm.runInContext(script, ctx);
setTimeout(() => {
  const lines = ul.children.map(li => ({text: li.textContent, cls: li.className}));
  process.stdout.write(JSON.stringify(lines));
}, 200);
"""


def page_lines(page: str, rows: list) -> tuple[list[dict], str]:
    found = re.search(r"<script>(.*?)</script>", page, re.S)
    if not found:
        return [], "the page carries no script"
    n = subprocess.run(["node", "-e", HARNESS], input=json.dumps([found.group(1), rows]), capture_output=True,
                       text=True, timeout=60)
    if n.returncode != 0 or not n.stdout.startswith("["):
        return [], f"node exit {n.returncode}: {n.stderr[-400:]}"
    return json.loads(n.stdout), ""


def forget_rows(since: float) -> str:
    """This check's rows off the one page with the community desk's /desk-forget, two passes apart so a report still in
    flight goes too; "" when the desk lists none of them afterwards, else why."""
    body = json.dumps({"names": list(NAMES), "since": max(0.0, since - DESK_CLOCK_SKEW_S)})
    d: dict = {}
    for n in range(2):
        if n:
            time.sleep(3)
        r = kubectl(COMMUNITY, *DESK_FORGET, body)
        try:
            d = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
        except ValueError:
            d = {}
        if not d:
            return f"/desk-forget on {COMMUNITY} answered exit {r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}"
    return "" if d.get("named_left") == 0 else f"the desk still lists rows of {list(NAMES)}: {d}"


missing = []
if not PRIVATE:
    missing.append("PRIVATE_CONTEXT is not set: name the kube-context of the private KubeCon cluster "
                   "(watch-it-burn-private)")
if not COMMUNITY:
    missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community KubeCon cluster "
                   "(watch-it-burn-community), whose desk serves deployments.burritobot.co")
for tool in ("kubectl", "node"):
    if not shutil.which(tool):
        missing.append(f"{tool} is not on PATH")
if missing:
    for m in missing:
        print(f"FAIL: {m}", file=sys.stderr)
    sys.exit(1)

print(f"== 1. the sweep and desk-relay run on {PRIVATE}, and {COMMUNITY}'s desk labels the token's rows ==")
check(f"{PRIVATE} answers", kubectl(PRIVATE, "get", "--raw", "/readyz").returncode == 0)
check(f"{COMMUNITY} answers", kubectl(COMMUNITY, "get", "--raw", "/readyz").returncode == 0)
check(f"the DeletingPolicy {SWEEP} is installed on {PRIVATE}", bool(get_json(PRIVATE, "deletingpolicy", SWEEP)))
relay = get_json(PRIVATE, "deployment", "desk-relay", "-n", "agent")
check(f"desk-relay runs on {PRIVATE}", relay.get("status", {}).get("readyReplicas", 0) >= 1, str(relay.get("status")))
env = kubectl(COMMUNITY, *DESK_ENV)
try:
    desk_env = json.loads(env.stdout.strip().splitlines()[-1]) if env.returncode == 0 and env.stdout.strip() else {}
except ValueError:
    desk_env = {}
check(f"the desk on {COMMUNITY} labels its own rows {COMMUNITY_LABEL!r} and the token's {PRIVATE_LABEL!r}",
      desk_env == {"cluster": COMMUNITY_LABEL, "remote": PRIVATE_LABEL}, env.stderr.strip()[:200] or str(desk_env))
if failures:
    finish()

made: dict[str, list[str]] = {}


def run_checks() -> None:
    """Steps 2 to 9, under the guard lock on both clusters."""
    print("== 2. the start state ==")
    before = actions(PRIVATE)
    community_actions = actions(COMMUNITY)
    found = {PRIVATE: found_names(PRIVATE), COMMUNITY: found_names(COMMUNITY)}
    print(f"  ..    validationActions on {PRIVATE}: {before}; on {COMMUNITY}: {community_actions}")
    check(f"both registry policies on {PRIVATE} read Deny or Audit",
          all(v in (["Deny"], ["Audit"]) for v in before.values()), str(before))
    check(f"both registry policies on {COMMUNITY} read Audit, so its sweep leaves this check's Deployment there",
          all(v == ["Audit"] for v in community_actions.values()), str(community_actions))
    targets = sweep_targets(PRIVATE)
    check(f"armed, the sweep on {PRIVATE} would delete nothing in agent that this check did not create", not targets,
          f"it would delete {targets}, so arming here would not leave the cluster as found; nothing was changed")
    if failures:
        return
    armed: list[str] = []
    t_start = time.time()
    try:
        print("== 3. room Deployments: a public and an internal one on private, the public name on community ==")
        for ctx, pairs in ((PRIVATE, ((GONE, PUBLIC_IMAGE), (KEPT, INTERNAL_IMAGE))),
                           (COMMUNITY, ((GONE, PUBLIC_IMAGE),))):
            made[ctx] = [n for n, _ in pairs]
            r = kubectl(ctx, "apply", "-f", "-", stdin="\n---\n".join(json.dumps(deployment(n, i)) for n, i in pairs))
            check(f"{', '.join(made[ctx])} created on {ctx}", r.returncode == 0, r.stderr.strip()[:300])

        print("== 4. each is reported as its cluster's deploy_app reports it ==")
        for ctx, svc, name, image, label in ((PRIVATE, "svc/desk-relay", GONE, PUBLIC_IMAGE, PRIVATE_LABEL),
                                             (PRIVATE, "svc/desk-relay", KEPT, INTERNAL_IMAGE, PRIVATE_LABEL),
                                             (COMMUNITY, "svc/fake-ticket", GONE, PUBLIC_IMAGE, COMMUNITY_LABEL)):
            status, row, err = landed(ctx, svc, name, image)
            check(f"POST /landed for {name} through {svc} on {ctx} answers its row, labelled {label}",
                  status == 200 and isinstance(row, dict) and row.get("cluster") == label
                  and row.get("kind") == "Deployment" and row.get("ok") is True, err or f"{status} {str(row)[:300]}")
        rows, err = page_rows()
        seen = mine(rows)
        check(f"{PAGE}/deployments.json lists all three rows, unmarked", unmarked(seen),
              err or json.dumps(marks(seen)))

        print(f"== 5. reads that list them mark none ({READ_INTERVAL_S} s) ==")
        time.sleep(READ_INTERVAL_S)
        rows, err = page_rows()
        seen = mine(rows)
        check("all three rows are still unmarked after a read interval", unmarked(seen), err or json.dumps(marks(seen)))

        print(f"== 6. guardrails-on's Kyverno half, on {PRIVATE} alone ==")
        for p in POLICIES:
            if before[p] != ["Deny"]:
                r = set_actions(PRIVATE, p, ["Deny"])
                armed.append(p)
                check(f"{p} is set to Deny on {PRIVATE}", r.returncode == 0, r.stderr.strip()[:300])
        t_arm = time.monotonic()
        check(f"both registry policies on {PRIVATE} read Deny", all(v == ["Deny"] for v in actions(PRIVATE).values()))

        print(f"== 7. the private public row reads removed within {LIMIT_S} s; the other two do not ==")
        marked: dict = {}
        elapsed = 0.0
        while time.monotonic() - t_arm < LIMIT_S:
            seen = mine(page_rows()[0])
            if seen.get(P_GONE, {}).get("removed_at"):
                elapsed = time.monotonic() - t_arm
                marked = seen
                break
            time.sleep(POLL_S)
        check(f"{PAGE}/deployments.json marks the private row removed within {LIMIT_S} s of the arm", bool(marked),
              f"after {LIMIT_S} s it read {json.dumps(marks(seen))}")
        if marked:
            private_now, community_now = deployment_names(PRIVATE), deployment_names(COMMUNITY)
            print(f"  ..    marked {elapsed:.0f} s after the arm: {json.dumps(marked[P_GONE])}")
            check("it reads 'removed at <HH:MM:SS>'", bool(HHMMSS.fullmatch(marked[P_GONE]["removed_at"])),
                  marked[P_GONE]["removed_at"])
            check(f"the sweep deleted {GONE} on {PRIVATE}", GONE not in private_now)
            check(f"{KEPT} still runs on {PRIVATE}", KEPT in private_now, str(sorted(private_now)))
            check(f"{GONE} still runs on {COMMUNITY}", GONE in community_now, str(sorted(community_now)))
            check("in that same read the private internal row is unmarked",
                  marked.get(P_KEPT, {}).get("removed_at") == "", json.dumps(marked.get(P_KEPT)))
            check("and the community row of the removed name is unmarked: a private read greys no community row",
                  marked.get(C_GONE, {}).get("removed_at") == "", json.dumps(marked.get(C_GONE)))

            print("== 8. the page the room sees greys the private line and only it ==")
            page, err = fetch(PAGE + "/")
            check(f"{PAGE}/ is the deployments page", "Everything BurritoBot deployed" in page, err)
            if page:
                lines, err = page_lines(page, [marked[k] for k in (P_GONE, P_KEPT, C_GONE)])
                want = {
                    f"Someone deployed nginx at {marked[P_GONE]['at']}, removed at {marked[P_GONE]['removed_at']} "
                    f"{PRIVATE_LABEL}": "removed",
                    f"Someone deployed maintenance-shell at {marked[P_KEPT]['at']} {PRIVATE_LABEL}": "",
                    f"Someone deployed nginx at {marked[C_GONE]['at']} {COMMUNITY_LABEL}": ""}
                by_text = {x["text"]: x["cls"] for x in lines}
                for text, cls in want.items():
                    check(f"the page's script renders {text!r} " + ("with the class it greys" if cls else "ungreyed"),
                          text in by_text and by_text[text] == cls
                          and (not cls or "li.removed,li.removed b{color:" in page), err or json.dumps(lines))
    finally:
        print("== 9. both clusters and the page as they were found ==")
        for p in armed:
            r = set_actions(PRIVATE, p, before[p])
            check(f"{p} on {PRIVATE} is back to {before[p]}", r.returncode == 0, r.stderr.strip()[:300])
        for ctx, names in made.items():
            r = kubectl(ctx, "delete", "deployment", "-n", "agent", *names, "--ignore-not-found", "--wait=true")
            check(f"this check's Deployments on {ctx} are deleted", r.returncode == 0, r.stderr.strip()[:300])
        if made:
            why = forget_rows(t_start)
            check("/desk-forget removed this check's rows from the one desk", not why, why)
            rows, err = page_rows()
            left = [f"{r.get('name')}@{r.get('cluster')}" for r in rows if r.get("name") in NAMES]
            check(f"{PAGE}/deployments.json lists no row of this check's names", not err and not left, err or str(left))
        after = actions(PRIVATE)
        check(f"both registry policies on {PRIVATE} read what they read before", after == before,
              f"before {before}, after {after}")
        for ctx in (PRIVATE, COMMUNITY):
            now = found_names(ctx)
            check(f"every Deployment, StatefulSet, DaemonSet, Job and CronJob in agent on {ctx} is as found",
                  now == found[ctx], f"before {json.dumps(found[ctx])}\n        after  {json.dumps(now)}")


if not guard_lease.run_held(PRIVATE, run_checks, check, "verify/test_private_removed_row_live.py", with_peer=True):
    sys.exit(guard_lease.BUSY_EXIT)
finish()
