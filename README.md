# airportiq — Airport Investment Intelligence Agent

A conversational agent that helps an airport-modernization investor see which US airports are under the most
capacity pressure: where added runway, gate or terminal capacity would be absorbed. Every number comes from
deterministic code over public FAA and BTS data; the LLM interprets the question, calls typed tools and explains
the result inside an enforced JSON schema.

Status: kickoff 1.11.2026. Design: `docs/DESIGN.md` (to come with v2). Product docs and specs: `agent-os/`.

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run agent chat --test "What can you help me with?"   # offline, no key, no spend
uv run agent serve --test                                # http://localhost:8000
```

Copy `.env.example` to `.env` and set the keys you have. A model whose key is missing is skipped at startup.

## Spend limits

- Code: `BUDGET_USD` enforced before every paid call (reserve → settle / release).
- Provider consoles: Anthropic, Google, TypeSafe caps set on `TODO(date)` by the owner.
