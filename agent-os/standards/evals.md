# Evals

- Unit tests prove the code; evals measure the agent with real models. `evals/cases.yaml` is the set; `agent eval` is the runner; `evals/results/<tag>.{json,md}` is the committed evidence.
- Categories, each with at least three cases once the domain exists: `in_scope` (must answer, named tools must be called, key facts in `must_contain`), `off_topic` and `injection` (must refuse with the right status), `false_positive` (looks suspicious, must answer), `followup` (multi-turn via `prior_turns`).
- `--repeat N` runs each case N times: a case that passes some runs is *flaky* (exit 2), one that fails every run is *failed* (exit 1). A prompt or model change may not merge on exit 1.
- `--down <vendor>` drops a vendor from the chain to prove cross-vendor fallback end to end; the report records the simulated outage and which model served each run.
- Each report records models, guard, config version, cost and latency per run, so two reports can be compared by hand or diffed as JSON.
- Rule: any change to prompts, the chain, the guard threshold or the schemas is committed with the new report and a one-line comparison to the previous one in the commit message.
