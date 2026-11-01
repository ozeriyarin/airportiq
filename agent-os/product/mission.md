# Product Mission — airportiq

## Problem

A firm invests in airport modernization projects in the US. Its analysts must pick the airports where added
capacity (runways, gates, terminals) will be absorbed by real traffic, because that is where a modernization pays
back. Today that judgement is manual: pulling FAA forecasts, BTS traffic tables and delay statistics airport by
airport, eyeballing them, and arguing about what "congested" or "unmet demand" means. The result is slow,
inconsistent and hard to defend in an investment committee.

## Target Users

Investment analysts at the firm who screen US airports for modernization opportunities, and the partners they
report to. They ask in plain language ("which New England airports are strong candidates for terminal
expansion?", "compare LA and Santa Ana congestion", "what share of Anchorage's flights are long haul?", "what is
the unmet demand at SFO and why?") and need an answer they can defend: a number, how it was computed, how sure we
are, and what the data cannot say.

## Solution

A conversational agent over a **deterministic Capacity Pressure Score (CPS)**:

- **KPI: Capacity Pressure Score, 0–100 per airport**, a weighted sum of five normalized components computed from
  public FAA and BTS data: runway utilization (operations against capacity), ground delay (late departures and
  excess taxi-out), load factor (passengers against seats), demand growth (FAA forecast and recent actuals) and
  long-haul share (segments of 3,000 statute miles or more). Weights, thresholds and definitions live in a
  versioned YAML, so a ranking is reproducible and auditable. Each component is also answerable on its own, so
  "congestion", "unmet demand", "terminal expansion" and "long haul" are lenses over the same engine.
- **Capacity is measured where the FAA measured it, modelled elsewhere, and the answer says which.** For 33 large
  airports the hourly capacity comes from the FAA Airport Capacity Profiles. For the other hub airports a runway
  model calibrated against those 33 estimates it, and the fit error is reported as uncertainty.
- **The LLM never produces a number.** It interprets the question, calls typed tools and explains the result.
  Every figure comes from code over the data; the LLM-to-code contract is an enforced Pydantic schema (`AnswerOut`:
  status, answer, sources, limitations).
- **Regions are data, not guesses.** Airports carry state, US Census region and division in `config/airports.yaml`;
  "New England" is a filter. Names resolve through registry aliases ("LA" → LAX, "Santa Ana" → SNA).
- **Now vs history.** Frozen snapshots (FAA TAF, BTS T-100, BTS On-Time, runway inventory) give the score; the FAA
  NAS status feed answers "what is happening at X right now" and is shown beside the score, never blended into it.
- **Production-shaped platform:** model chain with cross-vendor fallback, typed guardrail, spend budget, rate
  limits, eval runner with a pass/fail gate, offline tests, CI, Render deploy.
- **Spec-driven.** One Agent OS spec per version; every acceptance criterion maps to a named test.

## Scope & Assumptions

**In scope:** US airports classified by the FAA as large, medium or small hubs (about 130); five capacity
components from public data; ranking, comparison, single-airport stats and "why" explanations; conversational
follow-ups within a session; a small eval set; a chat page over a JSON API; Render deployment.

**Out of scope:** financial return, construction cost, financing and revenue modelling (the score is a proxy for
where capacity would be absorbed, not a profitability estimate); non-hub and non-US airports; airline-level
analysis; terminal and gate counts (no public source); multi-user auth; persistent sessions; streaming.

**Assumptions and uncertainty:** modelled capacity carries the calibration error of a runway-count model; FAA
profile rates are dated 2014–2019; BTS On-Time covers domestic reporting carriers only, so delay figures miss
international and small operators; T-100 is downloaded once by hand and frozen at that date; forecast growth is
the FAA's, not ours; 2020–2021 are flagged as COVID years and excluded from trends. Every answer carries
`limitations` and names the data vintage.
