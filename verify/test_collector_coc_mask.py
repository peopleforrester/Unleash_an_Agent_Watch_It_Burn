# ABOUTME: Every profile's collector masks the code of conduct's terms in the conversation before any exporter (#1277):
# ABOUTME: the rendered config's transform/coc_mask, its patterns the #1267 spike's portable_patterns() (#1328), its place.
"""Pins #1277: the term list the #1267 spike chose is masked in trace content in the collector, on every profile,
whatever the guardrails are set to, so an expletive or slur typed into /chat never reaches Tempo or the Datadog
panels on the screen.

The collector config is rendered as each profile builds it (collector_render.py: the Application's value files, then
what the datadog-gate loads), with and without datadog-secret, and with one org and two on attendee. This holds:

  - transform/coc_mask is defined in no relay.yaml but in the otel-collector-coc-mask ConfigMap (#1332), which each
    profile's Application deploys from gitops/otel-collector/coc-mask/ and its collector mounts, not optionally, and
    loads with a further --config, and whose file's SHA-256 is the checksum/coc-mask pod annotation, so a new list
    rolls the collector;
  - transform/coc_mask is in the traces pipeline of every render, after transform/adk_model_content and
    transform/adk_tool_content (which copy the content to gen_ai.*), and last but for burn's transform/scrub_pii;
  - every other traces pipeline either receives only from a connector a masked pipeline exports to (traces/llmobs,
    through forward/llmobs) or keeps none of the eight keys (traces/lab's contract), so no exporter gets an unmasked
    copy;
  - its statements are exactly coc_mask_cases.statements(): the eight keys burn's scrub keeps, copied to the cache,
    masked with each pattern in turn, twice (the second pass where the first masked something), merged back, in the
    span and the span-event context;
  - the patterns, decoded from the config as the collector and OTTL read them, are floor.portable_patterns() in order,
    each short enough to parse quickly (#1328), and each term of the list comes out of them as it comes out of
    floor.portable_pattern();
  - applied with Python's re, they mask the term cases and leave HC-666's ticket as it is.

test_collector_coc_mask_e2e.py runs the same cases through the real collector. Offline: reads the collector value
files, the coc-mask ConfigMap, the bootstrap Applications, the spike's term list and gitops/ai-layer/ticket_site.py.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from coc_mask_cases import (KEYS, MASK, SECOND_PASS, decode, hc666_ticket, mask, patterns, statements,  # noqa: E402
                            term_cases)
from coc_mask_cases import floor  # noqa: E402
from collector_render import (COC_MASK_KEY, COC_MASK_MANIFEST, PROFILE_APP, REPO, collector_config,  # noqa: E402
                              coc_mask_configmap, config_paths, helm_values, mounted_file)

PORTABLE_LIMIT = floor.PORTABLE_LIMIT
SCRUB = "transform/scrub_pii"
COPIERS = ("transform/adk_model_content", "transform/adk_tool_content")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:600]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


RENDERS = [(p, s, a) for p in ("instructor", "attendee", "burn") for s in (False, True)
           for a in ((True, False) if p == "attendee" and s else (True,))]

print("== every profile: the mask is its own ConfigMap's file, mounted and loaded after relay.yaml (#1332) ==")
COC_MASK_DIR = COC_MASK_MANIFEST.parent.relative_to(REPO).as_posix()
for profile, app_path in PROFILE_APP.items():
    vals = helm_values(profile)
    app = yaml.safe_load(app_path.read_text(encoding="utf-8"))
    dirs = [s.get("path") for s in app["spec"]["sources"] if "path" in s and "chart" not in s]
    check(f"{profile}: {app_path.name} deploys {COC_MASK_DIR} as a source of its own ({dirs})", dirs == [COC_MASK_DIR])
    check(f"{profile}: relay.yaml (values `config`) does not define {MASK}", MASK not in vals["config"].get("processors", {}))
    loaded = [p for p in config_paths(vals) if p.endswith("/" + COC_MASK_KEY)]
    check(f"{profile}: the collector loads {COC_MASK_KEY} with one --config ({config_paths(vals)})", len(loaded) == 1)
    if len(loaded) == 1:
        volume, text = mounted_file(profile, vals, loaded[0])
        check(f"{profile}: from the otel-collector-coc-mask ConfigMap, mounted not optionally (without it the "
              f"collector would refuse relay.yaml's pipeline)", volume.get("configMap", {}).get("name")
              == "otel-collector-coc-mask" and not volume["configMap"].get("optional"))
        check(f"{profile}: that file defines {MASK} and nothing else",
              list(yaml.safe_load(text)) == ["processors"] and list(yaml.safe_load(text)["processors"]) == [MASK])
    annotation = (vals.get("podAnnotations") or {}).get("checksum/coc-mask")
    digest = hashlib.sha256(coc_mask_configmap()["data"][COC_MASK_KEY].encode("utf-8")).hexdigest()
    check(f"{profile}: the checksum/coc-mask pod annotation is the SHA-256 of the ConfigMap's {COC_MASK_KEY}, so a new "
          "list rolls the collector (the copies registry's write sets it)", annotation == digest,
          f"{annotation!r}, not {digest}")
check("the ConfigMap names no namespace, so it lands in the Applications' destination, monitoring",
      "namespace" not in yaml.safe_load(COC_MASK_MANIFEST.read_text(encoding="utf-8"))["metadata"])

def feeds_masked(cfg: dict, exporter: str) -> bool:
    """The exporter sends to this collector's own receiver of the traces pipeline, on the loopback (#1336's relay).

    Any loopback host counts here; test_collector_relay.py holds which one (127.0.0.1 since run 20576)."""
    endpoint = (cfg.get("exporters", {}).get(exporter) or {}).get("endpoint")
    ours = {(cfg["receivers"].get(r, {}).get("protocols") or {}).get("grpc", {}).get("endpoint")
            for r in cfg["service"]["pipelines"]["traces"].get("receivers", [])}
    return bool(endpoint) and str(endpoint).startswith(("127.0.0.1:", "localhost:")) and endpoint in ours


print("== every profile: the mask is in the traces pipeline, after the content copies, before every exporter ==")
for profile, secret, admin in RENDERS:
    cfg = collector_config(profile, datadog_secret=secret, admin_secret=admin)
    label = f"{profile} {'with' if secret else 'without'} datadog-secret" + ("" if admin or not secret else ", one org")
    pipes = cfg["service"]["pipelines"]
    procs = pipes["traces"]["processors"]
    check(f"{label}: {MASK} is defined", MASK in cfg.get("processors", {}))
    check(f"{label}: {MASK} is a traces processor {procs}", MASK in procs)
    if MASK not in procs:
        continue
    check(f"{label}: after {', '.join(COPIERS)}",
          all(c in procs and procs.index(c) < procs.index(MASK) for c in COPIERS))
    after = procs[procs.index(MASK) + 1:]
    check(f"{label}: nothing but burn's scrub runs after it ({after})",
          after == ([SCRUB] if profile == "burn" else []))
    check(f"{label}: the traces pipeline exports somewhere", bool(pipes["traces"].get("exporters")))
    fed = set(pipes["traces"].get("exporters", []))  # connectors fed by the masked pipeline
    for name, pipe in pipes.items():
        if not name.startswith("traces") or name == "traces":
            continue
        receivers = set(pipe.get("receivers", []))
        if receivers <= fed:
            check(f"{label}: {name} receives only from the masked pipeline ({sorted(receivers)})", True)
            continue
        # traces/intake (#1336) takes the senders' spans before the mask, and sends every one of them on to the masked
        # pipeline: each exporter it names is a loopback to a receiver of the traces pipeline, and nothing else.
        if pipe.get("exporters") and all(feeds_masked(cfg, e) for e in pipe["exporters"]):
            check(f"{label}: {name} sends every span it takes into the masked pipeline ({pipe['exporters']})", True)
            continue
        kept = [s for g in cfg["processors"].get("transform/lab_contract", {}).get("trace_statements", [])
                if g.get("context") == "span" for s in g["statements"] if s.startswith("keep_keys(attributes,")]
        check(f"{label}: {name} takes spans of its own, and its contract keeps none of the conversation keys",
              "transform/lab_contract" in pipe.get("processors", []) and len(kept) == 1
              and not any(f'"{k}"' in kept[0] for k in KEYS), f"{name}: {pipe}")

print("== the processor: the eight keys, cached, masked with each pattern twice, merged back, on spans and span events ==")
proc = collector_config("instructor", datadog_secret=False)["processors"][MASK]
check("error_mode is ignore, so a statement that cannot run never drops a span", proc.get("error_mode") == "ignore")
groups = {g["context"]: g["statements"] for g in proc.get("trace_statements", [])}
check(f"a span and a span-event group ({sorted(groups)})", sorted(groups) == ["span", "spanevent"])
want = statements()
for context, got in sorted(groups.items()):
    check(f"{context}: every statement is a string", all(isinstance(s, str) for s in got))
    check(f"{context}: the statements are coc_mask_cases.statements() (rerun the copies registry's write after the "
          "term list changes)", got == want,
          next((f"statement {i}: {g[:200]}..." for i, (g, w) in enumerate(zip(got, want)) if g != w), str(len(got))))

burn = yaml.safe_load((REPO / "gitops/otel-collector/values-burn.yaml").read_text(encoding="utf-8"))
keep = next(s for g in burn["config"]["processors"][SCRUB]["trace_statements"] if g["context"] == "span"
            for s in g["statements"] if s.startswith("keep_keys("))
check("the keys are the eight burn's transform/scrub_pii keeps",
      sorted(re.findall(r'"([^"]+)"', keep.partition(", ")[2])) == sorted(KEYS), keep)

print("== the patterns are the spike's floor.portable_patterns(), as the collector reads them ==")
REPLACE = re.compile(r'^replace_all_patterns\(cache\["coc"\], "value", "(.*)", "\$\$1\[redacted\]\$\$3"\)$')
span = groups.get("span", [])
replaces = [s for s in span if s.startswith("replace_all_patterns(")]
firsts, seconds = replaces[0::2], replaces[1::2]
written = [m.group(1) for m in map(REPLACE.match, firsts) if m]
check(f"each of the {len(firsts)} first passes has the shape the decoding reads", len(written) == len(firsts) > 0)
check(f"each is followed by its second pass, the same statement where the conversation holds a [redacted] "
      f"({SECOND_PASS.strip()})", len(seconds) == len(firsts) and all(b == a + SECOND_PASS for a, b in zip(firsts, seconds)))
regexes = [decode(w) for w in written]
want_regexes = patterns()
check(f"decoded, the patterns applied in turn are floor.portable_patterns() ({len(regexes)} of {len(want_regexes)})",
      regexes == want_regexes)
check(f"each pattern is at most floor.PORTABLE_LIMIT ({PORTABLE_LIMIT:,}) characters, so the collector parses it in "
      f"well under a second (longest {max(map(len, regexes), default=0):,})",
      bool(regexes) and max(map(len, regexes)) <= PORTABLE_LIMIT)
SINGLE = re.compile(floor.portable_pattern(), re.ASCII)
TERMS = floor.corpus.terms("proposed")
differ = [t for t in TERMS if mask(t) != floor.portable_mask(t, SINGLE)]
check(f"each of the {len(TERMS):,} terms, as the list writes it, comes out of the patterns in turn as it comes out of "
      f"floor.portable_pattern() (the collector split test holds the two equal on every corpus; differ: "
      f"{len(differ)})", not differ and len(TERMS) > 1000)
check("every $ in the config is doubled, so confmap reads none as a ${...} reference",
      bool(written) and all(len(run) % 2 == 0 for w in written for run in re.findall(r"\$+", w)))
check("no lookaround or backreference, which RE2 lacks",
      not any(re.search(r"\(\?<?[=!]|\\[1-9]", r) for r in regexes))
check("the replacement keeps both word edges ($1 and $3, written $$1 and $$3)",
      all("$$1[redacted]$$3" in s for s in replaces))

print("== what it does, with Python's re (test_collector_coc_mask_e2e.py runs RE2 in the collector) ==")
for text, masked in term_cases():
    check(f"a {len(text)}-character text with a term comes out masked", mask(text) == masked)
# The attributes are JSON: guard-proxy writes them with json.dumps, whose \n and \uXXXX escapes sit right before a
# term on a line's start or after a curly quote, and kagent's Go marshaller keeps UTF-8 as it is. Both must mask.
lines = "\n".join(t for t, _ in term_cases())
lines_masked = "\n".join(m for _, m in term_cases())
check("the cases on lines of one prompt, JSON-encoded with escapes (guard-proxy), come out masked",
      mask(json.dumps(lines)) == json.dumps(lines_masked), mask(json.dumps(lines)))
check("and JSON-encoded as UTF-8 (kagent)",
      mask(json.dumps(lines, ensure_ascii=False)) == json.dumps(lines_masked, ensure_ascii=False))
check("HC-666's ticket JSON-encoded either way is unchanged",
      all(mask(json.dumps(ticket_text, ensure_ascii=a)) == json.dumps(ticket_text, ensure_ascii=a)
          for ticket_text in [hc666_ticket()] for a in (True, False)))
ticket = hc666_ticket()
check(f"HC-666's ticket ({len(ticket)} characters, its injection included) comes out unchanged", mask(ticket) == ticket)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector code-of-conduct mask checks passed.")
