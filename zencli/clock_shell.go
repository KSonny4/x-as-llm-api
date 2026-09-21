package main

import (
	"fmt"
	"os"
	"syscall"
)

// Overridden only at test build/link time to relocate the immutable executable.
var clockShellPath = "/usr/local/libexec/keeper-clock/sh"

func validateClockShell(path string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	binary, err := os.Stat(self)
	if err != nil {
		return err
	}
	gate, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !gate.Mode().IsRegular() || gate.Mode().Perm()&0022 != 0 || gate.Mode().Perm()&0111 == 0 || !os.SameFile(binary, gate) {
		return fmt.Errorf("immutable clock shell must be this executable")
	}
	return nil
}

// OpenCode's native permission scanner checks AST commands, not the complete
// shell input (redirect-only statements can skip approval). Never hand its raw
// input to a real shell. This immutable gate executes only the proven clock
// command, with no PATH lookup, expansion, redirection, options or inherited env.
func clockShell(args []string) int {
	if len(args) != 2 || args[0] != "-c" || args[1] != "date" {
		fmt.Fprintln(os.Stderr, "clock command denied")
		return 126
	}
	if err := os.Chdir("/"); err != nil {
		return 126
	}
	if err := syscall.Exec("/bin/date", []string{"date"}, []string{"PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C", "TZ=UTC"}); err != nil {
		fmt.Fprintln(os.Stderr, "clock execution failed")
		return 126
	}
	return 0
}
