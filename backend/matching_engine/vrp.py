"""Vehicle Routing Problem — OPTIONAL / STRETCH module.

NOT part of the MVP. Nothing in candidate_filter.py, scoring.py,
optimizer.py, serializers.py, or rematching.py imports this file — the
core single-donation matching engine has zero dependency on VRP.

Only start on this after the MVP pipeline (donation -> hard
constraints -> scoring -> ranking -> best match -> rematching) is
implemented, tested, and integrated with Person 1/3/5.
"""
from __future__ import annotations


class VRPNotImplementedError(NotImplementedError):
    """Raised until the VRP stretch module is implemented."""


def solve_multi_donation_routing(*args, **kwargs):
    """Placeholder for multi-donation / multi-vehicle route optimisation.

    Intended direction (not implemented): treat each accepted match as
    a pickup+dropoff pair, batch pairs per available driver/vehicle
    capacity (see §8.6 of the project brief), and hand the batched stop
    sequence to Person 5's routing engine for ordering. Deliberately
    left unimplemented so it can never delay or complicate the MVP.
    """
    raise VRPNotImplementedError(
        "VRP is a stretch module and is not implemented in the MVP. "
        "Implement only after the core matching engine is complete and tested."
    )
