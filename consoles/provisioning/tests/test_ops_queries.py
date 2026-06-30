"""DB-backed tests for ops dashboard queries.

Same pattern as edge/store/tests: skip when EUNOMIA_STORE_TEST_DSN is unset. Insert synthetic
data via the store API, run dashboard queries, assert results.
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

from eunomia_consoles_provisioning.ops import queries

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
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


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
    version: int = 1,
    rotation_id: str = "r1",
) -> None:
    upsert(
        conn,
        "task",
        {
            "schema": "eunomia-task/v1",
            "task_id": task_id,
            "version": version,
            "rotation_id": rotation_id,
            "task_name": task_name,
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
    ingested_at: datetime | None = None,
    archive: int = 900,
    recording_suspect: int = 0,
    session_id: str = "sess_01",
) -> None:
    data: dict[str, object] = {
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
        "recording_suspect": recording_suspect,
    }
    if ingested_at is not None:
        data["ingested_at"] = _iso(ingested_at)
    upsert(conn, "episode", data)


def _seed_anomaly(
    conn: Connection,
    event_id: str,
    anomaly_type: str,
    *,
    kit_id: str | None = None,
    entity_id: str = "ep_x",
) -> None:
    append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": event_id,
            "event_type": "ingest_anomaly",
            "entity": "episode",
            "entity_id": entity_id,
            "as_of": _iso(NOW),
            "related_kit_id": kit_id,
            "payload": {
                "anomaly_type": anomaly_type,
                "detail": f"test detail for {event_id}",
            },
        },
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def test_overview_stats_empty_store(conn: Connection) -> None:
    stats = queries.overview_stats(conn)
    assert stats["episodes_today"] == 0
    assert stats["hours_today"] == 0.0
    assert stats["operators_active"] == 0
    assert stats["kits_in_use"] == 0


def test_overview_stats_with_episodes(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_01", recorded_at=NOW - timedelta(hours=1), archive=900)
    _seed_episode(conn, "ep_02", recorded_at=NOW - timedelta(hours=2), archive=1800)

    stats = queries.overview_stats(conn)
    assert stats["episodes_today"] == 2
    assert stats["operators_active"] == 1
    assert stats["kits_in_use"] == 1
    assert stats["hours_today"] == round((900 + 1800) / 30 / 3600, 1)


def test_anomaly_count_zero(conn: Connection) -> None:
    assert queries.anomaly_count(conn) == 0


def test_anomaly_count_nonzero(conn: Connection) -> None:
    _seed_anomaly(conn, "evt_a1", "recording_suspect")
    _seed_anomaly(conn, "evt_a2", "sidecar_without_footage")
    assert queries.anomaly_count(conn) == 2


def test_recent_episodes_ordering(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_old", recorded_at=NOW - timedelta(hours=5))
    _seed_episode(conn, "ep_new", recorded_at=NOW - timedelta(minutes=10))

    eps = queries.recent_episodes(conn, limit=10)
    assert len(eps) == 2
    assert eps[0]["episode_id"] == "ep_new"
    assert eps[1]["episode_id"] == "ep_old"


def test_recent_episodes_joins(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_j1", person_id="op_01", task_id="t_01")

    eps = queries.recent_episodes(conn, limit=1)
    assert eps[0]["operator_name"] == "Alice"
    assert eps[0]["task_name"] == "Wash"


def test_recent_episodes_null_joins(conn: Connection) -> None:
    _seed_kit(conn, "kit_01")
    _seed_episode(
        conn, "ep_null", person_id="", task_id="", task_version=1, rotation_id="r1"
    )

    eps = queries.recent_episodes(conn, limit=1)
    assert eps[0]["operator_name"] is None
    assert eps[0]["task_name"] is None


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------


def test_operator_list(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_person(conn, "op_02", "Bob")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(
        conn, "ep_a1", person_id="op_01", recorded_at=NOW - timedelta(hours=1)
    )
    _seed_episode(
        conn, "ep_a2", person_id="op_01", recorded_at=NOW - timedelta(hours=2)
    )
    _seed_episode(
        conn,
        "ep_b1",
        person_id="op_02",
        recorded_at=NOW - timedelta(hours=1),
        recording_suspect=1,
    )

    ops = queries.operator_list(conn)
    assert len(ops) >= 2
    alice = next(o for o in ops if o["person_id"] == "op_01")
    bob = next(o for o in ops if o["person_id"] == "op_02")
    assert alice["today"] >= 2
    assert bob["suspect_pct"] == 100.0


def test_operator_detail(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    person = queries.operator_detail(conn, "op_01")
    assert person is not None
    assert person["name"] == "Alice"


def test_operator_detail_not_found(conn: Connection) -> None:
    assert queries.operator_detail(conn, "nonexistent") is None


def test_operator_hours_by_task(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")
    _seed_task(conn, "t_02", "Fold")
    _seed_episode(conn, "ep_h1", person_id="op_01", task_id="t_01", archive=3600)
    _seed_episode(conn, "ep_h2", person_id="op_01", task_id="t_02", archive=1800)

    hours = queries.operator_hours_by_task(conn, "op_01")
    assert len(hours) == 2
    assert hours[0]["hours"] >= hours[1]["hours"]


def test_operator_sessions(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_session(conn, "sess_01", "op_01", "kit_01", NOW - timedelta(hours=4))
    _seed_session(conn, "sess_02", "op_01", "kit_01", NOW - timedelta(hours=1))

    sessions = queries.operator_sessions(conn, "op_01")
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "sess_02"


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------


def test_kit_list(conn: Connection) -> None:
    _seed_kit(conn, "kit_01")
    _seed_kit(conn, "kit_02")

    kits = queries.kit_list(conn)
    ids = [k["kit_id"] for k in kits]
    assert "kit_01" in ids
    assert "kit_02" in ids


def test_kit_detail(conn: Connection) -> None:
    _seed_kit(conn, "kit_01")
    kit = queries.kit_detail(conn, "kit_01")
    assert kit is not None
    assert kit["kit_id"] == "kit_01"


def test_kit_detail_not_found(conn: Connection) -> None:
    assert queries.kit_detail(conn, "nonexistent") is None


def test_kit_episode_stats(conn: Connection) -> None:
    _seed_kit(conn, "kit_01")
    _seed_person(conn, "op_01", "Alice")
    _seed_task(conn, "t_01", "Wash")
    _seed_episode(conn, "ep_k1", kit_id="kit_01")
    _seed_episode(conn, "ep_k2", kit_id="kit_01", recording_suspect=1)

    stats = queries.kit_episode_stats(conn, "kit_01")
    assert stats["episode_count"] == 2
    assert stats["suspect_count"] == 1


def test_kit_current_operator(conn: Connection) -> None:
    _seed_kit(conn, "kit_01")
    _seed_person(conn, "op_01", "Alice")
    _seed_session(conn, "sess_01", "op_01", "kit_01", NOW - timedelta(hours=1))

    assert queries.kit_current_operator(conn, "kit_01") == "Alice"


def test_kit_anomalies(conn: Connection) -> None:
    _seed_anomaly(conn, "evt_ka1", "recording_suspect", kit_id="kit_01")
    _seed_anomaly(conn, "evt_ka2", "sidecar_without_footage", kit_id="kit_02")

    anom = queries.kit_anomalies(conn, "kit_01")
    assert len(anom) == 1
    assert anom[0]["anomaly_type"] == "recording_suspect"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def test_task_list(conn: Connection) -> None:
    _seed_task(conn, "t_01", "Wash")
    _seed_task(conn, "t_02", "Fold")
    _seed_kit(conn, "kit_01")
    _seed_person(conn, "op_01", "Alice")
    _seed_episode(conn, "ep_t1", task_id="t_01", archive=5400)
    _seed_episode(conn, "ep_t2", task_id="t_02", archive=2700)

    tasks = queries.task_list(conn)
    assert len(tasks) >= 2
    first = tasks[0]
    assert first["hours"] >= tasks[1]["hours"]


def test_task_detail(conn: Connection) -> None:
    _seed_task(conn, "t_01", "Wash")
    _seed_kit(conn, "kit_01")
    _seed_person(conn, "op_01", "Alice")
    _seed_episode(conn, "ep_td1", task_id="t_01", archive=3600)

    task = queries.task_detail(conn, "t_01")
    assert task is not None
    assert task["episode_count"] == 1
    assert task["hours"] == round(3600 / 30 / 3600, 1)


def test_task_detail_not_found(conn: Connection) -> None:
    assert queries.task_detail(conn, "nonexistent") is None


def test_task_operators(conn: Connection) -> None:
    _seed_task(conn, "t_01", "Wash")
    _seed_kit(conn, "kit_01")
    _seed_person(conn, "op_01", "Alice")
    _seed_person(conn, "op_02", "Bob")
    _seed_episode(conn, "ep_to1", task_id="t_01", person_id="op_01", archive=3600)
    _seed_episode(
        conn,
        "ep_to2",
        task_id="t_01",
        person_id="op_02",
        archive=1800,
        recording_suspect=1,
    )

    ops = queries.task_operators(conn, "t_01")
    assert len(ops) == 2
    bob = next(o for o in ops if o["person_id"] == "op_02")
    assert bob["quality_pct"] == 0.0


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


def test_anomaly_feed_ordering(conn: Connection) -> None:
    _seed_anomaly(conn, "evt_f1", "recording_suspect")
    _seed_anomaly(conn, "evt_f2", "sidecar_without_footage")

    feed = queries.anomaly_feed(conn)
    assert len(feed) >= 2


def test_anomaly_feed_filter_by_type(conn: Connection) -> None:
    _seed_anomaly(conn, "evt_ft1", "recording_suspect")
    _seed_anomaly(conn, "evt_ft2", "sidecar_without_footage")

    feed = queries.anomaly_feed(conn, anomaly_type="recording_suspect")
    assert all(a["anomaly_type"] == "recording_suspect" for a in feed)


def test_anomaly_feed_filter_by_kit(conn: Connection) -> None:
    _seed_anomaly(conn, "evt_fk1", "recording_suspect", kit_id="kit_01")
    _seed_anomaly(conn, "evt_fk2", "recording_suspect", kit_id="kit_02")

    feed = queries.anomaly_feed(conn, kit_id="kit_01")
    assert all(a["kit_id"] == "kit_01" for a in feed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_frames_to_seconds() -> None:
    assert queries.frames_to_seconds(30) == 1.0
    assert queries.frames_to_seconds(0) == 0.0
    assert queries.frames_to_seconds(None) == 0.0


def test_frames_to_hours() -> None:
    assert queries.frames_to_hours(30 * 3600) == 1.0


# ---------------------------------------------------------------------------
# Pipeline health
# ---------------------------------------------------------------------------


def test_pipeline_health_empty(conn: Connection) -> None:
    since = datetime(2020, 1, 1, tzinfo=UTC)
    health = queries.pipeline_health(conn, since)
    assert health["total_episodes"] == 0
    assert health["ingested"] == 0
    assert health["normalized"] == 0
    assert health["qc_complete"] == 0
    assert health["synced"] == 0


def test_pipeline_health_funnel_counts(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")

    # ep1: fully through normalize + QC
    _seed_episode(
        conn,
        "ep_ph1",
        recorded_at=NOW - timedelta(hours=3),
        ingested_at=NOW - timedelta(hours=2),
    )
    append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": "evt_fn_ph1",
            "event_type": "footage_normalized",
            "entity": "episode",
            "entity_id": "ep_ph1",
            "as_of": _iso(NOW - timedelta(hours=1, minutes=30)),
            "payload": {"normalized_path": "/tmp/test.mp4"},
        },
    )
    append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": "evt_qv_ph1",
            "event_type": "qa_verdict",
            "entity": "episode",
            "entity_id": "ep_ph1",
            "as_of": _iso(NOW - timedelta(hours=1)),
            "payload": {"verdict": "accept"},
        },
    )

    # ep2: ingested only (not normalized)
    _seed_episode(
        conn,
        "ep_ph2",
        recorded_at=NOW - timedelta(hours=2),
        ingested_at=NOW - timedelta(hours=1, minutes=30),
    )

    # ep3: recorded only (not ingested)
    _seed_episode(conn, "ep_ph3", recorded_at=NOW - timedelta(hours=1))

    since = datetime(2020, 1, 1, tzinfo=UTC)
    health = queries.pipeline_health(conn, since)
    assert health["total_episodes"] == 3
    assert health["ingested"] == 2
    assert health["normalized"] == 1
    assert health["qc_complete"] == 1
    assert health["synced"] == 0


def test_pipeline_health_latency_values(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")

    _seed_episode(
        conn,
        "ep_lat1",
        recorded_at=NOW - timedelta(hours=2),
        ingested_at=NOW - timedelta(hours=1),
    )

    since = datetime(2020, 1, 1, tzinfo=UTC)
    health = queries.pipeline_health(conn, since)
    assert health["median_drain_to_ingest_min"] is not None
    assert health["median_drain_to_ingest_min"] > 0


def test_pipeline_stalls(conn: Connection) -> None:
    _seed_person(conn, "op_01", "Alice")
    _seed_kit(conn, "kit_01")
    _seed_task(conn, "t_01", "Wash")

    # Episode with no ingested_at -> awaiting_ingest
    _seed_episode(conn, "ep_ps1", recorded_at=NOW - timedelta(hours=1))
    # Episode ingested but not normalized -> awaiting_normalize
    _seed_episode(
        conn,
        "ep_ps2",
        recorded_at=NOW - timedelta(hours=2),
        ingested_at=NOW - timedelta(hours=1),
    )

    stalls = queries.pipeline_stalls(conn)
    by_stage = {s["stage"]: s for s in stalls}
    assert by_stage["awaiting_ingest"]["count"] >= 1
    assert by_stage["awaiting_normalize"]["count"] >= 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_format_duration() -> None:
    assert queries.format_duration(30) == "1s"
    assert queries.format_duration(30 * 90) == "1m 30s"
    assert queries.format_duration(30 * 3660) == "1h 01m"
    assert queries.format_duration(0) == "0s"
    assert queries.format_duration(None) == "0s"
