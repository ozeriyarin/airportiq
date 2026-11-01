"""OurAirports CSVs: identifiers and coordinates (airports.csv) and the runway inventory (runways.csv)."""

from __future__ import annotations

import csv
import io

from pydantic import BaseModel

from app.data.errors import SourceError

AIRPORT_COLUMNS = ("id", "ident", "type", "name", "latitude_deg", "longitude_deg", "iso_country", "iso_region", "municipality", "icao_code", "iata_code", "local_code")
RUNWAY_COLUMNS = ("airport_ref", "airport_ident", "length_ft", "surface", "closed", "le_ident")
MIN_RUNWAY_FT = 3000  # below this a strip is not an air-carrier runway (helipads are 'H1' and ~100 ft)
AIR_CARRIER_FT = 6000


class OaAirport(BaseModel):
    ref: int
    ident: str
    name: str
    lat: float
    lon: float
    state: str  # from iso_region US-XX
    municipality: str
    icao: str
    iata: str
    local_code: str
    kind: str


class Runways(BaseModel):
    runways: int = 0  # open, at least MIN_RUNWAY_FT
    runways_6000ft: int = 0
    longest_ft: int = 0


def _reader(data: bytes, required: tuple[str, ...], label: str) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    header = reader.fieldnames or []
    if missing := [c for c in required if c not in header]:
        raise SourceError(f"OurAirports {label}: missing columns {missing}; header was {header}")
    return reader


def read_airports(data: bytes) -> list[OaAirport]:
    out: list[OaAirport] = []
    for r in _reader(data, AIRPORT_COLUMNS, "airports.csv"):
        if r["iso_country"] != "US" or r["type"] not in ("large_airport", "medium_airport", "small_airport"):
            continue
        out.append(OaAirport(
            ref=int(r["id"]), ident=r["ident"], name=r["name"], lat=float(r["latitude_deg"]), lon=float(r["longitude_deg"]),
            state=r["iso_region"].split("-", 1)[-1], municipality=r["municipality"], icao=r["icao_code"], iata=r["iata_code"],
            local_code=r["local_code"], kind=r["type"],
        ))
    return out


def read_runways(data: bytes) -> dict[int, Runways]:
    """Runway counts per OurAirports airport ref. Closed runways and strips under MIN_RUNWAY_FT never count."""
    out: dict[int, Runways] = {}
    for r in _reader(data, RUNWAY_COLUMNS, "runways.csv"):
        if r["closed"] == "1" or not r["length_ft"]:
            continue
        length = int(float(r["length_ft"]))
        if length < MIN_RUNWAY_FT:
            continue
        rw = out.setdefault(int(r["airport_ref"]), Runways())
        rw.runways += 1
        rw.runways_6000ft += int(length >= AIR_CARRIER_FT)
        rw.longest_ft = max(rw.longest_ft, length)
    return out
