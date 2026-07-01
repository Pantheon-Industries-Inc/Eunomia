"""Admin catalog queries — CRUD for hardware_catalog, firmware_catalog, setup_version.

All queries take a SQLAlchemy Connection and return plain dicts/lists. Unlike the ops queries
(read-only), these include write operations (insert, update).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in result.mappings().all()]


# ---------------------------------------------------------------------------
# hardware_catalog
# ---------------------------------------------------------------------------


def list_hardware(
    conn: Connection, *, status: str | None = None
) -> list[dict[str, Any]]:
    t = schema.hardware_catalog
    stmt = sa.select(t).order_by(t.c.display_name)
    if status:
        stmt = stmt.where(t.c.status == status)
    return _rows(conn.execute(stmt))


def get_hardware(conn: Connection, catalog_id: str) -> dict[str, Any] | None:
    t = schema.hardware_catalog
    row = (
        conn.execute(sa.select(t).where(t.c.catalog_id == catalog_id))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_hardware(
    conn: Connection,
    *,
    catalog_id: str,
    display_name: str,
    category: str,
    photo_url: str | None = None,
    specs: dict[str, Any] | None = None,
    provisioning_steps: list[Any] | None = None,
) -> dict[str, Any]:
    t = schema.hardware_catalog
    conn.execute(
        sa.insert(t).values(
            catalog_id=catalog_id,
            display_name=display_name,
            category=category,
            photo_url=photo_url,
            specs=specs,
            provisioning_steps=provisioning_steps,
        )
    )
    conn.commit()
    return get_hardware(conn, catalog_id)  # type: ignore[return-value]


def update_hardware(
    conn: Connection, catalog_id: str, **updates: Any
) -> dict[str, Any] | None:
    t = schema.hardware_catalog
    allowed = {
        "display_name",
        "category",
        "photo_url",
        "specs",
        "provisioning_steps",
        "status",
    }
    vals = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not vals:
        return get_hardware(conn, catalog_id)
    conn.execute(sa.update(t).where(t.c.catalog_id == catalog_id).values(**vals))
    conn.commit()
    return get_hardware(conn, catalog_id)


# ---------------------------------------------------------------------------
# firmware_catalog
# ---------------------------------------------------------------------------


def list_firmware(
    conn: Connection,
    *,
    hardware_catalog_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    fc = schema.firmware_catalog
    hc = schema.hardware_catalog
    stmt = (
        sa.select(fc, hc.c.display_name.label("hardware_name"))
        .outerjoin(hc, fc.c.hardware_catalog_id == hc.c.catalog_id)
        .order_by(fc.c.released_at.desc().nulls_last())
    )
    if hardware_catalog_id:
        stmt = stmt.where(fc.c.hardware_catalog_id == hardware_catalog_id)
    if status:
        stmt = stmt.where(fc.c.status == status)
    return _rows(conn.execute(stmt))


def get_firmware(conn: Connection, firmware_id: str) -> dict[str, Any] | None:
    fc = schema.firmware_catalog
    hc = schema.hardware_catalog
    row = (
        conn.execute(
            sa.select(fc, hc.c.display_name.label("hardware_name"))
            .outerjoin(hc, fc.c.hardware_catalog_id == hc.c.catalog_id)
            .where(fc.c.firmware_id == firmware_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_firmware(
    conn: Connection,
    *,
    firmware_id: str,
    hardware_catalog_id: str,
    version: str,
    changelog: str | None = None,
    sidecar_schema_version: str | None = None,
    binary_url: str | None = None,
) -> dict[str, Any]:
    t = schema.firmware_catalog
    conn.execute(
        sa.insert(t).values(
            firmware_id=firmware_id,
            hardware_catalog_id=hardware_catalog_id,
            version=version,
            changelog=changelog,
            sidecar_schema_version=sidecar_schema_version,
            binary_url=binary_url,
        )
    )
    conn.commit()
    return get_firmware(conn, firmware_id)  # type: ignore[return-value]


def update_firmware(
    conn: Connection, firmware_id: str, **updates: Any
) -> dict[str, Any] | None:
    t = schema.firmware_catalog
    allowed = {"version", "changelog", "sidecar_schema_version", "binary_url", "status"}
    vals = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not vals:
        return get_firmware(conn, firmware_id)
    conn.execute(sa.update(t).where(t.c.firmware_id == firmware_id).values(**vals))
    conn.commit()
    return get_firmware(conn, firmware_id)


# ---------------------------------------------------------------------------
# setup_version
# ---------------------------------------------------------------------------


def list_setups(conn: Connection, *, status: str | None = None) -> list[dict[str, Any]]:
    t = schema.setup_version
    stmt = sa.select(t).order_by(t.c.display_name)
    if status:
        stmt = stmt.where(t.c.status == status)
    return _rows(conn.execute(stmt))


def get_setup(conn: Connection, setup_id: str) -> dict[str, Any] | None:
    t = schema.setup_version
    row = conn.execute(sa.select(t).where(t.c.setup_id == setup_id)).mappings().first()
    return dict(row) if row else None


def create_setup(
    conn: Connection,
    *,
    setup_id: str,
    display_name: str,
    components: list[dict[str, Any]],
    constraints: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t = schema.setup_version
    conn.execute(
        sa.insert(t).values(
            setup_id=setup_id,
            display_name=display_name,
            components=components,
            constraints=constraints,
            contract=contract,
        )
    )
    conn.commit()
    return get_setup(conn, setup_id)  # type: ignore[return-value]


def update_setup(
    conn: Connection, setup_id: str, **updates: Any
) -> dict[str, Any] | None:
    t = schema.setup_version
    allowed = {"display_name", "components", "constraints", "contract", "status"}
    vals = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not vals:
        return get_setup(conn, setup_id)
    conn.execute(sa.update(t).where(t.c.setup_id == setup_id).values(**vals))
    conn.commit()
    return get_setup(conn, setup_id)


def kits_using_setup(conn: Connection, setup_id: str) -> int:
    kit = schema.TABLES["kit"]
    row = conn.execute(
        sa.select(sa.func.count()).where(kit.c.setup_version_id == setup_id)
    ).scalar()
    return int(row or 0)
