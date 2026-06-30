-- Eunomia SYNC1: create the logical replication subscription on Hades.
--
-- Prerequisites:
--   1. Database 'eunomia_replica' exists on Hades:
--        createdb eunomia_replica
--   2. Alembic migrations have been run on eunomia_replica:
--        EUNOMIA_STORE_DSN="postgresql+psycopg://...@localhost/eunomia_replica" \
--          alembic -c edge/store/alembic.ini upgrade head
--   3. The publication 'eunomia_hades' exists on Styx:
--        Run setup-styx-replication.sh on Styx first.
--
-- Usage:
--   psql -d eunomia_replica -f setup-hades-subscription.sql
--
-- Idempotent: IF NOT EXISTS guard on the subscription.
--
-- NOTE: Update the CONNECTION string below with the actual Styx host, password,
-- and sslmode before running.

-- The subscription. copy_data = true does the initial bulk copy of all rows.
-- The apply worker runs with session_replication_role = 'replica', which
-- automatically skips user-defined triggers (the eunomia_forbid_mutation
-- audit triggers from rev_0001).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_subscription WHERE subname = 'eunomia_styx_sub'
  ) THEN
    -- Replace <styx-tailscale-ip> and <password> before running.
    CREATE SUBSCRIPTION eunomia_styx_sub
      CONNECTION 'host=<styx-tailscale-ip> port=5432 dbname=eunomia user=eunomia_replicator password=<password> sslmode=require'
      PUBLICATION eunomia_hades
      WITH (
        copy_data = true,
        create_slot = true,
        slot_name = 'eunomia_hades_slot'
      );
    RAISE NOTICE 'Subscription eunomia_styx_sub created.';
  ELSE
    RAISE NOTICE 'Subscription eunomia_styx_sub already exists.';
  END IF;
END $$;

-- Verify:
-- SELECT * FROM pg_stat_subscription WHERE subname = 'eunomia_styx_sub';
-- SELECT * FROM pg_subscription_rel;
