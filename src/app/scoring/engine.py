"""The Capacity Pressure Score engine: per-airport components, percentile normalization across the universe,
weighted CPS and lenses, rankings, comparisons, traffic mix and unmet-demand drivers. Pure over the store."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data.profiles import ProfilesFile
from app.data.registry import Airport, AirportRegistry
from app.data.store import Store
from app.scoring import components as comp
from app.scoring.capacity import RunwayModel, capacity_for, fit_runway_model
from app.scoring.config import ScoringConfig
from app.scoring.models import (
    AirportProfile,
    AirportScore,
    Capacity,
    Comparison,
    ComparisonRow,
    ComponentValue,
    Driver,
    RankEntry,
    Ranking,
    TrafficMix,
    UnmetDemand,
    YearValue,
)

COMPONENTS = ("utilization", "delay", "growth", "load_factor", "long_haul")


@dataclass
class _Raw:
    """Per-airport raw component series before normalization."""

    capacity: Capacity
    utilization: dict[int, float] = field(default_factory=dict)
    delay: dict[int, dict[str, float]] = field(default_factory=dict)
    load_factor: dict[int, float] = field(default_factory=dict)
    mix: dict[int, dict[str, float]] = field(default_factory=dict)
    growth: dict[str, float] | None = None
    taf_last_actual: int | None = None
    taf_ops_latest: int | None = None
    taf_enp_latest: int | None = None
    taf_intl_share: float | None = None


def _series(values: dict[int, float]) -> tuple[list[YearValue], float | None, float | None, float | None]:
    if not values:
        return [], None, None, None
    years = sorted(values)
    per_year = [YearValue(year=y, value=round(values[y], 4)) for y in years]
    trend = round(values[years[-1]] - values[years[0]], 4) if len(years) > 1 else None
    return per_year, round(min(values.values()), 4), round(max(values.values()), 4), trend


class Engine:
    def __init__(self, store: Store, registry: AirportRegistry, config: ScoringConfig, profiles: ProfilesFile | None) -> None:
        self.store, self.registry, self.config, self.profiles = store, registry, config, profiles
        self.model: RunwayModel | None = fit_runway_model(registry.all, config.capacity.runway_model.features)
        self._raw: dict[str, _Raw] = {a.id: self._compute_raw(a) for a in registry.all}
        self._percentiles = self._normalize()
        self._scores: dict[str, AirportScore] = {}

    # ---- raw series -------------------------------------------------------------------------------------------
    def _compute_raw(self, a: Airport) -> _Raw:
        cfg = self.config
        window = (cfg.window.start, cfg.window.end)
        raw = _Raw(capacity=capacity_for(a, cfg.capacity, self.profiles, self.model))
        taf = self.store.taf(a.id)
        raw.utilization = comp.utilization_by_year(taf, raw.capacity.annual_operations, cfg.taf_actual_years)
        raw.growth = comp.growth(taf, cfg.growth.forecast_years, cfg.growth.actual_from_fiscal_year, cfg.covid_years)
        actual = [r for r in taf if r.actual and r.ops_total > 0]
        if actual:
            last = max(actual, key=lambda r: r.fiscal_year)
            raw.taf_last_actual, raw.taf_ops_latest, raw.taf_enp_latest = last.fiscal_year, last.ops_total, last.enplanements
            raw.taf_intl_share = round(last.enp_international / last.enplanements, 4) if last.enplanements else None
        raw.delay = comp.delay_by_year(self.store.ontime(a.id), window, cfg.min_departures_per_year)
        t100 = self.store.t100(a.id)
        raw.load_factor = comp.load_factor_by_year(t100, window)
        raw.mix = comp.traffic_mix_by_year(t100, window)
        return raw

    @staticmethod
    def _latest(values: dict[int, float]) -> float | None:
        return values[max(values)] if values else None

    def _sub_latest(self, airport: str, key: str, source: str) -> float | None:
        series = getattr(self._raw[airport], source)
        if not series:
            return None
        year = max(series)
        return series[year].get(key)

    def _normalize(self) -> dict[str, dict[str, float]]:
        """Percentile ranks per component (and per sub-metric) across the universe, latest year."""
        ids = list(self._raw)
        pct: dict[str, dict[str, float]] = {}
        pct["utilization"] = comp.percentile_ranks({i: v for i in ids if (v := self._latest(self._raw[i].utilization)) is not None})
        pct["load_factor"] = comp.percentile_ranks({i: v for i in ids if (v := self._latest(self._raw[i].load_factor)) is not None})
        pct["long_haul"] = comp.percentile_ranks({i: v for i in ids if (v := self._sub_latest(i, "long_haul_share", "mix")) is not None})
        d15 = comp.percentile_ranks({i: v for i in ids if (v := self._sub_latest(i, "delayed15_share", "delay")) is not None})
        taxi = comp.percentile_ranks({i: v for i in ids if (v := self._sub_latest(i, "excess_taxi_out_min", "delay")) is not None})
        pct["delay"] = {i: round((d15[i] + taxi[i]) / 2, 1) if i in taxi else d15[i] for i in d15}
        pct["delay_d15"], pct["delay_taxi"] = d15, taxi
        fc = comp.percentile_ranks({i: g["forecast_cagr"] for i in ids if (g := self._raw[i].growth) and "forecast_cagr" in g})
        ac = comp.percentile_ranks({i: g["actual_cagr"] for i in ids if (g := self._raw[i].growth) and "actual_cagr" in g})
        pct["growth"] = {i: round((fc[i] + ac[i]) / 2, 1) if i in ac else fc[i] for i in fc}
        for i in ac:
            pct["growth"].setdefault(i, ac[i])
        pct["growth_forecast"], pct["growth_actual"] = fc, ac
        return pct

    # ---- typed components ---------------------------------------------------------------------------------------
    def _component(self, airport: str, name: str) -> ComponentValue:
        c, raw, cfg = self.config.components[name], self._raw[airport], self.config
        percentile = self._percentiles[name].get(airport)
        if name == "utilization":
            per_year, low, high, trend = _series(raw.utilization)
            value = self._latest(raw.utilization)
            note = f"capacity {raw.capacity.source}" + (" (estimate)" if raw.capacity.source == "runway_model" else " (measured)")
            return ComponentValue(name=name, label=c.label, unit=c.unit, value=_r(value), percentile=percentile, per_year=per_year,
                                  low=low, high=high, trend=trend, detail={"annual_capacity": float(raw.capacity.annual_operations)}, note=note)
        if name == "delay":
            d15 = {y: v["delayed15_share"] for y, v in raw.delay.items()}
            per_year, low, high, trend = _series(d15)
            year = max(raw.delay) if raw.delay else None
            detail = {k: round(v, 4) for k, v in raw.delay[year].items()} if year else {}
            detail.update({f"percentile_{k}": self._percentiles[f"delay_{k}"][airport] for k in ("d15", "taxi") if airport in self._percentiles[f"delay_{k}"]})
            return ComponentValue(name=name, label=c.label, unit=c.unit, value=percentile, percentile=percentile, per_year=per_year, low=low, high=high,
                                  trend=trend, detail=detail, note="per_year/low/high/trend are the delayed-15 share; value is the combined percentile")
        if name == "growth":
            g = raw.growth or {}
            detail = {k: round(v, 4) for k, v in g.items()}
            for k in ("forecast", "actual"):
                if airport in self._percentiles[f"growth_{k}"]:
                    detail[f"percentile_{k}"] = self._percentiles[f"growth_{k}"][airport]
            return ComponentValue(name=name, label=c.label, unit=c.unit, value=percentile, percentile=percentile, detail=detail,
                                  note="value is the combined percentile; CAGRs are in detail (FAA TAF enplanements)")
        if name == "load_factor":
            per_year, low, high, trend = _series(raw.load_factor)
            return ComponentValue(name=name, label=c.label, unit=c.unit, value=_r(self._latest(raw.load_factor)), percentile=percentile,
                                  per_year=per_year, low=low, high=high, trend=trend, note="scheduled passenger service, BTS T-100")
        shares = {y: v["long_haul_share"] for y, v in raw.mix.items()}
        per_year, low, high, trend = _series(shares)
        year = max(raw.mix) if raw.mix else None
        detail = {k: round(v, 4) for k, v in raw.mix[year].items()} if year else {}
        return ComponentValue(name=name, label=c.label, unit=c.unit, value=_r(self._latest(shares)), percentile=percentile, per_year=per_year,
                              low=low, high=high, trend=trend, detail=detail, note=f"segments of {cfg.long_haul_miles}+ miles, all carriers incl. cargo")

    def data_through(self) -> dict[str, str]:
        return {c.source: c.last for c in self.store.coverage()}

    # ---- scores ---------------------------------------------------------------------------------------------------
    def score(self, airport_id: str) -> AirportScore:
        if airport_id in self._scores:
            return self._scores[airport_id]
        a = self.registry.by_id(airport_id)
        assert a is not None
        comps = [self._component(a.id, n) for n in COMPONENTS]
        weights = {n: self.config.components[n].weight for n in COMPONENTS}
        present = {c.name: c.percentile for c in comps if c.percentile is not None}
        missing = [c.name for c in comps if c.percentile is None]
        cps = None
        contributions: list[dict[str, float | str]] = []
        if present:
            total_w = sum(weights[n] for n in present)
            for n, p in present.items():
                w = weights[n] / total_w
                contributions.append({"component": n, "percentile": p, "weight": round(w, 4), "contribution": round(w * p, 2)})
            contributions.sort(key=lambda d: -float(d["contribution"]))
            cps = round(sum(float(d["contribution"]) for d in contributions), 1)
        lenses = {name: self._lens_score(present, weights, lens.components, lens.weighted) for name, lens in self.config.lenses.items()}
        raw = self._raw[a.id]
        limitations = [f"weights and thresholds are stated assumptions (scoring {self.config.version}), not calibrated to investment outcomes"]
        if raw.capacity.source == "runway_model":
            limitations.append(f"capacity is a runway-model estimate, RMSE {raw.capacity.uncertainty_operations} operations per year")
        elif raw.capacity.source == "faa_profile":
            limitations.append(f"capacity is the FAA profile hourly rate ({raw.capacity.profile_year}) times {self.config.capacity.annual_hours_equivalent} hours")
        if missing:
            limitations.append(f"no data for {', '.join(missing)}; weights renormalized over the other components")
        if "delay" in present:
            limitations.append("delay statistics cover domestic reporting carriers only (BTS On-Time)")
        score = AirportScore(
            airport=a.id, name=a.name, city=a.city, state=a.state, division=a.division, hub_class=a.hub_class, cps=cps, lenses=lenses,
            components=comps, capacity=raw.capacity, weights=weights, contributions=contributions, missing_components=missing,
            scoring_version=self.config.version, data_through=self.data_through(), limitations=limitations,
        )
        self._scores[a.id] = score
        return score

    @staticmethod
    def _lens_score(present: dict[str, float], weights: dict[str, float], names: list[str], weighted: bool) -> float | None:
        avail = [n for n in names if n in present]
        if not avail:
            return None
        if weighted:
            total = sum(weights[n] for n in avail)
            return round(sum(weights[n] / total * present[n] for n in avail), 1)
        return round(sum(present[n] for n in avail) / len(avail), 1)

    def rank(self, lens: str, area: str | None = None, top: int = 10) -> Ranking:
        airports = self.registry.all if not area else (self.registry.in_area(area) or [])
        scored = [(self.score(a.id), a) for a in airports]
        with_value = [(s, a) for s, a in scored if s.lenses.get(lens) is not None]
        with_value.sort(key=lambda sa: (-sa[0].lenses[lens], sa[1].id))
        entries = []
        for i, (s, a) in enumerate(with_value[:top], 1):
            driver = max((c for c in s.components if c.name in self.config.lenses[lens].components and c.percentile is not None),
                         key=lambda c: c.percentile, default=None)
            entries.append(RankEntry(rank=i, airport=a.id, name=a.name, state=a.state, hub_class=a.hub_class, score=s.lenses[lens],
                                     top_driver=driver.name if driver else "", capacity_source=s.capacity.source))
        return Ranking(lens=lens, lens_label=self.config.lenses[lens].label, area=area, universe=len(with_value), entries=entries,
                       excluded=[a.id for s, a in scored if s.lenses.get(lens) is None], scoring_version=self.config.version, data_through=self.data_through())

    def compare(self, a_id: str, b_id: str, lens: str = "congestion") -> Comparison:
        sa, sb = self.score(a_id), self.score(b_id)
        rows = []
        for ca, cb in zip(sa.components, sb.components, strict=True):
            diff = round(ca.value - cb.value, 4) if ca.value is not None and cb.value is not None else None
            higher = None
            if ca.percentile is not None and cb.percentile is not None:
                higher = a_id if ca.percentile > cb.percentile else b_id if cb.percentile > ca.percentile else "equal"
            rows.append(ComparisonRow(component=ca.name, label=ca.label, unit=ca.unit, value_a=ca.value, value_b=cb.value,
                                      percentile_a=ca.percentile, percentile_b=cb.percentile, difference=diff, higher=higher))
        return Comparison(lens=lens, airport_a=a_id, airport_b=b_id, name_a=sa.name, name_b=sb.name, lens_score_a=sa.lenses.get(lens),
                          lens_score_b=sb.lenses.get(lens), capacity_a=sa.capacity, capacity_b=sb.capacity, rows=rows,
                          scoring_version=self.config.version, data_through=self.data_through())

    def traffic_mix(self, airport_id: str, year: int | None = None) -> TrafficMix | None:
        raw = self._raw[airport_id]
        if not raw.mix:
            return None
        year = year if year in raw.mix else max(raw.mix)
        m = raw.mix[year]
        lf = self._raw[airport_id].load_factor.get(year)
        a = self.registry.by_id(airport_id)
        assert a is not None
        return TrafficMix(
            airport=airport_id, name=a.name, year=year, departures=int(m["departures"]), long_haul_departures=int(m["long_haul_departures"]),
            long_haul_pct=round(100 * m["long_haul_share"], 1), international_departures=int(m["international_departures"]),
            international_pct=round(100 * m["international_share"], 1), cargo_departures=int(m["cargo_departures"]),
            cargo_pct=round(100 * m["cargo_share"], 1), seats=int(m["seats"]), passengers=int(m["passengers"]),
            load_factor=round(lf, 3) if lf is not None else None, long_haul_miles=self.config.long_haul_miles,
            per_year=[{"year": float(y), "long_haul_pct": round(100 * v["long_haul_share"], 1), "international_pct": round(100 * v["international_share"], 1)} for y, v in sorted(raw.mix.items())],
            scoring_version=self.config.version, data_through=self.data_through(),
        )

    def available_years(self, airport_id: str) -> list[int]:
        return sorted(self._raw[airport_id].mix)

    def unmet_demand(self, airport_id: str) -> UnmetDemand:
        s = self.score(airport_id)
        names = self.config.lenses["unmet_demand"].components
        comps = [c for c in s.components if c.name in names]
        util = next((c for c in s.components if c.name == "utilization"), None)
        drivers = sorted(
            (Driver(component=c.name, direction="raises" if c.percentile >= 50 else "lowers", percentile=c.percentile, value=c.value,
                    unit=c.unit, magnitude=round(abs(c.percentile - 50), 1)) for c in comps if c.percentile is not None),
            key=lambda d: -d.magnitude,
        )
        return UnmetDemand(airport=s.airport, name=s.name, lens_score=s.lenses.get("unmet_demand"), components=comps, utilization=util,
                           capacity=s.capacity, drivers=drivers, scoring_version=self.config.version, data_through=s.data_through,
                           limitations=s.limitations + ["unmet demand is inferred from load factor, forecast growth and delays; no source observes it directly"])

    def profile(self, airport_id: str) -> AirportProfile:
        a = self.registry.by_id(airport_id)
        assert a is not None
        raw = self._raw[airport_id]
        return AirportProfile(
            airport=a.id, name=a.name, city=a.city, state=a.state, region=a.region, division=a.division, hub_class=a.hub_class, runways=a.runways,
            runways_6000ft=a.runways_6000ft, longest_runway_ft=a.longest_runway_ft, enplanements_latest_year=a.enplanements_latest_year,
            enplanements_latest=a.enplanements_latest, enplanements_previous=a.enplanements_previous, capacity=raw.capacity,
            latest_actual_fiscal_year=raw.taf_last_actual, operations_latest=raw.taf_ops_latest, enplanements_taf_latest=raw.taf_enp_latest,
            international_enplanement_share=raw.taf_intl_share, scoring_version=self.config.version, data_through=self.data_through(),
        )


def _r(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None
