"""Acceptance criteria of agent-os/specs/2026-11-01-v6-opensky, one test per criterion, all offline (MockTransport)."""

from __future__ import annotations

import json

import httpx2
import pytest
import yaml

from app.agent import prompts
from app.agent.tools import Ambiguous, NotFound, ToolContext, Unavailable, build_toolset
from app.config import ROOT, Settings
from app.data.opensky import AircraftNow, OpenSkyClient, bounding_box, count_states
from app.data.registry import AirportRegistry

STATES = {"time": 1793500000, "states": [
    ["a1", "UAL60  ", "United States", 1, 1, -122.4, 37.6, 1000.0, False, 200.0, 90.0, 0.0, None, 1100.0, None, False, 0, 3],
    ["a2", "ACA570 ", "Canada", 1, 1, -122.39, 37.61, None, True, 5.0, 0.0, 0.0, None, None, None, False, 0, 3],
    ["a3", "", "United States", 1, 1, -122.38, 37.62, 500.0, False, 150.0, 90.0, 0.0, None, 600.0, None, False, 0, 3],
]}


def _transport(log: list, *, token_status=200, states_status=200, first_401=False, credits="398"):
    calls = {"states": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append((request.method, request.url.path, request.headers.get("Authorization", ""), dict(request.url.params)))
        if request.url.path.endswith("/token"):
            body = request.content.decode()
            assert "grant_type=client_credentials" in body and "client_id=cid" in body
            return httpx2.Response(token_status, json={"access_token": f"tok{len(log)}", "expires_in": 1800})
        calls["states"] += 1
        if first_401 and calls["states"] == 1:
            return httpx2.Response(401, json={})
        if states_status == 429:
            return httpx2.Response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "3600", "X-Rate-Limit-Remaining": "0"})
        if states_status != 200:
            return httpx2.Response(states_status, text="boom")
        return httpx2.Response(200, json=STATES, headers={"X-Rate-Limit-Remaining": credits})

    return httpx2.MockTransport(handler)


def _client(log, **kw) -> OpenSkyClient:
    clock = kw.pop("clock", [0.0])
    creds = kw.pop("creds", True)
    http = httpx2.AsyncClient(transport=_transport(log, **kw))
    return OpenSkyClient(http, "cid" if creds else None, "sec" if creds else None, now=lambda: clock[0])


async def test_criterion_1_optional_credentials_anonymous_or_client(monkeypatch):
    for key in ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"):  # a prior compose() may have loaded .env
        monkeypatch.delenv(key, raising=False)
    assert Settings(_env_file=None).opensky_client_id is None
    masked = repr(Settings(_env_file=None, anthropic_api_key="value-one", opensky_client_secret="value-two"))  # SecretStr never shows
    assert "value-one" not in masked and "value-two" not in masked and "**********" in masked
    log: list = []
    anon = _client(log, creds=False)
    r = await anon.aircraft_near("SFO", 37.62, -122.38)
    assert r.available and r.auth == "anonymous" and not anon.configured and all(a == "" for _, _, a, _ in log)
    log.clear()
    client = _client(log)
    r = await client.aircraft_near("SFO", 37.62, -122.38)
    assert r.available and r.auth == "client" and client.configured
    assert log[0][1].endswith("/token") and log[1][2] == "Bearer tok1"


async def test_criterion_2_token_cached_refetched_on_401_and_degrades():
    log: list = []
    clock = [0.0]
    client = _client(log, clock=clock)
    await client.aircraft_near("SFO", 37.62, -122.38)
    clock[0] = 200
    await client.aircraft_near("BOS", 42.36, -71.0)
    assert sum(1 for _, p, _, _ in log if p.endswith("/token")) == 1  # cached
    clock[0] = 1800
    await client.aircraft_near("LAX", 33.94, -118.4)
    assert sum(1 for _, p, _, _ in log if p.endswith("/token")) == 2  # expired, re-fetched
    log.clear()
    retry = _client(log, first_401=True)
    r = await retry.aircraft_near("SFO", 37.62, -122.38)
    assert r.available and [p for _, p, _, _ in log].count("/api/states/all") == 2 and sum(1 for _, p, _, _ in log if p.endswith("/token")) == 2
    log.clear()
    broken = _client(log, token_status=500)
    r = await broken.aircraft_near("SFO", 37.62, -122.38)
    assert r.available and r.auth == "anonymous" and "token exchange returned 500" in r.note


async def test_criterion_3_bounding_box_and_counts():
    box = bounding_box(37.62, -122.38, 25)
    assert box["lamax"] - box["lamin"] == pytest.approx(2 * 25 / 111, abs=1e-3) and box["lomax"] - box["lomin"] > box["lamax"] - box["lamin"]
    assert count_states(STATES) == (3, 2, 1, ["UAL60", "ACA570"]) and count_states({}) == (0, 0, 0, [])
    log: list = []
    r = await _client(log).aircraft_near("SFO", 37.62, -122.38)
    params = log[-1][3]
    assert set(params) == {"lamin", "lamax", "lomin", "lomax"} and float(params["lamin"]) < 37.62 < float(params["lamax"])
    assert (r.total, r.airborne, r.on_ground, r.callsigns, r.credits_remaining, r.time) == (3, 2, 1, ["UAL60", "ACA570"], 398, 1793500000)


async def test_criterion_4_cache_quota_and_failures_never_raise():
    log: list = []
    clock = [0.0]
    client = _client(log, clock=clock)
    await client.aircraft_near("SFO", 37.62, -122.38)
    await client.aircraft_near("SFO", 37.62, -122.38)
    assert [p for _, p, _, _ in log].count("/api/states/all") == 1
    clock[0] = 121
    await client.aircraft_near("SFO", 37.62, -122.38)
    assert [p for _, p, _, _ in log].count("/api/states/all") == 2
    quota = await _client([], states_status=429).aircraft_near("SFO", 37.62, -122.38)
    assert not quota.available and "quota" in quota.reason and "3600" in quota.reason and quota.credits_remaining == 0
    down = await _client([], states_status=503).aircraft_near("SFO", 37.62, -122.38)
    assert not down.available and "503" in down.reason
    dead = OpenSkyClient(httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: (_ for _ in ()).throw(httpx2.ConnectError("x")))), None, None)
    r = await dead.aircraft_near("SFO", 37.62, -122.38)
    assert not r.available and "ConnectError" in r.reason
    log.clear()
    failed = _client(log, clock=clock, states_status=503)
    await failed.aircraft_near("BOS", 42.36, -71.0)
    clock[0] += 30
    await failed.aircraft_near("BOS", 42.36, -71.0)
    assert [p for _, p, _, _ in log].count("/api/states/all") == 1  # failures cached one minute


async def test_criterion_5_tool_registered_resolves_names_and_prompt_lists_it():
    from pydantic_ai import RunContext

    from app.agent.tools import aircraft_now

    names = set(build_toolset().tools)
    assert "aircraft_now" in names and "- aircraft_now:" in prompts.TOOL_GUIDE and prompts.PROMPT_VERSION == "0.4.0"
    deps = ToolContext(product_name="t", registry=AirportRegistry.load(), opensky=_client([]))
    assert "OpenSky" in deps.data_facts or deps.engine is None
    ctx = RunContext(deps=deps, model=None, usage=None)  # type: ignore[arg-type]
    assert isinstance(await aircraft_now(ctx, "Atlantis"), NotFound)
    assert isinstance(await aircraft_now(ctx, "portland"), Ambiguous)
    assert isinstance(await aircraft_now(ctx, "SFO"), AircraftNow)
    assert isinstance(await aircraft_now(RunContext(deps=ToolContext(product_name="t", registry=deps.registry), model=None, usage=None), "SFO"), Unavailable)  # type: ignore[arg-type]


def test_criterion_6_smoke_case_render_env_and_docs():
    smoke = yaml.safe_load((ROOT / "evals" / "smoke.yaml").read_text(encoding="utf-8"))["cases"]
    assert any(c.get("tools") == ["aircraft_now"] for c in smoke)
    render = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"][0]
    assert {e["key"] for e in render["envVars"] if e.get("sync") is False} >= {"OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"}
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "OPENSKY_CLIENT_ID=" in env and "OPENSKY_CLIENT_SECRET=" in env
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    assert "OpenSky" in readme and "aircraft_now" in readme and "OpenSky" in design and "never blended" in design
    assert json.dumps(AircraftNow(airport="SFO", available=False, radius_km=25).model_dump())  # serializable for the model
