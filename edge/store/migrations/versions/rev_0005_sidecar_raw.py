"""R4 sidecar_raw + firmware_version: archive the complete raw sidecar as JSONB and
promote fob_build to a typed column for firmware-version queries.

Revision ID: 0005
Create Date: Run R4

- sidecar_raw: nullable JSONB — the complete sidecar dict, untouched.
- firmware_version: nullable TEXT — provenance.fob_build from the sidecar.
- eunomia_writer already has INSERT/UPDATE on episode (rev_0001); no new grants needed.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE episode ADD COLUMN IF NOT EXISTS sidecar_raw JSONB;")
    op.execute(
        "COMMENT ON COLUMN episode.sidecar_raw IS "
        "'Complete raw sidecar JSON as received from the camera. "
        "Archived for reprocessing; new firmware fields appear here automatically.';"
    )
    op.execute("ALTER TABLE episode ADD COLUMN IF NOT EXISTS firmware_version TEXT;")
    op.execute(
        "COMMENT ON COLUMN episode.firmware_version IS "
        "'Fob firmware build (provenance.fob_build). "
        "Typed column for querying/filtering episodes by firmware version.';"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE episode DROP COLUMN IF EXISTS firmware_version;")
    op.execute("ALTER TABLE episode DROP COLUMN IF EXISTS sidecar_raw;")
