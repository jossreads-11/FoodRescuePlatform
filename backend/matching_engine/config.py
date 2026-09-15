"""Configuration for the matching engine.

Keeps tunable constants (like ETA_max) out of the scoring code, and
out of scattered magic numbers, per the project's explainability
requirement. MatchingWeights (w1..w5) live in models.py since they are
versioned per city/food-category (matching_weights_history) rather
than a single global config.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MatchingConfig:
    """Non-weight tunables for scoring.

    eta_max_minutes: the ETA at which transit_score and the ETA
        component of route_score bottom out at 0. Configurable per
        deployment/city rather than hard-coded inside scoring.py.
    demand_priority_weighting_enabled: if True, demand_score is
        boosted by `priority_boost[priority]` before clipping to
        [0, 1]. Off by default — priority is informational unless a
        team explicitly opts in, per the "make it explicit" rule.
    priority_boost: multiplier applied to demand_score per Priority
        value, only when demand_priority_weighting_enabled is True.
    """

    eta_max_minutes: float = 60.0
    demand_priority_weighting_enabled: bool = False
    priority_boost: dict = field(
        default_factory=lambda: {
            "LOW": 1.0,
            "MEDIUM": 1.0,
            "HIGH": 1.0,
            "CRITICAL": 1.0,
        }
    )

    def __post_init__(self) -> None:
        if self.eta_max_minutes <= 0:
            raise ValueError("eta_max_minutes must be > 0")


DEFAULT_CONFIG = MatchingConfig()
