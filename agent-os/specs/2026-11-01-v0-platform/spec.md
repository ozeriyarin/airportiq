# Spec: v0 platform

Status: shaped 1.11.2026, awaiting owner approval.

## Goal

Stand up the domain-agnostic platform airportiq runs on by lifting the pre-built scaffold (`agent-assignment`,
55 tests green): model chain with retries and cross-vendor fallback, typed guard, spend budget, FastAPI API with a
chat page, sessions, rate limits, eval runner with an exit-code gate and grounding check, prompt caching, offline
tests, CI and a Render Blueprint. After this spec the app runs keyless (`MODEL_MODE=test`), every gate is tested,
and later specs only add airports, data, scoring and prompts.

## Scope

**In:** everything under `src/app/` except domain code; `config/agent.yaml` (chain Sonnet → Haiku → Gemini, no
OpenAI), `config/prices.yaml` with a verified date; `evals/` runner and a smoke case set; `tests/`;
`render.yaml`; `agent verify`; `--down` and `--model` flags; turn record; README and DESIGN skeletons.

**Out:** airports, data, scoring, domain tools and prompts (v1–v3); live deployment (v4); voice.

## Acceptance criteria

1. `build_chain` skips a model whose vendor key is missing with a log line and raises `RuntimeError` when no key is set; the configured chain is Sonnet → Haiku → Gemini and contains no OpenAI entry.
2. When the first model raises `ModelAPIError`, an `httpx2.HTTPError` or returns a truncated reply, the next model answers; `Turn.served_by` names it and `Turn.failed_attempts` lists the failure.
3. The HTTP transport retries 429 and 5xx up to `retry_attempts` honouring `Retry-After`, does not retry 401, and vendor SDK retries are off.
4. With every model down, `Service.ask` returns status `unavailable` and the ledger keeps the reservation as failed.
5. Empty, over-long, control-character or regex-matched injection input is rejected before any model call and spends nothing.
6. A bare greeting or capability question is answered by the fixed intro (with the four brief questions as examples) before the guard and the budget; anchored patterns keep real questions on the model path.
7. The guard maps `Screening` to `in_scope` / `off_topic` / `injection`; a decision-model error or any field confidence below `guard_confidence` falls back to Haiku; refusals are the fixed strings in `prompts.py` and release the reservation; the previous question is passed as guard context so follow-ups stay in scope.
8. The budget reserves before a call, settles with real cost after, releases on refusal, keeps the estimate on failure, refuses with `budget_exhausted` at the monthly cap, resets by month, and prices an unknown model at the most expensive row.
9. A turn exceeding `request_limit` or `cost_limit` ends with status `cannot_answer`, not an exception.
10. Conversation history is sent on follow-ups and trimmed to `max_turns`.
11. `GET /health` lists chain models, guard name and a `data` field (null until v1); `POST /api/chat` returns the `Turn` plus `session_id`, reports `session_reset` for an unknown id, and returns 422 on an empty message.
12. Requests over `per_ip_per_hour` or `global_per_day` get 429 with `Retry-After`.
13. Sessions expire after `session_ttl_s`, the store evicts least-recently-used beyond 500, and `DELETE /api/sessions/{id}` returns 204.
14. `GET /api/stats` returns 401 without the admin token (constant-time compare) and the ledger stats with it.
15. `EvalCase` rejects duplicate ids and strings in both `must_contain` and `must_not_contain`; `check` reports status, must_contain, must_not_contain, tools, max_chars and grounding reasons.
16. The eval runner exits 0 when all runs pass, 1 when a case fails every run, 2 when only flaky; `--down <vendor>` removes that vendor from the chain and `--model <id>` runs a single model; the report records models, prompt and config versions, cost, cache share, p50/p95 and the per-case table.
17. The grounding check fails a run whose answer contains a number absent from that turn's tool outputs (tolerance 0.0051 below 1, 0.051 above).
18. With `MODEL_MODE=test` and no keys, the app composes, the guard labels ordinary questions `in_scope`, and `agent eval --test` on the committed smoke cases exits 0.
19. `config/agent.yaml` and `config/prices.yaml` validate, both carry `version`, `prices.yaml` carries a `verified` date, every chain model has a price, and the product name is `airportiq`.
20. Anthropic prompt caching is on (`models.cache: true`), the system prompt contains no date, and the turn record carries cache read and write tokens.
21. Every `Turn` carries served_by, failed_attempts, guardrail, tools_used, tokens in/out/cache, cost and latency; logs carry ids and statuses only, never chat content.
22. The coverage test fails naming the spec and expected file when a criterion lacks its test, and criteria of different specs never satisfy each other.
23. `GET /` serves the single-file chat page titled airportiq that calls `/api/chat`, with no external scripts.
24. `agent verify <url>` calls `/health` and asks one scored question through a retrying client and prints a dated record.
25. `.github/workflows/ci.yml` runs ruff, pytest and the offline eval smoke; `render.yaml` names the service `airportiq`, builds with `uv sync --frozen --no-dev`, starts `agent serve`, probes `/health`, lists `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` as `sync: false` and sets `BUDGET_USD` to 10.

## Design

Package `app` under `src/`, one subpackage per concern, `cli.compose` the only composition root. Lifted from the
scaffold and adapted; the module map is the same as hubrisk's:

- `app/config.py`: `Settings` (env, pydantic-settings; `AIRPORTIQ_*` prefixed variants win over plain names),
  `AgentConfig` from `config/agent.yaml`, prices from `config/prices.yaml`.
- `app/llm/models.py`: the only module importing vendor SDKs. Retrying transport, `build_model` with SDK retries
  off, `build_chain` → `FallbackModel(fallback_on=[ModelAPIError, httpx2.HTTPError, truncated])`, cache settings.
- `app/llm/budget.py`: SQLite ledger (`BEGIN IMMEDIATE`), reserve → settle / release(failed), estimate from the max
  of the last 20 settled calls × 1.25.
- `app/decide/guard.py`: `check_input`, `intro_reply`, `Screening`, Jev → Haiku, `offline_guard_model()`.
- `app/agent/`: `schema.py` (`AnswerOut`, `Turn`, `Status`), `prompts.py` (`PROMPT_VERSION`, scope, number rules,
  fixed refusal and intro strings), `tools.py` (`about` placeholder until v2), `core.py` (`Service.ask`).
- `app/api/`: routes, `RateLimiter`, `SessionStore`, `static/index.html`.
- `app/evals/`: `EvalCase`, runner (`--repeat`, `--tag`, `--down`, `--model`), grounding, report.
- `app/data/`, `app/scoring/`: empty packages reserved for v1 and v2.
- Tests: criterion tests in `tests/test_v0_platform.py`; `tests/test_spec_coverage.py` checks per spec folder.

Changes over the scaffold: OpenAI removed from the chain, prices and render; intro reply with the brief's four
questions; guard context from the previous question; grounding check; `--model`; cache settings; turn record
fields; `agent verify`; product name.

## Tasks

1. Save spec documentation.
2. Lift the scaffold into the repo (`pyproject.toml` named `airportiq`, `uv.lock`, `config/`, `src/app/`, `tests/`,
   `evals/`, `render.yaml`); `uv sync`; tests green unchanged.
3. Chain, prices (verify ids and prices with the claude-api skill, write the date), render, config renames.
4. Intro reply, guard context, grounding check, `--model`, cache settings, turn record, `agent verify`.
5. `tests/test_v0_platform.py` with the 25 criterion tests; coverage rule.
6. README platform section, DESIGN skeleton; `ruff`, `pytest`, `agent eval --test --tag ci-smoke` (commit the
   report), roadmap Shipped entry, commit, push.
