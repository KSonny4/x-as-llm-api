#!/usr/bin/env bash
# nomad-exec.sh — shell (or one-shot command) into a running Nomad alloc.
# Usage:
#   scripts/nomad-exec.sh [job] [cmd...]
#   scripts/nomad-exec.sh keeper                     # interactive sh in keeper
#   scripts/nomad-exec.sh keeper "python3 -c '...'"  # one-shot, no tty
#   TASK=probe scripts/nomad-exec.sh keeper-probe/dispatch-XXX env
# Notes: picks the first RUNNING alloc of the job. Token from env or Bao
# (never stored). Batch allocs vanish when done — exec those mid-run.
set -u
export NOMAD_ADDR="${NOMAD_ADDR:-https://nomad.pkubelka.cz}"
if [ -z "${NOMAD_TOKEN:-}" ]; then
  NOMAD_TOKEN="$(bao kv get -field=management secret/projects/NomadSetup/acl)" || exit 1
  export NOMAD_TOKEN
fi
JOB="${1:-keeper}"
if [ $# -gt 0 ]; then shift; fi
TASK_ARGS=""
[ -n "${TASK:-}" ] && TASK_ARGS="-task $TASK"
ALLOC="$(nomad job allocs -json "$JOB" 2>/dev/null | python3 -c \
  "import json,sys; a=[x for x in json.load(sys.stdin) if x['ClientStatus']=='running']; print(a[0]['ID'] if a else '')")"
[ -n "$ALLOC" ] || { echo "no running alloc for job $JOB" >&2; exit 1; }
echo "alloc: $ALLOC" >&2
if [ $# -eq 0 ]; then
  # shellcheck disable=SC2086
  exec nomad alloc exec -i -t $TASK_ARGS "$ALLOC" /bin/sh
else
  # shellcheck disable=SC2086
  exec nomad alloc exec $TASK_ARGS "$ALLOC" "$@"
fi
