"""Optional database connection for the ops dashboard.

The provisioning console starts without a database — the bench UI routes work fine. When
``EUNOMIA_STORE_DSN`` is set, the ops dashboard connects to S1. When it is not set, ops routes
return a 503-equivalent "store unavailable" page.
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Connection, Engine

from eunomia_edge_store.config import StoreConfig, StoreConfigError
from eunomia_edge_store.engine import make_engine

log = logging.getLogger(__name__)

_engine: Engine | None = None
_init_attempted: bool = False


def _ensure_engine() -> Engine | None:
    global _engine, _init_attempted  # noqa: PLW0603
    if _init_attempted:
        return _engine
    _init_attempted = True
    try:
        config = StoreConfig.from_env()
        _engine = make_engine(config, pool_pre_ping=True)
        log.info("Ops dashboard: connected to store")
    except StoreConfigError:
        log.info(
            "Ops dashboard: EUNOMIA_STORE_DSN not set — ops routes will show unavailable"
        )
        _engine = None
    return _engine


def get_conn() -> Connection | None:
    engine = _ensure_engine()
    if engine is None:
        return None
    return engine.connect()
