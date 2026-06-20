# ABOUTME: Render-gate check for the Namecheap demo-DNS tool: reads creds from env (not hardcoded),
# ABOUTME: dry-run is the default (mutation only with --apply), URL scheme documented. No network.
import importlib.util, pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
src = (REPO / "infra/dns/set-demo-dns.py").read_text()
readme = (REPO / "infra/dns/README.md").read_text()
spec = importlib.util.spec_from_file_location("set_demo_dns", REPO / "infra/dns/set-demo-dns.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # safe: main() only on __main__
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("credentials read from the env file (not hardcoded)", 'load_env' in dir(mod) and "namecheap.env" in src)
check("no hardcoded long secret literal", not any(len(w) >= 25 and w.isalnum() for w in src.split('"')))
check("mutation gated behind --apply (dry-run default)", 'action="store_true"' in src and "if not args.apply" in src)
check("merge preserves non-matching existing records", "not (r[\"Type\"] == \"CNAME\" and r[\"Name\"] in wanted)" in src)
check("targets agenticburn.com", 'DOMAIN = "agenticburn.com"' in src)
check("README documents the demo URL scheme", all(s in readme for s in ("burn.agenticburn.com", "wall.agenticburn.com", "haiku.agenticburn.com")))
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll DNS-tool checks passed.")
