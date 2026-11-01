"""Read-only DuckDB store over the committed Parquet snapshots. One connection, per-call cursors."""

from __future__ import annotations

from pathlib import Path

import duckdb
from pydantic import BaseModel

from app.data.ontime import OnTimeMonth
from app.data.snapshot import ONTIME_FILE, T100_FILE, TAF_FILE, Manifest, read_manifest
from app.data.t100 import T100Row
from app.data.taf import TafRow


class Coverage(BaseModel):
    source: str
    first: str
    last: str
    rows: int
    airports: int


class Store:
    def __init__(self, snapshot_dir: Path, manifest: Manifest) -> None:
        self.dir, self.manifest = snapshot_dir, manifest
        self._con = duckdb.connect()
        for view, name in (("taf", TAF_FILE), ("ontime", ONTIME_FILE), ("t100", T100_FILE)):
            path = snapshot_dir / name
            if path.exists():
                self._con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{path.as_posix()}')")
        self.tables = [v for v in ("taf", "ontime", "t100") if (snapshot_dir / {"taf": TAF_FILE, "ontime": ONTIME_FILE, "t100": T100_FILE}[v]).exists()]

    @classmethod
    def open_if_present(cls, snapshot_dir: Path) -> Store | None:
        manifest = read_manifest(snapshot_dir)
        return cls(snapshot_dir, manifest) if manifest else None

    def _q(self, sql: str, params: list | None = None) -> list[tuple]:
        return self._con.cursor().execute(sql, params or []).fetchall()

    def taf(self, airport: str, years: tuple[int, int] | None = None) -> list[TafRow]:
        sql, params = "SELECT * FROM taf WHERE airport = ?", [airport]
        if years:
            sql, params = sql + " AND fiscal_year BETWEEN ? AND ?", params + [years[0], years[1]]
        cols = list(TafRow.model_fields)
        return [TafRow(**dict(zip(cols, r, strict=True))) for r in self._q(sql + " ORDER BY fiscal_year", params)]

    def ontime(self, airport: str, years: tuple[int, int] | None = None) -> list[OnTimeMonth]:
        if "ontime" not in self.tables:
            return []
        sql, params = "SELECT * FROM ontime WHERE airport = ?", [airport]
        if years:
            sql, params = sql + " AND year BETWEEN ? AND ?", params + [years[0], years[1]]
        cols = list(OnTimeMonth.model_fields)
        return [OnTimeMonth(**dict(zip(cols, r, strict=True))) for r in self._q(sql + " ORDER BY year, month", params)]

    def t100(self, airport: str, years: tuple[int, int] | None = None) -> list[T100Row]:
        if "t100" not in self.tables:
            return []
        sql, params = "SELECT * FROM t100 WHERE airport = ?", [airport]
        if years:
            sql, params = sql + " AND year BETWEEN ? AND ?", params + [years[0], years[1]]
        cols = list(T100Row.model_fields)
        return [T100Row(**dict(zip(cols, r, strict=True))) for r in self._q(sql + " ORDER BY year", params)]

    def years(self, source: str) -> list[int]:
        if source not in self.tables:
            return []
        col = "fiscal_year" if source == "taf" else "year"
        extra = " WHERE actual" if source == "taf" else ""
        return [int(r[0]) for r in self._q(f"SELECT DISTINCT {col} FROM {source}{extra} ORDER BY 1")]

    def coverage(self) -> list[Coverage]:
        out: list[Coverage] = []
        for source in self.tables:
            if source == "taf":
                sql = "SELECT MIN(fiscal_year), MAX(fiscal_year), COUNT(*), COUNT(DISTINCT airport) FROM taf"
            elif source == "ontime":
                sql = "SELECT MIN(year*100+month), MAX(year*100+month), COUNT(*), COUNT(DISTINCT airport) FROM ontime"
            else:
                sql = "SELECT MIN(year), MAX(year), COUNT(*), COUNT(DISTINCT airport) FROM t100"
            first, last, rows, airports = self._q(sql)[0]
            out.append(Coverage(source=source, first=str(first), last=str(last), rows=int(rows), airports=int(airports)))
        return out

    def summary(self) -> dict:
        return {
            "airports": self.manifest.airports, "written_at": self.manifest.written_at, "registry_version": self.manifest.registry_version,
            "sources": {c.source: {"first": c.first, "last": c.last, "rows": c.rows, "airports": c.airports} for c in self.coverage()},
        }
