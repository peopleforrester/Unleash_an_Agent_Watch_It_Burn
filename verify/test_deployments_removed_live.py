# ABOUTME: Live end-to-end check of #1022 (#1049, #1050, #1051): a public-image room app the guardrails sweep deletes reads
# ABOUTME: "removed at <time>", greyed, on the deployments page within about 90 s, and a registry.burritobot.co one stays unmarked.
# SUITE: e2e (needs kubectl, node, COMMUNITY_CONTEXT naming a KubeCon cluster, and the network to reach its public host)
"""Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_deployments_removed_live.py

The pieces, each checked offline on its own: remove-untrusted-room-workloads deletes a room workload from outside
registry.burritobot.co once deny-external-registries reads Deny (#990, verify/test_room_cleanup_live.py live); the desk
marks a landed row removed from a cluster read (#1049, verify/test_desk_removed_rows.py); and workshop-mcp reads the
room's workloads every 30 s and posts each read to the desk (#1050, verify/test_room_reader.py). This runs them together
on a cluster, as the room sees them during guardrails-on.

In order, this:

1. checks the cluster runs the sweep (the DeletingPolicy) and reads the two registry policies' validationActions;
2. lists what the sweep would delete as things stand once armed, and fails, having changed nothing, when that is
   anything but this check's own: arming then would delete a workload this check did not create;
3. creates two Deployments of zero replicas in agent, labelled burritobot.co/workload as deploy_app labels the room's
   (so they run no pod): one on a public.ecr.aws image, one on registry.burritobot.co. As the admin they are judged by
   no agent policy;
4. reports each to the desk as deploy_app does, a POST /landed with kind Deployment over a port-forward to
   svc/fake-ticket :8080 (the console refuses /landed from outside), and checks both rows are listed and unmarked;
5. waits one reader interval and checks both rows are still unmarked: a read that lists them marks neither;
6. arms guardrails-on's Kyverno half on this cluster alone, the two patches the terminal's `_kg on kyverno` makes
   (restrict-image-registries and deny-external-registries to Deny). The terminal's whole guardrails-on would also flip
   RBAC, KubeArmor and egress on both KubeCon clusters, none of which the sweep reads;
7. polls until /deployments.json marks the public row "removed at <HH:MM:SS>", within LIMIT_S of the arm (a sweep pass
   comes each minute and a read each 30 s, so about 90 s, and the limit leaves room for a slow host), prints how long
   it took, checks
   the public Deployment is gone, and that in that same read the internal Deployment is still there and its row
   unmarked;
8. reads the page the room sees, https://deployments-<public host>/, and its /deployments.json through the console,
   and runs the page's own script in node against those rows: the public line reads "Someone deployed nginx at <t>,
   removed at <t>" with the class the page greys, the internal line reads "Someone deployed maintenance-shell at <t>"
   with no class;
9. always puts both policies back to the actions it read, deletes both Deployments, and checks the policies, and the
   names of every Deployment, StatefulSet, DaemonSet, Job and CronJob in agent, are as it found them.

Steps 2 to 9 hold the cluster's guard lock (verify/guard_lease.py, #1016), as every check that switches a policy does.

What it leaves: its two rows on the desk. The desk keeps landed rows in memory and has no way to drop one (#1049
keeps every row by design), and restarting fake-ticket would drop the room's rows and tickets as well, as
verify/desk_ticket_live.py says of its tickets. Both rows end greyed: once the check deletes the internal Deployment,
the next read marks it removed too, which the check waits for, so the page tells the truth about both.

It takes about four minutes.
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

CONTEXT = os.environ.get("COMMUNITY_CONTEXT", "")
POLICIES = ("restrict-image-registries", "deny-external-registries")
PUBLIC = "public.ecr.aws/docker/library/nginx:1.29-alpine"
INTERNAL = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
INTERNAL_REGISTRY = "registry.burritobot.co/"
ROOM_LABEL = "burritobot.co/workload"
# Names of the workloads the sweep can delete that a check of "as found" compares; ReplicaSets and Pods are left out,
# since the platform's own roll as they will.
FOUND_KINDS = ("deployments", "statefulsets", "daemonsets", "jobs", "cronjobs")
SWEEP_KINDS = ("deployments", "statefulsets", "daemonsets", "replicasets", "jobs", "cronjobs", "pods")
# workshop-mcp reads every CLUSTER_READ_SECONDS (30) and dates a read two seconds before it starts, so a read that
# counts for a row starts within 32 s of the row and posts a few seconds later.
READ_INTERVAL_S = 45
# A sweep pass comes at the next minute boundary after the arm, and the read that counts starts up to 32 s after the
# delete and takes a few seconds: about 95 s at worst. Each poll here is a port-forward and a GET, several seconds on a
# busy host. Run 18559 measured 54 s on watch-it-burn-community and 91 s on watch-it-burn-private, so 120 s would sit
# too close to the worst case; 150 s does not.
LIMIT_S = 150
POLL_S = 5
STAMP = time.strftime("%H%M%S")
GONE, KEPT = f"wib-1051-public-{STAMP}", f"wib-1051-internal-{STAMP}"
HHMMSS = re.compile(r"\d\d:\d\d:\d\d")
# Each line as it happens: the check waits for minutes, and a log read meanwhile should show where it is.
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
    print("DEPLOYMENTS REMOVED-ROW LIVE CHECK GREEN")
    sys.exit(0)


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "--context", CONTEXT, *args]
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"kubectl {' '.join(args)[:120]} timed out after 120 s")


def get_json(*args: str) -> dict:
    r = kubectl("get", *args, "-o", "json")
    try:
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except ValueError:
        return {}


def actions() -> dict[str, list[str]]:
    return {p: get_json("validatingpolicy", p).get("spec", {}).get("validationActions", []) for p in POLICIES}


def set_actions(policy: str, value: list[str]) -> subprocess.CompletedProcess:
    return kubectl("patch", "validatingpolicy", policy, "--type=json",
                   "-p", json.dumps([{"op": "replace", "path": "/spec/validationActions", "value": value}]))


def found_names() -> dict[str, list[str]]:
    return {k: sorted(o["metadata"]["name"] for o in get_json(k, "-n", "agent").get("items", [])) for k in FOUND_KINDS}


def sweep_targets() -> list[str]:
    """What remove-untrusted-room-workloads deletes once armed, by its own conditions read from git's policy: a room
    workload (its pod carries the room label) that owns itself, is not Argo CD's, and runs an image from outside the
    internal registry. "<kind>/<name>" each."""
    out = []
    for kind in SWEEP_KINDS:
        for o in get_json(kind, "-n", "agent").get("items", []):
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


def desk(path: str, body: dict | None = None) -> tuple[int | None, object, str]:
    """GET (or POST body as JSON) http://fake-ticket:8080<path> over a port-forward: (status, parsed JSON, error)."""
    with kube_forward.forward(["kubectl", "--context", CONTEXT], "agent", "svc/fake-ticket", 8080) as (port, err):
        if err:
            return None, None, err
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read()), ""
        except urllib.error.HTTPError as e:
            return e.code, None, e.read().decode("utf-8", "replace")[:300]
        except (OSError, ValueError) as e:
            return None, None, f"{type(e).__name__}: {e}"


def rows_by_name(rows: object) -> dict[str, dict]:
    """The newest row of each of this check's two names (the desk lists newest first)."""
    out: dict[str, dict] = {}
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("name") in (GONE, KEPT):
            out.setdefault(r["name"], r)
    return out


def fetch(url: str) -> tuple[str, str]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace"), ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", f"{type(e).__name__}: {e}"


# The page's script run in node with stub elements, as verify/test_deployments_witch_line_e2e.py runs it offline: an
# element's text is its own textContent, or its children's text in order, which is what a browser shows.
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


missing = []
if not CONTEXT:
    missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of a KubeCon cluster (watch-it-burn-community)")
for tool in ("kubectl", "node"):
    if not shutil.which(tool):
        missing.append(f"{tool} is not on PATH")
if missing:
    for m in missing:
        print(f"FAIL: {m}", file=sys.stderr)
    sys.exit(1)

print(f"== 1. the sweep runs on {CONTEXT} ==")
check("the cluster answers", kubectl("get", "--raw", "/readyz").returncode == 0)
check("the DeletingPolicy remove-untrusted-room-workloads is installed",
      bool(get_json("deletingpolicy", "remove-untrusted-room-workloads")))
public_host = kubectl("-n", "agent", "get", "configmap", "cluster-identity", "-o",
                      "jsonpath={.data.public-host}").stdout.strip()
check("the cluster-identity ConfigMap names this cluster's public host", bool(public_host))
if failures:
    finish()
PAGE = f"https://deployments-{public_host}"

made = False


def run_checks() -> None:
    """Steps 2 to 9, under the guard lock."""
    global made
    print("== 2. what arming would delete ==")
    before = actions()
    found = found_names()
    print(f"  ..    validationActions here: {before}")
    check("both registry policies read Deny or Audit", all(v in (["Deny"], ["Audit"]) for v in before.values()),
          str(before))
    targets = sweep_targets()
    check("armed, the sweep would delete nothing in agent that this check did not create", not targets,
          f"it would delete {targets}, so arming here would not leave the cluster as found; nothing was changed")
    if failures:
        return
    armed_here: list[str] = []
    try:
        print("== 3. two room Deployments, one public, one internal ==")
        r = kubectl("apply", "-f", "-", stdin="\n---\n".join(json.dumps(deployment(n, i))
                                                           for n, i in ((GONE, PUBLIC), (KEPT, INTERNAL))))
        made = True
        check("both are created", r.returncode == 0, r.stderr.strip()[:300])

        print("== 4. each is reported to the desk as deploy_app reports it ==")
        for name, image in ((GONE, PUBLIC), (KEPT, INTERNAL)):
            status, row, err = desk("/landed", {"name": name, "ok": True, "detail": "", "image": image,
                                                "requested_by": "", "kind": "Deployment"})
            check(f"POST /landed for {name} answers its row, kind Deployment",
                  status == 200 and isinstance(row, dict) and row.get("kind") == "Deployment" and row.get("ok") is True,
                  err or str(row)[:300])
        status, rows, err = desk("/deployments.json")
        mine = rows_by_name(rows)
        check("/deployments.json lists both rows, unmarked", set(mine) == {GONE, KEPT}
              and all(r.get("removed_at") == "" for r in mine.values()), err or json.dumps(mine)[:300])

        print(f"== 5. a read that lists them marks neither ({READ_INTERVAL_S} s) ==")
        time.sleep(READ_INTERVAL_S)
        status, rows, err = desk("/deployments.json")
        mine = rows_by_name(rows)
        check("both rows are still unmarked after a read interval", set(mine) == {GONE, KEPT}
              and all(r.get("removed_at") == "" for r in mine.values()), err or json.dumps(mine)[:300])

        print("== 6. guardrails-on's Kyverno half, on this cluster ==")
        for p in POLICIES:
            if before[p] != ["Deny"]:
                r = set_actions(p, ["Deny"])
                armed_here.append(p)
                check(f"{p} is set to Deny", r.returncode == 0, r.stderr.strip()[:300])
        t_arm = time.monotonic()
        check("both registry policies read Deny", all(v == ["Deny"] for v in actions().values()))

        print(f"== 7. the public row reads removed within {LIMIT_S} s, the internal one does not ==")
        marked: dict[str, dict] = {}
        names: set[str] = set()
        elapsed = 0.0
        while time.monotonic() - t_arm < LIMIT_S:
            status, rows, err = desk("/deployments.json")
            mine = rows_by_name(rows)
            if mine.get(GONE, {}).get("removed_at"):
                elapsed = time.monotonic() - t_arm
                marked = mine
                names = {d["metadata"]["name"] for d in get_json("deployment", "-n", "agent").get("items", [])}
                break
            time.sleep(POLL_S)
        check(f"/deployments.json marks the public row removed within {LIMIT_S} s of the arm", bool(marked),
              f"after {LIMIT_S} s it read {json.dumps(rows_by_name(desk('/deployments.json')[1]))[:300]}")
        if marked:
            print(f"  ..    marked {elapsed:.0f} s after the arm: {json.dumps(marked[GONE])}")
            check("it reads 'removed at <HH:MM:SS>'", bool(HHMMSS.fullmatch(marked[GONE]["removed_at"])),
                  marked[GONE]["removed_at"])
            check("the sweep deleted the public Deployment", GONE not in names)
            check("the internal Deployment is still there", KEPT in names, str(sorted(names)))
            check("and in that same read its row is unmarked", marked.get(KEPT, {}).get("removed_at") == "",
                  json.dumps(marked.get(KEPT)))

            print("== 8. the page the room sees greys the public line and only it ==")
            page, err = fetch(PAGE + "/")
            check(f"{PAGE}/ is the deployments page", "Everything BurritoBot deployed" in page, err)
            body, err = fetch(PAGE + "/deployments.json")
            try:
                public_rows = json.loads(body) if body else []
            except ValueError:
                public_rows = []
            seen = rows_by_name(public_rows)
            check(f"{PAGE}/deployments.json, through the console, marks the public row as the desk does",
                  seen.get(GONE, {}).get("removed_at") == marked[GONE]["removed_at"]
                  and seen.get(KEPT, {}).get("removed_at") == "", err or json.dumps(seen)[:300])
            if page and seen:
                lines, err = page_lines(page, [r for r in public_rows if r.get("name") in (GONE, KEPT)])
                want_gone = f"Someone deployed nginx at {seen[GONE]['at']}, removed at {seen[GONE]['removed_at']}"
                want_kept = f"Someone deployed maintenance-shell at {seen[KEPT]['at']}"
                by_text = {x["text"]: x["cls"] for x in lines}
                check(f"the page's script renders the public line {want_gone!r}, with the class it greys",
                      by_text.get(want_gone) == "removed" and "li.removed,li.removed b{color:" in page,
                      err or json.dumps(lines))
                check(f"and the internal line {want_kept!r}, not greyed", by_text.get(want_kept) == "",
                      err or json.dumps(lines))
    finally:
        print("== 9. the cluster as it was found ==")
        for p in armed_here:
            r = set_actions(p, before[p])
            check(f"{p} is back to {before[p]}", r.returncode == 0, r.stderr.strip()[:300])
        if made:
            r = kubectl("delete", "deployment", "-n", "agent", GONE, KEPT, "--ignore-not-found", "--wait=true")
            check("this check's Deployments are deleted", r.returncode == 0, r.stderr.strip()[:300])
        after = actions()
        check("both registry policies read what they read before", after == before, f"before {before}, after {after}")
        now = found_names()
        check("every Deployment, StatefulSet, DaemonSet, Job and CronJob in agent is as found", now == found,
              f"before {json.dumps(found)}\n        after  {json.dumps(now)}")


if not guard_lease.run_held(CONTEXT, run_checks, check, "verify/test_deployments_removed_live.py"):
    sys.exit(guard_lease.BUSY_EXIT)

if made:
    print(f"== the desk keeps both rows; the internal one is marked once a read misses it ({READ_INTERVAL_S * 2} s) ==")
    deadline = time.monotonic() + READ_INTERVAL_S * 2
    mine = {}
    while time.monotonic() < deadline:
        mine = rows_by_name(desk("/deployments.json")[1])
        if mine.get(KEPT, {}).get("removed_at"):
            break
        time.sleep(POLL_S)
    check("both of this check's rows now read removed, so the page says what the cluster runs",
          all(mine.get(n, {}).get("removed_at") for n in (GONE, KEPT)), json.dumps(mine)[:300])
finish()
