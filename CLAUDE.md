# CLAUDE.md

## What this is

airportiq: a conversational airport-capacity-pressure agent for a US airport-modernization investor, built
production-shaped as a one-day take-home (1.11.2026). Python 3.12, Pydantic AI, FastAPI, DuckDB over committed
Parquet, Render. Owner: Yarin Ozeri. Public repo `ozeriyarin/airportiq`, solo, commit straight to `main`.

## Workflow (Agent OS v3)

- Read `agent-os/product/` (mission, roadmap, tech-stack) before any work; standards in `agent-os/standards/` via `index.yml`.
- One spec per version: `agent-os/specs/<date>-<slug>/spec.md` with Goal, Scope, Acceptance criteria (numbered), Design, Tasks. Use `/shape-spec` in plan mode.
- Every criterion gets `test_criterion_<n>_<slug>` in `tests/test_<slug>.py`; `tests/test_spec_coverage.py` enforces it per spec.
- Order: spec → code + tests → `uv run ruff check src tests` → `uv run pytest` → eval report if prompts/models changed → README/roadmap closeout → commit.

## House rules

- Comments: one line, ≤100 chars, only when intent is not obvious. Explanations live in `docs/DESIGN.md` and the specs.
- Tests run offline; every external system has a fake. Never patch the network.
- Secrets only via env; never commit `.env`, `data/raw`, `*.db`. `MODEL_MODE=test` for keyless runs.
- Every AI call goes through Pydantic AI and the budget; no vendor SDK imports outside `app/llm/models.py`.
- The LLM never produces a number; every figure comes from a tool over the data. Measured vs modelled capacity is always labelled.
- Commit messages: `<prefix>/<dd-mm-yy hh-mm> - <what it does>`, prefix in `feature|fix|logs|debugging|crucial-adds`; tests green first.
- Docs move with the code in the same commit; no "still to come" lines; numbers in README match config and reports.
- Reply in English; keep answers short; surface the size of a change before building it when it grows.

## Commands

```bash
uv sync                      # install
uv run pytest -q             # offline tests
uv run ruff check src tests
uv run agent chat --test "hi"            # offline demo
uv run agent serve                       # http://localhost:8000
uv run agent registry                    # regenerate config/airports.yaml from the source files
uv run agent ingest                      # rebuild data/snapshots from FAA/BTS sources
uv run agent profiles                    # extract FAA capacity profile rates into config
uv run agent score SFO                   # one airport's CPS breakdown, no model call
uv run agent eval --repeat 3 --tag latest
uv run agent eval --down anthropic --tag anthropic-outage
```
