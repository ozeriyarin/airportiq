"""Acceptance criteria of agent-os/specs/2026-11-01-v1-airports-and-data, one test per criterion, all offline."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx2
import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import cli as cli_module
from app.api.app import create_app
from app.api.sessions import SessionStore
from app.config import CONFIG_DIR, ROOT
from app.data.areas import US_STATES, Areas, load_areas
from app.data.enplanements import read_enplanements
from app.data.errors import SourceError
from app.data.ingest import ingest
from app.data.live import NasStatusClient, parse_feed
from app.data.ontime import OnTimeMonth, aggregate_month
from app.data.ourairports import read_airports as oa_airports
from app.data.ourairports import read_runways
from app.data.profiles import load_profiles, parse_rates
from app.data.registry import Airport, AirportRegistry, build_registry, load_aliases
from app.data.snapshot import Manifest, SourceManifest, read_manifest, write_snapshot
from app.data.store import Store
from app.data.t100 import T100Row, aggregate
from app.data.taf import TafArchive, TafRow, dms_to_decimal, read_airports, read_rows
from tests import data_fixtures as fx

BRIEF = ("BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA", "ANC", "SFO")
SNAPSHOT = ROOT / "data" / "snapshots"


@pytest.fixture
def areas() -> Areas:
    return load_areas()


@pytest.fixture
def small_registry(areas) -> AirportRegistry:
    data = build_registry(
        read_airports(fx.taf_airports_xlsx()), read_enplanements(fx.enplanements_xlsx()), oa_airports(fx.OA_AIRPORTS_CSV.encode()),
        read_runways(fx.OA_RUNWAYS_CSV.encode()), areas, {"SFO": ["san fran"], "BOS": ["logan"]}, generated="2026-11-01", sources={"t": "x"},
    )
    return AirportRegistry(data, areas)


def test_criterion_1_areas_cover_every_state_and_reject_unknown(areas: Areas):
    assert {s for d in areas.divisions.values() for s in d.states} == US_STATES
    assert areas.division_of("MA") == "New England" and areas.region_of("MA") == "Northeast"
    assert set(areas.states_in("new england")) == {"CT", "ME", "MA", "NH", "RI", "VT"}
    assert areas.states_in("West Coast") == ["CA", "OR", "WA"] and areas.states_in("ca") == ["CA"]
    assert areas.states_in("Midwest") and areas.states_in("Atlantis") is None
    bad = yaml.safe_load((CONFIG_DIR / "areas.yaml").read_text(encoding="utf-8"))
    bad["divisions"]["Pacific"]["states"].append("ZZ")
    with pytest.raises(ValueError, match="unknown state"):
        Areas.model_validate(bad)


def test_criterion_2_registry_is_built_from_taf_enplanements_and_ourairports_and_validates(small_registry: AirportRegistry):
    ids = [a.id for a in small_registry.all]
    assert ids == ["BOS", "PWM", "SFO", "XNA"]  # 00F is not a hub and is dropped
    sfo = small_registry.by_id("SFO")
    assert sfo.hub_class == "L" and sfo.service_volume == 393000 and sfo.icao == "KSFO" and sfo.iata == "SFO"
    assert sfo.city == "San Francisco" and sfo.name == "San Francisco International"  # TAF city, FAA file name
    assert sfo.lat == pytest.approx(37.619, abs=0.001) and sfo.runways == 4 and sfo.runways_6000ft == 4 and sfo.longest_runway_ft == 11870
    assert small_registry.by_id("BOS").runways == 2 and small_registry.by_id("BOS").runways_6000ft == 1  # 2,557 ft strip excluded
    assert small_registry.by_id("XNA").service_volume == 0 and small_registry.by_id("PWM").enplanements_latest == 1287041
    assert dms_to_decimal("122-22-31.5000W") == pytest.approx(-122.3754, abs=0.001)
    committed = yaml.safe_load((CONFIG_DIR / "airports.yaml").read_text(encoding="utf-8"))
    assert committed["version"] and committed["generated"] and committed["sources"]
    for a in committed["airports"]:
        Airport.model_validate(a)
    with pytest.raises(ValueError):
        Airport.model_validate({**committed["airports"][0], "hub_class": "N"})


def test_criterion_3_committed_registry_has_the_brief_airports_and_the_hub_universe():
    r = AirportRegistry.load()
    for code in BRIEF:
        assert r.by_id(code) is not None, code
    for code in ("BOS", "BDL", "PVD", "MHT", "PWM", "BTV"):
        assert r.by_id(code).division == "New England"
    assert len(r.all) >= 100 and {a.hub_class for a in r.all} == {"L", "M", "S"}
    assert sum(a.service_volume > 0 for a in r.all) >= len(r.all) - 5


def test_criterion_4_find_resolves_ids_names_aliases_and_filters_areas(small_registry: AirportRegistry):
    r = AirportRegistry.load()
    assert r.find("LA").id == "LAX" and r.find("Santa Ana").id == "SNA" and r.find("John Wayne").id == "SNA"
    assert r.find("anchorage").id == "ANC" and r.find("ksfo").id == "SFO" and r.find("Boston Logan Airport").id == "BOS"
    assert r.find("Atlantis") is None
    ambiguous = r.find("portland")
    assert isinstance(ambiguous, list) and {a.id for a in ambiguous} == {"PDX", "PWM"}
    assert {a.id for a in r.in_area("new england")} >= {"BOS", "BDL", "PVD", "MHT", "PWM", "BTV"}
    assert r.in_area("Atlantis") is None and r.in_area("CA") and r.in_region("west") and r.in_division("pacific")
    assert [a.id for a in r.in_state("me")] == ["PWM"] or "PWM" in [a.id for a in r.in_state("me")]
    assert small_registry.find("san fran").id == "SFO" and small_registry.find("logan").id == "BOS"


def test_criterion_5_taf_reader_yields_actual_and_forecast_rows_and_rejects_missing_columns(tmp_path: Path):
    zip_path = tmp_path / "APO100_TAF_Final_2025.zip"
    zip_path.write_bytes(fx.taf_zip())
    archive = TafArchive(zip_path)
    rows = archive.rows({"SFO", "BOS", "PWM"})
    sfo = {r.fiscal_year: r for r in rows if r.airport == "SFO"}
    assert sfo[2024].actual and not sfo[2025].actual and sfo[2024].ops_total == 350000 + 21000 + 7000 + 3304
    assert sfo[2024].enplanements == 15383330 + 169 + 2107019 + 3093934 + 4181190 and sfo[2024].enp_international == 3093934 + 4181190
    assert sfo[2024].ops_air_carrier == 350000 and sfo[2024].ops_commuter == 21000 and sfo[2024].ops_military == 3304
    assert not any(r.airport == "00F" for r in rows)
    bad = fx.xlsx_bytes(("locid", "scenario", "ayear", "itn_Ac"), [("SFO", 0, 2024, 1)])
    with pytest.raises(SourceError, match="missing columns"):
        read_rows(bad, fx.taf_enp_xlsx(), {"SFO"})
    with pytest.raises(SourceError, match="lacks"):
        TafArchive(_zip_without(tmp_path, "Enplanements.xlsx")).rows({"SFO"})


def _zip_without(tmp_path: Path, member: str) -> Path:
    p = tmp_path / "partial.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Airports.xlsx", fx.taf_airports_xlsx())
        if member != "AirportsOperations.xlsx":
            z.writestr("AirportsOperations.xlsx", fx.taf_ops_xlsx())
    return p


def test_criterion_6_ourairports_runway_counts_ignore_closed_and_short_strips():
    airports = {a.iata: a for a in oa_airports(fx.OA_AIRPORTS_CSV.encode())}
    runways = read_runways(fx.OA_RUNWAYS_CSV.encode())
    sfo, bos = runways[airports["SFO"].ref], runways[airports["BOS"].ref]
    assert (sfo.runways, sfo.runways_6000ft, sfo.longest_ft) == (4, 4, 11870)  # the closed 9,000 ft one never counts
    assert (bos.runways, bos.runways_6000ft, bos.longest_ft) == (2, 1, 10083)
    assert "00A" not in {a.local_code for a in airports.values()}  # heliports are out
    with pytest.raises(SourceError, match="missing columns"):
        read_runways(b"id,airport_ref\n1,2\n")


def test_criterion_7_ontime_month_aggregates_per_origin_by_name(tmp_path: Path):
    zip_path = tmp_path / "ontime_2025_1.zip"
    zip_path.write_bytes(fx.ontime_zip())
    rows = {r.airport: r for r in aggregate_month(zip_path, {"SFO", "BOS", "PWM", "ANC"}, 3000)}
    sfo = rows["SFO"]
    assert (sfo.year, sfo.month, sfo.departures, sfo.cancelled, sfo.delayed15, sfo.long_haul_departures) == (2025, 1, 7, 1, 2, 1)
    assert sfo.operated == 6 and sfo.taxi_out_mean == pytest.approx((12 + 18 + 15 + 30 + 10 + 11) / 6)
    assert sfo.taxi_out_p10 is not None and 10 <= sfo.taxi_out_p10 <= 11
    assert rows["BOS"].departures == 1 and "ANC" not in rows
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x.csv", "Year,Month,Origin\n2025,1,SFO\n")
    with pytest.raises(SourceError, match="missing columns"):
        aggregate_month(bad, {"SFO"}, 3000)


def test_criterion_8_t100_aggregates_by_origin_year_international_long_haul_and_cargo(tmp_path: Path):
    p = tmp_path / "t100_2025.csv"
    p.write_text(fx.t100_csv(), encoding="utf-8")
    rows = aggregate([p], {"SFO", "BOS", "PWM"}, 3000)
    sfo = [r for r in rows if r.airport == "SFO"]
    intl_pax = next(r for r in sfo if r.international and r.long_haul and not r.cargo)
    assert (intl_pax.departures, intl_pax.seats, intl_pax.passengers) == (50, 15000, 13500)
    cargo = next(r for r in sfo if r.cargo)
    assert cargo.international and cargo.long_haul and cargo.seats == 0 and cargo.departures == 30
    domestic = [r for r in sfo if not r.international]
    assert sum(r.departures for r in domestic) == 120 and not any(r.long_haul for r in domestic)
    assert next(r for r in rows if r.airport == "BOS" and r.international).long_haul  # 3,255 mi to LHR
    bad = tmp_path / "bad.csv"
    bad.write_text("YEAR,ORIGIN,SEATS\n2025,SFO,1\n", encoding="utf-8")
    with pytest.raises(SourceError, match="missing T-100 columns"):
        aggregate([bad], {"SFO"}, 3000)
    with pytest.raises(SourceError, match="no T-100"):
        aggregate([], {"SFO"}, 3000)


def test_criterion_9_profile_extractor_reads_every_wording_variant():
    rates = parse_rates(fx.PROFILE_TEXT, "SFO", 2019, "https://x/SFO.pdf")
    assert (rates.primary("visual").low, rates.primary("visual").high) == (104, 107)
    assert (rates.primary("marginal").low, rates.primary("marginal").high) == (93, 98)
    assert (rates.primary("instrument").low, rates.primary("instrument").high) == (76, 78)
    assert [r.configuration for r in rates.visual] == ["28/01 Side-Byes", "28RT Stagger-Byes"]
    assert rates.instrument[-1].configuration.startswith("low instrument") and rates.instrument[-1].low == 60
    variants = ("The capacity rate range in South flow Visual conditions is cu rrently 172-173 operations per hour. "
                "The capacity rate range for East Flow operations in Marginal conditions is ~61 operations per hour. "
                "The capacity rate in Instrument conditions in Alternate South Flow is currently 77 operations per hour.")
    v = parse_rates(variants, "CLT", 2015, "u")
    assert (v.primary("visual").low, v.primary("marginal").low, v.primary("instrument").high) == (172, 61, 77)
    committed = load_profiles()
    assert committed and len(committed.profiles) >= 30 and committed.by_airport()["SFO"].primary("visual").high == 107
    for p in committed.profiles:
        assert p.url.startswith("https://www.faa.gov/") and 2014 <= p.year <= 2019


def test_criterion_10_snapshot_round_trips_and_writes_a_manifest(tmp_path: Path):
    taf = [TafRow(airport="SFO", fiscal_year=2024, actual=True, ops_air_carrier=1, enp_air_carrier=2, enp_intl_foreign_flag=3)]
    ontime = [OnTimeMonth(airport="SFO", year=2025, month=1, departures=7, cancelled=1, delayed15=2, taxi_out_mean=16.0, taxi_out_p10=10.5, long_haul_departures=1)]
    t100 = [T100Row(airport="SFO", year=2025, international=True, long_haul=True, cargo=False, departures=50, seats=15000, passengers=13500)]
    manifest = Manifest(version="1.0.0", written_at="2026-11-01T00:00:00+00:00", registry_version="1.0.0", airports=1, long_haul_miles=3000,
                        sources={"taf": SourceManifest(method="http GET x", fetched_at="2026-11-01", period="FY2024", rows=1)})
    write_snapshot(tmp_path, manifest, taf=taf, ontime=ontime, t100=t100)
    assert (tmp_path / "taf.parquet").exists() and json.loads((tmp_path / "manifest.json").read_text())["covid_years"] == [2020, 2021]
    store = Store.open_if_present(tmp_path)
    assert store.taf("SFO") == taf and store.ontime("SFO") == ontime and store.t100("SFO") == t100
    assert read_manifest(tmp_path).sources["taf"].period == "FY2024" and Store.open_if_present(tmp_path / "nope") is None


def test_criterion_11_store_queries_years_and_coverage(tmp_path: Path):
    taf = [TafRow(airport="SFO", fiscal_year=y, actual=y <= 2024) for y in (2023, 2024, 2025)]
    ontime = [OnTimeMonth(airport="SFO", year=2025, month=m, departures=1, cancelled=0, delayed15=0, taxi_out_mean=1, taxi_out_p10=1, long_haul_departures=0) for m in (1, 2)]
    manifest = Manifest(version="1", written_at="x", registry_version="1", airports=1, long_haul_miles=3000, sources={})
    write_snapshot(tmp_path, manifest, taf=taf, ontime=ontime)
    store = Store.open_if_present(tmp_path)
    assert [r.fiscal_year for r in store.taf("SFO", (2024, 2025))] == [2024, 2025] and store.years("taf") == [2023, 2024]
    assert store.years("ontime") == [2025] and store.years("t100") == [] and store.t100("SFO") == []
    cov = {c.source: c for c in store.coverage()}
    assert (cov["taf"].first, cov["taf"].last, cov["taf"].rows, cov["taf"].airports) == ("2023", "2025", 3, 1)
    assert (cov["ontime"].first, cov["ontime"].last) == ("202501", "202502")


async def test_criterion_12_ingest_runs_sources_writes_one_snapshot_and_the_committed_one_is_complete(tmp_path: Path, small_registry):
    raw, out = tmp_path / "raw", tmp_path / "snap"
    (raw / "t100").mkdir(parents=True)
    (raw / "t100" / "t100_2025.csv").write_text(fx.t100_csv(), encoding="utf-8")
    served: list[str] = []

    def transport(request: httpx2.Request) -> httpx2.Response:
        served.append(request.url.path)
        if "APO100" in request.url.path:
            return httpx2.Response(200, content=fx.taf_zip())
        if request.url.path.endswith("_2025_1.zip"):
            return httpx2.Response(200, content=fx.ontime_zip(1))
        return httpx2.Response(404, text="not published")

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(transport))
    m = await ingest(small_registry, http, raw, out, user_agent="t", years=(2025, 2025), long_haul_miles=3000)
    assert set(m.sources) == {"taf", "ontime", "t100"} and m.sources["ontime"].period == "2025-01..2025-01"
    assert m.sources["t100"].method.startswith("manual TranStats") and (raw / "taf").exists()
    m2 = await ingest(small_registry, http, raw, out, user_agent="t", years=(2025, 2025), long_haul_miles=3000, sources=("taf",))
    assert m2.sources["ontime"].rows == m.sources["ontime"].rows and served.count("/Downloads/APO100_TAF_Final_2025.zip") == 1
    committed = Store.open_if_present(SNAPSHOT)
    assert committed is not None, "run `agent ingest` and commit data/snapshots"
    registry = AirportRegistry.load()
    ids = {a.id for a in registry.all}
    cov = {c.source: c for c in committed.coverage()}
    assert cov["taf"].airports == len(ids) and committed.manifest.registry_version == registry.version
    assert cov["ontime"].first <= "202301" and cov["ontime"].last >= "202512"
    assert "t100" in cov and cov["t100"].first <= "2023" and cov["t100"].last >= "2025"
    dup = committed._q("SELECT airport, fiscal_year, COUNT(*) c FROM taf GROUP BY ALL HAVING c > 1")
    assert dup == [] and committed._q("SELECT airport, year, month, COUNT(*) c FROM ontime GROUP BY ALL HAVING c > 1") == []


async def test_criterion_13_live_status_parses_caches_and_degrades():
    update, events = parse_feed(fx.NAS_XML)
    assert update.startswith("Sun Nov 1") and {e.kind for e in events} == {"Airport Closures", "Ground Stop Programs", "General Arrival/Departure Delay Info"}
    calls: list[str] = []
    clock = [0.0]

    def transport(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.headers.get("User-Agent", ""))
        return httpx2.Response(200, text=fx.NAS_XML) if len(calls) < 3 else httpx2.Response(503, text="down")

    client = NasStatusClient(httpx2.AsyncClient(transport=httpx2.MockTransport(transport)), "airportiq-test", cache_min=10, now=lambda: clock[0])
    sfo = await client.status("sfo")
    assert sfo.available and len(sfo.events) == 2 and sfo.events[0].kind == "Ground Stop Programs" and sfo.events[0].reason.startswith("WEATHER")
    assert (await client.status("BOS")).events == [] and calls == ["airportiq-test"]  # second call within the TTL: no request
    clock[0] = 601
    assert (await client.status("LAX")).events[0].kind == "Airport Closures" and len(calls) == 2
    clock[0] = 1202
    down = await client.status("LAX")
    assert not down.available and "unavailable" in down.reason and len(calls) == 3
    clock[0] = 1230
    await client.status("LAX")
    assert len(calls) == 3  # failures are cached for one minute
    clock[0] = 1270
    await client.status("LAX")
    assert len(calls) == 4


def test_criterion_14_compose_without_snapshot_still_answers_in_test_mode(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "missing"))
    app = cli_module.compose(model_mode="test")
    assert app.data is None and app.service.deps.store is None and app.service.deps.registry is not None
    assert app.service.deps.live is not None and app.service.deps.profiles is not None
    assert any("no snapshot" in r.getMessage() for r in caplog.records)
    assert "NOT loaded" in app.service.deps.data_facts
    result = CliRunner().invoke(cli_module.cli, ["chat", "--test", "Which airports are in New England?"])
    assert result.exit_code == 0 and "answered" in result.output, result.output


def test_criterion_15_health_reports_data_coverage_or_null(service, budget, tmp_path: Path):
    client = TestClient(create_app(service, SessionStore(max_turns=5, ttl_s=60), budget, model_names=["fake"], guard_name="g"))
    assert client.get("/health").json()["data"] is None
    manifest = Manifest(version="1", written_at="2026-11-01T10:00:00+00:00", registry_version="1.0.0", airports=1, long_haul_miles=3000, sources={})
    write_snapshot(tmp_path, manifest, taf=[TafRow(airport="SFO", fiscal_year=2024, actual=True)])
    data = Store.open_if_present(tmp_path).summary()
    client = TestClient(create_app(service, SessionStore(max_turns=5, ttl_s=60), budget, model_names=["fake"], guard_name="g", data=data))
    payload = client.get("/health").json()["data"]
    assert payload["airports"] == 1 and payload["sources"]["taf"]["rows"] == 1 and payload["written_at"].startswith("2026-11-01")
    assert load_aliases()["LAX"] == ["la", "los angeles", "l.a."]
