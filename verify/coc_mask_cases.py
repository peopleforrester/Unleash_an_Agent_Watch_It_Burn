# ABOUTME: The collector's code-of-conduct mask (#1277): the OTTL statement built from the #1267 spike's term list, its
# ABOUTME: decoding back to the RE2 pattern, and the texts it must mask and leave alone, for the offline and tier tests.
"""One source for both halves of the mask's tests.

transform/coc_mask in gitops/otel-collector/values.yaml runs replace_all_patterns with the spike's term floor in its
RE2 form, cut into short patterns (docs/research/2026-11-09-coc-floor/floor.py's portable_patterns(), #1328): the
collector parses an OTTL string in time that grows with the square of its length, and portable_pattern() whole cost
about 46 s of CPU at every start. Each pattern is written into the collector config through three layers of escaping,
undone here in the reverse order a cluster applies them:

  YAML       the statement is a single-quoted scalar; the pattern has no quote, so YAML changes nothing
  confmap    the collector reads `$$` as a literal `$` (a bare `$` can open a ${...} reference)
  OTTL       the pattern is a double-quoted string literal, where `\\\\` is one backslash
  RE2        what Go's regexp compiles

The copies registry's `write` (coc_pattern_copies) writes the statements into values.yaml after the list changes, and
test_collector_coc_mask.py fails until the config and statements() agree. Run as a script, this prints them.

test_collector_coc_mask.py checks the statements and their placement offline and applies the decoded patterns with
Python's re; test_collector_coc_mask_e2e.py sends the same texts through the pinned otelcol-contrib.
"""
from __future__ import annotations

import functools
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


def patterns(terms: list[str] | None = None) -> list[str]:
    """The patterns the collector must run, in order: the spike's portable_patterns() on its proposed list. Building
    them takes about 1.5 s, so the proposed list's are built once."""
    return list(_proposed()) if terms is None else floor.portable_patterns(terms)


@functools.lru_cache(maxsize=1)
def _proposed() -> tuple[str, ...]:
    return tuple(floor.portable_patterns())


def collector_patterns(terms: list[str] | None = None) -> str:
    """patterns() as one text, a line each: the form the copies registry (coc_pattern_copies) holds the collector's
    copy to."""
    out = patterns(terms)
    if any("\n" in p for p in out):
        raise SystemExit("a term pattern holds a newline; collector_patterns() writes one a line")
    return "\n".join(out)


def encode(regex: str) -> str:
    """The regex as it is written inside the OTTL string literal in the collector's config."""
    if '"' in regex or "'" in regex:
        raise SystemExit("the term pattern holds a quote; encode() would need to escape it for OTTL and YAML")
    return regex.replace("\\", "\\\\").replace("$", "$$")


def decode(written: str) -> str:
    """What RE2 compiles from the pattern as written in the config: confmap's `$$`, then OTTL's `\\\\`."""
    return written.replace("$$", "$").replace("\\\\", "\\")


def replace_statement(regex: str) -> str:
    return f'replace_all_patterns({CACHE}, "value", "{encode(regex)}", "{REPLACEMENT}")'


# The second pass of each pattern runs only where the conversation holds a "[redacted]" (#1328), which every match of a
# first pass writes. A first pass that matched nothing leaves the text as it was, and the second would match nothing
# either, so the condition changes no output (a "[redacted]" from elsewhere only runs a pass that finds nothing). The
# conversation holds no term in nearly every span, and there the condition halves what the mask costs. `\\[` in the
# OTTL string is the RE2 `\[`.
SECOND_PASS = ' where IsMatch(String(cache["coc"]), "\\\\[redacted\\\\]")'


def keep_statement() -> str:
    return f'keep_keys({CACHE}, [{", ".join(f"{chr(34)}{k}{chr(34)}" for k in KEYS)}])'


def statements() -> list[str]:
    """Each context's statements: copy the attributes to the cache, keep the conversation, mask with each pattern in
    turn, twice (an edge is consumed, so two terms one separator apart take two passes; the second only where something
    is masked, SECOND_PASS), merge the masked copy back."""
    return ([f"set({CACHE}, attributes)", keep_statement()]
            + [s for regex in patterns() for s in (replace_statement(regex), replace_statement(regex) + SECOND_PASS)]
            + [f'merge_maps(attributes, {CACHE}, "upsert")'])


def mask(text: str) -> str:
    """The mask as the collector applies it, in Python: the spike's portable_mask (each pattern twice) with each
    pattern in turn. re.ASCII has the patterns' (?i) fold ASCII letters alone. Python's own folding reads a dotless i
    as i and RE2's does not, so without it a pattern that lacks the dotless i would pass here and miss it in the
    collector (#1301)."""
    for regex in _compiled():
        text = floor.portable_mask(text, regex)
    return text


@functools.lru_cache(maxsize=1)
def _compiled() -> tuple:
    import re
    return tuple(re.compile(regex, re.ASCII) for regex in patterns())


def hc666_ticket() -> str:
    """HC-666's ticket as read_support_ticket hands it to the bot: ticket_site.py's TICKETS entry, imported."""
    spec = importlib.util.spec_from_file_location("ticket_site_for_coc_mask", REPO / "gitops/ai-layer/ticket_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ticket = mod.TICKETS.get("HC-666")
    if not ticket or "IGNORE ALL PREVIOUS INSTRUCTIONS" not in ticket.get("body", ""):
        raise SystemExit("gitops/ai-layer/ticket_site.py has no HC-666 ticket with its injection; the case reads it")
    return ticket["body"]


SLANG = REPO / "gitops/ai-layer/guard-proxy/conformance/coc_floor/slang-set.rot13.tsv"  # guard-proxy-agenticburn#84's


def corpora() -> dict[str, list[str]]:
    """The four corpora #1316 held the collector's form to, text for text against the folded floor: the spike's abuse
    set, the pinned guard-proxy's slang fixture, the stage texts and the hard negatives."""
    import codecs
    if not SLANG.is_file():
        raise SystemExit(f"FAIL {SLANG.relative_to(REPO)} is missing; run bash verify/ensure-submodules.sh")
    slang = [codecs.decode(line.split("\t", 1)[1], "rot13") for line in SLANG.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#") and "\t" in line]
    return {"abuse set": [t for _, t in floor.corpus.abuse_set()], "slang fixture": slang,
            "stage texts": [t for _, t in floor.corpus.stage_texts()], "hard negatives": floor.corpus.hard_negatives()}


# Texts that must come out masked, one term each kind of spelling the RE2 form reads without folding. Terms from the
# spike's own list, decoded at run time, so the public tree does not spell them out (the list is ROT13 for the same
# reason). Each is (text, masked text).
def term_cases() -> list[tuple[str, str]]:
    terms = sorted(floor.corpus.terms("proposed"), key=len)
    word = next(t for t in terms if " " not in t and len(t) >= 4 and t.isascii() and t.isalpha())
    phrase = next(t for t in terms if " " in t and t.isascii())
    sharp = next(t for t in terms if "ß" in t)  # a letter json.dumps writes as ß, and fold() keeps
    dotless = next(t for t in terms if " " not in t and "i" in t and t.isascii() and t.isalpha()).replace("i", "ı")
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
        # The dotless i (U+0131), which guard-proxy's re.IGNORECASE reads as i and RE2's (?i) does not (#1301).
        (f"what a {dotless} move", "what a [redacted] move"),
    ]


if __name__ == "__main__":
    print("\n".join(statements()))
