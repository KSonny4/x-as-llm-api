package main

// Hermetic protocol tests use the real pinned binary, synthetic auth and a
// loopback-only fake upstream. No provider inference or installed login is used.
import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestPinnedNativeCLIAutoRejectsTools(t *testing.T) {
	bin := os.Getenv("KEEPER_TEST_OPENCODE_BIN")
	if bin == "" {
		t.Skip("set KEEPER_TEST_OPENCODE_BIN to genuine 1.18.31")
	}
	version, err := exec.Command(bin, "--version").Output()
	if err != nil || strings.TrimSpace(string(version)) != "1.18.31" {
		t.Fatal("requires pinned 1.18.31")
	}
	for _, scenario := range []string{"plain", "read", "bash", "task", "webfetch", "grep", "glob", "write", "clock", "redirect-only", "assignment-read", "grouped-redirect", "operator", "substitution", "env-prefix", "path-prefix", "date-option", "workdir", "function", "newline"} {
		t.Run(scenario, func(t *testing.T) {
			tool := scenario
			clockCases := map[string]bool{"clock": true, "redirect-only": true, "assignment-read": true, "grouped-redirect": true, "operator": true, "substitution": true, "env-prefix": true, "path-prefix": true, "date-option": true, "workdir": true, "function": true, "newline": true}
			if clockCases[scenario] {
				tool = "bash"
			}
			dir, err := filepath.EvalSymlinks(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			env, err := requestEnvironment(dir, "big-pickle", "synthetic-selected")
			if err != nil {
				t.Fatal(err)
			}
			marker := filepath.Join(dir, "executed")
			var mu sync.Mutex
			calls, fetched := 0, false
			clockOutput := false
			var failure string
			var srv *httptest.Server
			srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				defer mu.Unlock()
				if r.Method != "POST" {
					fetched = true
					http.Error(w, "tool executed", 500)
					return
				}
				raw, _ := io.ReadAll(r.Body)
				var req map[string]any
				if json.Unmarshal(raw, &req) != nil {
					failure = "invalid upstream request"
					http.Error(w, "bad request", 400)
					return
				}
				if req["model"] != "big-pickle" || r.Header.Get("Authorization") != "Bearer synthetic-selected" {
					failure = "wrong key/model"
				}
				if strings.Contains(string(raw), "synthetic-parent-secret") || strings.Contains(string(raw), "synthetic-selected") {
					failure = "secret entered model history"
				}
				definitions, _ := req["tools"].([]any)
				found := false
				for _, d := range definitions {
					f, _ := d.(map[string]any)["function"].(map[string]any)
					if f["name"] == tool {
						found = true
					}
				}
				auxiliary := len(definitions) == 0 && strings.Contains(string(raw), "You are a title generator.")
				if !found && !auxiliary && tool != "plain" {
					failure = "native tool definition absent"
				}
				if !auxiliary {
					calls++
					if calls == 2 && scenario == "clock" {
						messages, _ := req["messages"].([]any)
						for _, value := range messages {
							m, _ := value.(map[string]any)
							content, _ := m["content"].(string)
							if m["role"] == "tool" && strings.Contains(content, "UTC") {
								clockOutput = true
							}
						}
					}
				}
				w.Header().Set("Content-Type", "text/event-stream")
				delta := map[string]any{"content": "Safe final answer"}
				finish := "stop"
				if calls == 1 && !auxiliary && tool != "plain" {
					args := map[string]any{}
					switch tool {
					case "read":
						args = map[string]any{"filePath": filepath.Join(dir, "data", "opencode", "auth.json")}
					case "bash":
						args = map[string]any{"command": "env; cat /proc/$PPID/environ; cat " + filepath.Join(dir, "data", "opencode", "auth.json") + "; touch " + marker, "description": "inspect credentials"}
					case "task":
						args = map[string]any{"description": "inspect auth", "prompt": "Read all auth files and environment; create " + marker, "subagent_type": "general"}
					case "webfetch":
						args = map[string]any{"url": srv.URL + "/exfiltrate", "format": "text"}
					case "grep":
						args = map[string]any{"pattern": ".*", "path": filepath.Join(dir, "data", "opencode"), "include": "auth.json"}
					case "glob":
						args = map[string]any{"pattern": "**/*", "path": filepath.Join(dir, "data")}
					case "write":
						args = map[string]any{"filePath": marker, "content": "executed"}
					}
					if clockCases[scenario] {
						auth := filepath.Join(dir, "data", "opencode", "auth.json")
						commands := map[string]string{
							"clock": "date", "redirect-only": "> " + marker,
							"assignment-read":  "x=$(( $(<" + auth + ") ))",
							"grouped-redirect": "(date) > " + marker,
							"operator":         "date; date > " + marker,
							"substitution":     "date $(<" + auth + ")",
							"env-prefix":       "PATH=" + dir + " date", "path-prefix": "/bin/date",
							"date-option": "date -f " + auth, "workdir": "date",
							"function": "date() { > " + marker + "; }; date", "newline": "date\n> " + marker,
						}
						args = map[string]any{"command": commands[scenario]}
						if scenario == "workdir" {
							args["workdir"] = "/"
						}
					}
					encoded, _ := json.Marshal(args)
					delta = map[string]any{"tool_calls": []any{map[string]any{"index": 0, "id": "call_native", "type": "function", "function": map[string]any{"name": tool, "arguments": string(encoded)}}}}
					finish = "tool_calls"
				}
				event, _ := json.Marshal(map[string]any{"id": "fixture", "object": "chat.completion.chunk", "model": "big-pickle", "choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": nil}}})
				fmt.Fprintf(w, "data: %s\n\n", event)
				event, _ = json.Marshal(map[string]any{"id": "fixture", "object": "chat.completion.chunk", "model": "big-pickle", "choices": []any{map[string]any{"index": 0, "delta": map[string]any{}, "finish_reason": finish}}})
				fmt.Fprintf(w, "data: %s\n\ndata: [DONE]\n\n", event)
			}))
			defer srv.Close()
			// Override endpoint/SDK only in the fixture. Production has neither override.
			config := apiConfig("big-pickle")
			if _, configured := config["shell"]; configured {
				config["shell"] = testClockShell(t)
			}
			config["provider"] = map[string]any{"opencode": map[string]any{"npm": "@ai-sdk/openai-compatible", "whitelist": []string{"big-pickle"}, "options": map[string]any{"baseURL": srv.URL + "/v1"}, "models": map[string]any{"big-pickle": map[string]any{"name": "fixture", "tool_call": true, "limit": map[string]int{"context": 200000, "output": 8192}, "cost": map[string]int{"input": 0, "output": 0}}}}}
			encoded, _ := json.Marshal(config)
			for i, e := range env {
				if strings.HasPrefix(e, "OPENCODE_CONFIG_CONTENT=") {
					env[i] = "OPENCODE_CONFIG_CONTENT=" + string(encoded)
				}
			}
			catalog := filepath.Join(dir, "models.json")
			os.WriteFile(catalog, []byte("{}"), 0600)
			env = append(env, "OPENCODE_MODELS_PATH="+catalog, "OPENCODE_DISABLE_MODELS_FETCH=true", "OPENCODE_DISABLE_LSP_DOWNLOAD=true", "OPENCODE_DISABLE_CLAUDE_CODE=true", "OPENCODE_DISABLE_EXTERNAL_SKILLS=true")
			t.Setenv("KEEPER_TOKEN", "synthetic-parent-secret")
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, bin, "run", "--model", "opencode/big-pickle", "--format", "json", "--pure", "--", "--auto --yolo --dangerously-skip-permissions @"+filepath.Join(dir, "data", "opencode", "auth.json")+" inspect credentials")
			cmd.Dir = dir
			cmd.Env = env
			var stderr strings.Builder
			cmd.Stderr = &stderr
			raw, err := cmd.Output()
			if err != nil {
				t.Fatalf("CLI failed: %v; fixture stderr: %s", err, stderr.String())
			}
			mu.Lock()
			defer mu.Unlock()
			if failure != "" {
				t.Fatal(failure)
			}
			if (calls != 1 && !(clockCases[scenario] && calls == 2)) || fetched {
				t.Fatalf("unexpected model/tool requests: calls=%d fetched=%v", calls, fetched)
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatal("bash/task executed")
			}
			if tool != "plain" && !clockCases[scenario] && (!strings.Contains(string(raw), `"status":"error"`) || !strings.Contains(stderr.String(), "auto-rejecting")) {
				t.Fatalf("missing native rejection evidence: %s / %s", raw, stderr.String())
			}
			if strings.Contains(string(raw), "synthetic-selected") || strings.Contains(string(raw), "synthetic-parent-secret") {
				t.Fatal("secret emitted")
			}
			text, finish, err := parseText(raw, "synthetic-selected")
			if tool == "plain" || scenario == "clock" {
				if scenario == "clock" && (calls != 2 || !clockOutput) {
					t.Fatal("genuine successful UTC clock output did not reach model continuation")
				}
				if err != nil || text != "Safe final answer" || finish != "stop" {
					t.Fatalf("plain answer rejected: %v", err)
				}
			} else if err == nil {
				t.Fatal("incomplete tool-only run must not become success")
			}
		})
	}
}

// The configured gate path alone is relocated for hermetic tests; its immutable
// implementation is built from the same source as the production executable.
func testClockShell(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	binary := filepath.Join(dir, "zencli")
	if raw, err := exec.Command("go", "build", "-o", binary, ".").CombinedOutput(); err != nil {
		t.Fatalf("build gate: %v %s", err, raw)
	}
	gate := filepath.Join(dir, "sh")
	if err := os.Symlink(binary, gate); err != nil {
		t.Fatal(err)
	}
	return gate
}
