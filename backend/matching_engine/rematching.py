"""Automatic rematching after an NGO rejects or cancels.

The donor never has to manually restart matching: Person 1 calls
`rematch` with the accumulated set of excluded NGO ids, and gets back
the next best feasible candidate(s) using the same filter/score/rank
pipeline as the initial match.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import DEFAULT_CONFIG, MatchingConfig
from .models import Donation, MatchingWeights, NGOCandidate, RouteMetrics
from .optimizer import MatchingResult, match


def rematch(
    donation: Donation,
    ngos: list[NGOCandidate],
    routes: dict[str, RouteMetrics],
    weights: MatchingWeights,
    excluded_ngo_ids: set[str],
    reference_time: Optional[datetime] = None,
    config: MatchingConfig = DEFAULT_CONFIG,
    top_k: Optional[int] = None,
) -> MatchingResult:
    """Recalculate ranked candidates after one or more NGO rejections.

    `excluded_ngo_ids` must include every NGO that has rejected/cancelled
    this donation so far — Person 1's service layer is expected to
    accumulate this set across repeated rejections for the same
    donation_id (it is not tracked inside the engine, which is
    stateless). The original `ngos` list is never mutated: filtering
    happens over `ngos` with exclusions applied at filter time, so this
    call is O(n) over the candidate list rather than rebuilding it.

    This is a named, separate integration point from the initial
    `optimizer.match` call so rematching-specific behaviour (e.g. a
    future cool-down window before an NGO can be re-offered a similar
    donation) can be added here later without touching optimizer.py.
    """
    return match(
        donation=donation,
        ngos=ngos,
        routes=routes,
        weights=weights,
        reference_time=reference_time,
        excluded_ngo_ids=excluded_ngo_ids,
        config=config,
        top_k=top_k,
    )
