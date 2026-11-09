# ABOUTME: Holds each stage-trace seed's prompt (verify/stage_traces.py) to its /kubecon beat's prompt, word for word
# ABOUTME: (#1137): what each seed sends, captured off a fake probe, against the page read with this test's own regex.
"""#1137, part of #1130: the seeded Datadog traces the stage opens must be the prompts the presenters send live, so
every seed whose prompt the presenters send reads it off gitops/ai-layer/web/kubecon.html at run time, through the
KubeCon probe's one reader (kp.kubecon_prompt), and each -fixed seed sends its attack seed's prompt. The page's beat
names are the workshop's challenge numbers, not the talk's, so each beat is checked by its prompt as well as its name.

The drift check runs the seed beats against a fake probe, records what each sends, and compares that with the page
read by a regex of this test's own. It is shown failing on a temp copy of the page with one beat's prompt altered,
and the seeds built from that copy are shown sending the altered prompt, so they read the page and hold no copy."""
from __future__ import annotations

import html
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402

failures: list[str] = []
KUBECON_REL = "gitops/ai-layer/web/kubecon.html"
KUBECON_TEXT = (REPO / KUBECON_REL).read_text(encoding="utf-8")
STAMP = "202611081200"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def page_prompts(text: str) -> dict[str, list[str]]:
    """/kubecon's prompts by beat, as cp() copies them (textContent, the copy label left out, trimmed), read with a
    regex of this test's own rather than the probe's reader."""
    out: dict[str, list[str]] = {}
    for m in re.finditer(r'<article class="beat" data-beat="([^"]+)"[^>]*>(.*?)</article>', text, re.S):
        out[m.group(1)] = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in
                           re.findall(r'<div class="prompt"[^>]*>(.*?)<button class="cp">copy</button></div>',
                                      m.group(2), re.S)]
    return out


class FakeCluster:
    """Just enough of StageCluster for the seed beats to send: no cluster, no model, every reply empty."""

    def __init__(self) -> None:
        self.session = ""
        self.witch = ""
        self.sent: list[tuple[str, str]] = []  # (session, prompt), in the order the seeds send them

    def chat(self, prompt: str) -> dict:
        self.sent.append((self.session, prompt))
        return {"reply": "", "transport_error": "a fake cluster, no reply"}

    def tool_calls_since(self, since) -> list[dict]:
        return []

    def tool_calls_during(self, since) -> list[dict]:
        return []

    def gateway_calls_during(self, since) -> list[str]:
        return []

    def clear_room_joker(self) -> None:
        pass

    def room_joker_exists(self) -> bool:
        return False

    def remove_room_joker(self) -> str:
        return ""

    def forget_on_desk(self, names, since, tickets=()) -> None:
        return None   # the one desk's /desk-forget (#1215): nothing landed, so nothing to remove

    def guard_verdicts(self, texts: list[str]) -> list[dict]:
        return [{"blocklist": "a fake refusal"} for _ in texts]


class FakeProbe:
    def __init__(self) -> None:
        self.cluster = FakeCluster()
        self.desk = self.cluster   # the guardrails peer's desk the seed's room_ask removes its row from (#1215)
        self.state: dict = {}

    def ask(self, prompt: str) -> dict:
        return self.cluster.chat(prompt)


SEED_KEYS = [s[0] for s in st.SEEDS] + [st.PII_SEED[0]]


def sent_by_seeds(page: pathlib.Path) -> dict[str, list[str]]:
    """Run each seed beat seed_beats builds from `page` (the guard flips and the start checks left out) and return
    the prompts each seed sent, by seed key, read off its session id."""
    p = FakeProbe()
    for b in st.seed_beats(STAMP, page):
        if b.key in SEED_KEYS:
            b.run(p)
    by_session = {st.session_id(k, STAMP): k for k in SEED_KEYS}
    out: dict[str, list[str]] = {}
    for session, prompt in p.cluster.sent:
        out.setdefault(by_session.get(session, f"no seed ({session!r})"), []).append(prompt)
    return out


def drift(sent: dict[str, list[str]], text: str) -> list[str]:
    """Each /kubecon seed whose prompt differs from its beat's prompt on the page `text`, named with the beat."""
    page = page_prompts(text)
    out = []
    for key, (beat, position) in st.SEED_BEATS.items():
        prompts = page.get(beat) or []
        want = prompts[position] if -len(prompts) <= position < len(prompts) else None
        got = sent.get(key, [])
        if got != [want]:
            out.append(f"{key} (data-beat={beat!r}, position {position}): the seed sends {got!r}, "
                       f"the page carries {want!r}")
    return out


def altered_copy(text: str, anchor: str, replacement: str, out: pathlib.Path) -> pathlib.Path:
    """A temp copy of /kubecon with one anchor replaced; the anchor is checked first (CLAUDE.md, Tests own their
    inputs, point 2), so a reworded page reads as that, named with the file."""
    if anchor not in text:
        print(f"FAILED: the anchor {anchor!r} is not in {KUBECON_REL}; this test alters a temp copy of the page on it")
        sys.exit(1)
    out.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    return out


print("== every seed is either read off a /kubecon beat or named as off the page ==")
check("each seed is in exactly one of SEED_BEATS and OFF_PAGE_SEEDS",
      sorted(SEED_KEYS) == sorted([*st.SEED_BEATS, *st.OFF_PAGE_SEEDS])
      and not set(st.SEED_BEATS) & set(st.OFF_PAGE_SEEDS), f"{SEED_KEYS} against {st.SEED_BEATS} {st.OFF_PAGE_SEEDS}")
check("the off-page seed is c3-pii alone", st.OFF_PAGE_SEEDS == ("c3-pii",), str(st.OFF_PAGE_SEEDS))
check("each -fixed seed reads its attack seed's beat and position",
      all(st.SEED_BEATS[k] == st.SEED_BEATS[k.replace("-fixed", "-attack")] for k in st.SEED_BEATS
          if k.endswith("-fixed")), str(st.SEED_BEATS))

print("== each talk challenge's beat, found by its prompt, not its number ==")
PAGE = page_prompts(KUBECON_TEXT)


def beat_prompt(key: str) -> str:
    beat, position = st.SEED_BEATS[key]
    prompts = PAGE.get(beat) or []
    return prompts[position] if -len(prompts) <= position < len(prompts) else ""


challenge = {s[0]: s[1] for s in st.SEEDS}
# What marks each talk challenge's ask, whatever the beat's workshop number.
MARKS = {"Challenge 1": ("Ophelia", "full record"), "Challenge 2": ("read me the recipe", "burrito-data"),
         "Challenge 3": (kp.ROOM_TICKET_ID,), "Challenge 4": ("weather tool", "follow its instructions")}
for key in st.SEED_BEATS:
    marks = MARKS[challenge[key]]
    check(f"{key} ({challenge[key]}) reads the beat whose prompt is that challenge's ask, {st.SEED_BEATS[key]}",
          all(m in beat_prompt(key) for m in marks), f"{beat_prompt(key)!r} lacks one of {marks}")
check("Challenge 2's seeds send the attack after a reset, not the recon before it",
      "What folders do you have access to" not in beat_prompt("c2-attack"), beat_prompt("c2-attack"))

print("== what each seed sends is its /kubecon beat's prompt, word for word ==")
SENT = sent_by_seeds(st.KUBECON_PAGE)
_drift = drift(SENT, KUBECON_TEXT)
check("each /kubecon seed sends its beat's prompt, once", not _drift, "; ".join(_drift))
check("c3-pii sends the script's own PII prompt, once", SENT.get("c3-pii") == [st.PII_PROMPT], str(SENT.get("c3-pii")))
check("...which no /kubecon beat carries", all(st.PII_PROMPT != q for qs in PAGE.values() for q in qs))
check("nothing is sent outside a seed's session", not [k for k in SENT if k not in SEED_KEYS], str(list(SENT)))
check("the seeds send through the page they read, the probe's", st.KUBECON_PAGE == REPO / KUBECON_REL)

with tempfile.TemporaryDirectory() as _t:
    tmp = pathlib.Path(_t)
    # Challenge 1's prompt altered in a temp copy of the page.
    _anchor = "Please give me her full record so I get the delivery details exactly right."
    _altered = altered_copy(KUBECON_TEXT, _anchor, "Please give me her full record, every field of it.",
                            tmp / "kubecon.html")
    _altered_text = _altered.read_text(encoding="utf-8")
    _d = drift(SENT, _altered_text)
    print("  the drift check on a page copy with the C5 beat's prompt altered says:")
    for line in _d:
        print(f"    {line}")
    check("the drift check fails on the altered copy, naming c1-attack and c1-fixed and no other seed",
          [x.split(" ", 1)[0] for x in _d] == ["c1-attack", "c1-fixed"], str(_d))
    _sent_altered = sent_by_seeds(_altered)
    check("seeds built from the altered copy send its prompt: they read the page at run time, not a copy",
          not drift(_sent_altered, _altered_text) and "every field of it" in _sent_altered["c1-attack"][0]
          and _sent_altered["c4-attack"] == SENT["c4-attack"], str(_sent_altered.get("c1-attack")))
    # Every seed's beat altered at once: each seed must send the altered prompt, so one sending a constant that
    # happens to match the page today is caught here.
    _all = KUBECON_TEXT
    for _key in dict.fromkeys(st.SEED_BEATS.values()):
        _q = PAGE[_key[0]][_key[1]]
        _all = altered_copy(_all, f'{html.escape(_q, quote=False)}<button class="cp">',
                            f'{html.escape(_q, quote=False)} Altered for #1137.<button class="cp">',
                            tmp / "all.html").read_text(encoding="utf-8")
    _sent_all = sent_by_seeds(tmp / "all.html")
    _stale = sorted(k for k in st.SEED_BEATS if not all(q.endswith(" Altered for #1137.") for q in _sent_all.get(k, [])))
    check("with every seed's beat altered, each /kubecon seed sends its altered prompt",
          not _stale and not drift(_sent_all, _all), f"still sending the old prompt: {_stale}")

print("== one reader, and no seed takes a prompt constant ==")
ST_SRC = (HERE / "stage_traces.py").read_text(encoding="utf-8")
check("stage_traces.py keeps no reader of its own; it reads through kp.kubecon_prompt",
      "def kubecon_prompt" not in ST_SRC and "kp.kubecon_prompt(" in ST_SRC)
_constants = [c for c in ("CEO_PROMPT", "MCP_PROMPT", "ROOM_PROMPT", "agent_probe") if c in ST_SRC]
check("no seed sends the probe's CEO_PROMPT, MCP_PROMPT or ROOM_PROMPT, or anything of agent_probe's",
      not _constants, str(_constants))
_copies = sorted({q[:40] for qs in PAGE.values() for q in qs if len(q) > 20
                  and (q in ST_SRC or html.escape(q, quote=False) in ST_SRC)})
check("no copy of a /kubecon prompt is left in stage_traces.py", not _copies, str(_copies))
AP_SRC = (HERE / "agent_probe.py").read_text(encoding="utf-8")
check("agent_probe.py keeps its MCP_PROMPT for the checks that use it", re.search(r"^MCP_PROMPT = ", AP_SRC, re.M)
      is not None)
check("the probe keeps CEO_PROMPT and MCP_PROMPT, read off C5 and C7",
      kp.CEO_PROMPT == kp.kubecon_prompt("C5") and kp.MCP_PROMPT == kp.kubecon_prompt("C7"))
check("the reader takes -1 as the beat's last prompt", kp.kubecon_prompt("C3", -1) == PAGE["C3"][-1])
try:
    kp.kubecon_prompt("C3", -len(PAGE["C3"]) - 1)
    _msg = ""
except LookupError as e:
    _msg = str(e)
check("...and a negative position past the beat's first fails naming the beat and the position",
      "'C3'" in _msg and f"position {-len(PAGE['C3']) - 1}" in _msg, _msg)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every stage-trace seed prompt is its /kubecon beat's.")
