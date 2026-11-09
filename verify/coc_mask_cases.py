# ABOUTME: The collector's code-of-conduct mask (#1277): the OTTL statement built from the #1267 spike's term list, its
# ABOUTME: decoding back to the RE2 pattern, and the texts it must mask and leave alone, for the offline and tier tests.
"""One source for both halves of the mask's tests.

transform/coc_mask in gitops/otel-collector/values.yaml runs replace_all_patterns with the spike's term floor in its
RE2 form, docs/research/2026-11-09-coc-floor/floor.py's portable_pattern(). The pattern is written into the collector
config three times over, so each layer's escaping is undone here in the reverse order a cluster applies it:

  YAML       the statement is a single-quoted scalar; the pattern has no quote, so YAML changes nothing
  confmap    the collector reads `$$` as a literal `$` (a bare `$` can open a ${...} reference)
  OTTL       the pattern is a double-quoted string literal, where `\\\\` is one backslash
  RE2        what Go's regexp compiles

Run as a script it prints the statement to paste into values.yaml after the term list changes:
`python3 verify/coc_mask_cases.py`. test_collector_coc_mask.py fails until the two agree.

test_collector_coc_mask.py checks the statement and its placement offline and applies the decoded pattern with
Python's re; test_collector_coc_mask_e2e.py sends the same texts through the pinned otelcol-contrib.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
MASK = "transform/coc_mask"
CACHE = 'cache["coc"]'
REPLACEMENT = "$$1[redacted]$$3"  # groups 1 and 3 are the word edges the pattern consumes; `$$` is confmap's `$`
# The conversation: the same eight keys transform/scrub_pii keeps on burn (values-burn.yaml, #647) and Act 2 redacts.
KEYS = ("gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.tool.call.arguments", "gen_ai.tool.call.result",
        "gcp.vertex.agent.llm_request", "gcp.vertex.agent.llm_response", "gcp.vertex.agent.tool_call_args",
        "gcp.vertex.agent.tool_response")

sys.path.insert(0, str(SPIKE))
import floor  # noqa: E402


def pattern() -> str:
    """The pattern the collector must run: the spike's portable_pattern() on its proposed list."""
    return floor.portable_pattern()


def encode(regex: str) -> str:
    """The regex as it is written inside the OTTL string literal in the collector's config."""
    if '"' in regex or "'" in regex:
        raise SystemExit("the term pattern holds a quote; encode() would need to escape it for OTTL and YAML")
    return regex.replace("\\", "\\\\").replace("$", "$$")


def decode(written: str) -> str:
    """What RE2 compiles from the pattern as written in the config: confmap's `$$`, then OTTL's `\\\\`."""
    return written.replace("$$", "$").replace("\\\\", "\\")


def replace_statement() -> str:
    return f'replace_all_patterns({CACHE}, "value", "{encode(pattern())}", "{REPLACEMENT}")'


def keep_statement() -> str:
    return f'keep_keys({CACHE}, [{", ".join(f"{chr(34)}{k}{chr(34)}" for k in KEYS)}])'


def statements() -> list[str]:
    """Each context's statements: copy the attributes to the cache, keep the conversation, mask twice (an edge is
    consumed, so two terms one separator apart take two passes), merge the masked copy back."""
    return [f"set({CACHE}, attributes)", keep_statement(), replace_statement(), replace_statement(),
            f'merge_maps(attributes, {CACHE}, "upsert")']


def mask(text: str) -> str:
    """The mask as RE2 applies it, in Python: the spike's portable_mask with the collector's replacement."""
    import re
    return floor.portable_mask(text, re.compile(pattern()))


def hc666_ticket() -> str:
    """HC-666's ticket as read_support_ticket hands it to the bot: ticket_site.py's TICKETS entry, imported."""
    spec = importlib.util.spec_from_file_location("ticket_site_for_coc_mask", REPO / "gitops/ai-layer/ticket_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ticket = mod.TICKETS.get("HC-666")
    if not ticket or "IGNORE ALL PREVIOUS INSTRUCTIONS" not in ticket.get("body", ""):
        raise SystemExit("gitops/ai-layer/ticket_site.py has no HC-666 ticket with its injection; the case reads it")
    return ticket["body"]


# Texts that must come out masked, one term each kind of spelling the RE2 form reads without folding. Terms from the
# spike's own list, decoded at run time, so the public tree does not spell them out (the list is ROT13 for the same
# reason). Each is (text, masked text).
def term_cases() -> list[tuple[str, str]]:
    terms = sorted(floor.corpus.terms("proposed"), key=len)
    word = next(t for t in terms if " " not in t and len(t) >= 4 and t.isascii() and t.isalpha())
    phrase = next(t for t in terms if " " in t and t.isascii())
    sharp = next(t for t in terms if "ß" in t)  # a letter json.dumps writes as ß, and fold() keeps
    spaced = " ".join(word)
    # Once JSON-encoded, the second line starts after the two characters \n, and the curly quotes become ‘ and
    # ’: the cases a word edge of [^a-z0-9] alone misses (#1277).
    return [
        (f"This burrito is {word} cold.", "This burrito is [redacted] cold."),
        (f"{word.upper()}!!! where is my order", "[redacted]!!! where is my order"),
        (f"you {spaced}, answer me", "you [redacted], answer me"),
        (f"{word} {word} {word}", "[redacted] [redacted] [redacted]"),
        (f"I said: {phrase}.", "I said: [redacted]."),
        (f"‘{word}’ said the customer", "‘[redacted]’ said the customer"),
        (f"Ich sage {sharp} dazu", "Ich sage [redacted] dazu"),
    ]


if __name__ == "__main__":
    print(replace_statement())
