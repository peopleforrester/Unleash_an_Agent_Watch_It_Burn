# ABOUTME: Post-event behavioural harvest: pulls per-cluster usage, challenge completion, terminal history
# ABOUTME: and prompt text from every workshop cluster before teardown, for pattern analysis (no PII goal).
from __future__ import annotations
import os, json, os, re, subprocess, sys, urllib.request, concurrent.futures, pathlib, base64, datetime

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / ".harvest" / os.environ.get("WIB_EVENT", "devopsdays-portland")
SCRATCH = pathlib.Path(os.environ.get("WIB_SCRATCH", "/tmp/wib-harvest")); SCRATCH.mkdir(parents=True, exist_ok=True)
ACCOUNTS = ["accen-dev", "aws1-student31", "aws1-student32", "aws1-student33", "aws1-student34"]
REGION = "us-west-2"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

def sh(cmd, env=None, timeout=90):
    e = {**os.environ, **(env or {})}
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)
    return p.returncode, p.stdout, p.stderr

def friendly_names():
    rc, out, _ = sh(["bash", "-c",
        f'cd {REPO}/infra/terraform/fleet && source ./fleet.sh >/dev/null 2>&1; '
        'for n in $(seq 1 50); do echo "$n $(friendly_attendee_name $n)"; done'])
    m = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 2: m[int(p[0])] = p[1]
    return m

def find_account(cluster):
    for a in ACCOUNTS:
        rc, _, _ = sh(["aws", "eks", "describe-cluster", "--name", cluster, "--region", REGION],
                      env={"AWS_PROFILE": a}, timeout=60)
        if rc == 0: return a
    return None

def kubeconfig(cluster, acct):
    kc = SCRATCH / f"{cluster}.kubeconfig"
    if not kc.exists():
        sh(["aws", "eks", "update-kubeconfig", "--kubeconfig", str(kc), "--name", cluster,
            "--region", REGION], env={"AWS_PROFILE": acct}, timeout=90)
    rc, out, _ = sh(["kubectl", "config", "current-context"], env={"KUBECONFIG": str(kc)})
    return str(kc), out.strip()

def kc(kcfg, ctx, acct, *args, timeout=60):
    return sh(["kubectl", "--context", ctx, *args],
              env={"KUBECONFIG": kcfg, "AWS_PROFILE": acct}, timeout=timeout)

def http(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r: return json.load(r)
    except Exception: return None

def scrub(t):
    """Behavioural analysis only: drop e-mail addresses, keep everything else verbatim."""
    return EMAIL_RE.sub("<email>", t or "")

def dd_spans(api, app, hours=12, limit=1000):
    rows, cur, pages = [], None, 0
    while pages < 8:
        attrs = {"filter": {"from": f"now-{hours}h", "to": "now", "query": "*"},
                 "page": {"limit": limit}, "sort": "-timestamp"}
        if cur: attrs["page"]["cursor"] = cur
        body = json.dumps({"data": {"type": "search_request", "attributes": attrs}}).encode()
        req = urllib.request.Request("https://api.datadoghq.com/api/v2/spans/events/search", data=body,
            headers={"DD-API-KEY": api, "DD-APPLICATION-KEY": app, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: j = json.load(r)
        except Exception: break
        if "errors" in j: break
        d = j.get("data", []); rows += d; pages += 1
        cur = (j.get("meta", {}).get("page", {}) or {}).get("after")
        if not cur or not d: break
    return rows

def harvest(n, friendly, pool_by_key):
    cluster = f"watch-it-burn-attendee-{n:03d}" if isinstance(n, int) else n
    rec = {"slot": n if isinstance(n, int) else None, "cluster": cluster, "friendly": friendly}
    acct = find_account(cluster)
    rec["account"] = acct
    if not acct:
        rec["status"] = "cluster not found"; return rec
    kcfg, ctx = kubeconfig(cluster, acct)
    host = friendly

    rec["cost"] = http(f"https://{host}.agenticburn.com/cost")
    rec["controls"] = http(f"https://{host}.agenticburn.com/controls")

    # --- challenge completion markers, read off live cluster state ---
    ch = {}
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "agent", "get", "networkpolicy", "-o", "name")
    ch["c1_networkpolicies_installed"] = len([l for l in out.splitlines() if l.strip()])
    rc, out, _ = kc(kcfg, ctx, acct, "get", "clusterpolicy", "restrict-image-registries",
                    "-o", "jsonpath={.spec.rules[0].validate.failureAction}{.spec.validationFailureAction}")
    ch["c2_kyverno_mode"] = out.strip() or ("absent" if rc else "")
    rc, out, _ = kc(kcfg, ctx, acct, "get", "deploy", "-A", "-o",
                    "jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.template.spec.containers[*].image}{\"\\n\"}{end}")
    deploys = [l for l in out.splitlines() if l.strip()]
    ch["c2_villain_deploys"] = [d for d in deploys if any(v in d.lower() for v in
                               ("villain", "malicious", "evil", "docker.io", "nginx", "busybox", "alpine"))][:12]
    rc, out, _ = kc(kcfg, ctx, acct, "get", "kubearmorpolicy", "-A", "-o", "name")
    ch["c3_kubearmor_policies"] = len([l for l in out.splitlines() if l.strip()])
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "agent", "get", "deploy", "maintenance-shell", "-o", "name")
    ch["c6_maintenance_shell_exists"] = (rc == 0 and "maintenance-shell" in out)
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "agent", "get", "agent", "-o",
                    "jsonpath={range .items[*]}{.metadata.name}={.spec.declarative.tools[*].toolNames}{\"\\n\"}{end}")
    ch["c7_agent_toolnames"] = out.strip()[:400]
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "agent", "get", "role", "workshop-agent", "-o",
                    "jsonpath={.rules}")
    ch["c8_role_rules"] = out.strip()[:600]
    ch["c8_scoped"] = "resourceNames" in out
    rec["challenges"] = ch

    # --- terminal history (behavioural: what commands did they actually run) ---
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "agent", "exec", "deploy/web-terminal", "--",
                    "sh", "-c", "cat ~/.bash_history 2>/dev/null", timeout=60)
    rec["terminal_history"] = scrub(out) if rc == 0 else ""
    rec["terminal_lines"] = len([l for l in (out or "").splitlines() if l.strip()])

    # --- prompts, from this cluster's OWN datadog org ---
    rc, out, _ = kc(kcfg, ctx, acct, "-n", "monitoring", "get", "secret", "datadog-secret",
                    "-o", "jsonpath={.data.api-key}")
    prompts = []
    org = None
    if rc == 0 and out.strip():
        try: key = base64.b64decode(out.strip()).decode().strip()
        except Exception: key = ""
        o = pool_by_key.get(key)
        if o:
            org = o["org"]
            for s in dd_spans(o["api-key"], o["app-key"]):
                a = s.get("attributes", {}) or {}
                cu = a.get("custom", {}) or {}
                g = cu.get("gen_ai") or {}
                if not isinstance(g, dict): continue
                inp = (g.get("input") or {}).get("messages")
                outp = (g.get("output") or {}).get("messages")
                if not inp and not outp: continue
                def texts(blob):
                    """messages arrive as a JSON STRING of [{role, parts:[{type,content}]}]."""
                    try: msgs = json.loads(blob) if isinstance(blob, str) else blob
                    except Exception: return [str(blob)[:4000]]
                    out = []
                    for m in msgs or []:
                        if not isinstance(m, dict): continue
                        for part in m.get("parts") or []:
                            c = part.get("content")
                            if c: out.append(f"{m.get('role','?')}: {c}")
                    return out
                prompts.append({
                    "ts": a.get("start_timestamp") or a.get("timestamp"),
                    "service": a.get("service"),
                    "resource": a.get("resource_name"),
                    "duration_ns": a.get("duration"),
                    "user": [scrub(t) for t in texts(inp)],
                    "assistant": [scrub(t) for t in texts(outp)],
                    "tools": [k for k in g.keys() if "tool" in k.lower()],
                })
    rec["datadog_org"] = org
    rec["prompt_spans"] = len(prompts)
    rec["_prompts"] = prompts
    rec["status"] = "ok"
    return rec

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for d in ("per-cluster", "prompts", "terminal", "raw"): (OUT / d).mkdir(exist_ok=True)
    # datadog pool
    pool = []
    for s in ("watch-it-burn/datadog-pool", "watch-it-burn/datadog-pool-2"):
        rc, out, _ = sh(["aws", "secretsmanager", "get-secret-value", "--secret-id", s,
                         "--region", REGION, "--query", "SecretString", "--output", "text"],
                        env={"AWS_PROFILE": "accen-dev"}, timeout=60)
        try:
            d = json.loads(out)
            if isinstance(d, list): pool += d
        except Exception: pass
    pool_by_key = {o["api-key"]: o for o in pool}
    print(f"pool orgs: {len(pool)}", flush=True)

    names = friendly_names()
    targets = [(n, names[n]) for n in sorted(names)]
    targets.append(("watch-it-burn-community", "attackme"))
    print(f"targets: {len(targets)}", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(harvest, n, f, pool_by_key): (n, f) for n, f in targets}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            n, f = futs[fut]
            try: r = fut.result()
            except Exception as e: r = {"cluster": str(n), "friendly": f, "status": f"EXC {e}"}
            results.append(r)
            print(f"  [{i}/{len(targets)}] {f}: {r.get('status')}  "
                  f"req={(r.get('cost') or {}).get('requests')} "
                  f"term={r.get('terminal_lines')} prompts={r.get('prompt_spans')}", flush=True)

    for r in results:
        f = r.get("friendly") or r.get("cluster")
        pr = r.pop("_prompts", [])
        (OUT / "per-cluster" / f"{f}.json").write_text(json.dumps(r, indent=2, default=str))
        if pr: (OUT / "prompts" / f"{f}.json").write_text(json.dumps(pr, indent=2, default=str))
        if r.get("terminal_history"): (OUT / "terminal" / f"{f}.txt").write_text(r["terminal_history"])
    (OUT / "raw" / "all-clusters.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {len(results)} cluster records to {OUT}", flush=True)

if __name__ == "__main__":
    main()
