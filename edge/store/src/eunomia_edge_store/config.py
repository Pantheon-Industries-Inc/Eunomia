"""Topology-agnostic store config (NOTE F3): a Postgres reachable by a DSN.

The DSN/env is the ONLY seam — the same store binary runs edge OR central; there is no baked-in
edge-authoritative assumption and no replication here. ``sslmode`` is plumbed through so the layer is
TLS-capable (NOTE prod-bar a); the cert + enforcement are deploy concerns, not S1.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: The production DSN env var (e.g. ``postgresql+psycopg://user:pass@host:5432/eunomia?sslmode=require``).
DSN_ENV = "EUNOMIA_STORE_DSN"
#: Optional sslmode override merged into the DSN if it does not already carry one.
SSLMODE_ENV = "EUNOMIA_STORE_SSLMODE"
#: The DSN the DB-backed tests use; when unset those tests skip (the default `make gates` needs no DB).
TEST_DSN_ENV = "EUNOMIA_STORE_TEST_DSN"


class StoreConfigError(RuntimeError):
    """Raised when the store is not configured (no DSN — the topology seam is unset)."""


@dataclass(frozen=True)
class StoreConfig:
    dsn: str
    sslmode: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> StoreConfig:
        environ: Mapping[str, str] = os.environ if env is None else env
        dsn = environ.get(DSN_ENV)
        if not dsn:
            raise StoreConfigError(
                f"{DSN_ENV} is not set — the store needs a Postgres DSN (the topology seam, NOTE F3)"
            )
        return cls(dsn=dsn, sslmode=environ.get(SSLMODE_ENV))
