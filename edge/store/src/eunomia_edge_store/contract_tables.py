"""Derive SQLAlchemy Core columns from the contract (NOTE F8).

The store never hand-writes a contract model. Each current-state table's columns come straight from
the matching ``eunomia_contracts`` module's generated ``_TABLES`` (the hard/warn/nullable/type data
the codegen already distilled from the one neutral YAML source). The contract therefore stays the
single source of truth; ``tests/test_contract_coverage.py`` is the drift guard.

Mapping (contract type -> column type):
  string                -> Text          (timestamp-named -> timestamptz, NOTE F5)
  int                   -> BigInteger
  number                -> Double
  bool                  -> Boolean
  object / array        -> JSONB         (a nested object collapses to one JSONB column, one level)

Nullability is store-stricter than the wire (NOTE F4): a column is NOT NULL iff the contract field is
HARD, or it is part of the table's primary key, or it is force-listed (a composite natural key whose
parts are only WARN on the wire, e.g. task.version / task.rotation_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from eunomia_contracts import _semantics

# Timestamp-named contract fields become timestamptz columns (NOTE F5). All are `string` on the wire;
# `*_at` covers every dated field, plus the three explicit non-`_at` instants.
_TIMESTAMP_FIELDS = frozenset({"effective_from", "effective_to", "as_of"})


def is_timestamp_field(name: str) -> bool:
    """A contract `string` field the store persists as `timestamptz` (NOTE F5)."""
    return name.endswith("_at") or name in _TIMESTAMP_FIELDS


def column_type(name: str, json_type: str) -> sa.types.TypeEngine[Any]:
    if json_type == "string":
        return sa.DateTime(timezone=True) if is_timestamp_field(name) else sa.Text()
    if json_type == "int":
        return sa.BigInteger()
    if json_type == "number":
        return sa.Double()
    if json_type == "bool":
        return sa.Boolean()
    if json_type in ("object", "array"):
        return JSONB()
    raise ValueError(f"unmapped contract type {json_type!r} for field {name!r}")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    json_type: str
    hard: bool
    nullable_on_wire: bool


def top_level_fields(tables: _semantics.Tables) -> list[FieldSpec]:
    """The top-level contract fields, in a deterministic order (hard first, then warn).

    Nested object sub-paths (``provisioning.wifi_ssid`` ...) collapse into the parent JSONB column, so
    only the dot-free paths become columns.
    """
    out: list[FieldSpec] = []
    for path, json_type in tables.hard:
        if "." not in path:
            out.append(FieldSpec(path, json_type, True, path in tables.nullable))
    for path, json_type in tables.warn:
        if "." not in path:
            out.append(FieldSpec(path, json_type, False, path in tables.nullable))
    return out


def build_columns(
    tables: _semantics.Tables,
    *,
    primary_key: tuple[str, ...],
    force_not_null: frozenset[str] = frozenset(),
) -> list[sa.Column[Any]]:
    pk = set(primary_key)
    cols: list[sa.Column[Any]] = []
    for fs in top_level_fields(tables):
        is_pk = fs.name in pk
        not_null = fs.hard or is_pk or fs.name in force_not_null
        cols.append(
            sa.Column(
                fs.name,
                column_type(fs.name, fs.json_type),
                primary_key=is_pk,
                nullable=not not_null,
            )
        )
    return cols
