# Weaver: the guard-proxy span contract (PRD #20 M6)

The guard-proxy emits two spans (PRD #22 M1): an HTTP `SERVER` span for the inbound hop and a
gen_ai `sanitize` `INTERNAL` span for the guard decision. `weaver/registry/` is the machine-checkable
contract for those spans, pinned to OpenTelemetry semantic conventions **v1.37.0**. Two checks use it:

| Check | What it proves | When it runs |
|---|---|---|
| `weaver registry check` | The contract itself is well-formed and every `ref:` resolves against upstream semconv v1.37.0. Catches a typo'd or renamed attribute. | CI, on any change under `weaver/` (`.github/workflows/weaver-registry-check.yml`). |
| `weaver registry live-check` | The spans the **running** proxy actually emits match the contract. Catches drift between `proxy.py` and the registry. | Manually, against live telemetry from a deployed cluster. |

## Toolchain

Built and validated on **weaver 0.24.2**. The manifest format changed at 0.22.1 (the file is
`manifest.yaml`, not `registry_manifest.yaml`, and `schema_url` replaces the old
`semconv_version`/`schema_base_url` pair). Do not run these checks with weaver < 0.22.1.

Install the pinned binary (same step CI runs):

```bash
WEAVER_VERSION=v0.24.2
curl -sSfL "https://github.com/open-telemetry/weaver/releases/download/${WEAVER_VERSION}/weaver-x86_64-unknown-linux-gnu.tar.xz" -o weaver.tar.xz
tar xf weaver.tar.xz
install -m 0755 weaver-x86_64-unknown-linux-gnu/weaver ~/.local/bin/weaver
weaver --version
```

## The static check (what CI gates on)

```bash
weaver registry check --registry weaver/registry/
```

This resolves `weaver/registry/manifest.yaml` (which pins the upstream registry to the v1.37.0 tag
archive) and validates `weaver/registry/guard-proxy-spans.yaml`. Every `ref:` in the span groups must
name a real upstream attribute. A clean run prints `No after_resolution policy violation` and exits 0.
The check needs network access to fetch the pinned semconv archive on the first run; weaver caches it
under `~/.weaver/` afterward.

## The live check (against the running proxy)

`weaver registry live-check` compares real telemetry to the same registry. It reads telemetry from a
file, stdin, or a built-in OTLP listener (`--input-source`, default `otlp`).

### Path A: file input (recommended for the workshop)

Capture the proxy's spans into weaver's sample-telemetry JSON and check them offline. The format is a
JSON array of tagged samples; each span is `{"span": {...}}` with attributes as `{name, value}` pairs.
This is the exact shape weaver 0.24.2 accepts (verified):

```json
[
  {"span": {"name": "sanitize", "kind": "internal", "attributes": [
    {"name": "gen_ai.operation.name", "value": "chat"},
    {"name": "gen_ai.input.messages", "value": "[{\"role\":\"user\",\"parts\":[{\"type\":\"text\",\"content\":\"...\"}]}]"},
    {"name": "gen_ai.output.messages", "value": "[{\"role\":\"user\",\"parts\":[{\"type\":\"text\",\"content\":\"...\"}]}]"}
  ]}},
  {"span": {"name": "POST /a2a", "kind": "server", "attributes": [
    {"name": "http.request.method", "value": "POST"},
    {"name": "url.path", "value": "/a2a"},
    {"name": "http.response.status_code", "value": 200}
  ]}}
]
```

```bash
weaver registry live-check --registry weaver/registry/ \
  --input-source spans.json --input-format json
```

**Gotcha when sourcing spans from Tempo:** Tempo's `/api/traces/<id>` returns OTLP/JSON, which encodes
int64 attribute values as JSON strings (e.g. `http.response.status_code` comes back as
`{"intValue": "200"}`). If you flatten that to the JSON string `"200"` in the live-check input,
live-check reports a spurious `Attribute 'http.response.status_code' has type 'string'. Type should be
'int'.` violation. Coerce by the OTLP value tag when shaping the input: `intValue` to int, `doubleValue`
to float, `boolValue` to bool. The proxy emits the correct int; the artifact is purely in the OTLP/JSON
transport. With coercion, the real guard-proxy spans pass clean (verified 2026-06-25).

Exit 0 means every span conformed; exit 1 means at least one `violation`-level finding. The report
groups advice per span. Example output for a span that drifted (operation name set to `sanitize`
instead of `chat`, plus a stray attribute):

```
Span sanitize `internal`
    gen_ai.operation.name = sanitize
        - [information] Enum attribute 'gen_ai.operation.name' has value 'sanitize' which is not documented.
    witb.totally_made_up = x
        - [violation] Attribute 'witb.totally_made_up' does not exist in the registry.
```

The contract marks the guard-proxy groups `stability: development`, so live-check also emits a
non-fatal `improvement` advisory noting the attributes are not stable. That is expected for a workshop
demo contract and does not fail the check; only `violation`-level findings set exit 1.

### Path B: OTLP listener (live wiring)

Run weaver as an OTLP receiver and stream telemetry into it:

```bash
weaver registry live-check --registry weaver/registry/ \
  --otlp-grpc-port 4317 --admin-port 4320 --inactivity-timeout 30
# POST /stop on the admin port (or wait out the inactivity timeout) to finalize the report.
```

Then point an OTLP exporter at the listener. For the in-cluster Collector, weaver must be reachable
from the cluster (the Collector lives in the cluster; weaver runs on the laptop), so this path needs a
tunnel back to the laptop. For a quick local loop, run the proxy locally with
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` and exercise it. Path A is simpler for the demo
because it has no network-reachability requirement.

## Keeping the contract honest

The registry is only useful if it tracks reality. When `proxy.py` changes which attributes it sets on
the `SERVER` or `sanitize` spans, update `weaver/registry/guard-proxy-spans.yaml` in the same change.
CI's `weaver registry check` proves the registry resolves; a periodic `live-check` against a running
cluster proves the proxy still matches it.
