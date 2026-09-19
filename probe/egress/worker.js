// keeper-zen-egress worker (M3 fallback): dumb forwarder so the probe's
// Zen L1 exits via Cloudflare instead of OVH. No secrets stored here:
// the probe's Authorization header passes through per request (Cloudflare
// therefore sees the key in transit — accepted fallback trade-off, see
// docs/zen-egress.md). Path allowlist: /zen/* only.
export default {
  async fetch(req) {
    const url = new URL(req.url);
    if (!url.pathname.startsWith('/zen/')) {
      return new Response('not found', { status: 404 });
    }
    const target = 'https://opencode.ai' + url.pathname + url.search;
    const headers = new Headers(req.headers);
    headers.delete('host');
    headers.delete('cf-connecting-ip');
    return fetch(target, { method: req.method, headers, body: req.body });
  },
};
