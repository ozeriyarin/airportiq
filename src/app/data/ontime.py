"""BTS Airline On-Time Performance: one monthly zip (~600k flights) aggregated with DuckDB into one row per origin
airport and month. Domestic reporting carriers only; the raw file never ships."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import duckdb
from pydantic import BaseModel

from app.data.errors import SourceError

REQUIRED = ("Year", "Month", "Origin", "DepDel15", "TaxiOut", "Cancelled", "Distance")
MIN_DEPARTURES = 300  # below this a month's delay statistics are too thin to score


class OnTimeMonth(BaseModel):
    airport: str
    year: int
    month: int
    departures: int  # scheduled departures in the file, cancelled included
    cancelled: int
    delayed15: int  # operated departures leaving 15+ minutes late
    taxi_out_mean: float | None  # minutes, operated departures
    taxi_out_p10: float | None  # the airport's own unimpeded proxy
    long_haul_departures: int  # operated departures with Distance >= the configured miles

    @property
    def operated(self) -> int:
        return self.departures - self.cancelled


def _header(csv_path: Path) -> list[str]:
    with csv_path.open(encoding="utf-8", errors="replace") as f:
        return [c.strip().strip('"') for c in f.readline().strip().split(",")]


def aggregate_month(zip_path: Path, airports: set[str], long_haul_miles: int) -> list[OnTimeMonth]:
    """Extract the CSV from one monthly zip and aggregate per origin. Fields are read by name; a missing field raises."""
    with zipfile.ZipFile(zip_path) as z:
        csv_members = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise SourceError(f"{zip_path.name}: expected one CSV member, found {csv_members}")
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(z.extract(csv_members[0], tmp))
            header = _header(csv_path)
            if missing := [c for c in REQUIRED if c not in header]:
                raise SourceError(f"{zip_path.name}: missing columns {missing}")
            con = duckdb.connect()
            try:
                con.execute("CREATE TABLE wanted (code VARCHAR)")
                con.executemany("INSERT INTO wanted VALUES (?)", [(a,) for a in sorted(airports)])
                rows = con.execute(
                    f"""
                    SELECT Origin, CAST(Year AS INTEGER), CAST(Month AS INTEGER), COUNT(*),
                           SUM(CASE WHEN TRY_CAST(Cancelled AS DOUBLE) >= 1 THEN 1 ELSE 0 END),
                           SUM(CASE WHEN TRY_CAST(Cancelled AS DOUBLE) < 1 AND TRY_CAST(DepDel15 AS DOUBLE) >= 1 THEN 1 ELSE 0 END),
                           AVG(CASE WHEN TRY_CAST(Cancelled AS DOUBLE) < 1 THEN TRY_CAST(TaxiOut AS DOUBLE) END),
                           QUANTILE_CONT(CASE WHEN TRY_CAST(Cancelled AS DOUBLE) < 1 THEN TRY_CAST(TaxiOut AS DOUBLE) END, 0.1),
                           SUM(CASE WHEN TRY_CAST(Cancelled AS DOUBLE) < 1 AND TRY_CAST(Distance AS DOUBLE) >= {int(long_haul_miles)} THEN 1 ELSE 0 END)
                    FROM read_csv(?, header=true, all_varchar=true, ignore_errors=true)
                    WHERE Origin IN (SELECT code FROM wanted)
                    GROUP BY Origin, Year, Month ORDER BY Origin
                    """,
                    [str(csv_path)],
                ).fetchall()
            finally:
                con.close()
    return [
        OnTimeMonth(
            airport=r[0], year=r[1], month=r[2], departures=int(r[3]), cancelled=int(r[4] or 0), delayed15=int(r[5] or 0),
            taxi_out_mean=float(r[6]) if r[6] is not None else None, taxi_out_p10=float(r[7]) if r[7] is not None else None,
            long_haul_departures=int(r[8] or 0),
        )
        for r in rows
    ]
