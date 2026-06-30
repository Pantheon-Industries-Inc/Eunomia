# `edge/sync/` — Styx→Hades transfer (Run SYNC1)

Two transfer channels ship data from Styx (Mexico collection site) to Hades (SF datacenter):

1. **Footage rsync** — bulk video/sidecar files pulled by Hades over Tailscale. Modeled on
   Victor's proven `pluto-sync/` pattern (atomic `.tmp-` landing, flock, self-healing).
2. **Postgres logical replication** — all S1 tables replicated to a read-only Hades database.
   The D1 ops dashboard on Hades reads from this replica via `EUNOMIA_STORE_DSN`.

## Architecture

```
Styx (Mexico, primary)                          Hades (SF, R730)
┌──────────────────────┐                       ┌──────────────────────┐
│  S1 Postgres         │◄── logical repl ────► │  eunomia_replica     │
│  /mnt/robot-pool/umi │◄── rsync (pull) ────► │  /mnt/robot-pool/    │
│                      │                       │    styx/umi/         │
│  P1/P3 consoles (rw) │                       │  D1 dashboard (ro)   │
└──────────────────────┘                       └──────────────────────┘
         Tailscale (WAN)
```

## File layout

```
edge/sync/
  bin/
    eunomia-sync-footage.sh      # main rsync script (flock + atomic + validation)
    eunomia-sweep-broken.sh      # hourly broken-episode sweep
    eunomia-sync-status.sh       # generate status.json (sync + replication health)
  setup/
    install-hades.sh             # idempotent installer for Hades
    setup-styx-replication.sh    # one-time Styx Postgres + SSH setup
    setup-hades-subscription.sql # SQL to create the Hades subscription
  systemd/
    eunomia-sync-footage.{service,timer}
    eunomia-sweep-broken.{service,timer}
    eunomia-sync-status.{service,timer}
  logrotate/
    eunomia-sync
  tests/
    test_sync_logic.py           # pure logic (no DB, no network)
    test_sync_db.py              # DB-backed (footage_state, event idempotency)
    conftest.py
```

## footage_reference lifecycle

The `footage_state` field on `footage_reference` tracks the byte lifecycle:

```
on_card → on_styx → shipped → on_hades → purged
                     ▲          ▲
                     │          │
              rsync starts   validated on Hades
```

Each transition is logged as an `operational_event` (`sync_state_transition`) for auditability.
Footage is safe to purge from Styx only once `on_hades` is verified (decision A-2).

## Rsync details

- **Pull model**: Hades SSH's to Styx over Tailscale (`pantheon@<styx-tailscale-ip>`).
- **Atomic landing**: rsync into `.tmp-<episode_id>/`, `mv` to final on success.
- **Bandwidth limit**: `SYNC1_BW_LIMIT_KBPS` (default 50000 = 50 Mbps). Adjust via env file.
- **Validation**: ffprobe completeness check on `.mp4`/`.insv` before promotion.
- **Self-healing**: failed episodes retry on next 5-minute cycle; broken sweep hourly.
- **Single-instance**: `flock` prevents overlapping runs (pluto-sync pattern).

## Postgres replication

Native Postgres 16 logical replication. `FOR ALL TABLES` publication auto-includes future tables.
The `session_replication_role = replica` setting on the apply worker automatically skips the
`eunomia_forbid_mutation()` audit triggers — no special handling needed.

### Schema migration procedure

When a new Alembic migration lands:
1. Run the migration on the Hades replica **first** (creates new table/column structure).
2. Run the migration on the Styx primary.
3. `FOR ALL TABLES` auto-includes new tables; new columns replicate transparently.

## One-time setup

### Prerequisites

- Tailscale connectivity between Styx and Hades.
- Postgres 16 on both hosts.
- `iperf3` measurement between hosts to calibrate `SYNC1_BW_LIMIT_KBPS` (~80% of measured).

### On Styx

```bash
sudo bash edge/sync/setup/setup-styx-replication.sh
```

This sets `wal_level = logical`, creates the `eunomia_replicator` role, creates the publication,
and configures `pg_hba.conf`. Requires a Postgres restart for the `wal_level` change.

### On Hades

```bash
# 1. Create the replica database and run migrations
createdb eunomia_replica
EUNOMIA_STORE_DSN="postgresql+psycopg://...@localhost/eunomia_replica" \
  alembic -c edge/store/alembic.ini upgrade head

# 2. Create the subscription
psql -d eunomia_replica -f edge/sync/setup/setup-hades-subscription.sql

# 3. Generate SSH key and install on Styx
ssh-keygen -t ed25519 -f /home/pluto/.ssh/eunomia_sync_ed25519 -N ""
ssh-copy-id -i /home/pluto/.ssh/eunomia_sync_ed25519.pub pantheon@<styx-tailscale-ip>

# 4. Create the env file with credentials
sudo mkdir -p /etc/eunomia-sync
sudo tee /etc/eunomia-sync/env <<'ENVEOF'
SYNC1_STYX_HOST=<styx-tailscale-ip>
SYNC1_STYX_USER=pantheon
SYNC1_SSH_KEY=/home/pluto/.ssh/eunomia_sync_ed25519
SYNC1_SOURCE_ROOT=/mnt/robot-pool/umi
SYNC1_DEST_ROOT=/mnt/robot-pool/styx/umi
SYNC1_BW_LIMIT_KBPS=50000
SYNC1_STYX_PG_DSN="host=<styx-tailscale-ip> port=5432 dbname=eunomia user=eunomia_replicator password=<pw>"
ENVEOF
sudo chmod 600 /etc/eunomia-sync/env
sudo chown pluto:pluto /etc/eunomia-sync/env

# 5. Install scripts + systemd units
sudo bash edge/sync/setup/install-hades.sh
```

### Verification

```bash
systemctl list-timers 'eunomia-*' --no-pager
tail -n 20 /var/log/eunomia-sync/footage.log
cat /var/log/eunomia-sync/status.json | python3 -m json.tool
```

## Security

- All connections over Tailscale — no port-forwarding.
- SSH key restricted to rsync user on Styx (`pantheon`).
- Postgres `eunomia_replicator` role: SCRAM-SHA-256, `pg_hba.conf` restricts to Hades Tailscale IP.
- Credentials in `/etc/eunomia-sync/env` (mode 0600) — never in the repo.

## Status monitoring

`eunomia-sync-status.sh` writes `/var/log/eunomia-sync/status.json` every 60s with:
- Footage sync: last run/success, pending/broken counts, throughput.
- Replication: subscription active, lag bytes, last update time.
- Styx reachable: SSH connectivity check.

The Hades storage-health dashboard (`check-health.sh`) can read this file to add a "Styx sync"
section — a one-line follow-up in the `hades-r730-dashboard` repo.

## Alerting thresholds (documented, not automated)

| Condition | Action |
|---|---|
| Replication lag > 10 min | Check Tailscale/Postgres connectivity |
| No successful footage sync > 1 hour | Check SSH key, disk space, Styx health |
| Broken episodes > 0 | Investigate `.broken/` contents |
