"""Orchestrates candidate filtering, scoring and ranking for one donation.

This is the single entry point (`match`) that Person 1 calls. It is a
pure function: dicts/Pydantic models in, a deterministic ranked result
out. No DB session, ORM, HTTP call, or auth check anywhere in here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import scoring
from .candidate_filter import FeasibleCandidate, RejectionReason, filter_candidates
from .config import DEFAULT_CONFIG, MatchingConfig
from .models import Donation, MatchingWeights, NGOCandidate, RouteMetrics


@dataclass(frozen=True)
class ScoredMatch:
    ngo_id: str
    score: float
    capacity_score: float
    shelf_life_score: float
    transit_score: float
    demand_score: float
    route_score: float
    eta_minutes: float


@dataclass(frozen=True)
class MatchingResult:
    donation_id: str
    weights_version_id: str
    matches: list[ScoredMatch]
    # Internal diagnostics only — never exposed through serializers.py.
    # Lets an admin/explainability layer answer "why was NGO X rejected?"
    rejections: dict[str, RejectionReason]


def _effective_demand_kg(ngo: NGOCandidate, donation: Donation, reference_time: datetime) -> float:
    """Zero out demand that doesn't actually apply, rather than letting a
    mismatched-category or expired demand entry silently inflate a score."""
    demand = ngo.demand
    if demand is None:
        return 0.0
    if demand.food_category != donation.food_category:
        return 0.0
    if demand.valid_until is not None and demand.valid_until < reference_time:
        return 0.0
    if demand.required_quantity_kg < 0:
        return 0.0
    return demand.required_quantity_kg


def _score_candidate(
    candidate: FeasibleCandidate,
    donation: Donation,
    weights: MatchingWeights,
    config: MatchingConfig,
    reference_time: datetime,
) -> ScoredMatch:
    ngo, route = candidate.ngo, candidate.route
    eta = route.traffic_duration_minutes if route.traffic_duration_minutes is not None else route.duration_minutes
    remaining_life_minutes = (donation.expiry_time - reference_time).total_seconds() / 60.0

    c = scoring.capacity_score(ngo.available_capacity_kg, donation.quantity_kg)
    s = scoring.shelf_life_score(remaining_life_minutes, eta)
    t = scoring.transit_score(eta, config.eta_max_minutes)
    demand_kg = _effective_demand_kg(ngo, donation, reference_time)
    d = scoring.demand_score(demand_kg, donation.quantity_kg)
    r = scoring.route_score(route, config.eta_max_minutes)

    overall = scoring.weighted_score(
        c,
        s,
        t,
        d,
        r,
        weights.w_capacity,
        weights.w_shelf_life,
        weights.w_transit,
        weights.w_demand,
        weights.w_route,
    )

    return ScoredMatch(
        ngo_id=ngo.ngo_id,
        score=round(overall, 4),
        capacity_score=round(c, 4),
        shelf_life_score=round(s, 4),
        transit_score=round(t, 4),
        demand_score=round(d, 4),
        route_score=round(r, 4),
        eta_minutes=round(eta),
    )


def _sort_key(m: ScoredMatch) -> tuple:
    """Deterministic ranking: score desc, then ETA asc, then ngo_id asc —
    so equal-score candidates never order randomly across test runs."""
    return (-m.score, m.eta_minutes, m.ngo_id)


def match(
    donation: Donation,
    ngos: list[NGOCandidate],
    routes: dict[str, RouteMetrics],
    weights: MatchingWeights,
    reference_time: Optional[datetime] = None,
    excluded_ngo_ids: Optional[set[str]] = None,
    config: MatchingConfig = DEFAULT_CONFIG,
    top_k: Optional[int] = None,
) -> MatchingResult:
    """Filter, score and rank NGO candidates for a single donation.

    `routes` must already contain route metrics keyed by ngo_id
    (fetched by the caller through a RouteProvider — see
    route_provider.py). This function performs no routing itself.

    Complexity: O(n) filtering, O(n) scoring, O(n log n) sorting, where
    n = len(ngos). See README.md for the full analysis.
    """
    reference_time = reference_time or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware (UTC)")

    filter_result = filter_candidates(
        donation=donation,
        ngos=ngos,
        routes=routes,
        reference_time=reference_time,
        excluded_ngo_ids=excluded_ngo_ids,
    )

    scored = [
        _score_candidate(fc, donation, weights, config, reference_time)
        for fc in filter_result.feasible
    ]
    scored.sort(key=_sort_key)

    if top_k is not None:
        scored = scored[:top_k]

    return MatchingResult(
        donation_id=donation.id,
        weights_version_id=weights.weights_version_id,
        matches=scored,
        rejections=filter_result.rejections,
    )
