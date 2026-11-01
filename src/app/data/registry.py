"""Airport registry: generated from the FAA TAF airport table, FAA enplanements and OurAirports, committed as
config/airports.yaml. Filters and name resolution read this file; the model never decides geography."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import CONFIG_DIR
from app.data.areas import TERRITORIES, US_STATES, Areas
from app.data.enplanements import EnplanementRow
from app.data.ourairports import OaAirport, Runways
from app.data.taf import TafAirport

HUB_CLASSES = ("L", "M", "S")
TERRITORY_AREA = "Territories"


class Airport(BaseModel):
    id: str  # FAA LID, also the TAF locid
    iata: str
    icao: str
    name: str
    city: str
    state: str
    region: str
    division: str
    hub_class: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    service_volume: int = Field(ge=0, description="FAA annual service volume, operations per year; 0 = not given")
    enplanements_latest_year: int
    enplanements_latest: int = Field(ge=0)
    enplanements_previous: int = Field(ge=0)
    runways: int = Field(ge=0)
    runways_6000ft: int = Field(ge=0)
    longest_runway_ft: int = Field(ge=0)
    aliases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> Airport:
        if self.hub_class not in HUB_CLASSES:
            raise ValueError(f"{self.id}: hub class {self.hub_class!r} not in {HUB_CLASSES}")
        if self.state not in US_STATES | TERRITORIES:
            raise ValueError(f"{self.id}: unknown state {self.state!r}")
        return self

    def search_terms(self) -> set[str]:
        terms = {self.id, self.iata, self.icao, self.name, self.city, f"{self.city} {self.state}", *self.aliases}
        return {t.lower() for t in terms if t}


class RegistryFile(BaseModel):
    version: str
    generated: str
    sources: dict[str, str]
    airports: list[Airport] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> RegistryFile:
        ids = [a.id for a in self.airports]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate airport ids")
        return self


class AirportRegistry:
    def __init__(self, data: RegistryFile, areas: Areas) -> None:
        self._data, self._areas = data, areas
        self.all = sorted(data.airports, key=lambda a: a.id)
        self._by_id = {a.id: a for a in self.all}
        self._terms: dict[str, list[Airport]] = {}
        for a in self.all:
            for t in a.search_terms():
                self._terms.setdefault(t, []).append(a)

    @classmethod
    def load(cls, path: Path = CONFIG_DIR / "airports.yaml", areas: Areas | None = None) -> AirportRegistry:
        from app.data.areas import load_areas

        data = RegistryFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        return cls(data, areas or load_areas())

    @property
    def version(self) -> str:
        return self._data.version

    @property
    def areas(self) -> Areas:
        return self._areas

    def by_id(self, airport_id: str) -> Airport | None:
        return self._by_id.get(airport_id.upper())

    def find(self, query: str) -> Airport | list[Airport] | None:
        """One airport for an id, IATA, ICAO, city, name or alias; a list when ambiguous; None when unknown."""
        key = re.sub(r"\s+", " ", query.strip().lower().replace("airport", "")).strip()
        if not key:
            return None
        if hit := self._by_id.get(key.upper()):
            return hit
        if exact := self._terms.get(key):
            return exact[0] if len(exact) == 1 else exact
        partial = [a for a in self.all if any(key in t or t in key for t in a.search_terms() if len(t) > 3)]
        if len(partial) == 1:
            return partial[0]
        return partial or None

    def in_area(self, area: str) -> list[Airport] | None:
        """Airports in a region, division, area alias or state; None when the area is unknown."""
        if area.strip().lower() == TERRITORY_AREA.lower():
            return [a for a in self.all if a.state in TERRITORIES]
        states = self._areas.states_in(area)
        if states is None:
            return None
        wanted = set(states)
        return [a for a in self.all if a.state in wanted]

    def in_region(self, region: str) -> list[Airport]:
        return [a for a in self.all if a.region.lower() == region.strip().lower()]

    def in_division(self, division: str) -> list[Airport]:
        return [a for a in self.all if a.division.lower() == division.strip().lower()]

    def in_state(self, state: str) -> list[Airport]:
        return [a for a in self.all if a.state == state.strip().upper()]

    def area_names(self) -> list[str]:
        return self._areas.names() + [TERRITORY_AREA]


def build_registry(
    taf: list[TafAirport], enplanements: list[EnplanementRow], oa_airports: list[OaAirport], runways: dict[int, Runways],
    areas: Areas, aliases: dict[str, list[str]], *, generated: str, sources: dict[str, str], version: str = "1.0.0",
) -> RegistryFile:
    """Pure join: TAF defines the universe (hub classes L/M/S) and capacity; FAA enplanements add boardings;
    OurAirports adds ICAO, decimal coordinates and runways. Hub class comes from the FAA enplanement file when it
    lists the airport (calendar-year classification), else from the TAF."""
    enp_by_id = {e.locid: e for e in enplanements}
    oa_by_code: dict[str, OaAirport] = {}
    for a in oa_airports:  # local_code is the FAA LID; iata and the K-prefixed ICAO are fallbacks
        for code in (a.local_code, a.iata):
            if code:
                oa_by_code.setdefault(code, a)
    out: list[Airport] = []
    for t in taf:
        enp = enp_by_id.get(t.locid)
        hub = enp.hub_class if enp and enp.hub_class in HUB_CLASSES else t.hub_class
        if hub not in HUB_CLASSES:
            continue
        oa = oa_by_code.get(t.locid) or oa_by_code.get(f"K{t.locid}")
        rw = runways.get(oa.ref, Runways()) if oa else Runways()
        state = t.state
        if state in TERRITORIES:
            region = division = TERRITORY_AREA
        else:
            region, division = areas.region_of(state), areas.division_of(state)
            if region is None or division is None:
                continue
        out.append(Airport(
            id=t.locid, iata=(oa.iata if oa and oa.iata else t.locid), icao=(oa.icao if oa and oa.icao else ""),
            name=(enp.name if enp and enp.name else t.name), city=t.city, state=state,  # FAA file swaps city/name rows
            region=region, division=division, hub_class=hub, lat=oa.lat if oa else t.lat, lon=oa.lon if oa else t.lon,
            service_volume=t.service_volume, enplanements_latest_year=enp.latest_year if enp else 0,
            enplanements_latest=enp.latest if enp else 0, enplanements_previous=enp.previous if enp else 0,
            runways=rw.runways, runways_6000ft=rw.runways_6000ft, longest_runway_ft=rw.longest_ft,
            aliases=sorted(aliases.get(t.locid, [])),
        ))
    return RegistryFile(version=version, generated=generated, sources=sources, airports=sorted(out, key=lambda a: a.id))


def load_aliases(path: Path = CONFIG_DIR / "aliases.yaml") -> dict[str, list[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: [str(v).lower() for v in vals] for k, vals in (raw.get("aliases") or {}).items()}


def dump_registry(data: RegistryFile, path: Path = CONFIG_DIR / "airports.yaml") -> None:
    head = (
        "# GENERATED by `agent registry` from the FAA TAF airport table, the FAA CY enplanement file and OurAirports.\n"
        "# Universe: FAA large, medium and small hub airports. Edit config/aliases.yaml, not this file.\n"
    )
    path.write_text(head + yaml.safe_dump(data.model_dump(), sort_keys=False, allow_unicode=True, width=120), encoding="utf-8", newline="\n")
