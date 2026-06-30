#!/usr/bin/env bash
# Eunomia SYNC1 — pull verified footage from Styx to Hades via rsync.
#
# Modeled on pluto-sync/bin/sync-robot0X-recent-episodes.sh:
#   * flock single-instance guard
#   * Query S1 for episodes with footage_state = 'on_styx' (spot-check first, newest-first)
#   * Atomic rsync into .tmp-<ep>/, mv on success
#   * ffprobe completeness check before promotion
#   * footage_state transitions logged as operational_events
#
# Runs on Hades as user pluto, fired by eunomia-sync-footage.timer every 5 min.
# Configuration via /etc/eunomia-sync/env (EnvironmentFile in the systemd unit).
#
# Required env vars:
#   SYNC1_STYX_HOST       Tailscale IP or hostname of Styx
#   SYNC1_STYX_USER       SSH user on Styx (default: pantheon)
#   SYNC1_SSH_KEY          Path to the SSH private key
#   SYNC1_SOURCE_ROOT     Source root on Styx (default: /mnt/robot-pool/umi)
#   SYNC1_DEST_ROOT       Destination root on Hades (default: /mnt/robot-pool/styx/umi)
#   SYNC1_STYX_PG_DSN     psql connection string for Styx S1
#   SYNC1_BW_LIMIT_KBPS   rsync bandwidth limit in KBps (default: 50000 = 50 Mbps)
#
# Usage:
#   eunomia-sync-footage.sh              # normal run
#   eunomia-sync-footage.sh --dry-run    # print what would transfer
#   eunomia-sync-footage.sh --check      # verify connectivity only
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

STYX_HOST="${SYNC1_STYX_HOST:?SYNC1_STYX_HOST not set}"
STYX_USER="${SYNC1_STYX_USER:-pantheon}"
SSH_KEY="${SYNC1_SSH_KEY:?SYNC1_SSH_KEY not set}"
SOURCE_ROOT="${SYNC1_SOURCE_ROOT:-/mnt/robot-pool/umi}"
DEST_ROOT="${SYNC1_DEST_ROOT:-/mnt/robot-pool/styx/umi}"
STYX_PG_DSN="${SYNC1_STYX_PG_DSN:?SYNC1_STYX_PG_DSN not set}"
BW_LIMIT="${SYNC1_BW_LIMIT_KBPS:-50000}"
MAX_RETRIES="${SYNC1_MAX_RETRIES:-3}"

LOCK="/tmp/eunomia-sync-footage.lock"
LOG="${SYNC1_LOG:-/var/log/eunomia-sync/footage.log}"
STATUS_DIR="${SYNC1_STATUS_DIR:-/var/log/eunomia-sync}"
BROKEN_DIR="$DEST_ROOT/.broken"
DRY_RUN=0
CHECK_ONLY=0

SSH_OPTS="-i $SSH_KEY -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
REMOTE="$STYX_USER@$STYX_HOST"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --check)   CHECK_ONLY=1 ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────

log_msg() { echo "[$(date -Iseconds)] $*"; }

styx_psql() {
  psql "$STYX_PG_DSN" -tAX -c "$1" 2>/dev/null
}

styx_psql_exec() {
  psql "$STYX_PG_DSN" -c "$1" >/dev/null 2>&1
}

ssh_styx() {
  ssh -n $SSH_OPTS "$REMOTE" "$@"
}

# ── Connectivity check ───────────────────────────────────────────────────────

check_connectivity() {
  local ok=0
  if ssh_styx "echo ok" >/dev/null 2>&1; then
    log_msg "SSH to $REMOTE: ok"
  else
    log_msg "SSH to $REMOTE: FAILED"
    ok=1
  fi

  if styx_psql "SELECT 1" >/dev/null 2>&1; then
    log_msg "Postgres ($STYX_HOST): ok"
  else
    log_msg "Postgres ($STYX_HOST): FAILED"
    ok=1
  fi
  return $ok
}

if [[ $CHECK_ONLY -eq 1 ]]; then
  check_connectivity
  exit $?
fi

# ── Main sync ────────────────────────────────────────────────────────────────

mkdir -p "$DEST_ROOT" "$BROKEN_DIR" "$STATUS_DIR"

{
  log_msg "===== eunomia-sync-footage start ====="

  # flock single-instance guard — skip if another sync is running.
  if ! flock -n "$LOCK" true; then
    log_msg "another sync still running, skipping"
    log_msg "===== eunomia-sync-footage done ====="
    exit 0
  fi

  flock -n "$LOCK" bash -c '
    set -euo pipefail

    REMOTE="'"$REMOTE"'"
    SSH_OPTS="'"$SSH_OPTS"'"
    SOURCE_ROOT="'"$SOURCE_ROOT"'"
    DEST_ROOT="'"$DEST_ROOT"'"
    BW_LIMIT="'"$BW_LIMIT"'"
    MAX_RETRIES="'"$MAX_RETRIES"'"
    DRY_RUN="'"$DRY_RUN"'"
    BROKEN_DIR="'"$BROKEN_DIR"'"
    STATUS_DIR="'"$STATUS_DIR"'"
    STYX_PG_DSN="'"$STYX_PG_DSN"'"

    log_msg() { echo "[$(date -Iseconds)] $*"; }

    styx_psql() {
      psql "$STYX_PG_DSN" -tAX -c "$1" 2>/dev/null
    }

    styx_psql_exec() {
      psql "$STYX_PG_DSN" -c "$1" >/dev/null 2>&1
    }

    mint_event_id() {
      # Deterministic event_id: UUID5 from namespace + episode_id + event_type
      # Matches eunomia_ingest.events.mint_event_id pattern for idempotency.
      local ns="6ba7b810-9dad-11d1-80b4-00c04fd430c8"
      local input="sync:${1}:${2}"
      echo "$input" | python3 -c "
import sys, uuid
data = sys.stdin.read().strip()
print(uuid.uuid5(uuid.UUID('"'"'$ns'"'"'), data))
" 2>/dev/null || echo "$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo unknown)"
    }

    log_state_transition() {
      local episode_id="$1"
      local new_state="$2"
      local event_id
      event_id=$(mint_event_id "$episode_id" "sync_state_transition_$new_state")

      styx_psql_exec "
        INSERT INTO operational_event (event_id, entity, entity_id, event_type, as_of, payload)
        VALUES (
          '"'"'$event_id'"'"',
          '"'"'footage_reference'"'"',
          '"'"'$episode_id'"'"',
          '"'"'sync_state_transition'"'"',
          NOW(),
          jsonb_build_object(
            '"'"'new_state'"'"', '"'"'$new_state'"'"',
            '"'"'source_host'"'"', '"'"'$REMOTE'"'"',
            '"'"'dest_root'"'"', '"'"'$DEST_ROOT'"'"'
          )
        )
        ON CONFLICT (event_id) DO NOTHING;
      "
    }

    update_footage_state() {
      local episode_id="$1"
      local new_state="$2"

      styx_psql_exec "
        UPDATE footage_reference
        SET footage_state = '"'"'$new_state'"'"'
        WHERE episode_id = '"'"'$episode_id'"'"'
          AND footage_state != '"'"'$new_state'"'"';
      "
      log_state_transition "$episode_id" "$new_state"
    }

    # 1. Query S1 for episodes eligible for sync.
    #    Spot-check episodes first (priority lane), then newest-first by episode_id.
    episodes=$(styx_psql "
      SELECT fr.episode_id,
             COALESCE(
               (SELECT string_agg(loc, ',') FROM unnest(fr.locations) AS loc),
               ''
             ) AS locations
      FROM footage_reference fr
      WHERE fr.footage_state = '"'"'on_styx'"'"'
      ORDER BY
        fr.spot_check_selected DESC NULLS LAST,
        fr.episode_id DESC;
    " || true)

    if [[ -z "$episodes" ]]; then
      log_msg "no episodes pending sync"
      log_msg "===== eunomia-sync-footage done ====="
      exit 0
    fi

    n_total=$(echo "$episodes" | grep -c "^." || true)
    log_msg "episodes pending: $n_total"

    if [[ $DRY_RUN -eq 1 ]]; then
      log_msg "[dry-run] would sync:"
      echo "$episodes" | while IFS="|" read -r ep_id locs; do
        [[ -z "$ep_id" ]] && continue
        log_msg "  $ep_id  locations=$locs"
      done
      log_msg "===== eunomia-sync-footage done (dry-run) ====="
      exit 0
    fi

    # 2. Reap leftover .tmp-* dirs from prior killed rsyncs.
    while IFS= read -r tmp; do
      [[ -d "$tmp" ]] || continue
      log_msg "  reaping leftover: ${tmp#$DEST_ROOT/}"
      rm -rf "$tmp"
    done < <(find "$DEST_ROOT" -mindepth 1 -maxdepth 3 -type d -name ".tmp-*" 2>/dev/null)

    # 3. Per-episode: rsync into .tmp-<ep>, validate, atomic mv.
    n_ok=0; n_fail=0; bytes_total=0
    while IFS="|" read -r ep_id locs; do
      [[ -z "$ep_id" ]] && continue

      # Derive the source path from locations (tier:path format).
      # The first location with tier "styx" gives the relative path.
      src_relpath=""
      IFS="," read -ra loc_arr <<< "$locs"
      for loc in "${loc_arr[@]}"; do
        case "$loc" in
          styx:*)
            src_relpath="${loc#styx:}"
            ;;
        esac
      done

      # Fallback: if no styx: location, try to find the episode on the remote
      # by searching under SOURCE_ROOT for a directory matching the episode_id.
      if [[ -z "$src_relpath" ]]; then
        src_relpath=$(ssh -n $SSH_OPTS "$REMOTE" \
          "find '"'"'$SOURCE_ROOT'"'"' -maxdepth 4 -type d -name '"'"'*$ep_id*'"'"' -printf '"'"'%P\n'"'"' 2>/dev/null | head -1" || true)
      fi

      if [[ -z "$src_relpath" ]]; then
        log_msg "  SKIP: $ep_id — cannot resolve source path"
        continue
      fi

      TMP="$DEST_ROOT/.tmp-$ep_id"
      FINAL="$DEST_ROOT/$src_relpath"

      # Skip if already landed (idempotent).
      if [[ -d "$FINAL" ]]; then
        log_msg "  skip (already landed): $ep_id"
        update_footage_state "$ep_id" "on_hades"
        n_ok=$((n_ok + 1))
        continue
      fi

      mkdir -p "$(dirname "$FINAL")"
      rm -rf "$TMP"

      # Mark as shipped before starting transfer.
      update_footage_state "$ep_id" "shipped"

      # rsync with bandwidth limit, atomic tmp dir.
      if nice -n 10 ionice -c2 -n7 \
           rsync -ahz --partial \
             --bwlimit="$BW_LIMIT" \
             --timeout=300 --contimeout=30 \
             --skip-compress=insv/mp4/lrv/insp \
             -e "ssh $SSH_OPTS" \
             "$REMOTE:$SOURCE_ROOT/$src_relpath/" \
             "$TMP/"; then

        # ffprobe completeness check on any video files.
        validation_ok=1
        while IFS= read -r vfile; do
          if ! ffprobe -v error -show_entries format=duration "$vfile" >/dev/null 2>&1; then
            log_msg "  INCOMPLETE (ffprobe failed): $ep_id — $(basename "$vfile")"
            validation_ok=0
            break
          fi
        done < <(find "$TMP" \( -name "*.mp4" -o -name "*.insv" \) -size +0c 2>/dev/null)

        if [[ $validation_ok -eq 1 ]]; then
          mv "$TMP" "$FINAL"
          touch "$FINAL"
          update_footage_state "$ep_id" "on_hades"

          ep_bytes=$(du -sb "$FINAL" 2>/dev/null | awk '"'"'{print $1}'"'"' || echo 0)
          bytes_total=$((bytes_total + ep_bytes))
          log_msg "  ok: $ep_id ($ep_bytes bytes)"
          n_ok=$((n_ok + 1))
        else
          n_fail=$((n_fail + 1))
          # Check retry count.
          retry_marker="$TMP/.sync_retries"
          retries=0
          [[ -f "$retry_marker" ]] && retries=$(cat "$retry_marker" 2>/dev/null || echo 0)
          retries=$((retries + 1))
          echo "$retries" > "$retry_marker"

          if [[ $retries -ge $MAX_RETRIES ]]; then
            reason_dir="$BROKEN_DIR/validation_failed"
            mkdir -p "$reason_dir"
            mv "$TMP" "$reason_dir/$ep_id"
            log_msg "  BROKEN (max retries): $ep_id → .broken/"
            # Revert to on_styx so it does not stay as shipped forever.
            update_footage_state "$ep_id" "on_styx"
          fi
        fi
      else
        log_msg "  rsync failed (will retry): $ep_id"
        n_fail=$((n_fail + 1))
      fi
    done <<< "$episodes"

    log_msg "  synced=$n_ok failed=$n_fail bytes=$bytes_total"

    # Write a run summary for the status script.
    cat > "$STATUS_DIR/.last_run.json" <<RUNEOF
{
  "timestamp": "$(date -Iseconds)",
  "episodes_synced": $n_ok,
  "episodes_failed": $n_fail,
  "bytes_transferred": $bytes_total,
  "episodes_pending": $((n_total - n_ok))
}
RUNEOF

    log_msg "===== eunomia-sync-footage done ====="
  '
} >> "$LOG" 2>&1
