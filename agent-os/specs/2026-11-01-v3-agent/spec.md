# Spec: v3 agent

Status: shipped 1.11.2026, commit `dd57e32`, 7 criterion tests.

## Goal

Make the agent answer the brief's four questions and their follow-ups with the real models: domain prompts with
the tool guide and number rules, a live eval set whose expected facts are taken from the engine, an offline smoke
set, a baseline report and an Anthropic-down report proving cross-vendor fallback end to end.

## Scope

**In:** `app/agent/prompts.py` (tool guide, number and format rules, `PROMPT_VERSION`), `evals/cases.yaml` (live
set, at least 18 cases across in_scope / off_topic / injection / false_positive / followup), `evals/smoke.yaml`
(offline, tools asserted), reports `evals/results/v3-baseline.{json,md}` and `v3-anthropic-down.{json,md}`,
README evals table, DESIGN "where AI is used" refresh.

**Out:** deployment (v4), voice (v5), prompt tuning beyond what the baseline needs.

## Acceptance criteria

1. The system prompt names every registered tool with when to call it, forbids computing or combining numbers, requires the lens, the year and the denominator for percentages, and tells the model to state the capacity source; `PROMPT_VERSION` is bumped.
2. `evals/cases.yaml` holds the four brief questions as in_scope cases with `must_contain` facts read from the engine (airport ids, the ANC long-haul percentage, the SFO capacity source) and the tools that must be called.
3. The live set has at least three cases per category in off_topic, injection, false_positive and followup, and the follow-up cases use `prior_turns`.
4. The smoke set asserts the tool for each brief question offline (`rank_airports`, `compare_airports`, `traffic_mix`, `unmet_demand`) and `agent eval --test` exits 0.
5. A committed baseline report on the live set has no failed case (exit 0 or 2) with the grounding check on, records prompt and config versions, cost, cache share and latency percentiles; any flaky case is named in the README table with its reason. (Round 2: the set grew from 23 to 43 cases; a model-invented number that the grounding check catches in one of two runs is recorded as flaky, not hidden. Round 3: after the loop fixes the reports are `evals/results/v6-baseline` 43/43 with 0 of 86 ceiling hits and `evals/results/v6-anthropic-down` 41/43; the v3 reports stay as the pre-fix picture.)
6. A committed `--down anthropic` report shows every answered run served by Gemini and the simulated outage in its notes; its pass count is recorded honestly (a lower rate on the fallback model is expected, the proof is that answers still arrive).
7. The README evals table lists both reports with their pass counts and cost; the roadmap Shipped entry carries the commit.
10. (Round 3, guard measurement) `--down typesafe` removes the Jev decision model so the guard runs on Haiku alone; every turn and eval run records the guard model, its lowest field confidence, whether the fallback decided, its latency and its screening cost (a versioned name like jev-1.14.0 prices from the jev row); `evals/guard.yaml` holds exactly the four brief questions plus every off_topic, injection and false_positive case.
9. (Round 3) A tool called more than `max_calls_per_tool_per_turn` times in one turn (any arguments) returns `Repeated` with "answer now", and `traffic_mix` for a year outside the snapshot returns the latest year with a note naming the covered years instead of a bare not-found; both proven offline. (The captured loop was the model exploring years one by one after a not-found, alternating airport spellings, never two identical calls in a row.)
8. (Round 2) A tool called again with the same arguments in the same turn returns `Repeated` instead of running, so a model that re-issues a call cannot burn the request ceiling; proven offline with a scripted model that repeats a call, and the limit-exceeded log line names the tool-call sequence.

## Design

- Prompts: `TOOL_GUIDE` lists the nine tools; rules add percentile semantics, capacity-source wording, the
  "why" format (under 120 words, main driver first) and the Ambiguous handling ("ask which one").
- Eval facts come from `agent score` and the engine at authoring time and are pinned in `cases.yaml`; the
  grounding check guards every other number.
- `--down anthropic` leaves Gemini alone in the chain (no OpenAI), which is the honest fallback story.

## Tasks

1. Save spec documentation.
2. Prompts (done in v2 wiring), smoke set with tools.
3. Live cases from engine facts.
4. `agent eval --repeat 2 --tag v3-baseline`; fix prompt issues; `agent eval --down anthropic --tag v3-anthropic-down`.
5. `tests/test_v3_agent.py`; README evals table; DESIGN; roadmap; commit, push.
