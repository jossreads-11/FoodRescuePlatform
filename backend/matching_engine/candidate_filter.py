"""Hard-constraint filtering — runs before any scoring.

A candidate that fails any of the six checks below is never scored.
Order is fixed and matches the project brief exactly:

    1. Food available?
    2. NGO eligible?
    3. Food category accepted?
    4. Enough capacity?
    5. NGO operational?
    6. Can pickup happen before expiry?
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Optional

from .models import Donation, NGOCandidate, RouteMetrics


class RejectionReason(str, Enum):
    DONATION_UNAVAILABLE = "DONATION_UNAVAILABLE"
    NGO_NOT_VERIFIED = "NGO_NOT_VERIFIED"
    FOOD_CATEGORY_NOT_ACCEPTED = "FOOD_CATEGORY_NOT_ACCEPTED"
    INSUFFICIENT_CAPACITY = "INSUFFICIENT_CAPACITY"
    NGO_OUTSIDE_OPERATING_HOURS = "NGO_OUTSIDE_OPERATING_HOURS"
    EXPIRY_NOT_FEASIBLE = "EXPIRY_NOT_FEASIBLE"
    MISSING_ROUTE_DATA = "MISSING_ROUTE_DATA"


@dataclass(frozen=True)
class FeasibleCandidate:
    """A candidate that survived every hard constraint, paired with the
    route metrics used to prove check #6 — reused later for scoring so
    route data is never parsed/fetched twice."""

    ngo: NGOCandidate
    route: RouteMetrics


@dataclass(frozen=True)
class FilterResult:
    feasible: list[FeasibleCandidate]
    rejections: dict[str, RejectionReason]  # internal diagnostics only


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _is_within_operating_hours(ngo: NGOCandidate, at: datetime) -> bool:
    start = _parse_hhmm(ngo.operating_hours.start)
    end = _parse_hhmm(ngo.operating_hours.end)
    t = at.time()
    if start <= end:
        return start <= t <= end
    # Overnight window (e.g. 22:00-06:00): feasible outside the gap.
    return t >= start or t <= end


def filter_candidates(
    donation: Donation,
    ngos: list[NGOCandidate],
    routes: dict[str, RouteMetrics],
    reference_time: datetime,
    excluded_ngo_ids: Optional[set[str]] = None,
) -> FilterResult:
    """Apply the six hard constraints, in order, to every candidate.

    O(n) over the candidate list. Duplicate ngo_id entries in `ngos`
    keep only the first occurrence (deterministic). Candidates in
    `excluded_ngo_ids` (used by rematching) are skipped entirely and do
    not appear in the rejection diagnostics.
    """
    excluded_ngo_ids = excluded_ngo_ids or set()
    feasible: list[FeasibleCandidate] = []
    rejections: dict[str, RejectionReason] = {}
    seen_ids: set[str] = set()

    # 1. Food available? — donation-level check, same result for every
    # candidate, so compute once rather than per-candidate.
    donation_available = donation.available_from <= reference_time < donation.expiry_time
    remaining_life_minutes = (donation.expiry_time - reference_time).total_seconds() / 60.0

    for ngo in ngos:
        if ngo.ngo_id in seen_ids or ngo.ngo_id in excluded_ngo_ids:
            continue
        seen_ids.add(ngo.ngo_id)

        if not donation_available:
            rejections[ngo.ngo_id] = RejectionReason.DONATION_UNAVAILABLE
            continue

        # 2. NGO eligible?
        if not ngo.is_verified:
            rejections[ngo.ngo_id] = RejectionReason.NGO_NOT_VERIFIED
            continue

        # 3. Food category accepted?
        if donation.food_category not in ngo.accepted_categories:
            rejections[ngo.ngo_id] = RejectionReason.FOOD_CATEGORY_NOT_ACCEPTED
            continue

        # 4. Enough capacity?
        if ngo.available_capacity_kg <= 0 or ngo.available_capacity_kg < donation.quantity_kg:
            rejections[ngo.ngo_id] = RejectionReason.INSUFFICIENT_CAPACITY
            continue

        # 5. NGO operational?
        if not _is_within_operating_hours(ngo, reference_time):
            rejections[ngo.ngo_id] = RejectionReason.NGO_OUTSIDE_OPERATING_HOURS
            continue

        # 6. Can pickup happen before expiry?
        route = routes.get(ngo.ngo_id)
        if route is None:
            rejections[ngo.ngo_id] = RejectionReason.MISSING_ROUTE_DATA
            continue

        transit_minutes = (
            route.traffic_duration_minutes
            if route.traffic_duration_minutes is not None
            else route.duration_minutes
        )
        if transit_minutes < 0 or transit_minutes > remaining_life_minutes:
            rejections[ngo.ngo_id] = RejectionReason.EXPIRY_NOT_FEASIBLE
            continue

        feasible.append(FeasibleCandidate(ngo=ngo, route=route))

    return FilterResult(feasible=feasible, rejections=rejections)
