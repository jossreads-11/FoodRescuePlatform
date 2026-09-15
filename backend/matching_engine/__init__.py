"""Person 4 — Matching & Optimisation Engine.

Pure, testable Python. No database session, ORM, frontend, or auth
dependency anywhere in this package. See README.md at the project root
for the algorithm explanation, complexity analysis, and integration
instructions for Person 1.
"""
from .optimizer import match, MatchingResult, ScoredMatch
from .rematching import rematch
from .serializers import serialize_matching_result
from .models import (
    Donation,
    NGOCandidate,
    NGODemand,
    Location,
    OperatingHours,
    RouteMetrics,
    MatchingWeights,
    FoodCategory,
    Priority,
)
from .config import MatchingConfig, DEFAULT_CONFIG
from .candidate_filter import RejectionReason
from .route_provider import RouteProvider, StaticRouteProvider, MockRouteProvider
from .exceptions import (
    MatchingEngineError,
    InvalidInputError,
    InvalidWeightsError,
    RouteDataError,
)

__all__ = [
    "match",
    "rematch",
    "serialize_matching_result",
    "MatchingResult",
    "ScoredMatch",
    "Donation",
    "NGOCandidate",
    "NGODemand",
    "Location",
    "OperatingHours",
    "RouteMetrics",
    "MatchingWeights",
    "FoodCategory",
    "Priority",
    "MatchingConfig",
    "DEFAULT_CONFIG",
    "RejectionReason",
    "RouteProvider",
    "StaticRouteProvider",
    "MockRouteProvider",
    "MatchingEngineError",
    "InvalidInputError",
    "InvalidWeightsError",
    "RouteDataError",
]
