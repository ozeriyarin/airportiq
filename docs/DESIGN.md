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

## Scoring methodology

Arrives with v2 (`agent-os/specs/2026-11-01-v2-capacity-kpi`): five percentile-normalized components, versioned
weights, measured or modelled capacity always labelled, per-year bands, lenses for congestion, unmet demand,
expansion and long haul, and a worked SFO example recomputed by a test.

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
