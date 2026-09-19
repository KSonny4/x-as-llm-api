#!/usr/bin/env python3
"""Minimal SOCKS5 CONNECT forwarder (no auth), localhost-only.
Purpose: expose this machine's routing (e.g. Mullvad tunnel) to a peer
over an SSH -R forward, so a Nomad probe container can egress via it:
  ssh -D 1080 ... (replaced by this) + ssh -R 127.0.0.1:18080:127.0.0.1:1080 node
Then: ALL_PROXY=socks5h://127.0.0.1:18080 in the container (host net).
Stdlib only. Logs peer connects to stderr, never payloads/secrets.
"""
import select
import socket
import struct
import sys
import threading

LISTEN = ("127.0.0.1", 1080)


def relay(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 300)
            if not r:
                break
            data = r[0].recv(65536)
            if not data:
                break
            (b if r[0] is a else a).sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def recvn(sock, n):
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise OSError("eof")
        out += chunk
    return out


def handle(client):
    try:
        ver, nmethods = recvn(client, 2)  # VER + NMETHODS
        if ver != 5:
            return
        methods = recvn(client, nmethods)  # client may offer several
        if 0 not in methods:  # no-auth only
            client.sendall(b"\x05\xff")
            return
        client.sendall(b"\x05\x00")
        ver, cmd, _, atyp = struct.unpack("!BBBB", recvn(client, 4))
        if ver != 5 or cmd != 1:  # CONNECT only
            client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        if atyp == 1:
            host = socket.inet_ntoa(recvn(client, 4))
        elif atyp == 3:
            host = recvn(client, recvn(client, 1)[0]).decode()
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6, recvn(client, 16))
        else:
            return
        port = struct.unpack("!H", recvn(client, 2))[0]
        print("connect %s:%d" % (host, port), file=sys.stderr, flush=True)
        upstream = socket.create_connection((host, port), timeout=30)
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        relay(client, upstream)
    except OSError:
        try:
            client.close()
        except OSError:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(32)
    print("socks5 on %s:%d" % LISTEN, file=sys.stderr, flush=True)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
