"""DB-backed tests for SYNC1 — footage_state transitions and event idempotency.

Marked ``db``: skipped without ``EUNOMIA_STORE_TEST_DSN``, run via ``make gates-db``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from eunomia_edge_store.config import DSN_ENV, TEST_DSN_ENV, StoreConfig
from eunomia_edge_store.engine import make_engine

pytestmark = pytest.mark.db

DNS_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

MIGRATIONS = Path(__file__).resolve().parent.parent.parent / "store" / "migrations"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    dsn = os.environ.get(TEST_DSN_ENV)
    if not dsn:
        pytest.skip(f"{TEST_DSN_ENV} not set — DB-backed sync tests need a Postgres")
    eng = make_engine(StoreConfig(dsn=dsn))
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
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


def _mint_event_id(episode_id: str, event_type: str) -> str:
    return str(uuid.uuid5(DNS_NS, f"sync:{episode_id}:{event_type}"))


def _insert_footage_ref(
    conn: Connection,
    episode_id: str,
    footage_state: str = "on_styx",
    spot_check: bool = False,
) -> None:
    conn.execute(
        text("""
            INSERT INTO footage_reference (episode_id, footage_state, spot_check_selected)
            VALUES (:eid, :state, :spot)
            ON CONFLICT (episode_id) DO UPDATE SET footage_state = :state
        """),
        {"eid": episode_id, "state": footage_state, "spot": spot_check},
    )


def _get_footage_state(conn: Connection, episode_id: str) -> str | None:
    row = conn.execute(
        text("SELECT footage_state FROM footage_reference WHERE episode_id = :eid"),
        {"eid": episode_id},
    ).fetchone()
    return row[0] if row else None


def _update_footage_state(conn: Connection, episode_id: str, new_state: str) -> None:
    conn.execute(
        text("""
            UPDATE footage_reference
            SET footage_state = :state
            WHERE episode_id = :eid AND footage_state != :state
        """),
        {"eid": episode_id, "state": new_state},
    )


def _log_state_transition(conn: Connection, episode_id: str, new_state: str) -> str:
    event_id = _mint_event_id(episode_id, f"sync_state_transition_{new_state}")
    conn.execute(
        text("""
            INSERT INTO operational_event (event_id, entity, entity_id, event_type, as_of, payload)
            VALUES (:eid, 'footage_reference', :entity_id, 'sync_state_transition', NOW(),
                    jsonb_build_object('new_state', :new_state))
            ON CONFLICT (event_id) DO NOTHING
        """),
        {"eid": event_id, "entity_id": episode_id, "new_state": new_state},
    )
    return event_id


class TestFootageStateTransitions:
    def test_on_styx_to_shipped(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_id, "on_styx")
        _update_footage_state(conn, ep_id, "shipped")
        assert _get_footage_state(conn, ep_id) == "shipped"

    def test_shipped_to_on_hades(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_id, "shipped")
        _update_footage_state(conn, ep_id, "on_hades")
        assert _get_footage_state(conn, ep_id) == "on_hades"

    def test_full_sync_lifecycle(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_id, "on_styx")

        _update_footage_state(conn, ep_id, "shipped")
        assert _get_footage_state(conn, ep_id) == "shipped"

        _update_footage_state(conn, ep_id, "on_hades")
        assert _get_footage_state(conn, ep_id) == "on_hades"

    def test_idempotent_update(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_id, "on_hades")
        _update_footage_state(conn, ep_id, "on_hades")
        assert _get_footage_state(conn, ep_id) == "on_hades"

    def test_revert_shipped_to_on_styx(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_id, "shipped")
        _update_footage_state(conn, ep_id, "on_styx")
        assert _get_footage_state(conn, ep_id) == "on_styx"

    def test_no_footage_ref_graceful(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        _update_footage_state(conn, ep_id, "shipped")
        assert _get_footage_state(conn, ep_id) is None


class TestSyncEventLogging:
    def test_event_written(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        event_id = _log_state_transition(conn, ep_id, "shipped")

        row = conn.execute(
            text(
                "SELECT event_type, entity, entity_id FROM operational_event WHERE event_id = :eid"
            ),
            {"eid": event_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "sync_state_transition"
        assert row[1] == "footage_reference"
        assert row[2] == ep_id

    def test_event_idempotent(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        eid1 = _log_state_transition(conn, ep_id, "on_hades")
        eid2 = _log_state_transition(conn, ep_id, "on_hades")
        assert eid1 == eid2

        count = conn.execute(
            text("SELECT COUNT(*) FROM operational_event WHERE event_id = :eid"),
            {"eid": eid1},
        ).scalar()
        assert count == 1

    def test_different_states_different_events(self, conn: Connection) -> None:
        ep_id = str(uuid.uuid4())
        eid_shipped = _log_state_transition(conn, ep_id, "shipped")
        eid_on_hades = _log_state_transition(conn, ep_id, "on_hades")
        assert eid_shipped != eid_on_hades

        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM operational_event WHERE entity_id = :eid AND event_type = 'sync_state_transition'"
            ),
            {"eid": ep_id},
        ).scalar()
        assert count == 2


class TestEpisodeSelection:
    def test_only_on_styx_returned(self, conn: Connection) -> None:
        ep_styx = str(uuid.uuid4())
        ep_hades = str(uuid.uuid4())
        ep_shipped = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_styx, "on_styx")
        _insert_footage_ref(conn, ep_hades, "on_hades")
        _insert_footage_ref(conn, ep_shipped, "shipped")

        rows = conn.execute(
            text("""
                SELECT episode_id FROM footage_reference
                WHERE footage_state = 'on_styx'
                ORDER BY spot_check_selected DESC NULLS LAST, episode_id DESC
            """)
        ).fetchall()
        ids = [r[0] for r in rows]
        assert ep_styx in ids
        assert ep_hades not in ids
        assert ep_shipped not in ids

    def test_spot_check_first(self, conn: Connection) -> None:
        ep_normal = str(uuid.uuid4())
        ep_spot = str(uuid.uuid4())
        _insert_footage_ref(conn, ep_normal, "on_styx", spot_check=False)
        _insert_footage_ref(conn, ep_spot, "on_styx", spot_check=True)

        rows = conn.execute(
            text("""
                SELECT episode_id, spot_check_selected FROM footage_reference
                WHERE footage_state = 'on_styx'
                ORDER BY spot_check_selected DESC NULLS LAST, episode_id DESC
            """)
        ).fetchall()
        assert len(rows) >= 2
        assert rows[0][1] is True
