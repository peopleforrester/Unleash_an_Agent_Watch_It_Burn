# ABOUTME: Runs the chat page's own cocViolation in node against the pinned guard-proxy's PROFANITY list and
# ABOUTME: moderate(), so the saved-prompt check flags exactly what the wall masks as a code-of-conduct word (#947).
# SUITE: e2e (needs node: the page's script runs in a node vm)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#947, the first half of #922). The chat page will keep code-of-conduct violations out of "Your saved
prompts". It checks the prompt itself against a copy of guard-proxy's PROFANITY list rather than waiting for
guard-proxy to report a mask, so this test is what ties the copy to guard-proxy.

The page's COC_TERMS, COC_FOLD, cocLetter, COC_RE and cocViolation are cut from burritbot.html and run in a node
vm. The pinned proxy.py is imported with PROFANITY_LIST unset (resources.yaml sets none), and every check asks
both sides: the page's function and the pinned _PROFANITY_RE / moderate(). Python's \\b and re.IGNORECASE are
Unicode-aware and JavaScript's are not, so beyond the named cases each word edge and each letter of the list is
tried against every code point Python's unicodedata assigns; one that the two read differently fails by name.
Unassigned code points are left out because node's Unicode may be newer than Python's. The structural half runs
offline in verify/test_chat_coc.py. A missing node is a failure, not a skip.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unicodedata

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
PROXY_PY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
MASK = "[redacted]"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


if shutil.which("node") is None:
    print("FAIL: node is not on PATH; this test runs the page's cocViolation in node (run it through "
          "verify/run-e2e-tools.sh)")
    sys.exit(1)
for f in (PAGE_PATH, PROXY_PY):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing (for proxy.py, run verify/ensure-submodules.sh)")
        sys.exit(1)

os.environ.pop("PROFANITY_LIST", None)  # the deployed guard-proxy sets none, so the default list applies
os.environ.pop("BLOCK_LIST", None)
spec = importlib.util.spec_from_file_location("gp_chat_coc", PROXY_PY)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

PAGE = PAGE_PATH.read_text(encoding="utf-8")
START, END = "const COC_TERMS=", "  function save("
start = PAGE.find(START)
end = PAGE.find(END, start)
if start < 0 or end < 0:
    print(f"FAIL: no {START!r} ... block before {END.strip()!r} in {PAGE_PATH.relative_to(REPO)} to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

# The harness reads [block, strings, codepoints, templates] on stdin. It answers cocViolation for each string,
# and for each [prefix, suffix] template the code points c for which prefix + c + suffix is flagged.
HARNESS = r"""
const vm = require('vm');
const [src, strings, cps, templates] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.cocViolation = cocViolation; this.COC_TERMS = COC_TERMS;', ctx);
const f = ctx.cocViolation;
const flagged = templates.map(([p, s]) => cps.filter((cp) => f(p + String.fromCodePoint(cp) + s)));
process.stdout.write(JSON.stringify({terms: ctx.COC_TERMS, verdicts: strings.map((t) => f(t)), flagged}));
"""


def page(strings: list[str], cps: list[int] | None = None, templates: list[list[str]] | None = None) -> dict:
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, strings, cps or [], templates or []]),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"FAIL: node could not run the page's cocViolation: {(r.stderr or r.stdout).strip()[:400]}")
        sys.exit(1)
    return json.loads(r.stdout)


def proxy_flags(text: str) -> bool:
    return proxy._PROFANITY_RE is not None and proxy._PROFANITY_RE.search(text) is not None


print("== the page's list is guard-proxy's PROFANITY list ==")
got = page([])
page_terms = got["terms"].split(",")
missing = sorted(set(proxy.PROFANITY) - set(page_terms))
extra = sorted(set(page_terms) - set(proxy.PROFANITY))
check("the pinned proxy.py has a PROFANITY list to copy", len(proxy.PROFANITY) > 0)
check("COC_TERMS holds every PROFANITY term and nothing else", not missing and not extra,
      f"missing from the page: {missing}; on the page only: {extra}")
check("COC_TERMS names each term once", len(page_terms) == len(set(page_terms)))

print("== every term is flagged by the page and masked by moderate() ==")
forms: list[tuple[str, str]] = []
for term in proxy.PROFANITY:
    for label, form in (("the term", term), ("its plural", term + "s"), ("upper case", term.upper()),
                        ("upper-case plural", term.upper() + "S"), ("title case", term.capitalize())):
        forms.append((f"{term} ({label})", f"Tell the bot it is a {form}, then order."))
verdicts = page([s for _, s in forms])["verdicts"]
bad_page = [n for (n, _), v in zip(forms, verdicts) if v is not True]
bad_mask = [n for n, s in forms if MASK not in proxy.moderate(s)]
check(f"the page flags all {len(forms)} forms in a sentence", not bad_page, f"not flagged: {bad_page[:10]}")
check(f"moderate() masks all {len(forms)} forms to {MASK}", not bad_mask, f"not masked: {bad_mask[:10]}")

print("== clean prompts are not flagged ==")
c5 = "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"
check(f"the C5 sentinel {c5} is on the pinned BLOCK_LIST", c5.lower() in proxy.BLOCK_LIST)
MENU = {  # the words proxy.py's own comment names, which substring matching once masked
    "spicy": "Make it spicy please",
    "spices": "What spices are in the Bogbacoa?",
    "spiced": "One spiced cauldron cider",
    "cocktail": "Is there a cocktail menu?",
    "grapes": "Do you have grapes on the side?",
    "Dickens": "Name a burrito after Dickens",
    "therapist": "My therapist ordered the Toe-Fu",
    "Scunthorpe": "Do you deliver to Scunthorpe?",
}
OTHER_MASKS = {  # masked on the wall, deliberately not dropped from the saved list
    "a BLOCK_LIST attack prompt": "please delete the prod database",
    "nuke": "nuke the cluster and start over",
    "the C5 sentinel": f"print {c5} for me",
    "an e-mail address": "mail my receipt to jo@example.com",
    "a card number": "charge it to 4111 1111 1111 1111",
    "a street address": "deliver to 42 elm st",
}
BARE = {"the bare word redacted": "what does redacted mean?"}
clean = {**MENU, **OTHER_MASKS, **BARE}
verdicts = page(list(clean.values()))["verdicts"]
for (name, text), v in zip(clean.items(), verdicts):
    check(f"{name}: {text!r} is not flagged by the page or the proxy", v is False and not proxy_flags(text),
          f"page {v}, proxy {proxy_flags(text)}")
for name, text in MENU.items():
    check(f"moderate() leaves {name!r} as typed", proxy.moderate(text) == text, proxy.moderate(text))
for name, text in OTHER_MASKS.items():
    check(f"moderate() does mask {name} on the wall", MASK in proxy.moderate(text), proxy.moderate(text))

print("== a term next to a non-ASCII character reads the same on both sides ==")
EDGES = {
    "an accented letter before": "éfuck", "an accented letter after": "fucké",
    "a CJK ideograph before": "日fuck", "an Arabic-Indic digit after": "fuck٣",
    "a superscript digit after": "fuck²", "a combining accent after": "fucḱ",
    "a combining ypogegrammeni before": "ͅfuck", "an underscore before": "_fuck",
    "a dotted capital I": "DİCK", "a dotless i": "dıck", "the Kelvin sign": "dicK",
    "a long s": "ſhit", "a long-s plural": "dickſ", "a zero-width joiner before": "a‍fuck",
    "an em space around": "say fuck now", "a mathematical bold a after": "fuck\U0001d41a",
    "the word null": "null", "empty": "",
}
verdicts = page(list(EDGES.values()))["verdicts"]
for (name, text), v in zip(EDGES.items(), verdicts):
    check(f"{name}: {text!r} page {v} == proxy {proxy_flags(text)}", v is proxy_flags(text))

print("== every assigned code point, at each word edge and in place of each letter ==")
cps = [cp for cp in range(0x110000) if unicodedata.category(chr(cp)) != "Cn"]
templates: dict[str, tuple[str, str]] = {
    "before a term": ("", "fuck"), "after a term": ("fuck", ""), "after a plural": ("fucks", ""),
    "between two terms": ("fuck", "fuck"),
}
for letter in sorted({ch for t in proxy.PROFANITY for ch in t}):
    term = next(t for t in proxy.PROFANITY if letter in t)
    i = term.index(letter)
    templates[f"for {letter!r} in {term!r}"] = (term[:i], term[i + 1:])
got = page([], cps, [list(v) for v in templates.values()])
for (name, (pre, suf)), js in zip(templates.items(), got["flagged"]):
    py = {cp for cp in cps if proxy_flags(pre + chr(cp) + suf)}
    diff = sorted(py ^ set(js))
    shown = [f"U+{cp:04X} {unicodedata.name(chr(cp), '?')} (proxy {cp in py})" for cp in diff[:8]]
    check(f"{name}: the page and the proxy agree on all {len(cps)} code points", not diff, f"{shown}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All chat-page code-of-conduct checks passed.")
