# ABOUTME: Render-gate check for kube-context safety: no global current-context mutations, demo scripts
# ABOUTME: require an explicit CONTEXT, and the convention is documented for every Claude Code here.
import pathlib, re, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
claude = (REPO / "CLAUDE.md").read_text()
DEMO = [
 "beats/02-sanitization/toggle-output-guard-on.sh","beats/02-sanitization/toggle-input-guard-on.sh",
 "beats/02-sanitization/toggle-input-classifier-on.sh","beats/01-cncf-wall/toggle-kyverno-enforce.sh",
 "beats/01-cncf-wall/fallback.kubectl.sh","beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh",
]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("CLAUDE.md documents the kube-context safety rule", "Kube-context safety" in claude and "use-context" in claude)
# No global current-context mutation in any HOST script. The rule targets the shared host
# ~/.kube/config on this multi-tenant box; container entrypoints under images/ run with an isolated
# in-container HOME and cannot touch shared host state, so they are out of this rule's scope.
hits = []
for f in REPO.rglob("*.sh"):  # actual scripts only; docs may name the prohibition
    if ".git" in str(f) or "/images/" in str(f).replace("\\", "/"):
        continue
    if "kubectl config use-context" in f.read_text():
        hits.append(f.name)
check("no `kubectl config use-context` in any host script", not hits)
# Every demo script requires CONTEXT and routes kubectl through --context.
for s in DEMO:
    txt = (REPO / s).read_text()
    ok = 'CONTEXT:?' in txt and '--context "${CONTEXT}"' in txt
    bare = bool(re.search(r'(^|if |then |&& |\|\| )kubectl ', txt, re.M)) and "command -v kubectl" in txt
    # bare allowed only for the `command -v kubectl` probe
    bad = [l for l in txt.splitlines() if re.search(r'(^|if |then |&& |\|\| )kubectl ', l) and "command -v" not in l]
    check(f"requires CONTEXT + no bare kubectl: {pathlib.Path(s).name}", ok and not bad)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll kube-context-safety checks passed.")
