"""Snapshot writer: typed rows → Parquet files + manifest.json under data/snapshots (committed)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
from pydantic import BaseModel, Field

from app.data.ontime import OnTimeMonth
from app.data.t100 import T100Row
from app.data.taf import TafRow

COVID_YEARS = (2020, 2021)
TAF_FILE, ONTIME_FILE, T100_FILE = "taf.parquet", "ontime_monthly.parquet", "t100_annual.parquet"
SCHEMAS = {
    TAF_FILE: (
        "airport VARCHAR, fiscal_year INTEGER, actual BOOLEAN, ops_air_carrier BIGINT, ops_commuter BIGINT, ops_ga BIGINT, "
        "ops_military BIGINT, enp_air_carrier BIGINT, enp_commuter BIGINT, enp_intl_us_flag BIGINT, enp_intl_foreign_flag BIGINT"
    ),
    ONTIME_FILE: (
        "airport VARCHAR, year INTEGER, month INTEGER, departures BIGINT, cancelled BIGINT, delayed15 BIGINT, "
        "taxi_out_mean DOUBLE, taxi_out_p10 DOUBLE, long_haul_departures BIGINT"
    ),
    T100_FILE: "airport VARCHAR, year INTEGER, international BOOLEAN, long_haul BOOLEAN, cargo BOOLEAN, departures BIGINT, seats BIGINT, passengers BIGINT",
}


class SourceManifest(BaseModel):
    method: str  # "http GET <url>" or "manual TranStats download"
    fetched_at: str
    period: str  # e.g. "FY1990-FY2055" or "2023-01..2025-12"
    rows: int
    files: list[str] = Field(default_factory=list)
    note: str = ""


class Manifest(BaseModel):
    version: str
    written_at: str
    registry_version: str
    airports: int
    long_haul_miles: int
    covid_years: list[int] = Field(default_factory=lambda: list(COVID_YEARS))
    sources: dict[str, SourceManifest]


def _write(con: duckdb.DuckDBPyConnection, name: str, rows: Sequence[BaseModel], out_dir: Path) -> None:
    con.execute(f"CREATE OR REPLACE TABLE t ({SCHEMAS[name]})")
    if rows:
        fields = list(type(rows[0]).model_fields)
        con.executemany(f"INSERT INTO t VALUES ({', '.join('?' for _ in fields)})", [tuple(getattr(r, f) for f in fields) for r in rows])
    tmp = out_dir / f"{name}.tmp"
    con.execute(f"COPY t TO '{tmp.as_posix()}' (FORMAT PARQUET)")
    tmp.replace(out_dir / name)


def write_snapshot(
    out_dir: Path, manifest: Manifest, *, taf: Sequence[TafRow] | None = None, ontime: Sequence[OnTimeMonth] | None = None,
    t100: Sequence[T100Row] | None = None,
) -> None:
    """Write the given tables (others are left as they are) and the manifest. Each file replace is atomic."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        if taf is not None:
            _write(con, TAF_FILE, taf, out_dir)
        if ontime is not None:
            _write(con, ONTIME_FILE, ontime, out_dir)
        if t100 is not None:
            _write(con, T100_FILE, t100, out_dir)
    finally:
        con.close()
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def read_manifest(out_dir: Path) -> Manifest | None:
    p = out_dir / "manifest.json"
    return Manifest.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None
