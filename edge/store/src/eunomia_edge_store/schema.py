"""The store schema — one ``MetaData`` assembled from the contract (NOTE F8) + the store-native
audit tables.

- 11 **current-state** tables, columns derived from ``eunomia_contracts`` (``contract_tables``).
  Primary keys are the store-native natural keys; ``task`` and ``station`` are composite (NOTE F4).
  Reference columns are INDEXED but never FK'd (NOTE F6) — the resolver flags dangling refs loudly.
- ``operational_event`` — the polymorphic, append-only event log (open string ``event_type``, **no
  CHECK**); also derived from the contract.
- ``camera_id_ledger`` + ``import_backup`` — store-native audit tables (not contract entities).

All three audit tables are INSERT-ONLY (NOTE prod-bar c) — enforced at migration time by role grants
+ a ``BEFORE UPDATE OR DELETE`` trigger; the schema here just records which tables they are.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from eunomia_contracts import (
    calibration,
    capture_stack,
    episode,
    footage_reference,
    hardware_unit,
    kit,
    operational_event,
    person,
    session,
    station,
    task,
    task_station_assignment,
)
from eunomia_edge_store import contract_tables

metadata = sa.MetaData()


@dataclass(frozen=True)
class EntitySpec:
    """A contract entity → table: the module to derive from, its PK, and the columns to index."""

    module: Any  # an eunomia_contracts.<entity> module (carries _TABLES + SCHEMA_ID)
    table_name: str
    primary_key: tuple[str, ...]
    force_not_null: frozenset[str] = frozenset()
    indexes: tuple[tuple[str, ...], ...] = ()


# Reference columns are indexed (NOTE F6) but NOT foreign-keyed: the as-of grain + out-of-order
# arrival break simple FKs; the resolver enforces and flags dangling refs loudly instead.
ENTITIES: tuple[EntitySpec, ...] = (
    EntitySpec(person, "person", ("person_id",)),
    EntitySpec(
        hardware_unit,
        "hardware_unit",
        ("unit_id",),
        indexes=(
            ("kit_id",),
            ("camera_id",),
            ("fob_id",),
            ("body_serial",),
            ("hardware_catalog_id",),
        ),
    ),
    EntitySpec(
        kit,
        "kit",
        ("kit_id",),
        indexes=(
            ("left_cam_unit_id",),
            ("right_cam_unit_id",),
            ("fob_unit_id",),
            ("setup_version_id",),
        ),
    ),
    EntitySpec(
        calibration, "calibration", ("calibration_id",), indexes=(("camera_serial",),)
    ),
    # Composite natural key, store-stricter than the wire: version + rotation_id are WARN on the wire
    # but NOT NULL here (NOTE F4); the episode's task pin references this triple.
    EntitySpec(
        task,
        "task",
        ("task_id", "version", "rotation_id"),
        force_not_null=frozenset({"version", "rotation_id"}),
    ),
    EntitySpec(
        session,
        "session",
        ("session_id",),
        indexes=(("person_id",), ("kit_id",), ("station_id",), ("task_id",)),
    ),
    EntitySpec(
        capture_stack,
        "capture_stack",
        ("capture_stack_id",),
        indexes=(("kit_id",), ("kit_id", "effective_from")),
    ),
    EntitySpec(footage_reference, "footage_reference", ("episode_id",)),
    EntitySpec(
        episode,
        "episode",
        ("episode_id",),
        indexes=(
            ("kit_id",),
            ("session_id",),
            ("person_id",),
            ("station_id",),
            ("calibration_id",),
            ("capture_stack_id",),
            ("task_id", "task_version", "rotation_id"),
            ("setup_version_id",),
        ),
    ),
    EntitySpec(station, "station", ("site_id", "station_id")),
    EntitySpec(
        task_station_assignment,
        "task_station_assignment",
        ("assignment_id",),
        # the as-of resolution index: (site_id, station_id, effective_from)
        indexes=(("site_id", "station_id", "effective_from"), ("task_id",)),
    ),
    # The append-only event log (contract entity). Open string event_type, NO CHECK constraint.
    EntitySpec(
        operational_event,
        "operational_event",
        ("event_id",),
        indexes=(
            ("entity", "entity_id"),
            ("event_type",),
            ("related_unit_id",),
            ("related_kit_id",),
            ("as_of",),
        ),
    ),
)

#: The contract entities the store persists (current-state + the event log) — the coverage drift test
#: asserts every operational + operational_event contract module appears here.
ENTITY_MODULES: tuple[Any, ...] = tuple(spec.module for spec in ENTITIES)


def _ix_name(table: str, cols: tuple[str, ...]) -> str:
    """Deterministic, <=63-char index name (Postgres identifier limit)."""
    base = f"ix_{table}_{'_'.join(cols)}"
    if len(base) <= 63:
        return base
    digest = hashlib.sha1("_".join(cols).encode()).hexdigest()[:8]  # noqa: S324 (name only)
    return f"ix_{table}_{digest}"


def _build_entity(spec: EntitySpec) -> sa.Table:
    cols = contract_tables.build_columns(
        spec.module._TABLES,
        primary_key=spec.primary_key,
        force_not_null=spec.force_not_null,
    )
    table = sa.Table(spec.table_name, metadata, *cols)
    for icols in spec.indexes:
        sa.Index(_ix_name(spec.table_name, icols), *(table.c[c] for c in icols))
    return table


#: name -> derived current-state / event-log Table.
TABLES: dict[str, sa.Table] = {
    spec.table_name: _build_entity(spec) for spec in ENTITIES
}

# ---- store-native audit tables (NOT contract entities; legitimately hand-defined) ----

#: The Postgres sequence backing camera_id allocation (NOTE F7) — monotonic, so a retired id is never
#: reissued (retire-not-reuse) even though the ledger only ever records mints.
camera_id_seq = sa.Sequence("camera_id_seq", metadata=metadata)

#: Insert-only ledger of every allocated camera_id (the allocator's source of truth). Retirement is an
#: operational_event + the unit's status=retired — the ledger itself is never mutated (NOTE prod-bar c).
camera_id_ledger = sa.Table(
    "camera_id_ledger",
    metadata,
    sa.Column("ledger_id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("camera_id", sa.Text, nullable=False, unique=True),
    sa.Column("body_serial", sa.Text, nullable=True),
    sa.Column("seq_value", sa.BigInteger, nullable=True),
    sa.Column(
        "allocated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("allocated_by", sa.Text, nullable=True),
    sa.Index("ix_camera_id_ledger_body_serial", "body_serial"),
)

#: Insert-only before-image backups written by the non-destructive importer (NOTE F1) — the
#: camera_map-incident lesson, recorded so a merge is never a silent destructive overwrite.
import_backup = sa.Table(
    "import_backup",
    metadata,
    sa.Column("backup_id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("import_run_id", sa.Text, nullable=False),
    sa.Column("entity", sa.Text, nullable=False),
    sa.Column("natural_key", JSONB, nullable=False),
    sa.Column(
        "before_image", JSONB, nullable=True
    ),  # null = the row was new (no prior image)
    sa.Column("drift", JSONB, nullable=True),
    sa.Column("action", sa.Text, nullable=False),  # created | updated | unchanged
    sa.Column(
        "backed_up_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_import_backup_run", "import_run_id"),
)

#: The insert-only audit tables (NOTE prod-bar c): no UPDATE/DELETE path — enforced by grants + trigger.
AUDIT_TABLES: tuple[str, ...] = (
    "operational_event",
    "camera_id_ledger",
    "import_backup",
)

#: The current-state tables the writer role may insert/update (everything except the audit tables).
CURRENT_STATE_TABLES: tuple[str, ...] = tuple(
    name for name in TABLES if name not in AUDIT_TABLES
)

# ---- store-native supervisor tables (Run P3 — NOT contract entities, mutable) ----

#: Postgres sequence for permanent numeric task IDs (retire-not-reuse, like camera_id_seq).
task_catalog_seq = sa.Sequence("task_catalog_seq", metadata=metadata)

#: Per-operator weekly task assignments. Mutable (status flips active→removed).
operator_task_assignment = sa.Table(
    "operator_task_assignment",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
    sa.Column("person_id", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column(
        "assigned_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("assigned_by", sa.Text, nullable=False),
    sa.Column("week_of", sa.Date, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
    sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint(
        "person_id", "task_id", "week_of", name="uq_ota_person_task_week"
    ),
)
sa.Index(
    "ix_ota_person_week",
    operator_task_assignment.c.person_id,
    operator_task_assignment.c.week_of,
)
sa.Index("ix_ota_task", operator_task_assignment.c.task_id)

#: Research-team hour targets per task per period.
collection_target = sa.Table(
    "collection_target",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column("target_hours", sa.Double, nullable=False),
    sa.Column("period", sa.Text, nullable=False),
    sa.Column("created_by", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("task_id", "period", name="uq_ct_task_period"),
)
sa.Index("ix_ct_task", collection_target.c.task_id)
sa.Index("ix_ct_period", collection_target.c.period)

#: The P3 supervisor tables (mutable, not audit — writer gets full SELECT/INSERT/UPDATE).
SUPERVISOR_TABLES: tuple[str, ...] = (
    "operator_task_assignment",
    "collection_target",
)

# ---- store-native catalog tables (Run V1 — NOT contract entities, mutable) ----

#: Registry of hardware TYPES (not instances). Admin-managed via /admin/hardware.
hardware_catalog = sa.Table(
    "hardware_catalog",
    metadata,
    sa.Column("catalog_id", sa.Text, primary_key=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("category", sa.Text, nullable=False),
    sa.Column("photo_url", sa.Text, nullable=True),
    sa.Column("specs", JSONB, nullable=True),
    sa.Column("provisioning_steps", JSONB, nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
)
sa.Index("ix_hc_category", hardware_catalog.c.category)
sa.Index("ix_hc_status", hardware_catalog.c.status)

#: Registry of firmware VERSIONS. FK to hardware_catalog (both admin-managed, controlled creation
#: order — real FK is safe here unlike contract-derived tables subject to NOTE F6).
firmware_catalog = sa.Table(
    "firmware_catalog",
    metadata,
    sa.Column("firmware_id", sa.Text, primary_key=True),
    sa.Column(
        "hardware_catalog_id",
        sa.Text,
        sa.ForeignKey("hardware_catalog.catalog_id"),
        nullable=False,
    ),
    sa.Column("version", sa.Text, nullable=False),
    sa.Column("changelog", sa.Text, nullable=True),
    sa.Column("sidecar_schema_version", sa.Text, nullable=True),
    sa.Column("binary_url", sa.Text, nullable=True),
    sa.Column(
        "released_at",
        sa.DateTime(timezone=True),
        nullable=True,
        server_default=sa.func.now(),
    ),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'testing'")),
)
sa.Index("ix_fc_hardware", firmware_catalog.c.hardware_catalog_id)
sa.Index("ix_fc_status", firmware_catalog.c.status)

#: Registry of kit CONFIGURATIONS (setup versions). Admin-managed via /admin/setups.
setup_version = sa.Table(
    "setup_version",
    metadata,
    sa.Column("setup_id", sa.Text, primary_key=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("components", JSONB, nullable=False),
    sa.Column("constraints", JSONB, nullable=True),
    sa.Column("contract", JSONB, nullable=True),
    sa.Column(
        "released_at",
        sa.DateTime(timezone=True),
        nullable=True,
        server_default=sa.func.now(),
    ),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'testing'")),
)
sa.Index("ix_sv_status", setup_version.c.status)

#: The V1 catalog tables (mutable, not audit — writer gets SELECT/INSERT/UPDATE, no DELETE).
CATALOG_TABLES: tuple[str, ...] = (
    "hardware_catalog",
    "firmware_catalog",
    "setup_version",
)
