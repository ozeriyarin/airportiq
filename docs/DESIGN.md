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

- **Browser chat page.** Speech-to-text and spoken answers (v5) run in the browser via the Web Speech API and
  never reach the API; the server only ever sees text.
- **Two live signals, outside the score.** The FAA NAS status feed (closures, ground stops, delay programs) and
  the OpenSky Network aircraft count around an airport (v6) are snapshots the agent reports beside the frozen
  score, never blended into it; both degrade to `available=False` with a reason.
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
| Screening for scope and prompt injection | yes, cheap | TypeSafe Jev decision model, Haiku fallback; policy in code. Measured 1.11.2026 on 16 guard cases × 2: identical labels from both, Jev 223 ms p50 vs Haiku 786 ms, 0.00031 vs 0.00007 USD per call, Jev unsure (fell through) on 4 of 23 screened runs; kept on latency under a rule stated before the run |
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
- `opensky.py` (v6, OpenSky Network): OAuth2 client-credentials token (cached, re-fetched once on a 401, anonymous fallback with the
  reason recorded), a bounding box of 25 km around the airport, state vectors counted into total, airborne and
  on-ground aircraft, per-airport cache of two minutes, quota and failures reported as `available=False`. A snapshot
  beside the score, never blended into it.
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

**Capacity precedence** (`capacity.py`, scoring 1.1.0): FAA capacity-profile hourly rate (FAA-measured, 31 of the
largest airports, 2014–2019) blended visual 0.7 / marginal 0.2 / instrument 0.1 times 4,000 hours-equivalent → FAA
annual service volume from the TAF table (109 airports) → a runway model fitted by least squares on the airports
with a service volume (`service_volume ~ runways_6000ft + runways`, n = 137, RMSE 92,932 operations per year), used
for 3 airports and reported with that RMSE; GUM has neither and reports capacity as unavailable. Every result names
the source. The order was reversed on 1.11.2026 after measuring the two FAA figures against each other: the
service volume is a planning value that is stale for the largest hubs (16 airports ran above it in FY2024, Denver
at 1.96 times; profile-to-volume ratio median 1.23, range 0.62 to 2.96), while the profiles are measured rates. Even
so, 11 airports still run above their capacity figure (LAS 1.73 on a service volume without a profile, SNA 1.50 on a
2014 profile of a GA-heavy field); their scores carry a limitation saying the figure is dated and utilization
should be read as "at or above capacity".

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
universe, but it is stale where it matters most, so the measured profile rates lead where they exist. Delay and
growth are composites because one sub-metric alone is gameable (taxi-out without delay share rewards big
airfields; forecast CAGR without actual CAGR rewards optimism).

### Worked example: SFO

Every figure below is what `agent score SFO` prints on the committed snapshot (scoring 1.1.0, registry 1.0.0);
`test_criterion_14_snapshot_facts_new_england_sfo_and_anchorage` asserts every percentile and the CPS against the
engine, so this table cannot drift from the code.

Capacity: the 2019 FAA capacity profile, blended rate 100.6 operations per hour × 4,000 hours-equivalent =
**402,400** operations per year (source `faa_profile`). The TAF service volume, 393,000, sits 2.4% below it and is
reported beside it.

| component | latest value (unit) | years in band | band | percentile | weight | contribution |
|---|---|---|---|---|---|---|
| utilization | 0.9476 (ops / capacity, FY2024) | FY2022–FY2024 | 0.8613–0.9476, trend +0.0863 | 90.8 | 0.30 | 27.24 |
| delay | 60.9 (combined percentile; delayed-15 share 0.1893 of 143,415 departures, excess taxi-out 8.4 min) | 2023–2025 | 0.1893–0.2335, trend −0.0105 | 60.9 | 0.25 | 15.22 |
| growth | 45.8 (combined percentile; forecast CAGR +3.13% to FY2034, actual CAGR −2.18% FY2019→FY2024) | — | — | 45.8 | 0.20 | 9.16 |
| load_factor | 0.8231 (passengers / seats, 2025) | 2023–2025 | 0.8231–0.8330, trend −0.0099 | 86.5 | 0.15 | 12.97 |
| long_haul | 0.1362 (25,885 of 190,110 departures ≥ 3,000 mi, 2025; international 20.9%) | 2023–2025 | 0.1251–0.1398, trend +0.011 | 97.2 | 0.10 | 9.72 |

**CPS = 74.3** (Σ contributions). Lenses: congestion 75.8 (mean of utilization 90.8 and delay 60.9), unmet demand
64.4 (mean of load factor 86.5, growth 45.8, delay 60.9), long haul 97.2. Reading: SFO runs at 95% of its FAA
profile capacity with high load factors and the fifth-highest long-haul share of the 144 hubs; its delay sits in the
middle because departure delays are average while taxi-out excess is high; growth is a split story, strong FAA
forecast against a traffic level still below FY2019. `unmet_demand` returns those three components as typed
drivers (load factor raises, delay raises, growth lowers) and the model narrates them.

Universe facts the example sits in: 144 hub airports (30 large, 35 medium, 79 small); 31 on an FAA capacity
profile, 109 on the FAA service volume, 3 on the runway model (GPI, IWA, XNA; RMSE 92,932 operations per year over
137 airports) and 1 without any capacity (GUM, no runway data), which is reported as unavailable.

## Repository structure

```
config/        agent.yaml (models, limits), prices.yaml (verified date), v1: airports.yaml, areas.yaml, capacity_profiles.yaml, v2: scoring.yaml
src/app/
  config.py    Settings (env, AIRPORTIQ_* aliases) + YAML config loaders
  cli.py       Typer: agent serve | chat | eval | verify | accept | registry | ingest | profiles | score; compose() is the only composition root
  accept.py    the live acceptance pass behind `agent accept <url>`
  llm/         models.py (chain, retries, fallback, cache settings), budget.py (SQLite ledger)
  decide/      guard.py (regex layer, Screening, Jev→Haiku, offline guard)
  agent/       schema.py (AnswerOut, Turn), prompts.py, tools.py, core.py (Service)
  api/         app.py (routes), ratelimit.py, sessions.py, static/index.html (chat page)
  evals/       cases.py, runner.py, grounding.py, report.py
  data/        v1: registry, readers, snapshots, DuckDB store, live client
  scoring/     v2: deterministic Capacity Pressure Score engine
data/          snapshots/*.parquet committed (v1); raw/ and the runtime SQLite ledger ignored
evals/         cases.yaml (live), smoke.yaml (offline), accept/ (cases for `agent accept` and the vendor-outage proof), results/<tag>.{json,md}
tests/         offline pytest; test_<spec-slug>.py holds that spec's criterion tests; test_spec_coverage.py enforces
agent-os/      product docs, standards (+ index.yml), one spec folder per version
docs/          this file, ACCEPTANCE.md (the acceptance pass with evidence), demo-script.md
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
`/api/stats` sits behind a constant-time admin token; when `ADMIN_TOKEN` is unset (local runs) the endpoint is
open by design and exposes only spend counts, and the Render blueprint always generates a token. The live FAA XML
is parsed with defusedxml. The client IP for rate limiting is taken from the first `X-Forwarded-For` hop, which is
spoofable, so the per-IP limit is a fairness measure and the global per-day cap is the spend ceiling. User text
and tool text are data, never instructions, and the `injection` eval category proves it on every run.

## What the evals showed

The first live baseline (prompt 0.2.0, 23 cases) passed 16 of 23; every miss but three was the model converting a
ratio into a percentage itself (0.1893 became 18.93%), which the grounding check rightly rejects because the
number was not in a tool result. The fix was in the tools, not the prompt alone: every share now ships with a
`_pct` field, and the prompt says to quote one or the other, never to multiply. The remaining three were test
authoring (a length cap too tight for a two-airport answer, source names missing from the data facts, a case that
required two spellings of one number).

The set then grew to 43 cases (every tool, a modelled-capacity airport, the no-capacity airport, bad years and
areas, area and lens aliases, a Hebrew question, five follow-ups). The same conversion showed up twice more, in
the weights the data facts list (0.3 became 30%) and in the per-year bands (0.8526 became 85.26%), and both got the
same treatment: the facts now state weights in both forms and every band value carries a `_pct` twin (prompt
0.3.1, scoring 1.1.0). The final baseline is 40 of 43 with no failed case and three flaky cases that share one
root cause: in two of 86 runs the model looped on tool calls until the 16-request ceiling stopped the turn
(`cannot_answer`, zero spend), and one of those was a prior turn, which left its follow-up without context. The
loop was then caught in the act with `capture_run_messages`. The first capture looked like one call repeated
fifteen times; the full trace showed something else: after a not-found for a year outside the snapshot, the model
explored every valid year one by one, alternating "Anchorage" and "ANC", calling `about` in between, and never
wrote the reply. Two deterministic fixes followed, neither a prompt plea: a year outside the snapshot returns the
latest year with a note naming the covered years, and any tool called more than four times in a turn answers
"you have the data, answer now" (a repeated identical call returns the earlier result's pointer). A limit-exceeded
turn logs its call sequence (names and arguments, never content). Measured on the same 43 cases with repeat 2
(`evals/results/v6-baseline`, prompt 0.4.0): 43/43, 0 of 86 runs hit the
ceiling, 0 ungrounded, 0.78 USD, p95 10699 ms against 12616 ms
before; Gemini alone 41/43. The pre-fix reports stay in `evals/results/v3-*` as the before picture. The third flaky
case ("can an analyst override the weights?") drew an honest "I cannot confirm" once, which the case should have
accepted. Gemini alone (`--down anthropic`) passes 40 of 43, missing on formatting (31% for 31.0, a rounded
percentile) and two numbers it computed itself. The reports under `evals/results/` are the evidence; the README
table summarizes them.

## What production would change

Persistent sessions and ledger (Postgres), per-user auth, streaming replies, ASPM access for measured capacity at
every airport, scheduled snapshot refresh, and calibration of the weights against realised project outcomes. Tool
output size is the first cost lever: the largest turn in the v6 baseline (`xna-modelled`) put 67,957 input tokens
(35,225 uncached) into one turn because rankings and breakdowns return full component detail, so production
would return summary rows from `rank_airports` and fetch detail per airport on demand.
