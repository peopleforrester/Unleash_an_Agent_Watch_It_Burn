# ABOUTME: Turns the raw per-cluster harvest into a behavioural report: engagement funnel, challenge
# ABOUTME: completion, terminal patterns and attack-prompt taxonomy. Aggregate only, no per-person calling out.
from __future__ import annotations
import os, json, pathlib, re, collections, statistics

OUT = pathlib.Path(".harvest") / os.environ.get("WIB_EVENT", "devopsdays-portland")
rows = json.load(open(OUT / "raw/all-clusters.json"))
students = [r for r in rows if r.get("slot")]
attackme = next((r for r in rows if r["friendly"] == "attackme"), None)

def cost(r, k): return (r.get("cost") or {}).get(k) or 0
def ctrl(r, group, k): return ((r.get("controls") or {}).get(group) or {}).get(k)

active = [r for r in students if cost(r, "requests") > 0]
touched_term = [r for r in students if (r.get("terminal_lines") or 0) > 0]

L = []
def w(s=""): L.append(s)

w("# DevOpsDays Portland 2026: what attendees actually did")
w()
w(f"Harvested {len(rows)} clusters ({len(students)} student + AttackMe) live, before teardown.")
w("Aggregate behaviour only. E-mail addresses scrubbed; no cluster is named against a person.")
w()

w("## Engagement funnel")
w()
w("| Stage | Clusters | of 50 |")
w("|---|---|---|")
w(f"| Provisioned | 50 | 100% |")
w(f"| Sent at least one message to BurritoBot | {len(active)} | {len(active)*100//50}% |")
w(f"| Opened the terminal and ran something | {len(touched_term)} | {len(touched_term)*100//50}% |")
for thresh, label in ((10, "10+ messages"), (50, "50+ messages"), (100, "100+ messages")):
    n = len([r for r in students if cost(r, "requests") >= thresh])
    w(f"| {label} | {n} | {n*100//50}% |")
w()
reqs = sorted([cost(r, "requests") for r in active], reverse=True)
if reqs:
    w(f"Messages per active cluster: median **{statistics.median(reqs):.0f}**, "
      f"mean {statistics.mean(reqs):.0f}, max **{max(reqs)}**, min {min(reqs)}.")
    w()

w("## Did the workshop function for them?")
w()
w("Read off live cluster state and the `/controls` endpoint, which records which guardrails were installed.")
w()
w("| Challenge | Signal | Clusters |")
w("|---|---|---|")
c6 = len([r for r in students if (r.get("challenges") or {}).get("c6_maintenance_shell_exists")])
villain = len([r for r in students if any("festival-promo" in d for d in (r.get("challenges") or {}).get("c2_villain_deploys", []))])
fixes = {
    "C1 NetworkPolicy": ("networkpolicy", "infra"),
    "C2 Kyverno Enforce": ("kyverno", "infra"),
    "C3 KubeArmor": ("kubearmor", "infra"),
    "C4 budget guard": ("budget", "ai"),
    "C5 output guard": ("output", "ai"),
    "C6 input blocklist": ("input_blocklist", "ai"),
    "C6 input classifier": ("input_classifier", "ai"),
    "C7 tool allowlist": ("tool_allowlist", "infra"),
    "C8 RBAC scoped": ("rbac_scoped", "infra"),
}
w(f"| C2 attack | villain image `festival-promo` deployed | **{villain}** |")
w(f"| C6 attack | `maintenance-shell` Deployment created | **{c6}** |")
for label, (k, g) in fixes.items():
    n = len([r for r in students if ctrl(r, g, k) is True])
    w(f"| {label} | guardrail installed | **{n}** |")
w()
anyfix = len([r for r in students if any(ctrl(r, g, k) is True for k, g in fixes.values())])
w(f"**{anyfix} clusters installed at least one guardrail** (i.e. completed the fix half of a challenge).")
w()

w("## What they did in the terminal")
w()
allcmds = []
for r in students:
    for line in (r.get("terminal_history") or "").splitlines():
        line = line.strip()
        if line: allcmds.append(line)
w(f"{len(allcmds)} commands across {len(touched_term)} clusters "
  f"(median {statistics.median([r['terminal_lines'] for r in touched_term]):.0f} per cluster).")
w()
verbs = collections.Counter()
for c in allcmds:
    t = c.split()
    if t: verbs[t[0]] += 1
w("**Most-run commands (first word):**")
w()
w("| Command | Times |")
w("|---|---|")
for v, n in verbs.most_common(12): w(f"| `{v}` | {n} |")
w()
pats = {
    "read AWS credentials": r"\.aws/credentials|aws sts|get-caller-identity",
    "list secrets": r"get secrets?|get secret ",
    "impersonate the agent SA": r"--as=system:serviceaccount",
    "read the service-account token": r"serviceaccount/token",
    "hunt the recipe on disk": r"recipe|secret-sauce",
    "check maintenance-shell": r"maintenance-shell",
    "look at Falco / logs": r"falco|logs ",
    "poke kyverno": r"clusterpolicy|kyverno",
}
w("**Behaviours seen in terminal history:**")
w()
w("| Behaviour | Clusters |")
w("|---|---|")
for label, rx in pats.items():
    n = len([r for r in students if re.search(rx, r.get("terminal_history") or "", re.I)])
    w(f"| {label} | {n} |")
w()

w("## What they said to BurritoBot")
w()
tot = 0; convos = []
for r in students:
    p = OUT / f"prompts/{r['friendly']}.json"
    if not p.exists(): continue
    seen = set()
    for x in json.load(open(p)):
        for u in x.get("user") or []:
            u = u[len("user: "):] if u.startswith("user: ") else u
            if u in seen: continue
            seen.add(u); convos.append(u); tot += 1
n_pfiles = len([r for r in students if (OUT / f"prompts/{r['friendly']}.json").exists()])
w(f"**{tot} distinct user messages** captured across {n_pfiles} clusters.")
w()
tax = {
    "exfiltrate to a webhook (C1)": r"webhook|beacon|POST it|intake|agenticburn\.com/beacon",
    "authority / pretexting": r"\bCEO\b|ticket|HC-\d|CHG-\d|manager|authorized|compliance|audit",
    "run a shell command": r"bash -c|run_shell|/bin/sh|cat /|curl ",
    "ask for secrets directly": r"secret|credential|token|password|api[_ ]?key",
    "the planted recipe (C3)": r"recipe|secret[- ]sauce|WITCH-HAZEL",
    "deploy something (C6)": r"deployment|deploy |maintenance-shell|alpine",
    "ignore-previous-instructions": r"ignore (all )?previous|disregard your|maintenance mode",
    "role-play / persona": r"you are now|pretend|act as|roleplay",
    "denial-of-wallet (C4)": r"origin story|every single protein|in full detail|paragraph on each",
}
w("**Attack techniques attempted** (a message can match more than one):")
w()
w("| Technique | Messages | % |")
w("|---|---|---|")
for label, rx in sorted(tax.items(), key=lambda kv: -len([c for c in convos if re.search(kv[1], c, re.I)])):
    n = len([c for c in convos if re.search(rx, c, re.I)])
    w(f"| {label} | {n} | {n*100//max(tot,1)}% |")
w()
refus = len([c for c in convos if False])
w("## AttackMe (the shared community cluster)")
w()
if attackme:
    w(f"- **{cost(attackme,'requests')} requests**, {cost(attackme,'input_tokens'):,} input tokens, "
      f"${cost(attackme,'usd'):.2f}")
    w(f"- **{attackme.get('prompt_spans')} prompt spans** captured, the single busiest target of the day")
w()
w("## Telemetry gaps found during the harvest")
w()
gaps = [r for r in students if cost(r, "requests") > 0 and (r.get("prompt_spans") or 0) == 0]
w(f"{len(gaps)} clusters had real traffic but **no conversation content in Datadog** "
  "(only `burritobot-gateway` spans, which carry no `gen_ai` attributes):")
for r in gaps: w(f"- `{r['friendly']}`: {cost(r,'requests')} requests, 0 prompts recoverable")
w()
w("Their guard-proxy pod logs were empty too, so those conversations are unrecoverable. "
  "This is issue #382 in its most damaging form: when the proxy-side span is missing, the prompt "
  "text is gone, not merely hard to find.")
w()
(OUT / "SUMMARY.md").write_text("\n".join(L))
print("\n".join(L))
