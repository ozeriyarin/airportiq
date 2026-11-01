# Spec: v6 OpenSky

Status: shaped 1.11.2026 (bonus item; owner asked for it after the structure pass).

## Goal

A second "right now" signal beside the FAA status feed: how many aircraft are currently around an airport, from
the OpenSky Network REST API, with the owner's registered client (OAuth2 client credentials) or anonymously when
no credentials are set. Reported next to the frozen score, never blended into it.

## Scope

**In:** `app/data/opensky.py` (token exchange, bounding-box query, cache, degradation), settings
`OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` (optional), tool `aircraft_now`, prompt tool line, smoke case,
README / DESIGN / roadmap. **Out:** historical flights (login-gated on OpenSky), persistence of counts, any use
of the count inside the score.

## Acceptance criteria

1. The two settings are optional; without them the client calls the API anonymously and says so in its result; with them it exchanges client credentials at OpenSky's token endpoint for a bearer token.
2. The token is cached until shortly before its expiry and re-fetched once on a 401; a failed exchange degrades the query to anonymous with the reason recorded.
3. The query is a bounding box of the configured radius around the airport's coordinates (latitude and longitude spans corrected by latitude); the response's state vectors are counted into total, airborne and on-ground aircraft, with up to five trimmed callsigns; the remaining daily credits are read from the response header when present.
4. Results are cached per airport for the configured minutes (one minute after a failure); a 429 reports the quota and Retry-After, any other failure reports its reason; the client never raises.
5. `aircraft_now` is registered with the other tools, resolves names like the rest (NotFound, Ambiguous, Unavailable), the tool guide lists it, and the data facts name OpenSky among the sources.
6. All of it is proven offline with `MockTransport`; the smoke set asserts the tool; README, DESIGN and roadmap say what the signal is and that it stays outside the score.

## Design

- `OpenSkyClient(http, client_id, client_secret, *, radius_km=25, cache_min=2, now)`; `aircraft_near(airport) ->
  AircraftNow(airport, available, time, radius_km, total, airborne, on_ground, callsigns, credits_remaining,
  auth: "client" | "anonymous", reason, note)`.
- Token endpoint `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`,
  `grant_type=client_credentials`; states endpoint `https://opensky-network.org/api/states/all` with `lamin`,
  `lomin`, `lamax`, `lomax`. Anonymous quota 400 credits a day, a box under 25 square degrees costs one credit.
- Secrets never logged; the result carries only counts, callsigns and the auth mode.
- Prompt: one tool line; `PROMPT_VERSION` 0.4.0. The live baseline is not re-run for one added tool line (budget:
  about 8.3 USD of the 10 USD monthly cap is spent); the offline smoke set and a three-case live mini-run on the
  new tool are the evidence, said so in the README.

## Tasks

1. Save spec documentation.
2. Settings, `opensky.py`, tool, prompt, compose wiring, `.env.example`, `render.yaml`.
3. `tests/test_v6_opensky.py`, smoke case, live mini-run, docs, commit, push.
