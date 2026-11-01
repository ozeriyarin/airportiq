# v1 airports and data — Shaping Notes

## Scope

Registry of the FAA hub universe, frozen snapshots of the public traffic sources, FAA capacity profile extraction,
a DuckDB store and a live FAA status client. Every later number has a deterministic, offline-testable source.

## Decisions

- **The FAA TAF airport table is the universe**, not the enplanement file: it carries hub size, coordinates and the
  FAA annual service volume (`SER_VOL`, populated for 140 of the 144 hubs). The enplanement file adds the current
  hub class and boardings; OurAirports adds ICAO, decimal coordinates and runways. The city comes from the TAF
  because the FAA enplanement file swaps City and Airport Name on some rows (SFO).
- **TAF scenario codes:** 0 = actual (FY1976–FY2024), 1 = forecast (FY2025–FY2055). Locids carry trailing spaces.
  The enplanement sheet's `us_flag` + `frgn_flag` columns are international enplanements, so an international
  share exists for every airport without T-100.
- **On-Time aggregated at ingest** with DuckDB (one monthly zip ≈ 600k flights → one row per origin and month).
  Cancelled flights are excluded from delay and taxi statistics; `DepDel15` and `TaxiOut` are read by name.
- **T-100 by hand:** no scripted URL exists. Three yearly CSVs (2023, 2024, 2025) downloaded through the TranStats
  form in the browser pane during the session with fields DEPARTURES_PERFORMED, SEATS, PASSENGERS, DISTANCE,
  UNIQUE_CARRIER, ORIGIN, DEST, DEST_COUNTRY, YEAR, MONTH, CLASS; aggregated per origin, year, international,
  long-haul and cargo flag (CLASS ≠ F). Raw CSVs are gitignored; the manifest records the method.
- **Capacity profiles:** 31 of the 35 PDFs parse (the combined 2014 file and three appendix files are skipped or
  duplicate). Five wording variants across 2014–2019 are handled; "Low Instrument" never becomes the primary rate.
- **Timezone dropped** from the registry: no component needs it, and OurAirports does not carry it.
- **defusedxml** for the live feed: the FAA XML is external input.

## Context

- **References:** hubrisk `app/data` (registry, store, NWS client with cache and degradation).
- **Product alignment:** mission "regions are data", "now vs history".

## Standards Applied

- data-sources, testing, secrets-and-config, python-style.
