"""Typed results of the scoring engine: what the tools return and the model must quote verbatim."""

from __future__ import annotations

from pydantic import BaseModel, Field


class YearValue(BaseModel):
    year: int
    value: float
    value_pct: float | None = None


class ComponentValue(BaseModel):
    name: str
    label: str
    unit: str
    value: float | None = Field(description="latest-year value; None when the source has no usable data")
    percentile: float | None = Field(description="0-100 rank of the value within the hub-airport universe (higher = more pressure)")
    per_year: list[YearValue] = Field(default_factory=list)
    low: float | None = None
    high: float | None = None
    trend: float | None = Field(default=None, description="last year minus first year of the window, same unit")
    low_pct: float | None = None
    high_pct: float | None = None
    trend_pct: float | None = Field(default=None, description="trend in percentage points when the unit is a ratio or share")
    detail: dict[str, float] = Field(default_factory=dict, description="sub-metrics behind the value (shares, CAGRs, taxi minutes)")
    note: str = ""


class Capacity(BaseModel):
    source: str = Field(description="faa_service_volume (measured) | faa_profile (measured hourly rate x hours) | runway_model (estimate)")
    annual_operations: int
    uncertainty_operations: int | None = Field(default=None, description="runway-model fit RMSE; None for measured sources")
    profile_hourly_rate: float | None = Field(default=None, description="blended FAA capacity-profile rate, operations per hour, when a profile exists")
    profile_year: int | None = None
    profile_annual_operations: int | None = Field(default=None, description="profile rate x annual hours equivalent, the cross-check")


class AirportScore(BaseModel):
    airport: str
    name: str
    city: str
    state: str
    division: str
    hub_class: str
    cps: float | None = Field(description="Capacity Pressure Score 0-100: weighted sum of component percentiles")
    lenses: dict[str, float | None]
    components: list[ComponentValue]
    capacity: Capacity
    weights: dict[str, float]
    contributions: list[dict[str, float | str]] = Field(description="component, percentile, weight, contribution to the CPS, sorted descending")
    missing_components: list[str] = Field(default_factory=list)
    scoring_version: str
    data_through: dict[str, str]
    limitations: list[str] = Field(default_factory=list)


class RankEntry(BaseModel):
    rank: int
    airport: str
    name: str
    state: str
    hub_class: str
    score: float
    top_driver: str
    capacity_source: str


class Ranking(BaseModel):
    lens: str
    lens_label: str
    area: str | None
    universe: int
    entries: list[RankEntry]
    excluded: list[str] = Field(default_factory=list, description="airports in the area without a score for this lens")
    scoring_version: str
    data_through: dict[str, str]


class ComparisonRow(BaseModel):
    component: str
    label: str
    unit: str
    value_a: float | None
    value_b: float | None
    percentile_a: float | None
    percentile_b: float | None
    difference: float | None = Field(description="value_a minus value_b")
    higher: str | None


class Comparison(BaseModel):
    lens: str
    airport_a: str
    airport_b: str
    name_a: str
    name_b: str
    lens_score_a: float | None
    lens_score_b: float | None
    capacity_a: Capacity
    capacity_b: Capacity
    rows: list[ComparisonRow]
    scoring_version: str
    data_through: dict[str, str]


class TrafficMix(BaseModel):
    airport: str
    name: str
    year: int
    departures: int
    long_haul_departures: int
    long_haul_pct: float
    international_departures: int
    international_pct: float
    cargo_departures: int
    cargo_pct: float
    seats: int
    passengers: int
    load_factor: float | None
    load_factor_pct: float | None = None
    long_haul_miles: int
    per_year: list[dict[str, float]] = Field(default_factory=list)
    source: str = "BTS T-100 Segment, all carriers, departures performed"
    scoring_version: str
    data_through: dict[str, str]


class Driver(BaseModel):
    component: str
    direction: str  # "raises" | "lowers"
    percentile: float
    value: float | None
    unit: str
    magnitude: float = Field(description="percentile distance from the median (50)")


class UnmetDemand(BaseModel):
    airport: str
    name: str
    lens_score: float | None
    components: list[ComponentValue]
    utilization: ComponentValue | None
    capacity: Capacity
    drivers: list[Driver]
    scoring_version: str
    data_through: dict[str, str]
    limitations: list[str]


class AirportProfile(BaseModel):
    airport: str
    name: str
    city: str
    state: str
    region: str
    division: str
    hub_class: str
    runways: int
    runways_6000ft: int
    longest_runway_ft: int
    enplanements_latest_year: int
    enplanements_latest: int
    enplanements_previous: int
    capacity: Capacity
    latest_actual_fiscal_year: int | None
    operations_latest: int | None
    enplanements_taf_latest: int | None
    international_enplanement_share: float | None
    international_enplanement_pct: float | None = None
    scoring_version: str
    data_through: dict[str, str]
