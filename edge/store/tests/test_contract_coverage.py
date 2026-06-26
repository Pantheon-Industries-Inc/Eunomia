"""No-DB drift guard: the store schema is DERIVED from the contract and stays in lockstep (NOTE F8).

Runs in the default `make gates` (no database needed). It asserts (a) every contract entity the store
must persist has a table — a NEW operational entity with no table fails here; (b) every contract field
becomes a column with the right type + store-stricter nullability (NOTE F4/F5); (c) every table
compiles to valid PostgreSQL DDL. The live migration↔schema equality is the DB-backed half
(test_db_security.py).
"""

from __future__ import annotations

from types import ModuleType

import eunomia_contracts as ec
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable

from eunomia_edge_store import contract_tables, schema

# Contract entity modules the edge store does NOT persist (firmware card / ingest output / telemetry /
# sync). Everything else under eunomia_contracts is operational + must map to a store table.
NON_STORE_ENTITIES = frozenset({"sidecar", "release", "telemetry_event", "sync_delta"})


def _contract_entity_modules() -> dict[str, ModuleType]:
    mods: dict[str, ModuleType] = {}
    for name in ec.__all__:
        obj = getattr(ec, name)
        if isinstance(obj, ModuleType) and hasattr(obj, "_TABLES"):
            mods[name] = obj
    return mods


def test_store_persists_exactly_the_operational_entities() -> None:
    expected = set(_contract_entity_modules()) - NON_STORE_ENTITIES
    assert set(schema.TABLES) == expected, (
        "store tables drifted from the contract operational entities "
        f"(missing {expected - set(schema.TABLES)}, extra {set(schema.TABLES) - expected})"
    )


def test_audit_tables_are_separate_from_current_state() -> None:
    assert "operational_event" in schema.AUDIT_TABLES
    assert set(schema.AUDIT_TABLES).isdisjoint(schema.CURRENT_STATE_TABLES)
    # camera_id_ledger + import_backup are store-native (not contract entities, not current-state).
    assert {"camera_id_ledger", "import_backup"} <= set(schema.AUDIT_TABLES)


@pytest.mark.parametrize("spec", schema.ENTITIES, ids=lambda s: s.table_name)
def test_every_contract_field_is_a_column_with_derived_type(
    spec: schema.EntitySpec,
) -> None:
    table = schema.TABLES[spec.table_name]
    pk = set(spec.primary_key)
    for fs in contract_tables.top_level_fields(spec.module._TABLES):
        assert fs.name in table.c, f"{spec.table_name}.{fs.name} missing"
        col = table.c[fs.name]
        # store-stricter nullability (NOTE F4): hard | pk | force-not-null -> NOT NULL.
        expect_not_null = fs.hard or fs.name in pk or fs.name in spec.force_not_null
        assert col.nullable is (not expect_not_null), (
            f"{spec.table_name}.{fs.name} nullability"
        )
        _assert_type(spec.table_name, fs.name, fs.json_type, col)


def _assert_type(table: str, name: str, json_type: str, col: sa.Column) -> None:
    where = f"{table}.{name}"
    if json_type == "string":
        if contract_tables.is_timestamp_field(name):
            assert isinstance(col.type, sa.DateTime) and col.type.timezone, (
                f"{where} timestamptz"
            )
        else:
            assert isinstance(col.type, sa.Text), f"{where} Text"
    elif json_type == "int":
        assert isinstance(col.type, sa.BigInteger), f"{where} BigInteger"
    elif json_type == "number":
        assert isinstance(col.type, sa.Double), f"{where} Double"
    elif json_type == "bool":
        assert isinstance(col.type, sa.Boolean), f"{where} Boolean"
    elif json_type in ("object", "array"):
        assert isinstance(col.type, JSONB), f"{where} JSONB"
    else:  # pragma: no cover - defensive
        pytest.fail(f"{where}: unmapped contract type {json_type!r}")


def test_composite_keys_are_store_stricter() -> None:
    # task: (task_id, version, rotation_id), all NOT NULL though version/rotation_id are WARN (NOTE F4).
    task = schema.TABLES["task"]
    assert {c.name for c in task.primary_key.columns} == {
        "task_id",
        "version",
        "rotation_id",
    }
    assert task.c.version.nullable is False
    assert task.c.rotation_id.nullable is False
    # station: composite (site_id, station_id).
    station = schema.TABLES["station"]
    assert {c.name for c in station.primary_key.columns} == {"site_id", "station_id"}


def test_episode_task_pin_is_indexed_not_fkd() -> None:
    episode = schema.TABLES["episode"]
    indexed = {tuple(c.name for c in ix.columns) for ix in episode.indexes}
    assert ("task_id", "task_version", "rotation_id") in indexed
    # NOTE F6: no hard foreign keys anywhere in the store.
    for table in schema.TABLES.values():
        assert not table.foreign_keys, (
            f"{table.name} has a foreign key (NOTE F6 forbids hard FKs)"
        )


def test_event_log_has_no_check_constraint() -> None:
    # The polymorphic event table: open string event_type, NO CHECK (the contract WARN-set is the
    # only soft guard).
    event = schema.TABLES["operational_event"]
    checks = [c for c in event.constraints if isinstance(c, sa.CheckConstraint)]
    assert not checks


def test_all_tables_compile_to_postgresql_ddl() -> None:
    pg = postgresql.dialect()
    for table in (
        *schema.TABLES.values(),
        schema.camera_id_ledger,
        schema.import_backup,
    ):
        CreateTable(table).compile(dialect=pg)
