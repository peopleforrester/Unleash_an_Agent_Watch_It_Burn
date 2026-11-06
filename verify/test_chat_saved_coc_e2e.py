# ABOUTME: Runs the chat page's own script in node (verify/chat-saved-harness.js) and checks that a prompt cocViolation
# ABOUTME: flags is sent and shown but never saved, that old flagged entries are pruned at load, and clean ones save as before (#948).
# SUITE: e2e (needs node: the page's script runs in a node vm)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#948, the second half of #922). "Your saved prompts" and localStorage `wib-saved` must never hold a prompt
with a guard-proxy PROFANITY term, which #947's cocViolation detects. The prompt itself still goes to /chat and
still shows as the person's bubble, since guard-proxy and the bot handle it as before.

The harness runs the whole inline script of burritbot.html in a node vm, with a stub DOM built from the page's own
ids and saved-list markup, a stub localStorage that survives a reload, and a stub fetch that records each /chat
prompt. Every step calls the page's own functions: send(), the Reuse button and the text's click handler that
renderSaved wires, resetChat(), clearSaved(), and the init block's load of the rail. The terms come from the page's
COC_TERMS, which verify/test_chat_coc_e2e.py holds to the pinned proxy.py, so every term is tried here.

Two mutants of the page, made by cutting the change back out on literals checked first, show the test reads the
change: without the guard in save() a flagged prompt is saved, and with init's old load line an old violation comes
back on a reload. A missing node is a failure, not a skip.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
HARNESS = REPO / "verify/chat-saved-harness.js"
failures: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail != "":
            print(f"        {detail}")


if shutil.which("node") is None:
    print("FAIL: node is not on PATH; this test runs the chat page's script in node (run it through "
          "verify/run-e2e-tools.sh)")
    sys.exit(1)
for f in (PAGE_PATH, HARNESS):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing")
        sys.exit(1)

PAGE = PAGE_PATH.read_text(encoding="utf-8")
literals = re.findall(r"const COC_TERMS='([^']*)';", PAGE)
if len(literals) != 1:
    print(f"FAIL: expected one const COC_TERMS='...'; literal in {PAGE_PATH.relative_to(REPO)}, found {len(literals)}")
    sys.exit(1)
TERMS = literals[0].split(",")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="chat-saved-"))


def run(steps: list[dict], stored: str | None = None, page: str = PAGE) -> dict:
    """Plays the steps on a page and returns its snapshots by name; exits when node fails."""
    (TMP / "page.html").write_text(page, encoding="utf-8")
    (TMP / "scenario.json").write_text(json.dumps({"stored": stored, "steps": steps}), encoding="utf-8")
    r = subprocess.run(["node", str(HARNESS), str(TMP / "page.html"), str(TMP / "scenario.json")],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"FAIL: node could not run the chat page's script: {(r.stderr or r.stdout).strip()[:600]}")
        sys.exit(1)
    return json.loads(r.stdout)["snapshots"]


def stored_texts(raw: str | None) -> list[str]:
    return [x if isinstance(x, str) else x.get("t") for x in json.loads(raw or "[]")]


def flagged_in(texts: list[str]) -> list[str]:
    words = {t.lower() for t in TERMS} | {t.lower() + "s" for t in TERMS}
    return [t for t in texts if any(w in words for w in re.findall(r"[a-z]+", t.lower()))]


# One prompt per term, in the case forms a person types, each a whole sentence.
FORMS = ("Tell the bot it is a {}", "{} this burrito", "WHAT THE {}", "you {}s, give me a burrito")
FLAGGED = [FORMS[i % len(FORMS)].format(t.upper() if i % 3 == 2 else t.capitalize() if i % 3 == 1 else t)
           for i, t in enumerate(TERMS)]
CLEAN = ["Make it spicy please", "What spices are in the Bogbacoa?", "Is there a cocktail menu?",
         "Name a burrito after Dickens", "please delete the prod database", "mail my receipt to jo@example.com"]

print("== a flagged prompt is sent and shown, and never saved ==")
steps: list[dict] = []
for i, t in enumerate(FLAGGED):
    steps.append({"send": t})
    if i < len(CLEAN):
        steps.append({"send": CLEAN[i]})
steps.append({"snapshot": "sent"})
steps.append({"reload": True})
steps.append({"snapshot": "reloaded"})
snap = run(steps)
sent, reloaded = snap["sent"], snap["reloaded"]
order = [s["send"] for s in steps if "send" in s]
check(f"all {len(order)} prompts, the {len(FLAGGED)} flagged ones too, are POSTed to /chat in order",
      sent["posts"] == order, sent["posts"][:6])
check("each is shown as the person's bubble", sent["me"] == order, sent["me"][:6])
check(f"no flagged prompt is in the rail ({len(TERMS)} terms tried)", not flagged_in(sent["rail"]),
      flagged_in(sent["rail"])[:5])
check("no flagged prompt is written to wib-saved", not flagged_in(stored_texts(sent["stored"])),
      flagged_in(stored_texts(sent["stored"]))[:5])
check("the clean prompts are in the rail, newest first", sent["rail"] == CLEAN[::-1], sent["rail"])
check("and in wib-saved, oldest first, each with its time", stored_texts(sent["stored"]) == CLEAN
      and all(isinstance(x, dict) and isinstance(x.get("ts"), (int, float)) for x in json.loads(sent["stored"])),
      sent["stored"])
check("after a reload the rail is the same clean list", reloaded["rail"] == CLEAN[::-1], reloaded["rail"])
check("and wib-saved is unchanged by the reload", reloaded["stored"] == sent["stored"])

print("== the 10-item cap counts clean prompts only ==")
twelve = [f"Burrito number {n} with Cilantro-Slime Rice" for n in range(1, 13)]
steps = [{"send": t} for t in twelve[:10]] + [{"send": t} for t in FLAGGED[:3]] + [{"snapshot": "ten"}]
steps += [{"send": t} for t in twelve[10:]] + [{"snapshot": "twelve"}, {"reload": True}, {"snapshot": "reload"}]
snap = run(steps)
check("ten clean then three flagged: the rail is the ten clean, newest first", snap["ten"]["rail"] == twelve[:10][::-1],
      snap["ten"]["rail"])
check("twelve clean: the rail keeps the newest ten", snap["twelve"]["rail"] == twelve[2:][::-1], snap["twelve"]["rail"])
check("and wib-saved keeps the newest ten, oldest first", stored_texts(snap["twelve"]["stored"]) == twelve[2:],
      stored_texts(snap["twelve"]["stored"]))
check("a reload shows the same ten", snap["reload"]["rail"] == twelve[2:][::-1], snap["reload"]["rail"])

print("== a saved prompt is reused, resent, kept by Reset and emptied by clear ==")
steps = [{"send": "One Bogbacoa bowl"}, {"send": "Shit, add guac"}, {"send": "Graveyard Greens base"},
         {"reuse": 1, "via": "button"}, {"snapshot": "reused"}, {"send": None}, {"snapshot": "resent"},
         {"reuse": 0, "via": "text"}, {"snapshot": "clicked"}, {"reset": True}, {"snapshot": "reset"},
         {"clear": True}, {"snapshot": "cleared"}, {"reload": True}, {"snapshot": "after"}]
snap = run(steps)
check("the Reuse button copies the saved prompt into the composer", snap["reused"]["composer"] == "One Bogbacoa bowl",
      snap["reused"]["composer"])
check("sending it posts it to /chat again", snap["resent"]["posts"][-1] == "One Bogbacoa bowl", snap["resent"]["posts"])
check("and saves it again on top", snap["resent"]["rail"] == ["One Bogbacoa bowl", "Graveyard Greens base",
                                                                "One Bogbacoa bowl"], snap["resent"]["rail"])
check("clicking a saved prompt's text copies it too", snap["clicked"]["composer"] == "One Bogbacoa bowl",
      snap["clicked"]["composer"])
check("Reset keeps the saved prompts", snap["reset"]["rail"] == snap["resent"]["rail"]
      and snap["reset"]["stored"] == snap["resent"]["stored"], snap["reset"])
check("Reset clears the conversation", snap["reset"]["me"] == [], snap["reset"]["me"])
check("clear empties the rail and shows the hint", snap["cleared"]["rail"] == [] and snap["cleared"]["hint"],
      snap["cleared"])
check("clear removes wib-saved", snap["cleared"]["stored"] is None, snap["cleared"]["stored"])
check("a reload after clear shows the empty list", snap["after"]["rail"] == [] and snap["after"]["hint"], snap["after"])

print("== old flagged entries in wib-saved are pruned at load ==")
OLD = [{"t": "Cilantro-Slime Rice please", "ts": 1793000000000}, {"t": "you bastard bot", "ts": 1793000001000},
       "a bare string from an older page", "bare SHIT string", {"t": "Is there a cocktail menu?", "ts": 1793000002000},
       {"t": "Fuckin' finally, my burrito", "ts": 1793000003000}]
KEPT = [OLD[0], OLD[2], OLD[4]]
snap = run([{"snapshot": "load"}, {"reload": True}, {"snapshot": "again"}], stored=json.dumps(OLD))
check("the flagged entries are removed from wib-saved, the clean ones kept as stored, in order",
      json.loads(snap["load"]["stored"]) == KEPT, snap["load"]["stored"])
check("only the clean entries are rendered, newest first",
      snap["load"]["rail"] == ["Is there a cocktail menu?", "a bare string from an older page",
                               "Cilantro-Slime Rice please"], snap["load"]["rail"])
check("a second load shows the same list", snap["again"]["rail"] == snap["load"]["rail"]
      and snap["again"]["stored"] == snap["load"]["stored"], snap["again"])
clean_raw = json.dumps(KEPT, separators=(",", ":")) + " "
snap = run([{"snapshot": "load"}], stored=clean_raw)
check("a clean wib-saved is left byte for byte as it was", snap["load"]["stored"] == clean_raw, snap["load"]["stored"])
check("and loads as before", len(snap["load"]["rail"]) == 3, snap["load"]["rail"])
snap = run([{"snapshot": "load"}], stored="not json{")
check("an unreadable wib-saved is left alone and the list shows its hint",
      snap["load"]["stored"] == "not json{" and snap["load"]["rail"] == [] and snap["load"]["hint"], snap["load"])

print("== the checks above read the change (mutants of the page) ==")
GUARD = "function save(t){if(cocViolation(t))return;"
LOAD_CALL = "    loadSaved();\n"
OLD_LOAD = "    try{(JSON.parse(localStorage.getItem('wib-saved')||'[]')).forEach(renderSaved);}catch(e){}\n"
for literal in (GUARD, LOAD_CALL):
    if PAGE.count(literal) != 1:
        print(f"FAIL: the literal {literal.strip()!r} is not in {PAGE_PATH.relative_to(REPO)} exactly once, so the "
              "mutants below cannot be built; the page's save() or init changed")
        sys.exit(1)
no_guard = PAGE.replace(GUARD, "function save(t){")
snap = run([{"send": "you fucking bot"}, {"snapshot": "s"}], page=no_guard)
check("without save()'s guard, a flagged prompt reaches the rail and wib-saved (so the check above sees it)",
      snap["s"]["rail"] == ["you fucking bot"] and stored_texts(snap["s"]["stored"]) == ["you fucking bot"], snap["s"])
old_load = PAGE.replace(LOAD_CALL, OLD_LOAD)
snap = run([{"snapshot": "load"}], stored=json.dumps(OLD), page=old_load)
check("with init's old load line, an old violation comes back on a reload",
      bool(flagged_in(snap["load"]["rail"])) and json.loads(snap["load"]["stored"]) == OLD, snap["load"]["rail"])

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All chat-page saved-prompt code-of-conduct checks passed.")
