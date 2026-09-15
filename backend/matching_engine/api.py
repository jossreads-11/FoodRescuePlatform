"""Thin FastAPI wiring for Person 1 to mount (or copy the pattern from).

Contains zero scoring logic. Its only job is: receive request -> load
donation/NGOs via repositories -> load routes via a RouteProvider ->
call matching_engine.match -> serialize -> return. Replace the three
`_load_*` stubs with real repository/service calls.

The matching algorithm must never query the database directly, which
is why those lookups live here and not inside optimizer.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import match, serialize_matching_result
from .models import Donation, MatchingWeights, NGOCandidate, RouteMetrics

router = APIRouter(prefix="/api/v1/matching", tags=["matching"])


@router.get("/{donation_id}/candidates")
async def get_candidates(donation_id: str) -> dict:
    """GET /api/v1/matching/{donation_id}/candidates.

    Consumed by Person 3 (NGO offer screen) and Person 1 (state
    transition to MATCHED / NO_MATCH_FOUND). Example wiring only —
    replace the four lookups below with real calls before shipping.
    """
    donation = await _load_donation(donation_id)
    if donation is None:
        raise HTTPException(status_code=404, detail="donation not found")

    ngos = await _load_active_ngos()
    routes = await _load_routes(donation, ngos)
    weights = await _load_active_weights(donation)

    result = match(
        donation=donation,
        ngos=ngos,
        routes=routes,
        weights=weights,
        reference_time=datetime.now(timezone.utc),
    )
    return serialize_matching_result(result)


async def _load_donation(donation_id: str) -> Donation:
    raise NotImplementedError("wire to Person 1's donation repository")


async def _load_active_ngos() -> list[NGOCandidate]:
    raise NotImplementedError("wire to Person 1's NGO repository")


async def _load_routes(donation: Donation, ngos: list[NGOCandidate]) -> dict[str, RouteMetrics]:
    raise NotImplementedError("wire to a RouteProvider backed by Person 5's routing API")


async def _load_active_weights(donation: Donation) -> MatchingWeights:
    raise NotImplementedError("wire to a matching_weights_history lookup (city + food_category)")
