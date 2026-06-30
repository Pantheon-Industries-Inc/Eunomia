#!/usr/bin/env bash
# Eunomia SYNC1 — generate status.json for the storage-health dashboard.
#
# Reads the last-run summary from the footage sync, queries Postgres replication
# status on the local Hades replica, and checks Styx SSH reachability.
#
# Output: /var/log/eunomia-sync/status.json
# Runs every 60s via eunomia-sync-status.timer.
set -uo pipefail

STATUS_DIR="${SYNC1_STATUS_DIR:-/var/log/eunomia-sync}"
STATUS_FILE="$STATUS_DIR/status.json"
DEST_ROOT="${SYNC1_DEST_ROOT:-/mnt/robot-pool/styx/umi}"
BROKEN_DIR="$DEST_ROOT/.broken"

STYX_HOST="${SYNC1_STYX_HOST:-}"
STYX_USER="${SYNC1_STYX_USER:-pantheon}"
SSH_KEY="${SYNC1_SSH_KEY:-}"

HADES_REPLICA_DSN="${SYNC1_HADES_REPLICA_DSN:-}"

mkdir -p "$STATUS_DIR"

# ── Last footage sync run ────────────────────────────────────────────────────

last_run=""
last_success=""
episodes_synced=0
episodes_failed=0
episodes_pending=0
bytes_last_run=0

if [[ -f "$STATUS_DIR/.last_run.json" ]]; then
  last_run=$(python3 -c "
import json, sys
d = json.load(open('$STATUS_DIR/.last_run.json'))
print(d.get('timestamp', ''))
" 2>/dev/null || echo "")

  episodes_synced=$(python3 -c "
import json
d = json.load(open('$STATUS_DIR/.last_run.json'))
print(d.get('episodes_synced', 0))
" 2>/dev/null || echo 0)

  episodes_failed=$(python3 -c "
import json
d = json.load(open('$STATUS_DIR/.last_run.json'))
print(d.get('episodes_failed', 0))
" 2>/dev/null || echo 0)

  episodes_pending=$(python3 -c "
import json
d = json.load(open('$STATUS_DIR/.last_run.json'))
print(d.get('episodes_pending', 0))
" 2>/dev/null || echo 0)

  bytes_last_run=$(python3 -c "
import json
d = json.load(open('$STATUS_DIR/.last_run.json'))
print(d.get('bytes_transferred', 0))
" 2>/dev/null || echo 0)

  if [[ $episodes_synced -gt 0 && $episodes_failed -eq 0 ]]; then
    last_success="$last_run"
  fi
fi

# ── Broken episodes count ────────────────────────────────────────────────────

episodes_broken=0
if [[ -d "$BROKEN_DIR" ]]; then
  episodes_broken=$(find "$BROKEN_DIR" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | wc -l || echo 0)
  episodes_broken=$((episodes_broken + 0))
fi

# ── Styx reachability ────────────────────────────────────────────────────────

styx_reachable=false
if [[ -n "$STYX_HOST" && -n "$SSH_KEY" ]]; then
  if ssh -n -i "$SSH_KEY" \
       -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
       "$STYX_USER@$STYX_HOST" "echo ok" >/dev/null 2>&1; then
    styx_reachable=true
  fi
fi

# ── Postgres replication status ──────────────────────────────────────────────

sub_active=false
lag_bytes=0
latest_end_time=""

if [[ -n "$HADES_REPLICA_DSN" ]]; then
  repl_info=$(psql "$HADES_REPLICA_DSN" -tAX -c "
    SELECT
      CASE WHEN pid IS NOT NULL THEN 'true' ELSE 'false' END,
      COALESCE(EXTRACT(EPOCH FROM (NOW() - latest_end_time))::bigint, -1),
      COALESCE(TO_CHAR(latest_end_time, 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '')
    FROM pg_stat_subscription
    WHERE subname = 'eunomia_styx_sub'
    LIMIT 1;
  " 2>/dev/null || echo "false|-1|")

  if [[ -n "$repl_info" ]]; then
    IFS="|" read -r sub_active lag_secs latest_end_time <<< "$repl_info"
    lag_bytes=$((lag_secs > 0 ? lag_secs : 0))
  fi
fi

# ── Effective throughput ─────────────────────────────────────────────────────

effective_mbps=0
if [[ $bytes_last_run -gt 0 ]]; then
  # Approximate: assume the 5-minute timer interval was fully used.
  effective_mbps=$(python3 -c "print(round($bytes_last_run * 8 / 1_000_000 / 300, 1))" 2>/dev/null || echo 0)
fi

# ── Write status.json ────────────────────────────────────────────────────────

TMP="$STATUS_FILE.tmp"
cat > "$TMP" <<EOF
{
  "generated_at": "$(date -Iseconds)",
  "footage": {
    "last_run": "$last_run",
    "last_success": "$last_success",
    "episodes_synced_total": $episodes_synced,
    "episodes_pending": $episodes_pending,
    "episodes_broken": $episodes_broken,
    "bytes_last_run": $bytes_last_run,
    "effective_mbps": $effective_mbps,
    "styx_reachable": $styx_reachable
  },
  "replication": {
    "subscription_active": $sub_active,
    "lag_seconds": $lag_bytes,
    "latest_end_time": "$latest_end_time"
  }
}
EOF

mv "$TMP" "$STATUS_FILE"
