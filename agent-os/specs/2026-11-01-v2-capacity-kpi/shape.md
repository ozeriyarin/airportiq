# v2 capacity KPI — Shaping Notes

## Scope

The Capacity Pressure Score engine, its config, the capacity precedence (service volume > profile > runway model),
percentile normalization, lenses, the eight tools and `agent score`.

## Decisions

- **Measured capacity for 140 airports** comes from the FAA annual service volume found in v1; the capacity
  profiles (31 airports) are the cross-check (SFO 393,000 vs 402,600, within 2.5%); the runway model covers the 4
  airports without a service volume and reports its RMSE (about 93,000 operations, n = 137) as their uncertainty.
- **Percentile normalization** instead of min–max: robust to DEN/ATL outliers and interpretable in an answer
  ("higher than 87% of hub airports").
- **Delay and growth are composite percentiles** (two sub-metrics each), so their `value` is the percentile and
  the sub-metrics live in `detail`. Utilization, load factor and long-haul share keep a physical `value`.
- **Missing components renormalize weights** rather than scoring zero, and the limitation says so.
- **Lenses** are config: expansion = CPS, congestion, unmet_demand, long_haul.
- **Drivers are typed** (component, direction, percentile, magnitude); the model narrates, never computes.

## Context

- **References:** hubrisk `app/scoring` (config → pure engine → cached scores → thin tools).
- **Product alignment:** mission KPI definition; the four brief questions map to the four lenses.

## Standards Applied

- scoring, ai-calls, testing, python-style.
