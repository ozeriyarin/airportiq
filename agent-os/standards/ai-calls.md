# AI calls

- Every model call goes through Pydantic AI (`Agent` with `output_type`). Never import a vendor SDK outside `app/llm/models.py`.
- The answer model is a chain, in `config/agent.yaml` order: same vendor's cheaper model first, then another vendor. `build_chain` drops entries whose key is missing and logs them; with no key at all it fails at startup.
- Three retry layers, each with one job: the httpx transport retries 429/5xx/network per model with Retry-After or exponential backoff (`retry_attempts`, `retry_max_wait_s`); vendor SDK retries are off (`max_retries=0`); `FallbackModel` moves to the next model on `ModelAPIError` or a truncated reply. A timeout counts as a failed attempt and moves on.
- Output is always typed: `AnswerOut` for answers, `Screening` for the guard. A reply that fails validation is retried once with the error, then the turn fails loudly.
- The model never invents facts: every number or name comes from a tool result; `sources` names the tools used; `limitations` says what the data cannot tell.
- `Turn` records which model answered (`served_by`), which failed before it (`failed_attempts`), tokens, cost and latency. The API returns them; evals aggregate them.
- Prompts live in `app/agent/prompts.py` only. Any change to a prompt, the chain, `Screening`, `AnswerOut` or the guard threshold is committed together with a fresh `agent eval` report under `evals/results/`.
- Per-turn ceilings: `UsageLimits(request_limit, cost_limit)` from `config/agent.yaml`; a runaway tool loop stops with `cannot_answer`, not an exception.
