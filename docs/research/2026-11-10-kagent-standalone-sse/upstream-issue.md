<!-- The issue drafted for kagent-dev/kagent (#1306). Not filed: filing publishes, so a person decides. -->
<!-- Title: RemoteMCPServer timeout ends every streamable-HTTP MCP session after six timeouts (standalone SSE stream) -->

### Summary

The Go ADK sets a RemoteMCPServer's `timeout` as `http.Client.Timeout` on go-sdk's `StreamableClientTransport`
(`go/adk/pkg/mcp/registry.go`, `createTransport`). That client also carries the standalone GET stream go-sdk opens
after `initialize`. The timeout cuts that stream every `timeout`, and when the server has pushed nothing on it, go-sdk
counts each cut as a reconnect without progress. After the sixth (its default `MaxRetries` is 5) go-sdk fails the whole
connection, and every tool call in flight fails with:

```
connection closed: calling "tools/call": client is closing: standalone SSE stream: exceeded 5 retries without progress (session ID: ...)
```

With the CRD default of `30s`, every streamable-HTTP session to a server that never sends server-initiated messages
dies about three minutes after it opens. A tool call that is running at that moment fails, and the agent answers
without its result. The next turn opens a new session, so it shows up as an occasional, timing-dependent tool failure.

### Versions

- Seen on kagent 0.10.1 (`ghcr.io/kagent-dev/kagent/golang-adk:0.10.1`, go-sdk v1.6.1).
- Still present at v1.0.0, read from the source: `createTransport` still sets `Timeout: httpTimeout` on the
  `http.Client` it hands to `StreamableClientTransport`, the v1alpha3 RemoteMCPServer `timeout` still defaults to
  `30s`, and go-sdk v1.8.0's `handleSSE` has the same retries-without-progress check.

### Where it happens

- kagent `go/adk/pkg/mcp/registry.go`, `createTransport`: `httpClient := &http.Client{Timeout: httpTimeout, ...}`,
  then `&mcpsdk.StreamableClientTransport{Endpoint: params.URL, HTTPClient: httpClient}`. `sseReadTimeout` only
  applies when the server type is `sse`.
- go-sdk `mcp/streamable.go`: `connectStandaloneSSE` opens the GET stream unless `DisableStandaloneSSE` is set or the
  server answers 405. `handleSSE` reconnects when the stream ends, and when no new event id arrived it increments
  `retriesWithoutProgress`; once that passes `maxRetries` it calls `c.fail(...)`, which closes the connection.

### What we measured

On a cluster running kagent 0.10.1 with two RemoteMCPServers at the default `30s`, every standalone GET the agent
made to the MCP servers (through agentgateway) lasted 29995 to 30002 ms in the gateway's access log, and the sixth cut
fell about 187 seconds after `initialize`. A prompt that chains two tool calls succeeded 17 of 17 times when sent at
no chosen time, and failed 2 of 3 times when timed so the calls were in flight at the sixth cut; both failures logged
the error above.

### Reproduction (no cluster)

A go-sdk server that never pushes, and a go-sdk client built as `createTransport` builds it, with a 2-second timeout so
it takes seconds instead of minutes. The client calls a tool once a second for 25 seconds. The program is a single
`main.go` on go-sdk v1.8.0, in full under the output below.

```
$ go run . -mode timeout       # http.Client.Timeout = 2s, as createTransport sets it
first failure at 19.0s: connection closed: calling "tools/call": client is closing: standalone SSE stream: exceeded 5 retries without progress (session ID: ...)
mode=timeout timeout=2s: 19 calls passed, 6 failed

$ go run . -mode nosse         # the same, plus DisableStandaloneSSE: true
mode=nosse timeout=2s: 25 calls passed, 0 failed

$ go run . -mode notimeout     # no http.Client.Timeout
mode=notimeout timeout=0s: 25 calls passed, 0 failed
```

On go-sdk v1.6.1 the first failure came at 20.1 s. With the timeout at the CRD default (`-timeout 30s -for 220s`) the
first failure came at 187.4 s, after 187 calls passed, the same 187 seconds measured on the cluster.

### Possible fixes

1. Keep the operation timeout off the `http.Client` for streamable HTTP and bound each call with a context deadline
   instead, so the long-lived standalone GET is not cut.
2. Set `DisableStandaloneSSE: true` on the `StreamableClientTransport`, if the ADK does not use server-initiated
   messages on that stream.
3. Expose go-sdk's `MaxRetries` on RemoteMCPServer. This only moves the failure later, so 1 or 2 is the real fix.

### Workaround

Either make the MCP server (or the gateway in front of it) answer `GET` on the MCP path with `405 Method Not
Allowed`, which tells go-sdk there is no standalone stream, or raise the RemoteMCPServer `timeout` far enough that six
of them outlast the session (we set `12h` on one server).

<details><summary>main.go (go-sdk v1.8.0)</summary>

```go
// Reproduces kagent's MCP client setup (go/adk/pkg/mcp/registry.go, createTransport):
// a go-sdk StreamableClientTransport whose http.Client carries the RemoteMCPServer
// timeout. The server below is a plain go-sdk streamable server that never pushes
// on the standalone GET stream. The client calls a tool once a second.
//
//	go run . -mode timeout      # http.Client.Timeout set, as kagent does: the session dies
//	go run . -mode nosse        # same, plus DisableStandaloneSSE: every call passes
//	go run . -mode notimeout    # no http.Client.Timeout: every call passes
package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type empty struct{}

func main() {
	mode := flag.String("mode", "timeout", "timeout | nosse | notimeout")
	timeout := flag.Duration("timeout", 2*time.Second, "http.Client.Timeout (kagent's CRD default is 30s)")
	runFor := flag.Duration("for", 25*time.Second, "how long to keep calling the tool")
	flag.Parse()

	server := mcp.NewServer(&mcp.Implementation{Name: "quiet-server", Version: "v0"}, nil)
	mcp.AddTool(server, &mcp.Tool{Name: "ping", Description: "answers pong"},
		func(ctx context.Context, req *mcp.CallToolRequest, in empty) (*mcp.CallToolResult, empty, error) {
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: "pong"}}}, empty{}, nil
		})
	ts := httptest.NewServer(mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server }, nil))
	defer ts.Close()

	hc := &http.Client{}
	if *mode != "notimeout" {
		hc.Timeout = *timeout
	}
	transport := &mcp.StreamableClientTransport{
		Endpoint:             ts.URL,
		HTTPClient:           hc,
		DisableStandaloneSSE: *mode == "nosse",
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "kagent-like-client", Version: "v0"}, nil)
	ctx := context.Background()
	session, err := client.Connect(ctx, transport, nil)
	if err != nil {
		fmt.Println("connect:", err)
		os.Exit(2)
	}
	defer session.Close()

	start := time.Now()
	passed, failed := 0, 0
	for time.Since(start) < *runFor {
		_, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "ping"})
		if err != nil {
			failed++
			if failed == 1 {
				fmt.Printf("first failure at %.1fs: %v\n", time.Since(start).Seconds(), err)
			}
		} else {
			passed++
		}
		time.Sleep(time.Second)
	}
	fmt.Printf("mode=%s timeout=%s: %d calls passed, %d failed\n", *mode, hc.Timeout, passed, failed)
	if failed > 0 {
		os.Exit(1)
	}
}
```

</details>
