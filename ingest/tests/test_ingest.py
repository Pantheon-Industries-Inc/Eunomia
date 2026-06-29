"""DB-backed integration tests for the ingest pipeline.

Marked ``db`` — skip without ``EUNOMIA_STORE_TEST_DSN``. See ``edge/store/tests/conftest.py``
for the engine/conn fixtures (shared across both packages).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import Connection, Engine

from eunomia_ingest.ingest import (
    ingest_drain,
    ingest_fob_log,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    dsn = os.environ.get("EUNOMIA_STORE_TEST_DSN")
    if not dsn:
        pytest.skip(
            "EUNOMIA_STORE_TEST_DSN not set — DB-backed ingest tests need a Postgres"
        )

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from eunomia_edge_store.config import DSN_ENV
    from eunomia_edge_store.config import StoreConfig
    from eunomia_edge_store.engine import make_engine

    eng = make_engine(StoreConfig(dsn=dsn))
    migrations = (
        Path(__file__).resolve().parents[2] / ".." / "edge" / "store" / "migrations"
    )
    if not migrations.exists():
        migrations = (
            Path(__file__).resolve().parents[3] / "edge" / "store" / "migrations"
        )

    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    cfg = Config()
    cfg.set_main_option("script_location", str(migrations))
    previous = os.environ.get(DSN_ENV)
    os.environ[DSN_ENV] = dsn
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
    connection = engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()


def test_drain_creates_episodes(conn: Connection) -> None:
    drain_root = FIXTURES / "drain"
    report = ingest_drain(drain_root, conn)
    assert report.episodes_created == 2
    assert report.footage_refs_created == 2
    assert report.sidecars_skipped == 1

    from eunomia_edge_store import store

    ep = store.get(conn, "episode", episode_id="550e8400-e29b-41d4-a716-446655440000")
    assert ep is not None
    assert ep["kit_id"] == "kit_07"
    assert ep["side"] == "left"
    assert ep["person_id"] == "op_123"

    fr = store.get(
        conn, "footage_reference", episode_id="550e8400-e29b-41d4-a716-446655440000"
    )
    assert fr is not None
    assert fr["footage_state"] == "on_styx"


def test_fob_log_creates_events_and_sessions(conn: Connection) -> None:
    report = ingest_fob_log(FIXTURES / "fob_dump.jsonl", conn)
    assert report.events_appended > 0
    assert report.sessions_created == 1

    from eunomia_edge_store import store

    sess = store.get(conn, "session", session_id="sess_xyz")
    assert sess is not None
    assert sess["person_id"] == "op_123"
    assert sess["kit_id"] == "kit_07"
    assert sess["site_id"] == "mx_1"
    assert sess["fob_session_id"] == "1a2b3c4d"


def test_drain_then_fob_log_enriches_episode(conn: Connection) -> None:
    drain_root = FIXTURES / "drain"
    ingest_drain(drain_root, conn)
    report = ingest_fob_log(FIXTURES / "fob_dump.jsonl", conn)
    assert report.episodes_enriched >= 1

    from eunomia_edge_store import store

    ep = store.get(conn, "episode", episode_id="550e8400-e29b-41d4-a716-446655440000")
    assert ep is not None
    assert ep["task_id"] == "t_fold"
    assert ep["station_id"] == "5"
    assert ep["rotation_id"] == "r2"


def test_reimport_drain_idempotent(conn: Connection) -> None:
    drain_root = FIXTURES / "drain"
    r1 = ingest_drain(drain_root, conn)
    r2 = ingest_drain(drain_root, conn)
    assert r1.episodes_created == r2.episodes_created

    from eunomia_edge_store import store

    assert store.count(conn, "episode") == 2


def test_reimport_fob_log_idempotent(conn: Connection) -> None:
    path = FIXTURES / "fob_dump.jsonl"
    r1 = ingest_fob_log(path, conn)
    r2 = ingest_fob_log(path, conn)
    assert r1.events_appended == r2.events_appended

    from eunomia_edge_store import store

    assert store.count(conn, "session") == 1


def test_recording_suspect_flagged(conn: Connection) -> None:
    drain_root = FIXTURES / "drain"
    report = ingest_drain(drain_root, conn)
    suspects = [a for a in report.anomalies if a.anomaly_type == "recording_suspect"]
    assert len(suspects) == 1
    assert "660e8400" in suspects[0].entity_id


def test_fob_log_parse_errors_reported(conn: Connection) -> None:
    report = ingest_fob_log(FIXTURES / "fob_dump.jsonl", conn)
    assert report.fob_log_errors >= 1
    error_anomalies = [
        a for a in report.anomalies if a.anomaly_type == "fob_log_parse_error"
    ]
    assert len(error_anomalies) >= 1
