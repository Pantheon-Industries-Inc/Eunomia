"""P3 supervisor tables: operator_task_assignment + collection_target + task_catalog_seq.

Revision ID: 0003
Create Date: Run P3

- Two new store-native tables (NOT contract entities, mutable — not audit/insert-only).
- A Postgres sequence for permanent numeric task IDs (retire-not-reuse).
- eunomia_writer gets SELECT/INSERT/UPDATE on both tables + USAGE on the sequence.
"""

from __future__ import annotations

from alembic import op

from eunomia_edge_store import schema

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

WRITER = "eunomia_writer"


def upgrade() -> None:
    bind = op.get_bind()
    schema.task_catalog_seq.create(bind, checkfirst=True)
    schema.operator_task_assignment.create(bind, checkfirst=True)
    schema.collection_target.create(bind, checkfirst=True)

    for table in schema.SUPERVISOR_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {WRITER};")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE task_catalog_seq TO {WRITER};")


def downgrade() -> None:
    bind = op.get_bind()
    schema.collection_target.drop(bind, checkfirst=True)
    schema.operator_task_assignment.drop(bind, checkfirst=True)
    schema.task_catalog_seq.drop(bind, checkfirst=True)
