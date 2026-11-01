"""Shared fixtures. Every test is offline: models are FunctionModel/TestModel, the ledger is a temp SQLite file."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.core import Service, build_agent
from app.agent.tools import ToolContext
from app.config import ROOT, load_agent_config, load_prices
from app.decide.guard import Guard
from app.llm.budget import Budget
from tests.fakes import answer_model, screening_model


@pytest.fixture
def config():
    return load_agent_config(ROOT / "config" / "agent.yaml")


@pytest.fixture
def prices():
    return load_prices(ROOT / "config" / "prices.yaml")


@pytest.fixture
def budget(tmp_path: Path) -> Budget:
    return Budget(tmp_path / "ledger.db", cap_usd=1.0)


@pytest.fixture
def service(config, prices, budget) -> Service:
    """A Service whose guard says in_scope and whose model answers 'ok' without tools."""
    return Service(
        build_agent(answer_model("ok")), Guard(screening_model()), budget, config.limits, prices,
        ToolContext(product_name="test"),
    )
