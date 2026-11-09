# ABOUTME: Live check of #1269 on a KubeCon cluster: deploy_app, run in the workshop-mcp pod, refuses a deploy named with
# ABOUTME: a code-of-conduct term, and neither the cluster nor the deployments page holds any such name afterwards.
"""Usage:
    python3 verify/deploy_coc_live.py --context <kube-context> [--source gitops/ai-layer/workshop-mcp-server.py]
                                      [--deployments https://deployments.burritobot.co/deployments.json] [--term N]

Runs deploy_app in the cluster's own workshop-mcp pod (`kubectl exec deploy/workshop-mcp -c shim`, as the KubeCon
probe's C6 tool check runs read_support_ticket there), with its own Python, packages and ServiceAccount, on a Deployment
named joker-<term N of the #1267 floor> (term 0 unless --term says otherwise). With --source, the pod runs that file's
deploy_app, sent on stdin, instead of its mounted /app/server.py: that checks a change before it is deployed. Without
it, the pod runs what Argo CD deployed.

Before it calls deploy_app the pod checks the module carries the code-of-conduct check (coc_hit), and when it does not,
it calls nothing and the check FAILs saying so: a deploy_app without the check would apply the Deployment. The refusal
is raised before any call to the API server, so the check changes nothing on the cluster or the desk.

Then it holds, reading only:
  refused     deploy_app raised, starting "deploy failed for this manifest:", naming the code of conduct, with no term
  cluster     no Deployment in the agent namespace has the test's name, and none has a floor term in its name
  page        the deployments page's JSON (the community cluster's desk, the one page the room reads) has no row of the
              test's name and no floor term anywhere

No line it prints names the term: the term is sent to the pod ROT13-encoded and named by its index.
"""
from __future__ import annotations

import argparse
import codecs
import json
import pathlib
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "docs/research/2026-11-09-coc-floor"))
import corpus  # noqa: E402
import floor  # noqa: E402

FLOOR = floor.Floor("proposed")
IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
# Run in the pod. argv[1] is the ROT13 test name; stdin is the deploy_app source to load, or empty for /app/server.py.
IN_POD = r"""
import codecs, json, sys, types
sys.path.insert(0, "/app")
src = sys.stdin.read()
if src:
    server = types.ModuleType("server_under_test")
    server.__file__ = "/app/server.py"
    exec(compile(src, "workshop-mcp-server.py (sent)", "exec"), server.__dict__)
else:
    import server
if not hasattr(server, "coc_hit"):
    print(json.dumps({"has_check": False}))
    sys.exit(0)
name = codecs.decode(sys.argv[1], "rot13")
manifest = {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "labels": {"app": name}},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}},
                                  "spec": {"containers": [{"name": "joker", "image": sys.argv[2]}]}}}}
try:
    out = {"has_check": True, "refused": False, "answer": str(server.deploy_app(json.dumps(manifest), ""))[:300]}
except Exception as e:
    out = {"has_check": True, "refused": True, "type": type(e).__name__, "message": str(e)[:600]}
out["answer_has_term"] = bool(server.coc_hit(out.get("answer", ""), out.get("message", "")))
out.pop("answer", None) if out.get("answer_has_term") else None
print(json.dumps(out))
"""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def kubectl(context: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", context, *args], input=stdin, capture_output=True, text=True,
                          timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--context", required=True, help="the kube-context of the cluster to check (named on every call)")
    ap.add_argument("--source", help="a workshop-mcp-server.py to run in the pod instead of the deployed one")
    ap.add_argument("--deployments", default="https://deployments.burritobot.co/deployments.json",
                    help="the deployments page's JSON the room reads")
    ap.add_argument("--term", type=int, default=0, help="which term of the floor's list to name the deploy with")
    a = ap.parse_args()

    terms = corpus.terms("proposed")
    name = "joker-" + "-".join(terms[a.term].split())
    source = pathlib.Path(a.source).read_text(encoding="utf-8") if a.source else ""
    print(f"context {a.context}; deploy_app from {a.source or 'the deployed /app/server.py'}; the deploy is named "
          f"joker-<term {a.term} of {len(terms)}>", flush=True)

    p = kubectl(a.context, "-n", "agent", "exec", "-i", "deploy/workshop-mcp", "-c", "shim", "--",
                "python3", "-c", IN_POD, codecs.encode(name, "rot13"), IMAGE, stdin=source)
    try:
        got = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = None
    if got is None:
        check("deploy_app ran in the workshop-mcp pod", False,
              f"exit {p.returncode}; stderr: {FLOOR.mask(p.stderr.strip())[-400:]}")
    elif not got.get("has_check"):
        check("the pod's deploy_app carries the code-of-conduct check", False,
              "it has no coc_hit, so nothing was called: deploy it first, or pass --source")
    else:
        msg = got.get("message", "")
        check("deploy_app refused the deploy, plainly, naming no term",
              got.get("refused") and msg.startswith("deploy failed for this manifest:") and "code of conduct" in msg
              and msg.endswith("Nothing was deployed.") and not got.get("answer_has_term") and not FLOOR.spans(msg),
              FLOOR.mask(json.dumps(got)))

    p = kubectl(a.context, "-n", "agent", "get", "deployments", "-o", "json")
    if p.returncode != 0:
        check("the agent namespace's Deployments read", False, p.stderr.strip()[-300:])
    else:
        names = [d["metadata"]["name"] for d in json.loads(p.stdout).get("items", [])]
        check(f"no Deployment of the test's name, and no floor term in any of the {len(names)} Deployment names",
              name not in names and not [n for n in names if FLOOR.spans(n)],
              f"{sum(1 for n in names if FLOOR.spans(n))} names carry a term")

    try:
        with urllib.request.urlopen(urllib.request.Request(a.deployments, headers={"Cache-Control": "no-cache"}),
                                    timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
        rows = json.loads(page)
        check(f"the deployments page ({len(rows)} rows) has no row of the test's name and no floor term",
              not [r for r in rows if r.get("name") == name] and not FLOOR.spans(page),
              f"{len(FLOOR.spans(page))} terms on the page")
    except (OSError, ValueError) as e:
        check("the deployments page read", False, str(e)[:300])

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
