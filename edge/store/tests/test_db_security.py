"""DB-backed production-bar checks: least-privilege roles + grants (NOTE prod-bar b), the insert-only
audit trail (NOTE prod-bar c), and migration↔contract-derived-schema parity (the DB half of NOTE F8).
Skips without EUNOMIA_STORE_TEST_DSN."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from eunomia_edge_store import schema, store

pytestmark = pytest.mark.db

ROLES = ("eunomia_writer", "eunomia_reader", "eunomia_admin")


def test_least_privilege_roles_exist_and_are_nologin(engine: Engine) -> None:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'eunomia_%'"
            )
        ).all()
    rows: dict[str, bool] = {name: can_login for name, can_login in result}
    assert set(ROLES) <= set(rows)
    # NOLOGIN group roles — nothing connects as them directly; no superuser path (prod-bar b).
    for role in ROLES:
        assert rows[role] is False


def _has(conn: sa.Connection, role: str, priv: str, table: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT has_table_privilege(:r, :t, :p)"),
            {"r": role, "t": table, "p": priv},
        ).scalar_one()
    )


def test_grants_are_least_privilege(engine: Engine) -> None:
    with engine.connect() as conn:
        # writer: insert/update current-state, but never DELETE (the contract voids by flag).
        assert _has(conn, "eunomia_writer", "INSERT", "person")
        assert _has(conn, "eunomia_writer", "UPDATE", "person")
        assert not _has(conn, "eunomia_writer", "DELETE", "person")
        # writer on the audit log: INSERT only — no UPDATE/DELETE (insert-only, prod-bar c).
        assert _has(conn, "eunomia_writer", "INSERT", "operational_event")
        assert not _has(conn, "eunomia_writer", "UPDATE", "operational_event")
        assert not _has(conn, "eunomia_writer", "DELETE", "operational_event")
        # reader: select-only.
        assert _has(conn, "eunomia_reader", "SELECT", "person")
        assert not _has(conn, "eunomia_reader", "INSERT", "person")
        assert not _has(conn, "eunomia_reader", "UPDATE", "person")


def _seed_audit_row(conn: sa.Connection, table: str) -> None:
    """Insert one row using the GIVEN connection (no commit of its own) so the mutation that follows
    in the same transaction can be aborted by the trigger — leaving nothing committed (test isolation).
    """
    if table == "operational_event":
        store.append_event(
            conn,
            {
                "schema": "eunomia-operational-event/v1",
                "event_id": "evt-audit",
                "event_type": "station_registered",
                "entity": "station",
                "entity_id": "1000",
            },
        )
    elif table == "camera_id_ledger":
        conn.execute(
            schema.camera_id_ledger.insert().values(
                camera_id="CAM-audit", body_serial="BS"
            )
        )
    elif table == "import_backup":
        conn.execute(
            schema.import_backup.insert().values(
                import_run_id="r",
                entity="station",
                natural_key={"x": 1},
                action="created",
            )
        )


# A settable column per audit table (the trigger fires on any UPDATE; this just makes a valid SET).
_UPDATE_COL = {
    "operational_event": "reason",
    "camera_id_ledger": "allocated_by",
    "import_backup": "import_run_id",
}


@pytest.mark.parametrize("table", schema.AUDIT_TABLES)
def test_audit_tables_reject_update_and_delete(engine: Engine, table: str) -> None:
    t = schema.metadata.tables[table]
    # Seed + mutate in ONE transaction: the BEFORE UPDATE/DELETE trigger RAISES and aborts the whole
    # transaction, so the seed row never commits (no cross-test pollution).
    with pytest.raises(sa.exc.DBAPIError):
        with engine.begin() as conn:
            _seed_audit_row(conn, table)
            conn.execute(sa.update(t).values(**{_UPDATE_COL[table]: "x"}))
    with pytest.raises(sa.exc.DBAPIError):
        with engine.begin() as conn:
            _seed_audit_row(conn, table)
            conn.execute(sa.delete(t))


def test_migration_matches_contract_derived_schema(engine: Engine) -> None:
    insp = inspect(engine)
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    expected = set(schema.metadata.tables)
    assert db_tables == expected, f"migration drift: {db_tables ^ expected}"
    for name in expected:
        meta_table = schema.metadata.tables[name]
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        assert set(db_cols) == {c.name for c in meta_table.columns}, f"{name} columns"
        for col in meta_table.columns:
            assert db_cols[col.name]["nullable"] is col.nullable, (
                f"{name}.{col.name} nullability"
            )
        db_pk = set(insp.get_pk_constraint(name)["constrained_columns"])
        meta_pk = {c.name for c in meta_table.primary_key.columns}
        assert db_pk == meta_pk, f"{name} primary key"
