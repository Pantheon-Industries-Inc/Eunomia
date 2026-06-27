"""Site-binding seam — represent site identity, DEFER the auth mechanism.

P1: identity-only check (fob_site_id == request_site_id).
The credential type (cert, token, shared secret) is an infra-security decision — follow-on run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SiteBindingResult:
    valid: bool
    fob_site_id: str
    request_site_id: str
    reason: str


def validate_site_binding(fob_site_id: str, request_site_id: str) -> SiteBindingResult:
    """The wrong-site guard.

    P1: identity-only check. The *how* of validation (what credential proves
    the fob belongs to this site) is DEFERRED to infra-security.
    """
    if not fob_site_id:
        return SiteBindingResult(
            valid=False,
            fob_site_id=fob_site_id,
            request_site_id=request_site_id,
            reason="Fob has no site_id provisioned",
        )
    if fob_site_id != request_site_id:
        return SiteBindingResult(
            valid=False,
            fob_site_id=fob_site_id,
            request_site_id=request_site_id,
            reason=f"Site mismatch: fob={fob_site_id}, request={request_site_id}",
        )
    return SiteBindingResult(
        valid=True,
        fob_site_id=fob_site_id,
        request_site_id=request_site_id,
        reason="Site binding valid",
    )
