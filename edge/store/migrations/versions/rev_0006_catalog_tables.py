"""V1 catalog tables: hardware_catalog + firmware_catalog + setup_version.

Revision ID: 0006
Create Date: Run V1

- Three new store-native tables (NOT contract entities, mutable).
- firmware_catalog has a real FK to hardware_catalog (both admin-managed).
- Three new columns on contract-derived tables (hardware_catalog_id on hardware_unit,
  setup_version_id on kit + episode) — indexed, NOT FK'd (NOTE F6).
- eunomia_writer gets SELECT/INSERT/UPDATE on catalog tables.
- eunomia_reader gets SELECT on catalog tables.
"""

from __future__ import annotations

from alembic import op

from eunomia_edge_store import schema

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

WRITER = "eunomia_writer"
READER = "eunomia_reader"


def upgrade() -> None:
    bind = op.get_bind()
    schema.hardware_catalog.create(bind, checkfirst=True)
    schema.firmware_catalog.create(bind, checkfirst=True)
    schema.setup_version.create(bind, checkfirst=True)

    op.execute(
        "ALTER TABLE hardware_unit ADD COLUMN IF NOT EXISTS hardware_catalog_id TEXT;"
    )
    op.execute(
        "COMMENT ON COLUMN hardware_unit.hardware_catalog_id IS "
        "'Reference to hardware_catalog.catalog_id (V1 catalog). Admin-set.';"
    )
    op.execute("ALTER TABLE kit ADD COLUMN IF NOT EXISTS setup_version_id TEXT;")
    op.execute(
        "COMMENT ON COLUMN kit.setup_version_id IS "
        "'Setup configuration this kit is provisioned with (V1 catalog). Admin-set.';"
    )
    op.execute("ALTER TABLE episode ADD COLUMN IF NOT EXISTS setup_version_id TEXT;")
    op.execute(
        "COMMENT ON COLUMN episode.setup_version_id IS "
        "'Setup configuration this episode was recorded under (V1 catalog).';"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hardware_unit_hardware_catalog_id "
        "ON hardware_unit (hardware_catalog_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kit_setup_version_id ON kit (setup_version_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episode_setup_version_id "
        "ON episode (setup_version_id);"
    )

    for table in schema.CATALOG_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {WRITER};")
        op.execute(f"GRANT SELECT ON {table} TO {READER};")


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_episode_setup_version_id;")
    op.execute("DROP INDEX IF EXISTS ix_kit_setup_version_id;")
    op.execute("DROP INDEX IF EXISTS ix_hardware_unit_hardware_catalog_id;")
    op.execute("ALTER TABLE episode DROP COLUMN IF EXISTS setup_version_id;")
    op.execute("ALTER TABLE kit DROP COLUMN IF EXISTS setup_version_id;")
    op.execute("ALTER TABLE hardware_unit DROP COLUMN IF EXISTS hardware_catalog_id;")
    schema.setup_version.drop(bind, checkfirst=True)
    schema.firmware_catalog.drop(bind, checkfirst=True)
    schema.hardware_catalog.drop(bind, checkfirst=True)
