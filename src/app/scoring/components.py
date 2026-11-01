"""Pure component functions over typed rows. Each returns per-year values; the engine normalizes across airports."""

from __future__ import annotations

from app.data.ontime import OnTimeMonth
from app.data.t100 import T100Row
from app.data.taf import TafRow


def utilization_by_year(rows: list[TafRow], annual_capacity: int, years: int) -> dict[int, float]:
    """Operations / capacity for the latest `years` actual fiscal years."""
    if annual_capacity <= 0:
        return {}
    actual = sorted((r for r in rows if r.actual and r.ops_total > 0), key=lambda r: r.fiscal_year)[-years:]
    return {r.fiscal_year: r.ops_total / annual_capacity for r in actual}


def delay_by_year(rows: list[OnTimeMonth], window: tuple[int, int], min_departures: int) -> dict[int, dict[str, float]]:
    """Per year: delayed-15 share of operated departures and departure-weighted excess taxi-out (mean minus p10)."""
    out: dict[int, dict[str, float]] = {}
    for year in range(window[0], window[1] + 1):
        months = [m for m in rows if m.year == year and m.operated > 0]
        operated = sum(m.operated for m in months)
        if operated < min_departures:
            continue
        taxi = [m for m in months if m.taxi_out_mean is not None and m.taxi_out_p10 is not None]
        taxi_ops = sum(m.operated for m in taxi)
        excess = sum((m.taxi_out_mean - m.taxi_out_p10) * m.operated for m in taxi) / taxi_ops if taxi_ops else None
        entry = {"delayed15_share": sum(m.delayed15 for m in months) / operated, "operated": float(operated),
                 "cancelled_share": sum(m.cancelled for m in months) / sum(m.departures for m in months)}
        if excess is not None:
            entry["excess_taxi_out_min"] = excess
        out[year] = entry
    return out


def load_factor_by_year(rows: list[T100Row], window: tuple[int, int]) -> dict[int, float]:
    out: dict[int, float] = {}
    for year in range(window[0], window[1] + 1):
        pax = [r for r in rows if r.year == year and not r.cargo and r.seats > 0]
        seats = sum(r.seats for r in pax)
        if seats > 0:
            out[year] = sum(r.passengers for r in pax) / seats
    return out


def traffic_mix_by_year(rows: list[T100Row], window: tuple[int, int]) -> dict[int, dict[str, float]]:
    """Per year: long-haul, international and cargo shares of departures performed."""
    out: dict[int, dict[str, float]] = {}
    for year in range(window[0], window[1] + 1):
        yr = [r for r in rows if r.year == year]
        deps = sum(r.departures for r in yr)
        if deps <= 0:
            continue
        out[year] = {
            "departures": float(deps),
            "long_haul_share": sum(r.departures for r in yr if r.long_haul) / deps,
            "international_share": sum(r.departures for r in yr if r.international) / deps,
            "cargo_share": sum(r.departures for r in yr if r.cargo) / deps,
            "long_haul_departures": float(sum(r.departures for r in yr if r.long_haul)),
            "international_departures": float(sum(r.departures for r in yr if r.international)),
            "cargo_departures": float(sum(r.departures for r in yr if r.cargo)),
            "seats": float(sum(r.seats for r in yr if not r.cargo)),
            "passengers": float(sum(r.passengers for r in yr if not r.cargo)),
        }
    return out


def cagr(start: float, end: float, years: int) -> float | None:
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def growth(rows: list[TafRow], forecast_years: int, actual_from: int, covid: list[int]) -> dict[str, float] | None:
    """Forecast CAGR (last actual FY → +N forecast years) and actual CAGR (actual_from → last actual FY).
    COVID years are never an endpoint; the configured endpoints are pre- and post-COVID by construction."""
    by_year = {r.fiscal_year: r for r in rows if r.enplanements > 0}
    actual_years = [y for y, r in by_year.items() if r.actual and y not in covid]
    if not actual_years:
        return None
    last = max(actual_years)
    out: dict[str, float] = {"last_actual_fiscal_year": float(last)}
    if (target := by_year.get(last + forecast_years)) and not target.actual:
        f = cagr(by_year[last].enplanements, target.enplanements, forecast_years)
        if f is not None:
            out["forecast_cagr"] = f
            out["forecast_year"] = float(last + forecast_years)
    if actual_from in by_year and actual_from < last:
        a = cagr(by_year[actual_from].enplanements, by_year[last].enplanements, last - actual_from)
        if a is not None:
            out["actual_cagr"] = a
            out["actual_from_fiscal_year"] = float(actual_from)
    return out if ("forecast_cagr" in out or "actual_cagr" in out) else None


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """0-100 rank of each value within the set; ties share a rank; a single value sits at 50."""
    if not values:
        return {}
    items = list(values.items())
    n = len(items)
    if n == 1:
        return {items[0][0]: 50.0}
    out: dict[str, float] = {}
    for key, v in items:
        less = sum(1 for _, o in items if o < v)
        equal = sum(1 for _, o in items if o == v) - 1
        out[key] = round(100 * (less + 0.5 * equal) / (n - 1), 1)
    return out
