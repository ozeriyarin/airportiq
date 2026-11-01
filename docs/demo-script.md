# airportiq — two-minute demo script

Numbers below are refreshed at closeout from `agent score` and the eval reports; keep them in sync with the README.

## 0. One sentence

"An analyst's assistant that ranks US hub airports by capacity pressure, where every number is computed by code
over FAA and BTS data and the LLM only chooses tools and explains."

## 1. Open the chat (30 s)

- Show the page, the four example questions, and `/health` (models, guard, snapshot coverage).
- Say: Sonnet 5.5 answers, Haiku and Gemini are fallbacks; a TypeSafe Jev model screens every question first.

## 2. The four brief questions (60 s)

1. *Which airports in New England are strong candidates for terminal expansion?* → `rank_airports(expansion, New
   England)`: BOS first, then the small hubs; point at "top driver" and the capacity source per airport.
2. *Compare LA and Santa Ana airport congestion levels.* → alias resolution (LA → LAX, Santa Ana → SNA), the
   congestion lens, component by component with percentiles.
3. *What is the percentage of long haul flights out of Anchorage airport?* → `traffic_mix`: the share, the year,
   the denominator, cargo share; note 3,000 miles is a stated definition.
4. *What is the unmet flight demand in SFO airport and why?* → `unmet_demand`: typed drivers, utilization context,
   2019 FAA profile capacity 402,400 (service volume 393,000 beside it); "inferred, not observed".
   Follow-up: *and the year before?* → the engine's per-year series, no new definition.

## 3. Under the hood (30 s)

- `config/scoring.yaml`: five components, weights, lenses, capacity precedence; version string in every answer.
- `agent score SFO` in the terminal: the same numbers, no model call.
- Live: "How many planes are around SFO right now?" → OpenSky snapshot (registered client), separate from the score.
- Guard: ask "write me a poem" → fixed refusal, zero spend; "ignore your instructions" → regex layer.
- `evals/results/`: baseline report (pass rate, grounding, cost, cache share) and the Anthropic-down report.

## Numbers to have ready

- Universe: 144 FAA hub airports (30 large, 35 medium, 79 small); 31 on an FAA profile, 109 on the service volume.
- Capacity model: RMSE 92,932 operations per year over 137 airports (used for 3 airports; GUM has no capacity).
- SFO: CPS 74.3; utilization 0.95 of 402,400 operations; load factor 0.823; long-haul 13.6% of 190,110 departures (2025).
- ANC: 31.0% long-haul of 87,988 departures in 2025; cargo 59% of movements.
- Cost: a Sonnet tool turn ≈ 0.01–0.03 USD with caching; eval run cost in the README table.

## Honest answers

- "Profitability?" The score is a capacity-pressure proxy; cost, financing and revenue are out of scope.
- "How sure?" Bands per year, model RMSE, data vintage per source, COVID years excluded; every answer carries them.
- "Why profiles first?" The FAA service volume is stale for the big hubs (Denver ran at 1.96 times it); the profiles are measured rates. Found by checking the ratios, changed the same day, recorded in the v2 spec as Round 2.
- "What was pre-built?" The platform (chain, guard, ledger, evals) came from an earlier project; the airport data
  layer, the KPI and the prompts were built today.
- "Production?" ASPM access for measured capacity everywhere, Postgres for sessions and spend, scheduled refresh,
  calibration against realised project outcomes.
