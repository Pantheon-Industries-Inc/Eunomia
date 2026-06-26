"""Eunomia edge operational store (Run S1).

Persists the ``contracts/operational/`` model as current-state records + an append-only event log.
Topology-agnostic (a Postgres reachable by DSN). The tables are DERIVED from the contract
(``eunomia_contracts``) — never hand-written (NOTE F8). Depends only on ``contracts/``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.0.0"
