"""The camera_id allocator — a Postgres sequence + an insert-only ledger + retire-not-reuse (NOTE F7).

Allocation = ``nextval(camera_id_seq)`` → format → insert one ledger row. The sequence is monotonic,
so an id is **never reissued** even after retirement; retirement is recorded as an operational_event
+ the unit's ``status=retired``, never as a mutation of the insert-only ledger (NOTE prod-bar c).

The id FORMAT is a single swappable constant — ``CAM-<n>`` is a placeholder until the fleet's real
convention is confirmed (NOTE F7). The importer preserves existing camera_ids verbatim regardless.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema

#: Swappable camera_id format (NOTE F7). Swap this one constant to match the fleet convention.
CAMERA_ID_FORMAT = "CAM-{n}"


def format_camera_id(n: int) -> str:
    return CAMERA_ID_FORMAT.format(n=n)


def allocate_camera_id(
    conn: Connection,
    *,
    body_serial: str | None = None,
    allocated_by: str | None = None,
) -> str:
    """Mint a fresh, never-reused camera_id and record it in the insert-only ledger."""
    n = int(conn.execute(sa.select(schema.camera_id_seq.next_value())).scalar_one())
    camera_id = format_camera_id(n)
    conn.execute(
        schema.camera_id_ledger.insert().values(
            camera_id=camera_id,
            body_serial=body_serial,
            seq_value=n,
            allocated_by=allocated_by,
        )
    )
    return camera_id


def is_allocated(conn: Connection, camera_id: str) -> bool:
    """True iff this camera_id has ever been minted (retire-not-reuse spans the whole ledger)."""
    ledger = schema.camera_id_ledger
    found = conn.execute(
        sa.select(ledger.c.camera_id).where(ledger.c.camera_id == camera_id)
    ).first()
    return found is not None
