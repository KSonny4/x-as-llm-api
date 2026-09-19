# pi-zen-bridge verdict: FIT with known limits (2026-09-19)

## M1 spike: FIT in 13.5s

`pi -p --model zen-cli/mimo-v2.5-free` answered through the bridge.
Integration traps found and fixed (all measured):
- pi-spawned CLI hangs on piped stdin until timeout kill → `stdio: ignore`
- `opencode` not on pi's PATH → `OPENCODE_BIN` env (absolute path)
- free models prefer tool calls over text (`date` executions) →
  load-bearing plain-text instruction in the prompt wrapper
  (skippable via `ZEN_CLI_ALLOW_TOOLS=1` for CLI-action runs)
- opencode permission gate denies writes outside its CWD
  (`external_directory ... auto-rejecting`) → run pi with CWD = task dir

## M2 hardening truth

Timeout (180s SIGTERM with telemetry), abort (kills child), and error
(non-zero exit with stderr head) behavior all demonstrated live.
Structural limit, measured not assumed: the provider is TEXT-ONLY —
pi can never receive `toolCall` blocks through it, so pi-native tools
(Write/Bash/Task/subagents) cannot trigger. Agency lives inside the
CLI session instead.

## M3 e2e: real task, parallel fan-out, green tests

Two parallel `pi -p` agents (process-level fan-out — pi tool-call
fan-out is impossible through a text-only provider, see above):
- mimo-v2.5-free wrote `/tmp/zen-task/fizzbuzz.py` (PART-A-DONE)
- nemotron-3-ultra-free wrote `/tmp/zen-task/test_fizzbuzz.py`
  (PART-B-DONE)
- `python3 -m unittest discover`: 4 tests, OK

Free Zen keys are usable inside pi for chat AND CLI-executed tasks.
Direct-HTTP chat stays vendor-denied (FreeTierError) — unchanged.
