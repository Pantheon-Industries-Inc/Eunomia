"""No-DB tests for the V1 catalog tables (hardware_catalog, firmware_catalog, setup_version).

Verifies that the catalog table definitions compile to valid DDL and are registered
in schema.metadata. DB-backed CRUD tests require EUNOMIA_STORE_TEST_DSN.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from eunomia_edge_store import schema


def test_catalog_tables_in_metadata() -> None:
    names = set(schema.metadata.tables.keys())
    assert "hardware_catalog" in names
    assert "firmware_catalog" in names
    assert "setup_version" in names


def test_hardware_catalog_columns() -> None:
    t = schema.hardware_catalog
    col_names = {c.name for c in t.columns}
    assert col_names == {
        "catalog_id",
        "display_name",
        "category",
        "photo_url",
        "specs",
        "provisioning_steps",
        "created_at",
        "status",
    }
    assert t.c.catalog_id.primary_key
    assert not t.c.display_name.nullable
    assert not t.c.category.nullable


def test_firmware_catalog_columns() -> None:
    t = schema.firmware_catalog
    col_names = {c.name for c in t.columns}
    assert col_names == {
        "firmware_id",
        "hardware_catalog_id",
        "version",
        "changelog",
        "sidecar_schema_version",
        "binary_url",
        "released_at",
        "status",
    }
    assert t.c.firmware_id.primary_key
    assert not t.c.hardware_catalog_id.nullable
    assert len(t.foreign_keys) == 1


def test_setup_version_columns() -> None:
    t = schema.setup_version
    col_names = {c.name for c in t.columns}
    assert col_names == {
        "setup_id",
        "display_name",
        "components",
        "constraints",
        "contract",
        "released_at",
        "status",
    }
    assert t.c.setup_id.primary_key
    assert not t.c.components.nullable


def test_catalog_tables_tuple() -> None:
    assert schema.CATALOG_TABLES == (
        "hardware_catalog",
        "firmware_catalog",
        "setup_version",
    )


def test_catalog_tables_compile_ddl() -> None:
    pg = postgresql.dialect()
    for t in (schema.hardware_catalog, schema.firmware_catalog, schema.setup_version):
        CreateTable(t).compile(dialect=pg)


def test_firmware_catalog_fk_points_to_hardware_catalog() -> None:
    fk = next(iter(schema.firmware_catalog.foreign_keys))
    assert fk.column.table.name == "hardware_catalog"
    assert fk.column.name == "catalog_id"


def test_contract_derived_tables_have_new_indexes() -> None:
    hu_indexes = {
        tuple(c.name for c in ix.columns)
        for ix in schema.TABLES["hardware_unit"].indexes
    }
    assert ("hardware_catalog_id",) in hu_indexes

    kit_indexes = {
        tuple(c.name for c in ix.columns) for ix in schema.TABLES["kit"].indexes
    }
    assert ("setup_version_id",) in kit_indexes

    ep_indexes = {
        tuple(c.name for c in ix.columns) for ix in schema.TABLES["episode"].indexes
    }
    assert ("setup_version_id",) in ep_indexes


def test_contract_derived_tables_no_fks() -> None:
    for name in ("hardware_unit", "kit", "episode"):
        table = schema.TABLES[name]
        assert not table.foreign_keys, f"{name} should have no FKs (NOTE F6)"
