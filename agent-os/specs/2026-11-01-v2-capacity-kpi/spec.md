# Spec: v2 capacity KPI

Status: shipped 1.11.2026, commit `df86f19`, 16 criterion tests green.

## Goal

Turn the snapshots into the product's number: the **Capacity Pressure Score (CPS), 0–100 per airport**, from five
components with per-year bands and trends, measured or modelled capacity that is always labelled, and lenses for
the four kinds of question in the brief. Ship the deterministic tools the agent will call. The LLM never produces a
number; after this spec every figure an answer can contain exists as a typed tool result.

## Scope

**In:** `config/scoring.yaml`; `app/scoring` (config, models, pure component functions, capacity model and its
calibration, percentile normalization, cached `Engine`); tools `rank_airports`, `compare_airports`,
`airport_score`, `airport_profile`, `traffic_mix`, `unmet_demand`, `live_status`, `list_airports` registered in
the toolset; `ToolContext.engine`; `agent score <airport>` CLI; README methodology and DESIGN scoring sections with
the worked SFO example recomputed by a test.

**Out:** prompts, eval cases, the real eval report (v3); OpenSky; calibration against investment outcomes.

## Acceptance criteria

1. `config/scoring.yaml` validates: a version, five components with weights summing to 1.0, the long-haul miles (3,000), the year window, `annual_hours_equivalent`, the blend weights for visual/marginal/instrument rates, lenses that reference known components only; loading rejects an unknown component or a weight sum ≠ 1.
2. `hourly_capacity(profile)` blends the midpoints of the visual, marginal and instrument ranges with the configured weights; SFO 2019 yields a value between its instrument and visual midpoints.
3. Capacity precedence per airport is FAA annual service volume (TAF table, measured) > FAA profile blended rate x hours (measured hourly rate) > runway model; `fit_runway_model` fits the service volume on runway counts by least squares over the airports that have one and reports RMSE and n; a modelled airport carries `capacity_source=runway_model` with that RMSE, measured ones carry no model error, and a profiled airport also carries the profile rate and its annual cross-check. (Round 1 change: the TAF service volume, found during v1, replaced the profiles as the primary measured capacity; the profiles became the cross-check. **Round 2, superseded Round 1:** measuring the ratios showed the service volume is stale for the largest hubs (16 airports above 1.0 of it, DEN 1.96; profile-to-volume ratio median 1.23, range 0.62–2.96), so scoring 1.1.0 restores the original precedence: profile first (31 airports), service volume second, runway model last.)
4. `utilization(ops, hourly_capacity)` = ops / (hourly_capacity × annual_hours_equivalent) per year; the component carries per-year values, min, max and trend = last − first over the window.
5. `delay(ontime rows)` gives per-year delayed-15 share and excess taxi-out (mean − p10) and a combined value = the mean of the two percentile ranks; a year with fewer than the configured minimum departures is excluded and named in `limitations`.
6. `load_factor(t100 rows)` = passengers / seats per year over all departures; zero seats yields None, never a division error.
7. `growth(taf rows)` gives the forecast CAGR from the last actual fiscal year over 10 years and the actual CAGR over the recent window (default FY2019→latest actual); 2020–2021 are excluded from any fit and flagged.
8. `long_haul(t100 rows)` gives departures ≥ 3,000 mi / all departures and the international share separately, per year, with the denominators.
9. `percentile(values)` ranks within the universe 0–100 with ties sharing a rank; CPS = Σ weight × percentile and lens scores = the mean of their components' percentiles; scoring the same snapshot twice gives identical output.
10. `Engine.rank(lens, area|region|division|state, n)` orders airports by the lens descending with ties broken by id and area filters from the registry; `Engine.compare(a, b)` lists every component for both with the band and names the higher airport per component.
11. `unmet_demand(airport)` returns the lens score, its three components with values and percentiles, the utilization context, the capacity source, and a typed list of `drivers` (component name, direction, magnitude) sorted by contribution; no free text.
12. Tools never raise: an unknown airport, area or lens returns `NotFound` listing valid values (or the ambiguous candidates); a missing store returns `Unavailable` with a reason; every result carries `scoring_version`, `data_through` per source and `capacity_source`.
13. `rank_airports`, `compare_airports`, `airport_score`, `airport_profile`, `traffic_mix`, `unmet_demand`, `live_status` and `list_airports` are registered beside `about`, and `live_status` returns the NAS status with its `available` flag.
14. On the committed snapshot: ranking the `expansion` lens in New England returns BOS first; SFO's `unmet_demand` lens is above the universe median; ANC's long-haul share for the latest T-100 year equals the DuckDB count of ≥ 3,000 mi departures divided by all departures; SFO's capacity is the FAA service volume (393,000) with the 2019 profile as cross-check; the SFO worked example in DESIGN carries every component percentile and the CPS the engine computes.
15. `agent eval --test` on the committed smoke cases exits 0 with the tools registered, and `agent score SFO` prints the components, CPS, capacity source and band.
16. README documents every component, weight, threshold and the capacity model with the fit RMSE, and the documented values match `scoring.yaml` and the committed profiles.

## Design

**Components** (per airport, per year in the window, default CY2023–2025; TAF by fiscal year):

| component | definition | source | weight |
|---|---|---|---|
| utilization | annual operations / (hourly capacity × 4,000 hours-equivalent) | TAF ops, FAA profile or runway model | 0.30 |
| delay | mean of percentile(delayed ≥ 15 min share) and percentile(mean taxi-out − p10 taxi-out) | BTS On-Time | 0.25 |
| growth | mean of percentile(TAF forecast 10-year enplanement CAGR) and percentile(actual CAGR FY2019→latest) | TAF | 0.20 |
| load_factor | passengers / seats | T-100 | 0.15 |
| long_haul | departures ≥ 3,000 statute miles / departures (international share reported beside) | T-100 | 0.10 |

`annual_hours_equivalent = 4000` approximates the FAA annual service volume rule of thumb (hourly capacity × ~4,000
usable hours a year); stated as an assumption. The blended hourly rate uses visual 0.7 / marginal 0.2 / instrument
0.1 (clear weather dominates US hub hours); stated as an assumption. Weights were chosen before measuring, as the
investment reading of the brief (congestion first, growth second, mix last); the README says they are not
calibrated to outcomes and the config version makes any change auditable.

**Normalization:** percentile rank of the latest-year value within the registry universe, so a component reads as
"higher than N% of hub airports". CPS = Σ weight × percentile. **Lenses:** `congestion = utilization, delay`;
`unmet_demand = load_factor, growth, delay`; `expansion = CPS`; `long_haul = long_haul`.

**Capacity model:** hourly = a + b × runways + c × runways_6000ft, least squares over the ~33 profiled airports'
blended rates; the fit RMSE is the uncertainty of every modelled capacity and is printed in README. Modelled and
measured airports are never mixed without the label.

**Uncertainty:** per-year component values over the window with min and max; trend = last − first; the model
RMSE; `data_through` per source; COVID exclusions. The engine never returns a bare value.

**Tools** (`app/agent/tools.py`) are thin: resolve names through the registry, call the engine or the live client,
return typed models. `NotFound(kind, query, valid)`, `Ambiguous(candidates)` and `Unavailable(reason)` are return
values. `unmet_demand` returns typed drivers; the model narrates them.

**Worked example (SFO)** in DESIGN: each component value, its percentile, weight and contribution, the capacity
source and rate, the CPS, recomputed by `test_criterion_14_snapshot_facts`.

## Tasks

1. Save spec documentation.
2. `config/scoring.yaml`, `app/scoring/config.py`, `app/scoring/models.py`.
3. `app/scoring/capacity.py` (blend, fit, model), `app/scoring/components.py`, `app/scoring/engine.py` with table-driven tests on synthetic rows.
4. Tools, `ToolContext.engine`, `compose` wiring, `agent score`.
5. `tests/test_v2_capacity_kpi.py`, snapshot facts, worked example.
6. README methodology, DESIGN scoring + worked example, roadmap; `ruff`, `pytest`, `agent eval --test --tag ci-smoke`; commit, push.
