"""US Census regions and divisions by state, plus analyst area aliases, from config/areas.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import CONFIG_DIR

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
    "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
    "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}
TERRITORIES = {"PR", "VI", "GU", "AS", "MP"}


class Division(BaseModel):
    region: str
    states: list[str] = Field(min_length=1)


class Areas(BaseModel):
    version: str
    divisions: dict[str, Division]
    areas: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _complete_and_known(self) -> Areas:
        seen: dict[str, str] = {}
        for name, d in self.divisions.items():
            for s in d.states:
                if s not in US_STATES:
                    raise ValueError(f"division {name}: unknown state {s}")
                if s in seen:
                    raise ValueError(f"state {s} in two divisions: {seen[s]} and {name}")
                seen[s] = name
        if missing := US_STATES - set(seen):
            raise ValueError(f"states without a division: {sorted(missing)}")
        for name, states in self.areas.items():
            if unknown := set(states) - US_STATES:
                raise ValueError(f"area {name}: unknown states {sorted(unknown)}")
        return self

    def division_of(self, state: str) -> str | None:
        for name, d in self.divisions.items():
            if state in d.states:
                return name
        return None

    def region_of(self, state: str) -> str | None:
        name = self.division_of(state)
        return self.divisions[name].region if name else None

    def regions(self) -> list[str]:
        return sorted({d.region for d in self.divisions.values()})

    def states_in(self, area: str) -> list[str] | None:
        """States for a region, division, area alias or state code (case-insensitive); None when unknown."""
        key = area.strip().lower()
        if key.upper() in US_STATES | TERRITORIES:
            return [key.upper()]
        for name, d in self.divisions.items():
            if name.lower() == key:
                return list(d.states)
        if key in {r.lower() for r in self.regions()}:
            return sorted(s for d in self.divisions.values() if d.region.lower() == key for s in d.states)
        for name, states in self.areas.items():
            if name.lower() == key:
                return list(states)
        return None

    def names(self) -> list[str]:
        return self.regions() + list(self.divisions) + list(self.areas)


def load_areas(path: Path = CONFIG_DIR / "areas.yaml") -> Areas:
    return Areas.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
