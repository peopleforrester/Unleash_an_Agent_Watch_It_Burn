# ABOUTME: Pulls each /chat turn's prompt, reply and duration out of Tempo on an admin cluster for the code-of-conduct
# ABOUTME: spike (#1267), so every candidate floor is measured on the replies the bot really gave, not only on the repo.
"""Read-only: port-forwards service/tempo in namespace monitoring and reads traces; changes nothing on the cluster.

    python3 docs/research/2026-11-09-coc-floor/pull_turns.py --context watch-it-burn-private --days 7 \\
        --out "$TMPDIR/turns.json"

guard-proxy's `chat` span carries the prompt (gen_ai.input.messages) and the reply (gen_ai.output.messages); its
`POST /chat` server span carries the turn's wall time. The dump holds the text of real turns, so it is written to a
scratch path and not committed: the spike's README carries only what was measured on it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


def _text(messages: str | None) -> str:
    if not messages:
        return ""
    try:
        doc = json.loads(messages)
    except ValueError:
        return messages
    return "\n".join(p.get("content", "") for m in doc for p in m.get("parts", []) if p.get("type") == "text")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--port", type=int, default=13200)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pf = subprocess.Popen(["kubectl", "--context", a.context, "-n", "monitoring", "port-forward", "service/tempo",
                           f"{a.port}:3200"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{a.port}"
    try:
        for _ in range(30):
            try:
                _get(base, "/api/echo")
                break
            except Exception:
                time.sleep(1)
        end = int(time.time())
        start = end - a.days * 86400
        found = _get(base, "/api/search?" + urllib.parse.urlencode(
            {"q": '{ name = "chat" && span.gen_ai.input.messages != nil }', "start": start, "end": end,
             "limit": 5000, "spss": 10}))
        turns = []
        for t in found.get("traces", []):
            doc = _get(base, f"/api/v2/traces/{t['traceID']}")
            tr = doc.get("trace", doc)
            chat, post = None, None
            for rs in tr.get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    for sp in ss.get("spans", []):
                        if sp.get("name") == "chat":
                            chat = sp
                        elif sp.get("name") == "POST /chat":
                            post = sp
            if not chat:
                continue
            at = {x["key"]: x["value"].get("stringValue") for x in chat.get("attributes", [])}
            span = post or chat
            ms = (int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1e6
            turns.append({"trace": t["traceID"], "start": int(span["startTimeUnixNano"]) // 10**9,
                          "prompt": _text(at.get("gen_ai.input.messages")), "reply": _text(at.get("gen_ai.output.messages")),
                          "ms": round(ms, 1)})
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"context": a.context, "window": [start, end], "turns": turns}, fh)
        print(f"{len(turns)} turns from {a.context}, {a.days} days, written to {a.out}", file=sys.stderr)
        return 0
    finally:
        pf.terminate()


if __name__ == "__main__":
    sys.exit(main())
