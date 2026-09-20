#!/usr/bin/env python3
"""mitm-log.py — metadata-only HTTPS observation proxy (localhost-only).

Sits between a TLS client (e.g. opencode CLI) and the internet via HTTP
CONNECT and logs ONLY: timestamp, target host:port, TLS ClientHello
fields (SNI, ALPN, version, cipher list hash), byte counts, duration.
NEVER logs header values, bodies, or payloads (Authorization and keys
stay out of every log by construction — they are inside TLS).

Usage:
  python3 scripts/mitm-log.py [port]          # default 1082
  HTTPS_PROXY=http://127.0.0.1:1082 opencode run ...
Compare two legs (laptop vs Nomad docker) by diffing the log lines.

Stdlib only. Binds 127.0.0.1.
"""
import hashlib
import select
import socket
import struct
import sys
import threading
import time


def parse_hello(data):
    """Minimal TLS ClientHello parser -> dict. Returns {} if not TLS."""
    out = {}
    try:
        if len(data) < 5 or data[0] != 0x16:
            return out
        reclen = struct.unpack("!H", data[3:5])[0]
        body = data[5:5 + reclen]
        if len(body) < 4 or body[0] != 1:
            return out
        hlen = struct.unpack("!I", b"\x00" + body[1:4])[0]
        hello = body[4:4 + hlen]
        out["legacy_version"] = "%02x%02x" % (hello[0], hello[1])
        p = 2 + 32
        if len(hello) < p + 1:
            return out
        n = hello[p]  # session_id
        p += 1 + n
        if len(hello) < p + 2:
            return out
        n = struct.unpack("!H", hello[p:p + 2])[0]
        ciphers = struct.unpack("!%dH" % (n // 2), hello[p + 2:p + 2 + n])
        out["ciphers"] = len(ciphers)
        out["cipher_hash"] = hashlib.md5(
            ",".join("%04x" % c for c in ciphers).encode()).hexdigest()[:12]
        p += 2 + n
        if len(hello) < p + 1:
            return out
        n = hello[p]
        p += 1 + n
        if len(hello) < p + 2:
            return out
        n = struct.unpack("!H", hello[p:p + 2])[0]
        p += 2
        exts = hello[p:p + n]
        names = []
        q = 0
        while q + 4 <= len(exts):
            et, el = struct.unpack("!HH", exts[q:q + 4])
            ed = exts[q + 4:q + 4 + el]
            if et == 0 and el > 5:  # server_name: list(2)+type(1)+len(2)+name
                sl = struct.unpack("!H", ed[3:5])[0]
                out["sni"] = ed[5:5 + sl].decode("ascii", "replace")
            elif et == 16 and el > 2:  # alpn
                al = struct.unpack("!H", ed[:2])[0]
                out["alpn"] = ed[2:2 + al].decode("ascii", "replace")
            else:
                names.append("%d" % et)
            q += 4 + el
        out["extensions"] = len(names) + ("sni" in out) + ("alpn" in out)
    except (IndexError, struct.error, UnicodeDecodeError):
        pass
    return out


def relay(a, b, counts):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 300)
            if not r:
                break
            data = r[0].recv(65536)
            if not data:
                break
            (b if r[0] is a else a).sendall(data)
            counts[0 if r[0] is a else 1] += len(data)
    except OSError:
        pass


def handle(client, addr):
    t0 = time.time()
    counts = [0, 0]
    target = "?"
    try:
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 8192:
                return
        parts = head.split(b"\r\n", 1)[0].decode("latin1").split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        target = parts[1]
        host, port = (target.rsplit(":", 1) + ["443"])[:2]
        upstream = socket.create_connection((host, int(port)), timeout=30)
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        client.settimeout(10)
        try:
            hello = b""
            while len(hello) < 5:
                chunk = client.recv(5 - len(hello))
                if not chunk:
                    break
                hello += chunk
            if len(hello) == 5 and hello[0] == 0x16:
                need = 5 + struct.unpack("!H", hello[3:5])[0]
                while len(hello) < need:
                    chunk = client.recv(need - len(hello))
                    if not chunk:
                        break
                    hello += chunk
        except socket.timeout:
            hello = b""
        info = parse_hello(hello) if hello else {}
        if hello:
            upstream.sendall(hello)
        print("con target=%s ciphers=%s cipher_hash=%s sni=%s alpn=%s tls=%s"
              % (target, info.get("ciphers", "?"),
                 info.get("cipher_hash", "?"), info.get("sni", "?"),
                 info.get("alpn", "?"), info.get("legacy_version", "?")),
              flush=True)
        relay(client, upstream, counts)
    except OSError:
        pass
    finally:
        try:
            client.close()
        except OSError:
            pass
        print("end target=%s up=%d down=%d secs=%.1f"
              % (target, counts[0], counts[1], time.time() - t0), flush=True)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1082
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(32)
    print("mitm-log on 127.0.0.1:%d" % port, flush=True)
    while True:
        client, addr = srv.accept()
        threading.Thread(target=handle, args=(client, addr),
                         daemon=True).start()


if __name__ == "__main__":
    main()
