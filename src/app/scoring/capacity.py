"""Annual capacity per airport: FAA service volume (measured), FAA profile rate x hours (measured hourly rate),
or a runway model fitted on the airports that have a service volume (estimate, with its RMSE)."""

from __future__ import annotations

from dataclasses import dataclass

from app.data.profiles import ProfileRates, ProfilesFile
from app.data.registry import Airport
from app.scoring.config import CapacityConfig
from app.scoring.models import Capacity


def blended_hourly_rate(profile: ProfileRates, blend: dict[str, float]) -> float | None:
    """Weighted midpoint of the primary visual, marginal and instrument ranges. Missing conditions fall back to
    the next better one (an instrument rate is never higher than marginal)."""
    rates: dict[str, float] = {}
    for cond in ("visual", "marginal", "instrument"):
        if primary := profile.primary(cond):
            rates[cond] = primary.midpoint
    if "visual" not in rates:
        return None
    rates.setdefault("marginal", rates["visual"])
    rates.setdefault("instrument", rates["marginal"])
    return sum(blend[c] * rates[c] for c in blend)


@dataclass(frozen=True)
class RunwayModel:
    """service_volume ~ intercept + sum(coef * feature), least squares over airports with a service volume."""

    features: tuple[str, ...]
    intercept: float
    coefs: tuple[float, ...]
    rmse: float
    n: int

    def predict(self, airport: Airport) -> float:
        return self.intercept + sum(c * float(getattr(airport, f)) for c, f in zip(self.coefs, self.features, strict=True))


def fit_runway_model(airports: list[Airport], features: list[str]) -> RunwayModel | None:
    """Ordinary least squares by normal equations (tiny design matrix, no numpy dependency)."""
    rows = [a for a in airports if a.service_volume > 0 and a.runways > 0]
    k = len(features) + 1
    if len(rows) <= k:
        return None
    x = [[1.0] + [float(getattr(a, f)) for f in features] for a in rows]
    y = [float(a.service_volume) for a in rows]
    xtx = [[sum(x[r][i] * x[r][j] for r in range(len(rows))) for j in range(k)] for i in range(k)]
    xty = [sum(x[r][i] * y[r] for r in range(len(rows))) for i in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None
    residuals = [y[r] - sum(b * x[r][i] for i, b in enumerate(beta)) for r in range(len(rows))]
    rmse = (sum(e * e for e in residuals) / len(rows)) ** 0.5
    return RunwayModel(tuple(features), beta[0], tuple(beta[1:]), rmse, len(rows))


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-9:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def capacity_for(airport: Airport, cfg: CapacityConfig, profiles: ProfilesFile | None, model: RunwayModel | None) -> Capacity:
    profile = profiles.by_airport().get(airport.id) if profiles else None
    hourly = blended_hourly_rate(profile, cfg.profile_blend) if profile else None
    hourly = round(hourly, 1) if hourly else None  # the quoted rate and the cross-check must agree exactly
    profile_annual = round(hourly * cfg.annual_hours_equivalent) if hourly else None
    base = dict(profile_hourly_rate=hourly, profile_year=profile.year if profile else None, profile_annual_operations=profile_annual)
    for source in cfg.source_order:
        if source == "faa_service_volume" and airport.service_volume > 0:
            return Capacity(source=source, annual_operations=airport.service_volume, **base)
        if source == "faa_profile" and profile_annual:
            return Capacity(source=source, annual_operations=profile_annual, **base)
        if source == "runway_model" and model is not None and airport.runways > 0:
            return Capacity(source=source, annual_operations=max(1, round(model.predict(airport))), uncertainty_operations=round(model.rmse), **base)
    return Capacity(source="unavailable", annual_operations=0, **base)
