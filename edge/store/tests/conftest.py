"""DB-backed test harness (Run S1).

Every DB test is marked ``db`` and depends on the ``engine`` fixture, which SKIPS when
``EUNOMIA_STORE_TEST_DSN`` is unset — so the default ``make gates`` needs no database, and
``make gates-db`` (or CI's postgres service) sets the DSN to run them. The schema is built by running
the real Alembic migration (so the roles/grants/audit triggers are exercised, not just the tables).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from eunomia_edge_store.config import DSN_ENV, TEST_DSN_ENV, StoreConfig
from eunomia_edge_store.engine import make_engine

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    dsn = os.environ.get(TEST_DSN_ENV)
    if not dsn:
        pytest.skip(f"{TEST_DSN_ENV} not set — DB-backed store tests need a Postgres")
    eng = make_engine(StoreConfig(dsn=dsn))
    # Clean slate: drop + recreate the schema, then apply the migration from base (roles are
    # cluster-global and created idempotently by the migration, so they survive the schema drop).
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    previous = os.environ.get(DSN_ENV)
    os.environ[DSN_ENV] = dsn  # env.py reads EUNOMIA_STORE_DSN (the topology seam)
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop(DSN_ENV, None)
        else:
            os.environ[DSN_ENV] = previous
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A per-test connection wrapped in a transaction that always rolls back (test isolation)."""
    connection = engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()
