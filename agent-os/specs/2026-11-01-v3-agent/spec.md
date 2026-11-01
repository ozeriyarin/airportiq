# Spec: v3 agent

Status: shaped 1.11.2026 (roadmap item approved with the v0–v2 specs); implemented in the same session.

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
5. A committed baseline report on the live set passes every case (exit 0) with the grounding check on, records prompt and config versions, cost, cache share and latency percentiles.
6. A committed `--down anthropic` report shows every answered run served by Gemini and the simulated outage in its notes.
7. The README evals table lists both reports with their pass counts and cost; the roadmap Shipped entry carries the commit.

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
