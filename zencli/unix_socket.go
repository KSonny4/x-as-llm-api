package main

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

const defaultSocket = "/alloc/data/keeper-zencli/http.sock"

// The allocation's shared data directory contains only this private IPC child.
// Refuse symlinks, foreign ownership, permissive directories, active listeners
// and non-socket files; only our own ECONNREFUSED stale socket can be replaced.
func listenPrivateUnix(path string) (*net.UnixListener, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("absolute socket required")
	}
	dir := filepath.Dir(path)
	if err := os.Mkdir(dir, 0700); err != nil && !os.IsExist(err) {
		return nil, err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return nil, err
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !info.IsDir() || info.Mode().Perm()&0077 != 0 || !ok || owner.Uid != uint32(os.Geteuid()) {
		return nil, errors.New("private owned socket directory required")
	}
	if info, err := os.Lstat(path); err == nil {
		owner, ok := info.Sys().(*syscall.Stat_t)
		if info.Mode()&os.ModeSocket == 0 || !ok || owner.Uid != uint32(os.Geteuid()) {
			return nil, errors.New("unsafe socket file")
		}
		conn, err := net.DialTimeout("unix", path, 200*time.Millisecond)
		if err == nil {
			conn.Close()
			return nil, errors.New("socket already active")
		}
		if !errors.Is(err, syscall.ECONNREFUSED) {
			return nil, errors.New("socket not replaceable")
		}
		if err := os.Remove(path); err != nil {
			return nil, err
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0600); err != nil {
		listener.Close()
		return nil, err
	}
	return listener, nil
}
