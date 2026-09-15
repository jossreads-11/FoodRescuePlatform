"""Typed exceptions for the matching engine.

Kept separate from Pydantic's ValidationError so callers can catch
engine-specific problems without depending on pydantic internals.
"""


class MatchingEngineError(Exception):
    """Base class for all matching-engine errors."""


class InvalidInputError(MatchingEngineError):
    """Raised when donation/NGO/route input fails validation."""


class InvalidWeightsError(MatchingEngineError):
    """Raised when a MatchingWeights configuration is invalid."""


class RouteDataError(MatchingEngineError):
    """Raised when route metrics are missing or malformed for a candidate
    that the caller expected to be scoreable."""
