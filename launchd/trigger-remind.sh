#!/bin/bash
# Start the "Vet records reminder" workflow from this Mac, because GitHub's own
# schedule has been starting runs 4-9 hours late. Run by launchd (see the .plist next
# to this file) at 08:30, 09:00 and 09:30 on Mon/Wed/Fri. Each attempt only starts
# the workflow if it's still 8-10am New York time and the workflow hasn't already run
# today, so the later slots are retries (asleep, no network) rather than extra
# reminders.
#
#   trigger-remind.sh            normal run
#   trigger-remind.sh --dry-run  do every check, but don't start the workflow
#   trigger-remind.sh --force    skip the day/time window check (still skips if already run today)
set -euo pipefail

GH=/opt/homebrew/bin/gh
REPO=jwamin/vrr-discord-plugin
WORKFLOW=remind.yml
export TZ=America/New_York

dry_run=false force=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --force) force=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

# launchd runs a missed time slot when the Mac wakes, which could be hours later
weekday=$(date +%u) hour=$((10#$(date +%H)))
if ! $force && { [[ ! "$weekday" =~ ^[135]$ ]] || (( hour < 8 || hour >= 10 )); }; then
  log "outside Mon/Wed/Fri 8-10am, not starting"
  exit 0
fi

# midnight New York time, in UTC, to compare with the run's createdAt (ISO strings sort correctly)
midnight=$(date -j -f '%Y-%m-%d %H:%M:%S' "$(date +%Y-%m-%d) 00:00:00" +%s)
since=$(TZ=UTC date -r "$midnight" +%Y-%m-%dT%H:%M:%SZ)

# the network may not be up yet straight after waking
for attempt in 1 2 3 4 5; do
  if runs=$("$GH" run list -R "$REPO" -w "$WORKFLOW" -L 20 --json createdAt,event,status,conclusion \
              --jq "[.[] | select(.createdAt >= \"$since\")
                          | select(.conclusion != \"failure\" and .conclusion != \"cancelled\")] | length"); then
    break
  fi
  log "gh run list failed (attempt $attempt), retrying in 30s"
  sleep 30
done
if [[ -z "${runs:-}" ]]; then
  log "could not reach GitHub, giving up (a later slot will retry)"
  exit 1
fi

if (( runs > 0 )); then
  log "workflow already ran today ($runs run(s) since $since), not starting"
  exit 0
fi

if $dry_run; then
  log "dry run: would start $WORKFLOW on $REPO"
  exit 0
fi
"$GH" workflow run "$WORKFLOW" -R "$REPO"
log "started $WORKFLOW on $REPO"
