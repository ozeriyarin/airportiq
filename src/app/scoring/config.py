"""config/scoring.yaml → ScoringConfig. Validated at load; the version string travels with every result."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import CONFIG_DIR

CAPACITY_SOURCES = ("faa_service_volume", "faa_profile", "runway_model")


class Window(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.end < self.start:
            raise ValueError("window end before start")
        return self


class RunwayModelConfig(BaseModel):
    features: list[str] = Field(min_length=1)


class CapacityConfig(BaseModel):
    source_order: list[str]
    profile_blend: dict[str, float]
    annual_hours_equivalent: int = Field(gt=0)
    runway_model: RunwayModelConfig

    @model_validator(mode="after")
    def _checks(self) -> CapacityConfig:
        if set(self.source_order) != set(CAPACITY_SOURCES):
            raise ValueError(f"capacity.source_order must list exactly {CAPACITY_SOURCES}")
        if set(self.profile_blend) != {"visual", "marginal", "instrument"} or abs(sum(self.profile_blend.values()) - 1) > 1e-6:
            raise ValueError("capacity.profile_blend must weight visual, marginal and instrument to 1.0")
        return self


class Component(BaseModel):
    weight: float = Field(ge=0, le=1)
    unit: str
    label: str


class GrowthConfig(BaseModel):
    forecast_years: int = Field(gt=0)
    actual_from_fiscal_year: int


class Lens(BaseModel):
    components: list[str] = Field(min_length=1)
    weighted: bool = False
    label: str


class ScoringConfig(BaseModel):
    version: str
    window: Window
    taf_actual_years: int = Field(gt=0)
    long_haul_miles: int = Field(gt=0)
    covid_years: list[int]
    min_departures_per_year: int = Field(ge=0)
    capacity: CapacityConfig
    components: dict[str, Component]
    growth: GrowthConfig
    lenses: dict[str, Lens]

    @model_validator(mode="after")
    def _checks(self) -> ScoringConfig:
        if abs(sum(c.weight for c in self.components.values()) - 1.0) > 1e-6:
            raise ValueError("component weights must sum to 1.0")
        for name, lens in self.lenses.items():
            if unknown := set(lens.components) - set(self.components):
                raise ValueError(f"lens {name}: unknown components {sorted(unknown)}")
        return self

    def lens_names(self) -> list[str]:
        return list(self.lenses)


def load_scoring_config(path: Path = CONFIG_DIR / "scoring.yaml") -> ScoringConfig:
    return ScoringConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
