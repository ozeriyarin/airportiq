# Secrets and config

- Secrets come only from environment variables via `app.config.Settings` (pydantic-settings, `.env` for local dev). Names are listed in `.env.example`; values are never committed, printed or logged.
- Non-secret runtime configuration is `config/agent.yaml` (models, limits) and `config/prices.yaml`, validated by Pydantic at load. Both carry a version string that eval reports cite.
- A missing vendor key removes that vendor's models from the chain with a log line. A chain with no usable model fails at startup with the list of keys to set.
- `MODEL_MODE=test` runs the whole app offline on Pydantic AI's `TestModel`: no key, no spend, canned answers. CI and the demo use it.
- `ADMIN_TOKEN` guards `/api/stats` when set; leave it empty only on localhost.
- The database path (`DB_PATH`) is a file; on Render's free tier it is ephemeral and the README says so.
