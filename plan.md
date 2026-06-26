# Run S1 — `edge/store/`: the contract-derived operational store (plan-of-record)

Reconstructed from Mo's `NOTE:` annotations on the S1 plan (F1–F9 + the production-bar split). Builds
the first real code under `edge/store/`: a Postgres-backed operational store that persists the
`contracts/operational/` model as **current-state records + an append-only event log**. `contracts/`
is **untouched** (read-only consumer): `contracts/_generated/` is byte-identical and the cpp targets
are unchanged.

## What S1 is (and is NOT)

- **IS:** the store layer — schema (tables **derived from the contract**), migrations (Alembic), a
  thin store API (upsert current-state + append events), the camera_id allocator, the as-of resolvers,
  and the documented-shape registry importer. Topology-agnostic (a Postgres reachable by DSN).
- **IS NOT (F9):** no event-fold / materializer (folding events → views is a later run). S1 stores the
  current-state rows AND the append-only event log; it does not reconstruct views from events.
- **IS NOT (F3):** no edge-authoritative assumption, no replication, no release-contract logic. The
  store is built TOPOLOGY-AGNOSTIC — works edge OR central; the **DSN/env config is the only seam**.
  (MODULE_MAP calls `edge/` "edge-authoritative"; S1 deliberately does not bake that in.)
- **IS NOT (edge/api, edge/sync):** still README-only skeletons (their own future runs).

## Decisions folded from the NOTEs

| NOTE | Decision in S1 |
|---|---|
| **F2** | SQLAlchemy 2.0 **Core** (not ORM) + **psycopg3** + **Alembic**. Pin alignment with Polis is optional (separate repo) — not a blocker. |
| **F8** | Tables are **derived from the contract** at import (`eunomia_contracts._TABLES` + dataclasses), never hand-written. A **drift test** catches contract↔store divergence. |
| **F9** | Current-state records + append-only event log only. No materializer. |
| **F4** | Composite natural-key PKs, **store stricter than the wire**: `task` PK `(task_id, version, rotation_id)` NOT NULL; `station` PK `(site_id, station_id)`. The episode's task pin `(task_id, task_version, rotation_id)` references this composite (no hard FK — index + resolver, F6). |
| **F5** | Timestamp-named fields → `timestamptz` columns; **ISO-normalize on read**; the smoke test compares **parsed instants**, not strings. |
| **F6** | **No hard FKs** (as-of grain + out-of-order arrival break simple FKs). BUT **indexes on every reference column**, and the **resolver FLAGS dangling references loudly** (a reference to a missing kit/task/station is surfaced, never a silent orphan). The store writes don't reject; the resolver enforces. |
| **F1** | **Documented-shape importer** + committed **synthetic fixture** now (real `fleet.yaml`/`stations.yaml` are moved/absent — built against the documented shape until the live location is confirmed). **Non-destructive merge** (drift-detect + backup), never a destructive overwrite (the camera_map-incident lesson). |
| **F7** | camera_id format is a **single swappable constant** (`CAM-<n>` placeholder until the fleet's real convention is confirmed). The importer **preserves existing camera_ids verbatim**; only unallocated cameras get a minted id. |
| **F3** | Topology-agnostic core; DSN/env seam (see above). |
| **prod-bar (a)** | **TLS-capable** connections — psycopg3 `sslmode` is plumbed through the DSN/config (the layer supports encrypted connections; cert + enforcement is deploy). |
| **prod-bar (b)** | **Least-privilege roles + grants in the migration**: `eunomia_writer` (consoles — insert/update + allocate), `eunomia_reader` (ingest / god's-view — select-only), `eunomia_admin` (DDL/migrations). NOLOGIN group roles; nothing connects as superuser. |
| **prod-bar (c)** | The **audit trail is strictly insert-only**: the append-only operational-event log, the camera_id ledger, and the import-backup table have **no update/delete path** — enforced by role grants AND a `BEFORE UPDATE OR DELETE` trigger that RAISES. |
| **rest** | entity→table mapping; polymorphic event table (**open string `event_type`, NO CHECK**); allocator (**sequence + ledger + retire-not-reuse**); as-of resolvers + indexes; smoke test + `gates-db` + CI postgres service; `contracts/_generated`-untouched + cpp-unchanged verification. |

**Flagged to INFRA / Thomaz (NOT built in S1):** immutable + off-site (WORM) backups; tailnet
segmentation / ACLs so the store is not reachable by the whole flat Tailscale network; at-rest / disk
encryption. (prod-bar INFRA half.)

## Layout — a new uv workspace member `edge/store/` (`eunomia_edge_store`)

Mirrors `tooling/bench-harness` (src-layout, its own `pyproject.toml`). `edge/api/` + `edge/sync/`
stay README-only.

```
edge/store/
  pyproject.toml                     # eunomia-edge-store; deps: eunomia-contracts, SQLAlchemy, psycopg, alembic
  README.md                          # expanded from the 0a skeleton
  alembic.ini
  src/eunomia_edge_store/
    __init__.py
    config.py            # StoreConfig: DSN from env (EUNOMIA_STORE_DSN) + sslmode — the topology seam (F3, prod-bar a)
    engine.py            # SQLAlchemy Engine factory (psycopg3 driver, sslmode pass-through)
    timestamps.py        # ISO parse / normalize helpers — tz-correct (F5)
    contract_tables.py   # derive a Core Table from a contract entity module (F8)
    schema.py            # the MetaData: 11 current-state tables + operational_event log + camera_id ledger + import_backup
    store.py             # upsert current-state; append-only events; ISO-normalize on read (F5)
    allocator.py         # camera_id allocator: PG sequence + insert-only ledger + retire-not-reuse (F7)
    resolvers.py         # as-of resolvers (task→station, capture_stack) + loud dangling-ref flagging (F6)
    importer.py          # documented-shape registry → non-destructive merge + drift-detect + backup (F1, F7)
  migrations/env.py, migrations/versions/0001_*.py   # create_all(derived) + roles/grants + audit triggers + camera_id_seq
  fixtures/fleet.synthetic.json      # synthetic fleet/station registry (documented shape) (F1)
  tests/                             # no-DB derivation/coverage + DB-backed (skip if no DSN) smoke/drift/allocator/resolver/importer
```

## Entity → table mapping

Current-state tables (PK = the store-native natural key; NOT NULL = contract-hard OR part-of-PK):

| table | PK | notes |
|---|---|---|
| person | `person_id` | |
| hardware_unit | `unit_id` | `camera_id` preserved verbatim by the importer; allocator mints only when absent |
| kit | `kit_id` | current binding; history via events |
| calibration | `calibration_id` | |
| task | `(task_id, version, rotation_id)` | **store-stricter**: version/rotation_id NOT NULL though warn on the wire (F4) |
| session | `session_id` | |
| capture_stack | `capture_stack_id` | |
| footage_reference | `episode_id` | one footage state per episode |
| episode | `episode_id` | task pin `(task_id, task_version, rotation_id)` indexed, resolved not FK'd (F6) |
| station | `(site_id, station_id)` | composite; retire-not-reuse via `retired_at`/`status` |
| task_station_assignment | `assignment_id` | append-only; resolution `(site_id, station_id, ts)` → `[effective_from, effective_to)` |

Store-native (not contract current-state) — **append-only, insert-only audit**:

| table | role |
|---|---|
| operational_event | the polymorphic event log — open string `event_type`, **NO CHECK** (the contract WARN-set is the only soft guard) |
| camera_id_ledger | the allocator's ledger (every mint + retire); fed by `camera_id_seq` |
| import_backup | the importer's before-image backups (the non-destructive-merge audit) |

Column types (derived): string→`Text`; timestamp-named (`*_at`, `effective_from`, `effective_to`,
`as_of`)→`DateTime(timezone=True)`; int→`BigInteger`; number→`Double`; bool→`Boolean`;
object/array→`JSONB`.

## Derive-from-contract + drift (F8)

`contract_tables.build_table(entity_module)` reads the module's `_TABLES` (hard/warn/nullable/enum)
and dataclass to emit a Core `Table`. The runtime tables are therefore always in lockstep with the
contract. Two guards:

- **No-DB (default `pytest`):** every operational + `operational_event` contract entity maps to a
  table; every contract field is a column with the right type/nullability; the PK store-stricter
  overrides are consistent; **every table compiles to valid PostgreSQL DDL** (`CreateTable` against the
  pg dialect — no DB needed).
- **DB-backed (`gates-db`):** after `alembic upgrade head`, the live schema equals the contract-derived
  metadata; the three roles, their grants, and the audit triggers exist.

## Gates

- **Default `make gates` is unchanged** and must stay green with **no database**: DB-backed tests carry
  a `db` marker and `skipif` on a missing `EUNOMIA_STORE_TEST_DSN`. New deps land in the lockfile; the
  five Python gates + drift run over `edge/store/` too.
- **New `make gates-db`:** spins a throwaway docker Postgres (loud-skip if docker is absent, like
  `clang-tidy`), runs `alembic upgrade head` + `pytest -m db`. CI adds a parallel job with a
  `services: postgres` container.
- **Untouched:** `make drift` is clean and `git diff contracts/_generated` + the cpp targets are empty
  (S1 only READS the contract).

## Open questions (flagged, not silently decided)

1. **Member granularity / package name.** S1 makes `edge/store/` its own member `eunomia_edge_store`
   (matches the `tooling/bench-harness` leaf-is-the-member pattern; keeps S1 scoped; avoids the
   `eunomia_store` ↔ Hermes-store ambiguity MODULE_MAP warns about). The alternative — one `eunomia_edge`
   package with `store/`/`api/`/`sync/` subpackages — would make a future `api → store` call an
   intra-package import (no import-linter friction). Deferred to when `edge/api/` lands; reversible.
2. **camera_id format (F7).** `CAM-<n>` is a placeholder in a single swappable constant until the
   fleet's real convention is confirmed. The importer preserves existing ids verbatim regardless.
3. **Live registry location (F1).** Built against the documented shape + the committed synthetic
   fixture; swap the importer's source path once the current `fleet`/`stations` registry location is
   confirmed.
