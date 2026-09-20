// zencli — minimalist OpenAI-compatible server in front of opencode zen.
//
// One binary, zero dependencies (stdlib only). Serves GET /v1/models +
// POST /v1/chat/completions (non-stream + SSE) by driving the genuine
// `opencode` CLI subprocess per request — the only client the vendor
// gate passes. Selected keys are isolated per request; no default CLI auth.
//
// Usage:
//
//	./zencli -port 8099   # serves on 127.0.0.1:8099
package main

import (
	"crypto/rand"
	"crypto/subtle"
	"flag"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

// Msg mirrors one OpenAI chat message (content: string or parts array).
type Msg struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
}

// ChatReq is the subset of chat/completions we map to the CLI.
type ChatReq struct {
	Model    string `json:"model"`
	Messages []Msg  `json:"messages"`
	Stream   bool   `json:"stream"`
}

// textOf extracts plain text from string or parts-array content.
func textOf(c any) string {
	switch t := c.(type) {
	case string:
		return t
	case []any:
		var sb strings.Builder
		for _, p := range t {
			if m, ok := p.(map[string]any); ok {
				if s, ok := m["text"].(string); ok {
					sb.WriteString(s)
				}
			}
		}
		return sb.String()
	}
	return ""
}

// buildPrompt flattens system + multi-turn messages into one CLI prompt.
// System first (verbatim), then turns labeled; last user message raw when
// it is the only content (common case: byte-identical prompt).
func buildPrompt(msgs []Msg) string {
	var sys []string
	type turn struct{ role, text string }
	var turns []turn
	for _, m := range msgs {
		t := strings.TrimSpace(textOf(m.Content))
		if t == "" {
			continue
		}
		if m.Role == "system" {
			sys = append(sys, t)
			continue
		}
		if m.Role == "tool" {
			turns = append(turns, turn{"Tool result", t})
			continue
		}
		turns = append(turns, turn{m.Role, t})
	}
	if len(sys) == 0 && len(turns) == 1 && turns[0].role == "user" {
		return turns[0].text
	}
	var sb strings.Builder
	for _, s := range sys {
		sb.WriteString(s)
		sb.WriteString("\n\n")
	}
	for i, t := range turns {
		if i == len(turns)-1 && t.role == "user" && len(turns) > 1 {
			sb.WriteString(t.text)
			continue
		}
		name := t.role
		if name == "assistant" {
			name = "Assistant"
		} else if name == "user" {
			name = "User"
		}
		sb.WriteString(name + ": " + t.text + "\n\n")
	}
	return strings.TrimSpace(sb.String())
}

// requireAuth never permits an unauthenticated bridge, including loopback.
func requireAuth(token string, h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store, private")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		if token == "" || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		h(w, r)
	}
}

func rid(prefix string, n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
	var sb strings.Builder
	sb.WriteString(prefix)
	for _, v := range b {
		sb.WriteByte(alpha[int(v)%len(alpha)])
	}
	return sb.String()
}

func main() {
	port := flag.String("port", "8099", "private loopback port")
	bin := flag.String("opencode-bin", "/usr/local/bin/opencode", "pinned genuine CLI binary")
	flag.Parse()
	token := os.Getenv("KEEPER_ZENCLI_TOKEN")
	if token == "" {
		fmt.Fprintln(os.Stderr, "internal bridge token required")
		os.Exit(2)
	}
	b := newBridge(*bin)
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/chat/completions", requireAuth(token, b.chat))
	mux.HandleFunc("/v1/models", requireAuth(token, b.list))
	mux.HandleFunc("/internal/catalog", requireAuth(token, b.catalog))
	server := &http.Server{Addr: "127.0.0.1:" + *port, Handler: mux, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 120 * time.Second}
	fmt.Fprintln(os.Stderr, "zencli private loopback ready")
	if err := server.ListenAndServe(); err != nil {
		fmt.Fprintln(os.Stderr, "zencli stopped")
		os.Exit(1)
	}
}
