#!/bin/bash
# tripwire: refuse secret-looking literals in tracked repo files.
#
# v2 (2026-09-20): whole-repo scope (was keeper+probe py only) + bare
# sk- pattern (zen keys are sk- + ~64 chars; the old pattern missed
# them). Proves "no secret values anywhere" in git, not just code.
#
# Matches real key FORMATS only (long, high-entropy). The suite's named
# fixture stubs ("k", "k1", "k2", "test-key", "test-token", "wrong",
# "uitest", "m2test", "Bearer t", "sekret", "bogus", "va/vb") are
# structurally excluded: none matches the length/charset floors below,
# so no name-allowlist is needed and none exists.
# Exit 0 = clean, 1 = hit (prints file:line, never values).
set -u
cd "$(dirname "$0")/.." || exit 2
hits=$(git grep -nE "sk-[A-Za-z0-9]{20,}|sk-or-v1-[A-Za-z0-9]{8,}|AIza[A-Za-z0-9_-]{10,}|enc:v1:[A-Za-z0-9+/=]{16,}|xox[bpas]-[A-Za-z0-9-]+|glpat-[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_-]{16,}|[A-Za-z0-9+/]{40,}={0,2}" -- . ':!*.png' ':!package-lock.json' || true)
hits=$(printf "%s" "$hits" | grep -vE "hexdigest|token_urlsafe|sha256|Max-Age|uuid|abcdef" || true)
if [ -n "$hits" ]; then
  printf "%s\n" "$hits" | cut -c1-120
  echo "TRIPWIRE DIRTY"
  exit 1
fi
echo "TRIPWIRE CLEAN"
