<!-- ABOUTME: Research spike on LLM Guard input/output sanitization (the Regex output scanner) as used by -->
<!-- ABOUTME: guard-proxy for the C5 recipe-redaction beat. Verified live against the scanner source + behavior. -->

# LLM Guard input/output sanitization (Regex output scanner) — 2026-06-29

Verified live in the workshop `llm-guard` pod (the pinned image) by reading the installed
`llm_guard` source and exercising the scanner directly, after the C5 output guard only
redacted the recipe **signature** and left the ingredient amounts readable.

## TL;DR / the fix

For a redacting `Regex` output scanner with several secrets to scrub, use **ONE alternation
pattern** and **`match_type: all`**. Do NOT use multiple patterns with `match_type: search`.

```yaml
output_scanners:
  - type: Regex
    params:
      patterns:
        - 'SECRET_A|SECRET_B|phrase[\W_]+with[\W_]+spaces|[Oo]gre[\W_]+[Tt]oenails'
      is_blocked: true
      redact: true
      match_type: all
```

## The two behaviors that bite (both confirmed from the scanner source)

`llm_guard.input_scanners.regex.Regex.scan()` (the output `Regex` delegates to it):

```python
for pattern in self._patterns:
    matches = self._match_type.match(pattern, prompt)
    if matches is None or len(matches) == 0:
        continue
    if self._is_blocked:
        if self._redact:
            for match in matches:
                ... replace match with [REDACTED] ...
        return text, False, 1.0      # <-- RETURNS on the FIRST pattern that matches
```

1. **Early return on the first matching pattern.** The loop returns as soon as ANY pattern
   matches; later patterns are never evaluated. So with a list like
   `[signature, amount1, amount2, ogre]`, if the signature is always present it matches
   first and the amount/ogre patterns NEVER run. Symptom we hit: only the signature
   redacted; every ingredient amount leaked. Collapse all secrets into ONE alternation
   pattern so a single pattern carries every branch.

2. **`match_type` controls how many matches are redacted.** The enum is
   `MatchType.{SEARCH, FULL_MATCH, ALL}`. `SEARCH` returns only the FIRST match;
   `FULL_MATCH` requires the whole string to match; **`ALL`** returns every match
   (finditer-style). For redaction you almost always want `all` so every occurrence of
   every alternation branch is scrubbed in one pass.

## Things that are NOT the problem (ruled out the hard way)

- **Spaces / multi-word patterns work.** `'pinch of moonlight'` redacts fine when it is the
  matching pattern. The earlier "space patterns don't match" theory was wrong; it was the
  early-return masking them.
- **`(?i)` is not needed and was a red herring.** Patterns are `re.compile`d; the
  case-insensitive inline flag does compile, but prefer explicit char classes
  (`[Oo]gre [Tt]oenails`) for clarity. The earlier `(?i)` failure was again the early-return.
- **It was not ConfigMap mount lag.** A freshly bounced pod loads the current mounted
  `scanners.yml`; the misbehavior was the scanner logic, not stale config.

## Operational gotchas

- **Config is read at pod startup** from the mounted `scanners.yml`
  (`/home/user/app/config/scanners.yml`); the ConfigMap is fixed-name
  (`disableNameSuffixHash: true`), so a content change needs a **pod bounce** to take effect.
- **Mid-rollout probes are unreliable.** guard-proxy calls the `llm-guard` Service, which
  round-robins the old (terminating) and new pods during a rollout. Verify only once a
  SINGLE Running pod remains, or the results interleave old/new behavior and look random.
- **The model reformats content** in its replies (markdown `**bold**`, `½ tsp`, emoji), so
  use `[\W_]+` between words in phrase patterns to tolerate injected non-word characters
  (e.g. `generous[\W_]+splash[\W_]+of[\W_]+bat[\W_]+saliva` matches `generous splash of
  **bat saliva**`).

## Redaction-policy note (C5 specific)

Redact the SECRET parts only: the recipe **signature**, the **amounts** (the proportions
are what is secret; anyone can taste that there is ghost pepper), and a made-up ingredient
("ground ogre toenails", blocked 100%). Do NOT blocklist bare common words
(moonlight / smoked paprika / bat saliva) — that censors them everywhere they appear, not
just in the recipe. Verified: amounts + ogre + signature redact in clean and messy
renderings, and normal chat ("a moonlight stroll", "smoked paprika on the Bogbacoa") is not
over-blocked.

## Cross-references

- `research/31-guard-proxy-sanitization-tracing-2026.md` (content capture + before/after tracing)
- `research/28-datadog-llm-obs-otlp-2026.md` (the gen_ai content -> Datadog path)
- `gitops/ai-layer/resources.yaml` (the live `llm-guard-scanners` ConfigMap)
