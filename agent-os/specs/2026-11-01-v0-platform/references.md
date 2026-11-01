# References for v0 platform

## hubrisk (private, `C:\ai-projects\hubrisk`)

- **Location:** `src/app/{llm,decide,agent,api,evals}`, `tests/`, `config/agent.yaml`, `render.yaml`.
- **Relevance:** the same platform after ten shipped versions; v0 is a domain-free copy of it.
- **Key patterns borrowed:** `FallbackModel(fallback_on=[ModelAPIError, httpx2.HTTPError, truncated])`, Jev →
  Haiku guard with `unsure_below`, SQLite ledger with `BEGIN IMMEDIATE`, `Conversation.last_question` as guard
  context, `intro_reply` anchored pattern, grounding tolerances 0.051 / 0.0051, `agent verify` record.

## Pydantic AI 2.63 docs

- `FallbackModel`, `UsageLimits`, `FunctionModel` / `TestModel`, `AsyncHTTPX2TenacityTransport`.
