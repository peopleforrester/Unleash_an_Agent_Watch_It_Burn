# ABOUTME: Second harvest pass for the perishable cluster-local evidence: Kyverno PolicyReports, Falco and
# ABOUTME: KubeArmor alerts, Kubernetes events and pod health. All of it dies with the clusters at teardown.
from __future__ import annotations
import os, json, os, subprocess, pathlib, concurrent.futures, re

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / ".harvest" / os.environ.get("WIB_EVENT", "devopsdays-portland")
SCRATCH = pathlib.Path("/tmp/wib-harvest")
ACCOUNTS = ["accen-dev", "aws1-student31", "aws1-student32", "aws1-student33", "aws1-student34"]
REGION = "us-west-2"

def sh(cmd, env=None, timeout=90):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    return p.returncode, p.stdout, p.stderr

def kc(kcfg, ctx, acct, *a, timeout=75):
    return sh(["kubectl", "--context", ctx, *a], env={"KUBECONFIG": kcfg, "AWS_PROFILE": acct}, timeout=timeout)

def one(rec):
    cluster, friendly, acct = rec["cluster"], rec["friendly"], rec.get("account")
    out = {"cluster": cluster, "friendly": friendly}
    if not acct: out["status"] = "no account"; return out
    kcfg = str(SCRATCH / f"{cluster}.kubeconfig")
    if not pathlib.Path(kcfg).exists():
        sh(["aws","eks","update-kubeconfig","--kubeconfig",kcfg,"--name",cluster,"--region",REGION],
           env={"AWS_PROFILE": acct}, timeout=90)
    rc, ctx, _ = sh(["kubectl","config","current-context"], env={"KUBECONFIG": kcfg}); ctx = ctx.strip()

    # 1. Kyverno PolicyReports: records the villain being CAUGHT, survives pod deletion
    rc, o, _ = kc(kcfg, ctx, acct, "get", "policyreport,clusterpolicyreport", "-A", "-o", "json")
    fails = []
    try:
        for item in (json.loads(o).get("items") or []):
            for r in item.get("results") or []:
                if r.get("result") in ("fail", "warn"):
                    res = (r.get("resources") or [{}])[0]
                    fails.append({"policy": r.get("policy"), "rule": r.get("rule"),
                                  "result": r.get("result"), "ns": res.get("namespace"),
                                  "name": res.get("name"), "kind": res.get("kind"),
                                  "msg": (r.get("message") or "")[:300]})
    except Exception: pass
    out["policy_violations"] = fails
    out["c2_villain_caught"] = any("festival-promo" in json.dumps(f) or "promo" in (f.get("name") or "")
                                   for f in fails)

    # 2. Falco events
    rc, o, _ = kc(kcfg, ctx, acct, "-n", "falco", "logs", "-l", "app.kubernetes.io/name=falco",
                  "--tail=3000", "--all-containers", timeout=120)
    ev = [l for l in (o or "").splitlines() if '"rule"' in l or "Warning" in l or "Notice" in l]
    rules = {}
    for l in ev:
        m = re.search(r'"rule"\s*:\s*"([^"]+)"', l)
        if m: rules[m.group(1)] = rules.get(m.group(1), 0) + 1
    out["falco_event_count"] = len(ev)
    out["falco_rules"] = dict(sorted(rules.items(), key=lambda kv: -kv[1])[:25])

    # 3. KubeArmor alerts
    rc, o, _ = kc(kcfg, ctx, acct, "-n", "kubearmor", "logs", "-l", "kubearmor-app=kubearmor",
                  "--tail=1500", timeout=120)
    ka = [l for l in (o or "").splitlines() if '"Action"' in l or "Block" in l]
    out["kubearmor_alert_count"] = len(ka)
    out["kubearmor_sample"] = ka[-8:]

    # 4. Kubernetes events: the timeline of what they made and broke
    rc, o, _ = kc(kcfg, ctx, acct, "get", "events", "-A", "-o",
        "custom-columns=TS:.lastTimestamp,NS:.involvedObject.namespace,KIND:.involvedObject.kind,"
        "NAME:.involvedObject.name,REASON:.reason,MSG:.message", "--sort-by=.lastTimestamp", timeout=90)
    lines = [l for l in (o or "").splitlines()[1:] if l.strip()]
    out["events_total"] = len(lines)
    interesting = [l for l in lines if re.search(
        r"maintenance-shell|festival-promo|promo-mascot|Failed|Killing|BackOff|Forbidden|Denied|policy", l, re.I)]
    out["events_interesting"] = interesting[-120:]

    # 5. pod health: did the platform break on them
    rc, o, _ = kc(kcfg, ctx, acct, "get", "pods", "-A", "-o",
        "custom-columns=NS:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,"
        "RESTARTS:.status.containerStatuses[0].restartCount", timeout=75)
    bad = [l for l in (o or "").splitlines()[1:]
           if l.strip() and (not re.search(r"\bRunning\b|\bSucceeded\b", l)
                             or re.search(r"\s(\d{2,})$", l))]
    out["unhealthy_pods"] = bad[:40]
    out["status"] = "ok"
    return out

def main():
    rows = json.load(open(OUT / "raw/all-clusters.json"))
    res = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(one, r): r["friendly"] for r in rows}
        for i, f in enumerate(concurrent.futures.as_completed(futs), 1):
            n = futs[f]
            try: r = f.result()
            except Exception as e: r = {"friendly": n, "status": f"EXC {e}"}
            res.append(r)
            print(f"  [{i}/{len(rows)}] {n}: pv={len(r.get('policy_violations') or [])} "
                  f"falco={r.get('falco_event_count')} ka={r.get('kubearmor_alert_count')} "
                  f"ev={r.get('events_total')}", flush=True)
    (OUT / "raw/forensics.json").write_text(json.dumps(res, indent=2, default=str))
    print(f"\nwrote forensics for {len(res)} clusters", flush=True)

if __name__ == "__main__":
    main()
