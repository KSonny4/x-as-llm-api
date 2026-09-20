package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestBuildPromptSingleUser(t *testing.T) {
	got := buildPrompt([]Msg{{Role: "user", Content: "hi"}})
	if got != "hi" {
		t.Fatalf("got %q", got)
	}
}

func TestBuildPromptMultiTurn(t *testing.T) {
	got := buildPrompt([]Msg{
		{Role: "system", Content: "Be terse."},
		{Role: "user", Content: "q1"},
		{Role: "assistant", Content: "a1"},
		{Role: "user", Content: "q2"},
	})
	for _, want := range []string{"Be terse.", "User: q1", "Assistant: a1", "q2"} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %q", want, got)
		}
	}
}

func TestBuildPromptPartsArray(t *testing.T) {
	got := buildPrompt([]Msg{{Role: "user", Content: []any{
		map[string]any{"type": "text", "text": "hello"},
	}}})
	if got != "hello" {
		t.Fatalf("got %q", got)
	}
}

func TestWriteSSEFormat(t *testing.T) {
	w := httptest.NewRecorder()
	writeSSE(w, "chatcmpl-1", "big-pickle", "hi there", nil)
	body := w.Body.String()
	if w.Header().Get("Content-Type") != "text/event-stream" {
		t.Fatal("wrong content type")
	}
	if !strings.Contains(body, `"content":"hi "`) {
		t.Fatalf("missing word chunk: %q", body[:200])
	}
	if !strings.Contains(body, `"finish_reason":"stop"`) {
		t.Fatal("missing stop chunk")
	}
	if !strings.HasSuffix(strings.TrimSpace(body), "data: [DONE]") {
		t.Fatal("missing DONE terminator")
	}
}

func TestServeModels(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	w := httptest.NewRecorder()
	serveModels(w, req)
	if w.Code != 200 {
		t.Fatalf("code %d", w.Code)
	}
	for _, want := range []string{`"big-pickle"`, `"object":"list"`} {
		if !strings.Contains(w.Body.String(), want) {
			t.Fatalf("missing %s", want)
		}
	}
}

func TestRequireAuth(t *testing.T) {
	ok := requireAuth("s3cret", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	})
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ok(w, req)
	if w.Code != 401 {
		t.Fatalf("want 401, got %d", w.Code)
	}
	req.Header.Set("Authorization", "Bearer s3cret")
	w = httptest.NewRecorder()
	ok(w, req)
	if w.Code != 200 {
		t.Fatalf("want 200, got %d", w.Code)
	}
	// empty token = open (localhost trust)
	open := requireAuth("", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	})
	w = httptest.NewRecorder()
	open(w, httptest.NewRequest(http.MethodGet, "/", nil))
	if w.Code != 200 {
		t.Fatalf("want 200 open, got %d", w.Code)
	}
}
