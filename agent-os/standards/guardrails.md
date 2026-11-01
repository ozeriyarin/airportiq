# Guardrails

- Order: deterministic input checks (empty, too long, control characters, injection regexes) → decision model → answer model. The cheapest layer that can decide, decides.
- The decision model is TypeSafe Jev (`typesafe:jev-latest`) when `TYPESAFE_API_KEY` is set: typed questions (`Screening` fields), calibrated per-field confidence read from `provider_details["confidence"]`. Below `guard_confidence` or on any API error, `FallbackModel` sends the same question to Claude Haiku. Without a Jev key, Haiku screens alone.
- Policy lives in code: the model returns `in_scope` and `injection`; `Guard.screen` maps them to a label; `Service.ask` maps the label to a fixed refusal string. The model never writes refusal text.
- A refusal never reaches the answer model and never spends from the budget (the reservation is released).
- User text is data: the guard instructions say so, the answer instructions say so, and eval category `injection` proves it on every run. Category `false_positive` proves ordinary questions that contain words like "system" or "ignore" still pass.
- Logs record the guard decision and model per session prefix; the API response records `guardrail` only as the deciding layer's name, never the reasoning.
