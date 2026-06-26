"""SQLAlchemy Engine factory (psycopg3 driver).

``sslmode`` is merged into the URL so the connection is TLS-capable (NOTE prod-bar a). A bare
``postgresql://`` DSN is coerced to the ``postgresql+psycopg`` (psycopg3) driver so callers need not
remember it.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine, make_url

from eunomia_edge_store.config import StoreConfig


def resolve_url(config: StoreConfig) -> sa.URL:
    url = make_url(config.dsn)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    if config.sslmode and "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": config.sslmode})
    return url


def make_engine(config: StoreConfig, *, echo: bool = False, **kwargs: Any) -> Engine:
    return sa.create_engine(resolve_url(config), echo=echo, **kwargs)
