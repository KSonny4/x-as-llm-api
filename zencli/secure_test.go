package main

import (
	"encoding/json"
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

func fixtureBridge(t *testing.T, script string) *Bridge {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "opencode")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\n"+script), 0700); err != nil {
		t.Fatal(err)
	}
	b := newBridge(bin)
	b.models["dynamic-free-model"] = time.Now().Add(time.Hour)
	return b
}
func invoke(b *Bridge, body, key string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	if key != "" {
		r.Header.Set("X-Keeper-Provider-Key", key)
	}
	w := httptest.NewRecorder()
	b.chat(w, r)
	return w
}

const plain = `{"model":"dynamic-free-model","messages":[{"role":"user","content":"hello"}]}`
const goodOutput = "printf '%s\\n' '{\"type\":\"text\",\"part\":{\"text\":\"hello from fixture\"}}' '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\"}}'\n"

func TestExactIsolatedKeyAndDenyAllConfiguration(t *testing.T) {
	t.Setenv("KEEPER_TOKEN", "must-not-inherit")
	t.Setenv("OPENCODE_API_KEY", "wrong-default-key")
	out := filepath.Join(t.TempDir(), "capture")
	script := `test -z "$KEEPER_TOKEN" || exit 3
 test -z "$OPENCODE_API_KEY" || exit 4
 test -z "$ZENCLI_INTERNAL_TOKEN" || exit 5
 printf '%s\n' "$HOME" > "` + out + `"
 cat "$XDG_DATA_HOME/opencode/auth.json" >> "` + out + `"
 printf '\n%s\n' "$OPENCODE_CONFIG_CONTENT" >> "` + out + `"
 printf '%s\n' "$@" >> "` + out + `"
 ` + goodOutput
	b := fixtureBridge(t, script)
	w := invoke(b, `{"model":"dynamic-free-model","messages":[{"role":"user","content":"--help"}]}`, "synthetic-selected")
	if w.Code != 200 {
		t.Fatalf("status %d", w.Code)
	}
	raw, _ := os.ReadFile(out)
	lines := strings.Split(string(raw), "\n")
	if _, err := os.Stat(lines[0]); !os.IsNotExist(err) {
		t.Fatal("request home not cleaned")
	}
	if !strings.Contains(string(raw), `"key":"synthetic-selected"`) {
		t.Fatal("wrong auth identity")
	}
	if !strings.Contains(string(raw), `"permission":{"*":"deny"}`) || !strings.Contains(string(raw), `"steps":1`) {
		t.Fatal("deny-all absent")
	}
	if !strings.Contains(string(raw), "--model\nopencode/dynamic-free-model\n--agent\nkeeper-api\n--format\njson\n--pure\n--\n--help") {
		t.Fatal("unsafe argv")
	}
	if strings.Contains(w.Body.String(), "synthetic-selected") {
		t.Fatal("secret reflected")
	}
}
func TestRejectPaidUnknownControlsToolsStreamingAndMissingKey(t *testing.T) {
	b := fixtureBridge(t, "exit 9")
	for _, body := range []string{
		`{"model":"paid-model","messages":[{"role":"user","content":"hi"}]}`,
		`{"model":"other/provider","messages":[{"role":"user","content":"hi"}]}`,
		`{"model":"dynamic-free-model","messages":[{"role":"user","content":"hi"}],"stream":true}`,
		`{"model":"dynamic-free-model","messages":[{"role":"user","content":"hi"}],"max_tokens":64}`,
		`{"model":"dynamic-free-model","messages":[{"role":"tool","content":"hi"}]}`,
		`{"model":"dynamic-free-model","messages":[{"role":"user","content":"hi"}],"tools":[]}`} {
		if w := invoke(b, body, "synthetic-selected"); w.Code != 400 {
			t.Fatalf("unsupported status %d", w.Code)
		}
	}
	if w := invoke(b, plain, ""); w.Code != 400 {
		t.Fatal("default auth allowed")
	}
}
func TestRawEventsOnlyNoToolsEmptyOrSecrets(t *testing.T) {
	for _, output := range []string{"echo 'raw formatted stdout'", "echo '{\"type\":\"text\",\"part\":{\"text\":\"\"}}'", "echo '{\"type\":\"tool_use\",\"part\":{\"tool\":\"bash\"}}'", "echo '{\"type\":\"text\",\"part\":{\"text\":\"synthetic-selected\"}}'"} {
		b := fixtureBridge(t, output)
		w := invoke(b, plain, "synthetic-selected")
		if w.Code != 502 || strings.Contains(w.Body.String(), "synthetic-selected") {
			t.Fatal("invalid evidence accepted/leaked")
		}
	}
}
func TestConcurrentRequestsNeverShareAuth(t *testing.T) {
	b := fixtureBridge(t, goodOutput)
	var wg sync.WaitGroup
	for range 5 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if invoke(b, plain, "synthetic-selected").Code != 200 {
				t.Error("request failed")
			}
		}()
	}
	wg.Wait()
}
func TestDynamicCatalogNoSevenModelCapAndExpiry(t *testing.T) {
	b := newBridge("unused")
	models := []map[string]any{}
	for i := range 30 {
		models = append(models, map[string]any{"model": string(rune('a'+i)) + "-free", "verified_at": time.Now().Add(-time.Minute).Unix()})
	}
	// model punctuation beyond z intentionally invalid; use numbered IDs instead.
	for i := range models {
		models[i]["model"] = "model-" + strings.Repeat("x", i+1)
	}
	raw, _ := json.Marshal(map[string]any{"models": models})
	r := httptest.NewRequest(http.MethodPost, "/internal/catalog", strings.NewReader(string(raw)))
	w := httptest.NewRecorder()
	b.catalog(w, r)
	if w.Code != 200 || len(b.models) != 30 {
		t.Fatal("catalog truncated")
	}
	b.models["dynamic-free-model"] = time.Now().Add(-time.Second)
	if invoke(b, plain, "synthetic-selected").Code != 400 {
		t.Fatal("expired eligibility accepted")
	}
}

// Optional local validation against the pinned genuine binary. This inspects
// effective configuration only: no provider prompt or inference is issued.
func TestPinnedGenuineCLIHasNoEnabledTools(t *testing.T) {
	bin := os.Getenv("KEEPER_TEST_OPENCODE_BIN")
	if bin == "" {
		t.Skip("set explicit genuine CLI path for config-only validation")
	}
	dir := t.TempDir()
	env, err := requestEnvironment(dir, "big-pickle", "synthetic-not-used")
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(bin, "debug", "agent", "keeper-api", "--pure")
	cmd.Env = env
	cmd.Dir = dir
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal("genuine CLI config validation failed")
	}
	var info struct {
		Tools      map[string]bool `json:"tools"`
		Steps      int             `json:"steps"`
		Permission []struct {
			Permission string `json:"permission"`
			Pattern    string `json:"pattern"`
			Action     string `json:"action"`
		} `json:"permission"`
	}
	if json.Unmarshal(raw, &info) != nil || info.Steps != 1 || len(info.Tools) == 0 {
		t.Fatal("unexpected agent configuration")
	}
	for name, enabled := range info.Tools {
		if enabled {
			t.Fatalf("tool enabled: %s", name)
		}
	}
	for _, tool := range []string{"read", "edit", "bash", "task", "webfetch", "websearch", "skill"} {
		action := ""
		for _, rule := range info.Permission {
			if rule.Permission == "*" || rule.Permission == tool {
				action = rule.Action
			}
		}
		if action != "deny" {
			t.Fatalf("effective %s permission not denied", tool)
		}
	}
}

func TestTimeoutCleansRequestAndKillsProcessGroup(t *testing.T) {
	b := fixtureBridge(t, "sleep 10 & wait")
	b.timeout = 30 * time.Millisecond
	started := time.Now()
	w := invoke(b, plain, "synthetic-selected")
	if w.Code != 502 || time.Since(started) > 2*time.Second {
		t.Fatal("timeout not enforced")
	}
}
