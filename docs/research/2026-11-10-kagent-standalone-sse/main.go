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
