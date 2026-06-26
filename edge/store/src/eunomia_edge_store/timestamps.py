"""Timezone-correct ISO-8601 handling (NOTE F5).

Timestamp fields are ``string`` on the wire (ISO-8601) and ``timestamptz`` in the store. On write a
string is parsed to a tz-aware instant; on read the instant is normalized back to a canonical UTC ISO
string. Equality is an INSTANT comparison — ``...T10:00:00-04:00`` and ``...T14:00:00Z`` are the same
moment — so the smoke test compares parsed instants, never raw strings.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_instant(value: str | datetime) -> datetime:
    """Parse an ISO-8601 string (or pass a datetime through) to a tz-aware UTC instant.

    A naive datetime / string with no offset is assumed UTC (the on-card clock convention).
    """
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        # datetime.fromisoformat handles the trailing 'Z' from Python 3.11+, but normalize defensively.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(value: str | datetime | None) -> str | None:
    """Normalize a stored instant (or ISO string) to a canonical UTC ISO-8601 string (``...+00:00``)."""
    if value is None:
        return None
    return parse_instant(value).isoformat()


def same_instant(a: str | datetime | None, b: str | datetime | None) -> bool:
    """True iff both denote the same instant (tz-correct), or both are None."""
    if a is None or b is None:
        return a is None and b is None
    return parse_instant(a) == parse_instant(b)
