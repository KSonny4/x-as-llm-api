package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Bridge only executes an immutable genuine CLI binary. The authenticated Keeper
// supplies exact-key requests and a fresh authoritative free model catalog.
// No default login, static model list, exported provider keys, or tool execution.
type Bridge struct {
	bin     string
	mu      sync.RWMutex
	models  map[string]time.Time
	timeout time.Duration
}

func newBridge(bin string) *Bridge {
	return &Bridge{bin: bin, models: map[string]time.Time{}, timeout: 110 * time.Second}
}

var modelID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$`)

func decodeBody(r *http.Request, target any) error {
	raw, err := io.ReadAll(io.LimitReader(r.Body, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 {
		return errors.New("invalid body")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if decoder.Decode(new(any)) != io.EOF {
		return errors.New("trailing data")
	}
	return nil
}
func (b *Bridge) catalog(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	var body struct {
		Models []struct {
			Model      string  `json:"model"`
			VerifiedAt float64 `json:"verified_at"`
		} `json:"models"`
	}
	if decodeBody(r, &body) != nil {
		http.Error(w, "invalid catalog", 400)
		return
	}
	models := map[string]time.Time{}
	now := time.Now()
	for _, m := range body.Models {
		stamp := time.UnixMilli(int64(m.VerifiedAt * 1000))
		if !modelID.MatchString(m.Model) || stamp.After(now) || !stamp.Add(24*time.Hour).After(now) {
			http.Error(w, "invalid catalog", 400)
			return
		}
		models[m.Model] = stamp.Add(24 * time.Hour)
	}
	b.mu.Lock()
	b.models = models
	b.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	io.WriteString(w, `{"ok":true}`)
}
func (b *Bridge) list(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", 405)
		return
	}
	data := []any{}
	b.mu.RLock()
	for model, expiry := range b.models {
		if expiry.After(time.Now()) {
			data = append(data, map[string]any{"id": model, "object": "model", "owned_by": "opencode-zen", "transport": "zencli", "stream": false, "tools": false})
		}
	}
	b.mu.RUnlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"object": "list", "data": data})
}

// apiConfig is validated against OpenCode v1.18.31 effective debug-agent output.
// Agent permission overrides defaults; tools are absent from the model request.
// Whitelisting + explicit small_model prevents paid auxiliary model selection.
func apiConfig(model string) map[string]any {
	return map[string]any{
		"permission": map[string]string{"*": "deny"}, "default_agent": "keeper-api",
		"agent":             map[string]any{"keeper-api": map[string]any{"mode": "primary", "description": "Text-only Keeper API", "permission": map[string]string{"*": "deny"}, "tools": map[string]bool{"*": false}, "steps": 1}},
		"enabled_providers": []string{"opencode"}, "provider": map[string]any{"opencode": map[string]any{"whitelist": []string{model}}},
		"model": "opencode/" + model, "small_model": "opencode/" + model,
		"autoupdate": false, "share": "disabled", "snapshot": false, "plugin": []string{}, "mcp": map[string]any{},
		"compaction": map[string]bool{"auto": false, "prune": false},
	}
}
func requestEnvironment(dir, model, key string) ([]string, error) {
	data := filepath.Join(dir, "data", "opencode")
	if err := os.MkdirAll(data, 0700); err != nil {
		return nil, err
	}
	auth, _ := json.Marshal(map[string]any{"opencode": map[string]string{"type": "api", "key": key}})
	if err := os.WriteFile(filepath.Join(data, "auth.json"), auth, 0600); err != nil {
		return nil, err
	}
	config, _ := json.Marshal(apiConfig(model))
	// Deliberately do not inherit os.Environ, PATH, proxy configuration, plugins,
	// API keys, internal/admin/service bearers, shell startup or default login.
	return []string{"HOME=" + dir, "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
		"XDG_DATA_HOME=" + filepath.Join(dir, "data"), "XDG_CONFIG_HOME=" + filepath.Join(dir, "config"),
		"XDG_CACHE_HOME=" + filepath.Join(dir, "cache"), "XDG_STATE_HOME=" + filepath.Join(dir, "state"),
		"TMPDIR=" + dir, "OPENCODE_CONFIG_CONTENT=" + string(config), "OPENCODE_DISABLE_PROJECT_CONFIG=true"}, nil
}

type boundedOutput struct{ bytes.Buffer }

func (w *boundedOutput) Write(p []byte) (int, error) {
	if w.Len()+len(p) > 1<<20 {
		return 0, errors.New("output too large")
	}
	return w.Buffer.Write(p)
}
func parseText(raw []byte, key string) (string, string, error) {
	scanner := bufio.NewScanner(bytes.NewReader(raw))
	scanner.Buffer(make([]byte, 4096), 1<<20)
	var text strings.Builder
	finish := ""
	for scanner.Scan() {
		var event struct {
			Type string `json:"type"`
			Part struct {
				Text   string `json:"text"`
				Reason string `json:"reason"`
			} `json:"part"`
		}
		if json.Unmarshal(scanner.Bytes(), &event) != nil {
			return "", "", errors.New("invalid event")
		}
		switch event.Type {
		case "error", "tool_use":
			return "", "", errors.New("unsafe or failed generation")
		case "text":
			text.WriteString(event.Part.Text)
		case "step_finish":
			if event.Part.Reason != "stop" && event.Part.Reason != "length" {
				return "", "", errors.New("incomplete generation")
			}
			finish = event.Part.Reason
		case "step_start", "reasoning": // only generated text is returned
		default:
			return "", "", errors.New("unknown event")
		}
	}
	result := strings.TrimSpace(text.String())
	if scanner.Err() != nil || result == "" || finish == "" || strings.Contains(result, key) {
		return "", "", errors.New("no usable output")
	}
	return result, finish, nil
}
func (b *Bridge) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	var req ChatReq
	if decodeBody(r, &req) != nil || req.Stream || !modelID.MatchString(req.Model) {
		http.Error(w, "unsupported request", 400)
		return
	}
	b.mu.RLock()
	expiry, known := b.models[req.Model]
	b.mu.RUnlock()
	key := r.Header.Get("X-Keeper-Provider-Key")
	if !known || !expiry.After(time.Now()) || key == "" || strings.ContainsAny(key, "\r\n") {
		http.Error(w, "exact free model and key required", 400)
		return
	}
	for _, msg := range req.Messages {
		if msg.Role != "system" && msg.Role != "user" && msg.Role != "assistant" {
			http.Error(w, "unsupported messages", 400)
			return
		}
		if _, ok := msg.Content.(string); !ok {
			http.Error(w, "text messages required", 400)
			return
		}
	}
	prompt := buildPrompt(req.Messages)
	if prompt == "" {
		http.Error(w, "no prompt content", 400)
		return
	}
	dir, err := os.MkdirTemp("", "zencli-request-")
	if err != nil {
		http.Error(w, "request setup failed", 500)
		return
	}
	defer os.RemoveAll(dir)
	env, err := requestEnvironment(dir, req.Model, key)
	if err != nil {
		http.Error(w, "request setup failed", 500)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), b.timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, b.bin, "run", "--model", "opencode/"+req.Model, "--agent", "keeper-api", "--format", "json", "--pure", "--", prompt)
	cmd.Dir = dir
	cmd.Env = env
	cmd.Stderr = io.Discard
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = time.Second
	var out boundedOutput
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		http.Error(w, "CLI generation failed", 502)
		return
	}
	text, finish, err := parseText(out.Bytes(), key)
	if err != nil {
		http.Error(w, "CLI generation failed", 502)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"id": "chatcmpl-" + rid("", 12), "object": "chat.completion", "created": time.Now().Unix(), "model": req.Model,
		"choices": []any{map[string]any{"index": 0, "message": map[string]string{"role": "assistant", "content": text}, "finish_reason": finish}}, "usage": map[string]int{}, "keeper_transport": "zencli"})
}
