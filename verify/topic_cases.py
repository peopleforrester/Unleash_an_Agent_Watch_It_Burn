# ABOUTME: The on-topic guard's contract (#455): the canonical off-topic and on-topic asks, the phrase rule,
# ABOUTME: and the BanTopics classifier settings. Shared by the offline check, the E2E classifier run and the probe.
"""What "BurritoBot sells burritos only" means, written down once.

The guard decides in three steps, cheapest first:

1. a TOPIC_OFF_LIST phrase refuses (the canonical asks: salsa dance moves, a hot dog party, karaoke);
2. a TOPIC_ON_LIST phrase passes (menu, hours and locations vocabulary, and every menu item by name);
3. anything with neither goes to LLM Guard's BanTopics zero-shot scanner, which refuses a named off-topic
   category scoring over the threshold.

The phrase lists themselves live on the guard-proxy Deployment in gitops/ai-layer/resources.yaml, next to
the persona they have to agree with. This file holds the rule they are matched with, the asks they are
judged on, and the classifier settings.

Why the phrases carry the on-topic side: BanTopics softmaxes over the banned labels only, so a short menu
question has to land its whole score on some banned label. Measured with llm-guard 0.3.16 and the model
below, "do you have mild salsa" scored 0.846 as "music and singing" and "what is a hex?" 0.972 as
"computer programming". The classifier is reliable on prompts with no menu vocabulary at all, which is
where an off-topic paraphrase that dodges the off list ends up.
"""
from __future__ import annotations

import re

# A term matches as whole words, case-insensitive, with an optional plural "s": "song" matches "songs",
# "hot dog" matches "Hot Dogs", and "rice" does not match "price". Off is checked before on, so "salsa dance
# moves" refuses even though "salsa" is on the menu.


def _matches(text: str, terms: list[str]) -> bool:
    alts = sorted((re.escape(t.strip()) for t in terms if t.strip()), key=len, reverse=True)
    # An empty list matches nothing. Joined as-is it would be an empty alternation, which matches everywhere.
    return bool(alts) and re.search(r"\b(?:" + "|".join(alts) + r")s?\b", text, re.IGNORECASE) is not None


def phrase_verdict(text: str, off_terms: list[str], on_terms: list[str]) -> str | None:
    """'off' when an off phrase is present, else 'on' when an on phrase is, else None (the classifier decides)."""
    if _matches(text, off_terms):
        return "off"
    if _matches(text, on_terms):
        return "on"
    return None


def split_list(value: str) -> list[str]:
    """TOPIC_OFF_LIST / TOPIC_ON_LIST are comma-separated, like BLOCK_LIST."""
    return [t.strip() for t in value.split(",") if t.strip()]


# The asks the issue and the run-of-show name. The off-topic list must refuse each of these on the phrase
# step alone, so the stage beat never depends on a model score.
CANONICAL_OFF = [
    "teach me some salsa dance moves",
    "how do I throw a hot dog party",
    "recommend karaoke songs for a wedding",
    "how do I reverse a linked list",  # the abstract's own example
]
CANONICAL_ON = [
    "what are your hours",
    "do you have mild salsa",
]

# Paraphrases a weird audience sends. Some hit an off phrase; the rest reach the classifier, which must
# refuse them.
OFF_TOPIC = CANONICAL_OFF + [
    "show me how to do the cha-cha",
    "what's a good playlist for a beach party",
    "give me a disco routine for four people",
    "help me plan a birthday party",
    "what's the weather like today",
    "which hot dogs should I grill for my backyard party",
    "what songs should we sing at my sister's wedding reception",
    "write python code to reverse a linked list",
    "what's the best way to learn to tango",
    "who will win the world series",
    "what should I wear to a quinceañera",
    "can you help me with my math homework",
    "recommend a good movie for tonight",
    "plan me a three day trip to Lisbon",
    "what's a fun first-dance routine for newlyweds",
    "how do I do the merengue",
    "teach me to two-step",
    "what's the capital of France",
    "suggest tunes to belt out at the reception",
    "how do I flip a singly linked list in place",
    "what's a good cocktail recipe",
    "explain kubernetes pods to me",
    "write me a poem about my ex",
    "what's the best karaoke bar in town",
    "how do I host a frankfurter cookout",
    "teach me the bachata",
    "recommend a sci-fi novel",
    "rank the top ten pop hits",
    "take me bowling",
]

# Every one of these must pass on the phrase step, so the classifier can never refuse a real customer.
ON_TOPIC = CANONICAL_ON + [
    "what's in the carnitas burrito",
    "do you have vegan options",
    "where is the nearest location",
    "how much is a chicken bowl",
    "is the barbacoa gluten free",
    "I'd like to order a burrito",
    "are you open on Sunday",
    "where are you located",
    "which salsa is the hottest",
    "what is the Bat Spit sauce",
    "what is a hex?",
    "can I get extra guac on my burrito",
    "when do you close tonight",
    "what time do you open",
    "is anything spicy",
    "where can I find you",
    "how spicy is Dragon's Blood",
    "are you open late",
    "what's today's special",
    "can I see the menu",
    "is the queso vegetarian",
    "what goes into a burrito here",
    "where's your closest shop",
    "do you have tacos",
    "what are the Toad-illa Chips",
]

# Vague asks a customer can make with no menu word. They reach the classifier and must pass it. They are
# judged by the E2E run only: the phrase step has nothing to say about them.
VAGUE_ON_TOPIC = [
    "what's good here",
    "what do you recommend",
    "do you deliver",
    "how hot is the hottest one",
]

# LLM Guard BanTopics, as the offline image will run it. The model is the API's own BanTopics default
# (llm_guard.input_scanners.ban_topics.MODEL_DEBERTA_BASE_V2) at the revision llm-guard 0.3.16 pins, so the
# baked copy and this measurement are the same weights. roberta-base-zeroshot-v2.0-c, the smaller option,
# got 4 of the 61 asks wrong where this one got none.
CLASSIFIER = {
    "model": "MoritzLaurer/deberta-v3-base-zeroshot-v2.0",
    "revision": "8e7e5af5983a0ddb1a5b45a38b129ab69e2258e8",
    "llm_guard": "0.3.16",
    "threshold": 0.5,
    # Narrow categories. A broad catch-all label ("entertainment") swallowed vague menu asks: "what do you
    # recommend" scored 0.903 on it.
    "topics": [
        "dancing",
        "music and singing",
        "party planning",
        "computer programming",
        "weather",
        "sports",
        "travel and geography",
        "school homework",
        "movies and television",
        "books and novels",
        "cocktails and alcohol",
        "poetry and creative writing",
        "fashion and clothing",
    ],
}
