<!-- ABOUTME: Research spike on OTel SDK delivery across the full Watch-It-Burn cluster stack (issue #15). -->
<!-- ABOUTME: Answers whether the OpenTelemetry Operator is warranted, how it coexists with the standalone Collector, and per-component delivery for the custom Python pods. -->

# 33. OTel SDK Delivery Strategy for the Full Cluster Stack (issue #15)

**Date:** 2026-06-23

## Verification Method

- **Approach:** Deep web research against current (2026) official sources, run 2026-06-23:
  the OpenTelemetry Operator docs and GitHub repo, the opentelemetry-operator Helm chart, the
  Instrumentation CRD spec, the OpenTelemetry zero-code/Python auto-instrumentation docs, the
  opentelemetry-python-contrib `bootstrap_gen.py` and the Operator's own
  `autoinstrumentation/python` image `requirements.txt` + `Dockerfile` (read directly via the
  GitHub API), and the OTel Operator Target Allocator docs. Every non-obvious or time-sensitive
  claim carries an inline source URL; the full list is in **Sources**.
- **In-repo facts taken as CONFIRMED** (read directly this session):
  `agent/gateway/guard-proxy/proxy.py` (stdlib `ThreadingHTTPServer`, no framework, no OTel,
  forwards A2A via `urllib.request`), `gitops/ai-layer/resources.yaml` (guard-proxy and
  evil-mcp-shim Deployments: `python:3.12-slim`, ConfigMap-mounted source, the guard-proxy
  `command: ["python","/app/proxy.py"]`, the evil-mcp-shim
  `command: ["sh","-c","pip install --quiet --no-cache-dir mcp && exec python /app/server.py"]`,
  the existing `OTEL_RESOURCE_ATTRIBUTES` env on the kagent Agent),
  `beats/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py` (FastMCP shim, poisoned tool
  descriptions), `gitops/apps/otel-collector.yaml` (standalone `otelcol-contrib 0.158.2`
  DaemonSet, ArgoCD Application, OTLP receivers on 4317/4318, `datadog` + `prometheusremotewrite`
  + `otlp/tempo` exporters, `spanmetrics` connector), `gitops/apps/cert-manager.yaml` (cert-manager
  is already in the stack).
- **Builds on (NOT re-researched; extracted per Whitney's instruction):**
  - `research/24-datadog-hybrid-impl-sizing-2026.md` §1.1: LOCKED architecture, standalone
    `otelcol-contrib 0.158.2` Collector as the neutral layer + standalone Datadog Agent DaemonSet
    for infra. NOT DDOT. This spike does NOT reopen that.
  - `research/28-datadog-llm-obs-otlp-2026.md` (issue #9): Datadog Agent Observability (formerly
    "LLM Observability") natively ingests OTel `gen_ai.*` over OTLP at semconv v1.37+, via direct
    intake / Datadog Agent OTLP / the Collector. Delivery path is OTLP into the existing Collector.
  - `research/29-python-ai-instrumentation-2026.md` (issue #10): per-component instrumentation
    verdicts. kagent/ADK and agentgateway self-instrument config-only; guard-proxy makes NO
    Bedrock call (it forwards A2A) and wants honest proxy/guard spans with W3C context propagation,
    not `gen_ai.*`; evil-mcp-shim needs no instrumentation (visible via the agent's `execute_tool`
    spans). `opentelemetry-instrumentation-botocore` 0.63b1 is the Bedrock SDK path on the agent.
  - `research/05-otel-genai-observability.md`: GenAI semconv all Development; `invoke_agent` /
    `execute_tool {gen_ai.tool.name}` span shape; content-capture re-leak trap.
  - `research/18-datadog-integrations-stack-2026.md`: per-component Datadog integration survey;
    UST attribute->tag mapping.

This spike is research-only. It does NOT edit manifests, config, or code, and does NOT reopen the
locked Collector/Agent architecture.

---

## TL;DR

**OTel Operator: NO.** Do not adopt the OpenTelemetry Operator for this stack. The Operator's two
jobs are (1) managing Collector instances via the `OpenTelemetryCollector` CRD and (2) injecting
language SDKs into pods via the `Instrumentation` CRD plus an init container. Neither earns its
keep here:

1. The Collector is already a standalone, ArgoCD-managed `otelcol-contrib 0.158.2` DaemonSet with
   a deliberately neutral, swappable pipeline (`research/24` §1.1, LOCKED). Putting it under the
   Operator's CRD buys nothing and fights the swappable principle.
2. The only pods that need SDK *injection* are the two custom Python pods, and for **both** the
   Operator's prebuilt Python auto-instrumentation is a poor fit: guard-proxy is a stdlib
   `http.server` with **no framework**, which the Operator's image cannot produce an inbound
   SERVER span for (it ships `urllib` + `wsgi` instrumentation but **no `http.server`
   instrumentation**), and evil-mcp-shim is an untrusted teaching prop that should NOT be
   instrumented at all (`research/29` Q4).
3. Each remaining stack component (per issue #15's stack table) needs no SDK injection: the
   bundled-OTel third-party components (kagent/ADK, agentgateway) self-instrument config-only; the
   platform components that emit OTel do so via their own native config (Istio ambient is OTel +
   Prometheus native, Kyverno is native-OTLP opt-in, ArgoCD has built-in OTel support); the
   Prometheus-only emitters (cert-manager, ESO, Falco) are scraped by the Collector / Datadog Agent;
   and the remaining custom/TBD components (the customer-stream generator, Backstage) are
   dispositioned in the per-component coverage table below. The one genuine injection candidate the
   Operator targets, Backstage (a Node.js app, which the Operator does inject), is out of M2/M3
   scope and config-native otherwise, so it does not move the verdict. No component in the stack
   needs the Operator's SDK injection.

The net is: the Operator would add a CRD-managed control plane, a mutating admission webhook, and
a cert dependency to deliver auto-instrumentation that does not actually instrument the one
component (guard-proxy) it would target. A small per-component delivery plan (below) is simpler,
matches the locked architecture, and produces strictly better telemetry for the guard-proxy.

**Scope boundary.** The active delivery work in scope here is the M2/M3 custom Python pods
(guard-proxy, evil-mcp-shim, customer-stream generator) plus the AI-layer third-party components
(kagent/ADK, agentgateway). The remaining platform components (Istio, ArgoCD, Kyverno, Falco,
cert-manager, ESO, Backstage) are surveyed for telemetry posture and dispositioned in the
stack-coverage table below, but their instrumentation work is out of the M2/M3 build scope; they
are listed so the "full cluster stack" framing in issue #15 is closed out, not left implicit.

### Stack coverage (every component in issue #15's stack table)

| Component | Issue table posture | Needs SDK injection? | Operator help? | Disposition |
|---|---|---|---|---|
| evil-mcp-shim | Custom Python, no OTel | No (deliberately un-instrumented) | No | NONE; narrated by agent `execute_tool` span (`research/29` Q4) |
| guard-proxy | Custom Python, no OTel (M3) | Yes | No (no `http.server` server instr; Q3) | Custom image + manual SDK (Q3, plan below) |
| customer-stream generator | Custom, instrumentation TBD | Maybe, see note | No (same stdlib/manual situation as guard-proxy if Python) | Out of M2/M3 scope; if instrumented, manual SDK per the guard-proxy pattern, not the Operator (see below) |
| kagent / ADK | Bundled OTel, config-only | No | No | Config-only (Helm values; Q4) |
| agentgateway | Bundled OTel, config-only | No | No | Config-only (`frontendPolicies.tracing`; Q4) |
| Istio ambient | OTel + Prometheus native | No | No | Native OTel/Prometheus config; mesh emits its own telemetry, no SDK to inject |
| ArgoCD | OTel support available | No | No | Built-in OTel; config-native, out of M2/M3 scope |
| Kyverno | Native OTLP opt-in | No | No | Native OTLP opt-in flag; config-native, out of M2/M3 scope |
| Falco / Falcosidekick | Events + Prometheus | No | No | Scraped / event-forwarded; Operator never scrapes (Q6) |
| cert-manager, ESO | Prometheus only | No | No | Scraped by Collector / Datadog Agent (Q6) |
| Backstage | Instrumentation TBD | Possibly (Node.js) | Possibly (Operator DOES inject Node.js) | Out of M2/M3 scope and config-native otherwise; the one plausible Operator injection target, but one out-of-scope pod does not justify adopting the Operator (see Q4) |

The customer-stream generator and Backstage are the two "TBD" rows. Neither is in M2/M3, so neither
forces a delivery decision now. If the customer-stream generator is later instrumented and is a
Python service, it falls under the same manual-SDK pattern as the guard-proxy (the Operator's
prebuilt image still has the gaps in Q3); if Backstage is later instrumented it is the single
Node.js pod the Operator could inject, but a lone out-of-scope candidate does not warrant the
Operator's control plane (Q4).

Confidence: HIGH.

---

## Q1. OTel Operator scope: SDK injection only, or Collector instances too? Right cluster-wide choice?

**Scope: BOTH, via two separate CRDs.** The OpenTelemetry Operator is "a Kubernetes Operator that
manages OpenTelemetry Collectors and auto-instrumentation of workloads." It exposes:

- The **`OpenTelemetryCollector` CRD**: creates and manages Collector instances the Operator owns,
  in modes DaemonSet, Sidecar, StatefulSet, or Deployment.
- The **`Instrumentation` CRD**: configures and injects language SDK auto-instrumentation
  (Java, Python, Node.js, .NET, Go, plus Apache HTTPD / Nginx) into workload pods.

Sources: https://github.com/open-telemetry/opentelemetry-operator ;
https://opentelemetry.io/docs/platforms/kubernetes/operator/

**Is it the right cluster-wide choice here? No.** The Operator is the right cluster-wide choice
when you want a CRD-managed control plane to (a) template many Collectors and/or (b) inject SDKs
broadly across many app pods, especially compiled-language or framework-heavy fleets where
zero-code injection is a large win. This stack has neither shape:

- The Collector is a **single standalone DaemonSet**, already pinned and ArgoCD-managed, with a
  hand-tuned neutral pipeline (`research/24` §1.1). There is exactly one Collector, so there is
  nothing for the Collector-management half of the Operator to template or scale.
- The pods needing SDK injection number exactly **two** (guard-proxy in M2, guard-proxy + the
  M3 beats), one of which should not be instrumented at all. That is per-component territory, not
  cluster-wide-mechanism territory.

So per-component delivery is sufficient and is the better fit. See the decision and plan at the
end. Confidence: HIGH.

---

## Q2. Coexistence of the Operator with a STANDALONE Collector: normal pattern? Who owns what?

**Yes, coexistence is explicitly supported and common, but it is not relevant unless you also want
SDK injection.** The Instrumentation CRD's `spec.exporter.endpoint` "defines where to send data
to" and can point at **any** OTLP-compatible receiver, a Collector managed by the Operator OR an
external/standalone one. The docs are explicit that deploying a Collector via the Operator is
optional: "If you chose not to use a Collector, you can skip to the next section." There is no
requirement that the Collector be Operator-managed for the Instrumentation CRD to function.
Source: https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/

**Layer ownership in the coexistence pattern:**

- **Operator (Instrumentation CRD + mutating webhook):** owns *getting the SDK into app pods*. On
  a pod annotated `instrumentation.opentelemetry.io/inject-python: "true"`, the webhook adds an
  init container (`opentelemetry-auto-instrumentation`) that copies the prebuilt SDK into an
  `emptyDir`, and sets `PYTHONPATH` so the app process loads it. It also stamps the OTLP endpoint,
  resource attributes, sampler, and propagators from the CRD.
  Source: https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/
- **Standalone Collector (unchanged):** owns *receiving, processing, and exporting* telemetry: the
  OTLP receivers, batch/memory_limiter/resource processors, the `spanmetrics` connector, and the
  `datadog` / `prometheusremotewrite` / `otlp/tempo` exporters (`gitops/apps/otel-collector.yaml`).
  The injected SDK simply exports OTLP to this Collector's `:4317`/`:4318`.

So if the Operator were used here, it would own injection only and the standalone Collector would
keep owning the pipeline. **But** the only value of that arrangement is injection, and Q3 shows
injection does not actually work for the guard-proxy. Confidence: HIGH that coexistence is a normal
supported pattern; HIGH that it adds no value here given Q3.

---

## Q3. Custom Python delivery: Operator init-container injection vs custom image layer vs `opentelemetry-instrument` wrapper

This is the load-bearing question. Three concrete options, evaluated against the **actual** deploy
shape: a stdlib `http.server` script (`proxy.py`) with **no web framework**, mounted from a
ConfigMap into a stock `python:3.12-slim`, started by `command: ["python","/app/proxy.py"]`.

### How the Operator's Python injection actually works (mechanism, confirmed)

The Operator does NOT rewrite the container command. It injects an init container that copies a
**prebuilt** instrumentation tree into a shared volume and sets `PYTHONPATH` to
`/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:/otel-auto-instrumentation-python`.
Because activation is a `sitecustomize` loaded off `PYTHONPATH`, it is **command-agnostic**: it
works whether the command is `python /app/proxy.py` or `sh -c "... && exec python /app/server.py"`,
as long as the process is CPython and inherits the env. The injected SDK is a fixed package set,
NOT a `opentelemetry-bootstrap` run against the target app.
Sources: https://opentelemetry.io/docs/platforms/kubernetes/operator/troubleshooting/automatic/ ;
https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/

### The decisive finding: what that prebuilt image instruments (and does NOT)

The Operator's `autoinstrumentation/python` image installs a fixed `requirements.txt` pinned to
`opentelemetry-distro==0.63b1` and a fixed list of contrib instrumentations. Read directly, that
list includes `opentelemetry-instrumentation-urllib` (stdlib `urllib.request` CLIENT),
`opentelemetry-instrumentation-urllib3`, `opentelemetry-instrumentation-requests`,
`opentelemetry-instrumentation-wsgi`, `opentelemetry-instrumentation-asgi`,
`opentelemetry-instrumentation-aiohttp-server` (the only `*-server` HTTP hook in the set, and
aiohttp-specific, not stdlib), `opentelemetry-instrumentation-botocore`, the web frameworks
(flask/django/fastapi/falcon/pyramid/starlette/tornado), and DB drivers. The same is true of the
contrib default set: `urllib` and
`wsgi` are in `default_instrumentations` (always installed), framework instrumentations are
library-gated.
Sources: opentelemetry-operator `autoinstrumentation/python/requirements.txt` (read via GitHub
API, 2026-06-23) ; opentelemetry-python-contrib
`opentelemetry-instrumentation/src/opentelemetry/instrumentation/bootstrap_gen.py` (read via GitHub
API; `default_instrumentations` = asyncio, dbapi, exceptions, logging, sqlite3, threading,
**urllib**, **wsgi**).

**There is NO `http.server` / `BaseHTTPRequestHandler` server instrumentation in OpenTelemetry
Python.** The only stdlib-level HTTP coverage is `urllib` (outbound client) and `wsgi`/`asgi`
(which instrument WSGI/ASGI *applications*, i.e. a `wsgi`/`asgi` callable, NOT a raw
`http.server.ThreadingHTTPServer`). `wsgi` is middleware you wrap a WSGI app with; it has nothing
to hook in a `BaseHTTPRequestHandler.do_POST` server. The image does ship one `*-server` HTTP
instrumentation, `opentelemetry-instrumentation-aiohttp-server`, but that is an aiohttp-specific
async server hook (it patches `aiohttp.web`), NOT a hook for stdlib `http.server`; it does nothing
for a `BaseHTTPRequestHandler`-based server either.
Source: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/wsgi/wsgi.html
(WSGI middleware "can be used on any WSGI framework"); contrib registry has no `http.server`
package.

**Consequence for guard-proxy (`proxy.py`).** If the Operator injected Python auto-instrumentation
into the guard-proxy:

- The outbound forward to the agent (`urllib.request.urlopen`) WOULD be auto-instrumented by
  `opentelemetry-instrumentation-urllib`: a CLIENT span with W3C `traceparent` propagation, so the
  agent's spans nest under it. This is genuinely useful and matches `research/29` Q6's propagation
  point.
- The **inbound** A2A request handled by `ThreadingHTTPServer` / `BaseHTTPRequestHandler` would
  produce **no SERVER span**, because no instrumentation hooks stdlib `http.server`. So the proxy
  appears in traces only as a client of the agent, with no inbound span of its own and no place to
  attach the guard-decision attributes (block-list hit, classifier verdict, output redaction) that
  the security beats need (`research/05`, `research/29` Q3/Q6).

That is the core reason auto-instrumentation underdelivers here: the guard-proxy's *value* as a
span is the guardrail decision on the inbound request, and that is exactly the span
auto-instrumentation cannot create for a frameworkless stdlib server.

### The three options, scored

1. **Operator init-container injection.** Mechanism works (command-agnostic via `PYTHONPATH`), but
   produces only the `urllib` CLIENT span and no SERVER/guard span for the guard-proxy. Adds the
   Operator control plane + webhook + cert dependency for a partial result. **Reject** for the
   guard-proxy. (For evil-mcp-shim, injection is technically possible, FastMCP runs on Starlette/
   ASGI which the image DOES instrument, but `research/29` Q4 says do not instrument the untrusted
   prop at all, so still reject.)
2. **`opentelemetry-instrument` wrapper (no Operator).** Change the command to
   `opentelemetry-instrument python /app/proxy.py` after `pip install opentelemetry-distro
   opentelemetry-exporter-otlp`. Identical instrumentation *coverage* to option 1 (same contrib
   libraries), so it has the **same `http.server` gap**: still no inbound SERVER span for the
   stdlib server. It also still needs packages added to the stock image (a `pip install` at startup
   or a baked image). **Reject** as insufficient for the same reason as option 1, and it carries the
   image-mutation cost without the (here-unused) cluster-wide-injection upside.
3. **Custom image layer with the manual OTel SDK (recommended).** Bake `proxy.py` into a pinned
   image with `opentelemetry-api` + `opentelemetry-sdk` +
   `opentelemetry-exporter-otlp-proto-grpc` (or `-http`) and add a few explicit spans: a SERVER
   span around the inbound A2A request carrying the guard-decision attributes, and a CLIENT span
   around the `urllib` forward with `inject(headers)` for W3C propagation. This is exactly the
   minimal manual pattern `research/29` Q6 specifies, and it produces the inbound guard span the
   beats need, which neither auto-instrumentation option can. The cost is real (the proxy is
   deliberately stdlib-only and ConfigMap-mounted today, so this means baking an image or
   `pip install` at startup), but `research/29` already flags that cost and it is incurred by ANY
   approach that puts the OTel SDK into the proxy.

**Concrete answer to "which fits a ConfigMap-mounted stdlib `python:3.12-slim` script": none of
the auto paths fit it well.** The ConfigMap+stock-image pattern was chosen so no image build is
needed for the test cluster; every OTel delivery option breaks that property (the SDK is not in
the stock image). Given the SDK must arrive somehow, prefer the manual SDK in a baked image
(option 3) because it is the only option that yields the inbound guard SERVER span. evil-mcp-shim:
no delivery at all (`research/29` Q4).

Confidence: HIGH on the `http.server` instrumentation gap (read from the contrib bootstrap and the
Operator image requirements directly) and on the mechanism being `PYTHONPATH`/command-agnostic.

---

## Q4. Bundled-OTel components (kagent/ADK, agentgateway): does the Operator add value?

**No. The Operator only helps pods that need SDK *injection*; these pods self-instrument
config-only.** Per `research/29`:

- **kagent / ADK:** tracing is OFF by default and turned on with Helm values
  (`otel.tracing.enabled: true`, `otel.tracing.exporter.otlp.endpoint`). The GenAI spans come from
  the Google ADK runtime bundled in the agent; no SDK injection is needed and the Operator has
  nothing to add. (`research/29` Q1.)
- **agentgateway v1.3.0:** built-in OTel tracing, activated in the config file under
  `frontendPolicies.tracing.otlpEndpoint` (NOT the env var the repo currently uses). Config-only;
  the Operator adds nothing. (`research/29` Q2.)

For any component that ships its own OTel, the Operator's injection is redundant at best and a
double-instrumentation risk at worst (two SDKs in one process). The Operator's value is strictly
"inject an SDK into a pod that has none," which does not apply to kagent or agentgateway.
Confidence: HIGH.

---

## Q5. OTEL_* env var configuration when the Operator is in play: Instrumentation CRD vs Helm vs pod env vs a mix

For completeness (so a future reader knows the tradeoff even though the recommendation is NO
Operator), this is **where the three canonical vars live under each delivery model**:

**If the Operator were used (Instrumentation CRD path):** the CRD owns most of it, with a defined
precedence:

- `OTEL_EXPORTER_OTLP_ENDPOINT`: set by the CRD's `spec.exporter.endpoint`. The Operator also sets
  `OTEL_EXPORTER_OTLP_PROTOCOL` (e.g. `http/protobuf` for Python) automatically.
- `OTEL_SERVICE_NAME`: derived by a priority chain, explicit `OTEL_SERVICE_NAME` env >
  `resource.opentelemetry.io/service.name` annotation > `app.kubernetes.io/name` label (when
  `useLabelsForResourceAttributes=true`) > the workload (Deployment/...) name > pod name >
  container name.
- `OTEL_RESOURCE_ATTRIBUTES`: composed from `spec.resource.resourceAttributes` (lowest priority in
  the resolution chain) plus Operator-added k8s semconv attributes; can be overridden by explicit
  pod env.
- Arbitrary OTEL_* (e.g. `OTEL_SEMCONV_STABILITY_OPT_IN`): CRD `spec.env` (global) or
  `spec.python.env` (language-scoped).

Source: https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/

So under the Operator it is **mostly the Instrumentation CRD**, with two deliberate overrides: pod
env wins for per-pod values, and Helm values are not in the loop for SDK config (Helm configures
the Operator/Collector themselves, not the injected SDK).

**In the recommended (no-Operator) model:** OTEL_* live as **pod env on each workload**, which is
already how this repo does UST (`OTEL_RESOURCE_ATTRIBUTES` on the kagent Agent and intended for the
proxy). `OTEL_EXPORTER_OTLP_ENDPOINT` points at the standalone Collector Service; `OTEL_SERVICE_NAME`
and `OTEL_RESOURCE_ATTRIBUTES` carry the UST vocabulary locked in PRD #7 Milestone 1; the agent/
gateway take their own native config (Helm values / `frontendPolicies.tracing`) for the endpoint per
`research/29`. This is a mix only in the sense that bundled-OTel components use their native config
field and the manual-SDK proxy uses pod env, no CRD needed. Confidence: HIGH.

---

## Q6. Platform Prometheus-only emitters (cert-manager, ESO, Falco): does the Operator interact?

**No. The Operator never scrapes anything.** Scraping is done by the **Collector** (its Prometheus
receiver), or by the Datadog Agent via Autodiscovery annotations (`research/24` §1.2). The
Operator's only Prometheus-adjacent feature is the optional **Target Allocator**, which discovers
scrape targets and distributes the scrape config to Operator-managed Collectors; the Collector
still does the actual scraping. The Target Allocator only applies to Collectors the Operator
manages, so it is irrelevant to a standalone Collector.
Source: https://opentelemetry.io/docs/platforms/kubernetes/operator/target-allocator/

For cert-manager, ESO, and Falco specifically: they expose Prometheus metrics, which are collected
by the existing scrape path (the Collector's Prometheus receiver and/or the Datadog Agent), exactly
as in `research/18` / `research/24`. The Operator would add nothing to this path. Confidence: HIGH.

---

## Q7. GitOps shape, and a concrete Instrumentation CRD scoped to this stack

Per the acceptance criteria, since the decision is NO, the operative deliverable is the
**per-component delivery plan** (next section). For completeness and to make the rejection
auditable, here is what the Operator GitOps shape *would* have been, plus the CRD scoped to this
stack's custom Python pods, so it is on record that it was evaluated concretely and not hand-waved.

**Operator deploy (the path NOT taken):** the Operator ships as a Helm chart
`opentelemetry-operator` from `https://open-telemetry.github.io/opentelemetry-helm-charts` (latest
chart 0.117.0 / app 0.153.0 as of 2026-06-23, verified against the chart's `Chart.yaml` on `main`
and ArtifactHub; the chart advances roughly weekly, so re-check at build time), so it slots into the
same ArgoCD-Application pattern
as `gitops/apps/otel-collector.yaml`. cert-manager is already in this stack
(`gitops/apps/cert-manager.yaml`), so `admissionWebhooks.certManager.enabled: true` is the clean
webhook-cert path (alternatively `admissionWebhooks.autoGenerateCert.enabled: true` with
cert-manager disabled). The Operator chart, the Instrumentation CRD, and the pod annotations would
be three new moving parts.
Sources: https://github.com/open-telemetry/opentelemetry-helm-charts/tree/main/charts/opentelemetry-operator ;
https://artifacthub.io/packages/helm/opentelemetry-helm/opentelemetry-operator

**Concrete, VALID-YAML Instrumentation CRD scoped to this stack's custom Python pods** (the
artifact the acceptance criteria asks for IF the Operator were adopted; included so the evaluation
is concrete). It points at the existing standalone Collector and is namespaced to `agent`, where
the custom Python pods run:

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: watch-it-burn-python
  namespace: agent
spec:
  # Export to the EXISTING standalone otelcol-contrib 0.158.2 DaemonSet (not an Operator-managed
  # Collector). http/protobuf to the node-local Collector's OTLP HTTP receiver on 4318.
  exporter:
    endpoint: http://otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4318
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_always_on
  # GenAI semconv is Development; opt into the latest experimental attribute names (research/05,
  # research/29). Applied to all injected languages here.
  env:
    - name: OTEL_SEMCONV_STABILITY_OPT_IN
      value: gen_ai_latest_experimental
  python:
    env:
      # Content capture OFF by default to avoid the re-leak trap (research/05); a security-beat
      # build would set EVENT_ONLY deliberately, never `true` (research/29 Q5).
      - name: OTEL_PYTHON_LOG_CORRELATION
        value: "true"
```

To target a pod, you would annotate its template
(`instrumentation.opentelemetry.io/inject-python: "true"`). **This CRD is shown to demonstrate the
evaluated alternative; the recommendation is NOT to apply it, because (Q3) it would not produce the
guard-proxy's inbound guard SERVER span.**

Confidence: HIGH that this is the correct GitOps shape and a valid CRD; the YAML is for the record,
not for application.

---

## Decision and per-component delivery plan

**OTel Operator: NO.** Reasoning, given the full stack:

1. **Collector half adds nothing.** One standalone, ArgoCD-managed, hand-tuned Collector exists and
   is the locked neutral layer (`research/24` §1.1). There is nothing to template or scale, and
   wrapping it in the `OpenTelemetryCollector` CRD would reduce the swappability the architecture
   exists to preserve.
2. **Injection half does not deliver for the one pod it would target.** The Operator's prebuilt
   Python image has no `http.server` server instrumentation, so it cannot create the guard-proxy's
   inbound guard SERVER span, which is the proxy's entire telemetry value for the security beats
   (Q3). It would only auto-create the `urllib` CLIENT span, which the manual SDK does anyway plus
   the SERVER span.
3. **Every other component in issue #15's stack table needs no SDK injection.** kagent/ADK and
   agentgateway are config-only (Q4). Istio ambient (OTel + Prometheus native), Kyverno (native-OTLP
   opt-in), and ArgoCD (built-in OTel support) emit via their own native config, not an injected SDK.
   cert-manager/ESO/Falco are Prometheus-only and scraped by the Collector / Datadog Agent, untouched
   by the Operator (Q6). The two "TBD" rows (customer-stream generator, Backstage) are out of M2/M3
   scope; Backstage is the single Node.js pod the Operator could theoretically inject, but one
   out-of-scope candidate does not justify the Operator's control plane (see the stack-coverage table
   in the TL;DR and Q4).
4. **Cost of adopting it is real:** a new Helm-chart Application, a mutating admission webhook, a
   webhook cert, and the Instrumentation CRD, to deliver partial instrumentation for two pods (one
   of which must not be instrumented at all). Per-component delivery is strictly simpler and
   produces better telemetry.

### Per-component delivery plan for the custom Python pods

**guard-proxy (M2, and M3 inherits it):**

- **Delivery mechanism: custom image layer + manual OTel SDK.** Bake `proxy.py` into a pinned image
  (replacing the ConfigMap-mounted stock `python:3.12-slim`) with `opentelemetry-api`,
  `opentelemetry-sdk`, and `opentelemetry-exporter-otlp-proto-grpc` (or `-http`). This is the only
  option that produces the inbound guard SERVER span; auto-instrumentation cannot (Q3).
- **Spans:** a SERVER span around the inbound A2A request carrying guard-decision attributes
  (block-list hit, classifier verdict, output-redaction outcome), and a CLIENT span around the
  `urllib` forward to the agent with `inject(headers)` for W3C propagation so the agent's
  `gen_ai.*` spans nest under it. This is the exact minimal pattern in `research/29` Q6.
- **OTEL_* config:** pod env. `OTEL_EXPORTER_OTLP_ENDPOINT` -> the standalone Collector Service;
  `OTEL_SERVICE_NAME` + `OTEL_RESOURCE_ATTRIBUTES` -> the PRD #7 Milestone 1 UST vocabulary
  (`OTEL_RESOURCE_ATTRIBUTES` is already wired on the AI layer).
- **Do NOT** attach `gen_ai.usage.*` as authoritative on the proxy span; the agent (ADK) owns the
  GenAI usage attributes to avoid double-counting in Datadog (`research/29` Q3). The Prometheus
  `witb_*` counters stay as the live cost-counter scrape source.
- **Implementation note (not done here):** this is M2/M3 build work, not part of this spike. The
  image-bake cost is the same regardless of delivery mechanism, since the SDK is not in the stock
  image.

**evil-mcp-shim (M3 beats):**

- **Delivery mechanism: NONE. Leave it un-instrumented** (`research/29` Q4). It is an untrusted
  teaching prop; the rogue tool call is narrated by the **agent's** `execute_tool
  {gen_ai.tool.name}` span and the **agentgateway** span, both of which already exist. Instrumenting
  the attacker would muddy the lesson (an untrusted server need not cooperate with your
  observability) and changes nothing visible. No Operator annotation, no SDK, no image change.

**customer-stream generator (custom, issue #15 "Instrumentation TBD"):**

- **Delivery mechanism: out of M2/M3 scope; deferred, not silently dropped.** Issue #15 lists it as a
  third custom component with instrumentation TBD, but it is not part of the M2 (evil-mcp-shim) or M3
  (guard-proxy) milestones, so no delivery decision is forced now. If it is later instrumented and is
  a Python service, it inherits the **guard-proxy pattern**: custom image layer + manual OTel SDK,
  exporting OTLP to the standalone Collector via pod env, NOT the Operator. The same reasoning as Q3
  applies, the Operator's prebuilt Python image still has no `http.server` server instrumentation and
  the manual SDK gives explicit control over span shape. This row is flagged here so the "full
  cluster stack" framing is closed out; the actual instrumentation is its own future build decision.

Confidence: HIGH on guard-proxy and evil-mcp-shim; the customer-stream generator is explicitly
deferred (out of M2/M3 scope) rather than decided.

---

## Cross-cutting risks / verify-at-build

1. **The guard-proxy image-bake is the real cost, and it is unavoidable for ANY OTel delivery.** The
   ConfigMap+stock-image pattern (`gitops/ai-layer/resources.yaml`) cannot carry the OTel SDK; M2
   must bake an image (or `pip install` at startup, weaker). This is a build decision for the M2
   child PRD, not a research finding to implement here. (HIGH)
2. **`http.server` has no OTel server instrumentation, period.** If anyone later argues for
   auto-instrumentation on the proxy, re-confirm the contrib registry still lacks an `http.server`
   package before assuming inbound spans will appear. (HIGH, confirmed 2026-06-23.)
3. **Collector OTLP Service name in the CRD example is illustrative.** If the Operator path is ever
   revisited, verify the actual Service DNS name the Helm chart creates for the standalone Collector
   (`gitops/apps/otel-collector.yaml` deploys via the `opentelemetry-collector` chart; the Service
   name depends on the release name). (LOW; only matters if the rejected path is reopened.)
4. **GenAI semconv is Development.** Whatever delivery is used, set
   `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` deliberately on the agent path and
   pin emitter versions (`research/05`, `research/29`). (HIGH)
5. **Do not double-instrument Bedrock.** Prefer ADK's `gen_ai.*` model span over a botocore span for
   the same call (`research/29` Q5); irrelevant to the proxy (it makes no Bedrock call) but relevant
   to the agent pod. (MEDIUM)

---

## Sources (distinct citations)

1. https://github.com/open-telemetry/opentelemetry-operator : Operator manages OTel Collectors AND
   auto-instrumentation of workloads (the two-CRD scope).
2. https://opentelemetry.io/docs/platforms/kubernetes/operator/ : Operator overview; manages
   Collectors + auto-instrumentation; CRDs and deployment modes.
3. https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/ : injection mechanism
   (init container, annotations, named/cross-namespace Instrumentation reference); Instrumentation
   CRD spec fields (`exporter.endpoint`, `propagators`, `sampler`, `env`, `resource`, per-language
   blocks); service-name priority chain; Collector is optional / can be external; auto-set
   `OTEL_EXPORTER_OTLP_PROTOCOL`.
4. https://opentelemetry.io/docs/platforms/kubernetes/operator/troubleshooting/automatic/ : the
   injected Python init container does `cp -r /autoinstrumentation/. /otel-auto-instrumentation-python`
   and sets `PYTHONPATH` (command-agnostic activation via sitecustomize).
5. https://opentelemetry.io/docs/zero-code/python/operator/ : Operator Python injection;
   Django/gevent env requirements (evidence the injected image is a fixed prebuilt set).
6. https://opentelemetry.io/docs/zero-code/python/ : `opentelemetry-instrument` monkey-patches
   supported libraries; `opentelemetry-bootstrap -a install` detects installed libs.
7. opentelemetry-operator `autoinstrumentation/python/requirements.txt` and `Dockerfile` (read via
   GitHub API, 2026-06-23): the prebuilt image pins `opentelemetry-distro==0.63b1` and a fixed
   instrumentation list including `urllib`, `urllib3`, `requests`, `wsgi`, `asgi`, `botocore`, web
   frameworks; the only `*-server` HTTP instrumentation shipped is `aiohttp-server` (an aiohttp-web
   async hook), NOT a stdlib `http.server` hook. NO `http.server` / `BaseHTTPRequestHandler` package.
   Image is `PYTHONPATH`-based, copied via `cp`.
8. opentelemetry-python-contrib
   `opentelemetry-instrumentation/src/opentelemetry/instrumentation/bootstrap_gen.py` (read via
   GitHub API, 2026-06-23): `default_instrumentations` (always installed) = asyncio, dbapi,
   exceptions, logging, sqlite3, threading, **urllib**, **wsgi**; framework instrumentations are
   library-gated; no `http.server` entry anywhere.
9. https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/wsgi/wsgi.html :
   WSGI instrumentation is middleware for WSGI frameworks (Django/Flask/web.py), not a hook for a
   raw stdlib `http.server`.
10. https://opentelemetry.io/docs/platforms/kubernetes/operator/target-allocator/ : the Target
    Allocator discovers/distributes scrape targets to Operator-managed Collectors; the Collector
    does the scraping; Operator never scrapes itself.
11. https://github.com/open-telemetry/opentelemetry-helm-charts/tree/main/charts/opentelemetry-operator :
    chart name `opentelemetry-operator`, repo `https://open-telemetry.github.io/opentelemetry-helm-charts`;
    cert-manager optional (`admissionWebhooks.certManager.enabled`) or `autoGenerateCert`.
12. https://artifacthub.io/packages/helm/opentelemetry-helm/opentelemetry-operator and
    https://raw.githubusercontent.com/open-telemetry/opentelemetry-helm-charts/main/charts/opentelemetry-operator/Chart.yaml :
    latest chart 0.117.0 / app 0.153.0 (verified 2026-06-23 against `Chart.yaml` on `main` +
    ArtifactHub). The chart advances ~weekly; re-check at build time.

(12 distinct external citations + direct reads of the two GitHub source files; builds on in-repo
`research/05`, `research/18`, `research/24`, `research/28`, `research/29` per instruction, and on
direct reads of `proxy.py`, `server.py`, `gitops/ai-layer/resources.yaml`,
`gitops/apps/otel-collector.yaml`.)

---

## Validation pass (triple-pass adversarial, 2026-06-23)

Three independent adversarial validators reviewed this file. Verdicts and key citations below, then
the corrections applied and the remaining verify-at-build items.

### Lens A (official-docs accuracy)

- Verdict: confirmed 18, refuted 0, unverified 3.
- Confirmed: the two-CRD Operator scope, the `PYTHONPATH`/sitecustomize command-agnostic injection
  mechanism, the absence of an `http.server` server instrumentation in OTel Python, the contrib
  `default_instrumentations` set, the Instrumentation CRD field shape, and the Target Allocator
  scope, all against the OpenTelemetry docs and the operator/contrib source files cited in Sources.
- Unverified (out of scope for an official-docs lens, not refuted): the HIGH/MEDIUM/LOW confidence
  labels and in-repo cross-references (project-internal); the agentgateway v1.3.0
  `frontendPolicies.tracing.otlpEndpoint` claim (sourced to `research/29`, not re-checked against
  agentgateway docs in this pass); the "two SDKs in one process is a double-instrumentation risk"
  point (engineering inference, not a quoted doc statement).
- Corrections requested: note the prebuilt image's only `*-server` HTTP instrumentation is
  `aiohttp-server` (aiohttp-specific, not stdlib `http.server`); refresh the stale chart version;
  keep the bootstrap-vs-prebuilt-image distinction explicit (already correct at the mechanism
  section). All applied.

### Lens B (currency + YAML)

- Verdict: confirmed 11, refuted 0, unverified 1.
- Confirmed: the chart 0.112.0 -> app 0.150.0 mapping is real and internally consistent; the
  Instrumentation CRD YAML is valid (`apiVersion: opentelemetry.io/v1alpha1`,
  `kind: Instrumentation`, with `exporter`/`propagators`/`sampler`/`env`/`python.env` fields all
  current).
- Unverified / currency drift (non-load-bearing, in the rejected Operator path): the file claimed
  chart 0.112.0 / app 0.150.0 was "latest as of 2026-06-23"; the actual latest on that date is chart
  0.117.0 / app 0.153.0 (verified via `Chart.yaml` on `main` + ArtifactHub). Corrected in both
  places. The CRD `apiVersion` was checked and remains current (no invalid/deprecated field).

### Lens C (completeness + soundness)

- Verdict: confirmed 9, refuted 1, unverified 3.
- Refuted (load-bearing wording, now fixed): TL;DR point 3 and Decision point 3 said "Every other
  component ... platform Prometheus-only emitters," which contradicts issue #15's own stack table
  (Istio ambient = "OTel + Prometheus native," Kyverno = "Native OTLP opt-in," ArgoCD = "OTel
  support available," none of them Prometheus-only). The Operator=NO verdict was not undermined (none
  of those need SDK injection), but the justification overclaimed completeness. Rewritten to
  enumerate each stack-table component with its actual posture rather than bucketing all remaining
  components as Prometheus-only.
- Unverified / completeness gaps (now closed): the customer-stream generator (a third custom
  component in the issue table, "Instrumentation TBD") was never addressed; Istio, Kyverno, ArgoCD,
  and Backstage were not dispositioned as component types; Backstage in particular is a Node.js app
  and the Operator does inject Node.js, so it is a plausible (un-examined) injection target. Added a
  full stack-coverage table in the TL;DR, an explicit scope boundary, a per-component disposition
  line for the customer-stream generator in the delivery plan, and a Backstage note (out of M2/M3
  scope, single Node.js pod does not justify the Operator).

### Corrections applied

1. Chart version refreshed to 0.117.0 / app 0.153.0 (verified against `Chart.yaml` on `main` +
   ArtifactHub, 2026-06-23) in the GitOps section and Sources; added a "re-check at build time" note.
2. Replaced the "Every other component / Prometheus-only" overclaim in TL;DR point 3 and Decision
   point 3 with an explicit per-component enumeration consistent with issue #15's stack table.
3. Added a stack-coverage table (every issue #15 component, injection need, Operator help,
   disposition) and an explicit scope boundary in the TL;DR.
4. Added a per-component disposition for the customer-stream generator (out of M2/M3 scope; inherits
   the guard-proxy manual-SDK pattern if later instrumented) and a Backstage note (Node.js, plausible
   Operator target, but out of scope and config-native, does not move the verdict).
5. Noted that the prebuilt image's only `*-server` HTTP instrumentation is `aiohttp-server`
   (aiohttp-specific, not stdlib `http.server`) in Q3 and in Source 7, pre-empting the reviewer
   objection without weakening the core `http.server`-gap finding.
6. Confirmed the Instrumentation CRD YAML uses the current `opentelemetry.io/v1alpha1` apiVersion and
   only current fields; no invalid/deprecated field was present, so no YAML change was required.

### Remaining verify-at-build items

- agentgateway v1.3.0's `frontendPolicies.tracing.otlpEndpoint` activation field is sourced to
  `research/29`; re-confirm against agentgateway's own docs when wiring it in M2/M3 (Lens A
  unverified).
- The opentelemetry-operator chart advances roughly weekly; re-check the latest chart/app version at
  build time if the Operator path is ever revisited (it is not the recommendation).
- The Collector OTLP Service DNS name in the CRD example is illustrative; if the rejected Operator
  path is reopened, verify the actual Service name the `opentelemetry-collector` chart creates (also
  listed in Cross-cutting risks item 3).
