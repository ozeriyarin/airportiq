# Data sources

- Airports are data: `config/airports.yaml` (FAA LID, IATA, ICAO, name, city, state, Census region and division, hub
  class, lat/lon, timezone, runway counts, aliases), **generated** by `agent registry` from the FAA enplanement file
  and OurAirports, then committed with the source files' dates. Filters ("New England", "West Coast", a state) read
  this file; the model never decides which airport belongs where. Aliases resolve names ("LA", "John Wayne").
- History is frozen: `agent ingest` fetches FAA TAF, BTS On-Time (monthly zips, years from config) and the hand-
  downloaded T-100 CSVs under `data/raw/` (gitignored), aggregates them with DuckDB, and writes
  `data/snapshots/*.parquet` + `manifest.json`, which are committed. A deploy never re-ingests.
- Aggregate at ingest, not at query time: On-Time (~600k rows a month) becomes one row per origin and month; T-100
  becomes one row per origin, year, domestic/international flag and long-haul flag. Raw files never ship.
- The manifest records per source: URL or download method, fetched_at, period covered, row count, and for T-100 the
  TranStats table name, field list and download date, because it was fetched by hand.
- Capacity rates: `agent profiles` downloads the FAA Airport Capacity Profile PDFs, extracts the "capacity rate range
  in <condition> ... is currently A-B operations per hour" sentences, and writes `config/capacity_profiles.yaml`
  (airport, profile year, visual/marginal/instrument min–max, source URL). Committed; re-run only to refresh.
- Queries over history go through DuckDB in-process, reading Parquet directly. One `Store` type wraps the connection;
  tests build it from small fixture Parquet files.
- Live conditions come from the FAA NAS status XML (`nasstatus.faa.gov`). Every external request sends the configured
  `FAA_USER_AGENT` (faa.gov rejects requests without a browser-like UA). Cached 10 minutes, 1 minute after a failure.
- Each external client takes an `httpx2.AsyncBaseTransport`; tests use `MockTransport` with trimmed recorded fixtures
  in `tests/fixtures/` and a `.meta.json` (date, URL). Never patch the network. Never edit fixture text to pass a test.
- Units and fields are verified from the response (xlsx headers, CSV columns), not from documentation; a mismatch
  raises `SourceError` at ingest, never a silent zero.
- A failed live call degrades, not crashes: the tool returns `available=false` with a reason and the answer's
  `limitations` says live data was unavailable. Dead sources are visible in `/health`.
- COVID years 2020–2021 are flagged in the manifest and excluded from trend fits by default; the answer says so when
  a trend is quoted.
