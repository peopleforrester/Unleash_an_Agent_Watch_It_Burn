# ABOUTME: The attendee text the public cluster's trace scrub must rewrite and the demo text it must leave alone
# ABOUTME: (#647), shared by the offline pattern test and the run through the real collector binary.
"""One set of cases for both halves of the scrub's tests.

test_collector_pii_scrub.py applies the patterns with Python's re (ASCII mode, which is how Go's RE2 reads \\b);
test_collector_pii_scrub_e2e.py sends the same text through otelcol-contrib itself, so a difference between the
two engines shows up as one test failing and the other passing.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
BURN_VALUES = REPO / "gitops/otel-collector/values-burn.yaml"
SCRUB = "transform/scrub_pii"

# What an attendee might type into attackme: every shape the scrub claims, and a name, which it does not.
ATTENDEE = ("Hi, I'm Jo Example, jo.example+kc@example.co.uk, call (503) 555-0142 or 503.555.0142 or 5035550142 "
            "or +44 20 7946 0958. Card 4111 1111 1111 1111, also 4111-1111-1111-1111 and 4111111111111111, "
            "amex 3782 822463 10005. SSN 123-45-6789.")
ATTENDEE_SCRUBBED = ("Hi, I'm Jo Example, [EMAIL], call [PHONE] or [PHONE] or [PHONE] "
                     "or [PHONE]. Card [CARD], also [CARD] and [CARD], "
                     "amex [CARD]. SSN [SSN].")
RAW_VALUES = ("jo.example", "example.co.uk", "555-0142", "5035550142", "7946", "4111", "822463", "6789")


def c5_record() -> str:
    """Challenge 5's planted record, a street address the trace is meant to keep (kubecon.html, C5)."""
    for doc in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")):
        if doc and doc.get("kind") == "Secret" and doc["metadata"]["name"] == "ceo-personal-record":
            return doc["stringData"]["record"]
    raise SystemExit("ceo-personal-record is not in gitops/ai-layer/resources.yaml")


# Text the scrub must not change: the demo's own record, the planted 7-digit 555 numbers and card tails, and the
# ids, dates, versions and addresses that turn up in tool results.
UNTOUCHED = (
    "Morticia Nightshade, 13 Cauldron Lane, Salem, MA, phone 555-0113, card_last4 4217",
    "order HC-1041 on 2026-10-29 at 10.100.200.30, account 123456789012, image 0.160.0-5b66b0dc6921",
    "session 3f2b9c1e-8d4a-4b7e-9f1a-2c3d4e5f6a7b, resourceVersion 48213377, RFC 1410",
)


def burn_scrub() -> dict:
    """The scrub processor as values-burn.yaml defines it."""
    return yaml.safe_load(BURN_VALUES.read_text(encoding="utf-8"))["config"]["processors"][SCRUB]


_REPLACE = re.compile(r'^replace_all_patterns\((?P<target>.+?), "value", "(?P<pattern>.*)", "(?P<label>\[[A-Z]+\])"\)$')


def patterns(statements: list[str]) -> list[tuple[str, str, str]]:
    """(target, OTTL-quoted pattern, label) of each replace_all_patterns statement, in order."""
    return [(m["target"], m["pattern"], m["label"]) for m in map(_REPLACE.match, statements) if m]


def unquote(ottl_pattern: str) -> str:
    """The regex OTTL hands RE2: a doubled backslash in the OTTL string literal is one backslash."""
    return ottl_pattern.replace("\\\\", "\\")
