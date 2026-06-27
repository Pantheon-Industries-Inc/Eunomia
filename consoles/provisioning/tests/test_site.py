"""Tests for site-binding validation."""

from __future__ import annotations

from eunomia_consoles_provisioning.site import validate_site_binding


def test_matching_sites() -> None:
    result = validate_site_binding("site-01", "site-01")
    assert result.valid


def test_mismatched_sites() -> None:
    result = validate_site_binding("site-01", "site-02")
    assert not result.valid
    assert "mismatch" in result.reason.lower()


def test_empty_fob_site() -> None:
    result = validate_site_binding("", "site-01")
    assert not result.valid
    assert "no site_id" in result.reason.lower()


def test_result_carries_ids() -> None:
    result = validate_site_binding("a", "b")
    assert result.fob_site_id == "a"
    assert result.request_site_id == "b"
