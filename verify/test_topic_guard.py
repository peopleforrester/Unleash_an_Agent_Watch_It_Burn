# ABOUTME: Offline check of the on-topic guard (#455): the deployed phrase lists refuse the canonical off-topic
# ABOUTME: asks and pass every on-topic one, the guard starts off, the persona has hours and locations, the helpers exist.
"""BurritoBot sells burritos only, held to verify/topic_cases.py without a cluster or a model.

What the phrase step guarantees is checked here exactly: the four canonical off-topic asks refuse on a phrase,
every on-topic ask passes on a phrase (so the classifier can never refuse a customer), and no off-topic ask
passes on one. What reaches the classifier is judged by verify/test_topic_classifier.py (E2E suite).
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import topic_cases as tc  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ai-layer's bundle and the Agent's, its own Application since #707.
docs = [d for p in ("gitops/ai-layer/resources.yaml", "gitops/workshop-agent/agent.yaml")
        for d in yaml.safe_load_all((REPO / p).read_text()) if d]


def obj(kind: str, name: str) -> dict:
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


proxy = next(c for c in obj("Deployment", "guard-proxy")["spec"]["template"]["spec"]["containers"]
             if c["name"] == "proxy")
env = {e["name"]: e.get("value") for e in proxy["env"]}
persona = obj("Agent", "workshop-agent")["spec"]["declarative"]["systemMessage"]
scanners = yaml.safe_load(obj("ConfigMap", "llm-guard-scanners")["data"]["scanners.yml"])
terminal = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text()

print("== the guard starts off and carries its settings ==")
check("TOPIC_GUARD is off at the wide-open start", env.get("TOPIC_GUARD") == "off", repr(env.get("TOPIC_GUARD")))
for k in ("TOPIC_OFF_LIST", "TOPIC_ON_LIST", "TOPIC_REFUSAL"):
    check(f"{k} is set on guard-proxy", bool(env.get(k)))
off = tc.split_list(env.get("TOPIC_OFF_LIST") or "")
on = tc.split_list(env.get("TOPIC_ON_LIST") or "")
both = sorted({t.lower() for t in off} & {t.lower() for t in on})
check("no phrase is on both lists", not both, f"on both: {both}")

print("== the phrase step ==")
for ask in tc.CANONICAL_OFF:
    v = tc.phrase_verdict(ask, off, on)
    check(f"canonical off-topic ask refuses on a phrase: {ask!r}", v == "off", f"verdict {v!r}")
for ask in tc.OFF_TOPIC:
    v = tc.phrase_verdict(ask, off, on)
    check(f"no on phrase lets an off-topic ask through: {ask!r}", v != "on", f"verdict {v!r}")
for ask in tc.ON_TOPIC:
    v = tc.phrase_verdict(ask, off, on)
    check(f"on-topic ask passes on a phrase: {ask!r}", v == "on", f"verdict {v!r}")
for ask in tc.CANONICAL_ON:
    check(f"the issue's on-topic ask is in the on-topic set: {ask!r}", ask in tc.ON_TOPIC)
residual = [a for a in tc.OFF_TOPIC if tc.phrase_verdict(a, off, on) is None]
check("some off-topic paraphrases are left for the classifier, so the E2E run judges something",
      len(residual) >= 5, f"{len(residual)} left")
check("the vague on-topic asks reach the classifier (they carry no menu word)",
      all(tc.phrase_verdict(a, off, on) is None for a in tc.VAGUE_ON_TOPIC))
check("the rule matches whole words: 'rice' is not found in 'price', 'bowl' not in 'bowling'",
      tc.phrase_verdict("what's the price", [], ["rice"]) is None
      and tc.phrase_verdict("take me bowling", [], ["bowl"]) is None
      and tc.phrase_verdict("Hot Dogs please", ["hot dog"], []) == "off")

print("== the on list knows the whole menu ==")
# The menu is the bulleted block between "The Hex & Cauldron menu." and the hours paragraph. A bullet's
# continuation lines are indented deeper and belong to it.
block = persona.split("The Hex & Cauldron menu.", 1)[-1].split("Hours and locations.", 1)[0]
check("the persona's menu block is found", "Hours and locations." in persona and "- Protein:" in block)
bullets: list[str] = []
for line in block.splitlines():
    if line.strip().startswith("- "):
        bullets.append(line.strip()[2:])
    elif bullets and line.strip():
        bullets[-1] += " " + line.strip()
items = []
for bullet in bullets:
    body = re.sub(r"\([^)]*\)", "", bullet.split(":", 1)[1])
    items += [i.strip() for i in re.sub(r"\s+", " ", body).split(",") if i.strip()]
check("the menu parses into its items", len(items) >= 30, f"{len(items)} items")
for item in items:
    check(f"menu item reads as on-topic: {item!r}", tc.phrase_verdict(f"tell me about {item}", off, on) == "on")

print("== the refusal and the persona ==")
refusal = (env.get("TOPIC_REFUSAL") or "").lower()
for word in ("menu", "hours", "locations"):
    check(f"the refusal offers the {word}", word in refusal, refusal)
check("the refusal stays polite and points at an order", "order" in refusal and "pick a base" in refusal)
check("the persona carries opening hours", re.search(r"open every day from \d+am to \d+pm", persona) is not None)
check("the persona carries its locations", "three cantinas" in persona and "Mandrake Row" in persona)
check("the persona does not restrict topics itself (the wide-open start needs it to answer anything)",
      "only talk burritos" not in persona and "off-topic" not in persona.lower())

print("== the terminal helpers ==")
for helper in ("guard-topic-on", "guard-topic-off"):
    check(f"{helper} is written and made executable",
          f'cat > "$HOME/{helper}"' in terminal and f'"$HOME"/{helper}' in terminal)
check("guard-topic-on flips topic=on and reads back what the proxy reports",
      '_pxkey "topic=on" topic' in terminal and "_pxkey()" in terminal)
check("guard-topic-on fails loudly on a guard-proxy without the topic stage",
      "This guard-proxy has no on-topic guard, so nothing changed" in terminal)
guards_on = terminal.split('cat > "$HOME/guards-on" <<\'EOS\'\n', 1)[1].split("\nEOS\n", 1)[0]
guards_off = terminal.split('cat > "$HOME/guards-off" <<\'EOS\'\n', 1)[1].split("\nEOS\n", 1)[0]
check("the guards-on and guards-off bodies are found", "_px" in guards_on and "_px" in guards_off)
check("guards-on leaves the on-topic guard off (it would refuse every challenge prompt)", "topic" not in guards_on)
check("guards-off turns the on-topic guard off too", '_px "topic=off"' in guards_off)
check("guards-status lists the on-topic guard", '"topic":"On-topic guard' in terminal)

print("== the classifier, when it is wired ==")
bt = [s for s in scanners.get("input_scanners", []) if s.get("type") == "BanTopics"]
if bt:
    params = bt[0].get("params", {})
    check("BanTopics topics are the measured set", params.get("topics") == tc.CLASSIFIER["topics"])
    check("BanTopics threshold is the measured one", params.get("threshold") == tc.CLASSIFIER["threshold"])
    check("BanTopics loads from a baked directory, never the Hub", bool(params.get("model_path")))
    src = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
    check("guard-proxy suppresses scanners per stage, so the injection classifier does not also ban topics",
          "scanners_suppress" in src)
else:
    # Not wired yet: the offline image does not carry the zero-shot model, and with lazy_load off a scanner
    # whose model is missing stops LLM Guard from starting, which would fail the injection classifier closed.
    print("  (BanTopics is not in scanners.yml yet; these checks arm when it is)")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nOn-topic guard contract holds")
