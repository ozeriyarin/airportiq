# Scoring

- The KPI is the **Capacity Pressure Score (CPS), 0–100 per airport**, computed by `app/scoring` from the snapshots.
  No LLM code path produces, rounds or adjusts a number.
- Five components, each a pure function over typed rows: `utilization` (annual operations / annual capacity),
  `delay` (share of departures delayed ≥ 15 min and excess taxi-out over the airport's own 10th percentile),
  `load_factor` (passengers / seats), `growth` (FAA forecast 10-year enplanement CAGR and actual CAGR over the
  recent window) and `long_haul` (departures ≥ 3,000 statute miles / departures; international share beside it).
- Normalization is the **percentile rank within the registry universe** (0–100) per component, so a value reads as
  "higher than N% of hub airports". CPS = Σ weight × percentile. Weights, thresholds, the long-haul distance, the
  capacity model parameters and the year window live in `config/scoring.yaml` with a `version`; every result cites it.
- Lenses are named groups in the config, like hubrisk's hazard groups: `congestion = utilization + delay`,
  `unmet_demand = load_factor + growth + delay`, `expansion = CPS`. A question picks a lens; the engine ranks by it.
- Capacity per airport is **measured** (FAA profile: blended hourly rate × `annual_hours_equivalent`) or **modelled**
  (runway model fitted on the profiled airports). Every capacity figure carries `capacity_source` (`faa_profile` |
  `model`) and, for the model, the fit RMSE as its uncertainty. The answer must say which.
- Every component ships with its uncertainty: per-year values over the covered years, min, max, and a trend (last
  year minus first year of the window). Never return a bare mean. `data_through` per source travels with the result.
- Rankings are stable: ties break by airport id. Same input, same output; the engine is pure and table-tested.
- Tools return Pydantic models (`AirportScore`, `Comparison`, `TrafficMix`, `LiveStatus`), never dicts; the model
  sees names, numbers and units it must quote verbatim and may not combine.
- Percent questions name the year and the denominator ("of 41,230 departures in CY2025").
- Live status ("right now") is a separate signal; it is reported next to the score, never blended into it.
- Thresholds and weights are stated assumptions chosen so each component separates airports on the snapshot; they
  are not calibrated to investment outcomes, and the README says so.
