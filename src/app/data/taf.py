"""FAA Terminal Area Forecast reader: the airports table (universe, hub size, annual service volume) and the
operations and enplanements sheets (scenario 0 = actual fiscal years, scenario 1 = forecast)."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import openpyxl
from pydantic import BaseModel

from app.data.errors import SourceError

AIRPORT_COLUMNS = ("LOCID", "REGION", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE", "SER_VOL", "HUB_SIZE")
OPS_COLUMNS = ("locid", "scenario", "ayear", "itn_Ac", "itn_at", "itn_ga", "itn_mil", "loc_ga", "loc_mil")
ENP_COLUMNS = ("locid", "scenario", "ayear", "aac", "aat", "commuter", "us_flag", "frgn_flag")
HUB_SIZE = {3: "L", 2: "M", 1: "S", 0: "N"}
ACTUAL, FORECAST = 0, 1
DMS = re.compile(r"^(\d+)-(\d+)-(\d+(?:\.\d+)?)([NSEW])$")


class TafAirport(BaseModel):
    locid: str
    faa_region: str
    name: str
    city: str
    state: str
    lat: float
    lon: float
    hub_class: str  # L | M | S | N
    service_volume: int  # FAA annual service volume (operations per year); 0 when the FAA gives none


class TafRow(BaseModel):
    """One airport and fiscal year. Operations exclude overflights; enplanements include the international split."""

    airport: str
    fiscal_year: int
    actual: bool
    ops_air_carrier: int = 0
    ops_commuter: int = 0  # air taxi / commuter itinerant
    ops_ga: int = 0  # itinerant + local general aviation
    ops_military: int = 0  # itinerant + local military
    enp_air_carrier: int = 0
    enp_commuter: int = 0  # air taxi + commuter
    enp_intl_us_flag: int = 0
    enp_intl_foreign_flag: int = 0

    @property
    def ops_total(self) -> int:
        return self.ops_air_carrier + self.ops_commuter + self.ops_ga + self.ops_military

    @property
    def enplanements(self) -> int:
        return self.enp_air_carrier + self.enp_commuter + self.enp_intl_us_flag + self.enp_intl_foreign_flag

    @property
    def enp_international(self) -> int:
        return self.enp_intl_us_flag + self.enp_intl_foreign_flag


def dms_to_decimal(text: str) -> float:
    m = DMS.match(text.strip())
    if not m:
        raise SourceError(f"TAF coordinate not in DMS form: {text!r}")
    deg, minutes, seconds, hemi = int(m[1]), int(m[2]), float(m[3]), m[4]
    value = deg + minutes / 60 + seconds / 3600
    return -value if hemi in "SW" else value


def _sheet(data: bytes, required: Iterable[str], label: str) -> tuple[dict[str, int], Iterator[tuple]]:
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    if missing := [c for c in required if c not in idx]:
        raise SourceError(f"TAF {label}: missing columns {missing}; header was {header}")
    return idx, rows


def _s(v: object) -> str:
    return str(v).strip() if v is not None else ""


def _i(v: object) -> int:
    return int(v) if v not in (None, "", "NULL") else 0


def read_airports(data: bytes) -> list[TafAirport]:
    idx, rows = _sheet(data, AIRPORT_COLUMNS, "Airports.xlsx")
    out: list[TafAirport] = []
    for r in rows:
        locid = _s(r[idx["LOCID"]])
        if not locid:
            continue
        hub = HUB_SIZE.get(_i(r[idx["HUB_SIZE"]]), "N")
        out.append(TafAirport(
            locid=locid, faa_region=_s(r[idx["REGION"]]), name=" ".join(_s(r[idx["APORT_NAME"]]).split()),
            city=" ".join(_s(r[idx["CITY"]]).title().split()), state=_s(r[idx["STATE"]]),
            lat=dms_to_decimal(_s(r[idx["LATITUDE"]])), lon=dms_to_decimal(_s(r[idx["LONGITUDE"]])),
            hub_class=hub, service_volume=_i(r[idx["SER_VOL"]]),
        ))
    return out


def read_rows(ops_data: bytes, enp_data: bytes, airports: set[str]) -> list[TafRow]:
    """Operations and enplanements joined on (airport, fiscal year) for the given airports."""
    rows: dict[tuple[str, int], TafRow] = {}
    idx, it = _sheet(ops_data, OPS_COLUMNS, "AirportsOperations.xlsx")
    for r in it:
        loc = _s(r[idx["locid"]])
        if loc not in airports:
            continue
        year, scenario = _i(r[idx["ayear"]]), _i(r[idx["scenario"]])
        rows[(loc, year)] = TafRow(
            airport=loc, fiscal_year=year, actual=scenario == ACTUAL,
            ops_air_carrier=_i(r[idx["itn_Ac"]]), ops_commuter=_i(r[idx["itn_at"]]),
            ops_ga=_i(r[idx["itn_ga"]]) + _i(r[idx["loc_ga"]]), ops_military=_i(r[idx["itn_mil"]]) + _i(r[idx["loc_mil"]]),
        )
    idx, it = _sheet(enp_data, ENP_COLUMNS, "Enplanements.xlsx")
    for r in it:
        loc = _s(r[idx["locid"]])
        if loc not in airports:
            continue
        year, scenario = _i(r[idx["ayear"]]), _i(r[idx["scenario"]])
        row = rows.get((loc, year)) or TafRow(airport=loc, fiscal_year=year, actual=scenario == ACTUAL)
        row.enp_air_carrier, row.enp_commuter = _i(r[idx["aac"]]), _i(r[idx["aat"]]) + _i(r[idx["commuter"]])
        row.enp_intl_us_flag, row.enp_intl_foreign_flag = _i(r[idx["us_flag"]]), _i(r[idx["frgn_flag"]])
        rows[(loc, year)] = row
    return sorted(rows.values(), key=lambda x: (x.airport, x.fiscal_year))


class TafArchive:
    """The TAF zip: `APO100_TAF_Final_<year>.zip` with Airports, AirportsOperations and Enplanements sheets."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _member(self, name: str) -> bytes:
        with zipfile.ZipFile(self.path) as z:
            if name not in z.namelist():
                raise SourceError(f"TAF zip {self.path.name} lacks {name}; members {z.namelist()}")
            return z.read(name)

    def airports(self) -> list[TafAirport]:
        return read_airports(self._member("Airports.xlsx"))

    def rows(self, airports: set[str]) -> list[TafRow]:
        return read_rows(self._member("AirportsOperations.xlsx"), self._member("Enplanements.xlsx"), airports)
