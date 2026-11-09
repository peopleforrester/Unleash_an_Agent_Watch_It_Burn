# ABOUTME: Runs each code-of-conduct floor candidate (#1267) over the stage's text, observed /chat turns, the hard
# ABOUTME: negatives and the abuse set, and writes what each flagged and how long it took: results.json and a raw dump.
"""Measure the candidates.

    # the two term floors, standard library only
    python3 measure.py --turns "$TMPDIR/turns.json" --raw "$TMPDIR/raw.jsonl" --out results.json

    # plus LLM Guard's Toxicity model (onnxruntime, tokenizers, huggingface_hub) and two Bedrock guardrails in detect
    # mode (boto3, after `. "$HECATON_CLUSTER_ENV"`); see README.md for the guardrails' definition
    python3 measure.py --turns ... --raw ... --out results.json --toxicity \\
        --bedrock classic=<guardrail-id> --bedrock standard=<guardrail-id>

results.json holds counts, rates and timings only, and the stage-text hits by source; the raw dump holds each text
with its verdicts and is written to scratch, because observed turns are the room's words.

LLM Guard's Toxicity scanner, replicated: ProtectAI/unbiased-toxic-roberta-onnx (the ONNX export of
unitary/unbiased-toxic-roberta that llm_guard/input_scanners/toxicity.py loads), sigmoid per label, flagged when any of
toxicity, severe_toxicity, obscene, threat, insult, identity_attack, sexual_explicit scores over the threshold (0.5,
the input scanner's default; 0.7, the output scanner's), whole text, truncated at 512 tokens.

Bedrock: each guardrail sets HATE, INSULTS, SEXUAL, VIOLENCE and MISCONDUCT at HIGH with action NONE, and the managed
PROFANITY word list with action NONE, so ApplyGuardrail reports every detection with its confidence and blocks nothing.
A filter at strength S would block a detection whose confidence is at least S's cutoff: HIGH blocks LOW and up,
MEDIUM blocks MEDIUM and up, LOW blocks HIGH only. So one detect-mode guardrail answers every strength.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import pathlib
import statistics
import sys
import time

import corpus
import floor

TOXIC_LABELS = ("toxicity", "severe_toxicity", "obscene", "threat", "insult", "identity_attack", "sexual_explicit")
CONF = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
CUTOFF = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}  # strength -> lowest confidence it blocks
# The two classifiers would sit on /chat (and could on the desk), so they are measured on what /chat and the desk carry:
# the prompts, the tickets, the data the tools hand the model, the replies. The term floors run on every text.
CLASSIFIER_SOURCES = {"kubecon-prompt", "replay-prompt", "catalog-prompt", "probe-prompt", "desk-ticket", "tool-data",
                      "cluster-data", "observed-prompt", "observed-reply", "hard-negative", "abuse"}


def _probe_own_prompts() -> list[str]:
    """The KubeCon probe's two prompts that /kubecon does not carry: its burrito order and its friendly CEO opener."""
    found = corpus._module_strings(corpus.REPO / "verify/kubecon_probe.py")
    return [found[n] for n in ("ORDER_PROMPT", "FRIENDLY_CEO_PROMPT") if isinstance(found.get(n), str)]


def _texts(turns: pathlib.Path | None) -> list[dict]:
    pages = sorted((corpus.REPO / "gitops/ai-layer/web").glob("*.html"))
    rows = [{"source": s, "text": t} for s, t in corpus.stage_texts(pages)]
    rows += [{"source": "probe-prompt", "text": t} for t in _probe_own_prompts()]
    if turns:
        rows += [{"source": s, "text": t} for s, t in corpus.observed_turns(turns)]
    rows += [{"source": "hard-negative", "text": t} for t in corpus.hard_negatives()]
    rows += [{"source": "abuse", "category": c, "text": t} for c, t in corpus.abuse_set()]
    return rows


class Toxicity:
    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer
        self.np = np
        path = pathlib.Path(snapshot_download("ProtectAI/unbiased-toxic-roberta-onnx"))
        self.revision = path.name
        self.tok = Tokenizer.from_file(str(path / "tokenizer.json"))
        self.tok.enable_truncation(512)
        cfg = json.loads((path / "config.json").read_text())
        self.labels = [cfg["id2label"][str(i)] for i in range(len(cfg["id2label"]))]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self.sess = ort.InferenceSession(str(path / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.sess.get_inputs()]

    def score(self, text: str) -> tuple[float, str, float]:
        """(max toxic-label score, that label, milliseconds)."""
        t0 = time.perf_counter()
        enc = self.tok.encode(text)
        feed = {"input_ids": self.np.array([enc.ids], dtype=self.np.int64),
                "attention_mask": self.np.array([enc.attention_mask], dtype=self.np.int64)}
        logits = self.sess.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0][0]
        probs = 1 / (1 + self.np.exp(-logits))
        ms = (time.perf_counter() - t0) * 1000
        best = max((float(probs[i]), self.labels[i]) for i in range(len(self.labels)) if self.labels[i] in TOXIC_LABELS)
        return best[0], best[1], ms


class Bedrock:
    def __init__(self, guardrail: str):
        import boto3
        from botocore.config import Config
        self.id = guardrail
        self.c = boto3.client("bedrock-runtime", region_name="us-west-2",
                              config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))

    def assess(self, text: str, source: str = "INPUT") -> dict:
        t0 = time.perf_counter()
        r = self.c.apply_guardrail(guardrailIdentifier=self.id, guardrailVersion="DRAFT", source=source,
                                   content=[{"text": {"text": text}}])
        ms = (time.perf_counter() - t0) * 1000
        filters, words, server_ms, units = {}, [], None, 0
        for a in r.get("assessments", []):
            for f in a.get("contentPolicy", {}).get("filters", []):
                if f.get("detected"):
                    filters[f["type"]] = max(filters.get(f["type"], 0), CONF[f["confidence"]])
            for w in a.get("wordPolicy", {}).get("managedWordLists", []):
                if w.get("detected", True):
                    words.append(w.get("match", ""))
            m = a.get("invocationMetrics", {})
            server_ms = m.get("guardrailProcessingLatency", server_ms)
        units = r.get("usage", {}).get("contentPolicyUnits", 0)
        return {"filters": filters, "profanity": bool(words), "ms": round(ms, 1), "server_ms": server_ms, "units": units}


def bedrock_flag(v: dict, strengths: dict[str, str], profanity: bool) -> bool:
    """Whether a guardrail with these filter strengths (and the managed profanity list, when profanity) would block."""
    return any(v["filters"].get(t, 0) >= CUTOFF[s] for t, s in strengths.items()) or (profanity and v["profanity"])


_HIS = ("HATE", "INSULTS", "SEXUAL")
BEDROCK_CONFIGS = {
    # the code-of-conduct set: the categories the CNCF code names, without the two that read attacks as crime or
    # violence (MISCONDUCT, VIOLENCE), each at one strength, with the managed profanity list
    "coc-high": ({t: "HIGH" for t in _HIS}, True),
    "coc-medium": ({t: "MEDIUM" for t in _HIS}, True),
    "coc-low": ({t: "LOW" for t in _HIS}, True),
    # the chosen mix: the set at MEDIUM and threats of violence only where Bedrock is most confident
    "coc-medium+violence-low": ({**{t: "MEDIUM" for t in _HIS}, "VIOLENCE": "LOW"}, True),
    "coc+violence-medium": ({t: "MEDIUM" for t in _HIS + ("VIOLENCE",)}, True),
    "all5-high": ({t: "HIGH" for t in _HIS + ("VIOLENCE", "MISCONDUCT")}, True),
    "all5-medium": ({t: "MEDIUM" for t in _HIS + ("VIOLENCE", "MISCONDUCT")}, True),
    "profanity-list-only": ({}, True),
}
# The candidates as they would run together: the term floor everywhere, a classifier on the /chat model hop.
UNIONS = ("bedrock-standard-coc-medium+violence-low", "bedrock-standard-coc-medium", "bedrock-classic-coc-medium",
          "toxicity-0.7")


def verdicts_for(rows: list[dict]) -> dict:
    v = {"term-current": lambda r: r["current"], "term-proposed": lambda r: r["proposed"]}
    if any("toxicity" in r for r in rows):
        v["toxicity-0.5"] = lambda r: r["toxicity"][0] > 0.5 if "toxicity" in r else None
        v["toxicity-0.7"] = lambda r: r["toxicity"][0] > 0.7 if "toxicity" in r else None
    for tier in ("classic", "standard"):
        k = f"bedrock-{tier}"
        if not any(k in r for r in rows):
            continue
        for cfg, (strengths, prof) in BEDROCK_CONFIGS.items():
            v[f"{k}-{cfg}"] = lambda r, k=k, s=strengths, p=prof: bedrock_flag(r[k], s, p) if k in r else None
        for t in ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"):
            v[f"{k}-only-{t.lower()}-high"] = lambda r, k=k, t=t: bedrock_flag(r[k], {t: "HIGH"}, False) if k in r else None
    for name in UNIONS:
        if name in v:
            v[f"term-proposed+{name}"] = lambda r, c=v[name]: None if c(r) is None else bool(r["proposed"] or c(r))
    return v


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))] if s else 0.0


def summarize(rows: list[dict], verdicts: dict[str, callable]) -> dict:
    out = {}
    for name, flagged in verdicts.items():
        stage = [r for r in rows if r["source"] not in ("abuse", "hard-negative") and flagged(r) is not None]
        fp = [r for r in stage if flagged(r)]
        hn = [r for r in rows if r["source"] == "hard-negative" and flagged(r) is not None]
        ab = [r for r in rows if r["source"] == "abuse" and flagged(r) is not None]
        by_cat = collections.defaultdict(lambda: [0, 0])
        for r in ab:
            by_cat[r["category"]][1] += 1
            by_cat[r["category"]][0] += bool(flagged(r))
        out[name] = {
            "stage_texts": len(stage),
            "stage_false_positives": len(fp),
            "stage_false_positives_by_source": dict(collections.Counter(r["source"] for r in fp)),
            "hard_negatives_flagged": sum(bool(flagged(r)) for r in hn), "hard_negatives": len(hn),
            "abuse_caught": sum(bool(flagged(r)) for r in ab), "abuse": len(ab),
            "abuse_by_category": {c: f"{v[0]}/{v[1]}" for c, v in sorted(by_cat.items())},
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=pathlib.Path)
    ap.add_argument("--raw", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--toxicity", action="store_true")
    ap.add_argument("--bedrock", action="append", default=[], help="tier=guardrail-id")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--resummarize", action="store_true",
                    help="recompute the candidates from --raw, keeping the timings already in --out")
    a = ap.parse_args()
    if a.resummarize:
        rows = [json.loads(line) for line in a.raw.read_text(encoding="utf-8").splitlines()]
        result = json.loads(a.out.read_text(encoding="utf-8"))
        result["candidates"] = summarize(rows, verdicts_for(rows))
        a.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        _print(result)
        return 0
    rows = _texts(a.turns)
    timing: dict[str, dict] = {}

    for name in ("current", "proposed"):
        f = floor.Floor(name)
        us = []
        for r in rows:
            t0 = time.perf_counter()
            r[name] = bool(f.spans(r["text"]))
            us.append((time.perf_counter() - t0) * 1e6)
        timing[f"term-{name}"] = {"per_text_us_median": round(statistics.median(us), 1),
                                  "per_text_us_p99": round(_pct(us, .99), 1), "per_text_us_max": round(max(us), 1)}
    # a /chat turn under the floor runs it twice: the prompt before the model, the reply after
    if a.turns:
        doc = json.loads(a.turns.read_text(encoding="utf-8"))
        f = floor.Floor("proposed")
        turn_us = []
        for t in doc["turns"]:
            t0 = time.perf_counter()
            f.spans(t["prompt"] or "")
            f.mask(t["reply"] or "")
            turn_us.append((time.perf_counter() - t0) * 1e6)
        ms = [t["ms"] for t in doc["turns"]]
        timing["chat-turn"] = {"turns": len(ms), "turn_ms_median": round(statistics.median(ms), 1),
                               "turn_ms_p90": round(_pct(ms, .9), 1),
                               "proposed_floor_us_per_turn_median": round(statistics.median(turn_us), 1),
                               "proposed_floor_us_per_turn_p99": round(_pct(turn_us, .99), 1),
                               "proposed_floor_us_per_turn_max": round(max(turn_us), 1)}

    if a.toxicity:
        tox = Toxicity()
        ms = []
        todo = [r for r in rows if r["source"] in CLASSIFIER_SOURCES]
        for n, r in enumerate(todo, 1):
            if n % 200 == 0:
                print(f"toxicity {n}/{len(todo)}", file=sys.stderr, flush=True)
            score, label, t = tox.score(r["text"])
            r["toxicity"] = [round(score, 4), label]
            ms.append(t)
        timing["toxicity"] = {"model": f"ProtectAI/unbiased-toxic-roberta-onnx@{tox.revision}",
                              "per_text_ms_median": round(statistics.median(ms), 1),
                              "per_text_ms_p99": round(_pct(ms, .99), 1), "host": "the run's host, 4 onnxruntime threads"}

    for spec in a.bedrock:
        tier, gid = spec.split("=", 1)
        br = Bedrock(gid)
        todo = [r for r in rows if r["source"] in CLASSIFIER_SOURCES]

        def run(r, br=br):
            return r, br.assess(r["text"][:20000], "OUTPUT" if r["source"] == "observed-reply" else "INPUT")
        with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
            for n, (r, v) in enumerate(ex.map(run, todo), 1):
                r[f"bedrock-{tier}"] = v
                if n % 200 == 0:
                    print(f"bedrock-{tier} {n}/{len(todo)}", file=sys.stderr, flush=True)
        ms = [r[f"bedrock-{tier}"]["ms"] for r in todo]
        srv = [r[f"bedrock-{tier}"]["server_ms"] or 0 for r in todo]
        timing[f"bedrock-{tier}"] = {"guardrail": gid, "calls": len(todo),
                                     "round_trip_ms_median": round(statistics.median(ms), 1),
                                     "round_trip_ms_p90": round(_pct(ms, .9), 1),
                                     "guardrail_processing_ms_median": statistics.median(srv),
                                     "content_policy_units": sum(r[f"bedrock-{tier}"]["units"] for r in todo),
                                     "from": "the run's host to bedrock-runtime.us-west-2, "
                                             f"{a.workers} calls at a time"}

    with a.raw.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    result = {"measured": time.strftime("%Y-%m-%d"), "texts": dict(collections.Counter(r["source"] for r in rows)),
              "timing": timing, "candidates": summarize(rows, verdicts_for(rows))}
    a.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    _print(result)
    return 0


def _print(result: dict) -> None:
    for name, v in result["candidates"].items():
        print(f"{name:58s} stage FP {v['stage_false_positives']:4d}/{v['stage_texts']:<5d} "
              f"hard-neg {v['hard_negatives_flagged']:2d}/{v['hard_negatives']} abuse {v['abuse_caught']:3d}/{v['abuse']}")
    print(json.dumps(result["timing"], indent=1))


if __name__ == "__main__":
    sys.exit(main())
