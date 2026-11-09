# ABOUTME: Offline half of the chat page's code-of-conduct check (#947, #1280): burritbot.html's COC_TERMS is the spike's
# ABOUTME: proposed floor list (corpus.terms("proposed")), its folding tables are floor.py's, and cocViolation stays pure.
"""The executed half is verify/test_chat_coc_e2e.py, which runs the page's cocViolation in node against floor.py's
proposed floor on every assigned code point, the abuse set and the stage's own text. This half needs no node.

Since #1280 the saved-prompts rail keeps off the floor the code-of-conduct spike chose for every surface (#1267,
docs/research/2026-11-09-coc-floor): its 144 terms, and its folding of leetspeak, spaced letters, repeated letters,
zero-width characters, look-alike letters and accents. This half reads the page's one ROT13 term literal and holds it,
entry for entry and in order, to corpus.terms("proposed"); it holds the page's leetspeak, zero-width and look-alike
tables to floor.py's _LEET, _ZERO_WIDTH and _HOMOGLYPH, and the separator class to every character Python's \\s
matches. Since #1288 guard-proxy is pinned at 48cc2ca or later, whose wall and /chat refusal read the same list, so the
pinned proxy.py's PROFANITY and the Go build's DefaultProfanity must each be the page's list, entry for entry and in
order, or the rail and the wall would keep off different terms.
It also checks the function touches nothing but its argument, and the save and load paths of #948.
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
GP = REPO / "gitops/ai-layer/guard-proxy"
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def one(pattern: str, what: str) -> str:
    """The single match of pattern's group 1 in the page; exits naming the literal when it is not there once."""
    found = re.findall(pattern, page)
    if len(found) != 1:
        print(f"FAIL: expected one {what} in {PAGE_PATH.relative_to(REPO)}, found {len(found)}")
        sys.exit(1)
    return found[0]


def js_string(body: str) -> str:
    """A single-quoted JavaScript string literal's value; it holds no quote, so JSON reads its \\u escapes."""
    return json.loads('"' + body.replace('"', '\\"') + '"')


for f in (PAGE_PATH, GP / "proxy.py", GP / "internal/config/config.go"):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing (for guard-proxy, run verify/ensure-submodules.sh)")
        sys.exit(1)

os.environ.pop("PROFANITY_LIST", None)
spec = importlib.util.spec_from_file_location("gp_chat_coc_offline", GP / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

page = PAGE_PATH.read_text(encoding="utf-8")

print("== the page's list is the spike's proposed floor list ==")
rot = one(r"const COC_TERMS='([^']*)'\.split\(','\)", "const COC_TERMS='...'.split(',') literal")
terms = [codecs.decode(t, "rot13") for t in rot.split(",")]
proposed = corpus.terms("proposed")
check(f"COC_TERMS decodes to corpus.terms('proposed'), all {len(proposed)} entries in order", terms == proposed,
      f"page only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(terms) - set(proposed))}; "
      f"spike only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(proposed) - set(terms))}")
check("the literal is ROT13, so the page source does not display the terms",
      not set(rot.split(",")) & set(proposed))
check("COC_TERMS is decoded by rotating ASCII letters by 13 and nothing else",
      ".map(function(w){return w.replace(/[a-z]/gi,function(c){var b=c<='Z'?65:97;"
      "return String.fromCharCode((c.charCodeAt(0)-b+13)%26+b);});});" in page)

print("== the folding tables are floor.py's ==")
leet = dict(re.findall(r"(\w):'([^']*)'", one(r"const COC_LEET=\{([^}]*)\};", "const COC_LEET={...}")))
check("COC_LEET is floor.py's _LEET", leet == floor._LEET, f"page {leet}")
zw = js_string(one(r"const COC_ZERO_WIDTH='([^']*)';", "const COC_ZERO_WIDTH='...'"))
check("COC_ZERO_WIDTH is floor.py's _ZERO_WIDTH", set(zw) == floor._ZERO_WIDTH and len(zw) == len(floor._ZERO_WIDTH),
      f"page {[hex(ord(c)) for c in zw]}")
src, dst = (js_string(s) for s in re.findall(r"'([^']*)'", one(r"const COC_LOOKALIKE=\[([^\]]*)\];",
                                                                   "const COC_LOOKALIKE=[...]")))
check("COC_LOOKALIKE maps each look-alike letter as floor.py's _HOMOGLYPH does",
      len(src) == len(dst) and dict(zip(map(ord, src), map(ord, dst))) == floor._HOMOGLYPH)
check("the look-alikes are written as \\u escapes, so a reader of the page can tell them from Latin letters",
      one(r"const COC_LOOKALIKE=\['([^']*)'", "COC_LOOKALIKE source string").isascii())
sep = js_string(one(r"const COC_SEP='([^']*)';", "const COC_SEP='...'"))
spaces = {chr(c) for c in range(0x110000) if re.match(r"\s", chr(c))}
sep_chars = {chr(c) for c in range(0x110000) if re.fullmatch(sep, chr(c))}
check("COC_SEP matches what floor.py's _SEP does: Python's whitespace, a dot, an underscore, an asterisk, a hyphen",
      sep_chars == spaces | set("._*-"),
      f"page only: {sorted(map(hex, map(ord, sep_chars - spaces - set('._*-'))))}; "
      f"floor only: {sorted(map(hex, map(ord, (spaces | set('._*-')) - sep_chars)))}")
check("cocLetter adds '*' for exactly floor.py's vowels",
      "('aeiou'.indexOf(c)>=0?'*':'')" in page and floor._VOWELS == set("aeiou"))
check("COC_RE is the whole-word, optional-plural pattern of floor.py's proposed_pattern() on the folded text",
      "const COC_RE=new RegExp('(?<![a-z0-9])(?:'+COC_TERMS.slice().sort(function(a,b){return b.length-a.length;})"
      ".map(cocTerm).join('|')+')s?(?![a-z0-9])');" in page
      and floor.proposed_pattern().pattern.startswith("(?<![a-z0-9])(?:")
      and floor.proposed_pattern().pattern.endswith(")s?(?![a-z0-9])"))

print("== the wall's list is the page's ==")
# Since #1288 the pin is guard-proxy 48cc2ca or later, whose default list is the same 144 entries in the same order, so
# the wall, the /chat refusal and the rail keep off one list. A term on one side only is named, ROT13.
check("the pinned proxy.py's PROFANITY is the page's list, entry for entry and in order", proxy.PROFANITY == terms,
      f"proxy only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(proxy.PROFANITY) - set(terms))}; "
      f"page only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(terms) - set(proxy.PROFANITY))}")
go = (GP / "internal/config/config.go").read_text(encoding="utf-8")
# The Go build keeps the list ROT13 too: var DefaultProfanity = rot13(defaultProfanityROT13), the constant a run of
# "..." + lines with // section comments between them, ending at the first string line with no trailing +.
m = re.search(r"^const defaultProfanityROT13 = \"\" \+\n((?:[ \t]*(?://[^\n]*|\"[^\"]*\" \+)\n)*[ \t]*\"[^\"]*\"\n)",
              go, re.M)
check("the Go build still names const defaultProfanityROT13, decoded by rot13 into DefaultProfanity",
      m is not None and "var DefaultProfanity = rot13(defaultProfanityROT13)" in go)
if m:
    lines = [ln for ln in m.group(1).splitlines() if not ln.strip().startswith("//")]
    go_terms = [codecs.decode(t, "rot13") for t in "".join(re.findall(r'"([^"]*)"', "\n".join(lines))).split(",")]
    check("the Go build's DefaultProfanity is the page's list, entry for entry and in order", go_terms == terms,
          f"Go only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(go_terms) - set(terms))}; "
          f"page only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(terms) - set(go_terms))}")
resources = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
override = re.search(r"name:\s*PROFANITY_LIST\s*\n\s*value:\s*[\"']?([^\"'\n]*)", resources)
if override:
    wall = [t.strip().lower() for t in override.group(1).split(",") if t.strip()]
    check("every term resources.yaml's PROFANITY_LIST sets is on the page's list", set(wall) <= set(terms),
          f"wall only (ROT13): {sorted(codecs.encode(t, 'rot13') for t in set(wall) - set(terms))}")
else:
    check("resources.yaml sets no PROFANITY_LIST, so guard-proxy masks its default list, held above",
          not re.search(r"name:\s*PROFANITY_LIST\b", resources))

print("== cocViolation is pure, and the saved list is wired to it ==")
defs = re.findall(r"function cocViolation\(", page)
check("burritbot.html defines cocViolation once", len(defs) == 1, f"found {len(defs)}")
fn = re.search(r"function cocViolation\((\w+)\)\{([^\n]*)\}\n", page)
check("cocViolation is one line taking one argument", fn is not None)
if fn:
    body = fn.group(2)
    check("cocViolation only tests its folded argument against COC_RE",
          "COC_RE.test(cocFold(" in body and not re.search(r"document|window|localStorage|sessionStorage|fetch|save\(",
                                                            body), body)
helpers = page[page.find("function cocFold("):page.find("const COC_RE=")]
check("cocFold, cocLetter and cocTerm touch nothing outside their arguments and the COC_ tables",
      helpers and not re.search(r"document|window|localStorage|sessionStorage|fetch|save\(", helpers))
check("cocFold drops marks after NFKD, as floor.py's fold() drops combining characters",
      "ch.normalize('NFKD').replace(/\\p{M}/gu,'')||ch" in helpers)

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
