# kagent's RemoteMCPServer timeout and go-sdk's standalone stream (#1306), 2026-11-10

#1303 found that the workshop agent's MCP sessions die about three minutes after they open, and worked around it on
our side (a 405 for GET on agentgateway's MCP binds, and a 12h timeout on evil-mcp's RemoteMCPServer). This directory
holds the report for kagent upstream and a reproduction that needs no cluster.

- `upstream-issue.md`: the issue drafted for kagent-dev/kagent, with its title in the comment at the top. It has not
  been filed; filing publishes, so a person decides whether to.
- `main.go`, `go.mod`, `go.sum`: the reproduction, on go-sdk v1.8.0 (the version kagent v1.0.0 pins). A go-sdk
  streamable server that never pushes, behind `httptest`, and a go-sdk client built as kagent's `createTransport`
  builds it. It needs go 1.25 or later and network the first time.

```
cd docs/research/2026-11-10-kagent-standalone-sse
go run . -mode timeout      # http.Client.Timeout 2s, as kagent sets it: the session dies near 19 s
go run . -mode nosse        # the same with DisableStandaloneSSE: every call passes
go run . -mode notimeout    # no http.Client.Timeout: every call passes
go run . -mode timeout -timeout 30s -for 220s   # kagent's CRD default
```

## What it showed, 2026-11-10

| go-sdk | mode | timeout | calls passed | calls failed | first failure |
|---|---|---|---|---|---|
| v1.8.0 | timeout | 2s | 19 | 6 | 19.0 s |
| v1.8.0 | nosse | 2s | 25 | 0 | none |
| v1.8.0 | notimeout | none | 25 | 0 | none |
| v1.6.1 | timeout | 2s | 20 | 5 | 20.1 s |
| v1.6.1 | nosse | 2s | 25 | 0 | none |
| v1.8.0 | timeout | 30s (220 s run) | 187 | 33 | 187.4 s |

Every failure was `connection closed: calling "tools/call": client is closing: standalone SSE stream: exceeded 5
retries without progress`. The v1.6.1 rows ran the same `main.go` after `go get
github.com/modelcontextprotocol/go-sdk@v1.6.1` in a scratch copy.

## Read from the sources at v0.10.1 and v1.0.0

- kagent `go/adk/pkg/mcp/registry.go`, `createTransport`: both tags build `&http.Client{Timeout: httpTimeout, ...}`
  and hand it to `StreamableClientTransport`; `sseReadTimeout` changes `httpTimeout` only for server type `sse`.
- kagent's RemoteMCPServer `timeout` defaults to `30s` in v1alpha2 (0.10.1) and v1alpha3 (v1.0.0).
- go-sdk `mcp/streamable.go` at v1.6.1 and v1.8.0: `MaxRetries` defaults to 5, and `handleSSE` calls `c.fail` once
  `retriesWithoutProgress` passes it. The two tags differ in that function only in `checkResponse` taking a context.
