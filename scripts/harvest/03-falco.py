# ABOUTME: Third pass, Falco and Falco-Talon only: the detect-and-respond evidence for Challenge 3, which
# ABOUTME: lives in ns 'security' (falco) and ns 'falco' (talon), not where the second pass looked.
from __future__ import annotations
import os, json, os, subprocess, pathlib, concurrent.futures, re
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / ".harvest" / os.environ.get("WIB_EVENT", "devopsdays-portland")
SCRATCH = pathlib.Path("/tmp/wib-harvest")
def sh(c, env=None, t=120):
    p = subprocess.run(c, capture_output=True, text=True, timeout=t, env={**os.environ, **(env or {})})
    return p.returncode, p.stdout, p.stderr
def one(rec):
    cluster, friendly, acct = rec["cluster"], rec["friendly"], rec.get("account")
    o = {"cluster": cluster, "friendly": friendly}
    if not acct: o["status"]="no account"; return o
    kcfg=str(SCRATCH/f"{cluster}.kubeconfig")
    rc,ctx,_=sh(["kubectl","config","current-context"],env={"KUBECONFIG":kcfg}); ctx=ctx.strip()
    def k(*a,t=150): return sh(["kubectl","--context",ctx,*a],env={"KUBECONFIG":kcfg,"AWS_PROFILE":acct},t=t)
    # Falco lives in ns 'security'
    rc,out,_=k("-n","security","logs","-l","app.kubernetes.io/name=falco","--tail=4000","--all-containers",t=180)
    lines=(out or "").splitlines()
    rules={}
    for l in lines:
        m=re.search(r'"rule"\s*:\s*"([^"]+)"',l) or re.search(r'Rule:\s*([A-Za-z0-9 _-]+)',l)
        if m: r=m.group(1).strip(); rules[r]=rules.get(r,0)+1
    o["falco_lines"]=len(lines)
    o["falco_rules"]=dict(sorted(rules.items(),key=lambda kv:-kv[1])[:30])
    o["falco_recipe_hits"]=sum(1 for l in lines if re.search(r"recipe|snoop|secret[- ]sauce",l,re.I))
    o["falco_sample"]=[l[:400] for l in lines if '"rule"' in l][-10:]
    # Talon responses (it kills the mcp pod)
    rc,out,_=k("-n","falco","logs","-l","app.kubernetes.io/name=falco-talon","--tail=2000","--all-containers",t=150)
    tl=(out or "").splitlines()
    acts=[l for l in tl if re.search(r"action|match|terminate|delete|labelize",l,re.I) and "INF" in l]
    o["talon_lines"]=len(tl)
    o["talon_action_count"]=len([l for l in acts if re.search(r"terminate|delete",l,re.I)])
    o["talon_sample"]=[re.sub(r"\x1b\[[0-9;]*m","",l)[:300] for l in acts[-12:]]
    o["status"]="ok"; return o
def main():
    rows=json.load(open(OUT/"raw/all-clusters.json"))
    res=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs={ex.submit(one,r):r["friendly"] for r in rows}
        for i,f in enumerate(concurrent.futures.as_completed(futs),1):
            n=futs[f]
            try: r=f.result()
            except Exception as e: r={"friendly":n,"status":f"EXC {e}"}
            res.append(r)
            print(f"  [{i}/{len(rows)}] {n}: falco_lines={r.get('falco_lines')} "
                  f"rules={len(r.get('falco_rules') or {})} recipe={r.get('falco_recipe_hits')} "
                  f"talon_actions={r.get('talon_action_count')}",flush=True)
    (OUT/"raw/falco.json").write_text(json.dumps(res,indent=2,default=str))
    print(f"\nwrote falco/talon forensics for {len(res)} clusters",flush=True)
main()
