# ABOUTME: Fourth pass: ArgoCD application sync history per surviving cluster (dies at teardown) and the
# ABOUTME: per-org Datadog metric series, exported for post-event analysis.
from __future__ import annotations
import os, json,os,subprocess,pathlib,concurrent.futures,urllib.request,time
REPO=pathlib.Path(__file__).resolve().parent.parent
OUT=REPO/".harvest"/os.environ.get("WIB_EVENT","devopsdays-portland"); SCRATCH=pathlib.Path(os.environ.get("WIB_SCRATCH","/tmp/wib-harvest"))
def sh(c,env=None,t=120):
    p=subprocess.run(c,capture_output=True,text=True,timeout=t,env={**os.environ,**(env or {})})
    return p.returncode,p.stdout,p.stderr
def argo(rec):
    cl,fr,acct=rec["cluster"],rec["friendly"],rec.get("account")
    o={"cluster":cl,"friendly":fr}
    if not acct: o["status"]="no account"; return o
    kcfg=str(SCRATCH/f"{cl}.kubeconfig")
    rc,ctx,_=sh(["kubectl","config","current-context"],env={"KUBECONFIG":kcfg}); ctx=ctx.strip()
    rc,out,_=sh(["kubectl","--context",ctx,"-n","argocd","get","applications","-o","json"],
                env={"KUBECONFIG":kcfg,"AWS_PROFILE":acct},t=120)
    if rc!=0: o["status"]="gone (destroyed?)"; return o
    apps=[]
    try:
        for a in json.loads(out).get("items",[]):
            st=a.get("status",{}) or {}
            hist=st.get("history") or []
            apps.append({"name":a["metadata"]["name"],
                         "sync":(st.get("sync") or {}).get("status"),
                         "health":(st.get("health") or {}).get("status"),
                         "revisions":len(hist),
                         "last_deploy":(hist[-1].get("deployedAt") if hist else None),
                         "conditions":[c.get("type") for c in (st.get("conditions") or [])]})
    except Exception as e: o["parse_error"]=str(e)
    o["apps"]=apps
    o["total_revisions"]=sum(a["revisions"] for a in apps)
    o["out_of_sync"]=[a["name"] for a in apps if a["sync"] not in (None,"Synced")]
    o["degraded"]=[a["name"] for a in apps if a["health"] not in (None,"Healthy")]
    o["status"]="ok"; return o
def dd_metrics(org):
    """Per-org metric inventory + the workshop's own cost series."""
    hdr={"DD-API-KEY":org["api-key"],"DD-APPLICATION-KEY":org["app-key"]}
    res={"org":org["org"]}
    try:
        now=int(time.time()); frm=now-12*3600
        req=urllib.request.Request(f"https://api.datadoghq.com/api/v1/metrics?from={frm}",headers=hdr)
        j=json.load(urllib.request.urlopen(req,timeout=45))
        names=j.get("metrics") or []
        res["metric_count"]=len(names)
        res["witb_metrics"]=[m for m in names if "witb" in m or "burrito" in m or "gen_ai" in m][:40]
        series={}
        for m in res["witb_metrics"][:8]:
            q=urllib.request.quote(f"avg:{m}{{*}}")
            r2=urllib.request.Request(f"https://api.datadoghq.com/api/v1/query?from={frm}&to={now}&query={q}",headers=hdr)
            try:
                jj=json.load(urllib.request.urlopen(r2,timeout=45))
                pts=[p for s in (jj.get("series") or []) for p in (s.get("pointlist") or [])]
                series[m]={"points":len(pts),"last":pts[-1] if pts else None}
            except Exception as e: series[m]={"error":str(e)[:80]}
        res["series"]=series
    except Exception as e: res["error"]=str(e)[:200]
    return res
def main():
    rows=json.load(open(OUT/"raw/all-clusters.json"))
    out=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs={ex.submit(argo,r):r["friendly"] for r in rows}
        for i,f in enumerate(concurrent.futures.as_completed(futs),1):
            n=futs[f]
            try: r=f.result()
            except Exception as e: r={"friendly":n,"status":f"EXC {e}"}
            out.append(r)
            print(f"  argo [{i}/{len(rows)}] {n}: {r.get('status')} apps={len(r.get('apps') or [])} "
                  f"revs={r.get('total_revisions')} oos={len(r.get('out_of_sync') or [])}",flush=True)
    (OUT/"raw/argocd.json").write_text(json.dumps(out,indent=2,default=str))
    # datadog metrics: the admin org plus a sample of student orgs
    pool=[]
    for s in ("watch-it-burn/datadog-pool","watch-it-burn/datadog-pool-2"):
        rc,o,_=sh(["aws","secretsmanager","get-secret-value","--secret-id",s,"--region","us-west-2",
                   "--query","SecretString","--output","text"],env={"AWS_PROFILE":"accen-dev"},t=60)
        try:
            d=json.loads(o)
            if isinstance(d,list): pool+=d
        except Exception: pass
    used={r.get("datadog_org") for r in rows if r.get("datadog_org")}
    targets=[o for o in pool if o["org"] in used or o["org"].endswith("-001")]
    mets=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(dd_metrics,targets):
            mets.append(r); print(f"  dd {r['org']}: metrics={r.get('metric_count')} witb={len(r.get('witb_metrics') or [])}",flush=True)
    (OUT/"raw/datadog-metrics.json").write_text(json.dumps(mets,indent=2,default=str))
    print(f"\nwrote argocd.json ({len(out)}) and datadog-metrics.json ({len(mets)})",flush=True)
main()
