#!/bin/bash
# tripwire v3: refuse secret-looking literals in the deliverable tree.
#
# Scope: tracked working tree EXCLUDING orchestration scratch
# (.pi-glla/, wt/) — scratch is machine-generated transcripts, scrubbed
# separately (2026-09-20: 12 sk- values redacted) and too noisy for
# exact matching. What ships (git) is fully covered, tracked or not.
#
# Two rule classes, NO whole-line suppression (field lesson 2026-09-20:
# an `abcdef` word-exclusion silently ate a planted sk- tripwire):
#  1. prefixed formats (sk-, service prefixes, 3-segment JWT, bearer /
#     token assignments) — always fire, zero exclusions.
#  2. bare hex 40/64 runs — fire UNLESS the exact value is a git object
#     (repo SHAs, resolved dynamically) or listed in tripwire.allowlist
#     (doc digests/snapshots, verified digest-context 2026-09-20; a hex
#     KEY on a sha256-labelled line still fires because only the exact
#     known value is suppressed, never the line).
#
# Negative controls live in keeper/test_tripwire.py (TRIPWIRE_ROOT).
# Exit 0 = clean, 1 = hit (prints file:line, never values).
set -u
ROOT="${TRIPWIRE_ROOT:-$(dirname "$0")/..}"
cd "$ROOT" || exit 2
ALLOW="$(dirname "$0")/tripwire.allowlist"
SCAN_EXCLUDES=(--exclude-dir=.git --exclude-dir=node_modules
  --exclude-dir=.pi-glla --exclude-dir=wt
  --exclude="*.png" --exclude=package-lock.json)

hits=$(grep -rEn "sk-[A-Za-z0-9]{20,}|sk-or-v1-[A-Za-z0-9]{8,}|AIza[A-Za-z0-9_-]{10,}|enc:v1:[A-Za-z0-9+/=]{16,}|xox[bpas]-[A-Za-z0-9-]+|glpat-[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|[Bb][Ee][Aa][Rr][Ee][Rr] +[A-Za-z0-9_.-]{20,}|[Tt][Oo][Kk][Ee][Nn][\"']? *: *[A-Za-z0-9_.-]{20,}" . "${SCAN_EXCLUDES[@]}" -I 2>/dev/null || true)

hexhits=""
while IFS= read -r val; do
  [ -n "$val" ] || continue
  if [ "${#val}" = 40 ] && git cat-file -e "$val" 2>/dev/null; then
    continue
  fi
  if [ -f "$ALLOW" ] && grep -Fxq "$val" "$ALLOW"; then
    continue
  fi
  locs=$(grep -rEnF "$val" . "${SCAN_EXCLUDES[@]}" -I 2>/dev/null | cut -c1-100 || true)
  hexhits=$(printf "%s\n%s" "$hexhits" "$locs")
done <<EOF
$(grep -rEho "[0-9a-f]{64}|[0-9A-F]{64}|[0-9a-f]{40}|[0-9A-F]{40}" . "${SCAN_EXCLUDES[@]}" -I 2>/dev/null | sort -u)
EOF

hits=$(printf "%s\n%s" "$hits" "$hexhits" | grep -v '^$' || true)
if [ -n "$hits" ]; then
  printf "%s\n" "$hits" | cut -c1-120
  echo "TRIPWIRE DIRTY"
  exit 1
fi
echo "TRIPWIRE CLEAN"
