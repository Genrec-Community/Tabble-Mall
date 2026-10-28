#!/bin/sh
# Run by systemd before every start of the agent (ExecStartPre), as the service user.
#
# After the agent updates itself it leaves print-agent.trial beside the program and deletes
# it once it has been connected for a minute. Every start while that file exists is counted
# here; after MAX launches that never became healthy the previous program (print-agent.old)
# is put back, the bad version is recorded in print-agent.bad so the agent will not fetch it
# again for a day, and the old version starts.
#
# It is done here and not in the agent because a build that cannot run cannot be asked to
# undo itself. It never fails the start: with no trial it does nothing, and the unit
# ignores a failure of this script (ExecStartPre=-).
#
#   rollback-guard.sh [install-dir]
MAX=3
DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
EXE="$DIR/print-agent"
TRIAL="$DIR/print-agent.trial"

[ -f "$TRIAL" ] || exit 0

get() { sed -n "s/^$1=//p" "$TRIAL" | head -n 1 | tr -d '\r'; }
from="$(get from)"
to="$(get to)"
starts="$(get starts)"
case "$starts" in ''|*[!0-9]*) starts=0 ;; esac
starts=$((starts + 1))

if [ "$starts" -le "$MAX" ]; then
  printf 'from=%s\nto=%s\nstarts=%s\n' "$from" "$to" "$starts" > "$TRIAL.tmp" \
    && mv -f "$TRIAL.tmp" "$TRIAL"
  exit 0
fi

if [ -f "$EXE.old" ]; then
  mv -f "$EXE" "$EXE.bad"
  mv -f "$EXE.old" "$EXE"
  printf 'version=%s\nuntil=%s\n' "$to" "$(( $(date +%s) + 86400 ))" > "$DIR/print-agent.bad"
  echo "mallt-print-agent: version $to did not become healthy in $MAX starts; restored $from" >&2
else
  echo "mallt-print-agent: update did not become healthy and there is no previous program to restore" >&2
fi
rm -f "$TRIAL"
exit 0
