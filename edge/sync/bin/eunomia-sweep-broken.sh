#!/usr/bin/env bash
# Eunomia SYNC1 — hourly broken-episode sweep.
#
# Modeled on pluto-sync/bin/sweep_broken.py:
#   * Move stale .tmp-* dirs (>1h old) to .broken/<reason>/
#   * Auto-purge .broken/ entries older than PURGE_DAYS
#   * flock single-instance guard
#
# Runs on Hades as user pluto, fired by eunomia-sweep-broken.timer hourly.
set -euo pipefail

DEST_ROOT="${SYNC1_DEST_ROOT:-/mnt/robot-pool/styx/umi}"
BROKEN_DIR="$DEST_ROOT/.broken"
LOCK="/tmp/eunomia-sweep-broken.lock"
LOG="${SYNC1_SWEEP_LOG:-/var/log/eunomia-sync/sweep.log}"

STALE_AGE_SECS="${SYNC1_STALE_AGE_SECS:-3600}"
PURGE_DAYS="${SYNC1_BROKEN_PURGE_DAYS:-7}"

log_msg() { echo "[$(date -Iseconds)] $*"; }

{
  log_msg "===== eunomia-sweep-broken start ====="

  if ! flock -n "$LOCK" true; then
    log_msg "another sweep still running, skipping"
    log_msg "===== eunomia-sweep-broken done ====="
    exit 0
  fi

  flock -n "$LOCK" bash -c '
    set -euo pipefail

    DEST_ROOT="'"$DEST_ROOT"'"
    BROKEN_DIR="'"$BROKEN_DIR"'"
    STALE_AGE_SECS="'"$STALE_AGE_SECS"'"
    PURGE_DAYS="'"$PURGE_DAYS"'"

    log_msg() { echo "[$(date -Iseconds)] $*"; }

    mkdir -p "$BROKEN_DIR"
    now=$(date +%s)

    # 1. Move stale .tmp-* dirs to .broken/stale_transfer/
    moved=0
    while IFS= read -r tmp; do
      [[ -d "$tmp" ]] || continue
      mtime=$(stat -c %Y "$tmp" 2>/dev/null || stat -f %m "$tmp" 2>/dev/null || echo "$now")
      age=$((now - mtime))
      if [[ $age -gt $STALE_AGE_SECS ]]; then
        ep_name=$(basename "$tmp")
        ep_name="${ep_name#.tmp-}"
        reason_dir="$BROKEN_DIR/stale_transfer"
        mkdir -p "$reason_dir"
        mv "$tmp" "$reason_dir/$ep_name" 2>/dev/null || true
        touch "$reason_dir/$ep_name" 2>/dev/null || true
        log_msg "  moved stale: $ep_name (age=${age}s)"
        moved=$((moved + 1))
      fi
    done < <(find "$DEST_ROOT" -mindepth 1 -maxdepth 3 -type d -name ".tmp-*" 2>/dev/null)

    # 2. Purge old .broken/ entries.
    purged=0
    cutoff=$((now - PURGE_DAYS * 86400))
    if [[ -d "$BROKEN_DIR" ]]; then
      while IFS= read -r reason_dir; do
        [[ -d "$reason_dir" ]] || continue
        [[ "$(basename "$reason_dir")" == "log.tsv" ]] && continue
        while IFS= read -r ep_dir; do
          [[ -d "$ep_dir" ]] || continue
          mtime=$(stat -c %Y "$ep_dir" 2>/dev/null || stat -f %m "$ep_dir" 2>/dev/null || echo "$now")
          if [[ $mtime -lt $cutoff ]]; then
            rm -rf "$ep_dir"
            purged=$((purged + 1))
            log_msg "  purged old: $(basename "$reason_dir")/$(basename "$ep_dir")"
          fi
        done < <(find "$reason_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
        # Remove empty reason dirs.
        rmdir "$reason_dir" 2>/dev/null || true
      done < <(find "$BROKEN_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
    fi

    # 3. Count current broken episodes.
    broken_count=0
    if [[ -d "$BROKEN_DIR" ]]; then
      broken_count=$(find "$BROKEN_DIR" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | wc -l || echo 0)
      broken_count=$((broken_count + 0))
    fi

    log_msg "moved=$moved purged=$purged broken_remaining=$broken_count"
    log_msg "===== eunomia-sweep-broken done ====="
  '
} >> "$LOG" 2>&1
