"""Acceptance criteria of agent-os/specs/2026-11-01-v4-deploy, one test per criterion, all offline."""

from __future__ import annotations

import re

import pytest
import yaml

from app.config import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
DEMO = (ROOT / "docs" / "demo-script.md").read_text(encoding="utf-8")
URL = "https://airportiq.onrender.com"


def test_criterion_1_render_blueprint_is_the_deployed_shape():
    svc = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"][0]
    assert svc["name"] == "airportiq" and svc["healthCheckPath"] == "/health" and "uv sync --frozen --no-dev" in svc["buildCommand"]
    secrets = {e["key"] for e in svc["envVars"] if e.get("sync") is False}
    assert secrets == {"ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"}
    assert next(e for e in svc["envVars"] if e["key"] == "BUDGET_USD")["value"] == "10"


def test_criterion_2_readme_has_the_live_url_and_a_dated_verify_record():
    assert URL in README
    m = re.search(r"Verified (\d{4}-\d{2}-\d{2}) at " + re.escape(URL), README)
    assert m and m.group(1) >= "2026-11-01"
    assert "served by claude-sonnet-5-5" in README and "typesafe:jev-latest" in README and "144 airports" in README
    for fact in ("sleeps after 15 minutes", "ephemeral"):
        assert fact in README


def test_criterion_3_spend_limits_with_dates():
    if "date recorded at closeout" in README:
        pytest.skip("provider-console cap dates not yet supplied by the owner")
    assert "BUDGET_USD" in README and "10 USD per month" in README and "verified 2026-11-01" in README
    assert re.search(r"Provider consoles:.*(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})", README), "provider caps need a date"


def test_criterion_4_assumptions_table_covers_the_required_rows():
    for topic in ("Profitability", "Weights and thresholds", "Capacity", "Delays", "T-100 vintage", "Growth", "Universe", "Sessions and spend ledger"):
        assert f"| {topic} |" in README, topic
    assert "92,932" in README and "2020–2021" in README


def test_criterion_5_design_names_the_three_topics_and_docs_carry_no_pending_lines():
    for section in ("## Scoring methodology", "## Key tradeoffs", "## Where AI is used"):
        assert section in DESIGN, section
    roadmap = (ROOT / "agent-os" / "product" / "roadmap.md").read_text(encoding="utf-8")
    for doc, text in (("README", README), ("DESIGN", DESIGN), ("roadmap", roadmap), ("demo", DEMO)):
        assert not re.search(r"still to come|TODO|TBD|\bpending\b|PLACEHOLDER", text), doc


def test_criterion_6_demo_script_numbers_match_the_readme():
    for fact in ("393,000", "402,400", "87,988", "31.0%", "92,932", "144"):
        assert fact in DEMO and fact in README, fact
