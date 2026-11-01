# airportiq — Design

Capacity-pressure agent for a US airport-modernization investor. This document covers the system architecture,
the scoring methodology (v2), the key tradeoffs and where AI is used. Product goals live in `agent-os/product/`,
behaviour in `agent-os/specs/`, conventions in `agent-os/standards/`.

## System architecture

```
browser chat page ──HTTP──▶ FastAPI (app/api)
                               │  rate limit per IP + global, session store (TTL + LRU, one lock per session)
                               ▼
                           Service.ask (app/agent/core.py)
                               │ 1. regex input checks            (app/decide/guard.py, free)
                               │ 2. fixed intro for greetings     (no model, no spend)
                               │ 3. budget.reserve                (app/llm/budget.py, SQLite ledger)
                               │ 4. guard.screen → Screening      (TypeSafe Jev → Claude Haiku fallback)
                               │ 5. Agent.run(output_type=AnswerOut, UsageLimits)
                               │       └─ FallbackModel chain: Sonnet 5.5 → Haiku 5.5 → Gemini 2.5 Flash
                               │       └─ FunctionToolset: deterministic tools (v2: the capacity engine)
                               │ 6. budget.settle(real cost)
                               ▼
                           Turn (status, answer, sources, limitations, served_by, failed_attempts, tokens, cost, latency)
```

- **The LLM never produces a number.** Tools return typed Pydantic models; the model picks tools and explains.
  `AnswerOut` is enforced by Pydantic AI; a reply that fails validation is retried once, then the turn fails loudly.
- **Three retry layers, one job each:** the httpx transport retries 429/5xx/network per model with Retry-After;
  vendor SDK retries are off; `FallbackModel` moves to the next model on an API error, an HTTP error or a truncated
  reply. All models down → `status: unavailable`, never a crash.
- **Guard before spend:** the regex layer costs nothing; greetings get a fixed intro; the decision model is Jev
  (typed questions, calibrated confidence) with Haiku taking over below `guard_confidence` or on error. The previous
  question is passed as context so follow-ups stay in scope. Refusals are fixed strings and release the reservation.
- **Spend is bounded twice:** the ledger enforces `BUDGET_USD` per month before every paid call, plus `UsageLimits`
  per turn and per-IP / daily request limits. Provider consoles carry the same cap as the hard backstop.
- **Prompt caching from the first commit.** The static prefix (instructions, tool definitions) is cached on
  Anthropic; cache reads and writes are recorded per turn and per eval report. The system prompt carries no date.
- **Evals are the quality gate:** `evals/cases.yaml` by category, `agent eval` writes `evals/results/<tag>`,
  exit 0 pass / 1 fail / 2 flaky, `--down <vendor>` proves cross-vendor fallback, and a grounding check fails any
  run whose answer contains a number absent from that turn's tool outputs.

## Where AI is used, and where it deliberately is not

| Step | AI? | What |
|---|---|---|
| Understanding the question, choosing tools, writing the explanation | yes | Claude Sonnet 5.5 (fallbacks Haiku, Gemini) inside an enforced JSON schema |
| Screening for scope and prompt injection | yes, cheap | TypeSafe Jev decision model, Haiku fallback; policy in code |
| Every number, ranking, percentage, capacity figure | **no** | deterministic engine over committed snapshots (v2) |
| Region, division and name resolution | **no** | registry YAML with aliases (v1) |
| Refusal, intro and error text | **no** | fixed strings in code |
| Greeting detection | **no** | anchored regex |

## Data layer (`app/data`)

- `areas.py`: Census regions and divisions by state plus informal areas (`config/areas.yaml`); "New England" or
  "west coast" is a lookup, never a model guess.
- `registry.py`: `Airport` and `AirportRegistry` over the generated `config/airports.yaml` (144 FAA large, medium
  and small hubs). `find` resolves ids, IATA, ICAO, city, name and aliases, and returns the candidates when a
  name is ambiguous ("Portland" → PDX, PWM). `build_registry` is a pure join of the three source files.
- `taf.py`: the FAA Terminal Area Forecast zip. Scenario 0 is actual (FY1976–FY2024), 1 is forecast (to FY2055);
  total operations exclude overflights; enplanements keep the international split. The airport table carries the
  FAA annual service volume, the measured capacity used by the engine.
- `ontime.py`: one BTS On-Time monthly zip (about 600k flights) aggregated with DuckDB into one row per origin and
  month; fields are read by name and a missing field raises `SourceError`.
- `t100.py`: the hand-downloaded T-100 yearly CSVs aggregated per origin, year, international, long-haul and
  cargo flag. The manifest records that no scripted download exists and which fields were selected.
- `profiles.py`: pypdf text plus one regex over five wording variants of the FAA capacity-profile sentence
  ("rate range in Visual conditions ... is currently 104-107 operations per hour"), written to
  `config/capacity_profiles.yaml` with the profile year and URL.
- `snapshot.py` / `store.py`: DuckDB writes the Parquet tables and the manifest atomically; `Store` exposes typed
  per-airport queries, `years` and `coverage`. `live.py`: the FAA NAS status XML (defusedxml), cached per feed,
  one minute after a failure, `available=False` with a reason instead of an exception.

## Scoring methodology (`app/scoring`)

The product's number is the **Capacity Pressure Score (CPS), 0–100 per airport**. `config/scoring.yaml` (version
1.0.0) holds every definition; `scoring_version` travels with every result.

**Components** (latest-year value, per-year series over the window, min, max, trend):

| component | definition | source | weight |
|---|---|---|---|
| utilization | annual operations / annual capacity, latest three actual fiscal years | FAA TAF | 0.30 |
| delay | mean of percentile(delayed-15 share) and percentile(mean taxi-out minus the airport's own p10 taxi-out) | BTS On-Time | 0.25 |
| growth | mean of percentile(FAA forecast 10-year enplanement CAGR) and percentile(actual CAGR FY2019→FY2024) | FAA TAF | 0.20 |
| load_factor | passengers / seats, scheduled passenger service | BTS T-100 | 0.15 |
| long_haul | departures of 3,000+ statute miles / all departures | BTS T-100 | 0.10 |

**Capacity precedence** (`capacity.py`): FAA annual service volume from the TAF table (measured, 140 airports) →
FAA capacity-profile hourly rate blended visual 0.7 / marginal 0.2 / instrument 0.1 times 4,000 hours-equivalent
(31 airports have a profile; it is reported as a cross-check beside the service volume) → a runway model fitted by
least squares on the airports with a service volume (`service_volume ~ runways_6000ft + runways`, n = 137, RMSE
92,932 operations per year), used for the 3 airports without one that have runway data and reported with that
RMSE. Every result names the source.

**Normalization and lenses** (`components.py`, `engine.py`): each component's latest value is percentile-ranked
within the universe (ties share a rank), so a value reads as "higher than N% of hub airports". CPS = Σ weight ×
percentile; missing components renormalize the weights and are listed in `limitations`. Lenses map the brief's
questions onto subsets: `expansion` = CPS, `congestion` = utilization + delay, `unmet_demand` = load factor +
growth + delay, `long_haul`. Rankings sort by the lens with ties broken by airport id; comparisons list every
component for both airports with the difference and which is higher; `unmet_demand` returns typed drivers sorted
by distance from the median percentile. The engine is pure over the store and table-tested; the same snapshot
always yields the same output.

**Why these choices.** Percentiles survive the DEN/ATL outliers that would flatten a min–max scale and read
naturally in a sentence. The FAA service volume is the only published per-airport capacity that covers the whole
universe; the profiles exist for 31 airports and agree with it within a few percent where both exist, which is
the evidence that the service volume is usable. Delay and growth are composites because one sub-metric alone is
gameable (taxi-out without delay share rewards big airfields; forecast CAGR without actual CAGR rewards optimism).

### Worked example: SFO

Every figure below is what `agent score SFO` prints on the committed snapshot (scoring 1.0.0, registry 1.0.0);
`test_criterion_14_snapshot_facts_new_england_sfo_and_anchorage` asserts every percentile and the CPS against the
engine, so this table cannot drift from the code.

Capacity: FAA annual service volume **393,000** operations per year (source `faa_service_volume`, measured). The
2019 FAA capacity profile cross-checks it: blended rate 100.6 operations per hour × 4,000 hours-equivalent =
402,400, 2.4% above the service volume.

| component | latest value (unit) | years in band | band | percentile | weight | contribution |
|---|---|---|---|---|---|---|
| utilization | 0.9702 (ops / capacity, FY2024) | FY2022–FY2024 | 0.8819–0.9702, trend +0.0883 | 86.6 | 0.30 | 25.98 |
| delay | 60.9 (combined percentile; delayed-15 share 0.1893 of 143,415 departures, excess taxi-out 8.4 min) | 2023–2025 | 0.1893–0.2335, trend −0.0105 | 60.9 | 0.25 | 15.22 |
| growth | 45.8 (combined percentile; forecast CAGR +3.13% to FY2034, actual CAGR −2.18% FY2019→FY2024) | — | — | 45.8 | 0.20 | 9.16 |
| load_factor | 0.8231 (passengers / seats, 2025) | 2023–2025 | 0.8231–0.8330, trend −0.0099 | 86.5 | 0.15 | 12.97 |
| long_haul | 0.1362 (25,885 of 190,110 departures ≥ 3,000 mi, 2025; international 20.9%) | 2023–2025 | 0.1251–0.1398, trend +0.011 | 97.2 | 0.10 | 9.72 |

**CPS = 73.1** (Σ contributions). Lenses: congestion 73.8 (mean of utilization 86.6 and delay 60.9), unmet demand
64.4 (mean of load factor 86.5, growth 45.8, delay 60.9), long haul 97.2. Reading: SFO runs at 97% of its FAA
service volume with high load factors and the fifth-highest long-haul share of the 144 hubs; its delay sits in the
middle because departure delays are average while taxi-out excess is high; growth is a split story, strong FAA
forecast against a traffic level still below FY2019. `unmet_demand` returns those three components as typed
drivers (load factor raises, delay raises, growth lowers) and the model narrates them.

Universe facts the example sits in: 144 hub airports (30 large, 35 medium, 79 small); 140 with an FAA service
volume, 31 with a capacity profile, 3 on the runway model (GPI, IWA, XNA; RMSE 92,932 operations per year over
137 airports) and 1 without any capacity (GUM, no runway data), which is reported as unavailable.

## Repository structure

```
config/        agent.yaml (models, limits), prices.yaml (verified date), v1: airports.yaml, areas.yaml, capacity_profiles.yaml, v2: scoring.yaml
src/app/
  config.py    Settings (env, AIRPORTIQ_* aliases) + YAML config loaders
  cli.py       Typer: agent serve | chat | eval | verify (+ v1: registry, ingest, profiles; v2: score); compose() is the only composition root
  llm/         models.py (chain, retries, fallback, cache settings), budget.py (SQLite ledger)
  decide/      guard.py (regex layer, Screening, Jev→Haiku, offline guard)
  agent/       schema.py (AnswerOut, Turn), prompts.py, tools.py, core.py (Service)
  api/         app.py (routes), ratelimit.py, sessions.py, static/index.html (chat page)
  evals/       cases.py, runner.py, grounding.py, report.py
  data/        v1: registry, readers, snapshots, DuckDB store, live client
  scoring/     v2: deterministic Capacity Pressure Score engine
data/          snapshots/*.parquet committed (v1); raw/ and the runtime SQLite ledger ignored
evals/         cases.yaml (live), smoke.yaml (offline), results/<tag>.{json,md}
tests/         offline pytest; test_<spec-slug>.py holds that spec's criterion tests; test_spec_coverage.py enforces
agent-os/      product docs, standards (+ index.yml), one spec folder per version
docs/          this file, demo-script.md (v4)
.github/       CI: ruff + pytest + offline eval smoke
render.yaml    Render Blueprint (python runtime, uv sync --frozen --no-dev, /health probe)
```

## Key tradeoffs

- **Lifted platform vs. building fresh.** The platform (chain, guard, ledger, evals) was lifted from an earlier
  project of the author and adapted in v0, so the day goes to the airport logic and the design. Said plainly here.
- **Sessions in memory, ledger in SQLite.** A restart forgets conversations and, on Render's free tier, the
  month-to-date spend; provider-side caps are the backstop. Acceptable for an analyst tool at this scale.
- **Three vendors, no OpenAI.** Same-vendor cheaper model first, then Gemini, keeps a vendor outage from taking the
  demo down while keeping the key set small.

## Security and privacy

Secrets only from env; never logged. Logs carry session prefixes, statuses and model names, never chat content.
`/api/stats` behind a constant-time admin token. User text and tool text are data, never instructions, and the
`injection` eval category proves it on every run.

## What production would change

Persistent sessions and ledger (Postgres), per-user auth, streaming replies, ASPM access for measured capacity at
every airport, scheduled snapshot refresh, and calibration of the weights against realised project outcomes.
