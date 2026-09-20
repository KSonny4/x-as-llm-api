# Protected zencli sanity check

Before diagnosing zencli availability, changing its invocation/configuration, or deploying Keeper integration, read [the verified original zencli control](docs/zencli-sanity-check.md) and its [HTTP receipt](docs/zencli-sanity-check.json).

**Original zencli works on Nomad:** unchanged `main-1` image, exact local-login key, `big-pickle`, original `/v1/chat/completions`, HTTP **200**, answer `September 20, 2026.` Job `zencli-original-sanity-1789946002` (2026-09-20 UTC). The local `opencode run --model opencode/big-pickle "whats the date"` control also passed.

- Preserve the original source and immutable control image; isolate candidate edits.
- Compare against that control on the same host/key/model/input before attributing failures. Keep configuration differences explicit.
- Normal `> build · big-pickle` / stderr progress is not an error.
- Direct Zen HTTP failures or failed custom profiles do not disprove CLI success.
- The successful control had no custom agent, tool/permission overrides, or forced step limit. Reuse the proven flow; do not change the control to fit a replacement.
- Keep secrets out of notes, logs and Git. This receipt is not proof of public Keeper rollout, every key/model, or unrestricted upstream availability.

Also retained in Cognee `pi_cognee_memory`; recall `x-as-llm-api original zencli Nomad sanity zencli-original-sanity-1789946002` if context is lost. The checked-in receipt is sufficient without Cognee access.
