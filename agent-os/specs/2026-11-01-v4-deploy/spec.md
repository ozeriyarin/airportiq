# Spec: v4 deploy

Status: shipped 1.11.2026, commit `dd57e32`, 6 criterion tests.

## Goal

The agent runs at a public URL on Render's free tier from the committed Blueprint, verified by `agent verify`,
with provider-side spend caps set and dated, and the deliverable docs complete: README (run, data, scoring,
assumptions table, evals, deployment record, spend limits), DESIGN (architecture, scoring methodology, key
tradeoffs, where AI is used), demo script.

## Scope

**In:** Render service created by the owner from `render.yaml`; secrets set in the dashboard; `agent verify
<url>` record in the README; README assumptions / uncertainty / scoping table; DESIGN deployment section and
closeout pass; `docs/demo-script.md` numbers; provider caps dated. **Out:** custom domain, persistent disk, alerts.

## Acceptance criteria

1. `render.yaml` validates for the `airportiq` service with the four vendor keys as `sync: false`, `BUDGET_USD` 10, `/health` probe and `uv sync --frozen --no-dev`.
2. The README deployment section carries the live URL and a dated `agent verify` record showing real models, the guard and the snapshot coverage, plus the free-tier facts (sleep, cold start, ephemeral ledger).
3. The README spend-limits section carries the code cap and the provider-console caps with the dates the owner set them.
4. The README assumptions / uncertainty / scoping table lists at least: proxy not profitability, uncalibrated weights, capacity sources and the model RMSE, domestic-only delays, hand-downloaded T-100 vintage, COVID exclusions, universe = hub airports, sessions and ledger ephemeral.
5. DESIGN names the three asked topics as sections (scoring methodology, key tradeoffs, where/how AI is used) and no doc contains "still to come", "TODO", "TBD" or "pending".
6. `docs/demo-script.md` numbers match `agent score` output and the README.

## Tasks

1. Save spec documentation.
2. Owner creates the service and sets secrets; agent runs `agent verify`, pastes the record.
3. README tables and deployment section; DESIGN closeout; demo script numbers.
4. `tests/test_v4_deploy.py`; drift grep; commit, push; final acceptance checklist.
