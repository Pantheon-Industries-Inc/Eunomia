"""R3 task metadata: add JSONB metadata column to the task table.

Revision ID: 0004
Create Date: Run R3

- Additive: a nullable JSONB column for flexible operational metadata (props, scene setup, etc.).
- eunomia_writer already has UPDATE on the task table (rev_0001); no new grants needed.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task ADD COLUMN IF NOT EXISTS metadata JSONB;")


def downgrade() -> None:
    op.execute("ALTER TABLE task DROP COLUMN IF EXISTS metadata;")
