# v0 platform — Shaping Notes

## Scope

Lift the production-shaped platform (model chain, guard, budget, API, sessions, evals, caching, CI, blueprint)
so every later version only adds airports, data, scoring and prompts. Keyless run with `MODEL_MODE=test`.

## Decisions

- Lifted hubrisk's final platform modules rather than the older `agent-assignment` scaffold: hubrisk already had
  prompt caching, the grounding check, `--model`, the turn record and `agent verify`, so nothing had to be rebuilt.
- Weather domain removed: no `data/`, `scoring/`, `alerts.py`; `ToolContext` carries `product_name` and a
  `data_facts` string the v1/v2 engine will fill; the only tool is `about`.
- Chain Sonnet → Haiku → Gemini, no OpenAI (owner decision 1.11.2026); the plain OpenAI branch left `build_model`,
  the OpenRouter branch stays for Jev via OpenRouter if TypeSafe direct fails.
- `AIRPORTIQ_*` prefixed env names win over plain names (`AliasChoices`), because shared cloud environments withhold
  `ANTHROPIC_API_KEY`; `populate_by_name` keeps tests constructing `Settings(anthropic_api_key=...)`.
- Prices verified 1.11.2026 from the Claude API model table (Sonnet 5.5 2.00/10.00, Haiku 5.5 0.10/0.50); Gemini and
  Jev rows from third-party trackers, marked as such in `config/prices.yaml`.
- Voice stays out of the chat page until v5 so the roadmap tells the truth.

## Context

- **Visuals:** none.
- **References:** `C:\ai-projects\hubrisk` (`src/app`, `tests/test_v0_platform.py`, `config/`, `render.yaml`).
- **Product alignment:** mission "production-shaped platform", roadmap item 1.

## Standards Applied

- ai-calls, guardrails, budget, evals, testing, secrets-and-config, deployment, python-style.

## Lesson recorded

- The Bash tool collapses `\\` in heredocs: a regex written through a Bash heredoc ended up with backspace bytes.
  Backslash-heavy edits go through the Edit/Write tools or a script file.
