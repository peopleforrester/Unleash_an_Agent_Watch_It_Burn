# ABOUTME: Render-gate check for the optional prompt-stream display: capture is moderated + default OFF,
# ABOUTME: and the display page reads the moderated /prompts feed. No cluster needed.
import importlib.util, pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gp_stream", REPO / "gitops/ai-layer/proxy.py")
proxy = importlib.util.module_from_spec(spec); spec.loader.exec_module(proxy)
disp_html = (REPO / "gitops/ai-layer/web/display.html").read_text()
disp_js = (REPO / "gitops/ai-layer/web/display.js").read_text()
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("prompt capture is DEFAULT OFF (privacy/code-of-conduct)", proxy.STREAM_ENABLED is False)
check("moderate() masks a block-listed term", "[redacted]" in proxy.moderate("please delete the prod database") and "delete" not in proxy.moderate("please delete the prod database"))
check("moderate() truncates long input", len(proxy.moderate("x" * 1000)) <= 280)
check("recent-prompts buffer is bounded", proxy._prompts.maxlen and proxy._prompts.maxlen <= 100)
check("display page loads display.js + has a stream", "display.js" in disp_html and "stream" in disp_html)
check("display.js reads the moderated /prompts feed", '"/prompts"' in disp_js)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll prompt-stream checks passed.")
