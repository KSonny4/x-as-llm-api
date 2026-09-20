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
	// Even loopback requires an internal bearer.
	open := requireAuth("", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	})
	w = httptest.NewRecorder()
	open(w, httptest.NewRequest(http.MethodGet, "/", nil))
	if w.Code != 401 {
		t.Fatalf("want 401 closed, got %d", w.Code)
	}
}
