# ABOUTME: The texts the code-of-conduct spike (#1267) measures every candidate on: the stage's own text, read from the
# ABOUTME: repo at run time, the ROT13-encoded abuse set, the hard negatives, and a Tempo dump of observed /chat turns.
"""Corpora for the code-of-conduct spike.

stage_texts() is what the room and the presenters can put on screen or what the bot can echo, read from the files the
stage runs, so a change to them reaches the measurement:

    kubecon-prompt   every .prompt block on /kubecon (gitops/ai-layer/web/kubecon.html)
    page-text        the visible text of /kubecon, or of every page under gitops/ai-layer/web/ (measure.py), as sentences
    replay-prompt    every prompt in facilitation/kubecon-na-2026/fallback/prompts.yaml (the room's replay set)
    catalog-prompt   every quoted prompt in challenges/PROMPT-CATALOG.md
    probe-prompt     topic_cases' asks (verify/topic_cases.py); measure.py adds the KubeCon probe's own two prompts
    desk-ticket      every fixed ticket on the desk, HC-666 among them: subject, customer and body (ticket_site.py)
    witch-name       every name the chat page can give a visitor (ticket_site.NAME_SPACE), and its Joker slug
    tool-data        the MCP tools' descriptions and the data they return (workshop-mcp-server.py, server.py)
    agent-prompt     the agent's system prompt (gitops/workshop-agent/agent.yaml), split into lines
    cluster-data     the Secrets and ConfigMaps in gitops/ai-layer/resources.yaml the bot reads (the CEO record, the recipe)

Nothing here imports the stage modules: their string constants are read with ast, so no server starts.
"""
from __future__ import annotations

import ast
import codecs
import html
import html.parser
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


def _decode_lines(path: pathlib.Path) -> list[str]:
    return [codecs.decode(l, "rot13") for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def terms(which: str) -> list[str]:
    """The current guard-proxy list ("current") or the spike's proposed list ("proposed"), decoded."""
    return _decode_lines(HERE / f"terms-{which}.rot13")


def abuse_set() -> list[tuple[str, str]]:
    """(category, text) pairs: expletive, slur, hate, sexual, insult, threat, evasion, foreign."""
    out = []
    for line in (HERE / "abuse-set.rot13.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cat, text = line.split("\t", 1)
        out.append((cat, codecs.decode(text, "rot13")))
    return out


def hard_negatives() -> list[str]:
    return [l for l in (HERE / "hard-negatives.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


class _Visible(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.prompts: list[str] = []
        self._skip = 0
        self._prompt: list[str] | None = None
        self._depth = 0
        self._button = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        cls = dict(attrs).get("class") or ""
        if self._prompt is not None and tag == "div":
            self._depth += 1
        elif tag == "div" and "prompt" in cls.split():
            self._prompt, self._depth = [], 1
        if tag == "button":
            self._button += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "button" and self._button:
            self._button -= 1
        if self._prompt is not None and tag == "div":
            self._depth -= 1
            if not self._depth:
                self.prompts.append("".join(self._prompt).strip())
                self._prompt = None

    def handle_data(self, data):
        if self._skip:
            return
        self.chunks.append(data)
        if self._prompt is not None and not self._button:
            self._prompt.append(data)


def _sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = " ".join(para.split())
        if para:
            out.extend(s for s in _SENT.split(para) if s.strip())
    return out


def _module_strings(path: pathlib.Path) -> dict[str, object]:
    """Module-level assignments whose value is a literal (or an f-string-free concatenation), by name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError):
                pass
    return found


def _strings_in(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings_in(k) + _strings_in(v)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [s for v in value for s in _strings_in(v)]
    return []


def _tool_descriptions(path: pathlib.Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef):
            doc = ast.get_docstring(node)
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "tool":
                    for kw in dec.keywords:
                        if kw.arg == "description":
                            try:
                                out.append(ast.literal_eval(kw.value))
                            except ValueError:
                                pass
                    if doc:
                        out.append(doc)
            # return "..." literals in tool bodies are what the tool hands the model
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant) and isinstance(sub.value.value, str):
                    out.append(sub.value.value)
    return out


def _ticket_texts() -> list[str]:
    """The desk's fixed tickets, rebuilt from ticket_site.py's source: TICKETS' literal entries plus HC-666."""
    src = REPO / "gitops/ai-layer/ticket_site.py"
    consts = _module_strings(src)
    out = []
    for name in ("_ROOM_COMPLAINT",):
        if isinstance(consts.get(name), str):
            out.append(consts[name])
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:
        # TICKETS is keyed by names and its payloads are f-strings, so its string literals are collected from the
        # tree; an f-string's literal parts are joined, the image name it fills in left out
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and \
                node.targets[0].id in ("TICKETS", "ROOM_PAYLOAD", "C6_PAYLOAD"):
            if node.targets[0].id == "TICKETS":
                out.extend(sub.value for sub in ast.walk(node.value)
                           if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and " " in sub.value)
            else:
                out.append(" ".join(sub.value for sub in ast.walk(node.value)
                                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str)))
    out.extend(["card keeps failing at checkout", "Walk-in customer"])
    return out


def _witch_names() -> list[str]:
    consts = _module_strings(REPO / "gitops/ai-layer/ticket_site.py")
    names = [f"{f} the {c}" for f in consts["FIRST"] for c in consts["CREATURES"]]
    return names + ["joker-" + n.lower().replace(" ", "-") for n in names]


def _agent_prompt() -> list[str]:
    text = (REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")
    m = re.search(r"systemMessage: \|\n(.*?)(?=\n    \w+:|\Z)", text, re.S)
    block = m.group(1) if m else ""
    return [" ".join(l.split()) for l in block.splitlines() if len(l.split()) >= 3]


def _cluster_data() -> list[str]:
    """The Secrets and ConfigMaps the bot can read or leak (the CEO record, the recipe, the vault), by their values."""
    import yaml
    out = []
    for doc in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")):
        if isinstance(doc, dict) and doc.get("kind") in ("Secret", "ConfigMap"):
            for key in ("stringData", "data"):
                for v in (doc.get(key) or {}).values():
                    if isinstance(v, str) and len(v.split()) >= 2 and len(v) < 20000:
                        out.extend(_sentences(v))
    return out


def _replay_prompts() -> list[str]:
    import yaml
    doc = yaml.safe_load((REPO / "facilitation/kubecon-na-2026/fallback/prompts.yaml").read_text(encoding="utf-8"))
    return [p["prompt"] for p in doc.get("prompts", []) if p.get("prompt")]


def _catalog_prompts() -> list[str]:
    out, cur = [], []
    for line in (REPO / "challenges/PROMPT-CATALOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("> ") and not line.startswith("> **"):
            cur.append(line[2:])
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _probe_prompts() -> list[str]:
    """topic_cases' asks. The KubeCon probe's own two prompts (its order and CEO opener) are added by measure.py, not
    here: verify/test_coc_floor_spike.py reads this module, and a test reading the probe script would make it
    one of more than 30 readers, which the scope map counts as shared."""
    out = []
    for v in _module_strings(REPO / "verify/topic_cases.py").values():
        out.extend(s for s in _strings_in(v) if " " in s)
    return out


KUBECON_PAGE = REPO / "gitops/ai-layer/web/kubecon.html"


def stage_texts(pages: list[pathlib.Path] | None = None) -> list[tuple[str, str]]:
    """(source, text) for every stage text, deduplicated within a source. page-text reads the pages given, /kubecon
    alone by default: measure.py passes every page under gitops/ai-layer/web/. The offline test keeps the default,
    because the chat page names the KubeCon probe script, and the scope map would then count the test as reading
    that script, which more than 30 tests already read."""
    groups: dict[str, list[str]] = {}
    page = _Visible()
    page.feed(KUBECON_PAGE.read_text(encoding="utf-8"))
    groups["kubecon-prompt"] = page.prompts
    visible = []
    for p in pages or [KUBECON_PAGE]:
        v = _Visible()
        v.feed(p.read_text(encoding="utf-8"))
        visible.extend(_sentences(html.unescape("".join(v.chunks))))
    groups["page-text"] = visible
    groups["replay-prompt"] = _replay_prompts()
    groups["catalog-prompt"] = _catalog_prompts()
    groups["probe-prompt"] = _probe_prompts()
    groups["desk-ticket"] = _ticket_texts()
    groups["witch-name"] = _witch_names()
    mcp = _module_strings(REPO / "gitops/ai-layer/workshop-mcp-server.py")
    data = [json.dumps(mcp[k]) for k in ("_CUSTOMERS", "_INVENTORY", "_ORDERS", "_MARKETING") if k in mcp]
    groups["tool-data"] = data + _tool_descriptions(REPO / "gitops/ai-layer/workshop-mcp-server.py") \
        + _tool_descriptions(REPO / "gitops/ai-layer/server.py")
    groups["agent-prompt"] = _agent_prompt()
    groups["cluster-data"] = _cluster_data()
    out = []
    for src, texts in groups.items():
        seen = set()
        for t in texts:
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append((src, t))
    return out


def observed_turns(path: pathlib.Path) -> list[tuple[str, str]]:
    """("observed-prompt" | "observed-reply", text) from a pull_turns.py dump, deduplicated."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    out, seen = [], set()
    for turn in doc["turns"]:
        for kind, text in (("observed-prompt", turn.get("prompt")), ("observed-reply", turn.get("reply"))):
            if text and (kind, text) not in seen:
                seen.add((kind, text))
                out.append((kind, text))
    return out


if __name__ == "__main__":
    import collections
    st = stage_texts()
    print(collections.Counter(s for s, _ in st))
    print(len(abuse_set()), "abuse;", len(hard_negatives()), "hard negatives;", len(terms("proposed")), "proposed terms")
