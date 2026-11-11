# ABOUTME: Offline check of the code-of-conduct spike's proposed term floor (#1267): it touches no stage text the repo
# ABOUTME: holds (every /kubecon prompt and its page, HC-666, the desk, the tools' data) and keeps its measured catch rate.
"""No cluster, no network, standard library and PyYAML.

docs/research/2026-11-09-coc-floor/README.md chose a deterministic term floor for every surface the room can write to,
on the measurement that it flags none of the stage's own text. That holds only while nobody adds a prompt, a menu item,
a witch name or a tool reply that a term matches, so this check reruns that half of the measurement on the files as
they stand: a new /kubecon prompt the floor would refuse fails here, naming the text and the term, not in the room.
The other pages' text is measure.py's: the chat page names the KubeCon probe script, which the scope map would then
count this test as reading.

It also holds the abuse set's catch rate per category at what the spike measured, so a shorter list or a looser
pattern that stops catching what it caught fails, and the hard negatives the floor is known to touch to the one the
README names (the rooster sentence: "cock" as a bird, a cost of matching the word at all).
"""
from __future__ import annotations

import ast
import codecs
import collections
import json
import re
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

# What the README states the proposed floor catches, per category of abuse-set.rot13.tsv (#1267, measured 2026-11-09).
CATCH_AT_LEAST = {"expletive": 20, "slur": 19, "sexual": 20, "evasion": 25, "foreign": 19, "hate": 4, "threat": 4}
# The hard negatives the proposed floor flags, and the only ones it may.
KNOWN_HARD_NEGATIVE_HITS = {"the rooster crowed; the cock crowed at dawn"}
# Anchors: texts the measurement must have read, so a parser that silently stops finding them reads as that.
ANCHORS = {
    "kubecon-prompt": "What's the status of my support ticket HC-666?",
    "desk-ticket": "I order a burrito every day for lunch",
    "tool-data": "Morticia Nightshade",
    "witch-name": "joker-",
}
# Every string literal in these is a prompt the probes send, a marker they judge a reply by, or text the stage's servers
# hand the model or the room. The floor masking one would turn a challenge that landed into a probe FAIL.
# The KubeCon probe script is not read here (the scope map counts a file more than 30 tests read as shared); its
# prompts are /kubecon's, read above, and measure.py checks its own two.
LITERAL_FILES = ("verify/agent_probe.py", "verify/topic_cases.py",
                 "gitops/ai-layer/workshop-mcp-server.py", "gitops/ai-layer/server.py", "gitops/ai-layer/ticket_site.py")
MIN_PER_SOURCE = {"kubecon-prompt": 10, "page-text": 300, "replay-prompt": 10, "catalog-prompt": 5, "probe-prompt": 10,
                  "desk-ticket": 5, "witch-name": 1000, "tool-data": 20, "agent-prompt": 100, "cluster-data": 50}

# The ports' markers, as verify/coc_pattern_copies.py names them.
PORT_START = "# --- the code-of-conduct floor (#1269, part of #1267) "
PORT_END = "# --- end of the code-of-conduct floor "

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def main() -> int:
    stage = corpus.stage_texts()
    by_source = collections.defaultdict(list)
    for src, text in stage:
        by_source[src].append(text)
    for src, least in MIN_PER_SOURCE.items():
        check(len(by_source[src]) >= least,
              f"corpus.py reads at least {least} {src} texts from the repo (read {len(by_source[src])})")
    for src, anchor in ANCHORS.items():
        check(any(anchor in t for t in by_source[src]),
              f"the {src} texts carry {anchor!r} (corpus.py, docs/research/2026-11-09-coc-floor)")

    for name in ("current", "proposed"):
        f = floor.Floor(name)
        hits = [(src, text, f.hits(text)) for src, text in stage if f.spans(text)]
        for src, text, h in hits[:10]:
            print(f"     {name} floor flags {src}: {text[:120]!r}, on {codecs.encode(repr(h), 'rot13')} (ROT13)")
        check(not hits, f"the {name} term floor flags none of the {len(stage)} stage texts ({len(hits)} flagged)")

    f = floor.Floor("proposed")
    # The two ports of floor.py (#1269) carry the term list itself, ROT13-encoded; ROT13 leaves an entry with no ASCII
    # letter as it is (1488, the finger emoji, #1316), so the list's own literal is not stage text and is left out.
    port_lines = {}
    for path in LITERAL_FILES:
        text = (REPO / path).read_text(encoding="utf-8")
        if PORT_START in text:
            port_lines[path] = (text[:text.index(PORT_START)].count("\n") + 1,
                                text[:text.index(PORT_END)].count("\n") + 1)
    literals = [(path, node.lineno, node.value) for path in LITERAL_FILES
                for node in ast.walk(ast.parse((REPO / path).read_text(encoding="utf-8")))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and not port_lines.get(path, (0, -1))[0] <= node.lineno <= port_lines.get(path, (0, -1))[1]]
    check(set(port_lines) == {"gitops/ai-layer/workshop-mcp-server.py", "gitops/ai-layer/ticket_site.py"},
          f"the two ports' markers ({PORT_START.strip()!r}) are found where the literals are read ({sorted(port_lines)})")
    flagged = [(p, n, v[:120]) for p, n, v in literals if f.spans(v)]
    for p, n, v in flagged[:10]:
        print(f"     {p}:{n} {v!r}")
    check(len(literals) > 2000 and not flagged,
          f"the proposed floor flags none of the {len(literals)} string literals of the probes and the stage's servers "
          f"({len(flagged)} flagged)")

    # The RE2 form the collector and an admission policy would run agrees with the folded floor on the stage and on
    # every abuse text that needs no folding (no zero-width character, look-alike letter, accent or fullwidth form).
    portable = re.compile(floor.portable_pattern())
    check(not [t for _, t in stage if floor.portable_mask(t, portable) != t],
          "the portable (RE2) pattern flags none of the stage texts")
    plain = [(c, t) for c, t in corpus.abuse_set() if floor.fold(t)[0] == t.lower()]
    differ = [codecs.encode(t, "rot13") for c, t in plain if (floor.portable_mask(t, portable) != t) != bool(f.spans(t))]
    check(len(plain) > 140 and not differ,
          f"the portable pattern and the folded floor agree on the {len(plain)} abuse texts that need no folding "
          f"(differ, ROT13: {differ})")

    hn = {t for t in corpus.hard_negatives() if f.spans(t)}
    check(hn == KNOWN_HARD_NEGATIVE_HITS,
          f"the proposed floor flags exactly the known hard negatives (unexpected: {sorted(hn - KNOWN_HARD_NEGATIVE_HITS)}, "
          f"no longer flagged: {sorted(KNOWN_HARD_NEGATIVE_HITS - hn)})")

    caught = collections.Counter(c for c, t in corpus.abuse_set() if f.spans(t))
    for cat, least in CATCH_AT_LEAST.items():
        check(caught[cat] >= least, f"the proposed floor catches at least {least} {cat} texts of the abuse set "
                                    f"(caught {caught[cat]})")

    # Masking keeps the text around a hit and maps a folded match back onto the original characters.
    sample = "ok " + codecs.decode("s​hсx", "rot13") + " ok"  # a zero-width space and a Cyrillic "c"
    masked = f.mask(codecs.decode("ab ", "rot13") + sample)
    check(masked.endswith(" ok") and "[redacted]" in masked and "​" not in masked,
          f"mask() replaces a match spelt with a zero-width space and a Cyrillic look-alike: {masked!r}")
    check(f.mask("put a burrito in the bag") == "put a burrito in the bag",
          "a separator between only some letters does not join words ('put a' stays)")

    # The dotless i (#1301): guard-proxy's re.IGNORECASE reads it as i, so the floor folds it to i, and the RE2 form,
    # which cannot fold and whose (?i) keeps it apart from i, lists it in every class that holds i. re.ASCII has
    # Python fold ASCII letters only, as RE2 does the i, so the form is read here as the collector and CEL read it.
    with_i = [t for t in corpus.terms("proposed") if "i" in t]
    dotless = [t.replace("i", "ı") for t in with_i]
    check(len(with_i) > 40 and all(f.spans(t) == [(0, len(t))] for t in dotless),
          f"the proposed floor flags each of the {len(with_i)} terms holding an i, spelt with a dotless i (U+0131) "
          f"for every i, from end to end (missed: {sum(f.spans(t) != [(0, len(t))] for t in dotless)})")
    re2 = re.compile(floor.portable_pattern(), re.ASCII)
    check(all(floor.portable_mask(t, re2) == "[redacted]" for t in dotless)
          and all(floor.portable_mask(json.dumps(t), re2) == '"[redacted]"' for t in dotless),
          "the portable (RE2) pattern, with case folded on ASCII letters alone, masks each of them, as written and as "
          "json.dumps escapes the dotless i (\\u0131)")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
