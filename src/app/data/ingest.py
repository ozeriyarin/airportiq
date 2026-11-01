"""Ingest: fetch the public files into data/raw (gitignored), aggregate them, write the committed snapshot."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from app.data.errors import SourceError
from app.data.ontime import OnTimeMonth, aggregate_month
from app.data.registry import AirportRegistry
from app.data.snapshot import COVID_YEARS, Manifest, SourceManifest, read_manifest, write_snapshot
from app.data.t100 import T100Row
from app.data.t100 import aggregate as aggregate_t100
from app.data.taf import TafArchive, TafRow

log = logging.getLogger(__name__)

TAF_URL = "https://taf.faa.gov/Downloads/APO100_TAF_Final_2025.zip"
ONTIME_URL = "https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
SOURCES = ("taf", "ontime", "t100")


async def fetch(http: httpx2.AsyncClient, url: str, dest: Path, user_agent: str) -> Path:
    """Download once; an existing non-empty file is kept. Streams to a temp file and renames."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    async with http.stream("GET", url, headers={"User-Agent": user_agent}) as r:
        if r.status_code != 200:
            raise SourceError(f"GET {url} returned {r.status_code}: {(await r.aread())[:200]!r}")
        with tmp.open("wb") as f:
            async for chunk in r.aiter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    return dest


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def ingest(
    registry: AirportRegistry, http: httpx2.AsyncClient, raw_dir: Path, out_dir: Path, *, user_agent: str,
    years: tuple[int, int], long_haul_miles: int, sources: tuple[str, ...] = SOURCES, manifest_version: str = "1.0.0",
) -> Manifest:
    """Run each selected source end to end and write the snapshot; sources left out keep their previous table."""
    airports = {a.id for a in registry.all}
    previous = read_manifest(out_dir)
    manifests: dict[str, SourceManifest] = dict(previous.sources) if previous else {}
    taf_rows: list[TafRow] | None = None
    ontime_rows: list[OnTimeMonth] | None = None
    t100_rows: list[T100Row] | None = None

    if "taf" in sources:
        zip_path = await fetch(http, TAF_URL, raw_dir / "taf" / TAF_URL.rsplit("/", 1)[-1], user_agent)
        taf_rows = TafArchive(zip_path).rows(airports)
        fy = [r.fiscal_year for r in taf_rows]
        manifests["taf"] = SourceManifest(method=f"http GET {TAF_URL}", fetched_at=_now(), period=f"FY{min(fy)}-FY{max(fy)}",
                                          rows=len(taf_rows), files=[zip_path.name], note="scenario 0 actual, 1 forecast")
        log.info("taf: %d rows", len(taf_rows))

    if "ontime" in sources:
        ontime_rows, files = [], []
        for year in range(years[0], years[1] + 1):
            for month in range(1, 13):
                url = ONTIME_URL.format(year=year, month=month)
                path = raw_dir / "ontime" / f"ontime_{year}_{month}.zip"
                try:
                    await fetch(http, url, path, user_agent)
                except SourceError as e:  # a month not yet published ends the series
                    log.warning("ontime %d-%02d skipped: %s", year, month, e)
                    continue
                ontime_rows += aggregate_month(path, airports, long_haul_miles)
                files.append(path.name)
                log.info("ontime %d-%02d: %d airports", year, month, sum(1 for r in ontime_rows if r.year == year and r.month == month))
        ym = sorted((r.year, r.month) for r in ontime_rows)
        manifests["ontime"] = SourceManifest(method=f"http GET {ONTIME_URL}", fetched_at=_now(),
                                             period=f"{ym[0][0]}-{ym[0][1]:02d}..{ym[-1][0]}-{ym[-1][1]:02d}" if ym else "none",
                                             rows=len(ontime_rows), files=files, note="domestic reporting carriers only")

    if "t100" in sources:
        csvs = sorted((raw_dir / "t100").glob("*.csv"))
        t100_rows = aggregate_t100(csvs, airports, long_haul_miles)
        yrs = sorted({r.year for r in t100_rows})
        manifests["t100"] = SourceManifest(
            method="manual TranStats download: T-100 Segment (All Carriers), fields YEAR, MONTH, ORIGIN, DEST, DEST_COUNTRY, "
                   "UNIQUE_CARRIER, CLASS, DEPARTURES_PERFORMED, SEATS, PASSENGERS, DISTANCE",
            fetched_at=_now(), period=f"{yrs[0]}-{yrs[-1]}" if yrs else "none", rows=len(t100_rows), files=[p.name for p in csvs],
            note="no scripted URL exists for T-100; downloaded by hand through the TranStats form",
        )

    manifest = Manifest(version=manifest_version, written_at=_now(), registry_version=registry.version, airports=len(airports),
                        long_haul_miles=long_haul_miles, covid_years=list(COVID_YEARS), sources=manifests)
    write_snapshot(out_dir, manifest, taf=taf_rows, ontime=ontime_rows, t100=t100_rows)
    return manifest
