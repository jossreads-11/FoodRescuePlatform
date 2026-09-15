"""Route-provider adapter.

Person 5 owns the actual routing engine. Person 4's core scoring code
never calls a maps API and never implements a fake routing engine —
it only consumes a dict[ngo_id -> RouteMetrics] that some adapter here
produced. Swap the adapter, not the algorithm.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .models import Donation, NGOCandidate, RouteMetrics


class RouteProvider(ABC):
    """Adapter interface. Person 1's service layer implements/wires the
    real one (typically calling Person 5's `/routes/calculate`)."""

    @abstractmethod
    def get_routes(
        self, donation: Donation, ngos: Iterable[NGOCandidate]
    ) -> dict[str, RouteMetrics]:
        """Return route metrics keyed by ngo_id for the given candidates."""
        raise NotImplementedError


class StaticRouteProvider(RouteProvider):
    """Wraps route metrics the caller already fetched (e.g. from Person
    5's API response), so the engine can be called with plain data."""

    def __init__(self, routes: Iterable[RouteMetrics]) -> None:
        self._routes: dict[str, RouteMetrics] = {}
        for route in routes:
            self._routes[route.ngo_id] = route  # last write wins on duplicates

    def get_routes(
        self, donation: Donation, ngos: Iterable[NGOCandidate]
    ) -> dict[str, RouteMetrics]:
        return dict(self._routes)


class MockRouteProvider(RouteProvider):
    """Deterministic mock for unit tests. Never calls an external API."""

    def __init__(self, fixed: dict[str, RouteMetrics]) -> None:
        self._fixed = dict(fixed)

    def get_routes(
        self, donation: Donation, ngos: Iterable[NGOCandidate]
    ) -> dict[str, RouteMetrics]:
        return dict(self._fixed)
