"""Add single-column index on episode.recorded_at for ops dashboard time-range queries.

Revision ID: 0002
Create Date: Run D1
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_episode_recorded_at"


def upgrade() -> None:
    op.create_index(INDEX_NAME, "episode", ["recorded_at"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="episode")
