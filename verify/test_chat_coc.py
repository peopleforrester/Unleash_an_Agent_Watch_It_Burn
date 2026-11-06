# ABOUTME: Offline half of the chat page's code-of-conduct check (#947): burritbot.html's COC_TERMS is guard-proxy's
# ABOUTME: PROFANITY list in both its builds, the deployed proxy sets no override, and cocViolation stays pure.
"""The executed half is verify/test_chat_coc_e2e.py, which runs the page's cocViolation in node against the pinned
proxy.py's _PROFANITY_RE and moderate() on every assigned code point. This half needs no node: it reads the page's
one term literal and compares it, term for term, with proxy.py's PROFANITY (imported with PROFANITY_LIST unset) and
the Go build's DefaultProfanity, and checks resources.yaml sets no PROFANITY_LIST, so the default is the list the
wall masks. It also checks the function touches nothing but its argument.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
GP = REPO / "gitops/ai-layer/guard-proxy"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


for f in (PAGE_PATH, GP / "proxy.py", GP / "internal/config/config.go"):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing (for guard-proxy, run verify/ensure-submodules.sh)")
        sys.exit(1)

os.environ.pop("PROFANITY_LIST", None)
spec = importlib.util.spec_from_file_location("gp_chat_coc_offline", GP / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

page = PAGE_PATH.read_text(encoding="utf-8")
literals = re.findall(r"const COC_TERMS='([^']*)';", page)
check("burritbot.html holds one COC_TERMS literal", len(literals) == 1, f"found {len(literals)}")
if len(literals) != 1:
    print("FAIL: no single const COC_TERMS='...'; literal to compare")
    sys.exit(1)
terms = literals[0].split(",")
check("COC_TERMS is lower case with no spaces or empty terms",
      all(t and t == t.strip().lower() for t in terms), f"{terms}")
check("COC_TERMS is proxy.py's PROFANITY, term for term", sorted(terms) == sorted(proxy.PROFANITY),
      f"page only: {sorted(set(terms) - set(proxy.PROFANITY))}; proxy only: {sorted(set(proxy.PROFANITY) - set(terms))}")

go = (GP / "internal/config/config.go").read_text(encoding="utf-8")
m = re.search(r"const DefaultProfanity = ((?:\"[^\"]*\"\s*\+?\s*)+)", go)
check("the Go build still names const DefaultProfanity", m is not None)
if m:
    go_terms = "".join(re.findall(r'"([^"]*)"', m.group(1))).split(",")
    check("COC_TERMS is the Go build's DefaultProfanity, term for term", sorted(terms) == sorted(go_terms),
          f"page only: {sorted(set(terms) - set(go_terms))}; Go only: {sorted(set(go_terms) - set(terms))}")

resources = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
check("resources.yaml sets no PROFANITY_LIST, so guard-proxy masks its default list",
      not re.search(r"name:\s*PROFANITY_LIST\b", resources))

defs = re.findall(r"function cocViolation\(", page)
check("burritbot.html defines cocViolation once", len(defs) == 1, f"found {len(defs)}")
fn = re.search(r"function cocViolation\((\w+)\)\{([^\n]*)\}\n", page)
check("cocViolation is one line taking one argument", fn is not None)
if fn:
    body = fn.group(2)
    check("cocViolation only tests its argument against COC_RE",
          "COC_RE.test(" in body and not re.search(r"document|window|localStorage|sessionStorage|fetch|save\(", body),
          body)
re_line = page[page.find("const COC_RE="):page.find("function cocViolation(")]
check("COC_RE is built from COC_TERMS without the i flag (letters are folded by cocLetter)",
      "COC_TERMS.split(','" in re_line and re_line.rstrip().endswith("'u');"), re_line[-80:])
check("COC_RE's word edges are Unicode letters, digits and underscore, not \\b",
      re_line.count("[\\\\p{L}\\\\p{N}_]") == 2 and "\\\\b" not in re_line, re_line)

# #948 wires the check into the saved list; verify/test_chat_saved_coc_e2e.py runs it, these hold its shape offline.
check("save() returns before it renders or stores a prompt cocViolation flags",
      page.count("function save(t){if(cocViolation(t))return;") == 1)
check("burritbot.html defines loadSaved once", len(re.findall(r"function loadSaved\(", page)) == 1)
ld = page[page.find("function loadSaved("):page.find("function save(")]
check("loadSaved drops entries cocViolation flags and writes the pruned list back to wib-saved",
      "cocViolation(" in ld and "localStorage.setItem('wib-saved'" in ld and "forEach(renderSaved)" in ld, ld[:200])
init = page[page.find("(function init(){"):]
init = init[:init.find("})();")]
check("init builds the rail through loadSaved, not straight from wib-saved",
      "loadSaved();" in init and "forEach(renderSaved)" not in init and "wib-saved" not in init)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All chat-page code-of-conduct structural checks passed.")
