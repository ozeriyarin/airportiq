"""OpenSky Network: aircraft currently around an airport (state vectors in a bounding box). A registered client
exchanges OAuth2 client credentials for a bearer token; without credentials the query runs anonymously. Cached
per airport; every failure degrades to available=False with a reason, never an exception."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2
from pydantic import BaseModel, Field

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"
KM_PER_DEGREE = 111.0


class AircraftNow(BaseModel):
    airport: str
    available: bool
    time: int | None = Field(default=None, description="OpenSky snapshot time, Unix seconds")
    radius_km: float
    total: int = 0
    airborne: int = 0
    on_ground: int = 0
    callsigns: list[str] = Field(default_factory=list, description="up to five callsigns in the box")
    credits_remaining: int | None = Field(default=None, description="OpenSky daily credits left, when the API reports them")
    auth: str = "anonymous"  # client | anonymous
    reason: str | None = None
    note: str = "live OpenSky state vectors in a box around the airport; a snapshot, reported beside the frozen score, never blended into it"


def bounding_box(lat: float, lon: float, radius_km: float) -> dict[str, float]:
    dlat = radius_km / KM_PER_DEGREE
    dlon = radius_km / (KM_PER_DEGREE * max(math.cos(math.radians(lat)), 0.1))
    return {"lamin": round(lat - dlat, 4), "lamax": round(lat + dlat, 4), "lomin": round(lon - dlon, 4), "lomax": round(lon + dlon, 4)}


def count_states(payload: dict) -> tuple[int, int, int, list[str]]:
    """OpenSky state vectors: index 1 is the callsign, index 8 the on_ground flag."""
    states = payload.get("states") or []
    on_ground = sum(1 for s in states if len(s) > 8 and s[8] is True)
    callsigns = [s[1].strip() for s in states if len(s) > 1 and isinstance(s[1], str) and s[1].strip()][:5]
    return len(states), len(states) - on_ground, on_ground, callsigns


@dataclass
class _Cached:
    at: float
    result: AircraftNow


@dataclass
class OpenSkyClient:
    http: httpx2.AsyncClient
    client_id: str | None = None
    client_secret: str | None = None
    radius_km: float = 25.0
    cache_min: int = 2
    now: Callable[[], float] = time.monotonic
    token_url: str = TOKEN_URL
    states_url: str = STATES_URL
    _token: str | None = field(default=None, repr=False)
    _token_expires: float = 0.0
    _cache: dict[str, _Cached] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _bearer(self, force: bool = False) -> tuple[str | None, str | None]:
        """A valid token, fetched when missing, expired or forced; (None, reason) when the exchange fails."""
        if not self.configured:
            return None, None
        if self._token and not force and self.now() < self._token_expires:
            return self._token, None
        try:
            r = await self.http.post(self.token_url, data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
            if r.status_code != 200:
                return None, f"token exchange returned {r.status_code}"
            body = r.json()
            self._token = str(body["access_token"])
            self._token_expires = self.now() + float(body.get("expires_in", 1800)) - 60
            return self._token, None
        except (httpx2.HTTPError, KeyError, ValueError) as e:
            return None, f"token exchange failed: {type(e).__name__}"

    async def aircraft_near(self, airport_id: str, lat: float, lon: float) -> AircraftNow:
        cached = self._cache.get(airport_id)
        if cached and self.now() - cached.at < (60 if not cached.result.available else self.cache_min * 60):
            return cached.result
        result = await self._query(airport_id, lat, lon)
        self._cache[airport_id] = _Cached(self.now(), result)
        return result

    async def _query(self, airport_id: str, lat: float, lon: float) -> AircraftNow:
        box = bounding_box(lat, lon, self.radius_km)
        token, token_reason = await self._bearer()
        auth = "client" if token else "anonymous"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = await self.http.get(self.states_url, params=box, headers=headers)
            if r.status_code == 401 and token:
                token, token_reason = await self._bearer(force=True)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                auth = "client" if token else "anonymous"
                r = await self.http.get(self.states_url, params=box, headers=headers)
            credits = r.headers.get("X-Rate-Limit-Remaining")
            remaining = int(credits) if credits and credits.isdigit() else None
            if r.status_code == 429:
                wait = r.headers.get("X-Rate-Limit-Retry-After-Seconds") or r.headers.get("Retry-After")
                return AircraftNow(airport=airport_id, available=False, radius_km=self.radius_km, auth=auth, credits_remaining=remaining,
                                   reason=f"OpenSky quota exhausted ({auth}); retry after {wait or 'unknown'} s")
            if r.status_code != 200:
                return AircraftNow(airport=airport_id, available=False, radius_km=self.radius_km, auth=auth, reason=f"OpenSky returned {r.status_code}")
            payload = r.json()
        except (httpx2.HTTPError, ValueError) as e:
            return AircraftNow(airport=airport_id, available=False, radius_km=self.radius_km, auth=auth, reason=f"OpenSky unavailable: {type(e).__name__}")
        total, airborne, on_ground, callsigns = count_states(payload)
        note = AircraftNow.model_fields["note"].default
        if token_reason:
            note += f"; {token_reason}, ran anonymously"
        return AircraftNow(airport=airport_id, available=True, time=payload.get("time"), radius_km=self.radius_km, total=total, airborne=airborne,
                           on_ground=on_ground, callsigns=callsigns, credits_remaining=remaining, auth=auth, note=note)
