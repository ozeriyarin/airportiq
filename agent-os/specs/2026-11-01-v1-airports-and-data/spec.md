# Spec: v1 airports and data

Status: shaped 1.11.2026, awaiting owner approval.

## Goal

Give the platform its data: a generated, committed registry of every FAA large, medium and small hub airport with
Census region and division and name aliases; frozen Parquet snapshots of FAA TAF (operations and enplanements,
history and forecast), BTS On-Time aggregates (delays, taxi-out), hand-downloaded BTS T-100 aggregates (seats,
passengers, distance, international) and runway inventory; FAA capacity profile rates extracted into config; a
DuckDB store; and a live FAA NAS status client. After this spec every later number has a deterministic,
offline-testable source, and `/health` says what data is loaded.

## Scope

**In:** `config/airports.yaml` (generated); `config/capacity_profiles.yaml` (extracted); `config/areas.yaml`
(Census regions and divisions by state, plus area aliases such as "West Coast"); `app/data` package (registry
builder, TAF reader, enplanement reader, OurAirports reader, On-Time aggregator, T-100 aggregator, profile
extractor, snapshot writer, DuckDB store, NAS status client, ingest); CLI `agent registry | ingest | profiles`;
`ToolContext` handles; `Health.data`; fixtures; the committed snapshots under `data/snapshots/`.

**Out:** scores, tools, prompts, eval cases (v2, v3); OpenSky (v6); any scheduled refresh; ASPM.

## Acceptance criteria

1. `config/areas.yaml` maps every US state and DC to one Census region and division, and defines area aliases (`new england`, `west coast`, `southwest`, …) as state lists; loading rejects an unknown state.
2. `agent registry` builds `config/airports.yaml` from the FAA TAF airport table (universe = hub size L/M/S, FAA annual service volume, coordinates), the FAA CY2025 enplanement xlsx (current hub class, boardings) and OurAirports (ICAO, decimal coordinates, runways), and the committed file validates: a version, source names, unique ids, lat/lon in range, hub class, region and division from `areas.yaml`, service volume, runway counts, longest runway. (Round 1 change: the TAF table replaced the enplanement file as the universe because it carries the FAA service volume; the timezone field was dropped, no component needs it.)
3. The committed registry contains BOS, BDL, PVD, MHT, PWM, BTV (division New England), LAX, SNA, ANC and SFO, and at least 100 airports in total.
4. `AirportRegistry.find` resolves an id, IATA, ICAO, city or alias case-insensitively ("LA", "Santa Ana", "John Wayne", "anchorage") and returns None for an unknown name; ambiguous matches return the candidates; `in_area("new england")`, `in_region`, `in_division`, `in_state` filter from data.
5. The TAF reader opens the zip's xlsx files and yields one row per airport and fiscal year, flagged actual (scenario 0) or forecast (scenario 1), with operations (air carrier, air taxi/commuter, GA, military; total excludes overflights) and enplanements including the international split (US-flag and foreign-flag), for registry airports, with column names verified against the file, and raises `SourceError` on a missing column or zip member.
6. The OurAirports reader counts open runways per airport, open runways of at least 6,000 ft, and the longest runway, joined by ICAO/IATA; a closed runway never counts.
7. The On-Time aggregator reads one monthly zip and emits one row per origin and month: departures, cancelled, delayed ≥ 15 min, mean and 10th-percentile taxi-out, departures with distance ≥ the configured long-haul miles; the fields are read by name and a missing field raises `SourceError`.
8. The T-100 aggregator reads the hand-downloaded CSVs and emits one row per origin, year, international flag and long-haul flag with departures performed, seats and passengers; it rejects a file whose header lacks any required field; the manifest records the download method and date.
9. The profile extractor parses every wording variant of the "capacity rate range in <Visual|Marginal|Instrument> conditions ... A-B operations per hour" sentence seen in the 2014–2019 PDFs (flow named before or after the condition, broken words, en dashes, single values, "Low Instrument") and writes per-airport rates per condition with the profile year and URL; a fixture yields the SFO 2019 values (visual 104–107, marginal 93–98, instrument 76–78 for the primary configuration) and the committed file covers at least 30 airports.
10. `write_snapshot` writes the Parquet files and `manifest.json` (per source: method, fetched_at, period, rows, COVID years flagged); `Store` reads them back and synthetic rows round-trip unchanged.
11. `Store` exposes `taf(airport, years)`, `ontime(airport, years)`, `t100(airport, years)`, `coverage()` and `years(source)`; `coverage` gives first and last period and row count per source.
12. `ingest` runs each source (or a `--source` subset) through its client, writes one snapshot, and a re-run replaces it; the committed snapshot covers every registry airport in TAF, On-Time 2023–2025 and T-100 for the downloaded years, with no duplicate keys.
13. The NAS status client parses the XML into `LiveStatus(available, closures, ground_stops, ground_delays, arrival_departure_delays, update_time)` per airport, sends the configured User-Agent, caches for `LIVE_CACHE_MIN` (1 min after failure), and a failed request returns `available=False` with a reason and does not raise.
14. `compose` builds `ToolContext` with the registry, store, profiles and live client; with no snapshot present the store is None, a warning is logged, and the app still composes and answers in test mode.
15. `GET /health` reports `data` with airport count, per-source coverage and the manifest date when a snapshot is loaded, and `null` when it is missing.

## Design

New package `src/app/data/`:

- `areas.py`: `Areas` from `config/areas.yaml` (state → region, division; alias → states).
- `registry.py`: `Airport` (id = FAA LID, iata, icao, name, city, state, region, division, hub_class, lat, lon,
  timezone, enplanements_cy25, enplanements_cy24, runways, runways_6000ft, longest_runway_ft, aliases) and
  `AirportRegistry` (`load`, `all`, `by_id`, `find`, `in_area`, `in_region`, `in_division`, `in_state`, `version`).
  `build_registry(enplanements_xlsx, airports_csv, runways_csv, areas, aliases)` is pure over parsed inputs;
  hand aliases live in `config/aliases.yaml` (small: LA, John Wayne, Logan, Dulles, Reagan, O'Hare, …).
- `taf.py`: `TafRow(airport, fiscal_year, enplanements, ops_total, ops_air_carrier, ops_commuter, ops_ga, ops_military, forecast: bool)`.
- `enplanements.py`, `ourairports.py`: readers over the xlsx and CSVs.
- `ontime.py`: `OnTimeMonth(airport, year, month, departures, cancelled, delayed15, taxi_out_mean, taxi_out_p10, long_haul_departures)`, DuckDB `read_csv` over the extracted CSV, one aggregation query.
- `t100.py`: `T100Row(airport, year, international, long_haul, departures, seats, passengers)`.
- `profiles.py`: `ProfileRates(airport, year, visual, marginal, instrument, url)` with `(min, max)` tuples; pypdf
  text extraction; regex on the fixed sentence; first configuration per condition is the primary one.
- `snapshot.py`, `store.py`: DuckDB write and read; `Manifest` with a `sources` map.
- `live.py`: `NasStatusClient(http, user_agent, cache_min, now)`; XML via `xml.etree`; per-airport view over one feed.
- `ingest.py`: sequential per source with backoff; `--source`, `--years`, `--raw-dir`.

Downloads: TAF zip, enplanement xlsx, OurAirports CSVs and On-Time zips are fetched by `ingest` into
`data/raw/` (gitignored) with the browser-like `FAA_USER_AGENT`. T-100 CSVs are placed in `data/raw/t100/` by hand
(owner or browser pane) from TranStats "T-100 Segment (All Carriers)" with fields YEAR, MONTH, ORIGIN, DEST,
ORIGIN_COUNTRY, DEST_COUNTRY, UNIQUE_CARRIER, DEPARTURES_PERFORMED, SEATS, PASSENGERS, DISTANCE for 2023–2025.

All HTTP clients take an `httpx2.AsyncClient`; production uses the retrying client, tests `MockTransport` with
trimmed fixtures (one TAF xlsx sheet with three airports, one On-Time CSV with 50 rows, one T-100 CSV with 30
rows, one NAS status XML, one profile page text). Settings: `FAA_USER_AGENT`, `SNAPSHOT_DIR`, `LIVE_CACHE_MIN`.
Dependencies: `duckdb`, `openpyxl`, `pypdf`.

Storage rationale (DESIGN): the aggregates are small (~130 airports × months or years), read-only at runtime and
queried analytically; committing Parquet means deploys need no network, no hand-downloaded file, and the demo
cannot be broken by an upstream outage. Raw files stay out of the repo.

## Tasks

1. Save spec documentation.
2. `areas.yaml`, `aliases.yaml`, `areas.py`, readers, `build_registry`, `agent registry`; run it, commit `airports.yaml`.
3. `taf.py`, `ontime.py`, `t100.py`, `snapshot.py`, `store.py` with fixtures and tests.
4. `profiles.py`, `agent profiles`; run it over the 33 PDFs, commit `capacity_profiles.yaml`.
5. `live.py` with fixture and tests.
6. T-100 download (browser pane, owner watching), `ingest.py`, `agent ingest`, `compose` wiring, `Health.data`.
7. Run the real ingest, inspect coverage, commit `data/snapshots/`.
8. `tests/test_v1_airports_and_data.py`; README data section, DESIGN data layer, roadmap; `ruff`, `pytest`, commit, push.
