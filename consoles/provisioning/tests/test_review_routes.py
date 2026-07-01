"""Smoke tests for QA review routes.

Tests that routes respond correctly when the store is unavailable (no EUNOMIA_STORE_DSN set).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_review_queue_no_db() -> None:
    resp = client.get("/ops/review")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_review_episode_no_db() -> None:
    resp = client.get("/ops/review/ep_nonexistent")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_review_scorecards_no_db() -> None:
    resp = client.get("/ops/review/scorecards")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_review_partial_stats_no_db() -> None:
    resp = client.get("/ops/review/partials/review-stats")
    assert resp.status_code == 200


def test_review_queue_table_partial_no_db() -> None:
    resp = client.get("/ops/review/partials/queue-table")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_review_nav_link() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert 'href="/ops/review"' in resp.text
    assert "Review" in resp.text


def test_review_sub_nav_active() -> None:
    resp = client.get("/ops/review")
    assert resp.status_code == 200


def test_review_queue_with_filters_no_db() -> None:
    resp = client.get(
        "/ops/review?operator_id=op1&auto_verdict=review&human_verdict_filter=unreviewed"
    )
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_review_scorecards_with_period_no_db() -> None:
    resp = client.get("/ops/review/scorecards?period=today")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_overview_includes_review_nav() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert 'href="/ops/review"' in resp.text


def test_submit_verdict_no_db() -> None:
    resp = client.post(
        "/ops/review/ep_test/verdict",
        data={"verdict": "accept", "reviewer": "mo", "comment": "looks good"},
    )
    assert resp.status_code == 503


def test_submit_verdict_invalid_verdict() -> None:
    resp = client.post(
        "/ops/review/ep_test/verdict",
        data={"verdict": "invalid_value", "reviewer": "mo"},
    )
    assert resp.status_code == 400


def test_bulk_accept_no_db() -> None:
    resp = client.post(
        "/ops/review/bulk-accept",
        data={"reviewer": "mo", "episode_ids": ["ep1", "ep2"]},
    )
    assert resp.status_code == 503
