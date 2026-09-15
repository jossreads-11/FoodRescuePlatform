"""The five explainable scoring factors: C, S, T, D, R.

Every function here is pure, takes primitives (not ORM objects), is
independently unit-testable, and is safe against division-by-zero and
NaN. No machine learning anywhere in this module — the project's
differentiator is explainable constraint satisfaction + weighted
scoring, not a black box.
"""
from __future__ import annotations

from .models import RouteMetrics


def _clip01(x: float) -> float:
    if x != x:  # NaN never survives to the API response
        return 0.0
    return max(0.0, min(1.0, x))


def capacity_score(capacity_kg: float, quantity_kg: float) -> float:
    """C = 1 - |capacity - quantity| / capacity, clipped to [0, 1].

    Rewards an appropriately-sized recipient, not merely "big enough" —
    an NGO with 1000 kg of spare capacity for a 5 kg donation is not a
    perfect match.
    """
    if capacity_kg <= 0 or quantity_kg <= 0:
        return 0.0
    return _clip01(1.0 - abs(capacity_kg - quantity_kg) / capacity_kg)


def shelf_life_score(remaining_life_minutes: float, transit_minutes: float) -> float:
    """S = (remaining_life - transit_time) / remaining_life, clipped to [0, 1].

    By the time this runs, hard-constraint filtering has already
    guaranteed transit_minutes <= remaining_life_minutes for any
    candidate reaching scoring — this function stays safe even if
    called directly with values that violate that invariant.
    """
    if remaining_life_minutes <= 0:
        return 0.0
    transit_minutes = max(0.0, transit_minutes)
    return _clip01((remaining_life_minutes - transit_minutes) / remaining_life_minutes)


def transit_score(eta_minutes: float, eta_max_minutes: float) -> float:
    """T = 1 - (ETA / ETA_max), clipped to [0, 1]. ETA_max is configurable
    (see config.MatchingConfig), never a magic number in this module."""
    if eta_max_minutes <= 0:
        return 0.0
    eta_minutes = max(0.0, eta_minutes)
    return _clip01(1.0 - (eta_minutes / eta_max_minutes))


def demand_score(required_quantity_kg: float, donation_quantity_kg: float) -> float:
    """D = min(1, demand / donation_quantity).

    Callers are responsible for zeroing `required_quantity_kg` upstream
    when the NGO's demand doesn't apply (wrong food category, expired
    validity, negative/missing demand) — see optimizer._effective_demand_kg.
    """
    if donation_quantity_kg <= 0 or required_quantity_kg <= 0:
        return 0.0
    return _clip01(min(1.0, required_quantity_kg / donation_quantity_kg))


def route_score(route: RouteMetrics, eta_max_minutes: float) -> float:
    """R — route/distance efficiency. Deliberately NOT `1 / distance`;
    the brief explicitly rejects a pure nearest-NGO heuristic.

    For the MVP, R blends a normalized ETA (which already reflects live
    traffic when Person 5 supplies traffic_duration_minutes) with
    normalized distance as a secondary signal, so a nearby-but-congested
    route doesn't automatically outrank a farther-but-faster one. This
    blend is an internal implementation detail of R — it is not part of
    the frozen w1..w5 weight vector and can be swapped for a richer
    traffic-aware/existing-route-plan calculation later without
    changing optimizer.py or the response contract.
    """
    eta = route.traffic_duration_minutes if route.traffic_duration_minutes is not None else route.duration_minutes
    eta_component = transit_score(eta, eta_max_minutes)

    # Distance is normalized against a generous, config-derived reference
    # so it acts as a secondary signal rather than a nearest-NGO heuristic.
    distance_reference_km = max(eta_max_minutes / 2.0, 1.0)
    distance_component = _clip01(1.0 - (route.distance_km / distance_reference_km))

    return _clip01(0.7 * eta_component + 0.3 * distance_component)


def weighted_score(
    c: float,
    s: float,
    t: float,
    d: float,
    r: float,
    w_capacity: float,
    w_shelf_life: float,
    w_transit: float,
    w_demand: float,
    w_route: float,
) -> float:
    """Score(D, N) = w1*C + w2*S + w3*T + w4*D + w5*R, clipped to [0, 1]."""
    return _clip01(
        w_capacity * c + w_shelf_life * s + w_transit * t + w_demand * d + w_route * r
    )
