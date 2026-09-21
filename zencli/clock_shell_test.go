package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestClockShellExactArgvAndScrubbedEnvironment(t *testing.T) {
	gate := testClockShell(t)
	dir := t.TempDir()
	marker := filepath.Join(dir, "executed")
	startup := filepath.Join(dir, "startup")
	os.WriteFile(startup, []byte("touch "+marker), 0600)
	os.WriteFile(filepath.Join(dir, "date"), []byte("#!/bin/sh\ntouch "+marker), 0700)
	env := []string{"PATH=" + dir, "TZ=:/synthetic/secret", "LANG=synthetic", "LC_ALL=synthetic", "BASH_ENV=" + startup, "ENV=" + startup, "KEEPER_TOKEN=synthetic-parent", "OPENCODE_API_KEY=synthetic-provider"}
	cases := [][]string{{}, {"-c"}, {"-lc", "date"}, {"-c", "date", "extra"}, {"date"}, {"-c", " date"}, {"-c", "date "}, {"-c", "date\n"}, {"-c", "/bin/date"}, {"-c", "date -u"}, {"-c", "date; date"}, {"-c", "(date) > " + marker}, {"-c", "> " + marker}, {"-c", "x=$(<" + startup + ")"}, {"-c", "PATH=" + dir + " date"}, {"-c", "date $(env)"}, {"--interactive"}}
	for _, args := range cases {
		cmd := exec.Command(gate, args...)
		cmd.Env = env
		raw, err := cmd.CombinedOutput()
		if err == nil || strings.Contains(string(raw), "synthetic-parent") || strings.Contains(string(raw), "synthetic-provider") {
			t.Fatalf("nonexact argv accepted/leaked: %q", args)
		}
	}
	cmd := exec.Command(gate, "-c", "date")
	cmd.Env = env
	cmd.Dir = dir
	raw, err := cmd.Output()
	if err != nil || !strings.Contains(string(raw), "UTC") {
		t.Fatal("exact UTC clock failed")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("startup or PATH command executed")
	}
}

func TestClockEventRequiresExactSuccessfulToolThenFinalText(t *testing.T) {
	clock := `{"type":"tool_use","part":{"tool":"bash","state":{"status":"completed","input":{"command":"date"},"metadata":{"exit":0},"output":"real clock output"}}}` + "\n"
	stop := `{"type":"step_finish","part":{"reason":"stop"}}` + "\n"
	text := `{"type":"text","part":{"text":"Actual final answer"}}` + "\n"
	for _, raw := range []string{
		clock + stop, text + clock + stop,
		strings.Replace(clock, `"exit":0`, `"exit":1`, 1) + text + stop,
		strings.Replace(clock, `"exit":0`, `"other":0`, 1) + text + stop,
		strings.Replace(clock, `"date"`, `"date -u"`, 1) + text + stop,
		strings.Replace(clock, `"bash"`, `"read"`, 1) + text + stop,
	} {
		if _, _, err := parseText([]byte(raw), "synthetic-key"); err == nil {
			t.Fatal("incomplete or unauthorized tool accepted")
		}
	}
	result, finish, err := parseText([]byte(clock+`{"type":"step_finish","part":{"reason":"tool-calls"}}`+"\n"+text+stop), "synthetic-key")
	if err != nil || result != "Actual final answer" || finish != "stop" {
		t.Fatal("actual clock continuation rejected")
	}
}

func TestClockShellCannotFallBackToRealInterpreter(t *testing.T) {
	dir := t.TempDir()
	if validateClockShell(filepath.Join(dir, "missing")) == nil {
		t.Fatal("missing gate accepted")
	}
	fake := filepath.Join(dir, "sh")
	os.WriteFile(fake, []byte("#!/bin/sh\nexec /bin/sh \"$@\""), 0755)
	if validateClockShell(fake) == nil {
		t.Fatal("foreign interpreter accepted")
	}
	os.Remove(fake)
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	os.Symlink(self, fake)
	if err := validateClockShell(fake); err != nil {
		t.Fatal("own immutable executable rejected")
	}
}
