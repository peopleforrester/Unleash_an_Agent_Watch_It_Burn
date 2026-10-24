# ABOUTME: Turns the student lab page (gitops/ai-layer/web/lab.html) into Markdown an instructor can hand
# ABOUTME: out. verify/export-lab-text.sh writes challenges/LAB-TEXT.md with it; the test re-renders to compare.
"""The lab text as Markdown, rendered from the page and never edited by hand (#419).

The eight challenges, their attack prompts and their fixes exist only inside lab.html, a large HTML file
that is a page and not a document. This walks the instructions column (`section.guide`) and nothing
else: the top bar, the terminal column, scripts and comments are page furniture, not lab text.

What the page hides, the copy shows and says so:

* Every caret (`<details>`) is opened. Its label is printed as **▸ label** and its body follows as a
  quote, so a nested caret reads as a nested quote. That is where the student page keeps the hints, the
  "Stuck? Try this prompt" prompts and the fixes.
* The page serves two variants and picks one by cluster profile (`data-full` and `data-burn`, see the
  CSS in lab.html). Both are printed, each marked with the clusters it shows on.
* Elements the page never shows to a laptop reader are left out: the Datadog login box that only fills
  from the link's query string, and the small-screen note.

Standard library only, so it runs wherever the offline suite runs.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = REPO / "gitops/ai-layer/web/lab.html"
OUT = REPO / "challenges/LAB-TEXT.md"

# The header ends at this line and the rendered page starts after it. The test splits on it.
BODY_MARKER = "<!-- LAB TEXT BELOW: rendered from lab.html by verify/export-lab-text.sh -->"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
DROP = {"script", "style", "button", "svg", "iframe", "noscript"}
BLOCK = {"p", "div", "section", "ul", "ol", "li", "h1", "h2", "h3", "h4", "details", "summary", "pre",
         "header", "table"}

ONLY_COMMUNITY = "[Community cluster only]"
NOT_COMMUNITY = "[Not on the Community cluster]"


class Node:
    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node | str] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def find(self, tag: str, cls: str) -> "Node | None":
        for c in self.children:
            if isinstance(c, Node):
                if c.tag == tag and cls in c.classes:
                    return c
                hit = c.find(tag, cls)
                if hit is not None:
                    return hit
        return None


class Tree(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}))

    def handle_endtag(self, tag):
        # Close back to the matching open tag; a stray end tag with no opener is ignored.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(page: str) -> Node:
    t = Tree()
    t.feed(page)
    t.close()
    return t.root


def hidden(n: Node) -> bool:
    style = n.attrs.get("style", "").replace(" ", "")
    return (n.tag in DROP or "display:none" in style
            or n.classes & {"guidetoggle", "guideopen", "mobnote", "num"})


def raw_text(n: Node | str) -> str:
    if isinstance(n, str):
        return n
    if n.tag in DROP:
        return ""
    return "".join(raw_text(c) for c in n.children)


def escape(text: str) -> str:
    # Only what would change the meaning when rendered: emphasis, code spans, and `<word>` read as a tag.
    return re.sub(r"([\\*_`<])", r"\\\1", text)


def fence(body: str, lang: str = "") -> str:
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{body}\n{ticks}"


def variant(n: Node) -> str:
    if "data-burn" in n.attrs:
        return ONLY_COMMUNITY
    if "data-full" in n.attrs:
        return NOT_COMMUNITY
    return ""


def wrap(mark: str, inner: str, end: str | None = None) -> str:
    """`**x**` around inline text, with the spaces kept outside the markers so the emphasis still renders."""
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()):]
    return f"{lead}{mark}{core}{mark if end is None else end}{trail}"


def inline(n: Node | str) -> str:
    if isinstance(n, str):
        return escape(re.sub(r"\s+", " ", n))
    if hidden(n):
        return ""
    if n.tag == "br":
        return "\\\n"
    inner = "".join(inline(c) for c in n.children)
    if n.tag in ("b", "strong"):
        out = wrap("**", inner)
    elif n.tag in ("i", "em"):
        out = wrap("*", inner)
    elif n.tag == "code":
        code = re.sub(r"\s+", " ", raw_text(n)).strip()
        ticks = "``" if "`" in code else "`"
        out = f"{ticks}{code}{ticks}" if code else ""
    elif n.tag == "a" and n.attrs.get("href"):
        out = wrap("[", inner, f"]({n.attrs['href']})")
    else:
        out = inner
    mark = variant(n)
    if mark:
        out = wrap(f"{mark[:-1]}: ", out, "]")
    return out


def is_block(n: Node | str) -> bool:
    return isinstance(n, Node) and (n.tag in BLOCK or (n.tag == "a" and "fblink" in n.classes))


def quote(blocks: list[str]) -> list[str]:
    text = "\n\n".join(blocks)
    return ["\n".join(f"> {line}" if line else ">" for line in text.split("\n"))] if text else []


def block(n: Node) -> list[str]:
    if hidden(n):
        return []
    cls = n.classes
    if n.tag == "div" and "step" in cls:
        num = n.find("div", "num")
        title = n.find("div", "t")
        t = re.sub(r"\s+", " ", raw_text(title)).strip() if title else ""
        n_txt = raw_text(num).strip() if num else ""
        if n_txt.isdigit() and not t.startswith("Challenge"):
            t = f"Step {n_txt}: {t}"
        # Everything but the title bar. Not just div.b: a step whose closing tag is missing holds the
        # steps after it, the way a browser nests them, and those must still come out.
        rest = Node("div", {})
        rest.children = [c for c in n.children if not (isinstance(c, Node) and "h" in c.classes)]
        return [f"## {t}"] + children(rest)
    if n.tag == "div" and "cmd" in cls:
        text = raw_text(n).strip("\n").rstrip()
        if not text.strip():
            return []
        out = [fence(text, "" if "noterm" in cls else "bash")]
    elif n.tag == "pre":
        out = [fence(raw_text(n).strip("\n").rstrip())]
    elif n.tag in ("h1", "h2", "h3", "h4"):
        level = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}[n.tag]
        out = [f"{level} {''.join(inline(c) for c in n.children).strip()}"]
    elif n.tag == "details":
        summary = next((c for c in n.children if isinstance(c, Node) and c.tag == "summary"), None)
        label = re.sub(r"\s+", " ", raw_text(summary)).strip() if summary else "Details"
        rest = Node("div", {})
        rest.children = [c for c in n.children if c is not summary]
        out = [f"**▸ {escape(label)}**"] + quote(children(rest))
    elif n.tag in ("ul", "ol"):
        items = [c for c in n.children if isinstance(c, Node) and c.tag == "li" and not hidden(c)]
        lines = []
        for i, li in enumerate(items, 1):
            text = " ".join(children(li)).replace("\n", " ")
            mark = variant(li)
            if mark:
                text = f"*{mark}* {text}"
            lines.append(f"{'-' if n.tag == 'ul' else f'{i}.'} {text}")
        return ["\n".join(lines)] if lines else []
    elif n.tag == "a":
        out = [inline(n).strip()]
    else:
        out = children(n)
        if "warn" in cls and out:
            out[0] = f"⚠ {out[0]}"
    mark = variant(n)
    if mark and out:
        # One paragraph takes the mark in front, one block of another kind takes it on the line above.
        # Anything longer is fenced by a start and an end line, so the second paragraph of a variant is
        # not mistaken for text every cluster shows.
        if len(out) == 1 and (out[0][:1] not in ("`", ">", "#", "-", "*") or out[0].startswith("**")):
            out = [f"*{mark}* {out[0]}"]
        elif len(out) == 1:
            out = [f"*{mark}*"] + out
        else:
            out = [f"*{mark}* ⤵"] + out + [f"*{mark[:-1]}: ends]*"]
    return out


def children(n: Node) -> list[str]:
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        text = re.sub(r"[ \t]+", " ", "".join(run)).strip()
        text = re.sub(r" *\\\n *", "\\\n", text)
        if text:
            out.append(text)
        run.clear()

    for c in n.children:
        if is_block(c):
            flush()
            out.extend(block(c))
        else:
            run.append(inline(c))
    flush()
    return out


def render(page: str) -> str:
    """The Markdown body for the instructions column of lab.html."""
    guide = parse(page).find("section", "guide")
    if guide is None:
        raise SystemExit("lab.html has no <section class=\"guide\">: the page changed shape, update lab_text.py")
    return "\n\n".join(children(guide)) + "\n"


def blob_id(data: bytes) -> str:
    """The id `git hash-object` gives this content, computed without git."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def header(*, copied: str, commit: str, changed: str, blob: str) -> str:
    return f"""<!-- ABOUTME: The student lab text from gitops/ai-layer/web/lab.html as Markdown, for instructors to hand out.
     ABOUTME: Generated by verify/export-lab-text.sh; verify/test_lab_text_export.py fails when it is behind the page. -->
# Watch It Burn: the student lab text

> **Generated file, do not edit by hand.** To refresh it, commit `lab.html` first, then run
> `bash verify/export-lab-text.sh` and commit the result.

| | |
|---|---|
| Copied out | {copied} |
| Source | `gitops/ai-layer/web/lab.html` |
| Source commit | `{commit}` (the last commit to change lab.html, on {changed}) |
| Source blob | `{blob}` |

**Is this copy current?** It is current when `git hash-object gitops/ai-layer/web/lab.html` prints the
source blob above. `verify/test_lab_text_export.py` checks that and fails when the page has changed
since this copy was made.

**Which copy this is.** This is the **student** copy: the page served at `/lab` on every attendee
cluster, with instructions on the left and a terminal on the right. On that page the hints, the
"Stuck? Try this prompt" attack prompts and the fixes are behind closed carets, so a student tries
each challenge before seeing the answer. The presenter copy, with the prompts visible from the start,
is `/brief` (`gitops/ai-layer/web/brief.html`).

**How to read it.**

- Every caret is open here. **▸ Label** is the caret's label and the quoted text under it is what it
  opens to. A caret inside a caret is a quote inside a quote.
- `bash` blocks are terminal commands. Unlabelled blocks are text to paste into BurritoBot, or text
  the page shows as-is.
- The page shows one of two variants, depending on the cluster. Text marked
  **{ONLY_COMMUNITY}** shows only on the Community cluster (attackme), which has no guardrails
  installed. Text marked **{NOT_COMMUNITY}** shows on the admin and attendee clusters and not on
  the Community cluster. A mark on a line of its own covers the block under it; a mark ending in ⤵
  covers everything down to its matching "ends" line.
- Left out: the top bar, the terminal, the Datadog login box (it fills in from each student's own
  link), and a note shown only on small screens.

---

{BODY_MARKER}

"""


def body_of(doc: str) -> str:
    _, sep, body = doc.partition(BODY_MARKER + "\n\n")
    if not sep:
        raise ValueError(f"no body marker line in the export: {BODY_MARKER}")
    return body


def stamp(doc: str, field: str) -> str:
    m = re.search(rf"^\| {re.escape(field)} \| `?([^`|]+?)`? (?:\(|\|)", doc, re.M)
    if not m:
        raise ValueError(f"no '{field}' row in the export header")
    return m.group(1)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", required=True, help="the last commit that changed lab.html")
    ap.add_argument("--changed", required=True, help="that commit's date, YYYY-MM-DD")
    ap.add_argument("--copied", required=True, help="today's date, YYYY-MM-DD")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    a = ap.parse_args(argv)

    data = LAB.read_bytes()
    body = render(data.decode("utf-8"))
    blob = blob_id(data)
    if a.out.exists():
        old = a.out.read_text(encoding="utf-8")
        # Unchanged page, unchanged rendering: keep the old file, so the date says when the text last moved.
        if (BODY_MARKER in old and body_of(old) == body and stamp(old, "Source blob") == blob
                and stamp(old, "Source commit") == a.commit):
            print(f"{a.out.relative_to(REPO) if a.out.is_relative_to(REPO) else a.out}: already current "
                  f"(copied {stamp(old, 'Copied out')}), not rewritten")
            return 0
    a.out.write_text(header(copied=a.copied, commit=a.commit, changed=a.changed, blob=blob) + body,
                     encoding="utf-8")
    words = len(re.findall(r"\w+", body))
    print(f"wrote {a.out} from lab.html {a.commit[:7]} ({words} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
