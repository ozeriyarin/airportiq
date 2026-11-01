# Roadmap — airportiq

One-day take-home (1.11.2026), live interview afterwards. Each version is one Agent OS spec under
`agent-os/specs/<date>-<slug>/` and one commit series. Order is fixed: spec → code + tests → ruff → pytest → eval
report (when prompts/models change) → README/roadmap → commit.

## Shipped

(none yet; kickoff 1.11.2026, repo skeleton commits `9ec1bcc`, `b897236`)

## Phase 1: MVP (must ship today)

1. **v0 platform** — lift the scaffold: model chain (Sonnet → Haiku → Gemini) with retries and fallback, Jev → Haiku
   guard, budget ledger, FastAPI API + chat page, sessions, rate limits, eval runner, prompt caching, CI, Render
   Blueprint, `agent verify`. Keyless run with `MODEL_MODE=test`.
2. **v1 airports and data** — generated registry of ~130 hub airports with Census region/division and aliases;
   ingest of FAA TAF, FAA enplanements, OurAirports runways, BTS On-Time (2023–2025 aggregates), hand-downloaded BTS
   T-100 aggregates, FAA capacity profile extraction; Parquet snapshots + manifest; DuckDB store; FAA NAS status
   live client with cache.
3. **v2 capacity KPI** — `config/scoring.yaml`, pure engine (five components, percentile normalization, weighted
   CPS, per-year band, trend, capacity model calibrated on the FAA profiles), tools that never raise, worked
   example (SFO) recomputed by a test.
4. **v3 agent** — domain prompts, tools wired, eval cases (the four brief questions plus off_topic / injection /
   false_positive / followup), baseline report and `--down anthropic` report.
5. **v4 deploy** — Render live, `agent verify` record, provider caps dated, DESIGN.md complete (scoring
   methodology, key tradeoffs, where AI is used), demo script.

## Phase 2: Bonus (only if time remains)

6. **v5 voice** — browser Web Speech mic and read-aloud in the chat page; nothing reaches the server.
7. **v6 OpenSky** — registered-account client for aircraft currently around an airport as a second live signal.
8. **v7 cost** — measured cache share and a Haiku-as-answerer experiment with the adoption rule stated first.

## Out of scope

Financial modelling, non-hub airports, airline-level analysis, multi-user auth, persistent sessions, streaming,
ASPM (login-gated; named in DESIGN as what production would use).
