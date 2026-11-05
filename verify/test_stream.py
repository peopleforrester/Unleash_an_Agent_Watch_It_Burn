# ABOUTME: Render-gate check for the optional prompt-stream display: capture is moderated + default OFF,
# ABOUTME: and the display page reads the moderated /prompts feed and hides masked prompts (#915). No cluster needed.
import importlib.util, pathlib, re, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gp_stream", REPO / "gitops/ai-layer/guard-proxy/proxy.py")
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

# #915: a prompt the feed masked is left off /display whole. The behaviour (display.js run in node against feeds
# built by moderate()) is test_display_masked_prompts_e2e.py in the tools tier; these hold the pieces offline.
feed_go = (REPO / "gitops/ai-layer/guard-proxy/internal/feed/feed.go").read_text()
go_mask = re.search(r'^\s*redacted\s*=\s*"([^"]+)"', feed_go, re.M)
js_mask = re.search(r'var MASK = "([^"]+)";', disp_js)
check("feed.go still names its mask (redacted = \"...\")", go_mask is not None)
check("display.js names the mask it hides (var MASK = \"...\";)", js_mask is not None)
py_mask = "[redacted]" if "[redacted]" in proxy.moderate("Go fuck yourself.") else None
check("display.js hides the mask both guard-proxies write",
      js_mask is not None and go_mask is not None and js_mask.group(1) == go_mask.group(1) == py_mask)
check("display.js matches the mask in any case", "String(p).toLowerCase().indexOf(MASK) === -1" in disp_js)
# #927 put a holding slot between the feed and the screen; a prompt enters it, or the first snapshot, only filtered.
check("display.js filters the first snapshot before it renders a row",
      re.search(r"rows = feed\.filter\(shown\)", disp_js) is not None)
check("display.js filters each new arrival before it is held or counted",
      re.search(r"newEntries\(last, feed\)\.filter\(shown\)\.forEach\(", disp_js) is not None)
# #927: the card interval is one named constant, 1.5 s, which the card tick runs on (the fake-clock behaviour is
# test_display_throttle_e2e.py in the tools tier).
check("display.js names its card interval (var CARD_INTERVAL_MS = 1500;)", "var CARD_INTERVAL_MS = 1500;" in disp_js)
check("display.js ticks cards on CARD_INTERVAL_MS", "setInterval(tick, CARD_INTERVAL_MS)" in disp_js)
check("display page carries the +N more count", 'id="more"' in disp_html)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll prompt-stream checks passed.")
