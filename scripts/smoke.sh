#!/usr/bin/env bash
# One redacting implementation for local/public/in-allocation checks.
# Read-only unless explicitly enabling documented SMOKE_* actions.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BASE="${1:-${BASE:-http://127.0.0.1:8080}}"
exec python3 "$ROOT/keeper/smoke.py"
