# ABOUTME: Render-gate check for kube-context safety: no global current-context mutations, demo scripts
# ABOUTME: require an explicit CONTEXT, and the convention is documented for every Claude Code here.
import pathlib, re, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
claude = (REPO / "CLAUDE.md").read_text()
DEMO = [
 "challenges/02-sanitization/toggle-output-guard-on.sh","challenges/02-sanitization/toggle-input-guard-on.sh",
 "challenges/02-sanitization/toggle-input-classifier-on.sh","challenges/01-cncf-wall/toggle-kyverno-enforce.sh",
 "challenges/01-cncf-wall/fallback.kubectl.sh","challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh",
]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("CLAUDE.md documents the kube-context safety rule", "Kube-context safety" in claude and "use-context" in claude)
# No global current-context mutation in any HOST script. The rule targets the shared host
# ~/.kube/config on this multi-tenant box, where another session may be driving another cluster.
#
# A container entrypoint is exempt, but the exemption is EARNED rather than granted by path: it must
# export its own HOME before touching contexts, which is what puts the kubeconfig it writes inside the
# container and out of reach of anything shared. Excluding by directory instead (the previous rule
# covered `images/` only) missed the identical second copy under gitops/ and turned a real check red for
# four days. A path list has to be remembered; this property is visible in the file itself.
hits = []
for f in REPO.rglob("*.sh"):  # actual scripts only; docs may name the prohibition
    if ".git" in str(f):
        continue
    txt = f.read_text()
    if "kubectl config use-context" not in txt:
        continue
    isolated = "export HOME=" in txt and txt.index("export HOME=") < txt.index("kubectl config use-context")
    if not isolated:
        hits.append(str(f.relative_to(REPO)))
check(f"no `kubectl config use-context` outside an isolated container HOME ({', '.join(hits) or 'none'})",
      not hits)
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
