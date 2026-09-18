# Keeper matrix UI access

Public base: `https://keeper.pkubelka.cz` (Nomad `keeper` job, Cloudflare
tunnel → node loopback :8102). `GET /healthz` is public; everything else
needs `Authorization: Bearer $KEEPER_TOKEN` (source of truth: Bao
`secret/projects/pi-infinity-llm/KEEPER_TOKEN`) or a browser session
cookie. No token in URLs, ever.

## Matrix shape (33 keys, ok-only open view)

Seeds cover all 33 `secret/projects/pi-infinity-llm/` keys
(`scripts/render-seeds.sh` renders them, values never in git): 11 live
routes with credentials + 22 keyless placeholders (`wire: none`, never
probed, honestly `unknown`). Rows are Bao `email` owners (8 today).
Opening a provider shows only `ok` model columns, best
ArtificialAnalysis score first (unscored last; stale badge when AA is
stale) — live since 2026-09-18 (key in Bao
`pi-infinity-llm/ARTIFICIALANALYSIS_API_KEY`, sent as `x-api-key`;
slugs are the join key, provider/model ids match on the bare name).
Internal ids with no AA counterpart (e.g. big-pickle) stay honestly
unscored — display-only: `/packs` + matrix JSON keep every column.

## Endpoints

| Path | Auth | Use |
|---|---|---|
| `GET /healthz` | none | liveness (`ok`) |
| `GET /login` | none | public token form |
| `POST /api/v1/session` | bearer (never cookie) | mint 12h `keeper_session` cookie (`HttpOnly; Secure; SameSite=Lax`) |
| `GET /` | bearer or session cookie | server-rendered matrix + 30s poller |
| `GET /api/v1/matrix` (`?refresh=1` bypasses cache) | bearer or session cookie | matrix JSON the page poller reads |
| `GET /guides`, `/signin`, `/report` | bearer or session cookie | consumer cards, re-mint steps, feedback form |
| `POST /api/v1/session/logout` | cookie or bearer | destroy session |
| all `POST` except login/logout | bearer only | cookie on POST → 401 (except logout) |

## Real browser path (header-gated pages have no anonymous view)

1. Open `https://keeper.pkubelka.cz/login`.
2. Paste `KEEPER_TOKEN` into the form and submit. The page `fetch`es
   `POST /api/v1/session` with the token in the `Authorization` header
   (body path — never the URL); on 200 the server sets `keeper_session`
   and the browser lands on `/`.
3. `/` renders the matrix server-side (works without JS); the embedded
   poller re-reads `GET /api/v1/matrix?refresh=1` every 30s and shows a
   stale banner if refresh fails — never silent old data.
4. Log out via the page button (`POST /api/v1/session/logout`).

## Verification (2026-09-18, live, token redacted)

- `GET /api/v1/matrix` bearer → **200**, 1 email, 46 columns.
- `GET /login` anonymous → **200**, form posts to `/api/v1/session`.
- `POST /api/v1/session` bearer → **200** `{"ok": true}` + `Set-Cookie:
  keeper_session=…`.
- `GET /` cookie-only → **200**, matrix page; `GET /api/v1/matrix`
  cookie-only → **200**.
- `POST /api/v1/probe` cookie-only → **401** (POSTs stay bearer-only).
- `POST /api/v1/session/logout` → **200**; `GET /` with the old cookie
  → **401** (session destroyed).

Curl equivalents of each step above (replace `$KEEPER_TOKEN` from Bao):

```bash
B=https://keeper.pkubelka.cz
curl -s -H "Authorization: Bearer $KEEPER_TOKEN" $B/api/v1/matrix -o /dev/null -w "%{http_code}\n"
curl -s -D - -H "Authorization: Bearer $KEEPER_TOKEN" -X POST $B/api/v1/session -o /dev/null
# then: curl -s -H "Cookie: keeper_session=<from Set-Cookie>" $B/ -o /dev/null -w "%{http_code}\n"
```
