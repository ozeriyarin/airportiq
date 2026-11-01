"""Live FAA NAS status (nasstatus.faa.gov XML): closures, ground stops, ground delay programs and arrival/departure
delays per airport. Cached per feed; a failure degrades to available=False, never raises."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import defusedxml.ElementTree as ET
import httpx2
from pydantic import BaseModel, Field

NAS_URL = "https://nasstatus.faa.gov/api/airport-status-information"


class LiveEvent(BaseModel):
    kind: str  # the feed's Delay_type name, e.g. "Airport Closures", "Ground Stop Programs"
    airport: str
    reason: str = ""
    details: dict[str, str] = Field(default_factory=dict)


class LiveStatus(BaseModel):
    airport: str
    available: bool
    update_time: str | None = None
    events: list[LiveEvent] = Field(default_factory=list)
    reason: str | None = None
    note: str = "live FAA NAS status; reported beside the frozen score, never blended into it"


def parse_feed(xml_text: str) -> tuple[str | None, list[LiveEvent]]:
    """Every <ARPT> inside a Delay_type becomes one event; sibling fields become details."""
    root = ET.fromstring(xml_text)
    update = (root.findtext("Update_Time") or "").strip() or None
    events: list[LiveEvent] = []
    for dt in root.iter("Delay_type"):
        kind = (dt.findtext("Name") or "unknown").strip()
        for node in dt.iter():
            arpt = node.find("ARPT")
            if arpt is None or not (arpt.text or "").strip():
                continue
            details = {c.tag: (c.text or "").strip() for c in node if c.tag != "ARPT" and (c.text or "").strip()}
            events.append(LiveEvent(kind=kind, airport=arpt.text.strip(), reason=details.pop("Reason", ""), details=details))
    return update, events


@dataclass
class _Cached:
    at: float
    update_time: str | None
    events: list[LiveEvent]
    error: str | None


class NasStatusClient:
    def __init__(self, http: httpx2.AsyncClient, user_agent: str, *, cache_min: int = 10, now: Callable[[], float] = time.monotonic, url: str = NAS_URL) -> None:
        self.http, self.user_agent, self.cache_s, self.now, self.url = http, user_agent, cache_min * 60, now, url
        self._cache: _Cached | None = None

    async def _feed(self) -> _Cached:
        if self._cache and self.now() - self._cache.at < (60 if self._cache.error else self.cache_s):
            return self._cache
        try:
            r = await self.http.get(self.url, headers={"User-Agent": self.user_agent, "Accept": "application/xml"})
            r.raise_for_status()
            update, events = parse_feed(r.text)
            self._cache = _Cached(self.now(), update, events, None)
        except (httpx2.HTTPError, ET.ParseError) as e:
            self._cache = _Cached(self.now(), None, [], f"FAA NAS status unavailable: {type(e).__name__}: {str(e)[:120]}")
        return self._cache

    async def status(self, airport: str) -> LiveStatus:
        feed = await self._feed()
        if feed.error:
            return LiveStatus(airport=airport, available=False, reason=feed.error)
        mine = [e for e in feed.events if e.airport.upper() == airport.upper()]
        return LiveStatus(airport=airport, available=True, update_time=feed.update_time, events=mine)
