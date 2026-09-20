# Keeper private OVH staging — 2026-09-20

**Not deployed to the public endpoint.** Production remains job version 11,
`main-keyqueue10`. The new inference principal/`keeper-coder` are not yet verified
or operational at `https://keeper.pkubelka.cz/v1`.

## Executed

- Independent bounded re-reviews approved safety commit `e7db1c6`.
- Private candidate `keeper-candidate-20260920t212913z`, allocation
  `4bcb5cb7-6d88-1c23-2faa-94f319127b4f`, ran on `ovh-nomad-fresh`.
  Keeper listened on loopback **18102**, leaving public production **8102** alone.
- Keeper code/image: `e7db1c60b6505074c36dc089ef813a124a96e292`, amd64 manifest
  `sha256:286cd718941a686de3161b944a116d061588c6403440bc7b989463a1c0f62062`.
  CLI image: reviewed `d751be8` digest
  `sha256:52a318754013e0d6ff56dd73899602e45ad2fde8e072ca2b3e2bff218f58eaa6`.
- Refreshed legacy SQLite backup: integrity `ok`, 20,480 bytes, four rows;
  SHA256 `3522522772db98706a8306b94665f8e1ebe5c7b80cbb6c6e2bf8a52f130e933b`.
  Backup and private rollback configuration are in the operator's mode-0700
  Keeper backup directory, with mode-0600 secret-bearing configuration files.
- Loaded **33 credential references**, **980 catalog models**, **3,088 exact
  connections**. **229** pairs were eligible for the paced sweep. Paid,
  unknown, unsupported and unproven-account-tier rows remained blocked.
- Final sampled progress: **48 done / 181 pending**, **zero Working models**.
  This is not complete coverage or a successful service acceptance result.
  Three inventory discoveries failed; worker and bridge synchronization remained
  operational. Catalog scan found no provider/admin/service secret values.

## Deployment defect found and fixed

Nomad planning accepted a Docker-style top-level `tmpfs` field, but the actual
Docker driver rejected it. Replaced it with the supported `mount { type="tmpfs"
... tmpfs_options { size=536870912 mode=1023 } }` block; 1023 is decimal Unix 01777.
No host configuration or privileges were changed.

The replacement allocation proved `/tmp` is `rw,nosuid,nodev,noexec`, 512 MiB;
UID 65532; effective capabilities zero; `NoNewPrivs=1`; root filesystem not
writable. A packaging regression checks the rendered mount configuration.
A successful Nomad plan alone does **not** validate every Docker-driver option.

## Live inference blockers

1. The actual genuine OpenCode **1.18.31** process, with the isolated exact stored
   key and dedicated deny-all agent, returned **HTTP 403 `FreeTierError`** for
   freshly eligible `big-pickle`: “OpenCode's free tier can only be used from
   within OpenCode.” This is evidence about the **hardened configuration**, not
   a retraction of today's historical genuine CLI success. Its cause must not
   be inferred solely from the direct HTTP rejection.
2. Direct-provider sweep attempts were rate-limited. A separate Kilo check of
   fresh zero-price, text-only `inclusionai/ling-3.0-flash-vl:free`, after honoring
   the recorded cooldown, returned HTTP 429 / `rate_limit_exceeded` from OVH.
   The earlier Mac HTTP 200 is not production readiness evidence.

An [OpenCode collaborator's statement](https://github.com/anomalyco/opencode/issues/49580#issuecomment-5723289721)
says free-tier abuse checks were tightened and very custom configurations can
be misclassified. Do not spoof client identity, enable paid fallback, or relax
the deny-all sandbox to get a green result. Provider approval/compatibility or
an actually available approved free API route is still needed.

Live diagnosis also found that the bridge mapped a structured CLI denial to
HTTP 502, unnecessarily making it retryable. The follow-up source fix preserves
only allowlisted HTTP rejection/rate-limit codes and validated `Retry-After`;
it never returns the vendor error message/body/other headers. That source change
requires its own rebuilt CLI image before another rollout.

## Safe stopped state

The private candidate was stopped to avoid repeated rejected provider calls.
Production was not switched. Durable availability state is retained on the
verified host bind; no Working result was invented or imported. Fresh public
inference, public auth isolation, allocation-replacement persistence, and final
README consumption acceptance remain **pending**.
