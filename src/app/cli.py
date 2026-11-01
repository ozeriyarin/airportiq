"""CLI: `agent serve`, `agent chat`, `agent eval`, `agent verify`. Composition root for the whole app."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx2
import typer
from dotenv import load_dotenv

from app.agent import prompts
from app.agent.core import Conversation, Service, build_agent
from app.agent.tools import ToolContext
from app.api.app import create_app
from app.api.ratelimit import RateLimiter
from app.api.sessions import SessionStore
from app.config import CONFIG_DIR, ROOT, AgentConfig, Settings, load_agent_config, load_prices
from app.decide.guard import Guard, build_guard_model, offline_guard_model
from app.evals.cases import load_cases
from app.evals.report import render_markdown
from app.evals.runner import run_all
from app.llm.budget import Budget
from app.llm.models import answer_chain, build_chain, retrying_http_client

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
cli = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger(__name__)
TEST_FLAG = typer.Option(False, "--test", help="offline TestModel: no key, no spend")
QUESTION = typer.Argument(None)
DOWN_OPT = typer.Option([], help="vendor prefix to drop from the chain, e.g. anthropic (outage simulation)")
NOTE_OPT = typer.Option([], help="free-text note recorded in the report")
MODEL_OPT = typer.Option(None, "--model", help="run the set on this single answer model (experiment), e.g. anthropic:claude-haiku-5-5")
CASES_OPT = typer.Option(None, help="case file; default evals/cases.yaml, or evals/smoke.yaml with --test")
VERIFY_QUESTION = "Which airports in New England are strong candidates for terminal expansion?"


@dataclass
class App:
    settings: Settings
    config: AgentConfig
    service: Service
    budget: Budget
    model_names: list[str]
    guard_name: str
    data: dict | None = None  # snapshot coverage for /health; None until v1 loads data


def compose(*, model_mode: str | None = None, down: list[str] | None = None, only: str | None = None) -> App:
    """Build everything from .env + config. `down` drops models from the chain to simulate a vendor outage."""
    load_dotenv()
    settings = Settings()
    if model_mode:
        settings.model_mode = model_mode
    config = load_agent_config()
    prices = load_prices()
    chain = build_chain(answer_chain(config.models.chain, down, only), settings, config.models)
    if settings.model_mode == "test":
        guard_model = offline_guard_model()
        guard_name = "test"
    else:
        decision = None
        if settings.key_for(config.models.guard_decision):
            decision = build_chain([config.models.guard_decision], settings, config.models).model
        fallback = build_chain([config.models.guard_fallback], settings, config.models).model
        guard_model = build_guard_model(decision, fallback, config.models.guard_confidence)
        guard_name = (f"{config.models.guard_decision} → " if decision else "") + config.models.guard_fallback
    budget = Budget(settings.db_path, settings.budget_usd)
    deps = ToolContext(product_name=config.name)
    service = Service(build_agent(chain.model, cache=config.models.cache), Guard(guard_model), budget, config.limits, prices, deps)
    return App(settings, config, service, budget, chain.names, guard_name)


def default_cases(test: bool) -> Path:
    """The live set asserts facts in the wording; the smoke set only statuses and tools (test-mode answers are canned)."""
    return ROOT / "evals" / ("smoke.yaml" if test else "cases.yaml")


@cli.command()
def serve(host: str = "0.0.0.0", port: int | None = None, test: bool = TEST_FLAG) -> None:
    """Run the web chat and JSON API."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = compose(model_mode="test" if test else None)
    web = create_app(
        app.service,
        SessionStore(max_turns=app.config.limits.max_turns, ttl_s=app.config.limits.session_ttl_s),
        app.budget,
        model_names=app.model_names,
        guard_name=app.guard_name,
        limiter=RateLimiter(per_ip_per_hour=app.config.limits.per_ip_per_hour, global_per_day=app.config.limits.global_per_day),
        admin_token=app.settings.admin_token,
        data=app.data,
    )
    uvicorn.run(web, host=host, port=port or app.settings.port)


@cli.command()
def chat(question: list[str] | None = QUESTION, test: bool = TEST_FLAG) -> None:
    """One question, or an interactive loop when none is given."""
    app = compose(model_mode="test" if test else None)
    conv = Conversation(max_turns=app.config.limits.max_turns)

    async def one(q: str) -> None:
        turn = await app.service.ask(conv, q)
        meta = [turn.status, turn.served_by or turn.guardrail or "", f"{turn.cost_usd:.4f} USD", f"{turn.latency_ms} ms"]
        if turn.failed_attempts:
            meta.append("fallback after " + ", ".join(turn.failed_attempts))
        typer.echo(turn.answer)
        typer.secho(" · ".join(m for m in meta if m), fg="bright_black")

    if question:
        asyncio.run(one(" ".join(question)))
        return
    typer.echo("Interactive chat; empty line to quit.")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        asyncio.run(one(q))


@cli.command("eval")
def eval_cmd(
    cases: Path | None = CASES_OPT,
    repeat: int = typer.Option(1, min=1),
    out: Path = ROOT / "evals" / "results",
    tag: str = "latest",
    test: bool = TEST_FLAG,
    down: list[str] = DOWN_OPT,
    model: str | None = MODEL_OPT,
    note: list[str] = NOTE_OPT,
) -> None:
    """Run evals/cases.yaml, write evals/results/<tag>.{json,md}, exit 0 pass / 1 fail / 2 flaky."""
    app = compose(model_mode="test" if test else None, down=down, only=model)
    loaded = load_cases(cases or default_cases(test))
    notes = list(note) + ([f"simulated outage: {', '.join(down)}"] if down else []) + ([f"single model: {model}"] if model else [])
    report = asyncio.run(
        run_all(
            app.service, loaded, repeat=repeat, models=app.model_names, guard=app.guard_name,
            config_version=app.config.version, max_turns=app.config.limits.max_turns, notes=notes,
            prompt_version=prompts.PROMPT_VERSION,
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{tag}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (out / f"{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    typer.echo(render_markdown(report))
    raise typer.Exit(code=report.exit_code)


@cli.command()
def verify(url: str, timeout_s: float = 90.0) -> None:
    """Check a deployed service: GET /health, one POST /api/chat; print a dated record; exit 1 on any failure."""
    base = url.rstrip("/")

    async def run() -> list[str]:
        http = retrying_http_client(attempts=4, timeout_s=timeout_s, max_wait_s=30)
        async with http:
            health = (await http.get(f"{base}/health")).json()
            chat = (await http.post(f"{base}/api/chat", json={"message": VERIFY_QUESTION})).json()
        return check_health(health) + check_chat(chat) + [verification_record(base, health, chat)]

    try:
        lines = asyncio.run(run())
    except (httpx2.HTTPError, ValueError) as e:
        typer.echo(f"verify failed: {e}")
        raise typer.Exit(code=1) from e
    problems, record = lines[:-1], lines[-1]
    typer.echo(record)
    if problems:
        typer.echo("verify failed:\n- " + "\n- ".join(problems))
        raise typer.Exit(code=1)


def check_health(payload: dict) -> list[str]:
    problems = []
    if payload.get("status") != "ok":
        problems.append(f"health status is {payload.get('status')!r}")
    models = payload.get("models") or []
    if not models or models == ["test"]:
        problems.append(f"model chain is {models!r}, expected real models")
    return problems


def check_chat(payload: dict) -> list[str]:
    if payload.get("status") != "answered":
        return [f"chat status is {payload.get('status')!r}: {str(payload.get('answer') or payload.get('detail'))[:120]}"]
    return []


def verification_record(base: str, health: dict, chat: dict) -> str:
    return "\n".join([
        f"Verified {date.today().isoformat()} at {base}",
        f"- /health: status {health.get('status')}, version {health.get('version')}, models {' -> '.join(health.get('models') or [])}, "
        f"guard {health.get('guard')}, data {health.get('data')}",
        f"- /api/chat: status {chat.get('status')}, served by {chat.get('served_by')}, tools {chat.get('tools_used')}, "
        f"{chat.get('latency_ms')} ms, {chat.get('cost_usd', 0):.4f} USD",
    ])


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; reports use UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    cli()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["CONFIG_DIR", "cli", "compose", "main"]
