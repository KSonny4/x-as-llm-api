#!/usr/bin/env bash
# build-receipt.sh — run the hermetic suites, write artefacts + a
# pr-evidence/v1 receipt, render the pr-summary/v1 table via the guidance
# renderer. Informative: exit 0 = rendered, NOT = verified. Renderer
# refusal (exit 2) = gate red (stale/tampered/missing).
#
# Usage: bash docs/l4/build-receipt.sh [--format markdown|json]
# Env: EG_ROOT (default ../engineering-guidance).
set -u
FORMAT="markdown"
if [ "${1:-}" = "--format" ]; then FORMAT="${2:-markdown}"; fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
L4="$ROOT/docs/l4"
OUT="$L4/artefacts"
mkdir -p "$OUT"
EG="${EG_ROOT:-$(dirname "$ROOT")/engineering-guidance}"
RENDERER="$EG/tools/pr_evidence.py"
if [ ! -f "$RENDERER" ]; then echo "missing renderer: $RENDERER" >&2; exit 3; fi

export L4_ROOT="$ROOT" L4_DIR="$L4" L4_OUT="$OUT"
export L4_REPO="KSonny4/x-as-llm-api"
export L4_REV="$(git -C "$ROOT" rev-parse HEAD)"
export L4_BASE="$(git -C "$ROOT" merge-base HEAD main 2>/dev/null || git -C "$ROOT" rev-parse HEAD)"
export L4_PYV="$(python3 --version 2>&1)"

run_suite() { # run_suite <start-dir> <artefact> ; echoes exit code
  local log="$OUT/$1.log" code=0
  set +e
  (cd "$ROOT" && python3 -m unittest discover -s "$1") >"$log" 2>&1
  code=$?
  set -e
  L4_LOG="$log" L4_ARTEFACT="$OUT/$2" python3 - <<'EOF'
import json, os, re
log = open(os.environ["L4_LOG"]).read()
m = re.search(r"^Ran (\d+) tests", log, re.M)
ran = int(m.group(1)) if m else 0
failed = errors = 0
m = re.search(r"^FAILED", log, re.M)
if m:
    f = re.search(r"failures=(\d+)", log); e = re.search(r"errors=(\d+)", log)
    failed = int(f.group(1)) if f else 0
    errors = int(e.group(1)) if e else 0
json.dump({"tests": {"passed": ran - failed - errors, "total": ran}},
          open(os.environ["L4_ARTEFACT"], "w"), indent=2)
EOF
  echo "$code"
}

KCODE="$(run_suite keeper keeper-tests.json)"
PCODE="$(run_suite probe probe-tests.json)"
if [ "$KCODE" = 0 ] && [ "$PCODE" = 0 ]; then export L4_VCODE=0; else export L4_VCODE=1; fi
export L4_KCODE="$KCODE" L4_PCODE="$PCODE"

python3 - <<'EOF'
import hashlib, json, os
d = {k: os.environ[k] for k in
     ("L4_DIR", "L4_OUT", "L4_REPO", "L4_REV", "L4_BASE", "L4_PYV",
      "L4_VCODE", "L4_KCODE", "L4_PCODE")}
def digest(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
defs = d["L4_DIR"] + "/pr-metrics-definitions.json"
receipt = {
    "schema": "pr-evidence/v1",
    "repository": d["L4_REPO"],
    "revision": d["L4_REV"],
    "base_revision": d["L4_BASE"],
    "definitions_sha256": digest(defs),
    "verification_exit_code": int(d["L4_VCODE"]),
    "inputs": {},
}
for key, code, artefact in (("keeper-tests", d["L4_KCODE"], "keeper-tests.json"),
                            ("probe-tests", d["L4_PCODE"], "probe-tests.json")):
    receipt["inputs"][key] = {
        "status": "complete",
        "tool": "python3 unittest",
        "tool_version": d["L4_PYV"],
        "exit_code": int(code),
        "sha256": digest(d["L4_OUT"] + "/" + artefact),
        "path": "artefacts/" + artefact,
    }
json.dump(receipt, open(d["L4_DIR"] + "/receipt.json", "w"), indent=2)
EOF

EXT="$FORMAT"
if [ "$FORMAT" = "markdown" ]; then EXT="md"; fi
python3 "$RENDERER" --definitions "$L4/pr-metrics-definitions.json" \
  --receipt "$L4/receipt.json" --evidence-root "$L4" \
  --repository "$L4_REPO" --revision "$L4_REV" --base-revision "$L4_BASE" \
  --format "$FORMAT" | tee "$L4/summary.$EXT"
echo "build exit: ${PIPESTATUS[0]}"
