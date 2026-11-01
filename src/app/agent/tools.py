"""Tools the model may call. Every tool is deterministic code over the data; the model only chooses and explains.

Tools never raise: an unknown airport, area or lens comes back as `NotFound` with the valid values, an ambiguous
name as `Ambiguous`, and missing data as `Unavailable`. Every scored result carries `scoring_version` and
`data_through`, and the capacity source (measured or modelled).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app import __version__
from app.agent.prompts import SCOPE_DESCRIPTION
from app.data.live import LiveStatus, NasStatusClient
from app.data.profiles import ProfilesFile
from app.data.registry import Airport, AirportRegistry
from app.data.store import Store
from app.scoring.engine import Engine
from app.scoring.models import AirportProfile, AirportScore, Comparison, Ranking, TrafficMix, UnmetDemand


@dataclass
class ToolContext:
    """Everything tools need. Built once at startup by `cli.compose`, injected per run as `deps`."""

    product_name: str
    registry: AirportRegistry | None = None
    store: Store | None = None  # None when no snapshot is present; scored tools then return Unavailable
    live: NasStatusClient | None = None
    profiles: ProfilesFile | None = None
    engine: Engine | None = None

    @property
    def data_facts(self) -> str:
        """Facts injected per run so the prompt can never be stale relative to the snapshot and the config."""
        if self.registry is None:
            return "Airport registry is not loaded: only `about` works."
        lines = [
            f"Airports: {len(self.registry.all)} FAA hub airports (large, medium, small). Area filters accepted: regions "
            f"{', '.join(self.registry.areas.regions())}; divisions such as {', '.join(list(self.registry.areas.divisions)[:3])}; "
            f"informal areas such as west coast; or a state code.",
        ]
        if self.engine is None:
            lines.append("Scoring data is NOT loaded: capacity, delay, demand and traffic-mix figures are unavailable; say so.")
        else:
            cfg = self.engine.config
            cov = "; ".join(f"{c.source} {c.first}..{c.last}" for c in self.store.coverage()) if self.store else ""
            lines.append(f"Snapshot: {cov}. Scoring version {cfg.version}. COVID years {cfg.covid_years} are excluded from trends.")
            lines.append("Lenses for rank_airports/compare_airports: " + "; ".join(f"{n} = {lens.label}" for n, lens in cfg.lenses.items()) + ".")
            lines.append("Component weights: " + ", ".join(f"{n} {c.weight:g}" for n, c in cfg.components.items()) + f". Long haul = {cfg.long_haul_miles}+ miles.")
        return "\n".join(lines)


class About(BaseModel):
    product: str
    version: str
    scope: str


class NotFound(BaseModel):
    kind: str = Field(description="what was not found: airport, area, lens or year")
    query: str
    valid: list[str]
    hint: str


class Ambiguous(BaseModel):
    kind: str = "airport"
    query: str
    candidates: list[str]
    hint: str = "ask which one, or use the airport id"


class Unavailable(BaseModel):
    reason: str


class AirportSummary(BaseModel):
    id: str
    name: str
    city: str
    state: str
    division: str
    hub_class: str


class AirportList(BaseModel):
    area: str | None
    airports: list[AirportSummary]
    areas: list[str] = Field(description="area names accepted besides state codes")
    lenses: list[str]
    registry_version: str
    data_through: dict[str, str]


NO_DATA = "scoring snapshot not loaded; run `agent ingest` to enable capacity, delay, demand and traffic-mix figures"


def about(ctx: RunContext[ToolContext]) -> About:
    """What this assistant is and what it covers. Call when the user asks what you can do."""
    return About(product=ctx.deps.product_name, version=__version__, scope=SCOPE_DESCRIPTION)


def resolve_airport(deps: ToolContext, query: str) -> Airport | NotFound | Ambiguous | Unavailable:
    if deps.registry is None:
        return Unavailable(reason="airport registry not loaded")
    hit = deps.registry.find(query)
    if hit is None:
        return NotFound(kind="airport", query=query, valid=[a.id for a in deps.registry.all][:40],
                        hint="FAA large, medium and small hub airports only; call list_airports with an area to see ids")
    if isinstance(hit, list):
        return Ambiguous(query=query, candidates=[f"{a.id} ({a.name}, {a.city} {a.state})" for a in hit[:8]])
    return hit


def _engine(deps: ToolContext) -> Engine | Unavailable:
    return deps.engine if deps.engine is not None else Unavailable(reason=NO_DATA)


def _lens(engine: Engine, lens: str) -> str | NotFound:
    key = lens.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"cps": "expansion", "terminal_expansion": "expansion", "capacity_pressure": "expansion", "congested": "congestion",
               "demand": "unmet_demand", "long_haul_share": "long_haul", "longhaul": "long_haul"}
    key = aliases.get(key, key)
    if key not in engine.config.lenses:
        return NotFound(kind="lens", query=lens, valid=engine.config.lens_names(), hint="expansion is the overall Capacity Pressure Score")
    return key


def _area(deps: ToolContext, area: str | None) -> str | None | NotFound:
    if not area or deps.registry is None:
        return None
    if deps.registry.in_area(area) is None:
        return NotFound(kind="area", query=area, valid=deps.registry.area_names(), hint="a Census region, division, informal area or state code")
    return area


def _list(deps: ToolContext, area: str | None) -> AirportList | NotFound | Unavailable:
    if deps.registry is None:
        return Unavailable(reason="airport registry not loaded")
    airports = deps.registry.all if not area else deps.registry.in_area(area)
    if airports is None:
        return NotFound(kind="area", query=area or "", valid=deps.registry.area_names(), hint="a Census region, division, informal area or state code")
    return AirportList(
        area=area, airports=[AirportSummary(id=a.id, name=a.name, city=a.city, state=a.state, division=a.division, hub_class=a.hub_class) for a in airports],
        areas=deps.registry.area_names(), lenses=deps.engine.config.lens_names() if deps.engine else [],
        registry_version=deps.registry.version, data_through=deps.engine.data_through() if deps.engine else {},
    )


def _rank(deps: ToolContext, lens: str, area: str | None, top: int) -> Ranking | NotFound | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    if isinstance(key := _lens(engine, lens), NotFound):
        return key
    if isinstance(a := _area(deps, area), NotFound):
        return a
    return engine.rank(key, a, top if 1 <= top <= 50 else 10)


def _compare(deps: ToolContext, airport_a: str, airport_b: str, lens: str) -> Comparison | NotFound | Ambiguous | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    a, b = resolve_airport(deps, airport_a), resolve_airport(deps, airport_b)
    if not isinstance(a, Airport):
        return a
    if not isinstance(b, Airport):
        return b
    if isinstance(key := _lens(engine, lens), NotFound):
        return key
    return engine.compare(a.id, b.id, key)


def _score(deps: ToolContext, airport: str) -> AirportScore | NotFound | Ambiguous | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    a = resolve_airport(deps, airport)
    return a if not isinstance(a, Airport) else engine.score(a.id)


def _profile(deps: ToolContext, airport: str) -> AirportProfile | NotFound | Ambiguous | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    a = resolve_airport(deps, airport)
    return a if not isinstance(a, Airport) else engine.profile(a.id)


def _mix(deps: ToolContext, airport: str, year: int | None) -> TrafficMix | NotFound | Ambiguous | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    a = resolve_airport(deps, airport)
    if not isinstance(a, Airport):
        return a
    years = engine.available_years(a.id)
    if not years:
        return Unavailable(reason=f"no T-100 traffic rows for {a.id} in the snapshot")
    if year is not None and year not in years:
        return NotFound(kind="year", query=str(year), valid=[str(y) for y in years], hint="years with T-100 data in the snapshot")
    mix = engine.traffic_mix(a.id, year)
    return mix if mix else Unavailable(reason=f"no traffic mix for {a.id}")


def _unmet(deps: ToolContext, airport: str) -> UnmetDemand | NotFound | Ambiguous | Unavailable:
    engine = _engine(deps)
    if isinstance(engine, Unavailable):
        return engine
    a = resolve_airport(deps, airport)
    return a if not isinstance(a, Airport) else engine.unmet_demand(a.id)


def list_airports(ctx: RunContext[ToolContext], area: str | None = None) -> AirportList | NotFound | Unavailable:
    """Airports in the registry, optionally filtered by area: a Census region (West), division (New England), informal area (west coast) or state code (CA)."""
    return _list(ctx.deps, area)


def rank_airports(ctx: RunContext[ToolContext], lens: str = "expansion", area: str | None = None, top: int = 10) -> Ranking | NotFound | Unavailable:
    """Rank airports by a lens: expansion (the Capacity Pressure Score, for terminal/runway expansion candidates), congestion, unmet_demand or long_haul; area filters (New England, West Coast, CA)."""
    return _rank(ctx.deps, lens, area, top)


def compare_airports(ctx: RunContext[ToolContext], airport_a: str, airport_b: str, lens: str = "congestion") -> Comparison | NotFound | Ambiguous | Unavailable:
    """Compare two airports component by component (utilization, delay, growth, load factor, long haul) with percentiles, the difference and which is higher; lens picks the headline score."""
    return _compare(ctx.deps, airport_a, airport_b, lens)


def airport_score(ctx: RunContext[ToolContext], airport: str) -> AirportScore | NotFound | Ambiguous | Unavailable:
    """Full Capacity Pressure Score breakdown for one airport: components with values, percentiles, year bands, trends, contributions, capacity source and limitations (why it scores the way it does)."""
    return _score(ctx.deps, airport)


def airport_profile(ctx: RunContext[ToolContext], airport: str) -> AirportProfile | NotFound | Ambiguous | Unavailable:
    """Facts about one airport: hub class, runways, FAA capacity (measured or modelled) with the profile cross-check, latest operations and enplanements, international enplanement share."""
    return _profile(ctx.deps, airport)


def traffic_mix(ctx: RunContext[ToolContext], airport: str, year: int | None = None) -> TrafficMix | NotFound | Ambiguous | Unavailable:
    """Share of long-haul (3,000+ mile), international and cargo departures and the load factor for one airport and year (latest year by default), with the denominators."""
    return _mix(ctx.deps, airport, year)


def unmet_demand(ctx: RunContext[ToolContext], airport: str) -> UnmetDemand | NotFound | Ambiguous | Unavailable:
    """Unmet demand lens for one airport: load factor, forecast growth and delay components with typed drivers, the utilization context and capacity; the explanation of 'why'."""
    return _unmet(ctx.deps, airport)


async def live_status(ctx: RunContext[ToolContext], airport: str) -> LiveStatus | NotFound | Ambiguous | Unavailable:
    """What is happening at an airport right now per the FAA NAS status feed: closures, ground stops, ground delay programs, arrival/departure delays. Separate from the frozen score."""
    a = resolve_airport(ctx.deps, airport)
    if not isinstance(a, Airport):
        return a
    if ctx.deps.live is None:
        return Unavailable(reason="live FAA status client not configured")
    return await ctx.deps.live.status(a.id)


def build_toolset() -> FunctionToolset[ToolContext]:
    toolset: FunctionToolset[ToolContext] = FunctionToolset()
    for fn in (about, list_airports, rank_airports, compare_airports, airport_score, airport_profile, traffic_mix, unmet_demand, live_status):
        toolset.add_function(fn)
    return toolset
