# Keeper tree edit — provenance note (2026-09-20)

The uncommitted `keeper/server.py` change (+43/-3: `zen_identity`
header-forwarding for opencode-zen routes) does NOT belong to the
zencli serve goal. Baseline evidence:

- File mtime `2026-09-20T15:05:31+0200` (= 13:05Z) predates this goal's
  activation (`20260920132220` = 13:22:20Z). It comes from the halted
  keeper-identity thread, stopped mid-edit by owner direction
  ("noo i want to speak with u") before this goal was drafted.
- `git log --since=2026-09-20T13:22:00Z -- keeper/` is empty: no commit
  in this goal touches keeper/.
- The diff is self-contained (new `zen_identity`/`_zen_rand` + threading
  through `chat_completions`/`call_upstream`); nothing in zencli/ or
  this goal depends on it, and it changes no tested behavior adversely
  (keeper suite 127 OK with it present).

Disposition: left uncommitted and untouched — shipping or reverting it
is the halted thread's decision, not this goal's. It must not be read
as part of the zencli deliverable.
