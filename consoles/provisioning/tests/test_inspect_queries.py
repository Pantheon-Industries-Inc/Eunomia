"""DB-backed tests for store inspector queries.

Same pattern as test_ops_queries: skip when EUNOMIA_STORE_TEST_DSN is unset.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from eunomia_edge_store.config import DSN_ENV, TEST_DSN_ENV, StoreConfig
from eunomia_edge_store.engine import make_engine
from eunomia_edge_store.store import append_event, upsert

from eunomia_consoles_provisioning.ops import inspect_queries

MIGRATIONS = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "edge"
    / "store"
    / "migrations"
)

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    dsn = os.environ.get(TEST_DSN_ENV)
    if not dsn:
        pytest.skip(f"{TEST_DSN_ENV} not set — DB-backed tests need a Postgres")
    eng = make_engine(StoreConfig(dsn=dsn))
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
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


@pytest.fixture()
def conn(engine: Engine) -> Iterator[Connection]:
    with engine.begin() as c:
        yield c
        c.rollback()


NOW = datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_person(conn: Connection, person_id: str, name: str) -> None:
    upsert(
        conn,
        "person",
        {
            "schema": "eunomia-person/v1",
            "person_id": person_id,
            "name": name,
            "role": "operator",
            "status": "active",
        },
    )


def _seed_kit(conn: Connection, kit_id: str) -> None:
    upsert(
        conn,
        "kit",
        {
            "schema": "eunomia-kit/v1",
            "kit_id": kit_id,
            "effective_from": _iso(NOW - timedelta(days=30)),
        },
    )


def _seed_task(
    conn: Connection,
    task_id: str,
    task_name: str,
    *,
    version: int = 1,
    rotation_id: str = "r1",
    metadata: dict | None = None,
) -> None:
    record: dict = {
        "schema": "eunomia-task/v1",
        "task_id": task_id,
        "version": version,
        "rotation_id": rotation_id,
        "task_name": task_name,
    }
    if metadata is not None:
        record["metadata"] = metadata
    upsert(conn, "task", record)


def _seed_episode(
    conn: Connection,
    episode_id: str,
    *,
    kit_id: str = "kit_01",
    person_id: str = "op_01",
    task_id: str = "t_01",
    task_version: int = 1,
    rotation_id: str = "r1",
    recorded_at: datetime | None = None,
    archive: int = 900,
    session_id: str = "sess_01",
) -> None:
    upsert(
        conn,
        "episode",
        {
            "schema": "eunomia-episode/v1",
            "episode_id": episode_id,
            "global_episode_seq": 1,
            "kit_id": kit_id,
            "side": "left",
            "person_id": person_id,
            "task_id": task_id,
            "task_version": task_version,
            "rotation_id": rotation_id,
            "station_id": "st_01",
            "session_id": session_id,
            "recorded_at": _iso(recorded_at or NOW - timedelta(hours=1)),
            "archive": archive,
            "recording_suspect": 0,
        },
    )


def _seed_session(
    conn: Connection,
    session_id: str,
    person_id: str,
    kit_id: str,
    signed_in_at: datetime,
) -> None:
    upsert(
        conn,
        "session",
        {
            "schema": "eunomia-session/v1",
            "session_id": session_id,
            "person_id": person_id,
            "kit_id": kit_id,
            "signed_in_at": _iso(signed_in_at),
        },
    )


def _seed_event(
    conn: Connection,
    event_id: str,
    event_type: str,
    *,
    entity: str = "episode",
    entity_id: str = "ep_x",
) -> None:
    append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": event_id,
            "event_type": event_type,
            "entity": entity,
            "entity_id": entity_id,
            "as_of": _iso(NOW),
            "payload": {"detail": f"test for {event_id}"},
        },
    )


# ---------------------------------------------------------------------------
# Episode queries
# ---------------------------------------------------------------------------


def test_episode_list_empty(conn: Connection) -> None:
    episodes = inspect_queries.episode_list(conn)
    assert episodes == []


def test_episode_list_pagination(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    for i in range(15):
        _seed_episode(
            conn,
            f"ep_{i:03d}",
            recorded_at=NOW - timedelta(hours=15 - i),
        )

    page1 = inspect_queries.episode_list(conn, limit=10, offset=0)
    assert len(page1) == 10

    page2 = inspect_queries.episode_list(conn, limit=10, offset=10)
    assert len(page2) == 5

    all_ids = [e["episode_id"] for e in page1 + page2]
    assert len(set(all_ids)) == 15


def test_episode_list_filter_by_kit(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_kit(conn, "kit_02")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_k1", kit_id="kit_01")
    _seed_episode(conn, "ep_k2", kit_id="kit_02")

    episodes = inspect_queries.episode_list(conn, kit_id="kit_01")
    assert len(episodes) == 1
    assert episodes[0]["episode_id"] == "ep_k1"


def test_episode_list_filter_by_episode_id(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_abc_123")
    _seed_episode(conn, "ep_xyz_456")

    episodes = inspect_queries.episode_list(conn, episode_id="abc")
    assert len(episodes) == 1
    assert episodes[0]["episode_id"] == "ep_abc_123"


def test_episode_detail(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_detail")

    detail = inspect_queries.episode_detail(conn, "ep_detail")
    assert detail is not None
    assert detail["episode_id"] == "ep_detail"
    assert detail["kit_id"] == "kit_01"


def test_episode_detail_not_found(conn: Connection) -> None:
    assert inspect_queries.episode_detail(conn, "nonexistent") is None


def test_episode_events(conn: Connection) -> None:
    _seed_event(conn, "evt_1", "episode_started", entity_id="ep_target")
    _seed_event(conn, "evt_2", "episode_stopped", entity_id="ep_target")
    _seed_event(conn, "evt_3", "episode_started", entity_id="ep_other")

    events = inspect_queries.episode_events(conn, "ep_target")
    assert len(events) == 2
    assert all(e["entity_id"] == "ep_target" for e in events)


def test_episode_footage_ref(conn: Connection) -> None:
    upsert(
        conn,
        "footage_reference",
        {
            "schema": "eunomia-footage-reference/v1",
            "episode_id": "ep_with_footage",
            "footage_state": "on_styx",
            "locations": ["/data/video.mp4"],
        },
    )

    ref = inspect_queries.episode_footage_ref(conn, "ep_with_footage")
    assert ref is not None
    assert ref["episode_id"] == "ep_with_footage"

    assert inspect_queries.episode_footage_ref(conn, "nonexistent") is None


# ---------------------------------------------------------------------------
# Event queries
# ---------------------------------------------------------------------------


def test_event_list_with_filter(conn: Connection) -> None:
    _seed_event(conn, "evt_a", "episode_started")
    _seed_event(conn, "evt_b", "qa_verdict")

    all_events = inspect_queries.event_list(conn, limit=50)
    assert len(all_events) >= 2

    filtered = inspect_queries.event_list(conn, event_type="qa_verdict")
    assert all(e["event_type"] == "qa_verdict" for e in filtered)


def test_event_types(conn: Connection) -> None:
    _seed_event(conn, "evt_t1", "episode_started")
    _seed_event(conn, "evt_t2", "qa_verdict")

    types = inspect_queries.event_types(conn)
    assert "episode_started" in types
    assert "qa_verdict" in types


# ---------------------------------------------------------------------------
# Session queries
# ---------------------------------------------------------------------------


def test_session_list(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_session(conn, "sess_01", "op_01", "kit_01", NOW - timedelta(hours=2))
    _seed_session(conn, "sess_02", "op_01", "kit_01", NOW - timedelta(hours=1))

    sessions = inspect_queries.session_list(conn)
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "sess_02"
    assert sessions[0]["operator_name"] == "Alice"


# ---------------------------------------------------------------------------
# Task queries
# ---------------------------------------------------------------------------


def test_task_list_raw(conn: Connection) -> None:
    _seed_task(conn, "t_01", "Wash", metadata={"difficulty": "easy"})
    _seed_task(conn, "t_02", "Fold")

    tasks = inspect_queries.task_list_raw(conn)
    assert len(tasks) >= 2
    wash = next(t for t in tasks if t["task_id"] == "t_01")
    assert wash["metadata"] == {"difficulty": "easy"}
