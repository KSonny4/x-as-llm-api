package main

import (
	"net"
	"os"
	"path/filepath"
	"testing"
)

func TestPrivateUnixSocketLifecycle(t *testing.T) {
	dir, err := os.MkdirTemp("/tmp", "kipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "private", "http.sock")
	listener, err := listenPrivateUnix(path)
	if err != nil {
		t.Fatal(err)
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 {
		t.Fatal("socket permissions")
	}
	info, _ = os.Stat(filepath.Dir(path))
	if info.Mode().Perm() != 0700 {
		t.Fatal("directory permissions")
	}
	if other, err := listenPrivateUnix(path); err == nil {
		other.Close()
		t.Fatal("replaced live socket")
	}
	listener.Close()
	// Simulate a process killed before unlinking its Unix socket.
	stale, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	stale.SetUnlinkOnClose(false)
	stale.Close()
	listener, err = listenPrivateUnix(path)
	if err != nil {
		t.Fatal("stale socket not recovered")
	}
	listener.Close()
	if err := os.WriteFile(path, []byte("preserve"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := listenPrivateUnix(path); err == nil {
		t.Fatal("non-socket overwritten")
	}
	os.Remove(path)
	target := filepath.Join(dir, "target")
	os.WriteFile(target, []byte("preserve"), 0600)
	os.Symlink(target, path)
	if _, err := listenPrivateUnix(path); err == nil {
		t.Fatal("symlink followed")
	}
	os.Remove(path)
	os.Chmod(filepath.Dir(path), 0755)
	if _, err := listenPrivateUnix(path); err == nil {
		t.Fatal("permissive directory accepted")
	}
}
