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
from app.data.live import NasStatusClient
from app.data.opensky import OpenSkyClient
from app.data.profiles import load_profiles
from app.data.registry import AirportRegistry
from app.data.store import Store
from app.decide.guard import Guard, build_guard_model, offline_guard_model
from app.evals.cases import load_cases
from app.evals.report import render_markdown
from app.evals.runner import run_all
from app.llm.budget import Budget
from app.llm.models import answer_chain, build_chain, retrying_http_client
from app.scoring.config import load_scoring_config
from app.scoring.engine import Engine

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
cli = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger(__name__)
TEST_FLAG = typer.Option(False, "--test", help="offline TestModel: no key, no spend")
QUESTION = typer.Argument(None)
DOWN_OPT = typer.Option([], help="vendor prefix to drop from the chain, e.g. anthropic (outage simulation)")
NOTE_OPT = typer.Option([], help="free-text note recorded in the report")
MODEL_OPT = typer.Option(None, "--model", help="run the set on this single answer model (experiment), e.g. anthropic:claude-haiku-5-5")
CASES_OPT = typer.Option(None, help="case file; default evals/cases.yaml, or evals/smoke.yaml with --test")
ACCEPT_CASES_OPT = typer.Option(None, help="case file; default evals/accept/cases.yaml")
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
    registry = AirportRegistry.load() if (CONFIG_DIR / "airports.yaml").exists() else None
    snapshot_dir = snapshot_path(settings.snapshot_dir)
    store = Store.open_if_present(snapshot_dir)
    if store is None:
        log.warning("no snapshot at %s: scoring data unavailable until `agent ingest` runs", snapshot_dir)
    if settings.model_mode == "test":  # offline: live calls fail fast and degrade, never touch the network
        live_http = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(503, text="test mode")))
    else:
        live_http = retrying_http_client(attempts=config.models.retry_attempts, timeout_s=config.models.timeout_s, max_wait_s=config.models.retry_max_wait_s)
    profiles = load_profiles()
    engine = Engine(store, registry, load_scoring_config(), profiles) if store and registry else None
    deps = ToolContext(
        product_name=config.name, registry=registry, store=store, profiles=profiles, engine=engine,
        live=NasStatusClient(live_http, settings.faa_user_agent, cache_min=settings.live_cache_min),
        opensky=OpenSkyClient(live_http, settings.opensky_client_id, settings.opensky_client_secret, cache_min=settings.opensky_cache_min),
    )
    service = Service(build_agent(chain.model, cache=config.models.cache), Guard(guard_model), budget, config.limits, prices, deps)
    return App(settings, config, service, budget, chain.names, guard_name, store.summary() if store else None)


def snapshot_path(p: Path) -> Path:
    return p if p.is_absolute() else ROOT / p


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


@cli.command()
def accept(url: str, cases: Path | None = ACCEPT_CASES_OPT, timeout_s: float = 120.0) -> None:
    """Live acceptance pass against a deployed service: endpoints plus evals/accept/cases.yaml over HTTP; exit 0 pass / 1 fail."""
    from app.accept import ACCEPT_DIR, render, run_accept

    base = url.rstrip("/")

    async def run():
        http = retrying_http_client(attempts=3, timeout_s=timeout_s, max_wait_s=30, validate=False)
        async with http:
            return await run_accept(http, base, cases or ACCEPT_DIR / "cases.yaml")

    try:
        report = asyncio.run(run())
    except (httpx2.HTTPError, ValueError) as e:
        typer.echo(f"accept failed: {e}")
        raise typer.Exit(code=1) from e
    typer.echo(render(report))
    raise typer.Exit(code=report.exit_code)


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


SOURCE_OPT = typer.Option([], "--source", help="taf | ontime | t100 (repeatable); default: all three")
RAW_DIR_OPT = typer.Option(ROOT / "data" / "raw", help="where raw downloads live (gitignored)")


@cli.command()
def ingest(
    source: list[str] = SOURCE_OPT, raw: Path = RAW_DIR_OPT, out: Path | None = None,
    years: str = typer.Option("2023-2025", help="On-Time year range, inclusive"), long_haul_miles: int = 3000,
) -> None:
    """Fetch the public sources, aggregate them with DuckDB and write data/snapshots (run once, commit)."""
    from app.data.ingest import SOURCES
    from app.data.ingest import ingest as run_ingest

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    settings, config = Settings(), load_agent_config()
    registry = AirportRegistry.load()
    out_dir = snapshot_path(out or settings.snapshot_dir)
    y0, y1 = (int(x) for x in years.split("-"))
    chosen = tuple(source) if source else SOURCES

    async def run():
        http = retrying_http_client(attempts=config.models.retry_attempts, timeout_s=300, max_wait_s=config.models.retry_max_wait_s)
        async with http:
            return await run_ingest(registry, http, raw, out_dir, user_agent=settings.faa_user_agent, years=(y0, y1),
                                    long_haul_miles=long_haul_miles, sources=chosen)

    m = asyncio.run(run())
    for name, sm in m.sources.items():
        typer.echo(f"{name:7s} {sm.period:22s} {sm.rows:>8d} rows  {sm.method[:60]}")
    typer.echo(f"snapshot written to {out_dir} ({m.airports} airports, registry {m.registry_version})")


@cli.command()
def score(airport: str, test: bool = TEST_FLAG) -> None:
    """Print the Capacity Pressure Score breakdown for one airport (no model call)."""
    app = compose(model_mode="test" if test else None)
    deps = app.service.deps
    if deps.engine is None or deps.registry is None:
        typer.echo("no snapshot loaded; run `agent ingest`")
        raise typer.Exit(code=1)
    hit = deps.registry.find(airport)
    if hit is None or isinstance(hit, list):
        typer.echo(f"unknown or ambiguous airport {airport!r}")
        raise typer.Exit(code=1)
    s = deps.engine.score(hit.id)
    cap = s.capacity
    typer.echo(f"{s.airport} {s.name} ({s.city}, {s.state}; {s.division}; hub {s.hub_class})")
    typer.echo(f"CPS {s.cps}  lenses {s.lenses}")
    typer.echo(f"capacity {cap.annual_operations:,} ops/yr from {cap.source}" + (f" (RMSE {cap.uncertainty_operations:,})" if cap.uncertainty_operations else "")
               + (f"; FAA profile {cap.profile_year}: {cap.profile_hourly_rate}/h -> {cap.profile_annual_operations:,}" if cap.profile_hourly_rate else ""))
    for c in s.components:
        band = f" band {c.low}..{c.high} trend {c.trend}" if c.low is not None else ""
        typer.echo(f"  {c.name:12s} value {c.value}  pct {c.percentile}{band}  {c.detail}")
    for d in s.contributions:
        typer.echo(f"  contribution {d['component']:12s} {d['contribution']}")
    for lim in s.limitations:
        typer.echo(f"  ! {lim}")


@cli.command()
def profiles(raw: Path = RAW_DIR_OPT, out: Path = CONFIG_DIR / "capacity_profiles.yaml") -> None:
    """Extract hourly capacity rates from the FAA Airport Capacity Profile PDFs into config (run once, commit)."""
    from app.data.profiles import ProfilesFile, dump_profiles, extract_dir

    base = "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/profiles"
    rates = extract_dir(raw / "profiles", base)
    dump_profiles(ProfilesFile(version="1.0.0", generated=date.today().isoformat(), source=base, profiles=rates), out)
    for r in rates:
        v, mg, i = r.primary("visual"), r.primary("marginal"), r.primary("instrument")
        fmt = lambda c: f"{c.low}-{c.high}" if c else "n/a"  # noqa: E731
        typer.echo(f"{r.airport} {r.year}: visual {fmt(v)}  marginal {fmt(mg)}  instrument {fmt(i)}")
    typer.echo(f"{len(rates)} profiles written to {out}")


@cli.command()
def registry(raw: Path = ROOT / "data" / "raw", out: Path = CONFIG_DIR / "airports.yaml") -> None:
    """Generate config/airports.yaml from the raw TAF zip, FAA enplanement xlsx and OurAirports CSVs (run once, commit)."""
    from app.data.areas import load_areas
    from app.data.enplanements import read_enplanements
    from app.data.ourairports import read_airports as oa_airports
    from app.data.ourairports import read_runways
    from app.data.registry import build_registry, dump_registry, load_aliases
    from app.data.taf import TafArchive

    taf_zip = next(raw.glob("taf/APO100_TAF_Final_*.zip"))
    enp_xlsx = next(raw.glob("faa/*enplanements*.xlsx"))
    airports_csv, runways_csv = raw / "ourairports" / "airports.csv", raw / "ourairports" / "runways.csv"
    data = build_registry(
        TafArchive(taf_zip).airports(), read_enplanements(enp_xlsx.read_bytes()), oa_airports(airports_csv.read_bytes()),
        read_runways(runways_csv.read_bytes()), load_areas(), load_aliases(),
        generated=date.today().isoformat(),
        sources={"taf": taf_zip.name, "faa_enplanements": enp_xlsx.name, "ourairports": "airports.csv + runways.csv"},
    )
    dump_registry(data, out)
    by_class = {c: sum(a.hub_class == c for a in data.airports) for c in ("L", "M", "S")}
    typer.echo(f"{len(data.airports)} airports written to {out}: {by_class}; without service volume: "
               f"{sum(a.service_volume == 0 for a in data.airports)}; without runways: {sum(a.runways == 0 for a in data.airports)}")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; reports use UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    cli()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["CONFIG_DIR", "cli", "compose", "main"]
