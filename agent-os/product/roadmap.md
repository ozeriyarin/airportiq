# Roadmap — airportiq

One-day take-home (1.11.2026), live interview afterwards. Each version is one Agent OS spec under
`agent-os/specs/<date>-<slug>/` and one commit series. Order is fixed: spec → code + tests → ruff → pytest → eval
report (when prompts/models change) → README/roadmap → commit.

## Shipped

- **v0 platform** (1.11.2026, spec `agent-os/specs/2026-11-01-v0-platform`, commit `4ca2322`): platform lifted from
  hubrisk and stripped of its domain; chain Sonnet 5.5 → Haiku 5.5 → Gemini 2.5 Flash (no OpenAI), Jev → Haiku guard
  with follow-up context, fixed intro, SQLite ledger, FastAPI API + chat page, sessions, rate limits, eval runner
  with grounding check, `--down` / `--model`, prompt caching, `agent verify`, CI, Render blueprint; 84 offline tests
  including 25 criterion tests; smoke eval 10/10 (`evals/results/ci-smoke`).

- **v1 airports and data** (1.11.2026, spec `agent-os/specs/2026-11-01-v1-airports-and-data`, commit `df86f19`): generated
  registry of 144 FAA hub airports with Census division, FAA service volume, runways and aliases; snapshot of FAA TAF
  (FY1976–FY2055, 11,456 rows), BTS On-Time 2023–2025 (5,076 origin-month rows), hand-downloaded BTS T-100 2023–2025
  (2,138 rows); 31 FAA capacity profiles extracted; DuckDB store; live FAA NAS status client; 15 criterion tests.

- **v2 capacity KPI** (1.11.2026, spec `agent-os/specs/2026-11-01-v2-capacity-kpi`, commit `df86f19`): `config/scoring.yaml`
  1.0.0, five percentile-normalized components, capacity precedence (FAA service volume > profile cross-check > runway
  model, RMSE 92,932 ops over 137 airports), lenses, eight tools, `agent score`, worked SFO example (CPS 73.1) asserted by
  a test; 16 criterion tests; 115 tests total.

- **v3 agent** (1.11.2026, spec `agent-os/specs/2026-11-01-v3-agent`, commit `dd57e32`): prompt 0.3.0 (tool guide, number
  rules, `_pct` fields so the model never converts ratios), 23-case live set, baseline 23/23 (repeat 2, 0 ungrounded,
  0.45 USD, 47% cache), `--down anthropic` 21/23 served by Gemini alone; 7 criterion tests.

- **v4 deploy** (1.11.2026, spec `agent-os/specs/2026-11-01-v4-deploy`, commit `dd57e32`): live at
  https://airportiq.onrender.com, dated `agent verify` record, assumptions / uncertainty / scoping table, DESIGN
  closeout (scoring methodology, key tradeoffs, where AI is used), demo script; 6 criterion tests (provider-cap
  dates awaited from the owner).

- **v5 voice** (1.11.2026, spec `agent-os/specs/2026-11-01-v5-voice`, commit `c3ab54b`): mic button (browser speech
  recognition, hidden when unsupported) and read-aloud toggle (speech synthesis) in the chat page; only text reaches
  the server; 4 criterion tests.

## Phase 1: MVP (must ship today)

1. ~~v0 platform~~ shipped. Was: lift the scaffold: model chain (Sonnet → Haiku → Gemini) with retries and fallback, Jev → Haiku
   guard, budget ledger, FastAPI API + chat page, sessions, rate limits, eval runner, prompt caching, CI, Render
   Blueprint, `agent verify`. Keyless run with `MODEL_MODE=test`.
2. ~~v1 airports and data~~ shipped. Was: generated registry of ~130 hub airports with Census region/division and aliases;
   ingest of FAA TAF, FAA enplanements, OurAirports runways, BTS On-Time (2023–2025 aggregates), hand-downloaded BTS
   T-100 aggregates, FAA capacity profile extraction; Parquet snapshots + manifest; DuckDB store; FAA NAS status
   live client with cache.
3. ~~v2 capacity KPI~~ shipped. Was: `config/scoring.yaml`, pure engine (five components, percentile normalization, weighted
   CPS, per-year band, trend, capacity model calibrated on the FAA profiles), tools that never raise, worked
   example (SFO) recomputed by a test.
4. ~~v3 agent~~ shipped. Was: domain prompts, tools wired, eval cases (the four brief questions plus off_topic / injection /
   false_positive / followup), baseline report and `--down anthropic` report.
5. ~~v4 deploy~~ shipped. Was: Render live, `agent verify` record, provider caps dated, DESIGN.md complete (scoring
   methodology, key tradeoffs, where AI is used), demo script.

## Phase 2: Bonus (only if time remains)

6. ~~v5 voice~~ shipped. Was: browser Web Speech mic and read-aloud in the chat page; nothing reaches the server.
7. **v6 OpenSky** — registered-account client for aircraft currently around an airport as a second live signal.
8. **v7 cost** — measured cache share and a Haiku-as-answerer experiment with the adoption rule stated first.

## Out of scope

Financial modelling, non-hub airports, airline-level analysis, multi-user auth, persistent sessions, streaming,
ASPM (login-gated; named in DESIGN as what production would use).
