# `edge/store/`

The operational store — persists the `contracts/operational/` model as **current-state records + an
append-only event log**. The consoles write through it; it is the live system of record on the ground.
Built in **Run S1**.

**Single responsibility:** persist + serve the operational model. No event-fold / materializer (a later
run), no replication (that is `edge/sync/`), no console/process logic (that is `edge/api/`).

**Dependency rule:** depends only on `contracts/`. The tables are **derived** from `eunomia_contracts`
(never hand-written) so the contract stays the single source of truth; a drift test catches divergence.

**Topology-agnostic (NOTE F3):** a Postgres reachable by **DSN** — works edge OR central. The DSN/env
config (`EUNOMIA_STORE_DSN`) is the only seam; there is no baked-in edge-authoritative assumption and
no replication/release logic here.

## Shape

| Module | Responsibility |
|---|---|
| `config.py` / `engine.py` | DSN/env config (the topology seam) + the SQLAlchemy Engine factory. `sslmode` is plumbed through (TLS-capable; cert + enforcement is deploy). |
| `contract_tables.py` / `schema.py` | derive a Core `Table` per contract entity (NOTE F8); assemble the `MetaData` (11 current-state tables + the operational-event log + the camera_id ledger + the import-backup table). |
| `timestamps.py` | ISO-8601 parse / normalize — timezone-correct; timestamp fields are `timestamptz` and compared as parsed instants (NOTE F5). |
| `store.py` | upsert current-state rows; append operational events (insert-only). |
| `allocator.py` | the camera_id allocator — a Postgres sequence + an insert-only ledger + **retire-not-reuse**. The id format is a single swappable constant (NOTE F7). |
| `resolvers.py` | as-of resolution (task→station assignment, capture_stack) + **loud dangling-reference flagging** — no hard FKs, but a reference to a missing kit/task/station is surfaced, never a silent orphan (NOTE F6). |
| `importer.py` | the documented-shape registry importer — a **non-destructive merge** (drift-detect + backup), never a destructive overwrite (the camera_map-incident lesson, NOTE F1). Existing camera_ids are preserved verbatim. |
| `migrations/` | Alembic. `0001` creates the derived tables + the least-privilege roles/grants (NOTE prod-bar b) + the insert-only audit triggers (NOTE prod-bar c) + the camera_id sequence. |

## Security posture (NOTE prod-bar)

Built in S1: TLS-capable connections (`sslmode`); least-privilege roles (`eunomia_writer` /
`eunomia_reader` / `eunomia_admin`, NOLOGIN group roles — nothing connects as superuser); an
insert-only audit trail (the event log, the camera_id ledger, the import-backup table).
Flagged to infra (NOT built here): immutable + off-site backups, tailnet segmentation/ACLs, at-rest
encryption.

## Running the DB-backed gates

The default `make gates` needs **no database** (the DB-backed tests skip without
`EUNOMIA_STORE_TEST_DSN`). To run them:

```sh
make gates-db          # spins a throwaway docker Postgres (loud-skip if docker is absent)
# or, against an existing DB:
EUNOMIA_STORE_TEST_DSN=postgresql+psycopg://user:pass@host:5432/eunomia_test uv run pytest edge/store -m db
```
