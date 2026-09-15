"""Produces the exact, frozen public response contract.

Field names and envelope shape here are treated as frozen per the API
contract: data.donation_id, data.weights_version_id, data.matches[].
{score, capacity_score, shelf_life_score, transit_score, demand_score,
route_score, ngo_id, eta_minutes}. Nothing renamed, nothing added.
"""
from __future__ import annotations

from .optimizer import MatchingResult


def serialize_matching_result(result: MatchingResult) -> dict:
    """GET /api/v1/matching/{donation_id}/candidates response body.

    Internal diagnostics (result.rejections) are intentionally NOT
    included — they exist for explainability/admin tooling only.
    """
    return {
        "data": {
            "donation_id": result.donation_id,
            "weights_version_id": result.weights_version_id,
            "matches": [
                {
                    "ngo_id": m.ngo_id,
                    "score": m.score,
                    "capacity_score": m.capacity_score,
                    "shelf_life_score": m.shelf_life_score,
                    "transit_score": m.transit_score,
                    "demand_score": m.demand_score,
                    "route_score": m.route_score,
                    "eta_minutes": m.eta_minutes,
                }
                for m in result.matches
            ],
        }
    }
