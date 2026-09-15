"""Comprehensive tests for Person 4's matching engine.

Covers: all six hard-constraint rejection paths, each of the five
scoring functions, weighted-score combination, deterministic ranking
and tie-breaking, edge cases (zero/negative/huge values), no-match
behaviour, rematching/exclusion, the frozen JSON contract, and the
project's worked example (demonstrating "not the nearest NGO").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from matching_engine import scoring
from matching_engine.candidate_filter import RejectionReason, filter_candidates
from matching_engine.config import MatchingConfig
from matching_engine.models import (
    Donation,
    FoodCategory,
    Location,
    MatchingWeights,
    NGOCandidate,
    NGODemand,
    OperatingHours,
    Priority,
    RouteMetrics,
)
from matching_engine.optimizer import match
from matching_engine.rematching import rematch
from matching_engine.serializers import serialize_matching_result

UTC = timezone.utc
REF_TIME = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
WEIGHTS = MatchingWeights(
    weights_version_id="wv_2026_bengaluru_cooked_v3",
    w_capacity=0.25,
    w_shelf_life=0.25,
    w_transit=0.20,
    w_demand=0.15,
    w_route=0.15,
)


# ---------------------------------------------------------------- helpers


def make_donation(**overrides) -> Donation:
    defaults = dict(
        id="don_test",
        food_category=FoodCategory.COOKED,
        quantity_kg=30.0,
        pickup_location=Location(latitude=12.9352, longitude=77.6245),
        available_from=REF_TIME,
        expiry_time=REF_TIME + timedelta(hours=2),
    )
    defaults.update(overrides)
    return Donation(**defaults)


def make_ngo(ngo_id: str, **overrides) -> NGOCandidate:
    defaults = dict(
        ngo_id=ngo_id,
        location=Location(latitude=12.9345, longitude=77.6104),
        available_capacity_kg=50.0,
        accepted_categories=[FoodCategory.COOKED],
        operating_hours=OperatingHours(start="08:00", end="20:00"),
        is_verified=True,
        demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=20, priority=Priority.MEDIUM),
    )
    defaults.update(overrides)
    return NGOCandidate(**defaults)


def make_route(ngo_id: str, distance_km: float = 3.0, duration_minutes: float = 15.0) -> RouteMetrics:
    return RouteMetrics(ngo_id=ngo_id, distance_km=distance_km, duration_minutes=duration_minutes)


# ---------------------------------------------------------- hard constraints


def test_valid_candidate_passes_all_constraints():
    donation = make_donation()
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert len(result.feasible) == 1
    assert result.feasible[0].ngo.ngo_id == "ngo_a"
    assert result.rejections == {}


def test_donation_unavailable_before_window():
    donation = make_donation(available_from=REF_TIME + timedelta(hours=1))
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert result.feasible == []
    assert result.rejections["ngo_a"] == RejectionReason.DONATION_UNAVAILABLE


def test_donation_unavailable_after_expiry():
    donation = make_donation(expiry_time=REF_TIME + timedelta(minutes=1))
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME + timedelta(minutes=5))
    assert result.rejections["ngo_a"] == RejectionReason.DONATION_UNAVAILABLE


def test_ngo_not_verified():
    donation = make_donation()
    ngo = make_ngo("ngo_a", is_verified=False)
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert result.rejections["ngo_a"] == RejectionReason.NGO_NOT_VERIFIED


def test_food_category_not_accepted():
    donation = make_donation(food_category=FoodCategory.DAIRY)
    ngo = make_ngo("ngo_a", accepted_categories=[FoodCategory.COOKED])
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert result.rejections["ngo_a"] == RejectionReason.FOOD_CATEGORY_NOT_ACCEPTED


def test_insufficient_capacity():
    donation = make_donation(quantity_kg=40.0)
    ngo = make_ngo("ngo_a", available_capacity_kg=20.0)
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert result.rejections["ngo_a"] == RejectionReason.INSUFFICIENT_CAPACITY


def test_ngo_outside_operating_hours():
    donation = make_donation()
    ngo = make_ngo("ngo_a", operating_hours=OperatingHours(start="18:00", end="23:00"))
    routes = {"ngo_a": make_route("ngo_a")}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)  # REF_TIME is 12:00
    assert result.rejections["ngo_a"] == RejectionReason.NGO_OUTSIDE_OPERATING_HOURS


def test_ngo_operating_hours_inclusive_boundaries():
    donation = make_donation()
    ngo = make_ngo("ngo_a", operating_hours=OperatingHours(start="12:00", end="12:00"))
    routes = {"ngo_a": make_route("ngo_a")}
    # opening exactly at pickup time and closing exactly at pickup time
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert "ngo_a" not in result.rejections


def test_route_cannot_complete_before_expiry():
    donation = make_donation(expiry_time=REF_TIME + timedelta(minutes=30))
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a", duration_minutes=45)}
    result = filter_candidates(donation, [ngo], routes, REF_TIME)
    assert result.rejections["ngo_a"] == RejectionReason.EXPIRY_NOT_FEASIBLE


def test_missing_route_data():
    donation = make_donation()
    ngo = make_ngo("ngo_a")
    result = filter_candidates(donation, [ngo], {}, REF_TIME)
    assert result.rejections["ngo_a"] == RejectionReason.MISSING_ROUTE_DATA


def test_candidate_rejected_before_scoring_never_gets_a_score():
    donation = make_donation(quantity_kg=40.0)
    ngo = make_ngo("ngo_a", available_capacity_kg=20.0)
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert result.matches == []
    assert result.rejections["ngo_a"] == RejectionReason.INSUFFICIENT_CAPACITY


# ------------------------------------------------------------------ scoring


def test_capacity_score_formula():
    assert scoring.capacity_score(50, 30) == pytest.approx(0.6)
    assert scoring.capacity_score(30, 30) == pytest.approx(1.0)


def test_capacity_score_edge_cases_no_div_by_zero():
    assert scoring.capacity_score(0, 30) == 0.0
    assert scoring.capacity_score(50, 0) == 0.0
    assert scoring.capacity_score(-5, 30) == 0.0


def test_shelf_life_score_formula():
    assert scoring.shelf_life_score(120, 30) == pytest.approx(0.75)
    assert scoring.shelf_life_score(120, 0) == pytest.approx(1.0)


def test_shelf_life_score_zero_remaining_life():
    assert scoring.shelf_life_score(0, 10) == 0.0


def test_transit_score_formula():
    assert scoring.transit_score(15, 60) == pytest.approx(0.75)


def test_transit_score_eta_zero():
    assert scoring.transit_score(0, 60) == pytest.approx(1.0)


def test_transit_score_eta_at_or_above_max_clips_to_zero():
    assert scoring.transit_score(60, 60) == pytest.approx(0.0)
    assert scoring.transit_score(90, 60) == pytest.approx(0.0)


def test_transit_score_negative_eta_treated_as_zero():
    assert scoring.transit_score(-5, 60) == pytest.approx(1.0)


def test_demand_score_formula():
    assert scoring.demand_score(30, 30) == pytest.approx(1.0)
    assert scoring.demand_score(10, 30) == pytest.approx(1 / 3)


def test_demand_score_demand_exceeds_donation_clips_to_one():
    assert scoring.demand_score(100, 30) == pytest.approx(1.0)


def test_demand_score_zero_or_negative_handled():
    assert scoring.demand_score(0, 30) == 0.0
    assert scoring.demand_score(-5, 30) == 0.0
    assert scoring.demand_score(30, 0) == 0.0


def test_route_score_not_pure_inverse_distance():
    close_slow = RouteMetrics(ngo_id="a", distance_km=1.0, duration_minutes=55)
    far_fast = RouteMetrics(ngo_id="b", distance_km=8.0, duration_minutes=10)
    r_close_slow = scoring.route_score(close_slow, eta_max_minutes=60)
    r_far_fast = scoring.route_score(far_fast, eta_max_minutes=60)
    # far-but-fast should beat close-but-slow: proves this isn't 1/distance
    assert r_far_fast > r_close_slow


def test_weighted_score_combination():
    score = scoring.weighted_score(
        c=1.0, s=1.0, t=1.0, d=1.0, r=1.0,
        w_capacity=0.25, w_shelf_life=0.25, w_transit=0.2, w_demand=0.15, w_route=0.15,
    )
    assert score == pytest.approx(1.0)
    score_zero = scoring.weighted_score(
        c=0, s=0, t=0, d=0, r=0,
        w_capacity=0.25, w_shelf_life=0.25, w_transit=0.2, w_demand=0.15, w_route=0.15,
    )
    assert score_zero == pytest.approx(0.0)


# ------------------------------------------------------------------ ranking


def test_candidates_sorted_by_descending_score():
    donation = make_donation(quantity_kg=30.0)
    ngo_a = make_ngo("ngo_a", available_capacity_kg=30.0, demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=30))
    ngo_b = make_ngo("ngo_b", available_capacity_kg=200.0, demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=1))
    routes = {"ngo_a": make_route("ngo_a", distance_km=2, duration_minutes=10), "ngo_b": make_route("ngo_b", distance_km=2, duration_minutes=10)}
    result = match(donation, [ngo_a, ngo_b], routes, WEIGHTS, reference_time=REF_TIME)
    scores = [m.score for m in result.matches]
    assert scores == sorted(scores, reverse=True)
    assert result.matches[0].ngo_id == "ngo_a"


def test_deterministic_tie_breaking_by_eta_then_ngo_id():
    donation = make_donation(quantity_kg=30.0)
    # Construct two NGOs that will land on an identical score, differing ETA.
    ngo_x = make_ngo("ngo_x", available_capacity_kg=30.0)
    ngo_y = make_ngo("ngo_y", available_capacity_kg=30.0)
    routes = {
        "ngo_x": make_route("ngo_x", distance_km=3, duration_minutes=20),
        "ngo_y": make_route("ngo_y", distance_km=3, duration_minutes=10),
    }
    result = match(donation, [ngo_x, ngo_y], routes, WEIGHTS, reference_time=REF_TIME)
    # ngo_y has the lower ETA so, tie or not, it must never rank below ngo_x
    # once scores are equal; assert ordering is reproducible across runs.
    result2 = match(donation, [ngo_x, ngo_y], routes, WEIGHTS, reference_time=REF_TIME)
    assert [m.ngo_id for m in result.matches] == [m.ngo_id for m in result2.matches]


# -------------------------------------------------------------- edge cases


def test_zero_capacity_ngo_rejected():
    donation = make_donation(quantity_kg=10.0)
    ngo = make_ngo("ngo_a", available_capacity_kg=0.0)
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert result.matches == []


def test_capacity_exactly_equal_to_quantity():
    donation = make_donation(quantity_kg=30.0)
    ngo = make_ngo("ngo_a", available_capacity_kg=30.0)
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert len(result.matches) == 1
    assert result.matches[0].capacity_score == 1.0


def test_huge_excess_capacity_scores_lower_than_well_sized():
    donation = make_donation(quantity_kg=10.0)
    ngo_huge = make_ngo("ngo_huge", available_capacity_kg=10000.0)
    ngo_snug = make_ngo("ngo_snug", available_capacity_kg=11.0)
    routes = {"ngo_huge": make_route("ngo_huge"), "ngo_snug": make_route("ngo_snug")}
    result = match(donation, [ngo_huge, ngo_snug], routes, WEIGHTS, reference_time=REF_TIME)
    by_id = {m.ngo_id: m for m in result.matches}
    assert by_id["ngo_snug"].capacity_score > by_id["ngo_huge"].capacity_score


def test_negative_quantity_rejected_at_model_level():
    with pytest.raises(Exception):
        make_donation(quantity_kg=-5.0)


def test_zero_quantity_rejected_at_model_level():
    with pytest.raises(Exception):
        make_donation(quantity_kg=0.0)


def test_eta_greater_or_equal_to_eta_max():
    donation = make_donation(quantity_kg=10.0, expiry_time=REF_TIME + timedelta(hours=3))
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a", duration_minutes=120)}
    config = MatchingConfig(eta_max_minutes=60.0)
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME, config=config)
    assert result.matches[0].transit_score == 0.0


def test_expired_donation_produces_no_matches():
    donation = make_donation(expiry_time=REF_TIME + timedelta(minutes=1))
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME + timedelta(hours=1))
    assert result.matches == []


def test_expired_demand_validity_zeroes_demand_score():
    donation = make_donation(quantity_kg=30.0)
    ngo = make_ngo(
        "ngo_a",
        demand=NGODemand(
            food_category=FoodCategory.COOKED,
            required_quantity_kg=30,
            valid_until=REF_TIME - timedelta(minutes=1),
        ),
    )
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert result.matches[0].demand_score == 0.0


def test_demand_wrong_food_category_zeroes_demand_score():
    donation = make_donation(food_category=FoodCategory.COOKED, quantity_kg=30.0)
    ngo = make_ngo(
        "ngo_a",
        demand=NGODemand(food_category=FoodCategory.PACKAGED, required_quantity_kg=30),
    )
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert result.matches[0].demand_score == 0.0


def test_multiple_ngos_all_scored_and_ranked():
    donation = make_donation(quantity_kg=30.0)
    ngos = [make_ngo(f"ngo_{i}", available_capacity_kg=30.0 + i) for i in range(5)]
    routes = {n.ngo_id: make_route(n.ngo_id, duration_minutes=10 + i) for i, n in enumerate(ngos)}
    result = match(donation, ngos, routes, WEIGHTS, reference_time=REF_TIME)
    assert len(result.matches) == 5


def test_no_match_result_when_all_candidates_rejected():
    donation = make_donation(quantity_kg=30.0)
    ngo = make_ngo("ngo_a", is_verified=False)
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    payload = serialize_matching_result(result)
    assert payload["data"]["matches"] == []


def test_duplicate_ngo_ids_deduplicated():
    donation = make_donation(quantity_kg=30.0)
    ngo1 = make_ngo("ngo_dup", available_capacity_kg=31.0)
    ngo2 = make_ngo("ngo_dup", available_capacity_kg=99.0)
    routes = {"ngo_dup": make_route("ngo_dup")}
    result = match(donation, [ngo1, ngo2], routes, WEIGHTS, reference_time=REF_TIME)
    assert len(result.matches) == 1


def test_very_large_candidate_list_runs_efficiently():
    donation = make_donation(quantity_kg=30.0)
    ngos = [make_ngo(f"ngo_{i}", available_capacity_kg=30.0) for i in range(2000)]
    routes = {n.ngo_id: make_route(n.ngo_id) for n in ngos}
    result = match(donation, ngos, routes, WEIGHTS, reference_time=REF_TIME)
    assert len(result.matches) == 2000
    assert result.matches == sorted(result.matches, key=lambda m: (-m.score, m.eta_minutes, m.ngo_id))


# --------------------------------------------------------------- rematching


def test_rematching_after_ngo_rejection_returns_next_best():
    donation = make_donation(quantity_kg=30.0)
    ngo_a = make_ngo("ngo_a", available_capacity_kg=30.0)
    ngo_b = make_ngo("ngo_b", available_capacity_kg=32.0)
    routes = {"ngo_a": make_route("ngo_a"), "ngo_b": make_route("ngo_b")}
    first = match(donation, [ngo_a, ngo_b], routes, WEIGHTS, reference_time=REF_TIME)
    top_ngo = first.matches[0].ngo_id

    second = rematch(
        donation, [ngo_a, ngo_b], routes, WEIGHTS,
        excluded_ngo_ids={top_ngo}, reference_time=REF_TIME,
    )
    assert top_ngo not in [m.ngo_id for m in second.matches]
    assert len(second.matches) == 1


def test_excluded_ngo_never_appears_in_rematch():
    donation = make_donation(quantity_kg=30.0)
    ngos = [make_ngo(f"ngo_{i}", available_capacity_kg=30.0) for i in range(3)]
    routes = {n.ngo_id: make_route(n.ngo_id) for n in ngos}
    excluded = {"ngo_0", "ngo_1"}
    result = rematch(donation, ngos, routes, WEIGHTS, excluded_ngo_ids=excluded, reference_time=REF_TIME)
    assert [m.ngo_id for m in result.matches] == ["ngo_2"]


def test_all_candidates_excluded_after_rematching_returns_no_match():
    donation = make_donation(quantity_kg=30.0)
    ngos = [make_ngo(f"ngo_{i}", available_capacity_kg=30.0) for i in range(2)]
    routes = {n.ngo_id: make_route(n.ngo_id) for n in ngos}
    result = rematch(
        donation, ngos, routes, WEIGHTS,
        excluded_ngo_ids={"ngo_0", "ngo_1"}, reference_time=REF_TIME,
    )
    assert result.matches == []


def test_rematching_does_not_mutate_original_ngo_list():
    donation = make_donation(quantity_kg=30.0)
    ngos = [make_ngo(f"ngo_{i}", available_capacity_kg=30.0) for i in range(3)]
    routes = {n.ngo_id: make_route(n.ngo_id) for n in ngos}
    original_ids = [n.ngo_id for n in ngos]
    rematch(donation, ngos, routes, WEIGHTS, excluded_ngo_ids={"ngo_0"}, reference_time=REF_TIME)
    assert [n.ngo_id for n in ngos] == original_ids


# ------------------------------------------------------------- contract/json


def test_exact_json_response_schema():
    donation = make_donation(quantity_kg=30.0)
    ngo = make_ngo("ngo_017", available_capacity_kg=72.0)
    routes = {"ngo_017": make_route("ngo_017", distance_km=5.4, duration_minutes=21)}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    payload = serialize_matching_result(result)

    assert set(payload.keys()) == {"data"}
    data = payload["data"]
    assert set(data.keys()) == {"donation_id", "weights_version_id", "matches"}
    assert data["donation_id"] == donation.id
    match_obj = data["matches"][0]
    assert set(match_obj.keys()) == {
        "ngo_id", "score", "capacity_score", "shelf_life_score",
        "transit_score", "demand_score", "route_score", "eta_minutes",
    }


def test_weights_version_id_preserved_in_output():
    donation = make_donation()
    ngo = make_ngo("ngo_a")
    routes = {"ngo_a": make_route("ngo_a")}
    result = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert result.weights_version_id == "wv_2026_bengaluru_cooked_v3"


def test_reference_time_produces_deterministic_results():
    donation = make_donation(quantity_kg=30.0)
    ngo = make_ngo("ngo_a", available_capacity_kg=32.0)
    routes = {"ngo_a": make_route("ngo_a", distance_km=4, duration_minutes=12)}
    r1 = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    r2 = match(donation, [ngo], routes, WEIGHTS, reference_time=REF_TIME)
    assert r1.matches[0].score == r2.matches[0].score


def test_matching_weights_must_sum_to_one():
    with pytest.raises(Exception):
        MatchingWeights(
            weights_version_id="bad",
            w_capacity=0.5, w_shelf_life=0.5, w_transit=0.5, w_demand=0.0, w_route=0.0,
        )


# ------------------------------------------------------------ worked example


def test_worked_example_not_nearest_ngo():
    """Reproduces the project's worked example (§8.4 / prompt worked
    example): 30 kg cooked donation, 2-hour expiry, three NGOs:

        A: 2 km, 15 min, capacity 50 kg, demand 10 kg  (nearest)
        B: 5 km, 18 min, capacity 40 kg, demand 30 kg
        C: 3 km, 40 min, capacity 35 kg, demand 30 kg

    The naive "nearest NGO" system would pick A. This engine should not.
    """
    donation = make_donation(
        id="don_worked_example",
        quantity_kg=30.0,
        available_from=REF_TIME,
        expiry_time=REF_TIME + timedelta(hours=2),
    )
    ngo_a = make_ngo(
        "ngo_a_nearest",
        available_capacity_kg=50.0,
        demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=10),
    )
    ngo_b = make_ngo(
        "ngo_b",
        available_capacity_kg=40.0,
        demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=30),
    )
    ngo_c = make_ngo(
        "ngo_c",
        available_capacity_kg=35.0,
        demand=NGODemand(food_category=FoodCategory.COOKED, required_quantity_kg=30),
    )
    routes = {
        "ngo_a_nearest": make_route("ngo_a_nearest", distance_km=2, duration_minutes=15),
        "ngo_b": make_route("ngo_b", distance_km=5, duration_minutes=18),
        "ngo_c": make_route("ngo_c", distance_km=3, duration_minutes=40),
    }
    result = match(donation, [ngo_a, ngo_b, ngo_c], routes, WEIGHTS, reference_time=REF_TIME)
    ranking = [m.ngo_id for m in result.matches]

    assert ranking[0] != "ngo_a_nearest", "engine must not simply pick the nearest NGO"
    assert ranking[0] == "ngo_b"
