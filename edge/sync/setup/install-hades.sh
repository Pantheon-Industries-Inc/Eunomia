#!/usr/bin/env bash
# Idempotent installer for SYNC1 on Hades (the R730).
# Copies sync scripts, installs systemd units + logrotate.
#
# Usage: sudo ./install-hades.sh
# Re-run is safe (idempotent).
#
# What this installs:
#   * 3 sync scripts -> /home/pluto/bin/ (mode 755, owned by pluto)
#   * 6 systemd units -> /etc/systemd/system/ (mode 644)
#   * 1 logrotate config -> /etc/logrotate.d/ (mode 644)
#   * Creates /var/log/eunomia-sync/ (owned by pluto)
#   * Enables and starts all 3 timers
#
# What this does NOT touch:
#   * Styx (run setup-styx-replication.sh separately)
#   * The Postgres subscription (run setup-hades-subscription.sql separately)
#   * The pluto-sync timers or storage-health dashboard
#   * Any data on /mnt/robot-pool
set -euo pipefail

SRC_DIR=$(cd "$(dirname "$0")/.." && pwd)

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (sudo ./install-hades.sh)" >&2
  exit 1
fi

id -u pluto >/dev/null 2>&1 || { echo "ERROR: user 'pluto' missing"; exit 1; }

echo "==> Creating /var/log/eunomia-sync/ (owner pluto)"
install -d -o pluto -g pluto -m 0755 /var/log/eunomia-sync

echo "==> Installing sync scripts to /home/pluto/bin/"
install -d -o pluto -g pluto -m 0755 /home/pluto/bin
for f in "$SRC_DIR"/bin/eunomia-*.sh; do
  install -o pluto -g pluto -m 0755 "$f" "/home/pluto/bin/$(basename "$f")"
  echo "    $(basename "$f")"
done

echo "==> Installing logrotate config"
install -m 0644 "$SRC_DIR/logrotate/eunomia-sync" /etc/logrotate.d/eunomia-sync

echo "==> Installing systemd units to /etc/systemd/system/"
for f in "$SRC_DIR"/systemd/eunomia-*.service "$SRC_DIR"/systemd/eunomia-*.timer; do
  install -m 0644 "$f" "/etc/systemd/system/$(basename "$f")"
  echo "    $(basename "$f")"
done

echo "==> systemctl daemon-reload"
systemctl daemon-reload

echo "==> Enabling and starting timers"
for t in eunomia-sync-footage.timer eunomia-sweep-broken.timer eunomia-sync-status.timer; do
  systemctl enable "$t"
  systemctl restart "$t"
  echo "    $t"
done

if [[ ! -f /etc/eunomia-sync/env ]]; then
  echo ""
  echo "WARNING: /etc/eunomia-sync/env does not exist yet."
  echo "Create it with the required environment variables before the first sync runs."
  echo "See edge/sync/README.md for the template."
fi

cat <<EOF

================================================================================
SYNC1 installed on Hades.

Timers:
  systemctl list-timers 'eunomia-*' --no-pager

Logs:
  tail -f /var/log/eunomia-sync/footage.log
  tail -f /var/log/eunomia-sync/sweep.log
  cat /var/log/eunomia-sync/status.json | python3 -m json.tool

Manual run:
  sudo -u pluto /home/pluto/bin/eunomia-sync-footage.sh --dry-run
  sudo -u pluto /home/pluto/bin/eunomia-sync-footage.sh --check

This installer does NOT set up Postgres replication. Run:
  1. setup-styx-replication.sh on Styx
  2. setup-hades-subscription.sql on Hades
See edge/sync/README.md for the full procedure.
================================================================================
EOF
