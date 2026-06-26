"""Alembic environment for edge/store (Run S1).

The DB URL comes from ``EUNOMIA_STORE_DSN`` via the store's own config/engine (the topology seam,
NOTE F3) — never from alembic.ini — so the same migrations apply edge or central and no credential
lives in the repo. Online mode only (a live connection is required).
"""

from __future__ import annotations

from alembic import context

from eunomia_edge_store import schema
from eunomia_edge_store.config import StoreConfig
from eunomia_edge_store.engine import make_engine

target_metadata = schema.metadata


def run_migrations_online() -> None:
    engine = make_engine(StoreConfig.from_env())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit(
        "edge/store migrations require a live connection — set EUNOMIA_STORE_DSN"
    )
run_migrations_online()
