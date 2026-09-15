# Person 4 — Matching & Optimisation Engine

Complete, integration-ready implementation of the matching/optimisation module for the
6-person Food-Waste Routing Platform, built against `food_rescue_platform_full_project_description.pdf`
and `food_rescue_platform_person_by_person_api_contract.pdf`.

## A. Folder structure

```
matching_engine/
├── __init__.py            # public API surface (match, rematch, serialize_matching_result, models)
├── models.py               # Donation, NGOCandidate, RouteMetrics, MatchingWeights (Pydantic)
├── config.py                # MatchingConfig (ETA_max etc.) — no magic numbers in scoring.py
├── exceptions.py            # MatchingEngineError and friends
├── route_provider.py        # RouteProvider adapter interface (+ Static/Mock implementations)
├── candidate_filter.py      # the six hard constraints, run before any scoring
├── scoring.py                # C, S, T, D, R — five pure, independently testable functions
├── optimizer.py              # match(): filter -> score -> rank, the single entry point
├── serializers.py            # produces the exact frozen JSON contract
├── rematching.py              # rematch(): named entry point for post-rejection rematching
├── vrp.py                      # stretch module, isolated, not implemented, not on MVP path
├── api.py                      # thin FastAPI router — wiring only, zero scoring logic
├── fixtures/
│   ├── donations.json          # 4 sample donations
│   └── ngos.json                # 8 sample NGOs covering every rejection path + rematch cases
└── tests/
    └── test_matching.py        # 48 pytest tests, all passing
```

No file was added beyond what the brief's suggested structure implies; no repository was
supplied to inspect, so this is a fresh, adapter-based module Person 1 can drop into the
existing FastAPI backend without rewriting anything.

## B. Source files

All files are included as attachments alongside this README (see the presented
`matching_engine.zip`, which contains the exact tree above).

## C. Dependencies

Only one runtime dependency beyond the standard library:

```
pydantic>=2
```

Dev/test only:

```
pytest>=8
```

`fastapi` is referenced only inside `api.py` (optional wiring); the core engine
(`candidate_filter.py`, `scoring.py`, `optimizer.py`, `rematching.py`, `serializers.py`)
imports nothing beyond `pydantic` and the standard library, so Person 1 does not need to
install FastAPI just to unit-test or import the algorithm.

## D. FastAPI integration

`api.py` provides `router`, mountable in Person 1's app:

```python
from matching_engine.api import router as matching_router
app.include_router(matching_router)
```

Its three `_load_*` stubs are the only things Person 1 needs to fill in (donation
repository, NGO repository, route provider). The algorithm itself never touches the
database — see §E.

## E. Example usage (how Person 1 calls the engine)

```python
from datetime import datetime, timezone
from matching_engine import (
    Donation, NGOCandidate, NGODemand, Location, OperatingHours,
    RouteMetrics, MatchingWeights, FoodCategory, match, rematch,
    serialize_matching_result,
)

donation = Donation(
    id="don_9931",
    food_category=FoodCategory.COOKED,
    quantity_kg=35.0,
    pickup_location=Location(latitude=12.9352, longitude=77.6245),
    available_from=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
    expiry_time=datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc),
)

ngos = [ ... ]                      # from Person 1's DB, maintained by Person 3
routes = { "ngo_017": RouteMetrics(ngo_id="ngo_017", distance_km=5.4, duration_minutes=21) }
weights = MatchingWeights(
    weights_version_id="wv_2026_bengaluru_cooked_v3",
    w_capacity=0.25, w_shelf_life=0.25, w_transit=0.20, w_demand=0.15, w_route=0.15,
)

result = match(
    donation=donation, ngos=ngos, routes=routes, weights=weights,
    reference_time=datetime.now(timezone.utc),
)
response_json = serialize_matching_result(result)   # -> the exact frozen contract

# On NGO rejection:
result2 = rematch(
    donation=donation, ngos=ngos, routes=routes, weights=weights,
    excluded_ngo_ids={"ngo_017"}, reference_time=datetime.now(timezone.utc),
)
```

`routes` is supplied by the caller — the engine never fetches routes itself. Person 1's
service layer is expected to call Person 5's `/routes/calculate` per candidate (or a batch
equivalent) and wrap the results in a `StaticRouteProvider`, or just build the
`dict[ngo_id, RouteMetrics]` directly.

## F. Exact sample output for the worked example

Donation: 30 kg cooked, 2-hour expiry window. Candidates: A (2 km / 15 min / 50 kg cap /
10 kg demand), B (5 km / 18 min / 40 kg cap / 30 kg demand), C (3 km / 40 min / 35 kg cap /
30 kg demand). Weights: `w_capacity=0.25, w_shelf_life=0.25, w_transit=0.20, w_demand=0.15, w_route=0.15`.

```json
{
  "data": {
    "donation_id": "don_9931",
    "weights_version_id": "wv_2026_bengaluru_cooked_v3",
    "matches": [
      {
        "ngo_id": "ngo_B",
        "score": 0.801,
        "capacity_score": 0.75,
        "shelf_life_score": 0.85,
        "transit_score": 0.7,
        "demand_score": 1.0,
        "route_score": 0.74,
        "eta_minutes": 18
      },
      {
        "ngo_id": "ngo_A",
        "score": 0.6895,
        "capacity_score": 0.6,
        "shelf_life_score": 0.875,
        "transit_score": 0.75,
        "demand_score": 0.3333,
        "route_score": 0.805,
        "eta_minutes": 15
      },
      {
        "ngo_id": "ngo_C",
        "score": 0.6731,
        "capacity_score": 0.8571,
        "shelf_life_score": 0.6667,
        "transit_score": 0.3333,
        "demand_score": 1.0,
        "route_score": 0.5033,
        "eta_minutes": 40
      }
    ]
  }
}
```

NGO B — not A, the nearest option — wins. This is the concrete demonstration that the
system optimises for feasibility and utilisation, not proximity, exactly as specified.

## G. Explanation of the algorithm

1. **Hard-constraint filtering** (`candidate_filter.py`) runs the six checks, in the fixed
   order the brief specifies, before any scoring: donation availability window → NGO
   verification → food-category acceptance → capacity → operating hours → expiry
   feasibility given transit time. Any failure produces an internal `RejectionReason` and
   the candidate is never scored. This is enforced structurally, not by convention: a
   `FeasibleCandidate` object (which scoring consumes) is only ever constructed after all
   six checks pass.

2. **Scoring** (`scoring.py`) computes five independent, explainable factors on a `[0, 1]`
   scale, exactly matching the specified formulas:
   - `C = 1 - |capacity - quantity| / capacity` — rewards an appropriately-sized match.
   - `S = (remaining_life - transit_time) / remaining_life`.
   - `T = 1 - (ETA / ETA_max)`, with `ETA_max` configurable via `MatchingConfig`.
   - `D = min(1, demand / donation_quantity)`, with demand zeroed upstream
     (`optimizer._effective_demand_kg`) when the NGO's demand entry doesn't apply
     (wrong food category, expired `valid_until`, or negative).
   - `R` — a `RouteMetrics`-driven blend of normalized ETA (traffic-aware, when Person 5
     supplies `traffic_duration_minutes`) and normalized distance, deliberately **not**
     `1 / distance`. The 0.7/0.3 blend is an internal implementation detail of `R` and can
     be swapped for a richer traffic/existing-route-plan model later without touching
     `optimizer.py` or the response contract.

3. **Weighted ranking** (`optimizer.py`) combines the five scores via
   `Score = w1*C + w2*S + w3*T + w4*D + w5*R` using a versioned `MatchingWeights`
   configuration (`weights_version_id`), then sorts candidates by score descending, with a
   deterministic tie-break of ETA ascending, then `ngo_id` ascending.

4. **Serialization** (`serializers.py`) produces the exact, frozen JSON contract —
   `data.donation_id`, `data.weights_version_id`, `data.matches[]` with the exact field
   names specified. No renaming (`score`, not `match_score`), no extra required fields,
   `matches: []` for the no-match case.

5. **Rematching** (`rematching.py`) is a named wrapper around the same `match()` pipeline,
   called with an accumulated `excluded_ngo_ids` set. The original `ngos` list is never
   mutated — exclusion is applied during filtering, so a fresh `FilterResult` is computed
   cleanly each time.

## H. Complexity analysis

Let `n` = number of candidate NGOs for a donation.

- **Filtering**: `O(n)` — each NGO passes through the six checks once, in constant time
  per check (a dict lookup for route data, a set lookup for exclusion/dedup, a
  string-split-and-compare for operating hours).
- **Scoring**: `O(n)` — five `O(1)` formulas per feasible candidate.
- **Ranking**: `O(n log n)` — a single Python `list.sort()` with a tuple key.
- **Rematching**: `O(n)` over the candidate list, same as a fresh match (the exclusion set
  is applied during the single filtering pass, not as a second pass).
- **Space**: `O(n)` for the feasible-candidate list and the rejection-diagnostics dict.

No repeated datetime parsing (operating-hours strings are parsed once per candidate per
call, not cached across calls, since Pydantic re-validates on each object construction —
this is a reasonable choice for correctness over the marginal cost, given `n` is a
candidate-NGO count in the tens to low hundreds per donation, not millions). No route
requests happen inside the engine at all — `routes` is caller-supplied. Verified against a
2,000-candidate synthetic list in `test_very_large_candidate_list_runs_efficiently`, which
completes in a few milliseconds.

## I. Testing instructions

```bash
pip install -r requirements.txt   # pydantic, pytest
python -m pytest matching_engine/tests/test_matching.py -v
```

48 tests, all passing, covering: all six hard-constraint rejection paths (with a dedicated
test for inclusive operating-hours boundaries), each of the five scoring formulas and their
edge cases (zero/negative/huge capacity, ETA at/above `ETA_max`, demand exceeding donation
quantity, expired/mismatched demand), deterministic ranking and tie-breaking, a
2,000-candidate performance smoke test, full rematching behaviour (including
non-mutation of the input list and "all excluded → no match"), the exact frozen JSON
schema, `weights_version_id` preservation, reference-time determinism, weights-sum
validation, and the project's worked example.

## J. Integration instructions for Person 1

1. Copy `matching_engine/` into the backend repository (e.g. `backend/app/matching_engine/`).
2. Add `pydantic>=2` to the backend's dependencies if not already present (FastAPI already
   depends on it).
3. Implement a `RouteProvider` (or just build a `dict[str, RouteMetrics]` directly) that
   calls Person 5's `/routes/calculate` per candidate — or reuse `StaticRouteProvider`
   once you already have the route responses.
4. Look up the active `MatchingWeights` row from `matching_weights_history` for the
   donation's city + food_category.
5. Call `matching_engine.match(...)`, then `matching_engine.serialize_matching_result(...)`,
   and return that dict directly as the `GET /api/v1/matching/{donation_id}/candidates`
   response body — no further transformation needed.
6. On `POST /matching/{donation_id}/reject`, accumulate the rejecting `ngo_id` into a
   per-donation excluded set (e.g. a column or a Redis set keyed by `donation_id`) and call
   `matching_engine.rematch(...)` with that set.
7. **Concurrency**: matching is a recommendation only. Person 1 must perform the
   transactional row-level lock (`SELECT ... FOR UPDATE`) and state transition at
   `POST /matching/{donation_id}/accept` time, and return `409 Conflict` on a race — this
   engine does not and should not attempt that.
8. If no candidate survives filtering, `result.matches == []`; serialize as normal and let
   Person 1's layer translate that into `NO_MATCH_FOUND`.

## K. Assumptions / ambiguities encountered

1. **Reject reason for exclusion vs. hard-constraint rejection**: the brief lists seven
   rejection-reason codes but doesn't define one for "excluded via rematching." I treated
   exclusion as a pre-filter (excluded NGOs are skipped silently, no diagnostic code),
   since they were never really "candidates" for this matching attempt — least disruptive
   reading, and keeps the seven defined codes exactly as specified.
2. **Route score (`R`) formula**: the brief explicitly rejects `1/distance` but doesn't
   give an exact formula, only "consider distance, ETA, traffic-aware travel time,
   existing route plan." I implemented a deterministic 0.7 (normalized ETA) / 0.3
   (normalized distance) blend as the MVP, isolated behind `scoring.route_score()` so it
   can be replaced with a richer model later without touching `optimizer.py` or the output
   contract.
3. **Demand priority**: the brief says priority "may be useful for tie-breaking or future
   extension" but should not silently change the formula. I left priority informational by
   default (`MatchingConfig.demand_priority_weighting_enabled = False`) rather than folding
   it into `demand_score` — enabling it and defining `priority_boost` multipliers is an
   explicit, documented opt-in for whoever configures the engine later.
2. **Operating-hours boundary**: "opening exactly at pickup time" and "closing exactly at
   pickup time" are treated as feasible (inclusive `start <= t <= end`), since the brief
   lists these as cases the engine must handle safely rather than specifying which side of
   the boundary should reject.
3. **`storage_capacity_kg`**: the API contract's NGO input for Person 4 doesn't include
   it (only `available_capacity_kg`), but §16's data-validation list mentions "available
   capacity <= storage capacity where storage capacity is available." I made
   `storage_capacity_kg` an optional field on `NGOCandidate` with a validator, so the
   constraint is enforced when the field is present and is a no-op when it isn't — no
   change to the required input shape.
4. **No existing repository was provided** alongside the two PDFs, so this is a
   freestanding module built against an adapter interface (`RouteProvider`) rather than
   integrated into any specific existing FastAPI app structure. Per §29 of the prompt, if a
   repository had been attached, its structure would have taken priority for file
   placement.
