"""Acceptance criteria of agent-os/specs/2026-11-01-v2-capacity-kpi, one test per criterion, all offline."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from app import cli as cli_module
from app.agent.tools import (
    Ambiguous,
    NotFound,
    ToolContext,
    Unavailable,
    _compare,
    _list,
    _mix,
    _profile,
    _rank,
    _score,
    _unmet,
    build_toolset,
    resolve_airport,
)
from app.config import CONFIG_DIR, ROOT
from app.data.areas import load_areas
from app.data.ontime import OnTimeMonth
from app.data.profiles import ConditionRates, ProfileRates, ProfilesFile, load_profiles
from app.data.registry import Airport, AirportRegistry, RegistryFile
from app.data.snapshot import Manifest, write_snapshot
from app.data.store import Store
from app.data.t100 import T100Row
from app.data.taf import TafRow
from app.scoring import components as comp
from app.scoring.capacity import blended_hourly_rate, capacity_for, fit_runway_model
from app.scoring.config import ScoringConfig, load_scoring_config
from app.scoring.engine import Engine

SNAPSHOT = ROOT / "data" / "snapshots"


def _airport(id: str, state: str, division: str, region: str, sv: int, rw: int, rw6: int, hub: str = "L") -> Airport:
    return Airport(id=id, iata=id, icao=f"K{id}", name=f"{id} Intl", city=id, state=state, region=region, division=division, hub_class=hub,
                   lat=40.0, lon=-100.0, service_volume=sv, enplanements_latest_year=2025, enplanements_latest=1_000_000, enplanements_previous=900_000,
                   runways=rw, runways_6000ft=rw6, longest_runway_ft=9000)


AIRPORTS = [
    _airport("AAA", "MA", "New England", "Northeast", 400_000, 4, 3), _airport("BBB", "ME", "New England", "Northeast", 200_000, 2, 2, "S"),
    _airport("CCC", "CA", "Pacific", "West", 600_000, 4, 4), _airport("DDD", "TX", "West South Central", "South", 800_000, 6, 6),
    _airport("EEE", "AK", "Pacific", "West", 0, 3, 3, "M"),  # no service volume -> runway model
]


def _taf(a: str, ops: dict[int, int], enp: dict[int, int]) -> list[TafRow]:
    rows = []
    for y in sorted(set(ops) | set(enp)):
        rows.append(TafRow(airport=a, fiscal_year=y, actual=y <= 2024, ops_air_carrier=ops.get(y, 0), enp_air_carrier=enp.get(y, 0)))
    return rows


def _ontime(a: str, year: int, d15: float, taxi_excess: float, operated: int = 12000) -> list[OnTimeMonth]:
    per = operated // 12
    return [OnTimeMonth(airport=a, year=year, month=m, departures=per + 10, cancelled=10, delayed15=int(per * d15), taxi_out_mean=10 + taxi_excess,
                        taxi_out_p10=10.0, long_haul_departures=0) for m in range(1, 13)]


def _t100(a: str, year: int, lf: float, long_haul_share: float, deps: int = 10000) -> list[T100Row]:
    lh = int(deps * long_haul_share)
    return [T100Row(airport=a, year=year, international=True, long_haul=True, cargo=False, departures=lh, seats=lh * 100, passengers=int(lh * 100 * lf)),
            T100Row(airport=a, year=year, international=False, long_haul=False, cargo=False, departures=deps - lh, seats=(deps - lh) * 100,
                    passengers=int((deps - lh) * 100 * lf))]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    registry = AirportRegistry(RegistryFile(version="t", generated="x", sources={}, airports=AIRPORTS), load_areas())
    taf, ontime, t100 = [], [], []
    profile = {
        "AAA": (dict.fromkeys(range(2019, 2035), 380_000), {2019: 20_000_000, 2024: 21_000_000, 2034: 28_000_000}),
        "BBB": (dict.fromkeys(range(2019, 2035), 100_000), {2019: 1_000_000, 2024: 1_100_000, 2034: 1_300_000}),
        "CCC": (dict.fromkeys(range(2019, 2035), 480_000), {2019: 27_000_000, 2024: 24_000_000, 2034: 30_000_000}),
        "DDD": (dict.fromkeys(range(2019, 2035), 400_000), {2019: 30_000_000, 2024: 36_000_000, 2034: 50_000_000}),
        "EEE": (dict.fromkeys(range(2019, 2035), 250_000), {2019: 2_000_000, 2024: 2_500_000, 2034: 3_000_000}),
    }
    for a, (ops, enp) in profile.items():
        taf += _taf(a, ops, enp)
    delays = {"AAA": (0.25, 8.0), "BBB": (0.10, 1.0), "CCC": (0.30, 10.0), "DDD": (0.20, 6.0), "EEE": (0.15, 3.0)}
    for a, (d15, taxi) in delays.items():
        for y in (2023, 2024, 2025):
            ontime += _ontime(a, y, d15 + (0.02 if y == 2025 else 0.0), taxi)
    mixes = {"AAA": (0.85, 0.05), "BBB": (0.70, 0.0), "CCC": (0.88, 0.15), "DDD": (0.82, 0.08), "EEE": (0.75, 0.30)}
    for a, (lf, lh) in mixes.items():
        for y in (2023, 2024, 2025):
            t100 += _t100(a, y, lf, lh)
    manifest = Manifest(version="t", written_at="2026-11-01T00:00:00+00:00", registry_version="t", airports=5, long_haul_miles=3000, sources={})
    write_snapshot(tmp_path, manifest, taf=taf, ontime=ontime, t100=t100)
    profiles = ProfilesFile(version="t", generated="x", source="u", profiles=[
        ProfileRates(airport="AAA", year=2019, url="u", visual=[ConditionRates(configuration="p", low=104, high=107)],
                     marginal=[ConditionRates(configuration="p", low=93, high=98)], instrument=[ConditionRates(configuration="p", low=76, high=78)]),
    ])
    return Engine(Store.open_if_present(tmp_path), registry, load_scoring_config(), profiles)


def _deps(engine: Engine) -> ToolContext:
    return ToolContext(product_name="t", registry=engine.registry, store=engine.store, engine=engine, profiles=engine.profiles)


def test_criterion_1_scoring_config_validates_weights_lenses_and_blend():
    cfg = load_scoring_config()
    assert cfg.version and set(cfg.components) == {"utilization", "delay", "growth", "load_factor", "long_haul"}
    assert cfg.long_haul_miles == 3000 and cfg.capacity.annual_hours_equivalent == 4000 and cfg.capacity.profile_blend == {"visual": 0.7, "marginal": 0.2, "instrument": 0.1}
    assert abs(sum(c.weight for c in cfg.components.values()) - 1) < 1e-9 and set(cfg.lenses) >= {"expansion", "congestion", "unmet_demand", "long_haul"}
    raw = yaml.safe_load((CONFIG_DIR / "scoring.yaml").read_text(encoding="utf-8"))
    bad = {**raw, "components": {**raw["components"], "utilization": {**raw["components"]["utilization"], "weight": 0.5}}}
    with pytest.raises(ValueError, match="sum to 1.0"):
        ScoringConfig.model_validate(bad)
    bad = {**raw, "lenses": {**raw["lenses"], "x": {"components": ["nope"], "label": "x"}}}
    with pytest.raises(ValueError, match="unknown components"):
        ScoringConfig.model_validate(bad)


def test_criterion_2_profile_rate_blends_the_three_conditions():
    p = ProfileRates(airport="SFO", year=2019, url="u", visual=[ConditionRates(configuration="p", low=104, high=107)],
                     marginal=[ConditionRates(configuration="p", low=93, high=98)], instrument=[ConditionRates(configuration="p", low=76, high=78)])
    blend = {"visual": 0.7, "marginal": 0.2, "instrument": 0.1}
    rate = blended_hourly_rate(p, blend)
    assert rate == pytest.approx(0.7 * 105.5 + 0.2 * 95.5 + 0.1 * 77) and 77 < rate < 105.5
    only_visual = ProfileRates(airport="X", year=2015, url="u", visual=[ConditionRates(configuration="p", low=120, high=125)])
    assert blended_hourly_rate(only_visual, blend) == pytest.approx(122.5)
    assert blended_hourly_rate(ProfileRates(airport="X", year=2015, url="u"), blend) is None


def test_criterion_3_capacity_precedence_measured_before_profile_before_model(engine: Engine):
    cfg = engine.config.capacity
    model = fit_runway_model(AIRPORTS, cfg.runway_model.features)
    assert model is not None and model.n == 4 and model.rmse >= 0
    aaa = capacity_for(AIRPORTS[0], cfg, engine.profiles, model)
    assert aaa.source == "faa_service_volume" and aaa.annual_operations == 400_000 and aaa.uncertainty_operations is None
    assert aaa.profile_hourly_rate == pytest.approx(100.6, abs=0.1) and aaa.profile_annual_operations == round(aaa.profile_hourly_rate * 4000)
    eee = capacity_for(AIRPORTS[4], cfg, engine.profiles, model)
    assert eee.source == "runway_model" and eee.annual_operations > 0 and eee.uncertainty_operations == round(model.rmse)
    no_sv = AIRPORTS[0].model_copy(update={"service_volume": 0})
    assert capacity_for(no_sv, cfg, engine.profiles, model).source == "faa_profile"
    assert capacity_for(no_sv.model_copy(update={"runways": 0}), cfg, None, model).source == "unavailable"


def test_criterion_4_utilization_per_year_band_and_trend(engine: Engine):
    rows = [TafRow(airport="X", fiscal_year=y, actual=y <= 2024, ops_air_carrier=o) for y, o in ((2021, 300), (2022, 320), (2023, 340), (2024, 360), (2025, 400))]
    series = comp.utilization_by_year(rows, 400, years=3)
    assert series == {2022: 0.8, 2023: 0.85, 2024: 0.9} and comp.utilization_by_year(rows, 0, 3) == {}
    u = next(c for c in engine.score("AAA").components if c.name == "utilization")
    assert u.value == pytest.approx(0.95) and u.low == u.high == pytest.approx(0.95) and u.trend == 0 and "measured" in u.note


def test_criterion_5_delay_combines_delayed15_and_excess_taxi_and_excludes_thin_years(engine: Engine):
    rows = _ontime("X", 2024, 0.2, 5.0, operated=12000) + _ontime("X", 2025, 0.1, 2.0, operated=1200)
    by_year = comp.delay_by_year(rows, (2023, 2025), min_departures=3000)
    assert list(by_year) == [2024] and by_year[2024]["delayed15_share"] == pytest.approx(0.2, abs=0.01)
    assert by_year[2024]["excess_taxi_out_min"] == pytest.approx(5.0)
    d = next(c for c in engine.score("CCC").components if c.name == "delay")
    assert d.percentile == 100.0 and d.value == d.percentile and d.detail["percentile_d15"] == 100.0 and d.detail["percentile_taxi"] == 100.0
    assert next(c for c in engine.score("BBB").components if c.name == "delay").percentile == 0.0


def test_criterion_6_load_factor_is_passengers_over_seats_without_division_errors():
    rows = _t100("X", 2025, 0.8, 0.1) + [T100Row(airport="X", year=2025, international=True, long_haul=True, cargo=True, departures=50, seats=0, passengers=0)]
    assert comp.load_factor_by_year(rows, (2025, 2025))[2025] == pytest.approx(0.8)
    assert comp.load_factor_by_year([T100Row(airport="X", year=2025, international=False, long_haul=False, cargo=False, departures=1, seats=0, passengers=0)], (2025, 2025)) == {}


def test_criterion_7_growth_uses_forecast_and_actual_cagr_and_skips_covid_years():
    rows = _taf("X", {}, {2019: 100, 2020: 20, 2021: 30, 2024: 110, 2034: 150})
    g = comp.growth(rows, forecast_years=10, actual_from=2019, covid=[2020, 2021])
    assert g["last_actual_fiscal_year"] == 2024 and g["forecast_cagr"] == pytest.approx((150 / 110) ** 0.1 - 1)
    assert g["actual_cagr"] == pytest.approx((110 / 100) ** 0.2 - 1)
    assert comp.growth(_taf("X", {}, {2024: 110}), 10, 2019, [2020, 2021]) is None
    assert comp.cagr(0, 10, 5) is None and comp.cagr(100, 200, 0) is None


def test_criterion_8_long_haul_share_with_denominators_and_international_beside_it():
    rows = _t100("X", 2025, 0.8, 0.3, deps=1000)
    mix = comp.traffic_mix_by_year(rows, (2025, 2025))[2025]
    assert mix["long_haul_share"] == pytest.approx(0.3) and mix["departures"] == 1000 and mix["long_haul_departures"] == 300
    assert mix["international_share"] == pytest.approx(0.3) and mix["cargo_share"] == 0


def test_criterion_9_percentiles_ties_and_deterministic_cps(engine: Engine):
    assert comp.percentile_ranks({"a": 1, "b": 2, "c": 3}) == {"a": 0.0, "b": 50.0, "c": 100.0}
    assert comp.percentile_ranks({"a": 1, "b": 1, "c": 3}) == {"a": 25.0, "b": 25.0, "c": 100.0} and comp.percentile_ranks({"a": 5}) == {"a": 50.0}
    s = engine.score("AAA")
    weights = s.weights
    expected = sum(weights[c.name] * c.percentile for c in s.components if c.percentile is not None) / sum(weights[c.name] for c in s.components if c.percentile is not None)
    assert s.cps == pytest.approx(expected, abs=0.11) and s.missing_components == []
    assert s.lenses["congestion"] == pytest.approx(sum(c.percentile for c in s.components if c.name in ("utilization", "delay")) / 2, abs=0.11)
    again = Engine(engine.store, engine.registry, engine.config, engine.profiles).score("AAA")
    assert again.model_dump() == s.model_dump()


def test_criterion_10_rank_and_compare(engine: Engine):
    r = engine.rank("expansion", None, 10)
    scores = [e.score for e in r.entries]
    assert scores == sorted(scores, reverse=True) and r.universe == 5 and r.entries[0].rank == 1
    ne = engine.rank("congestion", "new england", 10)
    assert [e.airport for e in ne.entries] == ["AAA", "BBB"] and ne.area == "new england"
    tie = engine.rank("long_haul", "new england", 10)
    assert tie.entries[0].airport == "AAA" and tie.entries[1].airport == "BBB"
    c = engine.compare("CCC", "BBB", "congestion")
    row = next(x for x in c.rows if x.component == "delay")
    assert row.higher == "CCC" and c.lens_score_a > c.lens_score_b
    lf = next(x for x in c.rows if x.component == "load_factor")
    assert lf.difference == pytest.approx(0.88 - 0.70, abs=0.001)


def test_criterion_11_unmet_demand_returns_typed_drivers(engine: Engine):
    u = engine.unmet_demand("DDD")
    assert {c.name for c in u.components} == {"load_factor", "growth", "delay"} and u.utilization is not None
    assert u.drivers and u.drivers == sorted(u.drivers, key=lambda d: -d.magnitude)
    assert all(d.direction in ("raises", "lowers") and d.component in ("load_factor", "growth", "delay") for d in u.drivers)
    assert u.capacity.source == "faa_service_volume" and any("inferred" in lim for lim in u.limitations)
    assert not hasattr(u, "narrative")


def test_criterion_12_tools_never_raise_and_carry_versions(engine: Engine):
    deps = _deps(engine)
    nf = _rank(deps, "nope", None, 10)
    assert isinstance(nf, NotFound) and nf.kind == "lens" and "expansion" in nf.valid
    assert isinstance(_rank(deps, "congestion", "Atlantis", 10), NotFound)
    assert isinstance(_score(deps, "ZZZ"), NotFound) and isinstance(_mix(deps, "AAA", 1999), NotFound)
    amb = resolve_airport(_deps_real(), "portland")
    assert isinstance(amb, Ambiguous) and {c[:3] for c in amb.candidates} == {"PDX", "PWM"}
    assert isinstance(_score(_deps_real(), "portland"), Unavailable)  # no engine: unavailable before resolution
    empty = ToolContext(product_name="t", registry=engine.registry)
    assert isinstance(_rank(empty, "expansion", None, 10), Unavailable) and isinstance(_unmet(empty, "AAA"), Unavailable)
    s = _score(deps, "AAA")
    assert s.scoring_version == engine.config.version and s.data_through and s.capacity.source
    assert _profile(deps, "AAA").capacity.source == "faa_service_volume" and _compare(deps, "AAA", "ZZZ", "congestion").kind == "airport"


def _deps_real() -> ToolContext:
    return ToolContext(product_name="t", registry=AirportRegistry.load())


def test_criterion_13_tools_are_registered_and_live_status_flag(engine: Engine):
    names = {t.name for t in build_toolset().tools.values()} if hasattr(build_toolset().tools, "values") else set(build_toolset().tools)
    assert {"about", "list_airports", "rank_airports", "compare_airports", "airport_score", "airport_profile", "traffic_mix", "unmet_demand", "live_status"} <= names
    listing = _list(_deps(engine), "new england")
    assert [a.id for a in listing.airports] == ["AAA", "BBB"] and "expansion" in listing.lenses


def test_criterion_14_snapshot_facts_new_england_sfo_and_anchorage():
    store = Store.open_if_present(SNAPSHOT)
    assert store is not None
    engine = Engine(store, AirportRegistry.load(), load_scoring_config(), load_profiles())
    ne = engine.rank("expansion", "new england", 10)
    assert ne.entries[0].airport == "BOS"
    sfo = engine.score("SFO")
    median = sorted(s.lenses["unmet_demand"] for a in engine.registry.all if (s := engine.score(a.id)).lenses["unmet_demand"] is not None)
    assert sfo.lenses["unmet_demand"] > median[len(median) // 2]
    mix = engine.traffic_mix("ANC")
    rows = store._q("SELECT SUM(CASE WHEN long_haul THEN departures ELSE 0 END), SUM(departures) FROM t100 WHERE airport='ANC' AND year=?", [mix.year])[0]
    assert mix.long_haul_pct == pytest.approx(100 * rows[0] / rows[1], abs=0.051)
    assert sfo.capacity.source == "faa_service_volume" and sfo.capacity.annual_operations == 393000 and sfo.capacity.profile_year == 2019
    design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    for c in sfo.components:
        if c.value is not None:
            assert f"{c.percentile}" in design, f"DESIGN worked example lacks {c.name} percentile {c.percentile}"
    assert f"{sfo.cps}" in design


def test_criterion_15_smoke_eval_passes_and_score_command_prints(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    result = CliRunner().invoke(cli_module.cli, ["eval", "--test", "--tag", "smoke", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(cli_module.cli, ["score", "SFO", "--test"])
    assert result.exit_code == 0 and "CPS" in result.output and "faa_service_volume" in result.output and "utilization" in result.output


def test_criterion_16_readme_documents_the_config():
    cfg = load_scoring_config()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name, c in cfg.components.items():
        assert name in readme and f"{c.weight:g}" in readme, name
    assert str(cfg.long_haul_miles) in readme and str(cfg.capacity.annual_hours_equivalent) in readme and "RMSE" in readme
    for cond, share in cfg.capacity.profile_blend.items():
        assert f"{cond} {share:g}" in readme or f"{share:g}" in readme
