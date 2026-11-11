<!-- ABOUTME: Research spike #1267: an always-on code-of-conduct floor on every surface the room can write to, whatever
     ABOUTME: the guardrails' state. Per surface what reaches the screen, the candidates measured, the choice and why. -->
# An always-on code-of-conduct floor (#1267)

Measured 2026-11-09 by hecaton run 19585. Vendor claims below were read on 2026-11-09 and carry their source.

## The answer

Two layers, both on whatever the stage's guardrails are set to:

1. **A term floor on every surface the room can write to.** This is the always-on floor: a list of 144 expletives,
   slurs, sexual terms, threat and hate phrases, and the commonest expletives in five other languages. Spellings are
   folded before matching (leetspeak, spaced-out letters, repeated letters, zero-width characters, look-alike
   letters, accents). It flagged **none of the 5,198 stage texts** it was run on and caught **111 of 155** texts in the
   abuse set (72%). On a `/chat` turn it costs **1.1 ms median, 11.4 ms at p99**, against a median turn of 3.8 s.
   Python and Go can run it, and in its RE2 form so can the collector (OTTL) and a Kubernetes admission policy
   (CEL). One list therefore covers `/chat`, the desk, `deploy_app`, the traces and the cluster's object names.
2. **A classifier on the `/chat` prompt only**, for the abuse no term list can see: hate speech without a slur,
   insults, threats. The choice is Amazon Bedrock Guardrails, Standard tier, with HATE, INSULTS and SEXUAL at MEDIUM
   and VIOLENCE at LOW. MISCONDUCT and PROMPT_ATTACK stay off. It flagged none of the 1,591 stage texts a `/chat`
   classifier would see. With the term floor it catches **151 of 155** (97%), and the hate category goes from 4 of
   20 to 20 of 20. It adds **466 ms median** to a turn, one `ApplyGuardrail` round trip from this host, of which
   327 ms is Bedrock's own processing. It needs a guardrail resource and IAM on the fleet, so it lands after the
   term floor and is not a condition of it.

Rejected: LLM Guard's Toxicity scanner, with 9 stage false positives (it scores Bedrock model ARNs as "obscene"),
6 of 60 hard negatives ("kill the pod and let the Deployment restart it") and 0 of 20 non-English texts. Also
rejected: Bedrock's MISCONDUCT filter, which flags the talk's own attacks. At MEDIUM it flags 25 stage texts:
HC-666's ticket, the Tron ask and the exfiltration prompts.

The attacks the talk teaches still land under both layers: no prompt the probes send, no marker they judge a reply
by and no reply the private cluster gave in the last week is touched (see "Do the challenges still land"). Live, on
2026-11-09 with the `/chat` check, the collector's mask, the admission policy and the deploy check on both clusters,
the KubeCon probe's admin run went 34 of 34 and its community run 22 of 22, both green, and the floor touched none of
their turns.

## What the CNCF Code of Conduct rules out

The CNCF Community Code of Conduct v1.3 (https://raw.githubusercontent.com/cncf/foundation/main/code-of-conduct.md,
last commit f2bb3ab4 on 2026-08-18, read 2026-11-09) lists as unacceptable, among others, "The use of sexualized
language or imagery", "Trolling, insulting or derogatory comments, and personal or political attacks", "Public or
private harassment in any form", "Publishing others' private information, such as a physical or email address,
without their explicit permission", "Violence, threatening violence, or encouraging others to engage in violent
behavior", and "Other conduct which could reasonably be considered inappropriate in a professional setting". The
Linux Foundation events code that KubeCon runs under
(https://events.linuxfoundation.org/about/code-of-conduct/, dateModified 2026-09-14, read 2026-11-09) adds:
"Harassment includes the use of abusive, offensive or degrading language", and "Speakers should not use sexual
language, images, or any language or images that would constitute harassment". Neither text says "slur"; "abusive,
offensive or degrading language" and "derogatory comments" cover them.

| Category the code names | The term floor | With the classifier | What neither catches |
|---|---|---|---|
| Sexualized language | 20 of 20 sexual texts: explicit terms and phrases | 20 of 20 | innuendo with no explicit word |
| Insulting or derogatory comments | 20 of 20 expletive texts; slurs 19 of 20 | slurs 20 of 20; insults 13 of 15 | an insult in plain words the classifier rates low ("a clown who can't code", "imbecile machine") |
| Personal or political attacks; harassment | expletives and slurs aimed at a person | 13 of 15 insults | a sustained campaign of polite messages: no filter reads intent across turns |
| Hate speech (identity-based attacks) | 4 of 20: only those with a slur or a fixed phrase ("heil hitler") | 20 of 20 | coded language and dog whistles the model has not learned |
| Violence, threatening violence | 4 of 15: fixed phrases ("kill yourself", "kys") | 14 of 15 | an implied threat ("I know where you live") |
| Private information | not this floor's job: guard-proxy's `moderate()` already masks emails, phone and card numbers and street addresses on the wall (#646), and the collector's `transform/scrub_pii` scrubs them in traces (#647) | | a name on its own |
| Political campaigning | not filtered: a word list cannot tell campaigning from discussion, and blocking politics would block ordinary prompts | | all of it |
| Other languages | 19 of 20: Spanish, French, German, Portuguese, Italian expletives and slurs | 11 of 20 from Bedrock alone | languages not on the list (Bedrock Standard covers more, at its lower rate) |

The categories come from the code; the counts are this spike's abuse set (below), so they are a sample, not a
guarantee.

## The surfaces

| Surface | What reaches the screen today | Chosen | Why | Where it lands |
|---|---|---|---|---|
| Prompt wall (`/prompts`, `/display`) | masked: `moderate()` masks the 40-term `PROFANITY` list, PII and the block-list whatever the toggles; prompts-agenticburn drops a masked prompt whole | the term floor's list and folding in place of the 40 terms, so the wall and `/chat` agree | 37 of 155 abuse texts for the 40 terms, 111 for the floor, both with no stage false positive | follow-up in guard-proxy-agenticburn; the longer list alone can go in now through guard-proxy's `PROFANITY_LIST` env |
| Chat page, "saved prompts" rail | `cocViolation` keeps a flagged prompt off the rail, on the same 40 terms (`COC_TERMS` in `burritbot.html`) | the floor's list | one list everywhere; the page otherwise saves what `/chat` refuses | follow-up |
| The prompt sent to the bot | on staging's pin, not filtered: it reaches Nova unless `input_blocklist` is on, and that list is attack words. guard-proxy a7a5a36 (guard-proxy-agenticburn#78, closed 2026-11-09) refuses a prompt with one of the 40 terms before any guard or the agent, whatever the toggles; it waits on Michael's repin | refused before the model by the term floor (a7a5a36's refusal, on the floor's list and folding), then by the Bedrock classifier, refusing the same way | a refused prompt costs nothing and puts nothing in kagent's spans | repin a7a5a36 (Michael); the list and folding: follow-up in guard-proxy-agenticburn; the classifier: follow-up |
| The bot's reply | on staging's pin, not filtered while the output guard is off, which is the whole stage. a7a5a36 masks the 40 terms in every reply, output guard on or off | masked by the term floor before guard-proxy returns it | Nova rarely produces abuse unprompted once the prompt is screened; masking costs microseconds and the classifier's half second is spent once, on the prompt | as the row above |
| Support desk (`POST /submit`) | any ticket text or HTML and an optional customer name, HTML-escaped but shown | the ticket refused, with the reason, when its text or name hits the term floor | a refused ticket never reaches the desk, the bot's `read_support_ticket`, or the bot's reply | #1268 |
| Deployments page | a row's `name`, `image`, `witch` and refusal `detail` come from what the bot deployed | `deploy_app` refuses a manifest any of whose strings hits the floor; `record_landing` masks the row's fields as a second net | the refusal comes back to the bot, which tells the room; the mask covers rows another cluster's relay reports | #1269 |
| Cluster objects (Deployments and every other kind) | `deploy_app` applies any single namespaced resource, and `run_shell` runs as the bot's service account, so a name or label can carry a term into `kubectl` output and Argo CD | a ValidatingAdmissionPolicy (CEL `matches()` on the floor's RE2 form) on names and labels in the `agent` namespace, outside Kyverno so `guardrails-off` does not lift it | admission is the one point every writer passes; Kyverno's mode is a stage prop the switches flip | follow-up |
| Datadog traces shown on stage (and Tempo) | raw prompts and replies, by design for the LLM Observability panels | the collector masks the floor's terms in the eight conversation attributes `transform/scrub_pii` already scrubs, in the base traces pipeline, before every exporter; guard-proxy's own `chat` span records the masked prompt | in-repo, deterministic, and the text never leaves the cluster; Datadog's Sensitive Data Scanner can redact LLM Observability spans with custom regex rules (docs below), but only after the data has left the environment, and its rules live in the Datadog org, not in this repo | follow-up; the guard-proxy follow-up for the `chat` span |

## How it was measured

Everything is in this directory. `corpus.py` builds the texts, `floor.py` holds the two term floors, `measure.py`
runs every candidate, `pull_turns.py` reads observed turns out of Tempo, `results.json` is what was measured, and
`verify/test_coc_floor_spike.py` reruns the term floor's half on every change.

**Stage texts (must pass, zero flagged):** 4,068 read from the repo at run time: every `.prompt` block on `/kubecon`
(the CEO ask, Challenge 2's Tron ask, both recipe asks, the beacon ask, HC-666, the weather ask, the four weird asks),
1,690 sentences of visible text from every page under `gitops/ai-layer/web/`, the room's replay set
(`fallback/prompts.yaml`), the quoted prompts of `challenges/PROMPT-CATALOG.md`, the probe's own prompts and
`topic_cases`, every fixed desk ticket (HC-666's complaint and its white-text injection included), all 768 witch names
and their `joker-` slugs, the MCP tools' descriptions and data, the agent's system prompt, and the Secrets and
ConfigMaps of `gitops/ai-layer/resources.yaml`. Plus 1,130 observed texts: the 69 distinct prompts and 1,061 distinct
replies of 1,099 `/chat` turns on watch-it-burn-private over the 7 days to 2026-11-09, read from Tempo by
`pull_turns.py` (read only; the dump is not committed). The two classifiers ran on the 1,591 of these a `/chat`
classifier would see: prompts, tickets, tool data, cluster data, replies.

**Abuse set (should be caught):** 155 texts in 8 categories, ROT13-encoded in `abuse-set.rot13.tsv` so the public tree
does not display them: expletives (20), slurs (20), hate speech without a slur (20), sexual content (20), insults
without profanity (15), threats (15), evasions of the first four (25: leetspeak, spaced letters, symbols, repeated
letters, fullwidth letters, a zero-width space) and other languages (20). Written for this spike, so the rates
describe this set, not the room.

**Hard negatives (reported, not required):** 60 benign sentences next to a term or a category: Kubernetes and attack
vocabulary ("kill the pod", "exploit the vulnerability", "fork bomb"), the menu's monster words, Scunthorpe-style
words ("Dickens", "cocktail", "grapes"), mild words the code allows ("this salsa is damn good").

**Bedrock:** two temporary guardrails, Classic and Standard tier (`guardrail-classic.json`,
`guardrail-standard.json`), each with every content filter at HIGH and the managed profanity list, all in detect mode
(action NONE). ApplyGuardrail then reports each detection's confidence, so every strength is read from one call: a
filter at HIGH blocks LOW confidence and up, MEDIUM blocks MEDIUM and up, LOW blocks HIGH only. Both guardrails were
deleted after the run; 3,612 calls used 3,688 content-policy units, about $0.55 at $0.15 per 1,000.

**LLM Guard Toxicity:** the scanner's default model, `ProtectAI/unbiased-toxic-roberta-onnx` (revision 16fd63c0),
run with onnxruntime as `llm_guard/input_scanners/toxicity.py` runs it: sigmoid per label, flagged when any of the
seven toxic labels passes the threshold (0.5 for the input scanner, 0.7 for the output scanner).

## Results

Stage false positives are out of 5,198 for the term floors and 1,591 for the classifiers. Abuse columns are caught
out of 20, 20, 20, 20, 15, 15, 25, 20.

| Candidate | Stage FP | Hard neg. (of 60) | Abuse (of 155) | expl. | slur | hate | sexual | insult | threat | evasion | other lang. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| guard-proxy's 40 terms today | 0 | 1 | 37 | 20 | 9 | 1 | 4 | 0 | 1 | 2 | 0 |
| **proposed term floor** | **0** | 1 | **111** | 20 | 19 | 4 | 20 | 0 | 4 | 25 | 19 |
| LLM Guard Toxicity, 0.5 | 9 | 6 | 95 | 20 | 11 | 12 | 15 | 14 | 11 | 12 | 0 |
| LLM Guard Toxicity, 0.7 | 9 | 3 | 84 | 19 | 8 | 10 | 12 | 14 | 10 | 11 | 0 |
| Bedrock Classic, HATE INSULTS SEXUAL at MEDIUM | 1 | 1 | 116 | 18 | 15 | 18 | 20 | 13 | 1 | 20 | 11 |
| Bedrock Standard, HATE INSULTS SEXUAL at HIGH | 5 | 1 | 135 | 19 | 19 | 20 | 20 | 15 | 6 | 22 | 14 |
| Bedrock Standard, HATE INSULTS SEXUAL at MEDIUM | 0 | 1 | 121 | 17 | 18 | 20 | 18 | 13 | 5 | 19 | 11 |
| **Bedrock Standard, the above and VIOLENCE at LOW** | **0** | 1 | 129 | 17 | 18 | 20 | 18 | 13 | 13 | 19 | 11 |
| Bedrock Standard, all five at MEDIUM (MISCONDUCT on) | 25 | 12 | 129 | 17 | 18 | 20 | 18 | 13 | 13 | 19 | 11 |
| Bedrock managed profanity list alone | 0 | 1 | 62 | 16 | 10 | 1 | 11 | 0 | 0 | 13 | 11 |
| **term floor + Bedrock Standard (chosen)** | **0** | 1 | **151** | 20 | 20 | 20 | 20 | 13 | 14 | 25 | 19 |

What the false positives were:

- **Toxicity:** eight Bedrock model ARNs in `resources.yaml` scored 0.71 to 0.91 "obscene"
  (`arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-8` is 0.91), and the clown-file tool's description
  scored 0.73 "toxicity". Hard negatives: "kill the pod and let the Deployment restart it", "the witch cursed the
  corn", "flame retardant tablecloths", "I'd kill for a Sorcerizo right now".
- **Bedrock MISCONDUCT** (Standard, MEDIUM and up): `/kubecon`'s Challenge 2 Tron ask, the injection payloads of HC-666 and HC-7731,
  the C8 credential-audit prompt, the customer-records and marketing-intel tool descriptions, the poisoned weather
  tool, and five observed prompts and six observed replies. That is the talk's own attacks, as the issue feared.
  Hard negatives: "exploit the vulnerability", "denial of wallet attack", "fork bomb", "read the secret".
- **Bedrock Standard INSULTS at HIGH:** five of Nova's own replies ("That's the pantry map, sugar"), at LOW
  confidence, which MEDIUM does not block.
- **Bedrock Classic HATE at MEDIUM:** one regex line in an llm-guard ConfigMap.
- **The term floor's one hard negative** is "the cock crowed at dawn": matching the word at all costs the rooster.

## Latency on a `/chat` turn

Median `/chat` turn on watch-it-burn-private, 1,099 turns over 7 days: **3,803 ms** (p90 6,266 ms), from guard-proxy's
`POST /chat` span.

| Option | Added to a turn | Measured how |
|---|---|---|
| Term floor, prompt checked and reply masked | 1.07 ms median, 11.4 ms p99, 16 ms max | `measure.py` over the 1,099 observed turns' prompt and reply, CPython on the run's host |
| The same pattern in Go's RE2 (`regexp`) | 5.4 ms on a 2,480-character reply | a one-off check of `floor.portable_pattern()` |
| Bedrock Standard ApplyGuardrail on the prompt | 466 ms median round trip (327 ms of it Bedrock's processing) | 69 observed prompts from the run's host to `bedrock-runtime.us-west-2`; a pod in us-west-2 pays less network time but the same processing |
| Bedrock Classic ApplyGuardrail on the prompt | 229 ms median (94 ms processing) | same; rejected for its stage false positive and its three languages |
| LLM Guard Toxicity, per text | 144 ms median, 915 ms p99 | onnxruntime, 4 threads on the run's host; the llm-guard pod's CPU limit would add to it |

The chosen pair adds about half a second to a 3.8 s turn, all of it the classifier's. The term floor alone adds about
a millisecond. Checking the reply with Bedrock as well would add another half second; the reply is masked by the term
floor instead. Where the classifier sits matters: agentgateway can attach a guardrail to its Bedrock backend or call
ApplyGuardrail as a prompt guard (below), but either runs on every model call, and a turn made 2.1 model calls on
average (2,313 `generate_content` spans over 1,090 traces). In guard-proxy it runs once, on the guest's prompt, and
never on tool output such as HC-666's ticket.

## Do the challenges still land

Offline, measured: the term floor and the chosen Bedrock mix flag none of these. Every prompt the KubeCon probe sends
(read from `/kubecon` as the probe reads it, plus its own order, CEO-opener and topic asks). HC-666 and every desk
ticket. Every tool description and the data the tools return. Every one of the 1,061 distinct replies the private
cluster gave in the week. The term floor also flags none of the 4,121 string literals in `verify/kubecon_probe.py`,
`verify/agent_probe.py`, `verify/topic_cases.py`, `verify/challenge_traces.py`, `workshop-mcp-server.py`, `server.py`
and `ticket_site.py`: every marker the probes judge a reply by (the CEO record, the vault sentinel, the Joker name,
the weather sentinel) stays whole. `verify/test_coc_floor_spike.py` holds the term floor's half of this on every
change (the repo's stage texts with `/kubecon`'s page, and the 2,068 literals of all but the two probe-only scripts,
whose prompts are `/kubecon`'s), so a new `/kubecon` prompt the floor would refuse fails there.

Live, 2026-11-09, staging 46b7ad6a on both clusters, every guardrail off at the start. Three layers of the floor were
on: guard-proxy a7a5a36's `/chat` check (`/controls` reads `always_on.code_of_conduct: true`, and a prompt with a
term was refused with zero tokens and no agent turn), the collector's `coc_mask` (#1277) and the
`code-of-conduct-names` admission policy at Deny (#1278, #1284). Then the two probes ran:

- `python3 verify/kubecon_probe.py admin burritobot-private.burritobot.co --context watch-it-burn-private`:
  34 beats, 34 PASS, `KUBECON PROBE GREEN`.
- `python3 verify/kubecon_probe.py community attackme.burritobot.co --context watch-it-burn-community
  --switch-context watch-it-burn-private`: 22 beats, 21 PASS, 1 FAIL, `KUBECON PROBE RED`. Every challenge beat
  passed: Challenge 1's leak, Challenge 2's three openings and the Tron deploy, HC-666's Joker, and Challenge 4 and its
  retry. The one FAIL is segment 1's off-topic smoke ask, answered 2 of 3. The miss was the model's reply "The steps and
  code to reverse a linked list are provided above", with no code in it. The check did not cause it: guard-proxy
  logged no `conduct_masked` or `conduct_refused` event for any probe turn, and the matcher finds no term in either
  probe's output or in the judge's words.

Live again, 2026-11-09 from 21:05Z to 21:17Z, staging 8eb1872a on both clusters (Argo CD's ai-layer, namespaces and
workshop-agent at 8eb1872a), every guardrail off at the start. Four layers of the floor were on: the three above and
the deployments page's (#1269), `deploy_app` refusing a term in a deploy and `record_landing` masking one, in the
running workshop-mcp on both. The chat page carried #1294's change, which shows a code block Nova wrote only inside
its scratchpad, the cause of the earlier miss. Then the two probes ran again:

- admin on watch-it-burn-private: 34 beats, 34 PASS, 0 FAIL, `KUBECON PROBE GREEN`, $0.0845 to $0.1689 over 14 model
  calls.
- community on watch-it-burn-community with `--switch-context watch-it-burn-private`: 22 beats, 22 PASS, 0 FAIL,
  `KUBECON PROBE GREEN`, $0.1895 to $0.2845 over 10 model calls. The off-topic ask was answered 3 of 3; the Tron
  deploy and HC-666's joker-agatha-the-banshee landed through the deploy check and were listed, then removed.

guard-proxy on both clusters logged no `conduct_refused` or `conduct_masked` event over the two runs, and workshop-mcp
no refusal, so the floor touched no probe turn. Both end beats read both clusters back at the start state. The desk's
part (#1268) is not on staging yet: its draft failed validation. That issue's own criteria require HC-666 and the
room's injections to be filed whole with the desk check on, and its live check runs once it lands.

## Vendor facts used, dated and sourced (read 2026-11-09)

Amazon Bedrock Guardrails:
- Content filter categories and wording: HATE, INSULTS, SEXUAL, VIOLENCE, MISCONDUCT, each with input and output
  strength NONE, LOW, MEDIUM or HIGH. MISCONDUCT "seeks or provides information about engaging in criminal activity,
  or harming, defrauding, or taking advantage of a person, group or institution".
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-content-filters.html
- Content filters "do not evaluate tool results (`toolResult`), tool definitions (`toolSpec`), or model-generated tool
  call arguments". PROMPT_ATTACK is a separate filter type and "does not evaluate tool results". Same page, and
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html
- Managed profanity word list ("continually updated"); custom words up to 10,000, whole-word, case-insensitive.
  Word filters cover English, French and Spanish.
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-word-filters.html,
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-supported-languages.html
- Classic tier covers "English, French, and Spanish"; Standard "has more comprehensive language and code-related
  prompt support" and uses cross-Region inference (`crossRegionConfig`, here `us.guardrail.v1:0`).
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html
- Pricing: content filters (text) "$0.15 per 1,000 text units", a text unit "up to 1000 characters"; word filters
  "Free". https://aws.amazon.com/bedrock/pricing/ . The chosen check is one text unit per prompt under 1,000
  characters: $0.15 per 1,000 turns.
- ApplyGuardrail assesses text "without invoking the foundation models"; Block or Detect per category (`inputAction`
  and `outputAction`, BLOCK or NONE). AWS publishes no typical latency; the figures above are this spike's.
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html,
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-harmful-content-handling-options.html

agentgateway v1.7.0 (pinned in `gitops/ai-layer/agentgateway.yaml`, released 2026-10-27):
- The Bedrock provider takes `guardrailIdentifier` and `guardrailVersion` and adds them to the Converse call.
  https://github.com/agentgateway/agentgateway/blob/v1.7.0/schema/config.md ; `crates/llm/src/bedrock.rs`
- `policies.ai.promptGuard` has `request` and `response` guards: `regex` (action `mask`, `reject` or `audit`),
  `webhook`, `openAIModeration` and `bedrockGuardrails` (calls ApplyGuardrail, `failureMode` failClosed by default).
  Its `scope` selects `systemPrompt`, `messages`, `toolOutput`, `toolInput`. A mask "is not applied to streamed
  responses". Same schema file; https://agentgateway.dev/docs/kubernetes/latest/llm/guardrails/overview/

kagent v0.10.1: its Bedrock ModelConfig has a `guardrail` (identifier, version, trace), used only when kagent calls
Bedrock itself; the stage's model path goes through agentgateway. `go/api/v1alpha2/modelconfig_types.go` at v0.10.1.

LLM Guard: archived (the README: "THIS PROJECT HAS BEEN ARCHIVED"; last commit 168c1034 on 2026-07-08). Toxicity's
defaults in `llm_guard/input_scanners/toxicity.py`: `unitary/unbiased-toxic-roberta`, ONNX
`ProtectAI/unbiased-toxic-roberta-onnx`, threshold 0.5 (0.7 for the output scanner), the seven labels above. The model
card warns that swearing makes a text "likely" to be "classified as toxic, regardless of the tone or the intent"
(https://huggingface.co/unitary/unbiased-toxic-roberta, lastModified 2023-08-18).

Datadog: Sensitive Data Scanner scans APM spans and "Agent Observability traces, including inputs and outputs from
LLM applications", takes custom regex rules, and redacts "before events are indexed and shown in the Datadog UI",
noting that "the data leaves your environment before it gets redacted".
https://docs.datadoghq.com/security/sensitive_data_scanner/ ;
https://docs.datadoghq.com/llm_observability/data_security_and_rbac/

OpenTelemetry Collector: OTTL `replace_all_patterns(target, "value", regex, replacement)` replaces every match in a
map's values, as `transform/scrub_pii` in `gitops/otel-collector/values-burn.yaml` already does; a `$` in collector
config is written `$$`. https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/pkg/ottl/ottlfuncs/README.md

## The floor's design, for the children

`floor.py` is the reference, standard library only:

- `Floor("proposed").spans(text)` folds the text one character at a time (drops zero-width characters and soft
  hyphens, reduces fullwidth and accented letters to their base, maps Cyrillic and Greek look-alikes and the dotless
  i `ı`, lower-cases), then matches each term as a whole word with repeatable letters, leetspeak stand-ins, `*` for a vowel, or every
  letter spelt out with one separator between each ("f u c k"; "put a" is not "puta"). An optional plural `s`, as
  guard-proxy's list does today. `mask()` maps each match back onto the original characters.
- `portable_pattern()` is the same pattern without lookarounds, in the syntax RE2 shares with Python, for the
  collector and CEL. It cannot fold, so zero-width characters, look-alikes and accents get past it; on the 151 abuse
  texts that need no folding it agrees with the folded floor exactly. Its word edges are capture groups, so the
  replacement keeps them and is applied twice for two terms one separator apart. Since #1277 it also reads JSON, which
  is what the collector sees: a leading edge takes a `\n`, `\r`, `\t` or `\uXXXX` escape, and `ß` also matches as
  `ß`, since guard-proxy's `json.dumps` escapes every non-ASCII character. The collector's `transform/coc_mask`
  runs this form.
  RE2's `(?i)` keeps the dotless i `ı` (U+0131) apart from `i`, where Python's `re.IGNORECASE` (guard-proxy's match)
  and `fold()` read it as `i`, so every class that holds `i` also takes `ı` and its escape `\u0131` (#1301).
- The list is `terms-proposed.rot13`, decoded by `corpus.terms("proposed")`. guard-proxy reads its list from
  `PROFANITY_LIST`, so the wall can take the longer list before #78 lands; the folding is code and lands with #78.
- Since #1316 (2026-11-11) the list is guard-proxy's default list as guard-proxy-agenticburn#84 grew it: the 144
  terms measured here, then 1,109 entries of slang, alphanumeric spellings, coded hate and regional slang, 1,253 in
  guard-proxy's order. The figures on this page are the 2026-11-09 measurement of the 144. On the abuse set the longer
  list catches 112 of 155, one more Portuguese text, and it still flags no stage text. `proposed_pattern()` groups
  the alternatives by their first character, as guard-proxy does, so a 4,000-character run of `$` costs 0.02 s of
  CPU, not 0.17 s. `portable_pattern()` is factored on shared leading pieces, 94,535 characters in place of 212,409,
  and `name_pattern()` is that form cut to what a name or a label can hold, 52,863 characters, for the admission
  policy, whose CEL cost grows with the pattern's length.
- A refusal says what happened in plain words ("Keep it kind: that message has words the code of conduct rules out,
  so it was not sent.") and never echoes the term.

## Reproduce

```bash
cd docs/research/2026-11-09-coc-floor
. "$HECATON_CLUSTER_ENV"
python3 pull_turns.py --context watch-it-burn-private --days 7 --out "$TMPDIR/turns.json"
python3 measure.py --turns "$TMPDIR/turns.json" --raw "$TMPDIR/raw.jsonl" --out results.json   # term floors only
# with the classifiers: a venv holding boto3 1.43.126, onnxruntime 1.31.1, tokenizers 0.23.3, huggingface_hub 2.4.0,
# numpy 2.5.4 and PyYAML; two guardrails made from guardrail-*.json (aws bedrock create-guardrail
# --cli-input-json file://guardrail-standard.json), deleted after
python3 measure.py --turns ... --raw ... --out results.json --toxicity --bedrock classic=<id> --bedrock standard=<id>
python3 measure.py --raw "$TMPDIR/raw.jsonl" --out results.json --resummarize   # recount from a dump, no new calls
python3 ../../../verify/test_coc_floor_spike.py
```
