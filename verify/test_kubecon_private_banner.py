# ABOUTME: Holds /kubecon's private (administrator) banner in the page source: the sentence, hidden by default inside
# ABOUTME: <main>, the chat page's .combanner style values, and a script that shows it only on burritobot-private. (#1181).
"""The offline half of #1181. verify/test_kubecon_private_banner_e2e.py (tools tier) renders the page on each host;
this reads the committed source, so a change to the banner's words, style or host rule fails here without a browser.
The style values are read against the chat page's own .combanner rule (gitops/ai-layer/web/burritbot.html, #761), so
the two banners cannot drift apart.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
CHAT = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
BANNER = "This is the private (administrator) KubeCon page."
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def rule(src: str, where: str) -> dict[str, str]:
    m = re.search(r"\.combanner\{([^}]*)\}", src)
    if not m:
        print(f"FAILED: no .combanner{{...}} rule in {where}")
        sys.exit(1)
    return {k.strip(): v.strip() for k, v in (d.split(":", 1) for d in m.group(1).split(";") if d.strip())}


page_rule, chat_rule = rule(PAGE, "kubecon.html"), rule(CHAT, "burritbot.html")

print("== the banner's markup ==")
div = re.search(r'<div id="privatebanner" class="combanner"( hidden)?>([^<]*)</div>', PAGE)
check("kubecon.html has a #privatebanner div with the .combanner class", div is not None)
check("it reads the issue's sentence", bool(div) and div.group(2) == BANNER, div.group(2) if div else "")
check("it starts hidden, so a host the script does not name never shows it", bool(div) and bool(div.group(1)))
main = PAGE.find("<main>"), PAGE.find("</main>")
check("it sits inside <main>, which the prompt sheet hides (#689)",
      bool(div) and main[0] < div.start() < main[1], str((main, div.start() if div else None)))
check("the page has one banner", PAGE.count('id="privatebanner"') == 1)

print("== the .combanner look: bold white on #C62222, #8E1414 border, rounded corners ==")
check("bold (800)", page_rule.get("font-weight") == "800", str(page_rule))
check("white text", page_rule.get("color") == "#fff", str(page_rule))
check("#C62222 background", page_rule.get("background") == "#C62222", str(page_rule))
check("a 1px solid #8E1414 border", page_rule.get("border") == "1px solid #8E1414", str(page_rule))
check("rounded corners", page_rule.get("border-radius") == "10px", str(page_rule))
check("the rule is the chat page's .combanner, value for value", page_rule == chat_rule,
      f"kubecon {page_rule} chat {chat_rule}")
check("no display set on it, so the hidden attribute hides it", "display" not in page_rule)

print("== the host decides at load time ==")
script = PAGE[PAGE.rfind("<script>"):PAGE.rfind("</script>")]
block = re.search(r"getElementById\('privatebanner'\).*?\}\)\(\);", script, re.S)
check("the page's script reads #privatebanner", block is not None)
body = block.group(0) if block else ""
check("it tests location.hostname against ^burritobot-private\\.",
      r"/^burritobot-private\./.test(location.hostname)" in body, body)
check("and sets hidden from that test, so every other host stays hidden",
      r"ban.hidden=!/^burritobot-private\./.test(location.hostname)" in body, body)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("/kubecon carries the private banner, in the chat page's look, for burritobot-private. alone.")
