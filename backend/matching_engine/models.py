"""Domain models for the matching engine.

These mirror the frozen contract shared with Person 1 (backend),
Person 3 (NGO module) and Person 5 (routing). They have no dependency
on the ORM, FastAPI, or any database session — they are plain
Pydantic models constructed from dicts/JSON, so the engine can be
tested entirely against fixtures.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class FoodCategory(str, Enum):
    COOKED = "COOKED"
    PACKAGED = "PACKAGED"
    PRODUCE = "PRODUCE"
    BAKERY = "BAKERY"
    DAIRY = "DAIRY"
    OTHER = "OTHER"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Location(BaseModel):
    latitude: float
    longitude: float

    @field_validator("latitude")
    @classmethod
    def _lat_range(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("latitude must be within [-90, 90]")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon_range(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("longitude must be within [-180, 180]")
        return v


class Donation(BaseModel):
    id: str
    food_category: FoodCategory
    quantity_kg: float
    pickup_location: Location
    available_from: datetime
    expiry_time: datetime

    @field_validator("quantity_kg")
    @classmethod
    def _qty_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity_kg must be > 0")
        return v

    @field_validator("available_from", "expiry_time")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware UTC")
        return v

    @model_validator(mode="after")
    def _expiry_after_available(self) -> "Donation":
        if self.expiry_time <= self.available_from:
            raise ValueError("expiry_time must be after available_from")
        return self


class OperatingHours(BaseModel):
    start: str  # "HH:MM", 24h
    end: str

    @field_validator("start", "end")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        try:
            h_str, m_str = v.split(":")
            h, m = int(h_str), int(m_str)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception as exc:
            raise ValueError(f"invalid HH:MM operating-hours time: {v!r}") from exc
        return v


class NGODemand(BaseModel):
    food_category: FoodCategory
    required_quantity_kg: float = Field(ge=0)
    priority: Priority = Priority.MEDIUM
    valid_until: Optional[datetime] = None

    @field_validator("valid_until")
    @classmethod
    def _tz_aware_or_none(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("valid_until must be timezone-aware UTC")
        return v


class NGOCandidate(BaseModel):
    ngo_id: str
    location: Location
    available_capacity_kg: float = Field(ge=0)
    accepted_categories: list[FoodCategory]
    operating_hours: OperatingHours
    is_verified: bool
    demand: Optional[NGODemand] = None
    storage_capacity_kg: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _capacity_within_storage(self) -> "NGOCandidate":
        if self.storage_capacity_kg is not None and self.available_capacity_kg > self.storage_capacity_kg:
            raise ValueError("available_capacity_kg cannot exceed storage_capacity_kg")
        return self


class RouteMetrics(BaseModel):
    ngo_id: str
    distance_km: float = Field(ge=0)
    duration_minutes: float = Field(ge=0)
    traffic_duration_minutes: Optional[float] = Field(default=None, ge=0)


class MatchingWeights(BaseModel):
    """w1..w5, versioned per city / food category (matching_weights_history)."""

    weights_version_id: str
    w_capacity: float
    w_shelf_life: float
    w_transit: float
    w_demand: float
    w_route: float

    @model_validator(mode="after")
    def _validate_weights(self) -> "MatchingWeights":
        for name in ("w_capacity", "w_shelf_life", "w_transit", "w_demand", "w_route"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        total = self.w_capacity + self.w_shelf_life + self.w_transit + self.w_demand + self.w_route
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"matching weights must sum to 1.0 (got {total:.6f}) for "
                f"weights_version_id={self.weights_version_id!r}. Weights are "
                f"not silently renormalized — fix the configuration row."
            )
        return self
