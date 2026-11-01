"""Acceptance criteria of agent-os/specs/2026-11-01-v3-agent, one test per criterion, all offline."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli as cli_module
from app.agent import prompts
from app.agent.tools import build_toolset
from app.config import ROOT
from app.evals.cases import load_cases

BRIEF_TOOLS = {"rank_airports", "compare_airports", "traffic_mix", "unmet_demand"}


def _report(tag: str) -> dict:
    return json.loads((ROOT / "evals" / "results" / f"{tag}.json").read_text(encoding="utf-8"))


def test_criterion_1_prompt_names_every_tool_and_the_rules():
    names = set(build_toolset().tools)
    for n in names:
        assert f"- {n}:" in prompts.TOOL_GUIDE, n
    text = prompts.INSTRUCTIONS
    flat = " ".join(text.split())
    for phrase in ("Never add, subtract, average", "lens", "denominator", "service volume", "Ambiguous", "percentile", "never multiply"):
        assert phrase in flat, phrase
    assert re.fullmatch(r"\d+\.\d+\.\d+", prompts.PROMPT_VERSION) and prompts.PROMPT_VERSION >= "0.2.0"


def test_criterion_2_brief_questions_are_pinned_with_engine_facts_and_tools():
    cases = {c.id: c for c in load_cases(ROOT / "evals" / "cases.yaml")}
    for q in prompts.EXAMPLE_QUESTIONS:
        assert any(c.question == q for c in cases.values()), q
    assert "BOS" in cases["brief-1-new-england-expansion"].must_contain and cases["brief-1-new-england-expansion"].tools == ["rank_airports"]
    assert set(cases["brief-2-lax-vs-sna-congestion"].must_contain) == {"LAX", "SNA"} and cases["brief-2-lax-vs-sna-congestion"].tools == ["compare_airports"]
    assert "31.0" in cases["brief-3-anc-long-haul"].must_contain and cases["brief-3-anc-long-haul"].tools == ["traffic_mix"]
    assert cases["brief-4-sfo-unmet-demand"].tools == ["unmet_demand"] and "profile" in cases["sfo-capacity-source"].must_contain


def test_criterion_3_every_category_has_three_cases_and_followups_use_prior_turns():
    cases = load_cases(ROOT / "evals" / "cases.yaml")
    assert len(cases) >= 18
    by_cat: dict[str, list] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)
    for cat in ("off_topic", "injection", "false_positive", "followup"):
        assert len(by_cat[cat]) >= 3, cat
    assert all(c.prior_turns for c in by_cat["followup"])


def test_criterion_4_smoke_set_asserts_the_brief_tools_offline(tmp_path: Path, monkeypatch):
    smoke = {c.question: c for c in load_cases(ROOT / "evals" / "smoke.yaml")}
    assert {t for q in prompts.EXAMPLE_QUESTIONS for t in smoke[q].tools} == BRIEF_TOOLS
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    result = CliRunner().invoke(cli_module.cli, ["eval", "--test", "--tag", "smoke", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output


def test_criterion_5_baseline_report_passes_with_grounding_and_metadata():
    r = _report("v6-baseline")
    assert r["exit_code"] in (0, 2) and r["repeat"] >= 2 and not any(not c["passed"] and not c["flaky"] for c in r["cases"])
    assert len(r["cases"]) >= 30
    assert r["prompt_version"] == prompts.PROMPT_VERSION and r["config_version"] and r["total_cost_usd"] > 0
    assert r["ungrounded_runs"] <= 2 and "cache_share" in r and r["latency_p95_ms"] > 0
    assert r["models"][0] == "anthropic:claude-sonnet-5-5"


def test_criterion_6_anthropic_down_report_is_served_by_gemini():
    r = _report("v6-anthropic-down")
    assert any("simulated outage: anthropic" in n for n in r["notes"]) and not any(m.startswith("anthropic") for m in r["models"])
    answered = [run for c in r["cases"] for run in c["runs"] if run["status"] in ("answered", "cannot_answer")]
    assert answered and all(run["served_by"].startswith("gemini") for run in answered)
    assert sum(c["passed"] for c in r["cases"]) >= len(r["cases"]) * 0.8


def test_criterion_7_readme_lists_both_reports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    base, down = _report("v6-baseline"), _report("v6-anthropic-down")
    for tag, r in (("v6-baseline", base), ("v6-anthropic-down", down)):
        assert f"`evals/results/{tag}`" in readme, tag
        passed = sum(c["passed"] for c in r["cases"])
        assert f"{passed}/{len(r['cases'])}" in readme, tag
    roadmap = (ROOT / "agent-os" / "product" / "roadmap.md").read_text(encoding="utf-8")
    assert "**v3 agent**" in roadmap


async def test_criterion_8_repeated_tool_call_returns_repeated_instead_of_rerunning(config, prices, budget, caplog):
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agent.core import Conversation, Service, build_agent, tool_call_trace
    from app.agent.tools import ToolContext
    from tests.fakes import USAGE, final, screening_model

    calls = {"n": 0}

    def repeating(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] <= 3:
            return ModelResponse(parts=[ToolCallPart("list_airports", {"area": "New England"})], usage=USAGE, model_name="rep")
        return final({"status": "answered", "answer": "ok", "sources": [], "limitations": []}, model_name="rep")

    from app.data.registry import AirportRegistry

    deps = ToolContext(product_name="t", registry=AirportRegistry.load())
    from app.decide.guard import Guard

    svc = Service(build_agent(FunctionModel(repeating, model_name="rep")), Guard(screening_model()), budget, config.limits, prices, deps)
    conv = Conversation(max_turns=5)
    turn = await svc.ask(conv, "Which airports do you cover in New England?")
    returns = [p for m in conv.history for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "list_airports"]
    assert turn.status == "answered" and len(returns) == 3
    assert "BOS" in str(returns[0].content) and "Repeated" in type(returns[1].content).__name__ and "already" in str(returns[2].content)
    assert tool_call_trace(conv.history) == ["list_airports{'area': 'New England'}"] * 3


async def test_criterion_9_per_tool_ceiling_and_bad_year_returns_latest(config, prices, budget):
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agent.core import Conversation, Service, build_agent
    from app.agent.tools import ToolContext
    from app.data.registry import AirportRegistry
    from app.decide.guard import Guard
    from tests.fakes import USAGE, final, screening_model

    n = {"calls": 0}

    def exploring(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:  # different args every time, like the captured loop
        n["calls"] += 1
        if n["calls"] <= 6:
            return ModelResponse(parts=[ToolCallPart("list_airports", {"area": ["New England", "West", "CA", "TX", "FL", "MA"][n["calls"] - 1]})], usage=USAGE, model_name="x")
        return final({"status": "answered", "answer": "ok", "sources": [], "limitations": []}, model_name="x")

    deps = ToolContext(product_name="t", registry=AirportRegistry.load(), max_calls_per_tool=4)
    svc = Service(build_agent(FunctionModel(exploring, model_name="x")), Guard(screening_model()), budget, config.limits, prices, deps)
    conv = Conversation(max_turns=5)
    turn = await svc.ask(conv, "Which airports do you cover?")
    returns = [p.content for m in conv.history for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "list_airports"]
    assert turn.status == "answered" and len(returns) == 6
    assert all(type(r).__name__ == "AirportList" for r in returns[:4]) and all("answer now" in str(r) for r in returns[4:])
    assert config.limits.max_calls_per_tool_per_turn == 4


async def test_criterion_10_guard_down_and_guard_fields_and_guard_set(config, prices, budget, tmp_path: Path, monkeypatch):
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agent.core import Conversation, Service, build_agent
    from app.agent.tools import ToolContext
    from app.config import Price
    from app.decide.guard import Guard, build_guard_model
    from app.llm.budget import estimate_cost
    from tests.fakes import USAGE, answer_model, screening_model

    def unsure(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("final_result", {"in_scope": True, "injection": False})], usage=USAGE, model_name="jev-1.14.0",
                             provider_details={"confidence": {"in_scope": 0.4, "injection": 0.95}})

    haiku = screening_model(model_name="claude-haiku-5-5")
    guard = Guard(build_guard_model(FunctionModel(unsure, model_name="jev-1.14.0"), haiku, 0.7))
    svc = Service(build_agent(answer_model("ok")), guard, budget, config.limits, prices, ToolContext(product_name="t"))
    turn = await svc.ask(Conversation(max_turns=5), "Which airport is most congested?")
    assert turn.guard_model == "claude-haiku-5-5" and turn.guard_fell_through and turn.guard_cost_usd > 0 and turn.guard_latency_ms >= 0
    sure = FunctionModel(lambda m, i: ModelResponse(parts=[ToolCallPart("final_result", {"in_scope": False, "injection": False})], usage=USAGE, model_name="jev-1.14.0",
                                                     provider_details={"confidence": {"in_scope": 0.9, "injection": 0.8}}), model_name="jev-1.14.0")
    svc = Service(build_agent(answer_model("never")), Guard(FallbackModel(sure, haiku)), budget, config.limits, prices, ToolContext(product_name="t"))
    turn = await svc.ask(Conversation(max_turns=5), "write a poem")
    assert turn.status == "refused_off_topic" and turn.guard_model == "jev-1.14.0" and turn.guard_confidence == 0.8 and not turn.guard_fell_through
    assert estimate_cost({"jev-latest": Price(input=0.5, output=0)}, "jev-1.14.0", 1_000_000, 0) == pytest.approx(0.5)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-test")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")
    assert cli_module.compose(down=["typesafe"]).guard_name == "anthropic:claude-haiku-5-5"
    assert cli_module.compose().guard_name.startswith("typesafe:jev-latest")
    cases = load_cases(ROOT / "evals" / "guard.yaml")
    assert len(cases) == 16 and sorted(c.category for c in cases).count("in_scope") == 4
    assert {c.question for c in cases if c.category == "in_scope"} == set(prompts.EXAMPLE_QUESTIONS)
    assert {c.category for c in cases} == {"in_scope", "off_topic", "injection", "false_positive"}
