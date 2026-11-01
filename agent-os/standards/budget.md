# Budget

- Hard monthly cap `BUDGET_USD`, enforced in code before any paid call by `app/llm/budget.py`: reserve an estimate in one `BEGIN IMMEDIATE` transaction, settle with the real cost after, release on a refusal, keep the estimate charged on a mid-call failure. Over the cap → `budget_exhausted`, never a quiet downgrade.
- Cost per turn comes from Pydantic AI's `RunUsage.cost` (genai-prices). When a model has no price there, `config/prices.yaml` prices it; an unknown model is charged the most expensive row.
- Per-turn ceiling via `UsageLimits(cost_limit, request_limit)`; per-IP and global request limits in the API; conversation memory capped at `max_turns`.
- The provider consoles carry the same cap (Anthropic Console → Limits; Google Cloud budget; TypeSafe dashboard). The code refuses *before* a call, the provider refuses *regardless* of the code. Both are required and documented in the README.
- `GET /api/stats` shows cap, month-to-date, remaining and the recent ledger so spend is visible without opening a console.
