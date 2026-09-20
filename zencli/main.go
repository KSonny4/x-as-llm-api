// zencli — minimalist OpenAI-compatible server in front of opencode zen.
//
// One binary, zero dependencies (stdlib only). Serves GET /v1/models +
// POST /v1/chat/completions (non-stream + SSE) by driving the genuine
// `opencode` CLI subprocess per request — the only client the vendor
// gate passes. No server-side key: the CLI uses its own auth.
//
// Usage:
//
//	./zencli -port 8099   # serves on 127.0.0.1:8099
package main

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
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

// writeSSE emits format-exact SSE (word chunks + DONE). Format parity:
// clients parsing event-streams work unchanged. NOT token-realtime —
// the completion is produced by one subprocess run, then chunked.
func writeSSE(w http.ResponseWriter, id, model, text string, fl http.Flusher) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	chunk := func(content string, finish any) string {
		d, _ := json.Marshal(map[string]any{
			"id":      id,
			"object":  "chat.completion.chunk",
			"created": time.Now().Unix(),
			"model":   model,
			"choices": []any{map[string]any{
				"index":         0,
				"delta":         map[string]string{"content": content},
				"finish_reason": finish,
			}},
		})
		return "data: " + string(d) + "\n\n"
	}
	fmt.Fprint(w, chunk("", nil))
	if fl != nil {
		fl.Flush()
	}
	for _, word := range strings.SplitAfter(text, " ") {
		if word == "" {
			continue
		}
		fmt.Fprint(w, chunk(word, nil))
		if fl != nil {
			fl.Flush()
		}
	}
	fmt.Fprint(w, chunk("", "stop"))
	fmt.Fprint(w, "data: [DONE]\n\n")
}

// serveExec implements POST /v1/chat/completions by driving the genuine
// opencode CLI subprocess (the only client proven to pass the gate).
// No ZEN_API_KEY needed: the CLI uses its own auth. Minimal mapping:
// last user message -> prompt, model "X" -> "opencode/X" (unless already
// prefixed); CLI stdout -> chat.completion JSON. Per-request temp cwd.
func serveExec(bin string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err != nil || len(body) == 0 {
			http.Error(w, "bad body", http.StatusBadRequest)
			return
		}
		var req ChatReq
		if err := json.Unmarshal(body, &req); err != nil || req.Model == "" {
			http.Error(w, "bad chat body", http.StatusBadRequest)
			return
		}
		prompt := buildPrompt(req.Messages)
		if prompt == "" {
			http.Error(w, "no prompt content", http.StatusBadRequest)
			return
		}
		model := req.Model
		if !strings.Contains(model, "/") {
			model = "opencode/" + model
		}
		dir, err := os.MkdirTemp("", "zencli-exec-")
		if err != nil {
			http.Error(w, "tmpdir", http.StatusInternalServerError)
			return
		}
		defer os.RemoveAll(dir)
		ctx, cancel := context.WithTimeout(r.Context(), 110*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, bin, "run", "--model", model, "--pure", prompt)
		cmd.Dir = dir
		out, err := cmd.Output()
		if err != nil {
			http.Error(w, "opencode: "+err.Error(), http.StatusBadGateway)
			return
		}
		text := strings.TrimSpace(string(out))
		id := "chatcmpl-" + rid("", 12)
		if req.Stream {
			fl, _ := w.(http.Flusher)
			writeSSE(w, id, req.Model, text, fl)
			return
		}
		resp := map[string]any{
			"id":      id,
			"object":  "chat.completion",
			"created": time.Now().Unix(),
			"model":   req.Model,
			"choices": []any{map[string]any{
				"index": 0,
				"message": map[string]string{
					"role":    "assistant",
					"content": text,
				},
				"finish_reason": "stop",
			}},
			"usage": map[string]int{},
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

// zenModels is the served catalog: free models observed working via the
// CLI backend (2026-09-20). No vendor touch to list.
var zenModels = []struct {
	id, name string
	ctx      int
}{
	{"big-pickle", "Big Pickle", 200000},
	{"mimo-v2.5-free", "Mimo (free)", 200000},
	{"muse-spark-1.2-contributor-free", "Muse Spark 1.2 (free)", 1000000},
	{"muse-spark-1.3-contributor-free", "Muse Spark 1.3 (free)", 1000000},
	{"nemotron-3-ultra-free", "Nemotron Ultra (free)", 1000000},
	{"nemotron-3.5-lightning-free", "Nemotron Lightning (free)", 262144},
	{"ling-3.0-flash-fin-free", "Ling Flash (free)", 262144},
}

func serveModels(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	data := make([]any, 0, len(zenModels))
	for _, m := range zenModels {
		data = append(data, map[string]any{
			"id": m.id, "object": "model", "owned_by": "opencode-zen",
			"context_window": m.ctx,
		})
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"object": "list", "data": data})
}

// requireAuth wraps a handler with optional bearer auth (flag -auth).
func requireAuth(token string, h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if token != "" && r.Header.Get("Authorization") != "Bearer "+token {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		h.ServeHTTP(w, r)
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

// Observed genuine-CLI profile (captured 2026-09-20 via CONNECT proxy):
// 17 ciphers, no GREASE; 14 extensions in fixed order; ALPN http/1.1;
// groups X25519/secp256r1/secp384r1; sigalgs Chrome-order + SHA1-RSA;
// BoringSSL padding last; NO compress-cert, NO ALPS, NO ECH.
func main() {
	port := flag.String("port", "8099", "listen port")
	execBin := flag.String("opencode-bin", "opencode", "opencode binary backing chat requests")
	bindAddr := flag.String("bind", "127.0.0.1", "listen address")
	authToken := flag.String("auth", "", "optional bearer token clients must present (empty = localhost trust)")
	flag.Parse()

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/chat/completions", requireAuth(*authToken, serveExec(*execBin)))
	mux.HandleFunc("/v1/models", requireAuth(*authToken, serveModels))
	fmt.Fprintf(os.Stderr, "zencli serve on %s:%s backend=%s\n", *bindAddr, *port, *execBin)
	if err := http.ListenAndServe(*bindAddr+":"+*port, mux); err != nil {
		fmt.Fprintln(os.Stderr, "serve:", err)
		os.Exit(1)
	}
}
