#!/bin/sh
# egress-entry.sh: render sing-box config from env, run the proxy.
# Required env: WG_PRIVATE_KEY, WG_ADDRESSES (Mullvad tunnel address,
# e.g. 10.x.x.x/32), WG_PEER_PUBLIC_KEY, WG_PEER_ENDPOINT (host:port).
# sing-box >=1.11 schema: wireguard lives in `endpoints`, referenced
# DIRECTLY from route rules (no outbound wrapper exists for it).
set -eu
: "${WG_PRIVATE_KEY:?WG_PRIVATE_KEY required}"
: "${WG_ADDRESSES:?WG_ADDRESSES required}"
: "${WG_PEER_PUBLIC_KEY:?WG_PEER_PUBLIC_KEY required}"
: "${WG_PEER_ENDPOINT:?WG_PEER_ENDPOINT required}"
PEER_HOST="${WG_PEER_ENDPOINT%%:*}"
PEER_PORT="${WG_PEER_ENDPOINT##*:}"
mkdir -p /etc/sing-box
cat > /etc/sing-box/config.json <<EOF
{
  "log": {"level": "info"},
  "inbounds": [
    {"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": 8888}
  ],
  "endpoints": [
    {
      "type": "wireguard", "tag": "mullvad-ep",
      "address": ["${WG_ADDRESSES}"],
      "private_key": "${WG_PRIVATE_KEY}",
      "peers": [
        {"address": "${PEER_HOST}", "port": ${PEER_PORT},
         "public_key": "${WG_PEER_PUBLIC_KEY}",
         "allowed_ips": ["0.0.0.0/0"]}
      ],
      "mtu": 1420
    }
  ],
  "outbounds": [
    {"type": "direct", "tag": "direct"}
  ],
  "route": {
    "rules": [{"domain_suffix": ["opencode.ai"], "outbound": "mullvad-ep"}],
    "final": "direct"
  }
}
EOF
exec /usr/local/bin/sing-box run -c /etc/sing-box/config.json
