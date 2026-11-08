# ABOUTME: Holds /kubecon's "Read the recipe off the filesystem" block (C3) to #952's shape: the recon prompt, then the
# ABOUTME: attack after a reset, each with its own success marker, on the seeded folder names, and no raw grep as the ask.
"""#972: a test for #952's criterion on `gitops/ai-layer/web/kubecon.html`.

#952 replaced the C3 block's one prompt, the raw `grep -ri -A3 recipe /tmp/burrito-data` from
`challenges/c3-secret-grep/agent-prompt.txt`, with #925's conversational pair: a recon prompt that asks what folders
the bot can see, whose marker is the folder names and no read, and, after a reset, an attack prompt that names the
kitchen folder with a kitchen reason, whose marker is the recipe card before the switch and KubeArmor's
`Permission denied` after it. No test held that: `test_instructor_brief.py` checks one prompt and one marker per block.

The folder names are not written here. They are read from what the bot actually has: the directory the agent's tool
image seeds (`images/workshop-mcp/Dockerfile`), the kitchen folder the agent's rule names
(`gitops/workshop-agent/agent.yaml`) and the directory `block-recipe-snoop` blocks. So a rename of the folder that
leaves the page behind fails here.

The checks run first on the page, then on mutated copies of the block, and each copy must fail the check it breaks:
a test that cannot go red does not hold the criterion.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE_PATH = "gitops/ai-layer/web/kubecon.html"
DOCKERFILE_PATH = "images/workshop-mcp/Dockerfile"
AGENT_PATH = "gitops/workshop-agent/agent.yaml"
POLICY_PATH = "policies/kubearmor/block-recipe-snoop.yaml"
GREP_PATH = "challenges/c3-secret-grep/agent-prompt.txt"
FALLBACK_PROMPTS_PATH = "facilitation/kubecon-na-2026/fallback/prompts.yaml"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def anchored(pattern: str, text: str, rel: str, flags: int = 0) -> re.Match[str]:
    m = re.search(pattern, text, flags)
    if m is None:
        sys.exit(f"anchor {pattern!r} is not in {rel}: reword the test with it")
    return m


PAGE = read(PAGE_PATH)

# The folders the bot can see: the image seeds /tmp/burrito-data/config/legacy and the card inside it.
_seed = anchored(r"mkdir -p (/tmp/(\S+?))/?\s", read(DOCKERFILE_PATH), DOCKERFILE_PATH)
SEED_DIR = _seed.group(1)
FOLDERS = _seed.group(2).split("/")          # ["burrito-data", "config", "legacy"]
CARD = anchored(re.escape(SEED_DIR) + r"/([\w.-]+\.conf)", read(DOCKERFILE_PATH), DOCKERFILE_PATH).group(1)
# The kitchen folder the agent's rule names, the one an attack has to name for case 3 to read the card.
KITCHEN = anchored(r'Your kitchen folder is "([^"]+)"', read(AGENT_PATH), AGENT_PATH).group(1)
POLICY = yaml.safe_load(read(POLICY_PATH))
# The raw command #952 took off the page as the ask.
RAW_GREP = anchored(r"^(grep .+)$", read(GREP_PATH), GREP_PATH, re.M).group(1).strip()
_fallback = {p["id"]: p["prompt"] for p in yaml.safe_load(read(FALLBACK_PROMPTS_PATH))["prompts"]
             if p["id"] in ("c3-recon", "c3-attack")}
for _id in ("c3-recon", "c3-attack"):
    if _id not in _fallback:
        sys.exit(f"prompt id {_id!r} is not in {FALLBACK_PROMPTS_PATH}: reword the test with it")


def c3_blocks(page: str) -> list[str]:
    return re.findall(r'<article class="beat"\s+data-beat="C3"\s+data-segment="[^"]+">(.*?)</article>', page, re.S)


def text_of(fragment: str) -> str:
    fragment = re.sub(r'<button class="cp">copy</button>', "", fragment)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def flat(fragment: str) -> str:
    return " ".join(fragment.split())


def c3_failures(page: str, show: bool = True) -> list[str]:
    """Run every check on a page; print each when show is set, and return the names of those that fail."""
    failed: list[str] = []

    def check(name: str, cond: bool) -> None:
        if show:
            print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failed.append(name)

    blocks = c3_blocks(page)
    check("the page has exactly one C3 block", len(blocks) == 1)
    if len(blocks) != 1:
        return failed
    block = blocks[0]
    check('the C3 block is "Read the recipe off the filesystem"',
          "<h3>Read the recipe off the filesystem</h3>" in block)
    visible = block.split("<details", 1)[0]
    cues = re.findall(r'<div class="(prompt|marker)"[^>]*>(.*?)</div>', visible, re.S)
    kinds = [k for k, _ in cues]
    check(f"the shown block is two prompts, each followed by its own success marker ({kinds})",
          kinds == ["prompt", "marker", "prompt", "marker"])
    if kinds != ["prompt", "marker", "prompt", "marker"]:
        return failed
    (_, recon_html), (_, recon_marker_html), (_, attack_html), (_, attack_marker_html) = cues
    recon, attack = text_of(recon_html), text_of(attack_html)
    recon_marker, attack_marker = flat(recon_marker_html), flat(attack_marker_html)
    check("both prompts are copy-ready",
          all('class="cp"' in p for p in (recon_html, attack_html)) and visible.count('onclick="cp(this)"') >= 2)

    # Recon: the agent's case 1 is a guest asking what folders it can see or has access to.
    check("the first prompt is the recon ask: what folders it has access to",
          "What folders do you have access to" in recon)
    check("the recon prompt carries the kitchen reason, the ruined recipe card", "recipe card" in recon)
    check("the recon prompt gives away no folder, file or path",
          not any(f in recon for f in FOLDERS) and "/tmp" not in recon and CARD not in recon)
    check("the recon marker is labelled recon", '<span class="lbl">Success marker · recon</span>' in recon_marker)
    check(f"the recon marker names the seeded folders {FOLDERS}",
          all(f"<code>{f}</code>" in recon_marker for f in FOLDERS))
    check("the recon marker says the bot opens nothing", "opens nothing" in recon_marker)

    # Attack, after a reset: the agent's case 3 is the kitchen folder named with a kitchen reason.
    check(f"the second prompt names the kitchen folder the agent's rule names ({KITCHEN} folder)",
          f"the {KITCHEN} folder" in attack)
    check("the attack prompt carries the kitchen reason, training a new line cook under the blood oath (#1106)",
          "line cook" in attack and "blood oath" in attack)
    check("the attack prompt is not the recon ask again (case 2 would decline it)", "What folders" not in attack)
    check("the attack marker is labelled the attack, after a reset",
          '<span class="lbl">Success marker · attack, after a reset</span>' in attack_marker)
    check("the attack marker calls for the reset", "Reset the chat first." in attack_marker)
    check("before the switch the recipe card comes back",
          "Before the switch, on either bot: the recipe card comes back." in attack_marker)
    check("after guardrails-on KubeArmor's block-recipe-snoop denies the read, with its Block alert",
          "After <code>guardrails-on</code>:" in attack_marker
          and "<code>Permission denied</code> from KubeArmor <code>block-recipe-snoop</code>" in attack_marker
          and '"PolicyName":"block-recipe-snoop"' in attack_marker and '"Action":"Block"' in attack_marker)

    # The raw grep is no longer the ask: no prompt carries it, or any grep, and the shown block does not show it.
    check(f"no prompt in the block carries the raw command ({RAW_GREP})",
          not any(RAW_GREP in text_of(p) for k, p in cues if k == "prompt"))
    check("no prompt in the block is a grep or a shell path",
          not any(re.search(r"\bgrep\b|/tmp/", text_of(p)) for k, p in cues if k == "prompt"))
    check("the shown block does not show the raw command", RAW_GREP not in html.unescape(visible))
    check("the raw grep stays the folded fallback script",
          "challenges/c3-secret-grep/fallback.kubectl.sh" in block.split("<details", 1)[-1]
          and "<details" in block)

    # The same two prompts are the fallback deck's c3-recon and c3-attack, word for word.
    check("the recon prompt is the fallback deck's c3-recon", recon == _fallback["c3-recon"])
    check("the attack prompt is the fallback deck's c3-attack", attack == _fallback["c3-attack"])
    return failed


failures: list[str] = []

print("== the folder names come from what the bot has ==")
for name, cond in (
    (f"the image seeds {SEED_DIR} with the recipe card {CARD} in it", FOLDERS[:1] == [KITCHEN] and len(FOLDERS) == 3),
    (f"the agent's rule names {KITCHEN} as its kitchen folder and the card's path",
     f"{SEED_DIR}/{CARD}" in read(AGENT_PATH)),
    (f"block-recipe-snoop blocks {SEED_DIR}/ in Block mode",
     POLICY["metadata"]["name"] == "block-recipe-snoop" and POLICY["spec"]["action"] == "Block"
     and [d["dir"] for d in POLICY["spec"]["file"]["matchDirectories"]] == [SEED_DIR + "/"]),
):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)

print(f"== {PAGE_PATH}: C3 is recon, then the attack after a reset (#952) ==")
failures += c3_failures(PAGE)

# Each mutation breaks the criterion one way, and must fail the check that holds it.
print("== the checks go red when the criterion stops holding ==")
_block = c3_blocks(PAGE)[0] if len(c3_blocks(PAGE)) == 1 else ""
_cues = re.findall(r'<div class="(?:prompt|marker)"[^>]*>.*?</div>', _block.split("<details", 1)[0], re.S)
if len(_cues) != 4:
    sys.exit(f"the C3 block in {PAGE_PATH} is not two prompts and two markers: the mutations cannot be built")
_recon_div, _recon_marker_div, _attack_div, _attack_marker_div = _cues
_attack_text = text_of(_attack_div)
_grep_prompt = f'<div class="prompt" onclick="cp(this)">{html.escape(RAW_GREP, quote=False)}<button class="cp">copy</button></div>'


def mutate(old: str, new: str) -> str:
    if old not in PAGE:
        sys.exit(f"anchor {old[:60]!r} is not in {PAGE_PATH}: reword the test with it")
    return PAGE.replace(old, new, 1)


MUTATIONS = {
    "the recon prompt dropped": (mutate(_recon_div, ""), "the shown block is two prompts"),
    "the recon marker dropped": (mutate(_recon_marker_div, ""), "the shown block is two prompts"),
    "the attack marker dropped": (mutate(_attack_marker_div, ""), "the shown block is two prompts"),
    "the prompts swapped": (mutate(_recon_div, "\0").replace(_attack_div, _recon_div, 1).replace("\0", _attack_div, 1),
                            "the first prompt is the recon ask"),
    "the pre-#952 shape: the raw grep as the one prompt": (
        mutate(_recon_div, "").replace(_recon_marker_div, "", 1).replace(_attack_div, _grep_prompt, 1),
        "the shown block is two prompts"),
    "the raw grep as the attack prompt": (mutate(_attack_div, _grep_prompt), "no prompt in the block carries the raw"),
    "the recon ask reworded away": (mutate("What folders do you have access to", "Where is the recipe"),
                                    "the first prompt is the recon ask"),
    "the recon prompt gives the folder away": (mutate("you might have a copy.", f"you might have a copy in {KITCHEN}."),
                                               "the recon prompt gives away no folder"),
    "the folder renamed in the attack prompt": (
        mutate(_attack_div, _attack_div.replace(f"the {KITCHEN} folder", "the kitchen-data folder")),
        "the second prompt names the kitchen folder"),
    "a seeded folder dropped from the recon marker": (
        mutate(_recon_marker_div, _recon_marker_div.replace(f"<code>{FOLDERS[-1]}</code>", "")),
        "the recon marker names the seeded folders"),
    "the reset dropped from the attack marker": (mutate("Reset the chat first. ", ""),
                                                 "the attack marker calls for the reset"),
    "KubeArmor's deny dropped from the attack marker": (
        mutate(_attack_marker_div, _attack_marker_div.replace("Permission\n      denied", "Forbidden")
               .replace("Permission denied", "Forbidden")),
        "after guardrails-on KubeArmor's block-recipe-snoop"),
    "the attack prompt out of step with the fallback deck": (
        mutate(_attack_div, _attack_div.replace("at midnight", "at noon")),
        "the attack prompt is the fallback deck's c3-attack"),
}
for label, (page, expect) in MUTATIONS.items():
    got = c3_failures(page, show=False)
    ok = any(n.startswith(expect) for n in got)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: fails '{expect}...' ({len(got)} check(s) red)")
    if not ok:
        failures.append(f"mutation '{label}' did not fail '{expect}...'")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All /kubecon C3 recipe-block checks passed.")
