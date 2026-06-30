#!/usr/bin/env bash
# One-time Styx setup for SYNC1 Postgres logical replication.
#
# What this does:
#   1. Sets wal_level = logical (requires Postgres restart)
#   2. Creates the eunomia_replicator role
#   3. Grants SELECT on all tables + UPDATE(footage_state) on footage_reference
#   4. Creates the eunomia_hades publication (FOR ALL TABLES)
#   5. Adds pg_hba.conf entry for Hades (Tailscale IP)
#
# Usage: sudo bash setup-styx-replication.sh [--hades-ip <tailscale-ip>] [--pg-password <pw>]
#
# Idempotent: safe to re-run.
set -euo pipefail

HADES_IP="${SYNC1_HADES_IP:-100.119.90.17}"
PG_PASSWORD=""
PG_DB="${SYNC1_PG_DB:-eunomia}"

for arg in "$@"; do
  case "$arg" in
    --hades-ip) shift; HADES_IP="$1"; shift ;;
    --hades-ip=*) HADES_IP="${arg#*=}" ;;
    --pg-password) shift; PG_PASSWORD="$1"; shift ;;
    --pg-password=*) PG_PASSWORD="${arg#*=}" ;;
  esac
done

if [[ -z "$PG_PASSWORD" ]]; then
  echo "ERROR: --pg-password is required (the password for the eunomia_replicator role)" >&2
  echo "Usage: sudo bash setup-styx-replication.sh --pg-password <pw> [--hades-ip <ip>]" >&2
  exit 1
fi

echo "==> Setting wal_level = logical"
sudo -u postgres psql -c "ALTER SYSTEM SET wal_level = 'logical';" 2>/dev/null || true
echo "    NOTE: Postgres must be restarted for wal_level change to take effect."

echo "==> Creating eunomia_replicator role (idempotent)"
sudo -u postgres psql -c "
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eunomia_replicator') THEN
      CREATE ROLE eunomia_replicator WITH REPLICATION LOGIN PASSWORD '$PG_PASSWORD';
    ELSE
      ALTER ROLE eunomia_replicator WITH REPLICATION LOGIN PASSWORD '$PG_PASSWORD';
    END IF;
  END \$\$;
"

echo "==> Granting permissions to eunomia_replicator"
sudo -u postgres psql -d "$PG_DB" -c "
  GRANT CONNECT ON DATABASE $PG_DB TO eunomia_replicator;
  GRANT USAGE ON SCHEMA public TO eunomia_replicator;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO eunomia_replicator;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO eunomia_replicator;
"

echo "==> Granting UPDATE(footage_state) on footage_reference"
sudo -u postgres psql -d "$PG_DB" -c "
  GRANT UPDATE (footage_state) ON footage_reference TO eunomia_replicator;
" 2>/dev/null || echo "    (footage_reference table may not exist yet — grant will be needed after migration)"

echo "==> Creating publication eunomia_hades (idempotent)"
sudo -u postgres psql -d "$PG_DB" -c "
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'eunomia_hades') THEN
      CREATE PUBLICATION eunomia_hades FOR ALL TABLES;
    END IF;
  END \$\$;
"

echo "==> Checking pg_hba.conf for Hades entry"
PG_HBA=$(sudo -u postgres psql -tAX -c "SHOW hba_file;")
if grep -q "$HADES_IP" "$PG_HBA" 2>/dev/null; then
  echo "    pg_hba.conf already has an entry for $HADES_IP"
else
  echo "    Adding replication entry for $HADES_IP to $PG_HBA"
  {
    echo ""
    echo "# Eunomia SYNC1: allow replication from Hades (Tailscale IP)"
    echo "hostssl replication eunomia_replicator ${HADES_IP}/32 scram-sha-256"
    echo "hostssl ${PG_DB}    eunomia_replicator ${HADES_IP}/32 scram-sha-256"
  } | sudo tee -a "$PG_HBA" > /dev/null
  echo "    Added. Postgres must be reloaded: sudo systemctl reload postgresql"
fi

cat <<EOF

================================================================================
Styx replication setup complete.

Next steps:
  1. Restart Postgres for wal_level change:
       sudo systemctl restart postgresql

  2. On Hades, create the replica database and subscription:
       See edge/sync/setup/setup-hades-subscription.sql

  3. Verify replication:
       sudo -u postgres psql -c "SELECT * FROM pg_replication_slots;"

Connection string for Hades:
  host=$HADES_IP port=5432 dbname=$PG_DB user=eunomia_replicator password=<pw> sslmode=require
================================================================================
EOF
