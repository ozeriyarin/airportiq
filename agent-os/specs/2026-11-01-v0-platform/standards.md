# Standards for v0 platform

Applied in full (see `agent-os/standards/`): ai-calls, guardrails, budget, evals, testing, secrets-and-config,
deployment, python-style. Key points enforced by the criterion tests:

- Every model call through Pydantic AI; vendor SDK imports only in `app/llm/models.py`; three retry layers.
- Regex → intro → reserve → Jev/Haiku screening with the previous question as context → fixed refusal strings.
- Ledger reserve/settle/release with a monthly cap; per-turn `UsageLimits`; per-IP and global rate limits.
- Eval runner with exit codes, `--down`, `--model`, grounding check, cache share and latency percentiles.
- Offline tests only; fakes for every model and transport; spec-coverage enforcer per spec folder.
