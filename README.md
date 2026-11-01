# airportiq — Airport Investment Intelligence Agent

A conversational agent that helps an airport-modernization investor see which US airports are under the most
capacity pressure: where added runway, gate or terminal capacity would be absorbed. Every number comes from
deterministic code over public FAA and BTS data; the LLM interprets the question, calls typed tools and explains
the result inside an enforced JSON schema.

Design: [docs/DESIGN.md](docs/DESIGN.md) (architecture, where AI is used; scoring methodology lands with v2).
Product docs and specs: [agent-os/](agent-os/). Built 1.11.2026 as a one-day take-home.

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run agent chat --test "What can you help me with?"   # offline, no key, no spend
uv run agent serve --test                                # http://localhost:8000
```

With real models, copy `.env.example` to `.env` and set the keys you have (`ANTHROPIC_API_KEY` recommended;
`GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` optional). A model whose key is missing is skipped at
startup. Then:

```bash
uv run agent serve                       # chat page at /, API at /api/chat, docs at /api/docs
uv run agent eval --repeat 3 --tag latest
uv run agent eval --down anthropic --tag anthropic-outage   # proves cross-vendor fallback
```

Tests and lint (offline, no keys):

```bash
uv run ruff check src tests
uv run pytest -q
```

## Platform (v0)

- **Model chain:** `anthropic:claude-sonnet-5-5` → `anthropic:claude-haiku-5-5` → `google-gla:gemini-2.5-flash`
  through Pydantic AI's `FallbackModel`; per-model HTTP retries on 429/5xx/network with Retry-After; vendor SDK
  retries off. All models down → `status: unavailable`.
- **Guard:** regex layer → fixed intro for greetings → TypeSafe Jev screening (confidence ≥ 0.7, else Claude Haiku)
  with the previous question as context → fixed refusal strings. Refusals spend nothing.
- **Budget:** SQLite ledger enforces `BUDGET_USD` (10) per month before every paid call; 0.25 USD and 16 model
  requests per turn; 20 requests per IP per hour, 200 per day.
- **API:** `GET /health`, `POST /api/chat`, `DELETE /api/sessions/{id}`, `GET /api/stats` (admin token), chat page at `/`.
  Sessions in memory, 1 h TTL, LRU 500.
- **Evals:** `agent eval --repeat N --tag T --down <vendor> --model <id>`; reports under `evals/results/`; exit
  0 pass / 1 fail / 2 flaky; every number in an answer must appear in that turn's tool outputs.
- **Prompt caching** of the static prefix is on from the first commit; cache tokens are in every turn record.
- **Offline mode:** `MODEL_MODE=test` (or `--test`) runs everything on Pydantic AI's `TestModel`.

## Data and scoring

Arrive with v1 and v2 (see `agent-os/product/roadmap.md`). Sources: FAA Terminal Area Forecast, FAA enplanements,
OurAirports runways, BTS On-Time Performance, BTS T-100 (downloaded once by hand), FAA Airport Capacity Profiles,
FAA NAS status (live).

## Spend limits

- Code: `BUDGET_USD` enforced before every paid call (reserve → settle / release).
- Provider consoles: Anthropic, Google, TypeSafe caps set on `TODO(date)` by the owner.
- Prices: `config/prices.yaml`, verified 2026-11-01.

## Evals

| Report | Models | Result |
|---|---|---|
| `evals/results/ci-smoke` | TestModel (offline) | statuses and tools only; see the file |

## Assumptions, uncertainty, scoping

The full table lands with v2. Standing items: the score is a capacity-pressure proxy, not a profitability
estimate; the platform was lifted from an earlier project of the author and adapted in v0.
