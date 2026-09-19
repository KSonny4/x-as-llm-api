# keeper-egress: userspace Mullvad exit for the probe's Zen L1 leg.
#
# sing-box (wireguard outbound + http CONNECT inbound), zero privileges:
# no NET_ADMIN, no /dev/net/tun, no node changes. Only opencode.ai is
# routed into the tunnel (route rules); everything else goes direct, so
# non-Zen L1 readings stay byte-identical to today.
#
# No secrets baked: WG_PRIVATE_KEY / WG_ADDRESSES arrive as task env
# (same holder class as KEEPER_TOKEN: Nomad management token only).
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY sing-box /usr/local/bin/sing-box
COPY entry.sh /usr/local/bin/egress-entry.sh
RUN chmod +x /usr/local/bin/egress-entry.sh
ENTRYPOINT ["/usr/local/bin/egress-entry.sh"]
