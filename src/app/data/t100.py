"""BTS T-100 Segment (All Carriers), downloaded once by hand from TranStats into data/raw/t100/*.csv and aggregated
into one row per origin, year, international flag, long-haul flag and cargo flag: departures, seats, passengers."""

from __future__ import annotations

from pathlib import Path

import duckdb
from pydantic import BaseModel

from app.data.errors import SourceError

REQUIRED = ("YEAR", "ORIGIN", "DEST_COUNTRY", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "DISTANCE", "CLASS")
PASSENGER_CLASS = "F"  # scheduled passenger service; G/L/P are cargo and non-scheduled


class T100Row(BaseModel):
    airport: str
    year: int
    international: bool
    long_haul: bool
    cargo: bool  # service class other than scheduled passenger (freight, non-scheduled)
    departures: int
    seats: int
    passengers: int


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", errors="replace") as f:
        return [c.strip().strip('"').upper() for c in f.readline().strip().split(",")]


def aggregate(csv_paths: list[Path], airports: set[str], long_haul_miles: int) -> list[T100Row]:
    if not csv_paths:
        raise SourceError("no T-100 CSV files found; download T-100 Segment (All Carriers) from TranStats into data/raw/t100/")
    for p in csv_paths:
        if missing := [c for c in REQUIRED if c not in _header(p)]:
            raise SourceError(f"{p.name}: missing T-100 columns {missing}")
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE wanted (code VARCHAR)")
        con.executemany("INSERT INTO wanted VALUES (?)", [(a,) for a in sorted(airports)])
        rows = con.execute(
            f"""
            SELECT ORIGIN, CAST(YEAR AS INTEGER), DEST_COUNTRY <> 'US', TRY_CAST(DISTANCE AS DOUBLE) >= {int(long_haul_miles)},
                   CLASS <> '{PASSENGER_CLASS}',
                   SUM(TRY_CAST(DEPARTURES_PERFORMED AS DOUBLE)), SUM(TRY_CAST(SEATS AS DOUBLE)), SUM(TRY_CAST(PASSENGERS AS DOUBLE))
            FROM read_csv(?, header=true, all_varchar=true, ignore_errors=true, union_by_name=true, normalize_names=false)
            WHERE ORIGIN IN (SELECT code FROM wanted) AND TRY_CAST(DEPARTURES_PERFORMED AS DOUBLE) > 0
            GROUP BY ALL ORDER BY ORIGIN, 2, 3, 4, 5
            """,
            [[str(p) for p in csv_paths]],
        ).fetchall()
    finally:
        con.close()
    return [
        T100Row(airport=r[0], year=r[1], international=bool(r[2]), long_haul=bool(r[3]), cargo=bool(r[4]),
                departures=int(r[5] or 0), seats=int(r[6] or 0), passengers=int(r[7] or 0))
        for r in rows
    ]
